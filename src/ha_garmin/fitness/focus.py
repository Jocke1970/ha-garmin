"""Training-effect load-focus helpers."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from .models import ActivityMetrics

LoadFocus = Literal["aerobic", "anaerobic", "mixed", "unknown"]


@dataclass(frozen=True, slots=True)
class LoadFocusSummary:
    """Garmin-load distribution by Training Effect focus."""

    total_activities: int
    activities_with_load: int
    aerobic_load: float
    anaerobic_load: float
    mixed_load: float
    unknown_load: float
    complete: bool
    dominant_focus: LoadFocus


def classify_load_focus(
    activity: ActivityMetrics,
    dominance_ratio: float = 1.5,
) -> LoadFocus:
    """Classify one activity from Garmin aerobic/anaerobic Training Effect.

    The classification follows the PulseCoach-inspired MVP rule from the
    project roadmap: one side must exceed the other by ``dominance_ratio`` to
    be considered dominant; otherwise the activity is mixed. Missing or wholly
    zero Training Effect values are unknown.
    """
    if dominance_ratio <= 1.0:
        raise ValueError("dominance_ratio must be greater than 1")

    aerobic = activity.aerobic_training_effect
    anaerobic = activity.anaerobic_training_effect
    if aerobic is None and anaerobic is None:
        return "unknown"

    aerobic_value = max(0.0, aerobic or 0.0)
    anaerobic_value = max(0.0, anaerobic or 0.0)
    if aerobic_value == 0.0 and anaerobic_value == 0.0:
        return "unknown"
    if aerobic_value > anaerobic_value * dominance_ratio:
        return "aerobic"
    if anaerobic_value > aerobic_value * dominance_ratio:
        return "anaerobic"
    return "mixed"


def summarize_load_focus(
    activities: Iterable[ActivityMetrics],
    dominance_ratio: float = 1.5,
) -> LoadFocusSummary:
    """Summarize known Garmin training load by Training Effect focus.

    Missing ``activityTrainingLoad`` is never treated as zero. ``complete`` is
    false when any activity lacks Garmin load, making the summary suitable for
    diagnostics before it is used as a user-facing load-focus metric.
    """
    values = list(activities)
    buckets: dict[LoadFocus, float] = {
        "aerobic": 0.0,
        "anaerobic": 0.0,
        "mixed": 0.0,
        "unknown": 0.0,
    }
    activities_with_load = 0

    for activity in values:
        if activity.garmin_training_load is None:
            continue
        activities_with_load += 1
        focus = classify_load_focus(activity, dominance_ratio)
        buckets[focus] += activity.garmin_training_load

    known_buckets = {key: value for key, value in buckets.items() if key != "unknown"}
    dominant: LoadFocus = "unknown"
    if any(value > 0 for value in known_buckets.values()):
        dominant = max(known_buckets, key=known_buckets.get)  # type: ignore[arg-type]

    return LoadFocusSummary(
        total_activities=len(values),
        activities_with_load=activities_with_load,
        aerobic_load=round(buckets["aerobic"], 3),
        anaerobic_load=round(buckets["anaerobic"], 3),
        mixed_load=round(buckets["mixed"], 3),
        unknown_load=round(buckets["unknown"], 3),
        complete=activities_with_load == len(values),
        dominant_focus=dominant,
    )
