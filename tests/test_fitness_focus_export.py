from datetime import date, timedelta

import pytest

from ha_garmin.fitness import (
    build_training_history_from_daily_loads,
    classify_activity_focus,
    classify_load_focus,
    export_training_history_rows,
    normalize_activity,
)
from ha_garmin.fitness.models import DailyLoad


def _activity(
    activity_id: int,
    aerobic: float | None,
    anaerobic: float | None,
    load: float | None,
):
    return normalize_activity(
        {
            "activityId": activity_id,
            "startTimeLocal": f"2026-08-0{activity_id}T08:00:00",
            "startTimeGMT": f"2026-08-0{activity_id}T06:00:00",
            "duration": 1800,
            "aerobicTrainingEffect": aerobic,
            "anaerobicTrainingEffect": anaerobic,
            "activityTrainingLoad": load,
        }
    )


def test_activity_focus_classification():
    assert classify_activity_focus(_activity(1, 3.0, 1.0, 10.0)) == "aerobic"
    assert classify_activity_focus(_activity(2, 1.0, 3.0, 10.0)) == "anaerobic"
    assert classify_activity_focus(_activity(3, 2.0, 1.5, 10.0)) == "mixed"
    assert classify_activity_focus(_activity(4, None, None, 10.0)) == "unknown"
    assert classify_activity_focus(_activity(5, 0.0, 0.0, 10.0)) == "unknown"


def test_load_focus_uses_average_training_effect():
    activities = [
        _activity(1, 4.0, 1.0, None),
        _activity(2, 3.0, 1.0, None),
        _activity(3, 2.0, 1.0, None),
    ]

    summary = classify_load_focus(activities)

    assert summary.total_activities == 3
    assert summary.classified_activities == 3
    assert summary.average_aerobic_effect == 3.0
    assert summary.average_anaerobic_effect == 1.0
    assert summary.dominant_focus == "aerobic"
    assert summary.complete


def test_load_focus_excludes_missing_training_effect_without_turning_it_into_zero():
    activities = [
        _activity(1, 3.0, 1.0, None),
        _activity(2, None, None, None),
    ]

    summary = classify_load_focus(activities)

    assert summary.total_activities == 2
    assert summary.classified_activities == 1
    assert summary.average_aerobic_effect == 3.0
    assert summary.average_anaerobic_effect == 1.0
    assert summary.dominant_focus == "aerobic"
    assert not summary.complete


def test_load_focus_validates_dominance_ratio():
    with pytest.raises(ValueError, match="greater than 1"):
        classify_load_focus([_activity(1, 3.0, 1.0, 10.0)], dominance_ratio=1.0)


def test_export_rows_align_late_starting_acwr_and_ramp_rate():
    start = date(2026, 7, 1)
    daily = [
        DailyLoad(
            date=start + timedelta(days=index),
            activity_count=1,
            loaded_activity_count=1,
            known_load=10.0,
            load=10.0,
            complete=True,
        )
        for index in range(42)
    ]
    history = build_training_history_from_daily_loads("garmin", daily)

    rows = export_training_history_rows(history)

    assert len(rows) == 42
    assert rows[0].acwr is None
    assert rows[0].ramp_rate is None
    assert rows[7].ramp_rate == 0.0
    assert rows[27].acwr == 1.0
    assert rows[-1].ctl == 10.0
    assert rows[-1].atl == 10.0
    assert rows[-1].tsb == 0.0


def test_export_rejects_incomplete_history():
    daily = [
        DailyLoad(
            date=date(2026, 8, 1),
            activity_count=1,
            loaded_activity_count=0,
            known_load=0.0,
            load=None,
            complete=False,
        )
    ]
    history = build_training_history_from_daily_loads("garmin", daily)

    with pytest.raises(ValueError, match="incomplete"):
        export_training_history_rows(history)
