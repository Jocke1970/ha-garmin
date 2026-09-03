from datetime import UTC, date, datetime

import pytest

from ha_garmin.fitness.models import ActivityMetrics
from ha_garmin.fitness.trimp import build_daily_trimp_series, compute_trimp


def _activity(
    day: int, avg_hr: float | None = 140, minutes: float = 60
) -> ActivityMetrics:
    return ActivityMetrics(
        activity_id=day,
        calendar_date=date(2026, 9, day),
        start_time=datetime(2026, 9, day, 10, tzinfo=UTC),
        activity_type="walking",
        duration_minutes=minutes,
        distance_meters=None,
        avg_hr=avg_hr,
        max_hr=160,
        calories=None,
        aerobic_training_effect=None,
        anaerobic_training_effect=None,
        garmin_training_load=None,
        vo2max=None,
        avg_power=None,
        normalized_power=None,
    )


def test_compute_trimp_known_value():
    value = compute_trimp(_activity(1), resting_hr=60, user_max_hr=180, sex="male")
    assert value == pytest.approx(143.866, abs=0.001)


def test_compute_trimp_preserves_zero_intensity():
    value = compute_trimp(
        _activity(1, avg_hr=55), resting_hr=60, user_max_hr=180, sex="male"
    )
    assert value == 0.0


def test_compute_trimp_returns_none_for_missing_hr():
    assert (
        compute_trimp(
            _activity(1, avg_hr=None), resting_hr=60, user_max_hr=180, sex="male"
        )
        is None
    )


def test_compute_trimp_validates_hr_range():
    with pytest.raises(ValueError, match="greater than resting_hr"):
        compute_trimp(_activity(1), resting_hr=180, user_max_hr=180, sex="male")


def test_daily_trimp_zero_fills_rest_days():
    series = build_daily_trimp_series(
        [_activity(1, avg_hr=100, minutes=30)],
        date(2026, 9, 1),
        date(2026, 9, 2),
        {date(2026, 9, 1): 60},
        user_max_hr=180,
        sex="male",
    )
    assert series[0].load is not None
    assert series[1].load == 0.0
    assert series[1].complete


def test_daily_trimp_marks_missing_resting_hr_incomplete():
    day = build_daily_trimp_series(
        [_activity(1)],
        date(2026, 9, 1),
        date(2026, 9, 1),
        {},
        user_max_hr=180,
        sex="male",
    )[0]
    assert day.load is None
    assert not day.complete
    assert day.loaded_activity_count == 0
