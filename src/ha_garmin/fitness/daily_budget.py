"""Conservative daily training-load budget recommendations.

The budget deliberately reuses the canonical Fitness V4 load calculations. It
simulates a higher total TRIMP for the current day, then finds the largest total
that stays inside transparent workload-policy limits. The result is a workload
planning heuristic, not a medical or overtraining guarantee.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

from .const import STRAIN_HARD_DAY_THRESHOLD
from .models import DailyLoad
from .pipeline import TrainingHistoryResult, build_training_history_from_daily_loads
from .strain import compute_strain_score

DAILY_LOAD_BUDGET_POLICY_VERSION = 1
DAILY_LOAD_BUDGET_ACWR_LIMIT = 1.30
DAILY_LOAD_BUDGET_TSB_FLOOR_ABSOLUTE = 10.0
DAILY_LOAD_BUDGET_TSB_FLOOR_CTL_RATIO = 0.50
DAILY_LOAD_BUDGET_RAMP_ABSOLUTE_MIN = 5.0
DAILY_LOAD_BUDGET_RAMP_CTL_RATIO = 0.10
DAILY_LOAD_BUDGET_RECOVERY_CAUTION_MODIFIER = 0.70
DAILY_LOAD_BUDGET_STALE_DATA_MODIFIER = 0.85

BudgetConstraint = Literal["acwr", "strain", "tsb", "ramp_rate"]
BudgetLimitingFactor = Literal[
    "acwr",
    "strain",
    "tsb",
    "ramp_rate",
    "recovery_caution",
    "insufficient_or_stale_data",
]
RecoveryModifierReason = Literal[
    "none",
    "recovery_caution",
    "insufficient_or_stale_data",
]


@dataclass(frozen=True, slots=True)
class ProjectedTrainingState:
    """Canonical Fitness metrics after simulating one total daily load."""

    total_load: float
    acwr: float | None
    strain: float
    tsb: float
    ramp_rate: float | None


@dataclass(frozen=True, slots=True)
class DailyLoadBudget:
    """Presentation-neutral recommended total and remaining load for today."""

    date: str
    policy_version: int
    current_load: float
    structural_max_load: float
    structural_remaining_load: float
    recommended_max_load: float
    remaining_load: float
    structural_limiting_factor: BudgetConstraint
    limiting_factor: BudgetLimitingFactor
    recovery_modifier: float
    recovery_modifier_reason: RecoveryModifierReason
    projected_acwr: float | None
    projected_strain: float
    projected_tsb: float
    projected_ramp_rate: float | None
    acwr_limit: float
    strain_limit: float
    tsb_floor: float
    ramp_rate_limit: float
    acwr_max_load: float
    strain_max_load: float
    tsb_max_load: float
    ramp_rate_max_load: float


def _replace_last_daily_load(
    history: TrainingHistoryResult,
    total_load: float,
) -> tuple[DailyLoad, ...]:
    """Return a complete load series with only today's load replaced."""
    days = history.daily_loads
    if not days:
        raise ValueError("Training history has no daily loads")
    last = days[-1]
    simulated = DailyLoad(
        date=last.date,
        activity_count=last.activity_count,
        loaded_activity_count=last.loaded_activity_count,
        known_load=total_load,
        load=total_load,
        complete=True,
    )
    return (*days[:-1], simulated)


def _project(
    history: TrainingHistoryResult,
    total_load: float,
    personal_trimp_max: float,
) -> ProjectedTrainingState:
    """Re-run canonical Fitness metrics after replacing today's total load."""
    simulated = build_training_history_from_daily_loads(
        history.source,
        _replace_last_daily_load(history, total_load),
    )
    if not simulated.assessment.ready or not simulated.training_points:
        raise ValueError("Training history must be complete before budgeting")

    current = simulated.training_points[-1]
    acwr = simulated.acwr_points[-1].acwr if simulated.acwr_points else None
    ramp_rate = (
        simulated.ramp_rate_points[-1].ramp_rate if simulated.ramp_rate_points else None
    )
    return ProjectedTrainingState(
        total_load=round(total_load, 3),
        acwr=acwr,
        strain=compute_strain_score(total_load, personal_trimp_max),
        tsb=current.tsb,
        ramp_rate=ramp_rate,
    )


