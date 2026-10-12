"""Unit tests for friendly date ranges (no database needed)."""

from __future__ import annotations

from datetime import date

import pytest

from salestalk_mcp.ranges import (
    DateRange,
    RangeError,
    add_months,
    parse_month,
    parse_range,
    previous_period,
    quarter_start,
)

TODAY = date(2026, 10, 11)  # a Sunday in Q4


def r(value: str, today: date = TODAY) -> tuple[date, date]:
    rng = parse_range(value, today)
    return rng.start, rng.end


# --------------------------------------------------------------------------- presets


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("today", (date(2026, 10, 11), date(2026, 10, 11))),
        ("yesterday", (date(2026, 10, 10), date(2026, 10, 10))),
        ("this_week", (date(2026, 10, 5), date(2026, 10, 11))),
        ("last_week", (date(2026, 9, 28), date(2026, 10, 4))),
        ("this_month", (date(2026, 10, 1), date(2026, 10, 11))),
        ("last_month", (date(2026, 9, 1), date(2026, 9, 30))),
        ("this_quarter", (date(2026, 10, 1), date(2026, 10, 11))),
        ("last_quarter", (date(2026, 7, 1), date(2026, 9, 30))),
        ("ytd", (date(2026, 1, 1), date(2026, 10, 11))),
        ("last_year", (date(2025, 1, 1), date(2025, 12, 31))),
        ("last_7_days", (date(2026, 10, 5), date(2026, 10, 11))),
        ("last_30_days", (date(2026, 9, 12), date(2026, 10, 11))),
        ("last_90_days", (date(2026, 7, 14), date(2026, 10, 11))),
        ("last_12_months", (date(2025, 10, 12), date(2026, 10, 11))),
        ("last_3_months", (date(2026, 7, 12), date(2026, 10, 11))),
        ("last_1_days", (date(2026, 10, 11), date(2026, 10, 11))),
    ],
)
def test_presets(value: str, expected: tuple[date, date]) -> None:
    assert r(value) == expected


@pytest.mark.parametrize(
    ("alias", "canonical"),
    [
        ("Last Month", "last_month"),
        ("last-month", "last_month"),
        ("  LAST_MONTH  ", "last_month"),
        ("previous_month", "last_month"),
        ("mtd", "this_month"),
        ("qtd", "this_quarter"),
        ("this year", "ytd"),
        ("year_to_date", "ytd"),
        ("ttm", "last_12_months"),
        ("past 30 days", "last_30_days"),
        ("past_year", "last_12_months"),
    ],
)
def test_aliases(alias: str, canonical: str) -> None:
    assert r(alias) == r(canonical)


def test_empty_uses_default() -> None:
    assert parse_range(None, TODAY, default="last_month").label == "last_month"
    assert parse_range("", TODAY).label == "last_30_days"


def test_all_time() -> None:
    start, end = r("all_time")
    assert start.year == 2000 and end == TODAY


# --------------------------------------------------------------------------- explicit


@pytest.mark.parametrize(
    "value",
    ["2026-01-01..2026-03-31", "2026-01-01 .. 2026-03-31", "2026-01-01 to 2026-03-31", "2026-01-01/2026-03-31"],
)
def test_explicit_range_separators(value: str) -> None:
    assert r(value) == (date(2026, 1, 1), date(2026, 3, 31))


def test_explicit_range_label_and_days() -> None:
    rng = parse_range("2026-02-01..2026-02-28", TODAY)
    assert rng.label == "2026-02-01..2026-02-28"
    assert rng.days == 28
    assert rng.end_exclusive == date(2026, 3, 1)


def test_single_day_month_quarter_year() -> None:
    assert r("2026-05-17") == (date(2026, 5, 17), date(2026, 5, 17))
    assert r("2026-02") == (date(2026, 2, 1), date(2026, 2, 28))
    assert r("2024-02") == (date(2024, 2, 1), date(2024, 2, 29))  # leap year
    assert r("2026-Q3") == (date(2026, 7, 1), date(2026, 9, 30))
    assert r("2026q1") == (date(2026, 1, 1), date(2026, 3, 31))
    assert r("2025") == (date(2025, 1, 1), date(2025, 12, 31))


