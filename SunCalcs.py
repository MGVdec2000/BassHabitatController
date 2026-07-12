import math
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

@dataclass
class SunSchedule:
    latitude: float
    longitude: float
    timezone: ZoneInfo
    sunrise: datetime = field(default=datetime.min, init=False)
    sunset: datetime = field(default=datetime.max, init=False)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def __post_init__(self):
        self.update()
        return

    def update(self):
        with self.lock:
            self.sunrise, self.sunset = calculate_sun_times(self)
            pass


def get_julian_date(dt: datetime) -> float:
    """Convert a UTC datetime object into a Julian Date float."""
    # Ensure datetime has UTC timezone info
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)

    # Unix timestamp is seconds since Jan 1, 1970 (Julian Date: 2440587.5)
    unix_timestamp = dt.timestamp()
    julian_date = int(unix_timestamp / 86400.0 + 2440587.5)
    return julian_date

def datetime_from_julian_date(julian_date: float) -> datetime:
    """Convert a Julian Date float into a UTC datetime object."""
    unix_timestamp = (julian_date - 2440587.5) * 86400.0
    return datetime.fromtimestamp(unix_timestamp, tz=timezone.utc)

def calculate_sun_times(sun_schedule: SunSchedule, requested_date: datetime | None = None):
    """
    Calculate UTC sunrise and sunset for a given latitude, longitude, and date.

    :param sun_schedule: SunSchedule object containing latitude, longitude, and other parameters
    :param requested_date: Date to check for sunrise and sunset. Defaults to current UTC datetime.
    :return: Tuple of (sunrise_datetime, sunset_datetime) in UTC, or (None, None)
    """

    lat = sun_schedule.latitude
    lon = sun_schedule.longitude
    lat_rad = math.radians(lat)

    if requested_date is None:
        requested_date = datetime.now(ZoneInfo('America/Indiana/Indianapolis'))

    tz = requested_date.tzinfo

    # 1. Current Julian Date
    julian_date = get_julian_date(requested_date.astimezone(timezone.utc))

    # 2. Days since J2000.0 epoch (January 1, 2000 at Noon)
    n = julian_date - 2451545.0 + 0.0008

    # 3. Approximate mean solar time
    solar_mean_time = n - (lon / 360.0)

    # 4. Solar mean anomaly (in degrees and radians)
    solar_mean_deg = (357.5291 + 0.98560028 * solar_mean_time) % 360
    solar_mean_rad = math.radians(solar_mean_deg)

    # 5. Equation of the center
    center = 1.9148 * math.sin(solar_mean_rad) + 0.0200 * math.sin(2 * solar_mean_rad) + 0.0003 * math.sin(3 * solar_mean_rad)

    # 6. Ecliptic longitude
    lambda_sun = (solar_mean_deg + center + 180 + 102.9372) % 360
    lambda_rad = math.radians(lambda_sun)

    # 7. Solar transit (Solar Noon in Julian Date format)
    solar_noon = 2451545.0 + solar_mean_time + 0.0053 * math.sin(solar_mean_rad) - 0.0069 * math.sin(2 * lambda_rad)

    # 8. Declination of the sun
    sin_delta = math.sin(lambda_rad) * math.sin(math.radians(23.44))
    cos_delta = math.cos(math.asin(sin_delta))

    # 9. Hour angle (h0 = -0.833° corrects for atmospheric refraction & solar disc size)
    hour_angle_rad = math.radians(-0.833)

    try:
        cos_hour_angle = (math.sin(hour_angle_rad) - math.sin(lat_rad) * sin_delta) / (math.cos(lat_rad) * cos_delta)

        # Handle polar days (constant sun) and polar nights (constant darkness)
        if cos_hour_angle > 1 or cos_hour_angle < -1:
            return None, None

        hour_angle_degrees = math.degrees(math.acos(cos_hour_angle))
    except ZeroDivisionError:
        return None, None

    # 10. Calculate Sunrise and Sunset Julian Dates
    julian_sunrise = solar_noon - (hour_angle_degrees / 360.0)
    julian_sunset = solar_noon + (hour_angle_degrees / 360.0)

    # Helper to convert Julian Dates back to UTC datetime
    def jd_to_datetime(jd):
        unix_time = (jd - 2440587.5) * 86400.0
        return datetime.fromtimestamp(unix_time, tz=timezone.utc)

    sunrise_datetime = jd_to_datetime(julian_sunrise).astimezone(tz)
    sunset_datetime = jd_to_datetime(julian_sunset).astimezone(tz)
    next_date = requested_date.astimezone(tz) + timedelta(hours=12)

    if requested_date > sunset_datetime:
        return calculate_sun_times(sun_schedule, next_date)

    return sunrise_datetime, sunset_datetime


# --- Example Usage ---
if __name__ == "__main__":
    # Test coordinates for Indianapolis, Indiana (39.7684° N, 86.1581° W)
    schedule = SunSchedule(
        latitude=39.7616,
        longitude=-86.5212,
        timezone=ZoneInfo('America/Indianapolis'))
    for hours in range(-12, 25):
        target_date = datetime.now(schedule.timezone) + timedelta(hours=hours)
        sunrise, sunset = calculate_sun_times(schedule, target_date)

        print(f"\nDate Evaluated (UTC): {target_date.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"  Sunrise (UTC):        {sunrise.strftime('%Y-%m-%d %H:%M:%S') if sunrise else 'Polar Night/Day'}")
        print(f"  Sunset (UTC):         {sunset.strftime('%Y-%m-%d %H:%M:%S') if sunset else 'Polar Night/Day'}")
