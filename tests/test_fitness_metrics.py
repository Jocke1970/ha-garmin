from datetime import date, timedelta

import pytest

from ha_garmin.fitness.metrics import compute_acwr, compute_ramp_rate
from ha_garmin.fitness.models import DailyLoad, TrainingLoadPoint


def _daily_loads(
    values: list[float], start: date = date(2026, 8, 1)
) -> list[DailyLoad]:
    return [
        DailyLoad(
            date=start + timedelta(days=index),
            activity_count=0 if value == 0 else 1,
            loaded_activity_count=0 if value == 0 else 1,
            known_load=value,
            load=value,
            complete=True,
        )
        for index, value in enumerate(values)
    ]


def test_acwr_requires_full_chronic_window():
    assert compute_acwr(_daily_loads([10.0] * 27)) == []

    result = compute_acwr(_daily_loads([10.0] * 28))

    assert len(result) == 1
    assert result[0].acute_average == 10.0
    assert result[0].chronic_average == 10.0
    assert result[0].acwr == 1.0


def test_acwr_uses_rolling_averages_not_raw_window_sums():
    loads = [10.0] * 21 + [20.0] * 7

    point = compute_acwr(_daily_loads(loads))[0]

    assert point.acute_average == 20.0
    assert point.chronic_average == 12.5
    assert point.acwr == 1.6


def test_acwr_returns_none_for_zero_chronic_load():
    point = compute_acwr(_daily_loads([0.0] * 28))[0]
    assert point.acwr is None


def test_acwr_rejects_incomplete_or_gapped_series():
    incomplete = _daily_loads([1.0] * 28)
    day = incomplete[10]
    incomplete[10] = DailyLoad(
        date=day.date,
        activity_count=1,
        loaded_activity_count=0,
        known_load=0.0,
        load=None,
        complete=False,
    )
    with pytest.raises(ValueError, match="incomplete"):
        compute_acwr(incomplete)

    gapped = _daily_loads([1.0] * 28)
    gapped.pop(5)
    with pytest.raises(ValueError, match="consecutive"):
        compute_acwr(gapped)


def test_acwr_validates_windows():
    with pytest.raises(ValueError, match="positive"):
        compute_acwr([], acute_days=0, chronic_days=28)
    with pytest.raises(ValueError, match="smaller"):
        compute_acwr([], acute_days=28, chronic_days=28)


def test_ramp_rate_is_ctl_change_seven_days_earlier():
    start = date(2026, 8, 1)
    points = [
        TrainingLoadPoint(
            date=start + timedelta(days=index),
            daily_load=float(index),
            ctl=float(index * 2),
            atl=float(index * 3),
            tsb=float(-index),
        )
        for index in range(10)
    ]

    result = compute_ramp_rate(points)

    assert len(result) == 3
    assert result[0].date == date(2026, 8, 8)
    assert result[0].ctl == 14.0
    assert result[0].ctl_7d_ago == 0.0
    assert result[0].ramp_rate == 14.0


def test_ramp_rate_rejects_gaps_and_invalid_period():
    with pytest.raises(ValueError, match="positive"):
        compute_ramp_rate([], period_days=0)

    points = [
        TrainingLoadPoint(date=date(2026, 8, 1), daily_load=1, ctl=1, atl=1, tsb=0),
        TrainingLoadPoint(date=date(2026, 8, 3), daily_load=1, ctl=1, atl=1, tsb=0),
    ]
    with pytest.raises(ValueError, match="consecutive"):
        compute_ramp_rate(points)
