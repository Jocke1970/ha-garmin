"""Tests for strict Garmin Insights recovery normalization."""

from datetime import date

from ha_garmin.insights import build_daily_recovery_metrics


def test_build_daily_recovery_metrics_full_payload() -> None:
    """Normalize exact-date recovery fields without presentation fallbacks."""
    target = date(2026, 9, 5)

    result = build_daily_recovery_metrics(
        target,
        summary_raw={
            "calendarDate": "2026-09-05",
            "restingHeartRate": 54,
            "lastSevenDaysAvgRestingHeartRate": 56,
            "averageStressLevel": 24,
            "bodyBatteryMostRecentValue": 68,
            "bodyBatteryHighestValue": 91,
            "bodyBatteryLowestValue": 22,
        },
        sleep_raw={
            "dailySleepDTO": {
                "calendarDate": "2026-09-05",
                "sleepScores": {"overall": {"value": 84}},
                "sleepTimeSeconds": 27000,
                "deepSleepSeconds": 5400,
                "remSleepSeconds": 6300,
                "sleepNeed": {"actual": 480},
            }
        },
        hrv_raw={
            "hrvSummary": {
                "calendarDate": "2026-09-05",
                "status": "BALANCED",
                "weeklyAvg": 52,
                "lastNightAvg": 55,
                "lastNight5MinHigh": 71,
                "baseline": {
                    "lowUpper": 42,
                    "balancedLow": 45,
                    "balancedUpper": 61,
                },
            }
        },
        readiness_raw={
            "calendarDate": "2026-09-05",
            "score": 78,
            "level": "HIGH",
            "recoveryTime": 180,
        },
        morning_readiness_raw={
            "calendarDate": "2026-09-05",
            "inputContext": "AFTER_WAKEUP_RESET",
            "score": 74,
        },
    )

    assert result.date == target
    assert result.resting_hr == 54
    assert result.resting_hr_7d_avg == 56
    assert result.average_stress_level == 24
    assert result.body_battery_most_recent == 68
    assert result.body_battery_high == 91
    assert result.body_battery_low == 22
    assert result.sleep_score == 84
    assert result.sleep_minutes == 450.0
    assert result.sleep_need_minutes == 480
    assert result.deep_sleep_minutes == 90.0
    assert result.rem_sleep_minutes == 105.0
    assert result.hrv_status == "BALANCED"
    assert result.hrv_weekly_avg == 52
    assert result.hrv_last_night_avg == 55
    assert result.hrv_last_night_5min_high == 71
    assert result.hrv_baseline_low_upper == 42
    assert result.hrv_baseline_balanced_low == 45
    assert result.hrv_baseline_balanced_upper == 61
    assert result.training_readiness == 78
    assert result.training_readiness_level == "HIGH"
    assert result.morning_training_readiness == 74
    assert result.recovery_minutes == 180
    assert result.summary_available is True
    assert result.sleep_available is True
    assert result.hrv_available is True
    assert result.readiness_available is True
    assert result.morning_readiness_available is True


def test_build_daily_recovery_metrics_rejects_adjacent_day_payloads() -> None:
    """Explicit stale dates must become unavailable instead of being reused."""
    target = date(2026, 9, 5)

    result = build_daily_recovery_metrics(
        target,
        summary_raw={"calendarDate": "2026-09-04", "restingHeartRate": 50},
        sleep_raw={
            "dailySleepDTO": {
                "calendarDate": "2026-09-04",
                "sleepScores": {"overall": {"value": 95}},
            }
        },
        hrv_raw={
            "hrvSummary": {
                "calendarDate": "2026-09-04",
                "status": "BALANCED",
            }
        },
        readiness_raw={"calendarDate": "2026-09-04", "score": 90},
        morning_readiness_raw={"calendarDate": "2026-09-04", "score": 88},
    )

    assert result.resting_hr is None
    assert result.sleep_score is None
    assert result.hrv_status is None
    assert result.training_readiness is None
    assert result.morning_training_readiness is None
    assert result.summary_available is False
    assert result.sleep_available is False
    assert result.hrv_available is False
    assert result.readiness_available is False
    assert result.morning_readiness_available is False


def test_build_daily_recovery_metrics_keeps_missing_values_unknown() -> None:
    """Missing and malformed physiology stays None rather than becoming zero."""
    result = build_daily_recovery_metrics(
        date(2026, 9, 5),
        summary_raw={"calendarDate": "2026-09-05", "restingHeartRate": None},
        sleep_raw={"dailySleepDTO": {"calendarDate": "2026-09-05"}},
        hrv_raw={"hrvSummary": {"calendarDate": "2026-09-05", "weeklyAvg": "nan"}},
        readiness_raw={"calendarDate": "2026-09-05", "score": True},
    )

    assert result.resting_hr is None
    assert result.sleep_minutes is None
    assert result.hrv_weekly_avg is None
    assert result.training_readiness is None
    assert result.summary_available is True
    assert result.sleep_available is True
    assert result.hrv_available is True
    assert result.readiness_available is True
