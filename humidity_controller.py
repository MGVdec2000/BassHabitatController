from datetime import datetime, time, timedelta
from shelly_plug import ShellyPlug
from environment_schedule import EnvironmentSchedule
from utils import between_two_times, get_timestamp


class HumidityController:
    """Controls a Shelly-plug-driven humidifier/mister with multiple evenly-spaced misting periods.

    The mister runs for `on_minutes` at the start of each of `number_of_periods` windows,
    evenly distributed between (sunrise + sunrise_offset_minutes) and (sunset + sunset_offset_minutes).
    When `only_during_daylight` is True, the mister is forced off outside the lighting window.

    Example: number_of_periods=4, on_minutes=0.5, sunrise_offset_minutes=30, sunset_offset_minutes=-30
    — mister runs for 0.5 minutes at the start of each of 4 periods between sunrise+30min and sunset-30min.
    """

    def __init__(
        self,
        plugs: dict[str, ShellyPlug],
        schedule: EnvironmentSchedule,
        on_minutes: float = 0.5,
        number_of_periods: int = 4,
        sunrise_offset_minutes: float = 0.0,
        sunset_offset_minutes: float = 0.0,
        only_during_daylight: bool = True,
        debug: bool = False,
    ):
        self.plugs = plugs
        self.schedule = schedule
        self.on_minutes = on_minutes
        self.number_of_periods = number_of_periods
        self.sunrise_offset_minutes = sunrise_offset_minutes
        self.sunset_offset_minutes = sunset_offset_minutes
        self.debug = debug
        self.cached_windows: list[tuple[datetime, datetime]] = []
        self.last_window_update_date: datetime | None = None

    def _update_misting_windows_if_needed(self, now: datetime) -> None:
        """Recalculate misting windows if the date has changed."""
        current_date = now.date()
        last_update_date = self.last_window_update_date.date() if self.last_window_update_date else None

        if last_update_date != current_date:
            self._calculate_misting_windows()
            self.last_window_update_date = now

    def _calculate_misting_windows(self) -> None:
        """Calculate and cache misting windows for today."""
        # Calculate effective day window with offsets
        eff_sunrise = self.schedule.lights_on + timedelta(minutes=self.sunrise_offset_minutes)
        eff_sunset = self.schedule.lights_off + timedelta(minutes=self.sunset_offset_minutes)

        if eff_sunrise >= eff_sunset:
            self.cached_windows = []
            return

        # Total duration available for misting periods
        total_duration = eff_sunset - eff_sunrise
        period_duration = total_duration / (self.number_of_periods - 1)
        on_delta = timedelta(minutes=self.on_minutes)

        self.cached_windows = []
        for i in range(self.number_of_periods):
            period_start = eff_sunrise + (period_duration * i)
            mist_end = period_start + on_delta
            self.cached_windows.append((period_start, mist_end))
            start_s = period_start.astimezone(self.schedule.sun_schedule.timezone).strftime('%Y-%m-%d %H:%M:%S')
            print(f"{get_timestamp()}Misting window {i+1}: {start_s}")

    def _should_mist(self, now: datetime) -> bool:
        """Check if we're currently in a misting window."""
        self._update_misting_windows_if_needed(now)

        if not between_two_times(now, self.schedule.lights_on, self.schedule.lights_off):
            return False

        for mist_start, mist_end in self.cached_windows:
            if mist_start <= now < mist_end:
                return True

        return False

    def update(self, now: datetime) -> None:
        misting = self._should_mist(now)
        if not misting:
            return
        success = False
        while not success:
            success = True
            for plug in self.plugs.values():
                success &= plug.set_on(True)
            time.sleep(1.0)
        elapsed_time = 0
        start_time = time.perf_counter()
        while elapsed_time < self.on_minutes * 60:
            dt = 0.5
            time.sleep(dt)
            elapsed_time = time.perf_counter() - start_time
        success = False
        while not success:
            success = True
            for plug in self.plugs.values():
                success &= plug.set_on(False)
            time.sleep(1.0)
