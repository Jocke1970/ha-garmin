"""Deterministic Garmin Insights V1 rules.

Rules consume only :class:`InsightSnapshot`. They never fetch Garmin data, read
Home Assistant state, or alter the locked Fitness calculations.
"""

from __future__ import annotations

from collections.abc import Iterable

from ..fitness import compute_load_focus_contribution
from ..fitness.const import LOAD_FOCUS_DOMINANCE_RATIO
from .models import (
    InsightConfidence,
    InsightEvidence,
    InsightResult,
    InsightSeverity,
    InsightSnapshot,
)

INSIGHT_RULESET_VERSION = 1

_ACWR_SPIKE_THRESHOLD = 1.5
_ACWR_WARNING_THRESHOLD = 1.8
_ACWR_LOW_THRESHOLD = 0.5

_READINESS_LOW_THRESHOLD = 40.0
_READINESS_VERY_LOW_THRESHOLD = 20.0
_READINESS_GOOD_THRESHOLD = 70.0
_SLEEP_LOW_THRESHOLD = 60.0
_SLEEP_GOOD_THRESHOLD = 75.0
_BODY_BATTERY_LOW_THRESHOLD = 30.0
_BODY_BATTERY_GOOD_THRESHOLD = 60.0
_STRESS_HIGH_THRESHOLD = 50.0
_RESTING_HR_ELEVATION_BPM = 5.0
_RECOVERY_LONG_MINUTES = 24.0 * 60.0
_RECOVERY_CAUTION_SIGNAL_COUNT = 2

_RECENT_FOCUS_MIN_ACTIVITIES = 3


def _result(
    rule_id: str,
    *,
    severity: InsightSeverity,
    priority: int,
    confidence: InsightConfidence,
    evidence: Iterable[InsightEvidence],
) -> InsightResult:
    """Build one stable rule result with translation keys derived from its ID."""
    return InsightResult(
        id=rule_id,
        severity=severity,
        priority=priority,
        confidence=confidence,
        title_key=f"insights.{rule_id}.title",
        message_key=f"insights.{rule_id}.message",
        evidence=tuple(evidence),
        ruleset_version=INSIGHT_RULESET_VERSION,
    )


def _data_quality_rule(snapshot: InsightSnapshot) -> InsightResult | None:
    """Surface incomplete/stale inputs without pretending missing values are safe."""
    quality = snapshot.data_quality
    if quality.complete:
        return None

    evidence: list[InsightEvidence] = []
    evidence.extend(
        InsightEvidence(code=f"stale.{field}") for field in quality.stale_fields
    )
    evidence.extend(
        InsightEvidence(code=f"missing_source.{source}")
        for source in quality.missing_sources
    )
    evidence.extend(
        InsightEvidence(code=f"missing_field.{field}")
        for field in quality.missing_fields
    )
    if not evidence:
        evidence.append(InsightEvidence(code="snapshot_incomplete"))

    return _result(
        "insufficient_or_stale_data",
        severity="info",
        priority=100,
        confidence="high",
        evidence=evidence,
    )


def _load_spike_rule(snapshot: InsightSnapshot) -> InsightResult | None:
    """Flag a high acute/chronic load ratio using the canonical Fitness ACWR."""
    training = snapshot.training
    if not training.ready or training.acwr is None:
        return None
    if training.acwr < _ACWR_SPIKE_THRESHOLD:
        return None

    evidence = [
        InsightEvidence(
            code="acwr_above_spike_threshold",
            value=round(training.acwr, 3),
            threshold=_ACWR_SPIKE_THRESHOLD,
        )
    ]
    if training.ramp_rate is not None and training.ramp_rate > 0:
        evidence.append(
            InsightEvidence(
                code="positive_ramp_rate", value=round(training.ramp_rate, 3)
            )
        )
    if (
        training.atl is not None
        and training.ctl is not None
        and training.atl > training.ctl
    ):
        evidence.append(
            InsightEvidence(
                code="atl_above_ctl", value=round(training.atl - training.ctl, 3)
            )
        )

    return _result(
        "load_spike",
        severity=("warning" if training.acwr >= _ACWR_WARNING_THRESHOLD else "caution"),
        priority=95,
        confidence="high" if len(evidence) >= 2 else "medium",
        evidence=evidence,
    )


def _low_recent_load_rule(snapshot: InsightSnapshot) -> InsightResult | None:
    """Flag a materially low recent load relative to an established chronic load."""
    training = snapshot.training
    if (
        not training.ready
        or training.acwr is None
        or training.ctl is None
        or training.ctl <= 0
        or training.acwr > _ACWR_LOW_THRESHOLD
    ):
        return None

    evidence = [
        InsightEvidence(
            code="acwr_below_low_load_threshold",
            value=round(training.acwr, 3),
            threshold=_ACWR_LOW_THRESHOLD,
        )
    ]
    declining_ramp = training.ramp_rate is not None and training.ramp_rate < 0
    sparse_week = len(snapshot.recent_activities) <= 1

    if declining_ramp and training.ramp_rate is not None:
        evidence.append(
            InsightEvidence(
                code="negative_ramp_rate", value=round(training.ramp_rate, 3)
            )
        )
    if sparse_week:
        evidence.append(
            InsightEvidence(
                code="sparse_recent_activity_window",
                value=len(snapshot.recent_activities),
                threshold=1.0,
            )
        )

    # ACWR alone is intentionally not enough for this V1 message.
    if len(evidence) < 2:
        return None

    return _result(
        "low_recent_load",
        severity="info",
        priority=45,
        confidence="high" if declining_ramp and sparse_week else "medium",
        evidence=evidence,
    )


