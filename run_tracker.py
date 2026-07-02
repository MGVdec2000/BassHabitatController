#!/usr/bin/env python3
"""
run_tracker.py – Main entrypoint for the tortoise pan/tilt tracking loop.

Usage
-----
  python run_tracker.py                    # headless (no display)
  python run_tracker.py --show             # show live video window
  python run_tracker.py --config my.json  # use alternate config file

Press Ctrl-C (or send SIGTERM) to stop gracefully.  Logs and plots are
written to the ``logs/`` directory (configurable in config.json).
"""

import argparse
import logging
import signal
import sys

import cv2  # noqa: E402 – imported after logging setup intentionally

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Tortoise pan/tilt tracker (Raspberry Pi 4 / 28BYJ-48)"
    )
    parser.add_argument(
        "--config", default="config.json",
        help="Path to JSON config file (default: config.json)",
    )
    parser.add_argument(
        "--show", action="store_true",
        help="Open a live video preview window (requires a connected display).",
    )
    args = parser.parse_args()

    # Late imports so the module-level logger is already configured
    from pantilt.config import Config
    from pantilt.pantilt_controller import PanTiltController
    from pantilt.tracker import TortoiseTracker
    from pantilt.mapper import EnclosureMapper

    config = Config(args.config)
    controller = PanTiltController(config)
    tracker = TortoiseTracker(config)
    mapper = EnclosureMapper(config)

    running = True

    def _stop(sig=None, frame=None) -> None:
        nonlocal running
        logger.info("Stop signal received – shutting down…")
        running = False

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    if not tracker.start():
        logger.error("Failed to open camera.  Check connection and config.")
        sys.exit(1)

    # Cumulative step positions (relative to calibrated centre)
    pan_pos = tilt_pos = 0
    frames_processed = 0

    logger.info(
        "Tracker running.  Frame=%dx%d @%dfps  deadband=%dpx  Press Ctrl-C to stop.",
        config["camera"]["width"], config["camera"]["height"],
        config["camera"]["fps"], config["tracking"]["deadband_px"],
    )

    try:
        while running:
            frame = tracker.read_frame()
            if frame is None:
                logger.warning("No frame received – retrying…")
                continue

            cx, cy, confidence, bbox = tracker.detect(frame)
            frames_processed += 1

            if cx is not None:
                dp, dt = controller.update(
                    cx, cy, frame.shape[1], frame.shape[0]
                )
                pan_pos += dp
                tilt_pos += dt
                mapper.log(pan_pos, tilt_pos, confidence)
                logger.debug(
                    "Centroid (%d,%d) conf=%.2f → Δpan=%+d Δtilt=%+d "
                    "pos=(%+d,%+d)",
                    cx, cy, confidence, dp, dt, pan_pos, tilt_pos,
                )

            if args.show:
                if cx is not None:
                    tracker.annotate_frame(frame, cx, cy, confidence, bbox)
                cv2.imshow("Tortoise Tracker – q to quit", frame)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break

    finally:
        tracker.stop()
        controller.shutdown()
        log_dir = config["logging"].get("log_dir", "logs")
        mapper.save_plots(log_dir)
        if args.show:
            try:
                cv2.destroyAllWindows()
            except Exception:
                pass
        logger.info(
            "Done.  Processed %d frames.  Logs and plots saved to '%s/'.",
            frames_processed, log_dir,
        )


if __name__ == "__main__":
    main()
