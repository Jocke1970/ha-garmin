"""Tests for canonical deterministic InsightSnapshot input."""

from datetime import UTC, date, datetime

import pytest

from ha_garmin.fitness import (
    ActivityMetrics,
    AcwrPoint,
    DailyLoad,
    LoadSeriesAssessment,
    RampRatePoint,
    TrainingHistoryResult,
    TrainingLoadPoint,
)
from ha_garmin.insights import DailyRecoveryMetrics, build_insight_snapshot


def _activity(
    activity_id: int,
    day: date,
    *,
    aerobic: float | None = 2.0,
    anaerobic: float | None = 0.5,
) -> ActivityMetrics:
    return ActivityMetrics(
        activity_id=activity_id,
        calendar_date=day,
        start_time=datetime(day.year, day.month, day.day, 12, tzinfo=UTC),
        activity_type="cycling",
        duration_minutes=60.0,
        distance_meters=20000.0,
        avg_hr=135.0,
        max_hr=165.0,
        calories=500.0,
        aerobic_training_effect=aerobic,
        anaerobic_training_effect=anaerobic,
        garmin_training_load=80.0,
        vo2max=44.0,
        avg_power=150.0,
        normalized_power=165.0,
    )


def _history(day: date, *, point_date: date | None = None) -> TrainingHistoryResult:
    point_day = point_date or day
    return TrainingHistoryResult(
        source="trimp",
        algorithm_version=4,
        assessment=LoadSeriesAssessment(
            total_days=28,
            activity_days=8,
            rest_days=20,
            complete_days=28,
            incomplete_days=(),
            ready=True,
        ),
        daily_loads=(
            DailyLoad(
                date=point_day,
                activity_count=1,
                loaded_activity_count=1,
                known_load=50.0,
                load=50.0,
                complete=True,
            ),
        ),
        training_points=(
            TrainingLoadPoint(
                date=point_day,
                daily_load=50.0,
                ctl=40.0,
                atl=45.0,
                tsb=-5.0,
            ),
        ),
        acwr_points=(
            AcwrPoint(
                date=point_day,
                acute_average=45.0,
                chronic_average=40.0,
                acwr=1.125,
            ),
        ),
        ramp_rate_points=(
            RampRatePoint(
                date=point_day,
                ctl=40.0,
                ctl_7d_ago=37.0,
                ramp_rate=3.0,
            ),
        ),
    )


def _recovery(day: date) -> DailyRecoveryMetrics:
    return DailyRecoveryMetrics(
        date=day,
        resting_hr=48.0,
        resting_hr_7d_avg=50.0,
        hrv_status="BALANCED",
        hrv_weekly_avg=45.0,
        hrv_last_night_avg=46.0,
        hrv_baseline_balanced_low=40.0,
        hrv_baseline_balanced_upper=52.0,
        sleep_score=82.0,
        sleep_minutes=440.0,
        sleep_need_minutes=450.0,
        average_stress_level=24.0,
        body_battery_most_recent=72.0,
        body_battery_high=80.0,
        body_battery_low=20.0,
        training_readiness=71.0,
        morning_training_readiness=76.0,
        recovery_minutes=480.0,
        summary_available=True,
        sleep_available=True,
        hrv_available=True,
        readiness_available=True,
        morning_readiness_available=True,
    )


def test_build_insight_snapshot_complete_exact_date() -> None:
    day = date(2026, 9, 5)
    older = _activity(1, date(2026, 8, 20))
    current = _activity(2, day)

    snapshot = build_insight_snapshot(
        datetime(2026, 9, 5, 8, tzinfo=UTC),
        recovery=_recovery(day),
        training_history=_history(day),
        activities=(older, current),
    )

    assert snapshot.training.daily_load == 50.0
    assert snapshot.training.ctl == 40.0
    assert snapshot.training.acwr == 1.125
    assert snapshot.training.ramp_rate == 3.0
    assert snapshot.training.strain is not None
    assert snapshot.load_focus.complete is True
    assert snapshot.load_focus.low_aerobic == 2.0
    assert snapshot.load_focus.anaerobic == 0.5
    assert [activity.activity_id for activity in snapshot.recent_activities] == [2]
    assert snapshot.data_quality.complete is True
    assert snapshot.data_quality.missing_fields == ()
    assert snapshot.data_quality.stale_fields == ()


def test_stale_recovery_is_carried_but_explicitly_flagged() -> None:
    day = date(2026, 9, 5)
    snapshot = build_insight_snapshot(
        datetime(2026, 9, 5, 8, tzinfo=UTC),
        recovery=_recovery(date(2026, 9, 4)),
        training_history=_history(day),
    )

    assert snapshot.recovery.date == date(2026, 9, 4)
    assert snapshot.data_quality.recovery_current is False
    assert snapshot.data_quality.stale_fields == ("recovery",)
    assert snapshot.data_quality.complete is False


def test_snapshot_never_borrows_previous_training_point() -> None:
    day = date(2026, 9, 5)
    snapshot = build_insight_snapshot(
        datetime(2026, 9, 5, 8, tzinfo=UTC),
        recovery=_recovery(day),
        training_history=_history(day, point_date=date(2026, 9, 4)),
    )

    assert snapshot.training.daily_load is None
    assert snapshot.training.ctl is None
    assert snapshot.training.ready is False
    assert snapshot.data_quality.training_complete is False
    assert "training.daily_load" in snapshot.data_quality.missing_fields
    assert "training.ctl" in snapshot.data_quality.missing_fields


def test_incomplete_load_focus_is_reported_without_zero_fill() -> None:
    day = date(2026, 9, 5)
    activity = _activity(3, day, aerobic=None, anaerobic=1.5)

    snapshot = build_insight_snapshot(
        datetime(2026, 9, 5, 8, tzinfo=UTC),
        recovery=_recovery(day),
        training_history=_history(day),
        activities=(activity,),
    )

    assert snapshot.load_focus.complete is False
    assert snapshot.load_focus.low_aerobic is None
    assert snapshot.load_focus.high_aerobic is None
    assert snapshot.load_focus.anaerobic is None
    assert snapshot.data_quality.load_focus_complete is False
    assert "load_focus.anaerobic" in snapshot.data_quality.missing_fields
    assert snapshot.data_quality.complete is False


def test_snapshot_requires_timezone_aware_as_of() -> None:
    day = date(2026, 9, 5)
    with pytest.raises(ValueError, match="timezone-aware"):
        build_insight_snapshot(
            datetime(2026, 9, 5, 8),
            recovery=_recovery(day),
            training_history=_history(day),
        )
