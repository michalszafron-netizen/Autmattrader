"""Polish timezone utility — CET (UTC+1) / CEST (UTC+2).

No external dependencies — pure stdlib datetime arithmetic.

Usage:
    from tz_utils import pl_time, pl_time_str, now_pl, fmt_both

    pl_time_str("14:30")           -> "14:30 UTC / 16:30 CEST"
    pl_time_str("2026-05-21T14:30:00Z") -> same
    fmt_both(datetime_utc)         -> "14:30 UTC / 16:30 CEST"
    now_pl()                       -> datetime in Polish tz
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


def _pl_offset(dt_utc: datetime) -> int:
    """Return Poland's UTC offset: +2 (CEST, last Sun Mar → last Sun Oct) else +1."""
    year = dt_utc.year
    # Last Sunday of March (at 01:00 UTC clocks go forward)
    d = datetime(year, 3, 31, 1, 0, tzinfo=timezone.utc)
    dst_start = d - timedelta(days=(d.weekday() + 1) % 7)
    # Last Sunday of October (at 01:00 UTC clocks go back)
    d = datetime(year, 10, 31, 1, 0, tzinfo=timezone.utc)
    dst_end = d - timedelta(days=(d.weekday() + 1) % 7)

    utc = dt_utc if dt_utc.tzinfo else dt_utc.replace(tzinfo=timezone.utc)
    return 2 if dst_start <= utc < dst_end else 1


def pl_offset_hours(dt_utc: datetime | None = None) -> int:
    """Current or given UTC moment's Polish offset in hours."""
    return _pl_offset(dt_utc or datetime.now(timezone.utc))


def to_pl(dt_utc: datetime) -> datetime:
    """Convert UTC datetime to Polish local time datetime."""
    utc = dt_utc if dt_utc.tzinfo else dt_utc.replace(tzinfo=timezone.utc)
    offset = _pl_offset(utc)
    return utc + timedelta(hours=offset)


def pl_label(dt_utc: datetime) -> str:
    return "CEST" if _pl_offset(dt_utc) == 2 else "CET"


def now_pl() -> datetime:
    """Current time in Polish timezone."""
    return to_pl(datetime.now(timezone.utc))


def fmt_both(dt_utc: datetime, fmt: str = "%H:%M") -> str:
    """'HH:MM UTC / HH:MM CEST' — both timezones in one string."""
    utc = dt_utc if dt_utc.tzinfo else dt_utc.replace(tzinfo=timezone.utc)
    pl  = to_pl(utc)
    lbl = pl_label(utc)
    return f"{utc.strftime(fmt)} UTC / {pl.strftime(fmt)} {lbl}"


def pl_time_str(time_input: str, fmt: str = "%H:%M") -> str:
    """Parse a time string (HH:MM or ISO) and return 'UTC / PL' string.

    Accepts:
      "14:30"                     — treated as today UTC
      "2026-05-21T14:30:00Z"      — full ISO
      "2026-05-21T14:30:00+00:00" — full ISO with tz
    """
    if not time_input:
        return "—"
    try:
        if "T" in time_input or "-" in time_input[:10]:
            clean = time_input.replace("Z", "+00:00")
            dt = datetime.fromisoformat(clean)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        else:
            # HH:MM or HH:MM:SS — assume today UTC
            parts = time_input.strip().split(":")
            now   = datetime.now(timezone.utc)
            dt    = now.replace(hour=int(parts[0]), minute=int(parts[1]),
                                second=0, microsecond=0)
        return fmt_both(dt, fmt)
    except Exception:
        return time_input
