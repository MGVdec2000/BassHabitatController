"""
Stepper motor driver for 28BYJ-48 motors with ULN2003 driver boards.

Uses the 8-step half-step sequence for smooth, high-resolution motion.
The 28BYJ-48 has 64 internal steps × 64:1 gear = 4096 half-steps per
revolution → ~11.38 half-steps per degree.

GPIO is imported at module load; if RPi.GPIO is unavailable (non-Pi
development machine) the bundled mock is used so the rest of the code
runs without modification.
"""

import logging
import time

logger = logging.getLogger(__name__)

try:
    import RPi.GPIO as GPIO  # type: ignore[import]
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)
    _GPIO_AVAILABLE = True
    logger.debug("RPi.GPIO loaded successfully.")
except ImportError:
    from pantilt import _gpio_mock as GPIO  # type: ignore[no-redef]
    _GPIO_AVAILABLE = False
    logger.warning(
        "RPi.GPIO not available – running in GPIO simulation mode. "
        "Motor movements will be counted but no pins will be driven."
    )

# 28BYJ-48 half-step sequence (8 phases × 4 coils)
_HALF_STEP: list[list[int]] = [
    [1, 0, 0, 0],
    [1, 1, 0, 0],
    [0, 1, 0, 0],
    [0, 1, 1, 0],
    [0, 0, 1, 0],
    [0, 0, 1, 1],
    [0, 0, 0, 1],
    [1, 0, 0, 1],
]

_SEQ_LEN = len(_HALF_STEP)  # 8

# Default delay between half-steps: 2 ms → ~500 Hz, comfortably within
# 28BYJ-48 safe speed; reduce carefully if you need faster slew.
_DEFAULT_STEP_DELAY = 0.002


class StepperMotor:
    """
    Controls a single 28BYJ-48 stepper via a ULN2003 board using the
    8-phase half-step sequence.

    Parameters
    ----------
    pins        : list of 4 BCM GPIO numbers [IN1, IN2, IN3, IN4]
    min_steps   : lower software travel limit (inclusive)
    max_steps   : upper software travel limit (inclusive)
    direction   : +1 (default) or -1 to reverse the motor sense
    step_delay  : seconds between half-steps (default 2 ms)
    """

    def __init__(
        self,
        pins: list,
        min_steps: int,
        max_steps: int,
        direction: int = 1,
        step_delay: float = _DEFAULT_STEP_DELAY,
    ):
        if len(pins) != 4:
            raise ValueError("pins must be a list of exactly 4 BCM GPIO numbers.")
        self.pins = list(pins)
        self.min_steps = min_steps
        self.max_steps = max_steps
        self.direction = int(direction)
        self.step_delay = step_delay

        self._seq_index: int = 0   # current half-step sequence index [0-7]
        self._position: int = 0    # cumulative step count from origin

        if _GPIO_AVAILABLE:
            for pin in self.pins:
                GPIO.setup(pin, GPIO.OUT)
                GPIO.output(pin, 0)

    # ── Public interface ────────────────────────────────────────────────────

    def step(self, n_steps: int) -> int:
        """
        Move *n_steps* half-steps (positive = forward, negative = backward).

        Stops early if a travel limit is reached.  Returns the signed number
        of steps actually taken.
        """
        if n_steps == 0:
            return 0

        sign = 1 if n_steps > 0 else -1
        effective_dir = sign * self.direction
        taken = 0

        for _ in range(abs(n_steps)):
            new_pos = self._position + sign
            if new_pos < self.min_steps or new_pos > self.max_steps:
                logger.debug(
                    "Travel limit reached at position %d (limit %d..%d).",
                    self._position, self.min_steps, self.max_steps,
                )
                break
            self._seq_index = (self._seq_index + effective_dir) % _SEQ_LEN
            self._apply()
            self._position = new_pos
            taken += 1
            time.sleep(self.step_delay)

        return taken * sign

    def de_energize(self) -> None:
        """Drive all coil outputs low to stop holding current and reduce heat."""
        if _GPIO_AVAILABLE:
            for pin in self.pins:
                GPIO.output(pin, 0)

    def reset_position(self) -> None:
        """Mark the current physical position as step 0 (new home / centre)."""
        self._position = 0

    # ── Properties ──────────────────────────────────────────────────────────

    @property
    def position(self) -> int:
        return self._position

    # ── Internal ────────────────────────────────────────────────────────────

    def _apply(self) -> None:
        """Write the current half-step phase to the GPIO pins."""
        phase = _HALF_STEP[self._seq_index]
        if _GPIO_AVAILABLE:
            for pin, val in zip(self.pins, phase):
                GPIO.output(pin, val)

    def cleanup(self) -> None:
        self.de_energize()
