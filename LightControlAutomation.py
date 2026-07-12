import time as thread
import yaml
import requests
import signal
import threading
import sys
from dataclasses import dataclass, field
from SunCalcs import SunSchedule
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

CONFIG_PATH = "tortoise_controller.yaml"
running = True
debug = False
trace = False


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


class ShellyPlug:
    def __init__(self, name: str, ip: str, shelly_id: str):
        self.name = name
        self.ip = ip
        self.shelly_id = shelly_id

    def check_state(self) -> bool | None:

        # noinspection HttpUrlsUsage
        url = f"http://{self.ip}/rpc"
        payload = {
            "id": 1,
            "method": "Shelly.GetStatus",
            "params": {
                "id": 0,
            },
        }

        try:
            response = requests.post(url, json=payload, timeout=5)
            response.raise_for_status()
        except requests.RequestException as error:
            #print(f"{get_timestamp()}Failed to get state for {self.name}: {error}")
            return None

        json_object = response.json()
        is_on = json_object["result"]["switch:0"]["output"]
        return is_on

    def set_on(self, cmd: bool) -> None:
        current_state = self.check_state()
        if current_state is None:
            # could not get state, so don't change state'
            return
        if self.check_state() == cmd:
            # already in desired state
            return

        # noinspection HttpUrlsUsage
        url = f"http://{self.ip}/rpc"
        payload = {
            "id": 1,
            "method": "Switch.Set",
            "params": {
                "id": 0,
                "on": cmd,
            },
        }

        try:
            response = requests.post(url, json=payload, timeout=5)
            response.raise_for_status()
            print(f"{get_timestamp()}Set {self.name} to {'ON' if cmd else 'OFF'}")
        except requests.RequestException as error:
            print(f"{get_timestamp()}Failed to set state for {self.name}: {error}")

def get_timestamp():
    dt = datetime.now(ZoneInfo('America/Indiana/Indianapolis'))
    formatted = dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}" + dt.strftime("%z")
    return f"[{formatted}] "

def request_shutdown(signum, _):
    global running
    print(f"{get_timestamp()}Shutdown requested by signal {signum}")
    running = False

signal.signal(signal.SIGINT, request_shutdown)
signal.signal(signal.SIGTERM, request_shutdown)

def load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as file:
        return yaml.safe_load(file)

def between_two_times(
    now: datetime,
    on_time: datetime,
    off_time: datetime,
) -> bool:
    after_lights_on = on_time <= now
    before_lights_off = now < off_time
    device_is_on = after_lights_on and before_lights_off
    return device_is_on

def before_or_after(now: datetime, off_time: datetime, on_time: datetime) -> bool:
    before_off_time = now < off_time
    after_on_time = now > on_time
    device_is_on = before_off_time or after_on_time
    return device_is_on

def get_current_states(plugs):
    for plug in plugs.values():
        state = plug.check_state()
        if state is None:
            print(f"{get_timestamp()}Plug {plug.name} is not responding")
            continue
        switch = "ON" if state else "OFF"
        print(f"{get_timestamp()}{plug.name} is {switch}")
    pass

def main() -> None:
    if debug:
        print(f"{get_timestamp()}Starting...")
        print(f"{get_timestamp()}Using config file: {CONFIG_PATH}")
    config = load_config()
    if debug:
        print(f"{get_timestamp()}Config loaded successfully")

    target_lat = float(config["location"]["latitude"])
    target_lon = float(config["location"]["longitude"])

    target_timezone_key = config["location"]["timezone"]
    tz = ZoneInfo(target_timezone_key)
    minimum_hours = float(config["daylight_minimum_hours"])

    if debug:
        print(f"{get_timestamp()}Location: {target_lat}, {target_lon}")
        print(f"{get_timestamp()}Timezone: {target_timezone_key}")
        print(f"{get_timestamp()}Minimum daylight hours: {minimum_hours}")

    plugs = {
        name: ShellyPlug(name=name, ip=plug_config["ip"], shelly_id=plug_config["shelly_id"])
        for name, plug_config in config["plugs"].items()
    }
    lamp_plugs = {
        name: plug
        for name, plug in plugs.items()
        if "_lamp" in name
    }
    heater_plugs = {
        name: plug
        for name, plug in plugs.items()
            if "_heater" in name
    }

    get_current_states(plugs)

    sun_schedule = SunSchedule(
        latitude=target_lat,
        longitude=target_lon,
        timezone=tz)
    sunrise = sun_schedule.sunrise.astimezone(sun_schedule.timezone).strftime('%Y-%m-%d %H:%M:%S')
    sunset = sun_schedule.sunset.astimezone(sun_schedule.timezone).strftime('%H:%M:%S')
    print(f"{get_timestamp()}Sun schedule updated ({sunrise} / {sunset})")
    enclosure_schedule = EnvironmentSchedule(
        minimum_hours,
        sun_schedule)

    try:
        while running:
            now = datetime.now(enclosure_schedule.sun_schedule.timezone)
            if now > enclosure_schedule.sun_schedule.sunset:
                enclosure_schedule.sun_schedule.update()
                sunrise = enclosure_schedule.sun_schedule.sunrise.astimezone(
                    enclosure_schedule.sun_schedule.timezone).strftime('%Y-%m-%d %H:%M:%S')
                sunset = enclosure_schedule.sun_schedule.sunset.astimezone(
                    enclosure_schedule.sun_schedule.timezone).strftime('%H:%M:%S')
                print(f"{get_timestamp()}Sun schedule updated ({sunrise} / {sunset})")
            if now > enclosure_schedule.lights_off:
                enclosure_schedule.update()

            lights_on = between_two_times(now, enclosure_schedule.lights_on, enclosure_schedule.lights_off)
            for plug in lamp_plugs.values():
                plug.set_on(lights_on)

            heaters_on = before_or_after(now, enclosure_schedule.heaters_off, enclosure_schedule.heaters_on)
            for plug in heater_plugs.values():
                plug.set_on(heaters_on)

            # Sleep for 10 seconds before checking again
            dt = 0.5 # seconds
            sleep_time = 10 # seconds
            n_loops = int(sleep_time // dt)
            for _ in range(n_loops):
                if not running:
                    break
                thread.sleep(dt)
    except KeyboardInterrupt:
        print(f"{get_timestamp()}Exiting gracefully...")

    print(f"{get_timestamp()}Exiting...")

if __name__ == "__main__":
    for arg in sys.argv:
        trace = trace or arg == "--trace"
        debug = debug or trace or arg == "--debug"
    main()