def _strain_load_ceiling(personal_trimp_max: float, strain_limit: float) -> float:
    """Invert the canonical strain transform for one strain threshold."""
    if personal_trimp_max <= 0:
        raise ValueError("personal_trimp_max must be positive")
    if strain_limit <= 0:
        return 0.0
    if strain_limit >= 21.0:
        return personal_trimp_max * 10.0
    return -personal_trimp_max * math.log(1.0 - (strain_limit / 21.0))


def _constraint_passes(
    projected: ProjectedTrainingState,
    constraint: BudgetConstraint,
    *,
    acwr_limit: float,
    strain_limit: float,
    tsb_floor: float,
    ramp_rate_limit: float,
) -> bool:
    """Return whether one projected state stays inside one policy limit."""
    if constraint == "acwr":
        return projected.acwr is None or projected.acwr <= acwr_limit
    if constraint == "strain":
        return projected.strain <= strain_limit
    if constraint == "tsb":
        return projected.tsb >= tsb_floor
    if constraint == "ramp_rate":
        return projected.ramp_rate is None or projected.ramp_rate <= ramp_rate_limit
    raise ValueError(f"Unknown budget constraint: {constraint}")


def _max_total_for_constraint(
    history: TrainingHistoryResult,
    personal_trimp_max: float,
    current_load: float,
    search_ceiling: float,
    constraint: BudgetConstraint,
    *,
    acwr_limit: float,
    strain_limit: float,
    tsb_floor: float,
    ramp_rate_limit: float,
) -> float:
    """Find the highest total load that satisfies one monotonic constraint."""
    current = _project(history, current_load, personal_trimp_max)
    if not _constraint_passes(
        current,
        constraint,
        acwr_limit=acwr_limit,
        strain_limit=strain_limit,
        tsb_floor=tsb_floor,
        ramp_rate_limit=ramp_rate_limit,
    ):
        return current_load

    ceiling = _project(history, search_ceiling, personal_trimp_max)
    if _constraint_passes(
        ceiling,
        constraint,
        acwr_limit=acwr_limit,
        strain_limit=strain_limit,
        tsb_floor=tsb_floor,
        ramp_rate_limit=ramp_rate_limit,
    ):
        return search_ceiling

    low = current_load
    high = search_ceiling
    for _ in range(36):
        midpoint = (low + high) / 2.0
        projected = _project(history, midpoint, personal_trimp_max)
        if _constraint_passes(
            projected,
            constraint,
            acwr_limit=acwr_limit,
            strain_limit=strain_limit,
            tsb_floor=tsb_floor,
            ramp_rate_limit=ramp_rate_limit,
        ):
            low = midpoint
        else:
            high = midpoint

    # Round down so display rounding never pushes the recommendation over a cap.
    return math.floor(low * 10.0) / 10.0


def _recovery_modifier(
    insight_result_ids: tuple[str, ...],
) -> tuple[float, RecoveryModifierReason]:
    """Return a conservative modifier from established Insights result IDs."""
    if "recovery_caution" in insight_result_ids:
        return DAILY_LOAD_BUDGET_RECOVERY_CAUTION_MODIFIER, "recovery_caution"
    if "insufficient_or_stale_data" in insight_result_ids:
        return DAILY_LOAD_BUDGET_STALE_DATA_MODIFIER, "insufficient_or_stale_data"
    return 1.0, "none"


