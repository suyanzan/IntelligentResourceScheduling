import datetime as dt

import pytest

from scheduler.services.timeconv import datetime_to_unit, unit_to_datetime

START = dt.date(2026, 1, 5)


def test_unit_zero_is_midnight_of_the_start_date() -> None:
    assert unit_to_datetime(START, 0, 60) == dt.datetime(2026, 1, 5, 0, 0)


@pytest.mark.parametrize("minutes", [15, 30, 60, 120, 1440])
@pytest.mark.parametrize("unit", [0, 1, 7, 24, 100, 336])
def test_round_trip(unit: int, minutes: int) -> None:
    assert datetime_to_unit(START, unit_to_datetime(START, unit, minutes), minutes) == unit


def test_known_values() -> None:
    assert unit_to_datetime(START, 30, 60) == dt.datetime(2026, 1, 6, 6, 0)
    assert unit_to_datetime(START, 3, 30) == dt.datetime(2026, 1, 5, 1, 30)
    assert datetime_to_unit(START, dt.datetime(2026, 1, 6, 6, 0), 60) == 30


def test_off_boundary_is_rejected() -> None:
    with pytest.raises(ValueError, match="boundary"):
        datetime_to_unit(START, dt.datetime(2026, 1, 5, 0, 30), 60)
    with pytest.raises(ValueError, match="boundary"):
        datetime_to_unit(START, dt.datetime(2026, 1, 5, 1, 0, 30), 60)
