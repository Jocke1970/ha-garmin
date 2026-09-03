"""Training Effect load-focus helpers."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from .const import LOAD_FOCUS_DOMINANCE_RATIO
from .models import ActivityMetrics

LoadFocus = Literal["aerobic", "anaerobic", "mixed", "unknown"]


@dataclass(frozen=True, slots=True)
class LoadFocusSummary:
    """Recent activity focus derived from Garmin Training Effect."""

    total_activities: int
    classified_activities: int
    average_aerobic_effect: float | None
    average_anaerobic_effect: float | None
    complete: bool
    dominant_focus: LoadFocus


def _focus_from_effects(
    aerobic: float | None,
    anaerobic: float | None,
    dominance_ratio: float,
) -> LoadFocus:
    """Classify a pair of aerobic/anaerobic Training Effect values."""
    if dominance_ratio <= 1.0:
        raise ValueError("dominance_ratio must be greater than 1")
    if aerobic is None or anaerobic is None:
        return "unknown"

    aerobic_value = max(0.0, aerobic)
    anaerobic_value = max(0.0, anaerobic)
    if aerobic_value == 0.0 and anaerobic_value == 0.0:
        return "unknown"
    if aerobic_value > anaerobic_value * dominance_ratio:
        return "aerobic"
    if anaerobic_value > aerobic_value * dominance_ratio:
        return "anaerobic"
    return "mixed"


def classify_activity_focus(
    activity: ActivityMetrics,
    dominance_ratio: float = LOAD_FOCUS_DOMINANCE_RATIO,
) -> LoadFocus:
    """Classify one activity from Garmin aerobic/anaerobic Training Effect."""
    return _focus_from_effects(
        activity.aerobic_training_effect,
        activity.anaerobic_training_effect,
        dominance_ratio,
    )


def classify_load_focus(
    activities: Iterable[ActivityMetrics],
    dominance_ratio: float = LOAD_FOCUS_DOMINANCE_RATIO,
) -> LoadFocusSummary:
    """Classify recent training focus from average Garmin Training Effect.

    This mirrors the PulseCoach-inspired MVP rule: average aerobic and
    anaerobic Training Effect across activities that provide both values, then
    require one average to exceed the other by ``dominance_ratio``. Activities
    missing either Training Effect value are excluded and make ``complete``
    false rather than being interpreted as zero.
    """
    if dominance_ratio <= 1.0:
        raise ValueError("dominance_ratio must be greater than 1")

    values = list(activities)
    effect_pairs = [
        (activity.aerobic_training_effect, activity.anaerobic_training_effect)
        for activity in values
        if activity.aerobic_training_effect is not None
        and activity.anaerobic_training_effect is not None
    ]
    if not effect_pairs:
        return LoadFocusSummary(
            total_activities=len(values),
            classified_activities=0,
            average_aerobic_effect=None,
            average_anaerobic_effect=None,
            complete=not values,
            dominant_focus="unknown",
        )

    average_aerobic = sum(pair[0] for pair in effect_pairs if pair[0] is not None) / len(
        effect_pairs
    )
    average_anaerobic = sum(
        pair[1] for pair in effect_pairs if pair[1] is not None
    ) / len(effect_pairs)
    dominant = _focus_from_effects(
        average_aerobic,
        average_anaerobic,
        dominance_ratio,
    )

    return LoadFocusSummary(
        total_activities=len(values),
        classified_activities=len(effect_pairs),
        average_aerobic_effect=round(average_aerobic, 3),
        average_anaerobic_effect=round(average_anaerobic, 3),
        complete=len(effect_pairs) == len(values),
        dominant_focus=dominant,
    )
