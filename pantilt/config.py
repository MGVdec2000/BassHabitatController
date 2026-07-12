"""
Configuration management for the pan/tilt tortoise tracker.

Settings are stored in a JSON file (default: config.json in the project root).
If no file exists the built-in defaults are used so the system is runnable
without any setup step.

Default GPIO pin assignments (BCM numbering, Raspberry Pi 5):
  Pan  motor (28BYJ-48 / ULN2003): IN1=17, IN2=18, IN3=27, IN4=22
  Tilt motor (28BYJ-48 / ULN2003): IN1=23, IN2=24, IN3=25, IN4=4

These pins are safe, common GPIO outputs on Pi 5 that avoid
hardware-special functions (SPI, I2C, UART, PWM on 12/13/18/19).
Override any value via the config file.
"""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = Path(__file__).parent.parent / "config.json"

DEFAULT_CONFIG: dict = {
    # ── Pan axis ────────────────────────────────────────────────────────────
    "pan": {
        "pins": [17, 18, 27, 22],    # BCM: IN1, IN2, IN3, IN4
        "min_steps": -1024,            # 90 degrees software travel limit (negative = left)
        "max_steps": 1024,             # 90 degrees software travel limit (positive = right)
        "direction": 1,               # 1 or -1 to flip motor direction
        "steps_per_degree": 11.38,    # 28BYJ-48: 4096 half-steps / 360°
    },
    # ── Tilt axis ───────────────────────────────────────────────────────────
    "tilt": {
        "pins": [23, 24, 25, 4],     # BCM: IN1, IN2, IN3, IN4
        "min_steps": -200,
        "max_steps": 200,
        "direction": 1,
        "steps_per_degree": 11.38,
    },
    # ── Camera ──────────────────────────────────────────────────────────────
    "camera": {
        "index": 0,     # V4L2 device index (Arducam IMX477 is usually /dev/video0)
        "width": 640,
        "height": 480,
        "fps": 15,
    },
    # ── Tracking / control ──────────────────────────────────────────────────
    "tracking": {
        "deadband_px": 20,           # pixel error below which no step is issued
        "max_step_per_frame": 8,     # rate-limit: max steps per frame per axis
        "confidence_threshold": 0.3, # minimum detection confidence to act on
    },
    # ── Enclosure mapping ───────────────────────────────────────────────────
    "mapping": {
        "pan_fov_deg": 62.2,          # Arducam IMX477 approximate HFOV
        "tilt_fov_deg": 48.8,         # Arducam IMX477 approximate VFOV
        "enclosure_width_in": 25,     # corridor width (both legs)
        "enclosure_short_leg_in": 60, # short leg length (5 ft, vertical)
        "enclosure_long_leg_in": 96,  # long leg length  (8 ft, horizontal)
        # Camera mount position in enclosure coordinate space (inches).
        # The coordinate origin is the inside corner of the L-shape.
        "camera_x_in": 12.5,          # centred on the width of leg 1
        "camera_y_in": -12.0,         # 12 in outside/behind the enclosure
        "camera_height_in": 36.0,     # camera height above enclosure floor
        "pan_inches_per_step": None,  # auto-computed if None
        "tilt_inches_per_step": None, # auto-computed if None
    },
    # ── Logging / output ────────────────────────────────────────────────────
    "logging": {
        "log_dir": "logs",
        "log_file": "track_log.csv",
    },
}


class Config:
    """Thin wrapper around a JSON config dict with load/save helpers."""

    def __init__(self, path=None):
        self.path = Path(path) if path else DEFAULT_CONFIG_PATH
        self._data: dict = {}
        self.load()

    # ── Persistence ─────────────────────────────────────────────────────────

    def load(self) -> None:
        if self.path.exists():
            try:
                with open(self.path) as fh:
                    loaded = json.load(fh)
                self._data = _deep_merge(
                    json.loads(json.dumps(DEFAULT_CONFIG)), loaded
                )
                logger.info("Config loaded from %s", self.path)
            except Exception as exc:
                logger.warning("Could not load config (%s) – using defaults.", exc)
                self._data = json.loads(json.dumps(DEFAULT_CONFIG))
        else:
            self._data = json.loads(json.dumps(DEFAULT_CONFIG))
            logger.info("No config file found at %s – using defaults.", self.path)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "w") as fh:
            json.dump(self._data, fh, indent=2)
        logger.info("Config saved to %s", self.path)

    # ── Accessors ────────────────────────────────────────────────────────────

    def get(self, *keys, default=None):
        """Nested key access: config.get('pan', 'pins')."""
        node = self._data
        for k in keys:
            if not isinstance(node, dict) or k not in node:
                return default
            node = node[k]
        return node

    def set(self, *keys_and_value) -> None:
        """Nested key setter: config.set('pan', 'direction', -1)."""
        *keys, value = keys_and_value
        node = self._data
        for k in keys[:-1]:
            node = node.setdefault(k, {})
        node[keys[-1]] = value

    def __getitem__(self, key):
        return self._data[key]

    def __setitem__(self, key, value) -> None:
        self._data[key] = value


# ── Helpers ─────────────────────────────────────────────────────────────────

def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge *override* into *base* (override wins on conflicts)."""
    result = dict(base)
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result
