import math
from datetime import datetime, timezone, timedelta
import asyncio
from kasa import SmartPlug  # Run: pip install python-kasa

# 1. Configuration
LATITUDE = 39.773660668668505 # Danville, IN
LONGITUDE = -86.49409774903292 # Danville, IN
TIMEZONE_OFFSET = -5  # Your local UTC offset (e.g., -5 for EST)
PLUG_IP = "192.168.1.100"  # Your smart plug's local IP address

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

# 3. Smart Plug Control
async def manage_habitat_lighting():
    sunrise_hour, sunset_hour = get_solar_times()
    if sunrise_hour is None:
        print("Extreme latitude detected. Check schedule manual fallback.")
        return

    # Get current local time as a decimal hour
    now = datetime.now()
    current_hour = now.hour + (now.minute / 60.0) + (now.second / 3600.0)

    # Initialize Plug
    plug = SmartPlug(PLUG_IP)
    await plug.update()

    # Determine if lights should be ON or OFF
    if sunrise_hour <= current_hour < sunset_hour:
        if not plug.is_on:
            await plug.turn_on()
            print(f"[{now.strftime('%X')}] Daylight active: Turned habitat lights ON.")
    else:
        if plug.is_on:
            await plug.turn_off()
            print(f"[{now.strftime('%X')}] Night active: Turned habitat lights OFF.")

# Run the task loop
if __name__ == "__main__":
    asyncio.run(manage_habitat_lighting())
