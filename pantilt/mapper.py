"""
Enclosure mapping, position logging, and visualisation.

Coordinate system
-----------------
The L-shaped enclosure is described in a 2-D coordinate space measured in
inches with the inside corner of the L at the origin (0, 0):

        Y
        ▲
  leg1  │  (vertical leg)  25" wide, 96" tall
        │  ╔═══════╗
        │  ║       ║
   96"  │  ║  leg1 ║
        │  ║       ║
    25" │  ╠═══════╬════════════════╗  ← where the two legs meet
     0" │  ╚═══════╩════════════════╝
        └──────────────────────────────► X
           0"    25"               85"
                        leg2 (60" long, 25" tall)

Valid positions satisfy:
  (0 ≤ x ≤ 25 AND 0 ≤ y ≤ 96)  ← vertical leg
  OR
  (0 ≤ x ≤ 60 AND 0 ≤ y ≤ 25) ← horizontal leg

Pan/tilt → enclosure mapping
-----------------------------
A simple ray-cast from the camera mount position is used.  The camera is
assumed to be mounted above and slightly outside the enclosure looking in.
At calibrated centre (pan=0, tilt=0) the ray hits a reference point.
Pan/tilt step offsets rotate the ray; the intersection with the floor
(z=0 plane) gives the estimated tortoise position.

If scipy is installed the occupancy heatmap is Gaussian-blurred; otherwise
the raw grid is used.
"""

import csv
import logging
import math
from datetime import datetime
from pathlib import Path

import matplotlib
matplotlib.use("Agg")   # non-interactive – no display required
import matplotlib.patches as patches
import matplotlib.pyplot as plt
import numpy as np

logger = logging.getLogger(__name__)

try:
    from scipy.ndimage import gaussian_filter as _gauss  # type: ignore[import]
    _SCIPY = True
except ImportError:
    _SCIPY = False

# CSV header
_CSV_HEADER = ["timestamp", "x_in", "y_in", "pan_steps", "tilt_steps", "confidence"]


def in_lshape(x: float, y: float,
              width: float, leg1: float, leg2: float) -> bool:
    """Return True if (x, y) lies inside the L-shaped enclosure."""
    in_vert = (0 <= x <= width) and (0 <= y <= leg1)
    in_horiz = (0 <= x <= leg2) and (0 <= y <= width)
    return in_vert or in_horiz


