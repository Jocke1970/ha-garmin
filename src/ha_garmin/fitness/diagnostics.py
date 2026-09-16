"""Coverage diagnostics for choosing a canonical training-load source."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date

from .load import analyze_garmin_load_coverage
from .models import ActivityMetrics, GarminLoadCoverage
from .trimp import TrimpInputCoverage, analyze_trimp_input_coverage


@dataclass(frozen=True, slots=True)
class ActivityTypeCoverage:
    """Garmin Load and TRIMP-input coverage for one activity type."""

    activity_type: str
    total_activities: int
    garmin_load_activities: int
    garmin_load_percent: float
    trimp_eligible_activities: int
    trimp_input_percent: float


@dataclass(frozen=True, slots=True)
class TrimpHistoryContextCoverage:
    """Day-level TRIMP readiness after resting-HR history is available."""

    activity_days: int
    activity_days_with_resting_hr: int
    fully_eligible_activity_days: int
    missing_resting_hr_days: tuple[date, ...]
    incomplete_activity_input_days: tuple[date, ...]
    fully_eligible_percent: float


@dataclass(frozen=True, slots=True)
class LoadSourceCoverageComparison:
    """Side-by-side load-source input coverage without auto-selecting a source."""

    garmin: GarminLoadCoverage
    trimp: TrimpInputCoverage
    by_activity_type: tuple[ActivityTypeCoverage, ...]


def compare_load_source_coverage(
    activities: Iterable[ActivityMetrics],
) -> LoadSourceCoverageComparison:
    """Compare Garmin Load availability with activity-level TRIMP eligibility.

    This intentionally does not recommend or select a canonical source. TRIMP
    additionally requires daily resting HR plus max-HR/sex configuration, so its
    activity-level eligibility alone is not enough to declare it usable.
    """
    values = list(activities)
    garmin = analyze_garmin_load_coverage(values)
    trimp = analyze_trimp_input_coverage(values)

    by_type: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
    for activity in values:
        counts = by_type[activity.activity_type]
        counts[0] += 1
        if activity.garmin_training_load is not None:
            counts[1] += 1
        if activity.avg_hr is not None and activity.duration_minutes > 0:
            counts[2] += 1

    type_rows = []
    for activity_type, (total, garmin_count, trimp_count) in sorted(by_type.items()):
        type_rows.append(
            ActivityTypeCoverage(
                activity_type=activity_type,
                total_activities=total,
                garmin_load_activities=garmin_count,
                garmin_load_percent=round((garmin_count / total) * 100.0, 1),
                trimp_eligible_activities=trimp_count,
                trimp_input_percent=round((trimp_count / total) * 100.0, 1),
            )
        )

    return LoadSourceCoverageComparison(
        garmin=garmin,
        trimp=trimp,
        by_activity_type=tuple(type_rows),
    )


def analyze_trimp_history_context(
    activities: Iterable[ActivityMetrics],
    resting_hr_by_date: Mapping[date, float],
) -> TrimpHistoryContextCoverage:
    """Measure full day-level TRIMP readiness before max-HR/sex configuration."""
    grouped: dict[date, list[ActivityMetrics]] = defaultdict(list)
    for activity in activities:
        grouped[activity.calendar_date].append(activity)

    activity_dates = sorted(grouped)
    missing_rhr: list[date] = []
    incomplete_inputs: list[date] = []
    fully_eligible = 0

    for activity_date in activity_dates:
        has_rhr = resting_hr_by_date.get(activity_date, 0) > 0
        inputs_complete = all(
            activity.avg_hr is not None and activity.duration_minutes > 0
            for activity in grouped[activity_date]
        )
        if not has_rhr:
            missing_rhr.append(activity_date)
        if not inputs_complete:
            incomplete_inputs.append(activity_date)
        if has_rhr and inputs_complete:
            fully_eligible += 1

    total_days = len(activity_dates)
    percent = round((fully_eligible / total_days) * 100.0, 1) if total_days else 0.0
    return TrimpHistoryContextCoverage(
        activity_days=total_days,
        activity_days_with_resting_hr=total_days - len(missing_rhr),
        fully_eligible_activity_days=fully_eligible,
        missing_resting_hr_days=tuple(missing_rhr),
        incomplete_activity_input_days=tuple(incomplete_inputs),
        fully_eligible_percent=percent,
    )
