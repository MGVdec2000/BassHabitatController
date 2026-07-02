"""
Minimal RPi.GPIO mock for running on non-Raspberry-Pi hardware (development/testing).
Provides the same interface used by stepper.py so imports don't fail.
"""
import logging

logger = logging.getLogger(__name__)

BCM = "BCM"
OUT = "OUT"
IN = "IN"


def setmode(mode):
    pass


def setwarnings(flag):
    pass


def setup(pin, mode):
    pass


def output(pin, value):
    pass


def input(pin):  # noqa: A001  (shadows built-in intentionally to match RPi.GPIO API)
    return 0


def cleanup():
    pass