class EnclosureMapper:
    """
    Converts pan/tilt step positions to 2-D enclosure coordinates (inches),
    logs every position to a CSV file, and generates path-plot / heatmap PNGs.

    Parameters
    ----------
    config : pantilt.config.Config
    """

    def __init__(self, config):
        map_cfg = config["mapping"]
        log_cfg = config["logging"]

        self._pan_spd: float = float(config["pan"].get("steps_per_degree", 11.38))
        self._tilt_spd: float = float(config["tilt"].get("steps_per_degree", 11.38))
        self._pan_fov: float = float(map_cfg.get("pan_fov_deg", 62.2))
        self._tilt_fov: float = float(map_cfg.get("tilt_fov_deg", 48.8))

        self.width: float = float(map_cfg.get("enclosure_width_in", 25))
        self.leg1: float = float(map_cfg.get("enclosure_leg1_in", 96))
        self.leg2: float = float(map_cfg.get("enclosure_leg2_in", 60))

        self._cam_x: float = float(map_cfg.get("camera_x_in", self.width / 2))
        self._cam_y: float = float(map_cfg.get("camera_y_in", -12.0))
        self._cam_h: float = float(map_cfg.get("camera_height_in", 36.0))

        # Optional linear-scale overrides set during calibration.
        # If present they must be numeric; invalid values fall back to None
        # so the geometric ray-cast is used instead.
        def _as_float_or_none(val):
            if val is None:
                return None
            try:
                return float(val)
            except (TypeError, ValueError):
                logger.warning("Invalid inches_per_step value %r – using auto.", val)
                return None

        self._pan_ipc: float | None = _as_float_or_none(map_cfg.get("pan_inches_per_step"))
        self._tilt_ipc: float | None = _as_float_or_none(map_cfg.get("tilt_inches_per_step"))

        # Log path setup
        log_dir = Path(log_cfg.get("log_dir", "logs"))
        log_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = log_dir / log_cfg.get("log_file", "track_log.csv")
        self._init_csv()

        # In-memory track for plotting
        self._track: list[tuple[float, float]] = []

    # ── Coordinate conversion ─────────────────────────────────────────────────

    def pan_tilt_to_enclosure(
        self, pan_steps: int, tilt_steps: int
    ) -> tuple[float | None, float | None]:
        """
        Convert pan/tilt step counts (relative to calibrated centre) to
        approximate enclosure (x, y) in inches.

        If calibrated linear scale factors (inches_per_step) are available
        they are used directly.  Otherwise a ray-cast from the camera mount
        position is computed.
        """
        if self._pan_ipc is not None and self._tilt_ipc is not None:
            # Fast linear path (used after calibration)
            x = self._cam_x + pan_steps * self._pan_ipc
            y = self._cam_y + tilt_steps * self._tilt_ipc
            return round(x, 1), round(y, 1)

        # Geometric ray-cast
        pan_deg = pan_steps / self._pan_spd
        tilt_deg = tilt_steps / self._tilt_spd

        pan_rad = math.radians(pan_deg)
        tilt_rad = math.radians(tilt_deg)

        # Camera ray direction (using a downward-looking frame):
        #   at tilt=0 the camera looks horizontally; positive tilt = look down.
        # We need the camera to look *downward* by default.  We add a constant
        # depression angle estimated from camera height / enclosure distance.
        try:
            base_depression = math.atan2(
                self._cam_h, max(abs(self._cam_y) + self.leg1 / 2, 1)
            )
        except ZeroDivisionError:
            base_depression = math.radians(30)

        effective_tilt_rad = tilt_rad + base_depression

        cos_t = math.cos(effective_tilt_rad)
        if abs(cos_t) < 1e-6:
            return None, None

        # Ground distance along the ray.
        # When the ray points upward (sin ≤ 0) it never intersects the floor;
        # cap at the maximum enclosure diagonal as a safe fallback.
        _MAX_GROUND_DIST = math.sqrt(self.leg1 ** 2 + self.leg2 ** 2)
        ground_dist = self._cam_h / math.tan(effective_tilt_rad) \
            if math.sin(effective_tilt_rad) > 0 else _MAX_GROUND_DIST

        x = self._cam_x + ground_dist * math.sin(pan_rad)
        y = self._cam_y + ground_dist * math.cos(pan_rad)
        return round(x, 1), round(y, 1)

    # ── Logging ───────────────────────────────────────────────────────────────

    def log(self, pan_steps: int, tilt_steps: int, confidence: float):
        """
        Compute enclosure position for the current pan/tilt, validate it
        against the L-shape mask, append to CSV log, and accumulate for
        plotting.

        Returns (x, y, valid) where *valid* is True when the point lies
        inside the enclosure.
        """
        x, y = self.pan_tilt_to_enclosure(pan_steps, tilt_steps)
        ts = datetime.now().isoformat(timespec="seconds")

        valid = False
        if x is not None and y is not None:
            valid = in_lshape(x, y, self.width, self.leg1, self.leg2)
            if valid:
                self._track.append((x, y))

        with open(self.log_path, "a", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow([
                ts,
                "" if x is None else x,
                "" if y is None else y,
                pan_steps,
                tilt_steps,
                f"{confidence:.3f}",
            ])

        return x, y, valid

    # ── Visualisation ─────────────────────────────────────────────────────────

    def save_plots(self, output_dir: str = "logs") -> None:
        """Generate and save path plot and occupancy heatmap to *output_dir*."""
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        self._save_path_plot(out / "path_plot.png")
        self._save_heatmap(out / "heatmap.png")

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _init_csv(self) -> None:
        if not self.log_path.exists():
            with open(self.log_path, "w", newline="") as fh:
                csv.writer(fh).writerow(_CSV_HEADER)

    def _draw_enclosure(self, ax) -> None:
        """Draw the L-shaped enclosure outline on a matplotlib Axes."""
        w, l1, l2 = self.width, self.leg1, self.leg2
        # Vertical leg (full height)
        ax.add_patch(patches.Rectangle(
            (0, 0), w, l1,
            linewidth=1.5, edgecolor="black", facecolor="none",
        ))
        # Horizontal leg (bottom of L)
        ax.add_patch(patches.Rectangle(
            (0, 0), l2, w,
            linewidth=1.5, edgecolor="navy", facecolor="lightsteelblue", alpha=0.25,
        ))

    def _save_path_plot(self, path: Path) -> None:
        fig, ax = plt.subplots(figsize=(6, 10))
        self._draw_enclosure(ax)
        if self._track:
            xs, ys = zip(*self._track)
            ax.plot(xs, ys, "b-", linewidth=0.8, alpha=0.7, label="path")
            ax.plot(xs[0], ys[0], "go", markersize=8, label="start")
            ax.plot(xs[-1], ys[-1], "ro", markersize=8, label="end")
            ax.legend(loc="upper right", fontsize=8)
        ax.set_xlim(-2, max(self.leg2, self.width) + 5)
        ax.set_ylim(-5, self.leg1 + 5)
        ax.set_xlabel("X (inches)")
        ax.set_ylabel("Y (inches)")
        ax.set_title("Tortoise Path Track")
        ax.set_aspect("equal", "box")
        fig.tight_layout()
        fig.savefig(path, dpi=100)
        plt.close(fig)
        logger.info("Path plot saved → %s", path)

    def _save_heatmap(self, path: Path) -> None:
        grid_w = int(max(self.leg2, self.width)) + 2
        grid_h = int(self.leg1) + 2
        grid = np.zeros((grid_h, grid_w), dtype=float)

        for x, y in self._track:
            xi = int(round(x))
            yi = int(round(y))
            if 0 <= xi < grid_w and 0 <= yi < grid_h:
                grid[yi, xi] += 1.0

        if _SCIPY and grid.max() > 0:
            grid = _gauss(grid, sigma=3)

        fig, ax = plt.subplots(figsize=(6, 10))
        im = ax.imshow(
            grid,
            origin="lower",
            extent=[0, grid_w, 0, grid_h],
            cmap="hot",
            aspect="equal",
            vmin=0,
        )
        self._draw_enclosure(ax)
        fig.colorbar(im, ax=ax, label="Visit frequency")
        ax.set_xlabel("X (inches)")
        ax.set_ylabel("Y (inches)")
        ax.set_title("Tortoise Occupancy Heatmap")
        fig.tight_layout()
        fig.savefig(path, dpi=100)
        plt.close(fig)
        logger.info("Heatmap saved → %s", path)
