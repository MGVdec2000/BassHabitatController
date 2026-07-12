#!/usr/bin/env python3
"""Control selected Raspberry Pi GPIO pins from the command line.

Supported BCM pins: 17, 18, 22, 27

Examples:
  python gpio_pin_control.py on
  python gpio_pin_control.py off 17 27
"""

from __future__ import annotations

import argparse

ALLOWED_PINS = (17, 18, 22, 27)

try:
    import lgpio  # type: ignore[import]
    LGPIO_AVAILABLE = True
except ImportError:
    lgpio = None  # type: ignore[assignment]
    LGPIO_AVAILABLE = False

try:
    import RPi.GPIO as GPIO  # type: ignore[import]
    GPIO_AVAILABLE = True
except ImportError:
    from pantilt import _gpio_mock as GPIO  # type: ignore[no-redef]
    GPIO_AVAILABLE = False


def _set_pins_with_lgpio(pins: list[int], output_value: int) -> None:
    if not LGPIO_AVAILABLE:
        raise RuntimeError("lgpio is not available")

    handle = lgpio.gpiochip_open(0)
    if handle < 0:
        raise RuntimeError(f"Could not open gpiochip0 (code {handle})")

    try:
        for pin in pins:
            # Some lgpio builds expose 3-arg claim, others expose 4-arg claim.
            try:
                rc = lgpio.gpio_claim_output(handle, pin, output_value)
            except TypeError:
                rc = lgpio.gpio_claim_output(handle, pin, output_value, 0)

            if rc < 0:
                raise RuntimeError(f"Failed to claim GPIO {pin} (code {rc})")
    finally:
        lgpio.gpiochip_close(handle)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Turn GPIO pins 17, 18, 22, and 27 on or off (BCM numbering)."
    )
    parser.add_argument(
        "state",
        choices=("on", "off"),
        help="Desired output state.",
    )
    parser.add_argument(
        "pins",
        nargs="*",
        type=int,
        choices=ALLOWED_PINS,
        default=None,
        help="Pins to control. If omitted, all supported pins are used.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    pins = args.pins if args.pins else list(ALLOWED_PINS)

    high = getattr(GPIO, "HIGH", 1)
    low = getattr(GPIO, "LOW", 0)
    output_value = high if args.state == "on" else low

    used_lgpio_fallback = False

    try:
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)

        for pin in pins:
            GPIO.setup(pin, GPIO.OUT)
            GPIO.output(pin, output_value)
    except RuntimeError as exc:
        message = str(exc)
        if "SOC peripheral base address" in message:
            try:
                _set_pins_with_lgpio(pins, output_value)
                used_lgpio_fallback = True
            except RuntimeError as fallback_exc:
                print(
                    "GPIO backend is unavailable on this setup. "
                    "On Raspberry Pi 5, install the lgpio compatibility stack "
                    "(python3-rpi-lgpio) or use rpi-lgpio in your environment."
                )
                print(f"Fallback error: {fallback_exc}")
                return 2
        else:
            print(f"GPIO runtime error: {message}")
            return 2

    state_label = "ON" if args.state == "on" else "OFF"
    print(f"Set pins {', '.join(map(str, pins))} to {state_label}.")

    if used_lgpio_fallback:
        print("Used lgpio fallback backend for pin control.")

    if not GPIO_AVAILABLE:
        print("RPi.GPIO not found: running in mock mode (no physical GPIO changed).")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
