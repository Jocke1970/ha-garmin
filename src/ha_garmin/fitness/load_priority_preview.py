"""Experimental per-sport Load Priority, without changing canonical Fitness.

This module chooses one *available* load source for each recorded activity.
Its output is deliberately NOT passed to the CTL/ATL/ACWR/Strain or budget
pipelines: Garmin Load, Banister TRIMP, power TSS and pace proxy are different
scales and must not be added together without a tested calibration policy.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from .models import ActivityMetrics
from .trimp import Sex, compute_trimp

LoadMethod = Literal["power", "hr", "pace", "garmin"]

# These are preview defaults, not assumptions about an individual athlete.
DEFAULT_LOAD_PRIORITY: dict[str, tuple[LoadMethod, ...]] = {
    "walking": ("hr", "pace", "garmin"),
    "cycling": ("power", "hr", "pace", "garmin"),
    "running": ("pace", "hr", "power", "garmin"),
    "rowing": ("power", "hr", "garmin"),
    "strength": ("garmin", "hr"),
    "other": ("garmin", "hr"),
}

SPORT_FAMILY: dict[str, str] = {
    "walking": "walking",
    "hiking": "walking",
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
    "strength": "strength",
    "strength_training": "strength",
}

UNITS: dict[LoadMethod, str] = {
    "power": "power_tss",
    "hr": "banister_trimp",
    "pace": "pace_proxy_unvalidated",
    "garmin": "garmin_training_load",
}


@dataclass(frozen=True, slots=True)
class SourceAttempt:
    method: LoadMethod
    available: bool
    reason: str


@dataclass(frozen=True, slots=True)
class ActivityLoadPreview:
    activity_id: int
    sport: str
    priority: tuple[LoadMethod, ...]
    selected_method: LoadMethod | None
    value: float | None
    unit: str | None
    attempts: tuple[SourceAttempt, ...]
    # No conversion to the canonical TRIMP series is implemented in this preview.
    canonical_compatible: bool = False


def _positive(value: float | None) -> bool:
    return value is not None and math.isfinite(value) and value > 0


def _priority(
    sport: str,
    profiles: Mapping[str, Sequence[LoadMethod]] | None,
) -> tuple[LoadMethod, ...]:
    configured = profiles.get(sport) if profiles is not None else None
    if configured is None:
        configured = DEFAULT_LOAD_PRIORITY[sport]
    result = tuple(configured)
    if not result or len(set(result)) != len(result):
        raise ValueError("Load priority must contain unique methods")
    if any(method not in UNITS for method in result):
        raise ValueError("Unknown load-priority method")
    return result


def _calculate(
    method: LoadMethod,
    activity: ActivityMetrics,
    *,
    resting_hr: float | None,
    user_max_hr: float | None,
    sex: Sex | None,
    ftp_watts: float | None,
    threshold_speed_mps: float | None,
) -> tuple[float | None, str]:
    if method == "garmin":
        value = activity.garmin_training_load
        if value is None or not math.isfinite(value) or value < 0:
            return None, "missing_or_invalid_garmin_load"
        return round(value, 3), "ok"

    if not _positive(activity.duration_minutes):
        return None, "missing_or_invalid_duration"

    if method == "hr":
        if not _positive(activity.avg_hr):
            return None, "missing_or_invalid_average_hr"
        if (
            resting_hr is None
            or not math.isfinite(resting_hr)
            or resting_hr < 0
            or user_max_hr is None
            or not _positive(user_max_hr)
            or user_max_hr <= resting_hr
            or sex not in ("male", "female")
        ):
            return None, "missing_or_invalid_hr_context"
        value = compute_trimp(activity, resting_hr, user_max_hr, sex)
        return value, "ok" if value is not None else "missing_trimp_inputs"

    if method == "power":
        # Normalized power is necessary for this interval-sensitive estimate;
        # mean power is intentionally NOT silently substituted.
        if activity.normalized_power is None or not _positive(
            activity.normalized_power
        ):
            return None, "missing_or_invalid_normalized_power"
        if ftp_watts is None or not _positive(ftp_watts):
            return None, "missing_or_invalid_ftp"
        tss = (
            activity.duration_minutes
            / 60.0
            * (activity.normalized_power / ftp_watts) ** 2
            * 100.0
        )
        return round(tss, 3), "ok"

    if method == "pace":
        if activity.distance_meters is None or not _positive(activity.distance_meters):
            return None, "missing_or_invalid_distance"
        if threshold_speed_mps is None or not _positive(threshold_speed_mps):
            return None, "missing_or_invalid_threshold_speed"
        speed_mps = activity.distance_meters / (activity.duration_minutes * 60.0)
        # EXPERIMENTAL speed-based proxy. Not calibrated against TRIMP or TSS;
        # distance-based pace does not account for grade, terrain or wind.
        proxy = (
            activity.duration_minutes
            / 60.0
            * (speed_mps / threshold_speed_mps) ** 2
            * 100.0
        )
        return round(proxy, 3), "uncalibrated_pace_proxy"

    raise ValueError("Unknown load-priority method")


def preview_activity_load(
    activity: ActivityMetrics,
    *,
    profiles: Mapping[str, Sequence[LoadMethod]] | None = None,
    resting_hr: float | None = None,
    user_max_hr: float | None = None,
    sex: Sex | None = None,
    ftp_watts: float | None = None,
    threshold_speed_mps: float | None = None,
    override: LoadMethod | None = None,
) -> ActivityLoadPreview:
    """Select the first usable source; a manual override has NO fallback.

    Profiles are keyed by a normalized sport family (walking/cycling/running/
    rowing/strength/other). A skipped source has an explicit diagnostic.
    This function reads normalized activities but never writes HA or history.
    """
    sport = SPORT_FAMILY.get(activity.activity_type, "other")
    priority = _priority(sport, profiles)
    if override is not None:
        if override not in UNITS:
            raise ValueError("Unknown load-priority override")
        priority = (override,)

    attempts: list[SourceAttempt] = []
    for method in priority:
        value, reason = _calculate(
            method,
            activity,
            resting_hr=resting_hr,
            user_max_hr=user_max_hr,
            sex=sex,
            ftp_watts=ftp_watts,
            threshold_speed_mps=threshold_speed_mps,
        )
        attempts.append(SourceAttempt(method, value is not None, reason))
        if value is not None:
            return ActivityLoadPreview(
                activity_id=activity.activity_id,
                sport=sport,
                priority=priority,
                selected_method=method,
                value=value,
                unit=UNITS[method],
                attempts=tuple(attempts),
            )

    return ActivityLoadPreview(
        activity_id=activity.activity_id,
        sport=sport,
        priority=priority,
        selected_method=None,
        value=None,
        unit=None,
        attempts=tuple(attempts),
    )
