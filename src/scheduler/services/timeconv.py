"""Conversion between integer time units and calendar datetimes.

The engine only knows integer units counted from 0. A scenario may carry a ``horizon_start`` date
and a ``time_unit_minutes`` length; this module is the single place that maps between the two.
Datetimes are naive (no time zone): unit 0 is midnight at the start of ``horizon_start``.
"""

from __future__ import annotations

import datetime as dt


def unit_to_datetime(horizon_start: dt.date, unit: int, time_unit_minutes: int) -> dt.datetime:
    """The datetime at which ``unit`` begins."""
    origin = dt.datetime.combine(horizon_start, dt.time.min)
    return origin + dt.timedelta(minutes=unit * time_unit_minutes)


def datetime_to_unit(horizon_start: dt.date, when: dt.datetime, time_unit_minutes: int) -> int:
    """The unit that begins at ``when``; raises ``ValueError`` if ``when`` is not on a boundary."""
    origin = dt.datetime.combine(horizon_start, dt.time.min)
    minutes, remainder = divmod((when - origin).total_seconds(), 60)
    if remainder != 0 or minutes % time_unit_minutes != 0:
        raise ValueError(f"{when.isoformat()} is not on a {time_unit_minutes}-minute boundary")
    return int(minutes // time_unit_minutes)
