from datetime import datetime
from zoneinfo import ZoneInfo


def get_timestamp(tz: ZoneInfo | None = None) -> str:
    if tz is None:
        tz = ZoneInfo('America/Indiana/Indianapolis')
    dt = datetime.now(tz)
    formatted = dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}" + dt.strftime("%z")
    return f"[{formatted}] "


def between_two_times(now: datetime, on_time: datetime, off_time: datetime) -> bool:
    """Returns True if now is between on_time (inclusive) and off_time (exclusive)."""
    return on_time <= now < off_time


def before_or_after(now: datetime, off_time: datetime, on_time: datetime) -> bool:
    """Returns True if now is before off_time or after on_time (for overnight/wraparound schedules)."""
    return now < off_time or now > on_time
