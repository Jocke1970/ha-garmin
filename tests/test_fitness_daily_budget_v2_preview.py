"""Tests for the experimental Daily Load Budget V2 preview."""

from datetime import date, timedelta

from ha_garmin.fitness import DailyLoad, build_training_history_from_daily_loads
from ha_garmin.fitness.daily_budget_v2_preview import preview_daily_load_budget_v2


def _history(loads: list[float]):
    end = date(2026, 9, 12)
    days = [
        DailyLoad(
            date=end - timedelta(days=len(loads) - 1 - index),
            activity_count=0 if value == 0 else 1,
            loaded_activity_count=0 if value == 0 else 1,
            known_load=value,
            load=value,
            complete=True,
        )
        for index, value in enumerate(loads)
    ]
    return build_training_history_from_daily_loads("trimp", days)


def _reentry_history():
    # Established load was higher, then dropped. A recent 20 + 10 TRIMP pair
    # makes 7-day load high relative to the sparse 28-day window while CTL/ATL
    # recovery has already brought TSB positive and Ramp Rate negative.
    return _history([20.0] * 62 + [1.0] * 21 + [20.0, 10.0, 0.0, 0.0, 0.0, 0.0, 0.0])


def test_preview_leaves_normal_v1_budget_unchanged() -> None:
    preview = preview_daily_load_budget_v2(
        _history([20.0] * 90),
        personal_trimp_max=100.0,
    )

    assert preview.mode == "v1"
    assert not preview.reentry_eligible
    assert preview.reentry_blockers == ()
    assert preview.remaining_load == preview.v1_budget.remaining_load
    assert preview.recommended_max_load == preview.v1_budget.recommended_max_load


def test_preview_opens_small_reentry_budget_when_only_acwr_is_blocking() -> None:
    preview = preview_daily_load_budget_v2(
        _reentry_history(),
        personal_trimp_max=100.0,
    )

    assert preview.v1_budget.structural_limiting_factor == "acwr"
    assert preview.v1_budget.remaining_load == 0.0
    assert preview.current_acwr is not None and preview.current_acwr > 1.30
    assert preview.current_tsb >= 0.0
    assert preview.current_ramp_rate is not None and preview.current_ramp_rate <= 0.0

    assert preview.mode == "reentry"
    assert preview.reentry_eligible
    assert preview.reentry_blockers == ()
    assert 0.0 < preview.remaining_load < 5.0
    assert preview.structural_limiting_factor == "acwr"
    assert preview.projected_acwr is not None
    assert preview.projected_acwr <= preview.acwr_guard_limit
    assert preview.projected_strain <= preview.reentry_strain_limit


def test_preview_blocks_reentry_when_recovery_caution_is_present() -> None:
    preview = preview_daily_load_budget_v2(
        _reentry_history(),
        personal_trimp_max=100.0,
        insight_result_ids=("recovery_caution",),
    )

    assert preview.mode == "blocked"
    assert not preview.reentry_eligible
    assert "recovery_caution" in preview.reentry_blockers
    assert preview.remaining_load == 0.0


def test_preview_blocks_reentry_when_insight_data_is_incomplete() -> None:
    preview = preview_daily_load_budget_v2(
        _reentry_history(),
        personal_trimp_max=100.0,
        insight_result_ids=("insufficient_or_stale_data",),
    )

    assert preview.mode == "blocked"
    assert "insufficient_or_stale_data" in preview.reentry_blockers
    assert preview.remaining_load == 0.0


def test_preview_blocks_reentry_until_tsb_and_ramp_have_recovered() -> None:
    preview = preview_daily_load_budget_v2(
        _history([0.0] * 83 + [15.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]),
        personal_trimp_max=100.0,
    )

    assert preview.v1_budget.structural_limiting_factor == "acwr"
    assert preview.current_acwr is not None and preview.current_acwr > 1.30
    assert preview.mode == "blocked"
    assert (
        "tsb_below_zero" in preview.reentry_blockers
        or "ramp_positive" in preview.reentry_blockers
    )
    assert preview.remaining_load == 0.0
