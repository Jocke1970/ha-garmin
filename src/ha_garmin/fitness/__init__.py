"""Garmin Fitness normalization and calculation primitives."""

from .const import GARMIN_FITNESS_ALGORITHM_VERSION
from .diagnostics import (
    ActivityTypeCoverage,
    LoadSourceCoverageComparison,
    TrimpHistoryContextCoverage,
    analyze_trimp_history_context,
    compare_load_source_coverage,
)
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
from .strain import (
    calibrate_personal_trimp_max,
    compute_strain_score,
    count_consecutive_hard_days,
)
from .training import compute_ctl_atl_tsb
from .trimp import (
    TrimpInputCoverage,
    analyze_trimp_input_coverage,
    build_daily_trimp_series,
    compute_trimp,
)

__all__ = [
    "AcwrPoint",
    "ActivityMetrics",
    "ActivityTypeCoverage",
    "DailyLoad",
    "GARMIN_FITNESS_ALGORITHM_VERSION",
    "GarminLoadCoverage",
    "GarminTrainingHistory",
    "LoadFocus",
    "LoadFocusSummary",
    "LoadSeriesAssessment",
    "LoadSourceCoverageComparison",
    "RampRatePoint",
    "TrainingHistoryExportRow",
    "TrainingHistoryResult",
    "TrainingLoadPoint",
    "TrimpHistoryContextCoverage",
    "TrimpInputCoverage",
    "analyze_garmin_load_coverage",
    "analyze_trimp_history_context",
    "analyze_trimp_input_coverage",
    "assess_daily_load_series",
    "build_daily_garmin_load_series",
    "build_daily_trimp_series",
    "build_garmin_training_history",
    "build_training_history_from_daily_loads",
    "build_trimp_training_history",
    "calibrate_personal_trimp_max",
    "classify_activity_focus",
    "classify_load_focus",
    "compare_load_source_coverage",
    "compute_acwr",
    "compute_ctl_atl_tsb",
    "compute_ramp_rate",
    "compute_strain_score",
    "compute_trimp",
    "count_consecutive_hard_days",
    "export_training_history_rows",
    "normalize_activities",
    "normalize_activity",
]
