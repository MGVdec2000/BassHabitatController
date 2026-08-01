from datetime import datetime

from shelly_plug import ShellyPlug
from environment_schedule import EnvironmentSchedule
from utils import between_two_times, get_timestamp


class LightingController:
    """Controls lamp plugs based on the environment schedule."""

    def __init__(
            self,
            plugs: dict[str, ShellyPlug],
            schedule: EnvironmentSchedule,
            debug: bool = False
        ):
        self.plugs = plugs
        self.schedule = schedule
        self.debug = debug
        self.get_current_states()

    def get_current_states(self) -> None:
        for plug in self.plugs.values():
            state = plug.check_state()
            if state is None:
                continue
            switch = "ON" if state else "OFF"
            print(f"{get_timestamp()}{plug.name} is {switch}")

    def update(self, now: datetime) -> None:
        lights_on = between_two_times(now, self.schedule.lights_on, self.schedule.lights_off)
        for plug in self.plugs.values():
            plug.set_on(lights_on)
