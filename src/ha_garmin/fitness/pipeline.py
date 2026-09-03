"""End-to-end training-history pipeline primitives."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from typing import Literal

from .load import (
    analyze_garmin_load_coverage,
    build_daily_garmin_load_series,
    normalize_activities,
)
from .metrics import AcwrPoint, RampRatePoint, compute_acwr, compute_ramp_rate
from .models import ActivityMetrics, DailyLoad, GarminLoadCoverage, TrainingLoadPoint
from .training import compute_ctl_atl_tsb
from .trimp import Sex, build_daily_trimp_series

LoadSource = Literal["garmin", "trimp"]


@dataclass(frozen=True, slots=True)
class LoadSeriesAssessment:
    """Completeness diagnostics for one daily load series."""

    total_days: int
    activity_days: int
    rest_days: int
    complete_days: int
    incomplete_days: tuple[date, ...]
    ready: bool


@dataclass(frozen=True, slots=True)
class TrainingHistoryResult:
    """Derived training metrics for one homogeneous load source."""

    source: LoadSource
    assessment: LoadSeriesAssessment
    daily_loads: tuple[DailyLoad, ...]
    training_points: tuple[TrainingLoadPoint, ...]
    acwr_points: tuple[AcwrPoint, ...]
    ramp_rate_points: tuple[RampRatePoint, ...]


@dataclass(frozen=True, slots=True)
class GarminTrainingHistory:
    """Normalized Garmin activity history plus derived Garmin-load metrics."""

    activities: tuple[ActivityMetrics, ...]
    load_coverage: GarminLoadCoverage
    history: TrainingHistoryResult


def assess_daily_load_series(daily_loads: Iterable[DailyLoad]) -> LoadSeriesAssessment:
    """Describe whether a daily-load series is ready for derived metrics."""
    days = tuple(daily_loads)
    incomplete = tuple(day.date for day in days if day.load is None or not day.complete)
    activity_days = sum(day.activity_count > 0 for day in days)
    rest_days = sum(day.activity_count == 0 for day in days)
    return LoadSeriesAssessment(
        total_days=len(days),
        activity_days=activity_days,
        rest_days=rest_days,
        complete_days=len(days) - len(incomplete),
        incomplete_days=incomplete,
        ready=bool(days) and not incomplete,
    )


def build_training_history_from_daily_loads(
    source: LoadSource,
    daily_loads: Iterable[DailyLoad],
) -> TrainingHistoryResult:
    """Calculate Training metrics when the chosen load series is complete.

    Incomplete source data is returned as diagnostics rather than coerced to
    zero. Derived metrics remain empty until every day in the requested series
    is trustworthy.
    """
    days = tuple(daily_loads)
    assessment = assess_daily_load_series(days)
    if not assessment.ready:
        return TrainingHistoryResult(
            source=source,
            assessment=assessment,
            daily_loads=days,
            training_points=(),
            acwr_points=(),
            ramp_rate_points=(),
        )

    training_points = tuple(compute_ctl_atl_tsb(days))
    return TrainingHistoryResult(
        source=source,
        assessment=assessment,
        daily_loads=days,
        training_points=training_points,
        acwr_points=tuple(compute_acwr(days)),
        ramp_rate_points=tuple(compute_ramp_rate(training_points)),
    )


def build_garmin_training_history(
    raw_activities: Iterable[dict[str, object]],
    start_date: date,
    end_date: date,
) -> GarminTrainingHistory:
    """Normalize Garmin activities and derive a Garmin-load training history."""
    activities = tuple(normalize_activities(raw_activities))
    coverage = analyze_garmin_load_coverage(activities)
    daily_loads = build_daily_garmin_load_series(activities, start_date, end_date)
    history = build_training_history_from_daily_loads("garmin", daily_loads)
    return GarminTrainingHistory(
        activities=activities,
        load_coverage=coverage,
        history=history,
    )


def build_trimp_training_history(
    activities: Iterable[ActivityMetrics],
    start_date: date,
    end_date: date,
    resting_hr_by_date: Mapping[date, float],
    user_max_hr: float,
    sex: Sex,
) -> TrainingHistoryResult:
    """Build a complete Training pipeline using Banister TRIMP as load source."""
    daily_loads = build_daily_trimp_series(
        activities,
        start_date,
        end_date,
        resting_hr_by_date,
        user_max_hr,
        sex,
    )
    return build_training_history_from_daily_loads("trimp", daily_loads)
