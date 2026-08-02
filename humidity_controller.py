from datetime import datetime, time, timedelta
import threading
import time as thread
from enum import Enum
from shelly_plug import ShellyPlug
from environment_schedule import EnvironmentSchedule
from utils import between_two_times, get_timestamp


class PumpState(Enum):
    ON = "ON"
    OFF = "OFF"
    ERROR = "Error"


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
        plug: ShellyPlug,
        schedule: EnvironmentSchedule,
        on_minutes: float = 0.5,
        number_of_periods: int = 4,
        sunrise_offset_minutes: float = 0.0,
        sunset_offset_minutes: float = 0.0,
        enabled: bool = True,
        debug: bool = False,
    ):
        self.plug = plug
        self.schedule = schedule
        self.on_minutes = on_minutes
        self.number_of_periods = number_of_periods
        self.sunrise_offset_minutes = sunrise_offset_minutes
        self.sunset_offset_minutes = sunset_offset_minutes
        self.enabled = enabled
        self.debug = debug
        self.current_state = PumpState.ERROR
        self.cached_windows: list[tuple[datetime, datetime]] = []
        self.last_window_update_date: datetime | None = None
        self._pump_cycle_active = False
        self._pump_cycle_lock = threading.Lock()

    def manual_override(self, signum, _frame):
        print(f"Manual override requested by signal {signum}")
        self._start_misting_cycle()

    def _start_misting_cycle(self) -> bool:
        with self._pump_cycle_lock:
            if self._pump_cycle_active:
                # print(f"{get_timestamp()}Misting cycle already running, skipping")
                return False
            self._pump_cycle_active = True

        pump_thread = threading.Thread(target=self._turn_pump_on)
        pump_thread.daemon = True
        pump_thread.start()
        return True

    def _update_misting_windows_if_needed(self, now: datetime) -> None:
        """Recalculate misting windows if the date has changed."""
        if not self.enabled:
            return
        current_date = now.date()
        last_update_date = self.last_window_update_date.date() if self.last_window_update_date else None

        if last_update_date != current_date:
            self._calculate_misting_windows()
            self.last_window_update_date = now

    def _calculate_misting_windows(self) -> None:
        """Calculate and cache misting windows for today."""
        if not self.enabled:
            return
        eff_sunrise = self.schedule.lights_on + timedelta(minutes=self.sunrise_offset_minutes)
        eff_sunset = self.schedule.lights_off + timedelta(minutes=self.sunset_offset_minutes)

        if eff_sunrise >= eff_sunset:
            self.cached_windows = []
            return

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
        if not self.enabled:
            return False
        self._update_misting_windows_if_needed(now)

        if not between_two_times(now, self.schedule.lights_on, self.schedule.lights_off):
            return False

        for mist_start, mist_end in self.cached_windows:
            if mist_start <= now < mist_end:
                return True

        return False

    def _turn_pump_on(self) -> None:
        """Turn the pump on for the configured duration, then turn it off."""
        print(f"{get_timestamp()}Start misting cycle for {self.on_minutes} minutes")
        try:
            self.plug.set_on(True)
            thread.sleep(self.on_minutes * 60)
        finally:
            self.plug.set_on(False)
            with self._pump_cycle_lock:
                self._pump_cycle_active = False
            print(f"{get_timestamp()}Misting cycle complete")

    def update(self, now: datetime) -> None:
        if not self.enabled:
            return
        misting = self._should_mist(now)
        if not misting:
            return
        self._start_misting_cycle()
