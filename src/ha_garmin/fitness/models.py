"""Normalized models used by Garmin Fitness calculations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True, slots=True)
class ActivityMetrics:
    """Normalized activity fields needed by fitness calculations."""

    activity_id: int
    calendar_date: date
    start_time: datetime
    activity_type: str
    duration_minutes: float
    distance_meters: float | None
    avg_hr: float | None
    max_hr: float | None
    calories: float | None
    aerobic_training_effect: float | None
    anaerobic_training_effect: float | None
    garmin_training_load: float | None
    vo2max: float | None
    avg_power: float | None
    normalized_power: float | None


@dataclass(frozen=True, slots=True)
class DailyLoad:
    """One calendar day's Garmin training-load coverage and value."""

    date: date
    activity_count: int
    loaded_activity_count: int
    known_load: float
    load: float | None
    complete: bool


@dataclass(frozen=True, slots=True)
class GarminLoadCoverage:
    """Coverage summary for Garmin's activityTrainingLoad field."""

    total_activities: int
    activities_with_load: int
    activities_without_load: int
    coverage_percent: float
