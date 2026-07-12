from datetime import datetime

from shelly_plug import ShellyPlug
from environment_schedule import EnvironmentSchedule
from utils import before_or_after


class HeaterController:
    """Controls heater plugs based on the environment schedule.

    Heaters run outside the lighting window (overnight) to maintain temperature
    when the lights are off.
    """

    def __init__(self, plugs: dict[str, ShellyPlug], schedule: EnvironmentSchedule):
        self.plugs = plugs
        self.schedule = schedule

    def update(self, now: datetime) -> None:
        heaters_on = before_or_after(now, self.schedule.heaters_off, self.schedule.heaters_on)
        for plug in self.plugs.values():
            plug.set_on(heaters_on)
