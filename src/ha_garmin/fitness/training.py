"""Training-load calculations for Garmin Fitness."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import timedelta

from .models import DailyLoad, TrainingLoadPoint

_CTL_ALPHA = 2.0 / (42.0 + 1.0)
_ATL_ALPHA = 2.0 / (7.0 + 1.0)


def compute_ctl_atl_tsb(
    daily_loads: Iterable[DailyLoad],
) -> list[TrainingLoadPoint]:
    """Compute a continuous 42-day CTL / 7-day ATL / TSB series.

    The function deliberately requires a complete daily-load series. Missing
    activity load must be resolved by the chosen load source before this stage;
    treating an incomplete activity day as zero would bias CTL/ATL downward.
    """
    days = list(daily_loads)
    if not days:
        return []

    for index, day in enumerate(days):
        if day.load is None or not day.complete:
            raise ValueError(f"Daily load is incomplete for {day.date.isoformat()}")
        if index and day.date != days[index - 1].date + timedelta(days=1):
            raise ValueError("Daily load series must contain consecutive dates")

    first_load = float(days[0].load)
    ctl = first_load
    atl = first_load
    result = [
        TrainingLoadPoint(
            date=days[0].date,
            daily_load=first_load,
            ctl=round(ctl, 3),
            atl=round(atl, 3),
            tsb=round(ctl - atl, 3),
        )
    ]

    for day in days[1:]:
        load = float(day.load)
        ctl = (_CTL_ALPHA * load) + ((1.0 - _CTL_ALPHA) * ctl)
        atl = (_ATL_ALPHA * load) + ((1.0 - _ATL_ALPHA) * atl)
        result.append(
            TrainingLoadPoint(
                date=day.date,
                daily_load=load,
                ctl=round(ctl, 3),
                atl=round(atl, 3),
                tsb=round(ctl - atl, 3),
            )
        )

    return result
