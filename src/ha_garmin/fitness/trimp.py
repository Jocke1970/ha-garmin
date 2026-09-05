"""Banister TRIMP calculations for Garmin Fitness."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

from .const import BANISTER_TRIMP_K_FEMALE, BANISTER_TRIMP_K_MALE
from .models import ActivityMetrics, DailyLoad

Sex = Literal["male", "female"]


@dataclass(frozen=True, slots=True)
class TrimpInputCoverage:
    """Coverage of activity-level inputs required for TRIMP."""

    total_activities: int
    eligible_activities: int
    ineligible_activities: int
    missing_average_hr: int
    missing_duration: int
    coverage_percent: float


def analyze_trimp_input_coverage(
    activities: Iterable[ActivityMetrics],
) -> TrimpInputCoverage:
    """Report whether activities contain average HR and positive duration."""
    values = list(activities)
    missing_hr = sum(activity.avg_hr is None for activity in values)
    missing_duration = sum(activity.duration_minutes <= 0 for activity in values)
    eligible = sum(
        activity.avg_hr is not None and activity.duration_minutes > 0
        for activity in values
    )
    total = len(values)
    percent = round((eligible / total) * 100.0, 1) if total else 0.0
    return TrimpInputCoverage(
        total_activities=total,
        eligible_activities=eligible,
        ineligible_activities=total - eligible,
        missing_average_hr=missing_hr,
        missing_duration=missing_duration,
        coverage_percent=percent,
    )


def compute_trimp(
    activity: ActivityMetrics,
    resting_hr: float,
    user_max_hr: float,
    sex: Sex,
) -> float | None:
    """Compute Banister TRIMP for one activity.

    Returns ``None`` when the activity lacks the HR/duration data required for
    the calculation. Physiologically valid zero intensity remains ``0.0``.
    """
    if activity.avg_hr is None or activity.duration_minutes <= 0:
        return None
    if user_max_hr <= resting_hr:
        raise ValueError("user_max_hr must be greater than resting_hr")
    if sex not in ("male", "female"):
        raise ValueError("sex must be male or female")

    hr_ratio = (activity.avg_hr - resting_hr) / (user_max_hr - resting_hr)
    hr_ratio = max(0.0, min(1.0, hr_ratio))
    k = BANISTER_TRIMP_K_FEMALE if sex == "female" else BANISTER_TRIMP_K_MALE
    trimp = activity.duration_minutes * hr_ratio * math.exp(k * hr_ratio)
    return round(trimp, 3)


def build_daily_trimp_series(
    activities: Iterable[ActivityMetrics],
    start_date: date,
    end_date: date,
    resting_hr_by_date: Mapping[date, float],
    user_max_hr: float,
    sex: Sex,
) -> list[DailyLoad]:
    """Build a continuous daily TRIMP series without hiding missing inputs."""
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
        if not day_activities:
            result.append(
                DailyLoad(
                    date=current,
                    activity_count=0,
                    loaded_activity_count=0,
                    known_load=0.0,
                    load=0.0,
                    complete=True,
                )
            )
            current += timedelta(days=1)
            continue

        resting_hr = resting_hr_by_date.get(current)
        values: list[float] = []
        if resting_hr is not None:
            for activity in day_activities:
                value = compute_trimp(activity, resting_hr, user_max_hr, sex)
                if value is not None:
                    values.append(value)

        known_load = round(sum(values), 3)
        complete = resting_hr is not None and len(values) == len(day_activities)
        result.append(
            DailyLoad(
                date=current,
                activity_count=len(day_activities),
                loaded_activity_count=len(values),
                known_load=known_load,
                load=known_load if complete else None,
                complete=complete,
            )
        )
        current += timedelta(days=1)

    return result
