#!/usr/bin/env python3
"""
calibrate.py – Interactive pan/tilt calibration utility.

Run this once (or whenever you change the physical rig) to set motor
directions, travel limits, centre position, and step-to-angle scaling.
All settings are saved to config.json and loaded automatically by
run_tracker.py.

Usage
-----
  python calibrate.py                    # use default config.json
  python calibrate.py --config my.json  # use alternate config file
"""

import argparse
import logging
import select
import sys
import termios
import tty

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

_DEFAULT_JOG_STEP = 5   # half-steps per key-press in jog mode


# ── Low-level keyboard helpers ───────────────────────────────────────────────

def _read_key(fd) -> str:
    """
    Read one key (or arrow-key escape sequence) from the raw file descriptor.
    Returns a single character or a 3-char sequence like '\\x1b[A'.
    """
    ch = sys.stdin.read(1)
    if ch == "\x1b":
        # Possible escape sequence – peek for up to 50 ms
        r, _, _ = select.select([sys.stdin], [], [], 0.05)
        if r:
            rest = sys.stdin.read(2)
            return ch + rest
    return ch


# ── Jog mode ─────────────────────────────────────────────────────────────────

def jog_mode(controller) -> None:
    """
    Let the user move the pan/tilt assembly with keyboard keys.

    Controls
    --------
    Arrow keys or WASD : move one jog-step in that direction
    +  / -             : increase / decrease jog step size
    0                  : reset position counters to zero (set new home)
    q  / Ctrl-C        : exit jog mode
    """
    jog_step = _DEFAULT_JOG_STEP
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)

    print("\n--- JOG MODE ---")
    print("  ↑ / W  = Tilt up      ↓ / S = Tilt down")
    print("  ← / A  = Pan left     → / D = Pan right")
    print("  + / -  = Change step size   0 = Reset home   q = Exit")

    try:
        tty.setraw(fd)
        while True:
            pan_pos, tilt_pos = controller.get_position()
            sys.stdout.write(
                f"\r  Pan={pan_pos:+6d}  Tilt={tilt_pos:+6d}  "
                f"Step={jog_step:2d}  "
            )
            sys.stdout.flush()

            key = _read_key(fd)

            if key in ("q", "Q", "\x03"):        # q or Ctrl-C
                break
            elif key in ("\x1b[D", "a", "A"):    # Left / A → pan left
                controller.jog_pan(-jog_step)
            elif key in ("\x1b[C", "d", "D"):    # Right / D → pan right
                controller.jog_pan(jog_step)
            elif key in ("\x1b[A", "w", "W"):    # Up / W → tilt up
                controller.jog_tilt(-jog_step)
            elif key in ("\x1b[B", "s", "S"):    # Down / S → tilt down
                controller.jog_tilt(jog_step)
            elif key == "+":
                jog_step = min(jog_step + 1, 40)
            elif key == "-":
                jog_step = max(jog_step - 1, 1)
            elif key == "0":
                controller.pan.reset_position()
                controller.tilt.reset_position()
                sys.stdout.write("\r  Position reset to 0,0.          \n")
                sys.stdout.flush()

    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
        controller.pan.de_energize()
        controller.tilt.de_energize()

    print("\nExited jog mode.")


# ── Calibration steps ────────────────────────────────────────────────────────

def set_center(controller) -> None:
    """Record current position as the home / centre and reset counters."""
    pan, tilt = controller.get_position()
    controller.pan.reset_position()
    controller.tilt.reset_position()
    print(f"\nCentre set (was pan={pan:+d}, tilt={tilt:+d}). Counters reset to 0.")


def set_axis_directions(controller, config) -> None:
    print("\n--- AXIS DIRECTIONS ---")
    for axis in ("pan", "tilt"):
        cur = config.get(axis, "direction") or 1
        ans = input(f"  Flip {axis.upper()} direction? Current = {cur:+d}  (y/n): ").strip().lower()
        if ans == "y":
            new_dir = -cur
            config.set(axis, "direction", new_dir)
            getattr(controller, axis).direction = new_dir
            print(f"  {axis.upper()} direction flipped to {new_dir:+d}.")
        else:
            print(f"  {axis.upper()} direction unchanged ({cur:+d}).")


