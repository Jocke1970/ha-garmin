"""Home-Assistant-neutral export rows for training history."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .pipeline import TrainingHistoryResult


@dataclass(frozen=True, slots=True)
class TrainingHistoryExportRow:
    """One daily row ready for an application-specific persistence adapter."""

    date: date
    daily_load: float
    ctl: float
    atl: float
    tsb: float
    acwr: float | None
    ramp_rate: float | None


def export_training_history_rows(
    history: TrainingHistoryResult,
) -> list[TrainingHistoryExportRow]:
    """Flatten a complete training result without importing Home Assistant.

    ACWR and ramp rate naturally begin later than CTL/ATL/TSB because they need
    longer look-back windows. Their earlier values are exported as ``None``.
    """
    if not history.assessment.ready:
        raise ValueError("Training history is incomplete and cannot be exported")

    acwr_by_date = {point.date: point.acwr for point in history.acwr_points}
    ramp_by_date = {point.date: point.ramp_rate for point in history.ramp_rate_points}

    return [
        TrainingHistoryExportRow(
            date=point.date,
            daily_load=point.daily_load,
            ctl=point.ctl,
            atl=point.atl,
            tsb=point.tsb,
            acwr=acwr_by_date.get(point.date),
            ramp_rate=ramp_by_date.get(point.date),
        )
        for point in history.training_points
    ]
