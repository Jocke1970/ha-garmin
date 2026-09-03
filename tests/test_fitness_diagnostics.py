from ha_garmin.fitness import (
    GARMIN_FITNESS_ALGORITHM_VERSION,
    compare_load_source_coverage,
    normalize_activities,
)


def test_algorithm_version_is_explicit():
    assert GARMIN_FITNESS_ALGORITHM_VERSION == 1


def test_source_coverage_comparison_is_side_by_side_without_selection():
    activities = normalize_activities(
        [
            {
                "activityId": 1,
                "startTimeLocal": "2026-08-01T08:00:00",
                "startTimeGMT": "2026-08-01T06:00:00",
                "activityType": {"typeKey": "walking"},
                "duration": 1800,
                "averageHR": 105,
                "activityTrainingLoad": 4.0,
            },
            {
                "activityId": 2,
                "startTimeLocal": "2026-08-02T08:00:00",
                "startTimeGMT": "2026-08-02T06:00:00",
                "activityType": {"typeKey": "walking"},
                "duration": 1800,
                "averageHR": 108,
            },
            {
                "activityId": 3,
                "startTimeLocal": "2026-08-03T08:00:00",
                "startTimeGMT": "2026-08-03T06:00:00",
                "activityType": {"typeKey": "strength_training"},
                "duration": 1200,
                "activityTrainingLoad": 8.0,
            },
        ]
    )

    comparison = compare_load_source_coverage(activities)

    assert comparison.garmin.coverage_percent == 66.7
    assert comparison.trimp.coverage_percent == 66.7
    assert [row.activity_type for row in comparison.by_activity_type] == [
        "strength_training",
        "walking",
    ]

    strength, walking = comparison.by_activity_type
    assert strength.garmin_load_percent == 100.0
    assert strength.trimp_input_percent == 0.0
    assert walking.garmin_load_percent == 50.0
    assert walking.trimp_input_percent == 100.0
