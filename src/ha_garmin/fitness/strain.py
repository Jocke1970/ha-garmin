"""TRIMP-derived strain helpers for Garmin Fitness."""

from __future__ import annotations

import math
from collections.abc import Iterable

from .const import DEFAULT_PERSONAL_TRIMP_MAX, STRAIN_HARD_DAY_THRESHOLD


def compute_strain_score(
    trimp: float,
    personal_trimp_max: float = DEFAULT_PERSONAL_TRIMP_MAX,
) -> float:
    """Convert TRIMP to a bounded 0-21 WHOOP-like strain score.

    The transformation is intentionally kept separate from canonical training
    load. CTL/ATL can use raw TRIMP while the user-facing strain score remains a
    presentation/insight metric.
    """
    if personal_trimp_max <= 0:
        raise ValueError("personal_trimp_max must be positive")
    if trimp <= 0:
        return 0.0

    score = 21.0 * (1.0 - math.exp(-trimp / personal_trimp_max))
    return round(min(21.0, max(0.0, score)), 2)


def calibrate_personal_trimp_max(
    historical_trimp: Iterable[float],
    *,
    min_sessions: int = 30,
    multiplier: float = 1.2,
) -> float | None:
    """Estimate a personal TRIMP maximum after enough valid sessions.

    The PulseCoach-inspired calibration is max historical TRIMP multiplied by
    1.2. Until ``min_sessions`` positive sessions exist, ``None`` is returned so
    callers can continue using the documented default rather than pretending a
    sparse history is personalized.
    """
    if min_sessions <= 0:
        raise ValueError("min_sessions must be positive")
    if multiplier <= 1.0:
        raise ValueError("multiplier must be greater than 1")

    values = [float(value) for value in historical_trimp if value > 0]
    if len(values) < min_sessions:
        return None
    return round(max(values) * multiplier, 3)


def count_consecutive_hard_days(
    strain_scores_newest_first: Iterable[float],
    threshold: float = STRAIN_HARD_DAY_THRESHOLD,
) -> int:
    """Count consecutive recent days above the hard-session threshold."""
    if threshold < 0:
        raise ValueError("threshold cannot be negative")

    count = 0
    for score in strain_scores_newest_first:
        if score > threshold:
            count += 1
        else:
            break
    return count
