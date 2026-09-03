from datetime import UTC, date, datetime

import pytest

from ha_garmin.fitness import (
    analyze_garmin_load_coverage,
    build_daily_garmin_load_series,
    normalize_activities,
    normalize_activity,
)


def test_normalize_activity_maps_garmin_fields():
    activity = normalize_activity(
        {
            "activityId": 123,
            "startTimeGMT": "2026-09-01T10:15:00",
            "activityType": {"typeKey": "walking"},
            "duration": 1800,
            "distance": 2500,
            "averageHR": 101,
            "maxHR": 124,
            "calories": 180,
            "activityTrainingLoad": 7.5,
            "aerobicTrainingEffect": 1.2,
            "anaerobicTrainingEffect": 0.0,
            "vO2MaxValue": 41.2,
        }
    )

    assert activity.activity_id == 123
    assert activity.calendar_date == date(2026, 9, 1)
    assert activity.start_time == datetime(2026, 9, 1, 10, 15, tzinfo=UTC)
    assert activity.activity_type == "walking"
    assert activity.duration_minutes == 30.0
    assert activity.garmin_training_load == 7.5


def test_normalize_activities_deduplicates_activity_id():
    raw = [
        {
            "activityId": 2,
            "startTimeGMT": "2026-09-02T10:00:00",
            "duration": 600,
        },
        {
            "activityId": 1,
            "startTimeGMT": "2026-09-01T10:00:00",
            "duration": 600,
        },
        {
            "activityId": 2,
            "startTimeGMT": "2026-09-02T10:00:00",
            "duration": 900,
        },
    ]

    normalized = normalize_activities(raw)

    assert [item.activity_id for item in normalized] == [1, 2]
    assert normalized[1].duration_minutes == 10.0


def test_load_coverage_distinguishes_missing_from_zero():
    activities = normalize_activities(
        [
            {
                "activityId": 1,
                "startTimeGMT": "2026-09-01T10:00:00",
                "activityTrainingLoad": 0,
            },
            {"activityId": 2, "startTimeGMT": "2026-09-02T10:00:00"},
        ]
    )

    coverage = analyze_garmin_load_coverage(activities)

    assert coverage.total_activities == 2
    assert coverage.activities_with_load == 1
    assert coverage.activities_without_load == 1
    assert coverage.coverage_percent == 50.0


def test_daily_series_zero_fills_real_rest_days():
    activities = normalize_activities(
        [
            {
                "activityId": 1,
                "startTimeGMT": "2026-09-01T10:00:00",
                "activityTrainingLoad": 6,
            }
        ]
    )

    series = build_daily_garmin_load_series(
        activities, date(2026, 9, 1), date(2026, 9, 3)
    )

    assert [day.load for day in series] == [6.0, 0, 0]
    assert all(day.complete for day in series)


def test_daily_series_marks_activity_day_incomplete_when_load_missing():
    activities = normalize_activities(
        [
            {
                "activityId": 1,
                "startTimeGMT": "2026-09-01T10:00:00",
                "activityTrainingLoad": 5,
            },
            {"activityId": 2, "startTimeGMT": "2026-09-01T17:00:00"},
        ]
    )

    day = build_daily_garmin_load_series(
        activities, date(2026, 9, 1), date(2026, 9, 1)
    )[0]

    assert day.activity_count == 2
    assert day.loaded_activity_count == 1
    assert day.known_load == 5.0
    assert day.load is None
    assert not day.complete


def test_daily_series_rejects_reverse_range():
    with pytest.raises(ValueError, match="start_date cannot be after end_date"):
        build_daily_garmin_load_series([], date(2026, 9, 2), date(2026, 9, 1))


def test_normalize_activity_requires_valid_identity_and_time():
    with pytest.raises(ValueError, match="activityId"):
        normalize_activity({"startTimeGMT": "2026-09-01T10:00:00"})
    with pytest.raises(ValueError, match="start timestamp"):
        normalize_activity({"activityId": 1})
