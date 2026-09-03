"""Activity normalization and Garmin training-load aggregation."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from typing import Any

from .models import ActivityMetrics, DailyLoad, GarminLoadCoverage


def _number(value: Any) -> float | None:
    """Return a finite numeric value as float, otherwise None."""
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if result != result or result in (float("inf"), float("-inf")):
        return None
    return result


def _parse_start_time(activity: dict[str, Any]) -> datetime:
    """Parse the best available Garmin activity start timestamp."""
    value = activity.get("startTime")
    if isinstance(value, datetime):
        return value

    for key, assume_utc in (("startTimeGMT", True), ("startTimeLocal", False)):
        raw = activity.get(key)
        if not isinstance(raw, str) or not raw:
            continue
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            continue
        if assume_utc and parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed

    raise ValueError("Activity is missing a valid start timestamp")


def _activity_type(activity: dict[str, Any]) -> str:
    """Normalize Garmin's activityType shape to a type key."""
    raw = activity.get("activityType")
    if isinstance(raw, dict):
        raw = raw.get("typeKey")
    return str(raw or "unknown")


def _calendar_date(activity: dict[str, Any], start_time: datetime) -> date:
    """Return the activity's local Garmin calendar date when available."""
    raw_calendar_date = activity.get("calendarDate")
    if isinstance(raw_calendar_date, date) and not isinstance(
        raw_calendar_date, datetime
    ):
        return raw_calendar_date
    if isinstance(raw_calendar_date, str):
        try:
            return date.fromisoformat(raw_calendar_date)
        except ValueError:
            pass

    raw_local = activity.get("startTimeLocal")
    if isinstance(raw_local, str) and raw_local:
        try:
            return datetime.fromisoformat(raw_local.replace("Z", "+00:00")).date()
        except ValueError:
            pass

    return start_time.date()


def normalize_activity(activity: dict[str, Any]) -> ActivityMetrics:
    """Normalize one Garmin activity into calculation-friendly fields."""
    activity_id = activity.get("activityId")
    if isinstance(activity_id, bool):
        raise ValueError("Activity has an invalid activityId")
    try:
        activity_id = int(activity_id)
    except (TypeError, ValueError) as err:
        raise ValueError("Activity is missing a valid activityId") from err
    if activity_id <= 0:
        raise ValueError("Activity has an invalid activityId")

    start_time = _parse_start_time(activity)
    duration_seconds = _number(activity.get("duration")) or 0.0

    return ActivityMetrics(
        activity_id=activity_id,
        calendar_date=_calendar_date(activity, start_time),
        start_time=start_time,
        activity_type=_activity_type(activity),
        duration_minutes=round(duration_seconds / 60.0, 3),
        distance_meters=_number(activity.get("distance")),
        avg_hr=_number(activity.get("averageHR")),
        max_hr=_number(activity.get("maxHR")),
        calories=_number(activity.get("calories")),
        aerobic_training_effect=_number(activity.get("aerobicTrainingEffect")),
        anaerobic_training_effect=_number(activity.get("anaerobicTrainingEffect")),
        garmin_training_load=_number(activity.get("activityTrainingLoad")),
        vo2max=_number(activity.get("vO2MaxValue")),
        avg_power=_number(activity.get("avgPower")),
        normalized_power=_number(activity.get("normPower")),
    )


def normalize_activities(
    activities: Iterable[dict[str, Any]],
) -> list[ActivityMetrics]:
    """Normalize and deduplicate activities by Garmin activity ID."""
    by_id: dict[int, ActivityMetrics] = {}
    for raw in activities:
        normalized = normalize_activity(raw)
        by_id.setdefault(normalized.activity_id, normalized)
    return sorted(
        by_id.values(),
        key=lambda item: (
            item.calendar_date,
            item.start_time.replace(tzinfo=None).time(),
            item.activity_id,
        ),
    )


def analyze_garmin_load_coverage(
    activities: Iterable[ActivityMetrics],
) -> GarminLoadCoverage:
    """Summarize how often Garmin supplies activityTrainingLoad."""
    values = list(activities)
    with_load = sum(item.garmin_training_load is not None for item in values)
    total = len(values)
    percent = round((with_load / total) * 100.0, 1) if total else 0.0
    return GarminLoadCoverage(
        total_activities=total,
        activities_with_load=with_load,
        activities_without_load=total - with_load,
        coverage_percent=percent,
    )


def build_daily_garmin_load_series(
    activities: Iterable[ActivityMetrics],
    start_date: date,
    end_date: date,
) -> list[DailyLoad]:
    """Build an inclusive calendar series without treating missing load as zero.

    A genuine rest day has a complete load of 0. A day containing activities is
    only complete when every activity has Garmin ``activityTrainingLoad``. The
    sum of available values is exposed as ``known_load`` for diagnostics, while
    ``load`` remains None for an incomplete day to avoid silently undercounting.
    """
    if start_date > end_date:
        raise ValueError("start_date cannot be after end_date")

    grouped: dict[date, list[ActivityMetrics]] = {}
    for activity in activities:
        if start_date <= activity.calendar_date <= end_date:
            grouped.setdefault(activity.calendar_date, []).append(activity)

    result: list[DailyLoad] = []
    current = start_date
    while current <= end_date:
        day_activities = grouped.get(current, [])
        known_values = [
            item.garmin_training_load
            for item in day_activities
            if item.garmin_training_load is not None
        ]
        known_load = round(sum(known_values), 3)
        loaded_count = len(known_values)
        complete = loaded_count == len(day_activities)
        load = known_load if complete else None
        result.append(
            DailyLoad(
                date=current,
                activity_count=len(day_activities),
                loaded_activity_count=loaded_count,
                known_load=known_load,
                load=load,
                complete=complete,
            )
        )
        current += timedelta(days=1)

    return result
