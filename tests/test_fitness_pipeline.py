from datetime import date, timedelta

from ha_garmin.fitness import (
    build_garmin_training_history,
    build_training_history_from_daily_loads,
    build_trimp_training_history,
    normalize_activities,
)
from ha_garmin.fitness.models import DailyLoad


def _complete_daily_loads(days: int) -> list[DailyLoad]:
    start = date(2026, 8, 1)
    return [
        DailyLoad(
            date=start + timedelta(days=index),
            activity_count=1,
            loaded_activity_count=1,
            known_load=10.0,
            load=10.0,
            complete=True,
        )
        for index in range(days)
    ]


def test_pipeline_builds_all_metrics_for_complete_series():
    result = build_training_history_from_daily_loads(
        "garmin", _complete_daily_loads(42)
    )

    assert result.assessment.ready
    assert result.assessment.total_days == 42
    assert len(result.training_points) == 42
    assert len(result.acwr_points) == 15
    assert len(result.ramp_rate_points) == 35
    assert result.training_points[-1].ctl == 10.0
    assert result.training_points[-1].atl == 10.0
    assert result.training_points[-1].tsb == 0.0
    assert result.acwr_points[-1].acwr == 1.0
    assert result.ramp_rate_points[-1].ramp_rate == 0.0


def test_pipeline_returns_diagnostics_instead_of_deriving_from_incomplete_load():
    loads = _complete_daily_loads(10)
    blocked = loads[4]
    loads[4] = DailyLoad(
        date=blocked.date,
        activity_count=1,
        loaded_activity_count=0,
        known_load=0.0,
        load=None,
        complete=False,
    )

    result = build_training_history_from_daily_loads("garmin", loads)

    assert not result.assessment.ready
    assert result.assessment.incomplete_days == (date(2026, 8, 5),)
    assert result.training_points == ()
    assert result.acwr_points == ()
    assert result.ramp_rate_points == ()


def test_garmin_pipeline_reports_load_coverage_and_rest_days():
    raw = [
        {
            "activityId": 1,
            "startTimeLocal": "2026-08-01T08:00:00",
            "startTimeGMT": "2026-08-01T06:00:00",
            "duration": 1800,
            "activityTrainingLoad": 6,
        },
        {
            "activityId": 2,
            "startTimeLocal": "2026-08-03T08:00:00",
            "startTimeGMT": "2026-08-03T06:00:00",
            "duration": 1200,
        },
    ]

    result = build_garmin_training_history(raw, date(2026, 8, 1), date(2026, 8, 3))

    assert result.load_coverage.total_activities == 2
    assert result.load_coverage.activities_with_load == 1
    assert result.load_coverage.coverage_percent == 50.0
    assert result.history.assessment.activity_days == 2
    assert result.history.assessment.rest_days == 1
    assert result.history.assessment.incomplete_days == (date(2026, 8, 3),)
    assert not result.history.assessment.ready


def test_trimp_pipeline_is_independent_of_garmin_load_field():
    activities = normalize_activities(
        [
            {
                "activityId": 1,
                "startTimeLocal": "2026-08-01T08:00:00",
                "startTimeGMT": "2026-08-01T06:00:00",
                "duration": 1800,
                "averageHR": 120,
            }
        ]
    )
    resting = {date(2026, 8, 1): 60.0}

    result = build_trimp_training_history(
        activities,
        date(2026, 8, 1),
        date(2026, 8, 2),
        resting,
        user_max_hr=180,
        sex="male",
    )

    assert result.source == "trimp"
    assert result.assessment.ready
    assert result.daily_loads[0].load is not None
    assert result.daily_loads[1].load == 0.0
    assert len(result.training_points) == 2
