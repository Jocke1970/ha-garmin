"""Strict normalization for daily Garmin recovery inputs."""

from __future__ import annotations

import math
from datetime import date
from typing import Any

from .models import DailyRecoveryMetrics


def _number(value: Any) -> float | None:
    """Return a finite numeric value, otherwise ``None``."""
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(result):
        return None
    return result


def _text(value: Any) -> str | None:
    """Return a non-empty text value, otherwise ``None``."""
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _matches_date(payload: dict[str, Any], target_date: date) -> bool:
    """Reject a payload when it explicitly identifies another calendar date.

    Some Garmin responses omit an embedded date because the requested date is
    already encoded in the endpoint URL. Missing date metadata is therefore
    accepted. If a date is present, however, it must match the requested day so
    stale/fallback data cannot silently enter strict history.
    """
    for key in ("calendarDate", "date"):
        raw = payload.get(key)
        if raw is None:
            continue
        if isinstance(raw, date):
            return raw == target_date
        if isinstance(raw, str):
            try:
                return date.fromisoformat(raw[:10]) == target_date
            except ValueError:
                return False
        return False
    return True


def _seconds_to_minutes(value: Any) -> float | None:
    """Convert a finite seconds value to minutes without inventing zero."""
    seconds = _number(value)
    if seconds is None:
        return None
    return round(seconds / 60.0, 1)


def build_daily_recovery_metrics(
    target_date: date,
    *,
    summary_raw: dict[str, Any] | None = None,
    sleep_raw: dict[str, Any] | None = None,
    hrv_raw: dict[str, Any] | None = None,
    readiness_raw: dict[str, Any] | None = None,
    morning_readiness_raw: dict[str, Any] | None = None,
) -> DailyRecoveryMetrics:
    """Normalize exact-date Garmin recovery payloads into one daily record."""
    summary = summary_raw or {}
    if summary and not _matches_date(summary, target_date):
        summary = {}

    daily_sleep: dict[str, Any] = {}
    raw_daily_sleep = (sleep_raw or {}).get("dailySleepDTO")
    if isinstance(raw_daily_sleep, dict) and _matches_date(raw_daily_sleep, target_date):
        daily_sleep = raw_daily_sleep

    hrv_summary: dict[str, Any] = {}
    raw_hrv_summary = (hrv_raw or {}).get("hrvSummary")
    if isinstance(raw_hrv_summary, dict) and _matches_date(raw_hrv_summary, target_date):
        hrv_summary = raw_hrv_summary

    readiness = readiness_raw or {}
    if readiness and not _matches_date(readiness, target_date):
        readiness = {}

    morning_readiness = morning_readiness_raw or {}
    if morning_readiness and not _matches_date(morning_readiness, target_date):
        morning_readiness = {}

    baseline = hrv_summary.get("baseline") or {}
    if not isinstance(baseline, dict):
        baseline = {}

    sleep_scores = daily_sleep.get("sleepScores") or {}
    overall_sleep = sleep_scores.get("overall") if isinstance(sleep_scores, dict) else {}
    if not isinstance(overall_sleep, dict):
        overall_sleep = {}

    sleep_need = daily_sleep.get("sleepNeed") or {}
    if not isinstance(sleep_need, dict):
        sleep_need = {}

    return DailyRecoveryMetrics(
        date=target_date,
        resting_hr=_number(summary.get("restingHeartRate")),
        resting_hr_7d_avg=_number(summary.get("lastSevenDaysAvgRestingHeartRate")),
        hrv_status=_text(hrv_summary.get("status")),
        hrv_weekly_avg=_number(hrv_summary.get("weeklyAvg")),
        hrv_last_night_avg=_number(hrv_summary.get("lastNightAvg")),
        hrv_last_night_5min_high=_number(hrv_summary.get("lastNight5MinHigh")),
        hrv_baseline_low_upper=_number(baseline.get("lowUpper")),
        hrv_baseline_balanced_low=_number(baseline.get("balancedLow")),
        hrv_baseline_balanced_upper=_number(baseline.get("balancedUpper")),
        sleep_score=_number(overall_sleep.get("value")),
        sleep_minutes=_seconds_to_minutes(daily_sleep.get("sleepTimeSeconds")),
        sleep_need_minutes=_number(sleep_need.get("actual")),
        deep_sleep_minutes=_seconds_to_minutes(daily_sleep.get("deepSleepSeconds")),
        rem_sleep_minutes=_seconds_to_minutes(daily_sleep.get("remSleepSeconds")),
        average_stress_level=_number(summary.get("averageStressLevel")),
        body_battery_most_recent=_number(summary.get("bodyBatteryMostRecentValue")),
        body_battery_high=_number(summary.get("bodyBatteryHighestValue")),
        body_battery_low=_number(summary.get("bodyBatteryLowestValue")),
        training_readiness=_number(readiness.get("score")),
        training_readiness_level=_text(readiness.get("level")),
        morning_training_readiness=_number(morning_readiness.get("score")),
        recovery_minutes=_number(readiness.get("recoveryTime")),
        summary_available=bool(summary),
        sleep_available=bool(daily_sleep),
        hrv_available=bool(hrv_summary),
        readiness_available=bool(readiness),
        morning_readiness_available=bool(morning_readiness),
    )
