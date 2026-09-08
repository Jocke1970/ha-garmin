"""Tests for deterministic recent-activity evaluation."""

from datetime import UTC, date, datetime

from ha_garmin.fitness import (
    ActivityDetailSample,
    ActivityMetrics,
    best_mean_power,
    evaluate_activity,
    parse_activity_detail_samples,
)


def _activity(
    *,
    activity_type: str = "virtual_ride",
    duration_minutes: float = 30.0,
    aerobic_te: float | None = 4.0,
    anaerobic_te: float | None = 0.5,
    max_hr: float | None = 185.0,
) -> ActivityMetrics:
    return ActivityMetrics(
        activity_id=123,
        calendar_date=date(2026, 9, 8),
        start_time=datetime(2026, 9, 8, 18, tzinfo=UTC),
        activity_type=activity_type,
        duration_minutes=duration_minutes,
        distance_meters=15000.0,
        avg_hr=150.0,
        max_hr=max_hr,
        calories=400.0,
        aerobic_training_effect=aerobic_te,
        anaerobic_training_effect=anaerobic_te,
        garmin_training_load=80.0,
        vo2max=None,
        avg_power=220.0,
        normalized_power=235.0,
    )


def test_parse_activity_detail_samples_uses_descriptor_indexes() -> None:
    details = {
        "metricDescriptors": [
            {"key": "directHeartRate", "metricsIndex": 2},
            {"key": "directTimestamp", "metricsIndex": 0},
            {"key": "directPower", "metricsIndex": 1},
        ],
        "activityDetailMetrics": [
            {"metrics": [1_757_353_200_000, 180, 130]},
            {"metrics": [1_757_353_201_000, 190, 132]},
            {"metrics": [1_757_353_202_000, 200, 134]},
        ],
    }

    samples = parse_activity_detail_samples(details)

    assert [sample.elapsed_seconds for sample in samples] == [0.0, 1.0, 2.0]
    assert [sample.power_watts for sample in samples] == [180.0, 190.0, 200.0]
    assert [sample.heart_rate for sample in samples] == [130.0, 132.0, 134.0]


def test_best_mean_power_requires_window_coverage() -> None:
    samples = tuple(
        ActivityDetailSample(
            elapsed_seconds=float(second),
            power_watts=260.0 if second < 1200 else 200.0,
            heart_rate=None,
        )
        for second in range(1501)
    )

    assert best_mean_power(samples, 300) == 260.0
    assert best_mean_power(samples, 1200) == 260.0
    assert best_mean_power(samples, 1800) is None


def test_evaluate_activity_builds_cycling_performance_estimates() -> None:
    samples = tuple(
        ActivityDetailSample(
            elapsed_seconds=float(second),
            power_watts=260.0 if second < 1200 else 200.0,
            heart_rate=170.0,
        )
        for second in range(1501)
    )

    result = evaluate_activity(
        _activity(),
        detail_samples=samples,
        body_weight_kg=70.0,
        user_max_hr=195.0,
    )

    assert result.assessment_id == "aerobic_development"
    assert result.best_5m_power == 260.0
    assert result.best_20m_power == 260.0
    assert result.estimated_vo2max == 47.1
    assert result.estimated_ftp_watts == 247
    assert result.vo2max_confidence == "high"
    assert result.ftp_confidence == "high"
    assert result.performance_confidence == "high"


def test_short_aerobic_activity_remains_valid_without_performance_estimate() -> None:
    result = evaluate_activity(
        _activity(
            duration_minutes=7.1,
            aerobic_te=2.3,
            anaerobic_te=0.4,
            max_hr=151.0,
        ),
        body_weight_kg=70.0,
        user_max_hr=195.0,
    )

    assert result.assessment_id == "short_aerobic"
    assert result.title_key == "activity_eval_short_aerobic_title"
    assert result.estimated_vo2max is None
    assert result.estimated_ftp_watts is None
    assert result.performance_confidence == "unavailable"


def test_non_cycling_activity_never_invents_cycling_estimates() -> None:
    samples = tuple(
        ActivityDetailSample(float(second), 300.0, 175.0) for second in range(1501)
    )

    result = evaluate_activity(
        _activity(activity_type="rowing_v2"),
        detail_samples=samples,
        body_weight_kg=70.0,
        user_max_hr=195.0,
    )

    assert result.estimated_vo2max is None
    assert result.estimated_ftp_watts is None
    assert result.performance_confidence == "unavailable"
