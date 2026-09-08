"""Tests for conservative daily training-load budgeting."""

from datetime import date, timedelta

import pytest

from ha_garmin.fitness import (
    DailyLoad,
    build_training_history_from_daily_loads,
    recommend_daily_load_budget,
)


def _history(*, today_load: float, baseline_load: float = 20.0, days: int = 90):
    end = date(2026, 9, 8)
    daily_loads = []
    for offset in range(days):
        value = today_load if offset == days - 1 else baseline_load
        daily_loads.append(
            DailyLoad(
                date=end - timedelta(days=days - 1 - offset),
                activity_count=0 if value == 0 else 1,
                loaded_activity_count=0 if value == 0 else 1,
                known_load=value,
                load=value,
                complete=True,
            )
        )
    return build_training_history_from_daily_loads("trimp", daily_loads)


def test_daily_budget_uses_most_conservative_structural_constraint() -> None:
    budget = recommend_daily_load_budget(
        _history(today_load=20.0),
        personal_trimp_max=250.0,
    )

    assert budget.date == "2026-09-08"
    assert budget.current_load == 20.0
    assert budget.structural_limiting_factor == "tsb"
    assert budget.limiting_factor == "tsb"
    assert budget.structural_max_load == pytest.approx(69.1, abs=0.1)
    assert budget.recommended_max_load == budget.structural_max_load
    assert budget.remaining_load == pytest.approx(49.1, abs=0.1)
    assert budget.projected_tsb >= budget.tsb_floor
    assert budget.projected_acwr is None or budget.projected_acwr <= budget.acwr_limit
    assert budget.projected_strain <= budget.strain_limit
    assert (
        budget.projected_ramp_rate is None
        or budget.projected_ramp_rate <= budget.ramp_rate_limit
    )


def test_recovery_caution_reduces_only_remaining_capacity() -> None:
    baseline = recommend_daily_load_budget(
        _history(today_load=20.0),
        personal_trimp_max=250.0,
    )
    cautious = recommend_daily_load_budget(
        _history(today_load=20.0),
        personal_trimp_max=250.0,
        insight_result_ids=("recovery_caution",),
    )

    assert cautious.current_load == baseline.current_load
    assert cautious.structural_max_load == baseline.structural_max_load
    assert cautious.recovery_modifier == 0.70
    assert cautious.recovery_modifier_reason == "recovery_caution"
    assert cautious.limiting_factor == "recovery_caution"
    assert cautious.remaining_load == pytest.approx(
        baseline.structural_remaining_load * 0.70,
        abs=0.1,
    )
    assert cautious.recommended_max_load == pytest.approx(
        cautious.current_load + cautious.remaining_load,
        abs=0.1,
    )


def test_stale_insight_data_applies_smaller_conservative_modifier() -> None:
    budget = recommend_daily_load_budget(
        _history(today_load=20.0),
        personal_trimp_max=250.0,
        insight_result_ids=("insufficient_or_stale_data",),
    )

    assert budget.recovery_modifier == 0.85
    assert budget.recovery_modifier_reason == "insufficient_or_stale_data"
    assert budget.limiting_factor == "insufficient_or_stale_data"
    assert budget.recommended_max_load < budget.structural_max_load


def test_favourable_insight_never_raises_structural_cap() -> None:
    baseline = recommend_daily_load_budget(
        _history(today_load=20.0),
        personal_trimp_max=250.0,
    )
    favourable = recommend_daily_load_budget(
        _history(today_load=20.0),
        personal_trimp_max=250.0,
        insight_result_ids=("favourable_training_signal",),
    )

    assert favourable.recovery_modifier == 1.0
    assert favourable.recommended_max_load == baseline.structural_max_load
    assert favourable.remaining_load == baseline.structural_remaining_load


def test_budget_never_recommends_negative_remaining_load_after_limit_is_exceeded() -> (
    None
):
    budget = recommend_daily_load_budget(
        _history(today_load=80.0),
        personal_trimp_max=250.0,
    )

    assert budget.current_load == 80.0
    assert budget.structural_max_load == 80.0
    assert budget.recommended_max_load == 80.0
    assert budget.remaining_load == 0.0
    assert budget.structural_limiting_factor == "tsb"


def test_budget_requires_complete_training_history() -> None:
    history = build_training_history_from_daily_loads(
        "trimp",
        [
            DailyLoad(
                date=date(2026, 9, 8),
                activity_count=1,
                loaded_activity_count=0,
                known_load=0.0,
                load=None,
                complete=False,
            )
        ],
    )

    with pytest.raises(ValueError, match="complete"):
        recommend_daily_load_budget(history, personal_trimp_max=250.0)
