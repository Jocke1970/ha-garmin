"""Garmin Fitness normalization and calculation primitives."""

from .export import TrainingHistoryExportRow, export_training_history_rows
from .focus import (
    LoadFocus,
    LoadFocusSummary,
    classify_activity_focus,
    classify_load_focus,
)
from .load import (
    analyze_garmin_load_coverage,
    build_daily_garmin_load_series,
    normalize_activities,
    normalize_activity,
)
from .metrics import AcwrPoint, RampRatePoint, compute_acwr, compute_ramp_rate
from .models import ActivityMetrics, DailyLoad, GarminLoadCoverage, TrainingLoadPoint
from .pipeline import (
    GarminTrainingHistory,
    LoadSeriesAssessment,
    TrainingHistoryResult,
    assess_daily_load_series,
    build_garmin_training_history,
    build_training_history_from_daily_loads,
    build_trimp_training_history,
)
from .training import compute_ctl_atl_tsb
from .trimp import build_daily_trimp_series, compute_trimp

__all__ = [
    "AcwrPoint",
    "ActivityMetrics",
    "DailyLoad",
    "GarminLoadCoverage",
    "GarminTrainingHistory",
    "LoadFocus",
    "LoadFocusSummary",
    "LoadSeriesAssessment",
    "RampRatePoint",
    "TrainingHistoryExportRow",
    "TrainingHistoryResult",
    "TrainingLoadPoint",
    "analyze_garmin_load_coverage",
    "assess_daily_load_series",
    "build_daily_garmin_load_series",
    "build_daily_trimp_series",
    "build_garmin_training_history",
    "build_training_history_from_daily_loads",
    "build_trimp_training_history",
    "classify_activity_focus",
    "classify_load_focus",
    "compute_acwr",
    "compute_ctl_atl_tsb",
    "compute_ramp_rate",
    "compute_trimp",
    "export_training_history_rows",
    "normalize_activities",
    "normalize_activity",
]
