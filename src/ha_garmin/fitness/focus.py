"""Training Effect load-focus helpers."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

from .const import LOAD_FOCUS_DOMINANCE_RATIO, LOAD_FOCUS_HIGH_AEROBIC_THRESHOLD
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


@dataclass(frozen=True, slots=True)
class DailyLoadFocus:
    """One calendar day's transparent Training Effect bucket totals."""

    date: date
    activity_count: int
    covered_activities: int
    complete: bool
    low_aerobic: float | None
    high_aerobic: float | None
    anaerobic: float | None


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

    average_aerobic = sum(
        pair[0] for pair in effect_pairs if pair[0] is not None
    ) / len(effect_pairs)
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


def build_daily_load_focus_series(
    activities: Iterable[ActivityMetrics],
    start_date: date,
    end_date: date,
    *,
    high_aerobic_threshold: float = LOAD_FOCUS_HIGH_AEROBIC_THRESHOLD,
) -> list[DailyLoadFocus]:
    """Build continuous daily low/high-aerobic and anaerobic TE buckets.

    The split is a transparent Garmin Fitness v1 heuristic, not Garmin's
    proprietary Load Focus algorithm. A rest day is a complete zero day. If an
    activity is missing either Training Effect value, that day remains
    incomplete and bucket values are ``None`` instead of fabricated zeros.
    """
    if start_date > end_date:
        raise ValueError("start_date cannot be after end_date")
    if high_aerobic_threshold <= 0:
        raise ValueError("high_aerobic_threshold must be positive")

    grouped: dict[date, list[ActivityMetrics]] = {}
    for activity in activities:
        if start_date <= activity.calendar_date <= end_date:
            grouped.setdefault(activity.calendar_date, []).append(activity)

    result: list[DailyLoadFocus] = []
    current = start_date
    while current <= end_date:
        day_activities = grouped.get(current, [])
        if not day_activities:
            result.append(
                DailyLoadFocus(
                    date=current,
                    activity_count=0,
                    covered_activities=0,
                    complete=True,
                    low_aerobic=0.0,
                    high_aerobic=0.0,
                    anaerobic=0.0,
                )
            )
            current += timedelta(days=1)
            continue

        low_aerobic = 0.0
        high_aerobic = 0.0
        anaerobic = 0.0
        covered = 0
        for activity in day_activities:
            aerobic = activity.aerobic_training_effect
            anaerobic_effect = activity.anaerobic_training_effect
            if aerobic is None or anaerobic_effect is None:
                continue
            if aerobic < 0 or anaerobic_effect < 0:
                continue

            covered += 1
            if 0 < aerobic < high_aerobic_threshold:
                low_aerobic += aerobic
            elif aerobic >= high_aerobic_threshold:
                high_aerobic += aerobic
            anaerobic += anaerobic_effect

        complete = covered == len(day_activities)
        result.append(
            DailyLoadFocus(
                date=current,
                activity_count=len(day_activities),
                covered_activities=covered,
                complete=complete,
                low_aerobic=round(low_aerobic, 3) if complete else None,
                high_aerobic=round(high_aerobic, 3) if complete else None,
                anaerobic=round(anaerobic, 3) if complete else None,
            )
        )
        current += timedelta(days=1)

    return result