def set_limits(controller, config) -> None:
    """Jog to each axis limit and record the step count as the software limit."""
    print("\n--- SET TRAVEL LIMITS ---")
    print("Jog each motor to its physical limit, then exit jog mode to record it.")
    print("Do NOT force past the physical stop – feel for resistance and stop just before.\n")

    for axis, label, is_min in [
        ("pan",  "PAN  minimum (left  limit)", True),
        ("pan",  "PAN  maximum (right limit)", False),
        ("tilt", "TILT minimum (up    limit)", True),
        ("tilt", "TILT maximum (down  limit)", False),
    ]:
        input(f"  → Press Enter to jog to {label}…")
        jog_mode(controller)
        pos = getattr(controller, axis).position
        key = "min_steps" if is_min else "max_steps"
        config.set(axis, key, pos)
        setattr(getattr(controller, axis), key, pos)
        print(f"  {label}: {pos:+d} steps recorded.\n")

    print("Travel limits saved.")


def set_step_scaling(config) -> None:
    """Configure steps-per-degree for both axes."""
    print("\n--- STEP SCALING ---")
    print("  28BYJ-48 default: 4096 half-steps / 360° = 11.38 steps/degree")
    print("  Measure by: jog 400 steps and measure degrees of rotation,")
    print("  then calculate: 400 / measured_degrees = steps_per_degree.")
    for axis in ("pan", "tilt"):
        cur = config.get(axis, "steps_per_degree") or 11.38
        raw = input(f"  {axis.upper()} steps/degree (Enter = keep {cur}): ").strip()
        if raw:
            try:
                config.set(axis, "steps_per_degree", float(raw))
                print(f"  {axis.upper()} steps/degree set to {float(raw)}.")
            except ValueError:
                print(f"  Invalid input – {axis.upper()} unchanged.")


def set_mapping_params(config) -> None:
    """Configure camera FOV, mount position, and optional linear scale factors."""
    print("\n--- MAPPING PARAMETERS ---")
    params = [
        ("mapping", "pan_fov_deg",          "Pan FOV (degrees)        ",   62.2),
        ("mapping", "tilt_fov_deg",         "Tilt FOV (degrees)       ",   48.8),
        ("mapping", "camera_height_in",     "Camera height (inches)   ",   36.0),
        ("mapping", "camera_x_in",          "Camera X pos (inches)    ",   12.5),
        ("mapping", "camera_y_in",          "Camera Y pos (inches)    ",  -12.0),
        ("mapping", "pan_inches_per_step",  "Pan  in/step (blank=auto)",    None),
        ("mapping", "tilt_inches_per_step", "Tilt in/step (blank=auto)",    None),
    ]
    for section, key, label, default in params:
        cur = config.get(section, key)
        if cur is None:
            prompt = f"  {label}: (Enter = auto) "
        else:
            prompt = f"  {label}: (Enter = keep {cur}) "
        raw = input(prompt).strip()
        if raw:
            try:
                config.set(section, key, float(raw))
            except ValueError:
                print("  Invalid – skipped.")


# ── Main menu ─────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Pan/tilt interactive calibration utility"
    )
    parser.add_argument(
        "--config", default="config.json",
        help="Path to JSON config file (default: config.json)",
    )
    args = parser.parse_args()

    from pantilt.config import Config
    from pantilt.pantilt_controller import PanTiltController

    config = Config(args.config)
    controller = PanTiltController(config)

    print("\n╔══════════════════════════════════════════╗")
    print("║  Pan/Tilt Calibration Utility            ║")
    print(f"║  Config: {str(config.path):<33}║")
    print("╚══════════════════════════════════════════╝")

    MENU = {
        "1": ("Jog motors (keyboard control)",          lambda: jog_mode(controller)),
        "2": ("Set centre (record as home)",            lambda: set_center(controller)),
        "3": ("Set axis directions (flip pan/tilt)",    lambda: set_axis_directions(controller, config)),
        "4": ("Set travel limits",                      lambda: set_limits(controller, config)),
        "5": ("Set step scaling (steps/degree)",        lambda: set_step_scaling(config)),
        "6": ("Set mapping parameters (FOV, position)", lambda: set_mapping_params(config)),
        "7": ("Save config and exit",                   None),
        "8": ("Exit WITHOUT saving",                    None),
    }

    try:
        while True:
            print("\n--- MAIN MENU ---")
            for k, (label, _) in MENU.items():
                print(f"  {k}) {label}")
            choice = input("Select option: ").strip()
            if choice not in MENU:
                print("  Unknown option – try again.")
                continue
            label, action = MENU[choice]
            if choice == "7":
                config.save()
                print(f"Config saved to {config.path}.")
                break
            elif choice == "8":
                print("Exiting without saving.")
                break
            else:
                action()
    finally:
        controller.shutdown()


if __name__ == "__main__":
    main()
