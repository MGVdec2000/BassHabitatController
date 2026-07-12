import time as thread
import yaml
import signal
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

from sun_schedule import SunSchedule
from environment_schedule import EnvironmentSchedule
from shelly_plug import ShellyPlug
from lighting_controller import LightingController
from heater_controller import HeaterController
from humidity_controller import HumidityController
from utils import get_timestamp

CONFIG_PATH = "tortoise_controller.yaml"
running = True
debug = False
trace = False


def request_shutdown(signum, _):
    global running
    print(f"{get_timestamp()}Shutdown requested by signal {signum}")
    running = False


signal.signal(signal.SIGINT, request_shutdown)
signal.signal(signal.SIGTERM, request_shutdown)


def load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as file:
        return yaml.safe_load(file)


def get_current_states(plugs: dict[str, ShellyPlug]) -> None:
    for plug in plugs.values():
        state = plug.check_state()
        if state is None:
            print(f"{get_timestamp()}Plug {plug.name} is not responding")
            continue
        switch = "ON" if state else "OFF"
        print(f"{get_timestamp()}{plug.name} is {switch}")


def main() -> None:
    if debug:
        print(f"{get_timestamp()}Starting...")
        print(f"{get_timestamp()}Using config file: {CONFIG_PATH}")

    config = load_config()

    target_lat = float(config["location"]["latitude"])
    target_lon = float(config["location"]["longitude"])
    target_timezone_key = config["location"]["timezone"]
    tz = ZoneInfo(target_timezone_key)
    minimum_hours = float(config["daylight_minimum_hours"])

    if debug:
        print(f"{get_timestamp()}Location: {target_lat}, {target_lon}")
        print(f"{get_timestamp()}Timezone: {target_timezone_key}")
        print(f"{get_timestamp()}Minimum daylight hours: {minimum_hours}")

    all_plugs = {
        name: ShellyPlug(name=name, ip=plug_cfg["ip"], shelly_id=plug_cfg["shelly_id"], debug=debug)
        for name, plug_cfg in config["plugs"].items()
    }
    lamp_plugs = {name: plug for name, plug in all_plugs.items() if "_lamp" in name}
    heater_plugs = {name: plug for name, plug in all_plugs.items() if "_heater" in name}

    humidity_cfg = config.get("humidity", {})
    humidity_plugs = {
        name: ShellyPlug(name=name, ip=plug_cfg["ip"], shelly_id=plug_cfg["shelly_id"], debug=debug)
        for name, plug_cfg in humidity_cfg.get("plugs", {}).items()
    }

    get_current_states({**all_plugs, **humidity_plugs})

    sun_schedule = SunSchedule(latitude=target_lat, longitude=target_lon, timezone=tz)
    sunrise = sun_schedule.sunrise.astimezone(tz).strftime('%Y-%m-%d %H:%M:%S')
    sunset = sun_schedule.sunset.astimezone(tz).strftime('%H:%M:%S')
    print(f"{get_timestamp()}Sun schedule updated ({sunrise} / {sunset})")

    env_schedule = EnvironmentSchedule(minimum_hours=minimum_hours, sun_schedule=sun_schedule)

    lighting = LightingController(plugs=lamp_plugs, schedule=env_schedule)
    heater = HeaterController(plugs=heater_plugs, schedule=env_schedule)
    humidity = HumidityController(
        plugs=humidity_plugs,
        schedule=env_schedule,
        on_minutes=float(humidity_cfg.get("on_minutes", 2.0)),
        cycle_interval_minutes=float(humidity_cfg.get("cycle_interval_minutes", 60.0)),
        only_during_daylight=bool(humidity_cfg.get("only_during_daylight", True)),
    )

    try:
        while running:
            now = datetime.now(tz)

            if now > env_schedule.sun_schedule.sunset:
                env_schedule.sun_schedule.update()
                sunrise = env_schedule.sun_schedule.sunrise.astimezone(tz).strftime('%Y-%m-%d %H:%M:%S')
                sunset = env_schedule.sun_schedule.sunset.astimezone(tz).strftime('%H:%M:%S')
                print(f"{get_timestamp()}Sun schedule updated ({sunrise} / {sunset})")

            if now > env_schedule.lights_off:
                env_schedule.update()

            lighting.update(now)
            heater.update(now)
            humidity.update(now)

            dt = 0.5
            sleep_time = 10
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
