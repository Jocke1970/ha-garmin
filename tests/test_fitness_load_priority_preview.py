"""Regression tests for the optional, non-production Load Priority preview."""

from dataclasses import replace
from datetime import UTC, date, datetime

import pytest

from ha_garmin.fitness.load_priority_preview import preview_activity_load
from ha_garmin.fitness.models import ActivityMetrics
from ha_garmin.fitness.trimp import compute_trimp


def _activity(activity_type: str = "walking") -> ActivityMetrics:
    return ActivityMetrics(
        activity_id=123,
        calendar_date=date(2026, 9, 16),
        start_time=datetime(2026, 9, 16, 9, tzinfo=UTC),
        activity_type=activity_type,
        duration_minutes=30.0,
        distance_meters=3000.0,
        avg_hr=105.0,
        max_hr=125.0,
        calories=100.0,
        aerobic_training_effect=1.0,
        anaerobic_training_effect=0.0,
        garmin_training_load=14.4,
        vo2max=None,
        avg_power=150.0,
        normalized_power=180.0,
    )


def _context() -> dict[str, float | str]:
    return {"resting_hr": 48.0, "user_max_hr": 185.0, "sex": "male"}


def test_walking_prefers_hr_even_with_power_and_garmin_load():
    activity = _activity()
    result = preview_activity_load(activity, ftp_watts=200, **_context())
    assert result.sport == "walking"
    assert result.selected_method == "hr"
    assert result.value == compute_trimp(activity, 48, 185, "male")
    assert result.unit == "banister_trimp"
    assert not result.canonical_compatible


def test_cycling_prefers_normalized_power_when_ftp_available():
    result = preview_activity_load(
        _activity("virtual_ride"), ftp_watts=200, **_context()
    )
    assert result.sport == "cycling"
    assert result.selected_method == "power"
    assert result.value == pytest.approx(40.5)
    assert result.unit == "power_tss"
    assert len(result.attempts) == 1


def test_cycling_falls_back_to_hr_when_ftp_missing():
    result = preview_activity_load(_activity("cycling"), **_context())
    assert result.selected_method == "hr"
    assert result.attempts[0].reason == "missing_or_invalid_ftp"
    assert result.attempts[1].available


def test_normalized_power_is_required_and_average_power_is_not_substituted():
    activity = replace(_activity("cycling"), normalized_power=None)
    result = preview_activity_load(activity, ftp_watts=200, **_context())
    assert result.selected_method == "hr"
    assert result.attempts[0].reason == "missing_or_invalid_normalized_power"


def test_later_garmin_fallback_when_other_sources_lack_context():
    activity = replace(_activity("cycling"), avg_hr=None, distance_meters=None)
    result = preview_activity_load(activity)
    assert result.selected_method == "garmin"
    assert result.value == 14.4
    assert [attempt.available for attempt in result.attempts] == [
        False,
        False,
        False,
        True,
    ]


def test_zero_garmin_load_is_valid_not_missing():
    activity = replace(_activity(), garmin_training_load=0.0, avg_hr=None)
    result = preview_activity_load(activity)
    assert result.selected_method == "garmin"
    assert result.value == 0.0


def test_running_pace_needs_explicit_threshold_and_is_marked_uncalibrated():
    result = preview_activity_load(_activity("running"), threshold_speed_mps=3.0)
    assert result.selected_method == "pace"
    # 3 km / 30 min = 1.6667 m/s; 0.5 h * (1.6667 / 3)^2 * 100.
    assert result.value == pytest.approx(15.432, abs=0.001)
    assert result.unit == "pace_proxy_unvalidated"
    assert result.attempts[0].reason == "uncalibrated_pace_proxy"
    assert not result.canonical_compatible


def test_running_uses_hr_when_pace_threshold_missing():
    result = preview_activity_load(_activity("running"), **_context())
    assert result.selected_method == "hr"
    assert result.attempts[0].reason == "missing_or_invalid_threshold_speed"


def test_configurable_sport_priority_can_prefer_hr_over_power():
    result = preview_activity_load(
        _activity("road_biking"),
        profiles={"cycling": ("hr", "power", "garmin")},
        ftp_watts=200,
        **_context(),
    )
    assert result.selected_method == "hr"
    assert result.priority == ("hr", "power", "garmin")


def test_manual_override_is_strict_without_hidden_fallback():
    result = preview_activity_load(_activity("cycling"), override="power", **_context())
    assert result.selected_method is None
    assert result.value is None
    assert len(result.attempts) == 1
    assert result.attempts[0].reason == "missing_or_invalid_ftp"


def test_missing_all_sources_never_becomes_fake_rest_day():
    activity = replace(
        _activity("walking"),
        avg_hr=None,
        distance_meters=None,
        garmin_training_load=None,
    )
    result = preview_activity_load(activity)
    assert result.selected_method is None
    assert result.value is None
    assert result.unit is None
    assert not result.canonical_compatible


@pytest.mark.parametrize(
    "priority",
    [(), ("power", "power"), ("bogus",)],
)
def test_invalid_priority_rejected(priority):
    with pytest.raises(ValueError, match="priority"):
        preview_activity_load(_activity(), profiles={"walking": priority})


def test_unknown_sport_uses_other_profile_not_power_assumption():
    result = preview_activity_load(_activity("yoga"), ftp_watts=200, **_context())
    assert result.sport == "other"
    assert result.selected_method == "garmin"


def test_invalid_power_and_pace_inputs_do_not_create_negative_load():
    activity = replace(_activity("cycling"), normalized_power=float("nan"))
    result = preview_activity_load(activity, ftp_watts=200, **_context())
    assert result.selected_method == "hr"
    running = replace(_activity("running"), distance_meters=-10.0, avg_hr=None)
    result = preview_activity_load(running, threshold_speed_mps=3.0)
    assert result.selected_method == "garmin"
