"""
Pan/tilt controller with deadband (jitter prevention) and rate-limited stepping.

The controller accepts a frame centroid (cx, cy) and frame dimensions, computes
the pixel error from the frame centre, applies a deadband zone, then converts
the residual error to motor steps (clamped to max_step_per_frame to rate-limit
sudden movements).
"""

import logging

from pantilt.stepper import StepperMotor

logger = logging.getLogger(__name__)


class PanTiltController:
    """
    Drives pan and tilt stepper motors to keep a detected target centred.

    Parameters
    ----------
    config : pantilt.config.Config
        Loaded configuration object.
    """

    def __init__(self, config):
        pan_cfg = config["pan"]
        tilt_cfg = config["tilt"]
        track_cfg = config["tracking"]

        self.pan = StepperMotor(
            pins=pan_cfg["pins"],
            min_steps=pan_cfg["min_steps"],
            max_steps=pan_cfg["max_steps"],
            direction=pan_cfg.get("direction", 1),
        )
        self.tilt = StepperMotor(
            pins=tilt_cfg["pins"],
            min_steps=tilt_cfg["min_steps"],
            max_steps=tilt_cfg["max_steps"],
            direction=tilt_cfg.get("direction", 1),
        )

        self.deadband_px: int = int(track_cfg.get("deadband_px", 20))
        self.max_step_per_frame: int = int(track_cfg.get("max_step_per_frame", 8))

        # Pixels-to-steps gain  (steps per pixel of error from frame centre).
        # Derived from steps/degree and a rough FOV estimate:
        #   gain = (steps_per_deg) / (frame_half_dimension_in_pixels_per_deg)
        # We compute lazily in update() once we know frame dimensions.
        self._pan_spd: float = float(pan_cfg.get("steps_per_degree", 11.38))
        self._tilt_spd: float = float(tilt_cfg.get("steps_per_degree", 11.38))
        self._pan_fov: float = float(config.get("mapping", "pan_fov_deg", default=62.2) or 62.2)
        self._tilt_fov: float = float(config.get("mapping", "tilt_fov_deg", default=48.8) or 48.8)

    # ── Control update ───────────────────────────────────────────────────────

    def update(self, cx: int, cy: int, frame_w: int, frame_h: int):
        """
        Compute and apply pan/tilt corrections for centroid (cx, cy).

        Returns
        -------
        (pan_steps, tilt_steps) : signed integers actually applied this frame.
        """
        err_x = cx - frame_w / 2.0
        err_y = cy - frame_h / 2.0

        pan_steps = 0
        tilt_steps = 0

        if abs(err_x) > self.deadband_px:
            # pixels-per-degree in horizontal axis
            px_per_deg_h = frame_w / self._pan_fov
            gain_h = self._pan_spd / px_per_deg_h
            raw = err_x * gain_h
            clamped = max(-self.max_step_per_frame,
                          min(self.max_step_per_frame, raw))
            pan_steps = self.pan.step(int(round(clamped)))

        if abs(err_y) > self.deadband_px:
            px_per_deg_v = frame_h / self._tilt_fov
            gain_v = self._tilt_spd / px_per_deg_v
            raw = err_y * gain_v
            clamped = max(-self.max_step_per_frame,
                          min(self.max_step_per_frame, raw))
            tilt_steps = self.tilt.step(int(round(clamped)))

        if pan_steps or tilt_steps:
            logger.debug(
                "err=(%.1f, %.1f)px → pan=%+d tilt=%+d steps | pos=(%+d, %+d)",
                err_x, err_y, pan_steps, tilt_steps,
                self.pan.position, self.tilt.position,
            )

        return pan_steps, tilt_steps

    # ── Manual jog (used by calibration CLI) ────────────────────────────────

    def jog_pan(self, steps: int) -> int:
        """Move pan axis by *steps* half-steps. Returns steps actually taken."""
        return self.pan.step(steps)

    def jog_tilt(self, steps: int) -> int:
        """Move tilt axis by *steps* half-steps. Returns steps actually taken."""
        return self.tilt.step(steps)

    def get_position(self) -> tuple:
        """Return (pan_position, tilt_position) in half-steps from home."""
        return self.pan.position, self.tilt.position

    # ── Shutdown ─────────────────────────────────────────────────────────────

    def shutdown(self) -> None:
        """De-energise both motors and release GPIO resources."""
        self.pan.de_energize()
        self.tilt.de_energize()
        try:
            import RPi.GPIO as GPIO  # type: ignore[import]
            GPIO.cleanup()
        except Exception:
            pass
        logger.info("Pan/tilt controller shut down cleanly.")
