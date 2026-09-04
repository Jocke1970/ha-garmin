"""Tests for the Home Assistant-facing Garmin Fitness history facade."""

from datetime import date
from unittest.mock import AsyncMock, patch

import pytest

from ha_garmin import GarminAuth, GarminClient, GarminHistoryClient
from ha_garmin.fitness import CANONICAL_LOAD_SOURCE


def _make_client() -> GarminClient:
    auth = GarminAuth()
    auth.di_token = "fake_di_token"
    return GarminClient(auth)


def _raw_activity() -> dict:
    return {
        "activityId": 1,
        "calendarDate": "2026-09-02",
        "startTimeGMT": "2026-09-02T16:00:00",
        "startTimeLocal": "2026-09-02T18:00:00",
        "activityType": {"typeKey": "indoor_rowing"},
        "duration": 600,
        "averageHR": 120,
        "maxHR": 140,
    }


async def test_fetch_trimp_training_history_reuses_strict_history_inputs() -> None:
    client = _make_client()
    history = GarminHistoryClient(client)
    start = date(2026, 9, 1)
    end = date(2026, 9, 2)

    with (
        patch.object(
            history,
            "get_activities_by_date",
            new_callable=AsyncMock,
            return_value=[_raw_activity()],
        ) as activity_fetch,
        patch.object(
            history,
            "get_resting_heart_rate_range",
            new_callable=AsyncMock,
            return_value={date(2026, 9, 2): 50.0},
        ) as rhr_fetch,
    ):
        result = await history.fetch_trimp_training_history(
            start,
            end,
            user_max_hr=175,
            sex="male",
        )

    activity_fetch.assert_awaited_once_with(start, end)
    rhr_fetch.assert_awaited_once_with(start, end)
    assert CANONICAL_LOAD_SOURCE == "trimp"
    assert result.source == "trimp"
    assert result.assessment.ready is True
    assert len(result.daily_loads) == 2
    assert result.daily_loads[0].load == 0.0
    assert result.daily_loads[1].load is not None
    assert len(result.training_points) == 2
    assert result.training_points[-1].daily_load == result.daily_loads[-1].load


async def test_fetch_trimp_training_history_rejects_invalid_sex() -> None:
    history = GarminHistoryClient(_make_client())

    with pytest.raises(ValueError, match="sex must be male or female"):
        await history.fetch_trimp_training_history(
            date(2026, 9, 1),
            date(2026, 9, 2),
            user_max_hr=175,
            sex="other",  # type: ignore[arg-type]
        )