@pytest.mark.parametrize(
    "value",
    [
        "2026-03-31..2026-01-01",  # start after end
        "2026-02-30..2026-03-01",  # invalid date
        "2026-13",  # invalid month
        "2026-00",
        "2026-Q5",
        "next_month",
        "last_0_days",
        "last_99999_days",
        "since forever",
        "1990-01-01..2026-01-01",  # longer than 20 years
        "'; DROP TABLE orders; --",
    ],
)
def test_invalid_ranges(value: str) -> None:
    with pytest.raises(RangeError):
        parse_range(value, TODAY)


def test_error_lists_options() -> None:
    with pytest.raises(RangeError, match="last_month"):
        parse_range("blah", TODAY)


# --------------------------------------------------------------------------- boundaries


def test_last_month_in_january_crosses_year() -> None:
    assert r("last_month", date(2026, 1, 15)) == (date(2025, 12, 1), date(2025, 12, 31))


def test_last_quarter_in_q1_crosses_year() -> None:
    assert r("last_quarter", date(2026, 2, 10)) == (date(2025, 10, 1), date(2025, 12, 31))


def test_this_quarter_on_first_day() -> None:
    assert r("this_quarter", date(2026, 4, 1)) == (date(2026, 4, 1), date(2026, 4, 1))


def test_last_month_from_march_31() -> None:
    assert r("last_month", date(2024, 3, 31)) == (date(2024, 2, 1), date(2024, 2, 29))


def test_last_12_months_on_leap_day() -> None:
    assert r("last_12_months", date(2028, 2, 29)) == (date(2027, 3, 1), date(2028, 2, 29))


# --------------------------------------------------------------------------- months


@pytest.mark.parametrize(
    ("value", "expected", "label"),
    [
        ("last_month", (date(2026, 9, 1), date(2026, 9, 30)), "2026-09"),
        ("previous month", (date(2026, 9, 1), date(2026, 9, 30)), "2026-09"),
        ("this_month", (date(2026, 10, 1), date(2026, 10, 11)), "2026-10"),
        ("2026-02", (date(2026, 2, 1), date(2026, 2, 28)), "2026-02"),
        ("2025-12", (date(2025, 12, 1), date(2025, 12, 31)), "2025-12"),
        (None, (date(2026, 9, 1), date(2026, 9, 30)), "2026-09"),
    ],
)
def test_parse_month(value: str | None, expected: tuple[date, date], label: str) -> None:
    rng = parse_month(value, TODAY)
    assert (rng.start, rng.end) == expected
    assert rng.label == label


@pytest.mark.parametrize("value", ["2026-13", "september", "last_quarter", "2026-09-01", "2026"])
def test_parse_month_invalid(value: str) -> None:
    with pytest.raises(RangeError):
        parse_month(value, TODAY)


# --------------------------------------------------------------------------- helpers


def test_add_months_clamps_day() -> None:
    assert add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert add_months(date(2026, 3, 15), -3) == date(2025, 12, 15)
    assert add_months(date(2026, 12, 1), 1) == date(2027, 1, 1)


def test_quarter_start() -> None:
    assert quarter_start(date(2026, 11, 30)) == date(2026, 10, 1)
    assert quarter_start(date(2026, 3, 31)) == date(2026, 1, 1)


def test_previous_period_same_length() -> None:
    prev = previous_period(parse_range("2026-07-01..2026-09-30", TODAY))
    assert (prev.start, prev.end) == (date(2026, 3, 31), date(2026, 6, 30))
    assert prev.days == 92


def test_date_range_validates_order() -> None:
    with pytest.raises(RangeError):
        DateRange(date(2026, 2, 1), date(2026, 1, 1), "bad")


def test_to_dict() -> None:
    assert parse_range("last_month", TODAY).to_dict() == {
        "label": "last_month",
        "start": "2026-09-01",
        "end": "2026-09-30",
        "days": 30,
    }
