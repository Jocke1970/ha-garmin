"""Build immutable Insight rule input from existing canonical Fitness data."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta

from ..fitness import (
    ActivityMetrics,
    TrainingHistoryResult,
    build_daily_load_focus_series,
    compute_strain_score,
)
from ..fitness.const import DEFAULT_PERSONAL_TRIMP_MAX
from .models import (
    DailyRecoveryMetrics,
    InsightDataQuality,
    InsightSnapshot,
    LoadFocusSnapshot,
    TrainingSnapshot,
)

_REQUIRED_RECOVERY_SOURCES = (
    ("summary", "summary_available"),
    ("sleep", "sleep_available"),
    ("hrv", "hrv_available"),
)

_REQUIRED_RECOVERY_FIELDS = (
    "resting_hr",
    "hrv_last_night_avg",
    "sleep_score",
)


def _aware(as_of: datetime) -> bool:
    """Return whether a datetime carries an effective UTC offset."""
    return as_of.tzinfo is not None and as_of.utcoffset() is not None


def build_insight_snapshot(
    as_of: datetime,
    *,
    recovery: DailyRecoveryMetrics,
    training_history: TrainingHistoryResult,
    activities: Iterable[ActivityMetrics] = (),
    personal_trimp_max: float = DEFAULT_PERSONAL_TRIMP_MAX,
    recent_activity_days: int = 7,
) -> InsightSnapshot:
    """Combine exact-date recovery and canonical Fitness data for Insight rules.

    The builder never substitutes an older Fitness point for the requested day.
    A recovery record from another date may be carried through only so data
    quality can explicitly label it stale; recovery-dependent rules can then
    refuse to evaluate it.

    Existing Fitness helpers remain the sole owners of Strain and Load Focus
    calculations. This module only selects the requested day and packages the
    already-defined metrics into an immutable rule-input contract.
    """
    if not _aware(as_of):
        raise ValueError("as_of must be timezone-aware")
    if personal_trimp_max <= 0:
        raise ValueError("personal_trimp_max must be positive")
    if recent_activity_days <= 0:
        raise ValueError("recent_activity_days must be positive")

    target_date = as_of.date()
    activity_values = tuple(activities)

    training_point = next(
        (
            point
            for point in training_history.training_points
            if point.date == target_date
        ),
        None,
    )
    acwr_point = next(
        (point for point in training_history.acwr_points if point.date == target_date),
        None,
    )
    ramp_point = next(
        (
            point
            for point in training_history.ramp_rate_points
            if point.date == target_date
        ),
        None,
    )

    training_ready = bool(training_history.assessment.ready and training_point)
    training = TrainingSnapshot(
        date=target_date,
        source=training_history.source,
        algorithm_version=training_history.algorithm_version,
        ready=training_ready,
        daily_load=training_point.daily_load if training_point else None,
        ctl=training_point.ctl if training_point else None,
        atl=training_point.atl if training_point else None,
        tsb=training_point.tsb if training_point else None,
        acwr=acwr_point.acwr if acwr_point else None,
        ramp_rate=ramp_point.ramp_rate if ramp_point else None,
        strain=(
            compute_strain_score(training_point.daily_load, personal_trimp_max)
            if training_point
            else None
        ),
    )

    focus_day = build_daily_load_focus_series(
        activity_values,
        target_date,
        target_date,
    )[0]
    load_focus = LoadFocusSnapshot(
        date=target_date,
        activity_count=focus_day.activity_count,
        covered_activities=focus_day.covered_activities,
        complete=focus_day.complete,
        low_aerobic=focus_day.low_aerobic,
        high_aerobic=focus_day.high_aerobic,
        anaerobic=focus_day.anaerobic,
    )

    recent_start = target_date - timedelta(days=recent_activity_days - 1)
    recent_activities = tuple(
        sorted(
            (
                activity
                for activity in activity_values
                if recent_start <= activity.calendar_date <= target_date
            ),
            key=lambda activity: activity.start_time,
            reverse=True,
        )
    )

    recovery_current = recovery.date == target_date
    stale_fields = () if recovery_current else ("recovery",)

    missing_sources: list[str] = []
    missing_fields: list[str] = []
    if recovery_current:
        for source_name, attribute_name in _REQUIRED_RECOVERY_SOURCES:
            if not bool(getattr(recovery, attribute_name)):
                missing_sources.append(source_name)
        if not (recovery.readiness_available or recovery.morning_readiness_available):
            missing_sources.append("readiness")

        for field_name in _REQUIRED_RECOVERY_FIELDS:
            if getattr(recovery, field_name) is None:
                missing_fields.append(f"recovery.{field_name}")
        if (
            recovery.training_readiness is None
            and recovery.morning_training_readiness is None
        ):
            missing_fields.append("recovery.training_readiness")

    for field_name in (
        "daily_load",
        "ctl",
        "atl",
        "tsb",
        "acwr",
        "ramp_rate",
        "strain",
    ):
        if getattr(training, field_name) is None:
            missing_fields.append(f"training.{field_name}")

    if not load_focus.complete:
        for field_name in ("low_aerobic", "high_aerobic", "anaerobic"):
            if getattr(load_focus, field_name) is None:
                missing_fields.append(f"load_focus.{field_name}")

    training_complete = bool(
        training.ready
        and training.daily_load is not None
        and training.ctl is not None
        and training.atl is not None
        and training.tsb is not None
        and training.acwr is not None
        and training.ramp_rate is not None
        and training.strain is not None
    )

    quality = InsightDataQuality(
        complete=bool(
            recovery_current
            and training_complete
            and load_focus.complete
            and not missing_sources
            and not missing_fields
            and not stale_fields
        ),
        recovery_current=recovery_current,
        training_complete=training_complete,
        load_focus_complete=load_focus.complete,
        missing_sources=tuple(missing_sources),
        missing_fields=tuple(missing_fields),
        stale_fields=stale_fields,
    )

    return InsightSnapshot(
        as_of=as_of,
        recovery=recovery,
        training=training,
        load_focus=load_focus,
        recent_activities=recent_activities,
        data_quality=quality,
    )
