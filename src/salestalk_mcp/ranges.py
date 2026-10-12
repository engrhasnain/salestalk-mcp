"""Friendly date ranges for the sales tools.

Claude (or a person) can say ``last_month``, ``this_quarter``, ``ytd`` or give an
explicit ``2026-01-01..2026-03-31``. Everything resolves to an inclusive
``DateRange`` that the SQL layer turns into ``order_date >= start AND
order_date < end_exclusive``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

MAX_SPAN_DAYS = 366 * 20  # sanity cap for explicit ranges
ALL_TIME_START = date(2000, 1, 1)

RANGE_HELP = (
    "Use a preset (today, yesterday, this_week, last_week, this_month, last_month, "
    "this_quarter, last_quarter, ytd, last_year, last_7_days, last_30_days, last_90_days, "
    "last_N_days, last_N_months, last_12_months, all_time) or an explicit period: "
    "YYYY-MM-DD..YYYY-MM-DD, YYYY-MM, YYYY-Qn or YYYY."
)
MONTH_HELP = "Use YYYY-MM (e.g. 2026-09), last_month or this_month."

_ALIASES = {
    "previous_month": "last_month",
    "prev_month": "last_month",
    "mtd": "this_month",
    "month_to_date": "this_month",
    "current_month": "this_month",
    "qtd": "this_quarter",
    "quarter_to_date": "this_quarter",
    "current_quarter": "this_quarter",
    "previous_quarter": "last_quarter",
    "this_year": "ytd",
    "year_to_date": "ytd",
    "current_year": "ytd",
    "previous_year": "last_year",
    "past_year": "last_12_months",
    "rolling_12_months": "last_12_months",
    "trailing_12_months": "last_12_months",
    "ttm": "last_12_months",
    "all": "all_time",
    "everything": "all_time",
    "week_to_date": "this_week",
    "previous_week": "last_week",
}

_EXPLICIT_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2})\s*(?:\.\.|/|\s+to\s+|\s*->\s*)\s*(\d{4}-\d{2}-\d{2})$", re.IGNORECASE
)
_SINGLE_DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MONTH_RE = re.compile(r"^(\d{4})-(\d{1,2})$")
_QUARTER_RE = re.compile(r"^(\d{4})[-_ ]?q([1-4])$", re.IGNORECASE)
_YEAR_RE = re.compile(r"^(\d{4})$")
_LAST_N_RE = re.compile(r"^(?:last|past|previous)_(\d{1,4})_(day|days|month|months)$")


class RangeError(ValueError):
    """Raised when a range or month string cannot be understood."""


@dataclass(frozen=True)
class DateRange:
    """An inclusive date range with a human label."""

    start: date
    end: date
    label: str

    def __post_init__(self) -> None:
        if self.start > self.end:
            raise RangeError(f"Range start {self.start} is after end {self.end}.")

    @property
    def end_exclusive(self) -> date:
        return self.end + timedelta(days=1)

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "days": self.days,
        }


# --------------------------------------------------------------------------- helpers


def month_start(d: date) -> date:
    return d.replace(day=1)


def add_months(d: date, months: int) -> date:
    """Shift a date by whole months, clamping the day (Jan 31 + 1 month = Feb 28/29)."""
    total = d.year * 12 + (d.month - 1) + months
    year, month0 = divmod(total, 12)
    month = month0 + 1
    day = min(d.day, _days_in_month(year, month))
    return date(year, month, day)


def month_end(d: date) -> date:
    return add_months(month_start(d), 1) - timedelta(days=1)


def quarter_start(d: date) -> date:
    return date(d.year, 3 * ((d.month - 1) // 3) + 1, 1)


def _days_in_month(year: int, month: int) -> int:
    if month == 12:
        return 31
    return (date(year, month + 1, 1) - date(year, month, 1)).days


def _parse_iso(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise RangeError(f"'{value}' is not a valid date (expected YYYY-MM-DD).") from exc


def _month_range(year: int, month: int, label: str | None = None) -> DateRange:
    if not 1 <= month <= 12:
        raise RangeError(f"Month must be 01-12, got {month:02d}.")
    start = date(year, month, 1)
    return DateRange(start, month_end(start), label or f"{year:04d}-{month:02d}")


def _normalize_keyword(value: str) -> str:
    key = re.sub(r"[\s\-]+", "_", value.strip().lower())
    return _ALIASES.get(key, key)


# --------------------------------------------------------------------------- public API


def parse_range(value: str | None, today: date | None = None, default: str = "last_30_days") -> DateRange:
    """Resolve a friendly or explicit range string into a :class:`DateRange`.

    ``today`` is injectable so tests (and demos) are deterministic.
    """
    today = today or date.today()
    raw = (value or "").strip() or default

    # Explicit ranges first (they contain digits and separators we must not normalize).
    if m := _EXPLICIT_RE.match(raw):
        start, end = _parse_iso(m.group(1)), _parse_iso(m.group(2))
        if start > end:
            raise RangeError(f"Range start {start} is after end {end}. {RANGE_HELP}")
        if (end - start).days > MAX_SPAN_DAYS:
            raise RangeError("Explicit ranges are limited to 20 years.")
        return DateRange(start, end, f"{start.isoformat()}..{end.isoformat()}")
    if _SINGLE_DAY_RE.match(raw):
        day = _parse_iso(raw)
        return DateRange(day, day, day.isoformat())
    if m := _MONTH_RE.match(raw):
        return _month_range(int(m.group(1)), int(m.group(2)))
    if m := _QUARTER_RE.match(raw):
        year, q = int(m.group(1)), int(m.group(2))
        start = date(year, 3 * (q - 1) + 1, 1)
        return DateRange(start, month_end(add_months(start, 2)), f"{year}-Q{q}")
    if m := _YEAR_RE.match(raw):
        year = int(m.group(1))
        return DateRange(date(year, 1, 1), date(year, 12, 31), str(year))

    key = _normalize_keyword(raw)

    if m := _LAST_N_RE.match(key):
        n, unit = int(m.group(1)), m.group(2)
        if n < 1:
            raise RangeError("N must be at least 1.")
        if unit.startswith("day"):
            if n > MAX_SPAN_DAYS:
                raise RangeError("last_N_days is limited to 20 years.")
            return DateRange(today - timedelta(days=n - 1), today, f"last_{n}_days")
        if n > 240:
            raise RangeError("last_N_months is limited to 240 months.")
        return DateRange(add_months(today, -n) + timedelta(days=1), today, f"last_{n}_months")

    if key == "today":
        return DateRange(today, today, "today")
    if key == "yesterday":
        y = today - timedelta(days=1)
        return DateRange(y, y, "yesterday")
    if key == "this_week":  # ISO week, Monday start
        start = today - timedelta(days=today.weekday())
        return DateRange(start, today, "this_week")
    if key == "last_week":
        start = today - timedelta(days=today.weekday() + 7)
        return DateRange(start, start + timedelta(days=6), "last_week")
    if key == "this_month":
        return DateRange(month_start(today), today, "this_month")
    if key == "last_month":
        start = add_months(month_start(today), -1)
        return DateRange(start, month_end(start), "last_month")
    if key == "this_quarter":
        return DateRange(quarter_start(today), today, "this_quarter")
    if key == "last_quarter":
        start = add_months(quarter_start(today), -3)
        return DateRange(start, month_end(add_months(start, 2)), "last_quarter")
    if key == "ytd":
        return DateRange(date(today.year, 1, 1), today, "ytd")
    if key == "last_year":
        return DateRange(date(today.year - 1, 1, 1), date(today.year - 1, 12, 31), "last_year")
    if key == "all_time":
        return DateRange(ALL_TIME_START, today, "all_time")

    raise RangeError(f"Unknown range '{value}'. {RANGE_HELP}")


def parse_month(value: str | None, today: date | None = None) -> DateRange:
    """Resolve ``YYYY-MM``, ``last_month`` or ``this_month`` into a full-month range.

    ``this_month`` ends today (month to date); everything else is a full calendar month.
    """
    today = today or date.today()
    raw = (value or "").strip() or "last_month"

    if m := _MONTH_RE.match(raw):
        return _month_range(int(m.group(1)), int(m.group(2)))

    key = _normalize_keyword(raw)
    if key == "last_month":
        start = add_months(month_start(today), -1)
        return DateRange(start, month_end(start), start.strftime("%Y-%m"))
    if key == "this_month":
        start = month_start(today)
        return DateRange(start, today, start.strftime("%Y-%m"))

    raise RangeError(f"Unknown month '{value}'. {MONTH_HELP}")


def previous_period(rng: DateRange) -> DateRange:
    """The period of equal length immediately before ``rng`` (for % change)."""
    end = rng.start - timedelta(days=1)
    return DateRange(end - timedelta(days=rng.days - 1), end, f"previous_{rng.days}_days")