def recommend_daily_load_budget(
    history: TrainingHistoryResult,
    personal_trimp_max: float,
    *,
    insight_result_ids: tuple[str, ...] = (),
    acwr_limit: float = DAILY_LOAD_BUDGET_ACWR_LIMIT,
    strain_limit: float = STRAIN_HARD_DAY_THRESHOLD,
) -> DailyLoadBudget:
    """Recommend a conservative maximum total TRIMP and remaining budget today.

    Structural capacity is the minimum of four simulated limits: ACWR, canonical
    Strain, TSB and Ramp Rate. Current recovery Insights may reduce only the
    *remaining* capacity; favourable recovery never raises the structural cap.
    """
    if not history.assessment.ready or not history.daily_loads:
        raise ValueError("Training history must be complete before budgeting")
    if personal_trimp_max <= 0:
        raise ValueError("personal_trimp_max must be positive")
    if acwr_limit <= 0:
        raise ValueError("acwr_limit must be positive")
    if not 0 < strain_limit < 21:
        raise ValueError("strain_limit must be between 0 and 21")

    today = history.daily_loads[-1]
    if today.load is None:
        raise ValueError("Today's training load is incomplete")
    current_load = max(0.0, float(today.load))

    previous_ctl = (
        history.training_points[-2].ctl
        if len(history.training_points) >= 2
        else history.training_points[-1].ctl
    )
    tsb_floor = -max(
        DAILY_LOAD_BUDGET_TSB_FLOOR_ABSOLUTE,
        previous_ctl * DAILY_LOAD_BUDGET_TSB_FLOOR_CTL_RATIO,
    )
    ramp_rate_limit = max(
        DAILY_LOAD_BUDGET_RAMP_ABSOLUTE_MIN,
        previous_ctl * DAILY_LOAD_BUDGET_RAMP_CTL_RATIO,
    )

    strain_ceiling = _strain_load_ceiling(personal_trimp_max, strain_limit)
    search_ceiling = max(current_load, strain_ceiling)

    constraint_order: tuple[BudgetConstraint, ...] = (
        "acwr",
        "strain",
        "tsb",
        "ramp_rate",
    )
    maxima = {
        constraint: _max_total_for_constraint(
            history,
            personal_trimp_max,
            current_load,
            search_ceiling,
            constraint,
            acwr_limit=acwr_limit,
            strain_limit=strain_limit,
            tsb_floor=tsb_floor,
            ramp_rate_limit=ramp_rate_limit,
        )
        for constraint in constraint_order
    }
    structural_factor = min(constraint_order, key=maxima.__getitem__)
    structural_max = max(current_load, maxima[structural_factor])
    structural_remaining = max(0.0, structural_max - current_load)

    modifier, modifier_reason = _recovery_modifier(insight_result_ids)
    recommended_remaining = structural_remaining * modifier
    # Quantize only the *additional* capacity. Flooring the total could make a
    # fractional load already completed today appear lower than the real load.
    recommended_remaining = math.floor(recommended_remaining * 10.0) / 10.0
    recommended_max = current_load + recommended_remaining

    limiting_factor: BudgetLimitingFactor
    if modifier_reason != "none" and recommended_remaining < structural_remaining:
        limiting_factor = modifier_reason
    else:
        limiting_factor = structural_factor

    projected = _project(history, recommended_max, personal_trimp_max)
    return DailyLoadBudget(
        date=today.date.isoformat(),
        policy_version=DAILY_LOAD_BUDGET_POLICY_VERSION,
        current_load=round(current_load, 1),
        structural_max_load=round(structural_max, 1),
        structural_remaining_load=round(structural_remaining, 1),
        recommended_max_load=round(recommended_max, 1),
        remaining_load=round(recommended_remaining, 1),
        structural_limiting_factor=structural_factor,
        limiting_factor=limiting_factor,
        recovery_modifier=modifier,
        recovery_modifier_reason=modifier_reason,
        projected_acwr=projected.acwr,
        projected_strain=projected.strain,
        projected_tsb=projected.tsb,
        projected_ramp_rate=projected.ramp_rate,
        acwr_limit=acwr_limit,
        strain_limit=strain_limit,
        tsb_floor=round(tsb_floor, 1),
        ramp_rate_limit=round(ramp_rate_limit, 1),
        acwr_max_load=round(maxima["acwr"], 1),
        strain_max_load=round(maxima["strain"], 1),
        tsb_max_load=round(maxima["tsb"], 1),
        ramp_rate_max_load=round(maxima["ramp_rate"], 1),
    )
