from datetime import date

import pytest

from ha_garmin.fitness.models import DailyLoad
from ha_garmin.fitness.training import compute_ctl_atl_tsb


def _day(day: int, load: float | None, complete: bool = True) -> DailyLoad:
    return DailyLoad(
        date=date(2026, 9, day),
        activity_count=0 if load == 0 else 1,
        loaded_activity_count=0 if load in (0, None) else 1,
        known_load=0.0 if load is None else load,
        load=load,
        complete=complete,
    )


def test_empty_series_returns_empty():
    assert compute_ctl_atl_tsb([]) == []


def test_steady_load_stays_steady():
    series = compute_ctl_atl_tsb([_day(day, 10) for day in range(1, 8)])
    assert all(point.ctl == 10 for point in series)
    assert all(point.atl == 10 for point in series)
    assert all(point.tsb == 0 for point in series)


def test_load_spike_moves_atl_faster_than_ctl():
    days = [_day(day, 10) for day in range(1, 8)] + [_day(8, 100)]
    latest = compute_ctl_atl_tsb(days)[-1]
    assert latest.atl > latest.ctl
    assert latest.tsb < 0


def test_rest_after_load_decays_atl_faster_than_ctl():
    days = [_day(day, 20) for day in range(1, 8)] + [_day(8, 0)]
    latest = compute_ctl_atl_tsb(days)[-1]
    assert latest.ctl > latest.atl
    assert latest.tsb > 0


def test_incomplete_daily_load_is_rejected():
    with pytest.raises(ValueError, match="incomplete for 2026-09-02"):
        compute_ctl_atl_tsb([_day(1, 5), _day(2, None, complete=False)])


def test_date_gaps_are_rejected():
    with pytest.raises(ValueError, match="consecutive dates"):
        compute_ctl_atl_tsb([_day(1, 5), _day(3, 5)])
