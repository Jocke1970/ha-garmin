"""Tests for strict Garmin recovery history access."""

from datetime import date
from unittest.mock import AsyncMock, MagicMock, call

import pytest

from ha_garmin import GarminHistoryClient
from ha_garmin.exceptions import GarminAPIError


def _history_client() -> tuple[GarminHistoryClient, MagicMock]:
    client = MagicMock()
    client._get_user_summary_raw = AsyncMock(return_value={})
    client._get_sleep_data_raw = AsyncMock(return_value={})
    client._get_hrv_data_raw = AsyncMock(return_value={})
    client._request = AsyncMock(return_value=[])
    return GarminHistoryClient(client), client


async def test_fetch_daily_recovery_metrics_uses_only_requested_date() -> None:
    """Strict recovery input must not retry yesterday as a presentation fallback."""
    history, client = _history_client()
    target = date(2026, 9, 5)

    client._get_user_summary_raw.return_value = {
        "calendarDate": "2026-09-05",
        "restingHeartRate": 55,
    }
    client._get_sleep_data_raw.return_value = {
        "dailySleepDTO": {
            "calendarDate": "2026-09-05",
            "sleepTimeSeconds": 25200,
        }
    }
    client._get_hrv_data_raw.return_value = {
        "hrvSummary": {
            "calendarDate": "2026-09-05",
            "lastNightAvg": 49,
        }
    }
    client._request.return_value = [
        {
            "calendarDate": "2026-09-05",
            "inputContext": "DAILY",
            "score": 67,
            "recoveryTime": 240,
        },
        {
            "calendarDate": "2026-09-05",
            "inputContext": "AFTER_WAKEUP_RESET",
            "score": 63,
        },
    ]

    result = await history.fetch_daily_recovery_metrics(target)

    assert result.date == target
    assert result.resting_hr == 55
    assert result.sleep_minutes == 420.0
    assert result.hrv_last_night_avg == 49
    assert result.training_readiness == 67
    assert result.morning_training_readiness == 63
    assert result.recovery_minutes == 240

    client._get_user_summary_raw.assert_awaited_once_with(target)
    client._get_sleep_data_raw.assert_awaited_once_with(target)
    client._get_hrv_data_raw.assert_awaited_once_with(target)
    client._request.assert_awaited_once()
    method, url = client._request.call_args.args
    assert method == "GET"
    assert url.endswith("/2026-09-05")


async def test_training_readiness_contexts_are_not_substituted() -> None:
    """Morning-only readiness must not masquerade as regular readiness."""
    history, client = _history_client()
    target = date(2026, 9, 5)
    client._request.return_value = [
        {
            "calendarDate": "2026-09-05",
            "inputContext": "AFTER_WAKEUP_RESET",
            "score": 80,
        }
    ]

    regular, morning = await history.get_training_readiness_entries(target)

    assert regular == {}
    assert morning["score"] == 80


async def test_fetch_recovery_history_is_inclusive_and_sequential() -> None:
    """Build one exact-date record per day in the requested inclusive window."""
    history, client = _history_client()
    start = date(2026, 9, 4)
    end = date(2026, 9, 5)

    client._get_user_summary_raw.side_effect = lambda day: {
        "calendarDate": day.isoformat(),
        "restingHeartRate": 50 + day.day,
    }
    client._get_sleep_data_raw.side_effect = lambda day: {
        "dailySleepDTO": {"calendarDate": day.isoformat()}
    }
    client._get_hrv_data_raw.side_effect = lambda day: {
        "hrvSummary": {"calendarDate": day.isoformat()}
    }

    async def readiness_request(method: str, url: str):
        assert method == "GET"
        day = url.rsplit("/", 1)[-1]
        return [{"calendarDate": day, "inputContext": "DAILY", "score": 60}]

    client._request.side_effect = readiness_request

    result = await history.fetch_recovery_history(start, end)

    assert [item.date for item in result] == [start, end]
    assert [item.resting_hr for item in result] == [54, 55]
    assert client._get_user_summary_raw.await_args_list == [call(start), call(end)]
    assert client._get_sleep_data_raw.await_args_list == [call(start), call(end)]
    assert client._get_hrv_data_raw.await_args_list == [call(start), call(end)]
    assert client._request.await_count == 2


async def test_fetch_recovery_history_rejects_reverse_range() -> None:
    """A reversed history window is invalid."""
    history, _ = _history_client()

    with pytest.raises(ValueError, match="start_date cannot be after end_date"):
        await history.fetch_recovery_history(date(2026, 9, 5), date(2026, 9, 4))


async def test_training_readiness_rejects_unexpected_payload_shape() -> None:
    """Unexpected Garmin readiness shapes must fail loudly in strict history."""
    history, client = _history_client()
    client._request.return_value = "unexpected"

    with pytest.raises(GarminAPIError, match="training-readiness history response"):
        await history.get_training_readiness_entries(date(2026, 9, 5))
