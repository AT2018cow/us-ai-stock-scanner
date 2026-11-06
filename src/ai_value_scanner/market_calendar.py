"""Pure NYSE sessions shared by EOD publication and holding-period labels.

Historical / replay paths take explicit dates and never use the wall clock.

Scope is intentionally small and testable:

- regular sessions are Monday-Friday minus the standard NYSE holidays;
- fixed-date holidays use the observed Friday/Monday rule (New Year's Day is
  not shifted to the preceding Friday, matching NYSE practice);
- Good Friday is derived from the Gregorian Easter algorithm;
- Juneteenth is a holiday from 2022 onward;
- early closes (13:00 ET) cover the day after Thanksgiving, July 3 when
  it is a session, and Christmas Eve when it is a regular session;
- a Friday before a Sunday/Monday July 4 remains a full session. The
  publication gate must not infer an early close from holiday proximity.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo

NYSE_TZ = ZoneInfo("America/New_York")
_REGULAR_OPEN = (9, 30)
_REGULAR_CLOSE = (16, 0)
_EARLY_CLOSE = (13, 0)
_WEEKEND = {5, 6}


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """Return the n-th (1-based) ``weekday`` of a month."""
    first = date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    return first + timedelta(days=offset + 7 * (n - 1))


def _last_weekday(year: int, month: int, weekday: int) -> date:
    if month == 12:
        last = date(year, 12, 31)
    else:
        last = date(year, month + 1, 1) - timedelta(days=1)
    offset = (last.weekday() - weekday) % 7
    return last - timedelta(days=offset)


def _easter_sunday(year: int) -> date:
    """Anonymous Gregorian algorithm for Easter Sunday."""
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    ell = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * ell) // 451
    month = (h + ell - 7 * m + 114) // 31
    day = ((h + ell - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def _observed_fixed(day: date) -> date:
    """Saturday -> Friday, Sunday -> Monday (regular NYSE fixed-date rule)."""
    if day.weekday() == 5:
        return day - timedelta(days=1)
    if day.weekday() == 6:
        return day + timedelta(days=1)
    return day


@lru_cache(maxsize=64)
def nyse_holidays(year: int) -> frozenset[date]:
    holidays: set[date] = {
        _nth_weekday(year, 1, 0, 3),  # Martin Luther King Jr. Day
        _nth_weekday(year, 2, 0, 3),  # Washington's Birthday
        _easter_sunday(year) - timedelta(days=2),  # Good Friday
        _last_weekday(year, 5, 0),  # Memorial Day
        _nth_weekday(year, 9, 0, 1),  # Labor Day
        _nth_weekday(year, 11, 3, 4),  # Thanksgiving
    }
    new_year = date(year, 1, 1)
    if new_year.weekday() == 6:
        # Only Sunday shifts to Monday; a Saturday New Year is not observed
        # on the preceding Friday (NYSE practice).
        holidays.add(new_year + timedelta(days=1))
    elif new_year.weekday() != 5:
        holidays.add(new_year)
    holidays.add(_observed_fixed(date(year, 7, 4)))
    holidays.add(_observed_fixed(date(year, 12, 25)))
    if year >= 2022:
        holidays.add(_observed_fixed(date(year, 6, 19)))
    # Exchange-announced national days of mourning in this study's history.
    # ICE notices: Bush (2018-12-05), Carter (2025-01-09).
    if year == 2018:
        holidays.add(date(2018, 12, 5))
    if year == 2025:
        holidays.add(date(2025, 1, 9))
    return frozenset(holidays)


def is_session_day(day: date) -> bool:
    if day.weekday() in _WEEKEND:
        return False
    return day not in nyse_holidays(day.year)


def is_early_close(day: date) -> bool:
    if not is_session_day(day):
        return False
    if day == _nth_weekday(day.year, 11, 3, 4) + timedelta(days=1):
        return True  # day after Thanksgiving
    if day == date(day.year, 7, 3):
        return True
    christmas = date(day.year, 12, 25)
    if christmas.weekday() in {1, 2, 3, 4} and day == date(day.year, 12, 24):
        return True
    return False


def session_open_utc(day: date) -> datetime:
    """Regular-session open (09:30 ET); early-close days open at the same time."""
    local_open = datetime(
        day.year, day.month, day.day, _REGULAR_OPEN[0], _REGULAR_OPEN[1],
        tzinfo=NYSE_TZ,
    )
    return local_open.astimezone(timezone.utc)


def session_close_utc(day: date) -> datetime:
    hour, minute = _EARLY_CLOSE if is_early_close(day) else _REGULAR_CLOSE
    local_close = datetime(
        day.year, day.month, day.day, hour, minute, tzinfo=NYSE_TZ
    )
    return local_close.astimezone(timezone.utc)


def latest_completed_session(now_utc: datetime) -> date:
    """Most recent NYSE session whose close (ET) has already happened.

    During a session, on weekends, and on holidays this returns the prior
    regular session, so a scanner reading the newest daily bars never treats
    Friday data as stale on Saturday/Sunday/Monday pre-close.
    """
    if now_utc.tzinfo is None:
        raise ValueError("now_utc must be timezone-aware")
    cursor = now_utc.astimezone(NYSE_TZ).date()
    for _ in range(30):
        if is_session_day(cursor) and now_utc >= session_close_utc(cursor):
            return cursor
        cursor -= timedelta(days=1)
    raise ValueError("no NYSE session found within 30 days (calendar error)")