def _hrv_negative_evidence(snapshot: InsightSnapshot) -> InsightEvidence | None:
    recovery = snapshot.recovery
    if (
        recovery.hrv_last_night_avg is not None
        and recovery.hrv_baseline_balanced_low is not None
        and recovery.hrv_last_night_avg < recovery.hrv_baseline_balanced_low
    ):
        return InsightEvidence(
            code="hrv_below_balanced_baseline",
            value=round(recovery.hrv_last_night_avg, 2),
            threshold=recovery.hrv_baseline_balanced_low,
        )

    status = recovery.hrv_status.upper() if recovery.hrv_status else None
    if status in {"LOW", "UNBALANCED"}:
        return InsightEvidence(code="hrv_status_unfavourable", value=status)
    return None


def _negative_recovery_evidence(
    snapshot: InsightSnapshot,
) -> tuple[InsightEvidence, ...]:
    """Return independent exact-date recovery caution signals."""
    if not snapshot.data_quality.recovery_current:
        return ()

    recovery = snapshot.recovery
    evidence: list[InsightEvidence] = []

    if (
        recovery.training_readiness is not None
        and recovery.training_readiness < _READINESS_LOW_THRESHOLD
    ):
        evidence.append(
            InsightEvidence(
                code="training_readiness_low",
                value=round(recovery.training_readiness, 1),
                threshold=_READINESS_LOW_THRESHOLD,
            )
        )
    if recovery.sleep_score is not None and recovery.sleep_score < _SLEEP_LOW_THRESHOLD:
        evidence.append(
            InsightEvidence(
                code="sleep_score_low",
                value=round(recovery.sleep_score, 1),
                threshold=_SLEEP_LOW_THRESHOLD,
            )
        )
    if (
        recovery.body_battery_most_recent is not None
        and recovery.body_battery_most_recent < _BODY_BATTERY_LOW_THRESHOLD
    ):
        evidence.append(
            InsightEvidence(
                code="body_battery_low",
                value=round(recovery.body_battery_most_recent, 1),
                threshold=_BODY_BATTERY_LOW_THRESHOLD,
            )
        )
    if (
        recovery.average_stress_level is not None
        and recovery.average_stress_level > _STRESS_HIGH_THRESHOLD
    ):
        evidence.append(
            InsightEvidence(
                code="average_stress_high",
                value=round(recovery.average_stress_level, 1),
                threshold=_STRESS_HIGH_THRESHOLD,
            )
        )
    if (
        recovery.recovery_minutes is not None
        and recovery.recovery_minutes > _RECOVERY_LONG_MINUTES
    ):
        evidence.append(
            InsightEvidence(
                code="recovery_time_long",
                value=round(recovery.recovery_minutes, 1),
                threshold=_RECOVERY_LONG_MINUTES,
            )
        )
    if (
        recovery.resting_hr is not None
        and recovery.resting_hr_7d_avg is not None
        and recovery.resting_hr
        >= recovery.resting_hr_7d_avg + _RESTING_HR_ELEVATION_BPM
    ):
        evidence.append(
            InsightEvidence(
                code="resting_hr_elevated",
                value=round(recovery.resting_hr - recovery.resting_hr_7d_avg, 1),
                threshold=_RESTING_HR_ELEVATION_BPM,
            )
        )

    hrv_evidence = _hrv_negative_evidence(snapshot)
    if hrv_evidence is not None:
        evidence.append(hrv_evidence)

    return tuple(evidence)


def _recovery_caution_rule(snapshot: InsightSnapshot) -> InsightResult | None:
    """Require multiple independent negative recovery signals before cautioning."""
    evidence = _negative_recovery_evidence(snapshot)
    if len(evidence) < _RECOVERY_CAUTION_SIGNAL_COUNT:
        return None

    readiness = snapshot.recovery.training_readiness
    severe = (
        len(evidence) >= 4
        or readiness is not None
        and readiness < _READINESS_VERY_LOW_THRESHOLD
    )
    return _result(
        "recovery_caution",
        severity="warning" if severe else "caution",
        priority=90,
        confidence="high" if len(evidence) >= 3 else "medium",
        evidence=evidence,
    )


def _hrv_positive_evidence(snapshot: InsightSnapshot) -> InsightEvidence | None:
    recovery = snapshot.recovery
    status = recovery.hrv_status.upper() if recovery.hrv_status else None
    if status == "BALANCED":
        return InsightEvidence(code="hrv_balanced", value=status)

    if (
        recovery.hrv_last_night_avg is not None
        and recovery.hrv_baseline_balanced_low is not None
        and recovery.hrv_baseline_balanced_upper is not None
        and recovery.hrv_baseline_balanced_low
        <= recovery.hrv_last_night_avg
        <= recovery.hrv_baseline_balanced_upper
    ):
        return InsightEvidence(
            code="hrv_within_balanced_baseline",
            value=round(recovery.hrv_last_night_avg, 2),
        )
    return None


