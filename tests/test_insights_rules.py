"""Scenario tests for deterministic Garmin Insights Rules V1."""

from dataclasses import replace
from datetime import UTC, date, datetime

from ha_garmin.fitness import ActivityMetrics
from ha_garmin.insights import (
    INSIGHT_RULESET_VERSION,
    DailyRecoveryMetrics,
    InsightDataQuality,
    InsightResult,
    InsightSnapshot,
    LoadFocusSnapshot,
    TrainingSnapshot,
    evaluate_insights,
)

_DAY = date(2026, 9, 7)


def _activity(
    activity_id: int,
    *,
    day: date = _DAY,
    aerobic: float | None = 2.0,
    anaerobic: float | None = 0.2,
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


def _recovery() -> DailyRecoveryMetrics:
    return DailyRecoveryMetrics(
        date=_DAY,
        resting_hr=48.0,
        resting_hr_7d_avg=50.0,
        hrv_status="BALANCED",
        hrv_last_night_avg=46.0,
        hrv_baseline_balanced_low=40.0,
        hrv_baseline_balanced_upper=52.0,
        sleep_score=82.0,
        body_battery_most_recent=72.0,
        average_stress_level=24.0,
        training_readiness=76.0,
        recovery_minutes=480.0,
        summary_available=True,
        sleep_available=True,
        hrv_available=True,
        readiness_available=True,
    )


def _training() -> TrainingSnapshot:
    return TrainingSnapshot(
        date=_DAY,
        source="trimp",
        algorithm_version=4,
        ready=True,
        daily_load=40.0,
        ctl=40.0,
        atl=40.0,
        tsb=0.0,
        acwr=1.0,
        ramp_rate=1.0,
        strain=6.0,
    )


def _quality() -> InsightDataQuality:
    return InsightDataQuality(
        complete=True,
        recovery_current=True,
        training_complete=True,
        load_focus_complete=True,
    )


def _snapshot(
    *,
    recovery: DailyRecoveryMetrics | None = None,
    training: TrainingSnapshot | None = None,
    quality: InsightDataQuality | None = None,
    activities: tuple[ActivityMetrics, ...] = (),
) -> InsightSnapshot:
    return InsightSnapshot(
        as_of=datetime(2026, 9, 7, 8, tzinfo=UTC),
        recovery=recovery or _recovery(),
        training=training or _training(),
        load_focus=LoadFocusSnapshot(
            date=_DAY,
            activity_count=0,
            covered_activities=0,
            complete=True,
            low_aerobic=0.0,
            high_aerobic=0.0,
            anaerobic=0.0,
        ),
        recent_activities=activities,
        data_quality=quality or _quality(),
    )


def _by_id(snapshot: InsightSnapshot) -> dict[str, InsightResult]:
    return {result.id: result for result in evaluate_insights(snapshot)}


def test_favourable_training_signal_requires_multiple_current_inputs() -> None:
    results = evaluate_insights(_snapshot())
    favourable = next(
        result for result in results if result.id == "favourable_training_signal"
    )

    assert favourable.severity == "positive"
    assert favourable.confidence == "high"
    assert favourable.ruleset_version == INSIGHT_RULESET_VERSION
    assert favourable.title_key == "insights.favourable_training_signal.title"
    assert {item.code for item in favourable.evidence} >= {
        "training_readiness_good",
        "sleep_score_good",
        "hrv_balanced",
    }


def test_recovery_caution_requires_two_independent_negative_signals() -> None:
    recovery = replace(
        _recovery(),
        training_readiness=32.0,
        sleep_score=52.0,
        hrv_status="BALANCED",
        body_battery_most_recent=65.0,
    )
    results = _by_id(_snapshot(recovery=recovery))

    caution = results["recovery_caution"]
    assert caution.severity == "caution"
    assert caution.confidence == "medium"
    assert "favourable_training_signal" not in results


def test_load_spike_suppresses_positive_signal() -> None:
    training = replace(
        _training(),
        acwr=1.7,
        ramp_rate=4.0,
        atl=55.0,
        ctl=40.0,
    )
    results = _by_id(_snapshot(training=training))

    spike = results["load_spike"]
    assert spike.severity == "caution"
    assert spike.confidence == "high"
    assert "favourable_training_signal" not in results


def test_extreme_load_spike_is_warning() -> None:
    training = replace(_training(), acwr=1.9)
    results = _by_id(_snapshot(training=training))

    assert results["load_spike"].severity == "warning"


def test_low_recent_load_needs_supporting_decline_or_sparse_week() -> None:
    training = replace(_training(), acwr=0.3, ramp_rate=-3.0)
    results = _by_id(_snapshot(training=training, activities=(_activity(1),)))

    low = results["low_recent_load"]
    assert low.severity == "info"
    assert low.confidence == "high"
    assert {item.code for item in low.evidence} >= {
        "acwr_below_low_load_threshold",
        "negative_ramp_rate",
        "sparse_recent_activity_window",
    }


def test_stale_recovery_is_reported_and_not_evaluated_as_current() -> None:
    stale_recovery = replace(_recovery(), date=date(2026, 9, 6))
    quality = InsightDataQuality(
        complete=False,
        recovery_current=False,
        training_complete=True,
        load_focus_complete=True,
        stale_fields=("recovery",),
    )
    results = evaluate_insights(_snapshot(recovery=stale_recovery, quality=quality))
    ids = [result.id for result in results]

    assert ids[0] == "insufficient_or_stale_data"
    assert "recovery_caution" not in ids
    assert "favourable_training_signal" not in ids


def test_recent_load_focus_imbalance_requires_complete_recent_te_window() -> None:
    activities = (
        _activity(1, day=date(2026, 9, 5), aerobic=2.2, anaerobic=0.1),
        _activity(2, day=date(2026, 9, 6), aerobic=2.4, anaerobic=0.1),
        _activity(3, day=_DAY, aerobic=2.0, anaerobic=0.2),
    )
    results = _by_id(_snapshot(activities=activities))

    imbalance = results["load_focus_imbalance"]
    assert imbalance.severity == "info"
    assert any(item.code == "dominant_focus.low_aerobic" for item in imbalance.evidence)

    incomplete = (*activities, _activity(4, aerobic=None, anaerobic=0.5))
    incomplete_results = _by_id(_snapshot(activities=incomplete))
    assert "load_focus_imbalance" not in incomplete_results


def test_result_ordering_is_priority_then_stable_id() -> None:
    training = replace(_training(), acwr=1.7, ramp_rate=3.0)
    quality = InsightDataQuality(
        complete=False,
        recovery_current=True,
        training_complete=True,
        load_focus_complete=False,
        missing_fields=("load_focus.anaerobic",),
    )
    results = evaluate_insights(_snapshot(training=training, quality=quality))

    assert [result.id for result in results[:2]] == [
        "insufficient_or_stale_data",
        "load_spike",
    ]
