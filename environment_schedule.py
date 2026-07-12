from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sun_schedule import SunSchedule
from utils import get_timestamp


def apply_minimum_daylight(
    sun_schedule: SunSchedule,
    minimum_hours: float,
) -> tuple[datetime, datetime]:
    minimum = timedelta(hours=minimum_hours)
    with sun_schedule.lock:
        natural = sun_schedule.sunset - sun_schedule.sunrise
        if natural >= minimum:
            return sun_schedule.sunrise, sun_schedule.sunset
        extension = minimum - natural
        half_extension = extension / 2
        return sun_schedule.sunrise - half_extension, sun_schedule.sunset + half_extension


@dataclass
class EnvironmentSchedule:
    minimum_hours: float
    sun_schedule: SunSchedule
    lights_on: datetime = field(default=datetime.min, init=False)
    lights_off: datetime = field(default=datetime.max, init=False)
    heaters_on: datetime = field(default=datetime.min, init=False)
    heaters_off: datetime = field(default=datetime.max, init=False)

    def __post_init__(self):
        if self.minimum_hours <= 0:
            raise ValueError("Minimum hours must be positive")
        self.update()

    def update(self):
        self.lights_on, self.lights_off = apply_minimum_daylight(self.sun_schedule, self.minimum_hours)
        self.heaters_on = self.lights_off - timedelta(minutes=2)
        self.heaters_off = self.lights_on + timedelta(minutes=2)

        total_hours = (self.lights_off - self.lights_on).total_seconds() / 3600
        on_s = self.lights_on.astimezone(self.sun_schedule.timezone).strftime('%Y-%m-%d %H:%M:%S')
        off_s = self.lights_off.astimezone(self.sun_schedule.timezone).strftime('%H:%M:%S')
        print(f"{get_timestamp()}Lighting schedule updated ({on_s} / {off_s}, {total_hours:.1f} / {self.minimum_hours:.0f} hrs)")

        on_s = self.heaters_on.astimezone(self.sun_schedule.timezone).strftime('%H:%M:%S')
        off_s = self.heaters_off.astimezone(self.sun_schedule.timezone).strftime('%Y-%m-%d %H:%M:%S')
        print(f"{get_timestamp()}Heater schedule updated ({off_s} / {on_s})")
