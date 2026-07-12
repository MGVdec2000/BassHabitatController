from datetime import datetime

from shelly_plug import ShellyPlug
from environment_schedule import EnvironmentSchedule
from utils import between_two_times


class LightingController:
    """Controls lamp plugs based on the environment schedule."""

    def __init__(self, plugs: dict[str, ShellyPlug], schedule: EnvironmentSchedule):
        self.plugs = plugs
        self.schedule = schedule

    def update(self, now: datetime) -> None:
        lights_on = between_two_times(now, self.schedule.lights_on, self.schedule.lights_off)
        for plug in self.plugs.values():
            plug.set_on(lights_on)
