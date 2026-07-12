from datetime import datetime

from shelly_plug import ShellyPlug
from environment_schedule import EnvironmentSchedule
from utils import between_two_times


class HumidityController:
    """Controls a Shelly-plug-driven humidifier/mister on a repeating cycle.

    The mister runs for `on_minutes` at the start of every `cycle_interval_minutes`
    window (measured from Unix epoch). When `only_during_daylight` is True, the
    mister is forced off outside of the lighting schedule.

    Example: on_minutes=2, cycle_interval_minutes=60 — mister runs for the first
    2 minutes of every hour, but only while the lights are on.
    """

    def __init__(
        self,
        plugs: dict[str, ShellyPlug],
        schedule: EnvironmentSchedule,
        on_minutes: float = 2.0,
        cycle_interval_minutes: float = 60.0,
        only_during_daylight: bool = True,
    ):
        self.plugs = plugs
        self.schedule = schedule
        self.on_minutes = on_minutes
        self.cycle_interval_minutes = cycle_interval_minutes
        self.only_during_daylight = only_during_daylight

    def _should_mist(self, now: datetime) -> bool:
        if self.only_during_daylight:
            if not between_two_times(now, self.schedule.lights_on, self.schedule.lights_off):
                return False
        minutes_since_epoch = now.timestamp() / 60.0
        position_in_cycle = minutes_since_epoch % self.cycle_interval_minutes
        return position_in_cycle < self.on_minutes

    def update(self, now: datetime) -> None:
        misting = self._should_mist(now)
        for plug in self.plugs.values():
            plug.set_on(misting)
