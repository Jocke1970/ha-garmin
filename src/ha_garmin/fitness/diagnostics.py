"""Coverage diagnostics for choosing a canonical training-load source."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass

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
