"""Normalized models used by deterministic Garmin Insights inputs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from ..fitness.models import ActivityMetrics


@dataclass(frozen=True, slots=True)
class DailyRecoveryMetrics:
    """Strict, date-bound recovery inputs for one Garmin calendar day.

    Values are never filled from an adjacent day. ``None`` means the requested
    Garmin source did not provide a usable value for this date. Source
    availability flags allow later Insight rules to distinguish an absent
    measurement from a successful source payload that simply lacks one field.
    """

    date: date

    resting_hr: float | None = None
    resting_hr_7d_avg: float | None = None

    hrv_status: str | None = None
    hrv_weekly_avg: float | None = None
    hrv_last_night_avg: float | None = None
    hrv_last_night_5min_high: float | None = None
    hrv_baseline_low_upper: float | None = None
    hrv_baseline_balanced_low: float | None = None
    hrv_baseline_balanced_upper: float | None = None

    sleep_score: float | None = None
    sleep_minutes: float | None = None
    sleep_need_minutes: float | None = None
    deep_sleep_minutes: float | None = None
    rem_sleep_minutes: float | None = None

    average_stress_level: float | None = None
    body_battery_most_recent: float | None = None
    body_battery_high: float | None = None
    body_battery_low: float | None = None

    training_readiness: float | None = None
    training_readiness_level: str | None = None
    morning_training_readiness: float | None = None
    recovery_minutes: float | None = None

    summary_available: bool = False
    sleep_available: bool = False
    hrv_available: bool = False
    readiness_available: bool = False
    morning_readiness_available: bool = False


@dataclass(frozen=True, slots=True)
class TrainingSnapshot:
    """Exact-date canonical Training V4 values used by Insight rules."""

    date: date
    source: str
    algorithm_version: int
    ready: bool
    daily_load: float | None = None
    ctl: float | None = None
    atl: float | None = None
    tsb: float | None = None
    acwr: float | None = None
    ramp_rate: float | None = None
    strain: float | None = None


@dataclass(frozen=True, slots=True)
class LoadFocusSnapshot:
    """Exact-date Training Effect bucket coverage for Insight rules."""

    date: date
    activity_count: int
    covered_activities: int
    complete: bool
    low_aerobic: float | None = None
    high_aerobic: float | None = None
    anaerobic: float | None = None


@dataclass(frozen=True, slots=True)
class InsightDataQuality:
    """Explain whether a snapshot can safely support deterministic rules."""

    complete: bool
    recovery_current: bool
    training_complete: bool
    load_focus_complete: bool
    missing_sources: tuple[str, ...] = ()
    missing_fields: tuple[str, ...] = ()
    stale_fields: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class InsightSnapshot:
    """One immutable, presentation-independent input bundle for Insight rules."""

    as_of: datetime
    recovery: DailyRecoveryMetrics
    training: TrainingSnapshot
    load_focus: LoadFocusSnapshot
    recent_activities: tuple[ActivityMetrics, ...]
    data_quality: InsightDataQuality