def _favourable_training_rule(snapshot: InsightSnapshot) -> InsightResult | None:
    """Emit a positive signal only when several current recovery inputs agree."""
    if not snapshot.data_quality.recovery_current:
        return None

    recovery = snapshot.recovery
    if (
        recovery.training_readiness is None
        or recovery.training_readiness < _READINESS_GOOD_THRESHOLD
        or recovery.sleep_score is None
        or recovery.sleep_score < _SLEEP_GOOD_THRESHOLD
    ):
        return None

    evidence = [
        InsightEvidence(
            code="training_readiness_good",
            value=round(recovery.training_readiness, 1),
            threshold=_READINESS_GOOD_THRESHOLD,
        ),
        InsightEvidence(
            code="sleep_score_good",
            value=round(recovery.sleep_score, 1),
            threshold=_SLEEP_GOOD_THRESHOLD,
        ),
    ]

    hrv_evidence = _hrv_positive_evidence(snapshot)
    if hrv_evidence is not None:
        evidence.append(hrv_evidence)
    if (
        recovery.body_battery_most_recent is not None
        and recovery.body_battery_most_recent >= _BODY_BATTERY_GOOD_THRESHOLD
    ):
        evidence.append(
            InsightEvidence(
                code="body_battery_good",
                value=round(recovery.body_battery_most_recent, 1),
                threshold=_BODY_BATTERY_GOOD_THRESHOLD,
            )
        )
    if (
        recovery.resting_hr is not None
        and recovery.resting_hr_7d_avg is not None
        and recovery.resting_hr <= recovery.resting_hr_7d_avg + 2.0
    ):
        evidence.append(
            InsightEvidence(
                code="resting_hr_near_or_below_baseline",
                value=round(recovery.resting_hr - recovery.resting_hr_7d_avg, 1),
                threshold=2.0,
            )
        )

    if len(evidence) < 3:
        return None

    return _result(
        "favourable_training_signal",
        severity="positive",
        priority=30,
        confidence="high" if len(evidence) >= 4 else "medium",
        evidence=evidence,
    )


def _load_focus_imbalance_rule(snapshot: InsightSnapshot) -> InsightResult | None:
    """Detect a strong seven-day Training Effect bucket dominance conservatively."""
    activities = snapshot.recent_activities
    if len(activities) < _RECENT_FOCUS_MIN_ACTIVITIES:
        return None

    totals = {"low_aerobic": 0.0, "high_aerobic": 0.0, "anaerobic": 0.0}
    for activity in activities:
        contribution = compute_load_focus_contribution(
            activity.aerobic_training_effect,
            activity.anaerobic_training_effect,
        )
        # Do not infer a distribution from a partially observed recent window.
        if contribution is None:
            return None
        for bucket in totals:
            totals[bucket] += contribution[bucket]

    total_effect = sum(totals.values())
    if total_effect <= 0:
        return None

    dominant_bucket = max(totals, key=totals.__getitem__)
    dominant = totals[dominant_bucket]
    others = total_effect - dominant
    if others > 0 and dominant < others * LOAD_FOCUS_DOMINANCE_RATIO:
        return None

    evidence = [
        InsightEvidence(
            code=f"dominant_focus.{dominant_bucket}",
            value=round(dominant, 3),
        ),
        InsightEvidence(
            code="recent_focus_activity_count",
            value=len(activities),
            threshold=float(_RECENT_FOCUS_MIN_ACTIVITIES),
        ),
    ]
    if others > 0:
        evidence.append(
            InsightEvidence(
                code="dominance_ratio",
                value=round(dominant / others, 3),
                threshold=LOAD_FOCUS_DOMINANCE_RATIO,
            )
        )
    else:
        evidence.append(InsightEvidence(code="exclusive_recent_focus"))

    return _result(
        "load_focus_imbalance",
        severity="info",
        priority=40,
        confidence="high" if len(activities) >= 5 else "medium",
        evidence=evidence,
    )


def evaluate_insights(snapshot: InsightSnapshot) -> tuple[InsightResult, ...]:
    """Evaluate all V1 rules, resolve conflicts and return deterministic ordering.

    Caution/warning signals suppress the positive training signal. Independent
    observations such as low recent load and load-focus imbalance may coexist.
    """
    candidates = (
        _data_quality_rule(snapshot),
        _load_spike_rule(snapshot),
        _recovery_caution_rule(snapshot),
        _low_recent_load_rule(snapshot),
        _load_focus_imbalance_rule(snapshot),
        _favourable_training_rule(snapshot),
    )
    results = [result for result in candidates if result is not None]

    ids = {result.id for result in results}
    if {"load_spike", "recovery_caution"} & ids:
        results = [
            result for result in results if result.id != "favourable_training_signal"
        ]

    return tuple(sorted(results, key=lambda result: (-result.priority, result.id)))
