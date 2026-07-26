import requests

from utils import get_timestamp


class ShellyPlug:
    def __init__(self, name: str, ip: str, shelly_id: str, debug: bool = False):
        self.name = name
        self.ip = ip
        self.shelly_id = shelly_id
        self.debug = debug

    def check_state(self) -> bool | None:
        # noinspection HttpUrlsUsage
        url = f"http://{self.ip}/rpc"
        payload = {
            "id": 1,
            "method": "Shelly.GetStatus",
            "params": {"id": 0},
        }

        try:
            response = requests.post(url, json=payload, timeout=5)
            response.raise_for_status()
        except requests.RequestException as error:
            if self.debug:
                print(f"{get_timestamp()}Failed to get state for {self.name}: {error}")
            return None

        json_object = response.json()
        is_on = json_object["result"]["switch:0"]["output"]
        return is_on

    def set_on(self, cmd: bool) -> None:
        current_state = self.check_state()
        if current_state is None:
            if self.debug:
                print(f"{get_timestamp()}Failed to get current state for {self.name}")
            return
        if current_state == cmd:
            # Already in the desired state, no need to send a command
            return

        # noinspection HttpUrlsUsage
        url = f"http://{self.ip}/rpc"
        payload = {
            "id": 1,
            "method": "Switch.Set",
            "params": {"id": 0, "on": cmd},
        }

        try:
            response = requests.post(url, json=payload, timeout=5)
            response.raise_for_status()
            print(f"{get_timestamp()}Set {self.name} to {'ON' if cmd else 'OFF'}")
        except requests.RequestException as error:
            print(f"{get_timestamp()}Failed to set state for {self.name}: {error}")
