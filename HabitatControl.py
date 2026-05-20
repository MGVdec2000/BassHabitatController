import math
from datetime import datetime, timezone, timedelta
import urllib.request

# 1. Configuration
LATITUDE = 39.773660668668505 # Danville, IN
LONGITUDE = -86.49409774903292 # Danville, IN
TIMEZONE_OFFSET = -5  # Your local UTC offset (e.g., -5 for EST)
UVB_IP = "192.168.1.150"
BASKING_IP = "192.168.1.151"
CHE_IP = "192.168.1.152"
MIN_DAYLIGHT_HRS = 12.0

# 2. Solar Calculation Core
def get_solar_times():
    # Days since J2000.0 (January 1, 2000, 12:00 UTC)
    now_utc = datetime.now(timezone.utc)
    j2000 = datetime(2000, 1, 1, 12, 0, tzinfo=timezone.utc)
    n = (now_utc - j2000).total_seconds() / 86400.0

    # Solar math
    M = math.radians((357.5291 + 0.98560028 * n) % 360)
    C = 1.9148 * math.sin(M) + 0.02 * math.sin(2 * M)
    lam = math.radians((math.degrees(M) + C + 180 + 102.9372) % 360)
    
    # Declination
    sin_delta = math.sin(lam) * math.sin(math.radians(23.44))
    delta = math.asin(sin_delta)

    # Hour Angle
    phi = math.radians(LATITUDE)
    cos_H = (math.sin(math.radians(-0.833)) - math.sin(phi) * math.sin(delta)) / (math.cos(phi) * math.cos(delta))
    
    # Handle polar edge cases safely
    if cos_H >= 1: return None, None  # Always dark
    if cos_H <= -1: return None, None # Always light
    
    H = math.degrees(math.acos(cos_H))

    # Calculate Solar Noon & Events in Degrees
    solar_noon = 180 - LONGITUDE - C
    sunrise_deg = (solar_noon - H) % 360
    sunset_deg = (solar_noon + H) % 360

    # Convert degrees to UTC hours, then to local time
    sunrise_utc_hours = sunrise_deg / 15.0
    sunset_utc_hours = sunset_deg / 15.0

    local_sunrise = (sunrise_utc_hours + TIMEZONE_OFFSET) % 24
    local_sunset = (sunset_utc_hours + TIMEZONE_OFFSET) % 24

    return local_sunrise, local_sunset

def control_shelly(ip_address: ip, state: bool):
    state_str = "true" if state else "false"
    url = f"http://{ip_address}/rpc/Switch.Set?id=0&on={state_str}"
    try:
        urllib.request.urlopen(url, timeout=5)
    except Exception as e:
        print(f"Error communicating with smart plug {ip_address}: {e}")

# 3. Smart Plug Control
async def manage_habitat_lighting():
    natural_sunrise, natural_sunset = get_solar_times()
    natural_daylight = natural_sunset - natural_sunrise
    if natural_daylight < 0
        natural_daylight += 24

    if natural_daylight < MIN_DAYLIGHT_HRS
        deficit = MIN_DAYLIGHT_HRS - nautral_daylight
        padding = deficit / 2.0

    sunrise_hour = (natural_sunrise - padding) % 24
    sunset_hour = (natural_sunset + padding) % 24

    # Get current local time as a decimal hour
    now = datetime.now()
    current_hour = now.hour + (now.minute / 60.0) + (now.second / 3600.0)

    print(f"Current Time: {now.strftime('%H:%M:%S')} ({current_hour:.2f})")
    print(f"Target Sunrise: {int(sunrise):02d}:{int((sunrise%1)*60):02d}")
    print(f"Target Sunset:  {int(sunset):02d}:{int((sunset%1)*60):02d}")

    # Determine if lights should be ON or OFF
    if sunrise_hour <= current_hour < sunset_hour:
        control_shelly(UVB_IP, True)
        control_shelly(BASKING_IP, True)
        control_shelly(CHE_IP, False)
        print("Status: Habitat lights ON, heater OFF.")
    else:
        control_shelly(UVB_IP, False)
        control_shelly(BASKING_IP, False)
        control_shelly(CHE_IP, True)
        print("Status: Habitat lights OFF, heater OM.")

# Run the task loop
if __name__ == "__main__":
    asyncio.run(manage_habitat_lighting())
