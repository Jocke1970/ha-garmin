"""Experimental Daily Load Budget V2 preview.

This module is intentionally not wired into the public Fitness API or Home
Assistant runtime. It lets us exercise a less binary ACWR policy against the
same canonical Fitness calculations before deciding whether to replace V1.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .daily_budget import (
    DAILY_LOAD_BUDGET_ACWR_LIMIT,
    BudgetConstraint,
    DailyLoadBudget,
    _max_total_for_constraint,
    _project,
    _strain_load_ceiling,
    recommend_daily_load_budget,
)
from .pipeline import TrainingHistoryResult

DAILY_LOAD_BUDGET_V2_PREVIEW_POLICY_VERSION = 2
DAILY_LOAD_BUDGET_V2_REENTRY_STRAIN_LIMIT = 4.0
DAILY_LOAD_BUDGET_V2_REENTRY_ACWR_GROWTH = 0.05

PreviewMode = Literal["v1", "reentry", "blocked"]


@dataclass(frozen=True, slots=True)
class DailyLoadBudgetV2Preview:
    """Side-by-side V1/V2 preview without changing production behaviour."""

    date: str
    policy_version: int
    mode: PreviewMode
    reentry_eligible: bool
    reentry_blockers: tuple[str, ...]
    current_load: float
    current_acwr: float | None
    current_tsb: float
    current_ramp_rate: float | None
    recommended_max_load: float
    remaining_load: float
    structural_limiting_factor: BudgetConstraint
    projected_acwr: float | None
    projected_strain: float
    projected_tsb: float
    projected_ramp_rate: float | None
    acwr_guard_limit: float
    reentry_strain_limit: float
    v1_budget: DailyLoadBudget


def preview_daily_load_budget_v2(
    history: TrainingHistoryResult,
    personal_trimp_max: float,
    *,
    insight_result_ids: tuple[str, ...] = (),
    acwr_limit: float = DAILY_LOAD_BUDGET_ACWR_LIMIT,
    reentry_strain_limit: float = DAILY_LOAD_BUDGET_V2_REENTRY_STRAIN_LIMIT,
    reentry_acwr_growth: float = DAILY_LOAD_BUDGET_V2_REENTRY_ACWR_GROWTH,
) -> DailyLoadBudgetV2Preview:
    """Preview a conservative re-entry mode when V1 is blocked only by ACWR.

    V1 remains authoritative whenever it still has capacity or another
    structural constraint is the blocker. Re-entry is considered only when the
    current ACWR is already above the normal limit and V1 therefore has no
    remaining capacity because of ACWR.

    Re-entry requires non-negative TSB, non-positive Ramp Rate, and no recovery
    caution or incomplete/stale Insight signal. If eligible, the preview allows
    only the minimum capacity permitted by:

    * ACWR no more than ``reentry_acwr_growth`` above its already-high value;
    * a deliberately light Strain ceiling;
    * the existing V1 TSB floor; and
    * the existing V1 Ramp Rate ceiling.
    """
    if not 0 < reentry_strain_limit < 21:
        raise ValueError("reentry_strain_limit must be between 0 and 21")
    if reentry_acwr_growth < 0:
        raise ValueError("reentry_acwr_growth must be non-negative")

    v1 = recommend_daily_load_budget(
        history,
        personal_trimp_max,
        insight_result_ids=insight_result_ids,
        acwr_limit=acwr_limit,
    )
    current = _project(history, v1.current_load, personal_trimp_max)
    acwr_guard_limit = (
        acwr_limit
        if current.acwr is None
        else max(acwr_limit, current.acwr * (1.0 + reentry_acwr_growth))
    )

    def _result(
        *,
        mode: PreviewMode,
        blockers: tuple[str, ...],
        recommended_max_load: float,
        structural_factor: BudgetConstraint,
    ) -> DailyLoadBudgetV2Preview:
        projected = _project(history, recommended_max_load, personal_trimp_max)
        return DailyLoadBudgetV2Preview(
            date=v1.date,
            policy_version=DAILY_LOAD_BUDGET_V2_PREVIEW_POLICY_VERSION,
            mode=mode,
            reentry_eligible=mode == "reentry",
            reentry_blockers=blockers,
            current_load=v1.current_load,
            current_acwr=current.acwr,
            current_tsb=current.tsb,
            current_ramp_rate=current.ramp_rate,
            recommended_max_load=round(recommended_max_load, 1),
            remaining_load=round(max(0.0, recommended_max_load - v1.current_load), 1),
            structural_limiting_factor=structural_factor,
            projected_acwr=projected.acwr,
            projected_strain=projected.strain,
            projected_tsb=projected.tsb,
            projected_ramp_rate=projected.ramp_rate,
            acwr_guard_limit=round(acwr_guard_limit, 3),
            reentry_strain_limit=reentry_strain_limit,
            v1_budget=v1,
        )

    v1_blocked_by_acwr = (
        v1.remaining_load == 0.0
        and v1.structural_limiting_factor == "acwr"
        and current.acwr is not None
        and current.acwr > acwr_limit
    )
    if not v1_blocked_by_acwr:
        return _result(
            mode="v1",
            blockers=(),
            recommended_max_load=v1.recommended_max_load,
            structural_factor=v1.structural_limiting_factor,
        )

    blockers: list[str] = []
    if current.tsb < 0:
        blockers.append("tsb_below_zero")
    if current.ramp_rate is None:
        blockers.append("ramp_unavailable")
    elif current.ramp_rate > 0:
        blockers.append("ramp_positive")
    if "recovery_caution" in insight_result_ids:
        blockers.append("recovery_caution")
    if "insufficient_or_stale_data" in insight_result_ids:
        blockers.append("insufficient_or_stale_data")

    if blockers:
        return _result(
            mode="blocked",
            blockers=tuple(blockers),
            recommended_max_load=v1.current_load,
            structural_factor="acwr",
        )

    search_ceiling = max(
        v1.current_load,
        _strain_load_ceiling(personal_trimp_max, reentry_strain_limit),
    )
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
            v1.current_load,
            search_ceiling,
            constraint,
            acwr_limit=acwr_guard_limit,
            strain_limit=reentry_strain_limit,
            tsb_floor=v1.tsb_floor,
            ramp_rate_limit=v1.ramp_rate_limit,
        )
        for constraint in constraint_order
    }
    structural_factor = min(constraint_order, key=maxima.__getitem__)
    recommended_max = max(v1.current_load, maxima[structural_factor])

    return _result(
        mode="reentry",
        blockers=(),
        recommended_max_load=recommended_max,
        structural_factor=structural_factor,
    )
