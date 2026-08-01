from datetime import datetime, time, timedelta
import threading
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
        enabled: bool = True,
        debug: bool = False,
    ):
        self.plugs = plugs
        self.schedule = schedule
        self.on_minutes = on_minutes
        self.number_of_periods = number_of_periods
        self.sunrise_offset_minutes = sunrise_offset_minutes
        self.sunset_offset_minutes = sunset_offset_minutes
        self.enabled = enabled
        self.debug = debug
        self.cached_windows: list[tuple[datetime, datetime]] = []
        self.last_window_update_date: datetime | None = None
        self.get_current_states()

    def manual_override(self, signum, _frame):
        print(f"Manual override requested by signal {signum}")
        pump_thread = threading.Thread(target=self._turn_pump_on)
        pump_thread.daemon = True
        pump_thread.start()

    def get_current_states(self) -> None:
        if not self.enabled:
            print(f"{get_timestamp()}Humidity controller is disabled, skipping state check")
            return
        for plug in self.plugs.values():
            state = plug.check_state()
            if state is None:
                continue
            switch = "ON" if state else "OFF"
            print(f"{get_timestamp()}{plug.name} is {switch}")

    def _update_misting_windows_if_needed(self, now: datetime) -> None:
        if not self.enabled:
            return
        """Recalculate misting windows if the date has changed."""
        current_date = now.date()
        last_update_date = self.last_window_update_date.date() if self.last_window_update_date else None

        if last_update_date != current_date:
            self._calculate_misting_windows()
            self.last_window_update_date = now

    def _calculate_misting_windows(self) -> None:
        if not self.enabled:
            return
        """Calculate and cache misting windows for today."""
        eff_sunrise = self.schedule.lights_on + timedelta(minutes=self.sunrise_offset_minutes)
        eff_sunset = self.schedule.lights_off + timedelta(minutes=self.sunset_offset_minutes)

        if eff_sunrise >= eff_sunset:
            self.cached_windows = []
            return

        """Total duration available for misting periods"""
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
        if not self.enabled:
            return False
        """Check if we're currently in a misting window."""
        self._update_misting_windows_if_needed(now)

        if not between_two_times(now, self.schedule.lights_on, self.schedule.lights_off):
            return False

        for mist_start, mist_end in self.cached_windows:
            if mist_start <= now < mist_end:
                return True

        return False

    def _turn_pump_on(self) -> None:
        """Turn on the misting plugs."""
        success = False
        while not success:
            print(f"{get_timestamp()}Attempting to turn on misting plugs")
            success = True
            for plug in self.plugs.values():
                success &= plug.set_on(True)
            if success:
                print(f"{get_timestamp()}Successfully turned on misting plugs")
            else:
                print(f"{get_timestamp()}Failed to turn on misting plugs, retrying...")
                time.sleep(1.0)
        
        start_time = time.perf_counter()
        elapsed_time = 0
        while elapsed_time < self.on_minutes * 60:
            dt = 0.5
            time.sleep(dt)
            elapsed_time = time.perf_counter() - start_time
            if self.debug:
                print(f"{get_timestamp()}Elapsed misting time: {elapsed_time:.2f} seconds")
        success = False
        while not success:
            print(f"{get_timestamp()}Attempting to turn off misting plugs")
            success = True
            for plug in self.plugs.values():
                success &= plug.set_on(False)
                if success:
                    print(f"{get_timestamp()}Successfully turned off misting plugs")
                else:
                    print(f"{get_timestamp()}Failed to turn off misting plugs, retrying...")
                    time.sleep(1.0)
        print(f"{get_timestamp()}Misting cycle complete")

    def update(self, now: datetime) -> None:
        if not self.enabled:
            return
        misting = self._should_mist(now)
        if not misting:
            return
        pump_thread = threading.Thread(target=self._turn_pump_on)
        pump_thread.daemon = True
        pump_thread.start()
