"""Activity normalization and Garmin training-load aggregation."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from typing import Any

from .models import ActivityMetrics, DailyLoad, GarminLoadCoverage

_SHADOW_START_TOLERANCE = timedelta(minutes=2)
_SHADOW_DURATION_TOLERANCE_MINUTES = 1.0
_ACTIVITY_FAMILIES: dict[str, str] = {
    "cycling": "cycling",
    "road_biking": "cycling",
    "virtual_ride": "cycling",
    "indoor_cycling": "cycling",
    "mountain_biking": "cycling",
    "gravel_cycling": "cycling",
    "e_bike_fitness": "cycling",
    "e_bike_mountain": "cycling",
    "running": "running",
    "virtual_run": "running",
    "treadmill_running": "running",
    "trail_running": "running",
    "track_running": "running",
    "rowing": "rowing",
    "rowing_v2": "rowing",
    "indoor_rowing": "rowing",
    "walking": "walking",
    "hiking": "walking",
    "strength": "strength",
    "strength_training": "strength",
    "swimming": "swimming",
    "lap_swimming": "swimming",
    "open_water_swimming": "swimming",
}


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
    if isinstance(activity_id, bool) or not isinstance(activity_id, (int, str)):
        raise ValueError("Activity is missing a valid activityId")
    try:
        activity_id = int(activity_id)
    except ValueError as err:
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


def _activity_quality(activity: ActivityMetrics) -> tuple[int, int]:
    """Rank duplicate activity records by calculation-relevant completeness."""
    optional_values = (
        activity.distance_meters,
        activity.avg_hr,
        activity.max_hr,
        activity.calories,
        activity.aerobic_training_effect,
        activity.anaerobic_training_effect,
        activity.garmin_training_load,
        activity.vo2max,
        activity.avg_power,
        activity.normalized_power,
    )
    populated = sum(value is not None for value in optional_values)
    return populated, int(activity.duration_minutes > 0)


def _activity_family(activity_type: str) -> str:
    """Return a conservative activity family for duplicate-session matching."""
    return _ACTIVITY_FAMILIES.get(activity_type, activity_type)


def _trimp_inputs_ready(activity: ActivityMetrics) -> bool:
    """Return whether one normalized activity can contribute TRIMP."""
    return activity.avg_hr is not None and activity.duration_minutes > 0


def _same_shadow_session_window(
    left: ActivityMetrics,
    right: ActivityMetrics,
) -> bool:
    """Return whether two IDs fall inside one conservative session window."""
    if left.calendar_date != right.calendar_date:
        return False
    if _activity_family(left.activity_type) != _activity_family(right.activity_type):
        return False

    left_start = left.start_time.replace(tzinfo=None)
    right_start = right.start_time.replace(tzinfo=None)
    if abs(left_start - right_start) > _SHADOW_START_TOLERANCE:
        return False

    if left.duration_minutes <= 0 or right.duration_minutes <= 0:
        return False
    return (
        abs(left.duration_minutes - right.duration_minutes)
        <= _SHADOW_DURATION_TOLERANCE_MINUTES
    )


def _suppress_incomplete_shadow_sessions(
    activities: Iterable[ActivityMetrics],
) -> list[ActivityMetrics]:
    """Drop incomplete shadow copies when a complete session counterpart exists.

    Connected services can create multiple Garmin IDs for the same workout. Keep
    every TRIMP-capable activity, including multiple genuine overlapping passes,
    and suppress only incomplete records that match at least one complete session
    in the same conservative time/duration/family window.
    """
    values = list(activities)
    complete_sessions = [item for item in values if _trimp_inputs_ready(item)]
    return [
        activity
        for activity in values
        if _trimp_inputs_ready(activity)
        or not any(
            _same_shadow_session_window(activity, complete)
            for complete in complete_sessions
        )
    ]


def normalize_activities(
    activities: Iterable[dict[str, Any]],
) -> list[ActivityMetrics]:
    """Normalize and conservatively deduplicate Garmin activities.

    Same-ID duplicates prefer the richer copy. Distinct IDs are normally kept,
    except when incomplete near-identical sessions in the same activity family
    overlap a TRIMP-capable counterpart. Every complete activity is preserved;
    only incomplete cross-service shadow records are suppressed so they cannot
    invalidate an otherwise complete Fitness day or be double-counted beside the
    real recorded workout.
    """
    by_id: dict[int, ActivityMetrics] = {}
    for raw in activities:
        normalized = normalize_activity(raw)
        existing = by_id.get(normalized.activity_id)
        if existing is None or _activity_quality(normalized) > _activity_quality(
            existing
        ):
            by_id[normalized.activity_id] = normalized

    ordered = sorted(
        by_id.values(),
        key=lambda item: (
            item.calendar_date,
            item.start_time.replace(tzinfo=None).time(),
            item.activity_id,
        ),
    )
    return _suppress_incomplete_shadow_sessions(ordered)


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
