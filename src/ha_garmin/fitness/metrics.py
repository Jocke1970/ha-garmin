"""Additional training-load metrics for Garmin Fitness."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta

from .const import ACWR_ACUTE_DAYS, ACWR_CHRONIC_DAYS, RAMP_RATE_PERIOD_DAYS
from .models import DailyLoad, TrainingLoadPoint


@dataclass(frozen=True, slots=True)
class AcwrPoint:
    """One daily acute:chronic workload ratio point."""

    date: date
    acute_average: float
    chronic_average: float
    acwr: float | None


@dataclass(frozen=True, slots=True)
class RampRatePoint:
    """One daily CTL seven-day change point."""

    date: date
    ctl: float
    ctl_7d_ago: float
    ramp_rate: float


def compute_acwr(
    daily_loads: Iterable[DailyLoad],
    acute_days: int = ACWR_ACUTE_DAYS,
    chronic_days: int = ACWR_CHRONIC_DAYS,
) -> list[AcwrPoint]:
    """Compute rolling-average ACWR once a full chronic window exists.

    ACWR is the acute rolling average divided by the chronic rolling average.
    A zero chronic average has no meaningful ratio and therefore returns
    ``None`` rather than infinity.
    """
    if acute_days <= 0 or chronic_days <= 0:
        raise ValueError("ACWR windows must be positive")
    if acute_days >= chronic_days:
        raise ValueError("acute_days must be smaller than chronic_days")

    days = list(daily_loads)
    if not days:
        return []

    for index, day in enumerate(days):
        if day.load is None or not day.complete:
            raise ValueError(f"Daily load is incomplete for {day.date.isoformat()}")
        if index and day.date != days[index - 1].date + timedelta(days=1):
            raise ValueError("Daily load series must contain consecutive dates")

    loads = [float(day.load) for day in days if day.load is not None]
    result: list[AcwrPoint] = []
    for index in range(chronic_days - 1, len(days)):
        acute_window = loads[index - acute_days + 1 : index + 1]
        chronic_window = loads[index - chronic_days + 1 : index + 1]
        acute_average = sum(acute_window) / acute_days
        chronic_average = sum(chronic_window) / chronic_days
        ratio = acute_average / chronic_average if chronic_average > 0 else None
        result.append(
            AcwrPoint(
                date=days[index].date,
                acute_average=round(acute_average, 3),
                chronic_average=round(chronic_average, 3),
                acwr=round(ratio, 3) if ratio is not None else None,
            )
        )
    return result


def compute_ramp_rate(
    training_points: Iterable[TrainingLoadPoint],
    period_days: int = RAMP_RATE_PERIOD_DAYS,
) -> list[RampRatePoint]:
    """Compute CTL change compared with ``period_days`` earlier."""
    if period_days <= 0:
        raise ValueError("period_days must be positive")

    points = list(training_points)
    for index, point in enumerate(points):
        if index and point.date != points[index - 1].date + timedelta(days=1):
            raise ValueError("Training-load series must contain consecutive dates")

    result: list[RampRatePoint] = []
    for index in range(period_days, len(points)):
        current = points[index]
        previous = points[index - period_days]
        result.append(
            RampRatePoint(
                date=current.date,
                ctl=current.ctl,
                ctl_7d_ago=previous.ctl,
                ramp_rate=round(current.ctl - previous.ctl, 3),
            )
        )
    return result
