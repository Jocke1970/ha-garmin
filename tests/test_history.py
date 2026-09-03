"""Tests for strict Garmin history access."""

from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from ha_garmin import GarminAuth, GarminClient, GarminHistoryClient
from ha_garmin.const import (
    ACTIVITIES_URL,
    RESTING_HEART_RATE_METRIC_ID,
    USER_STATS_DAILY_URL,
)
from ha_garmin.exceptions import GarminAPIError


def _make_client() -> GarminClient:
    auth = GarminAuth()
    auth.di_token = "fake_di_token"
    return GarminClient(auth)


class TestGarminHistoryClient:
    """Tests for history-specific Garmin access."""

    async def test_get_daily_summary_is_strict_for_requested_date(self):
        client = _make_client()
        history = GarminHistoryClient(client)
        target = date(2026, 9, 1)

        with patch.object(
            client, "_get_user_summary_raw", new_callable=AsyncMock
        ) as mock_summary:
            mock_summary.return_value = {
                "calendarDate": "2026-09-01",
                "restingHeartRate": 58,
            }
            summary = await history.get_daily_summary(target)

        mock_summary.assert_awaited_once_with(target)
        assert summary["calendarDate"] == "2026-09-01"
        assert summary["restingHeartRate"] == 58

    async def test_get_resting_heart_rate_range_uses_one_strict_range_request(self):
        client = _make_client()
        history = GarminHistoryClient(client)
        payload = {
            "allMetrics": {
                "metricsMap": {
                    "WELLNESS_RESTING_HEART_RATE": [
                        {"calendarDate": "2026-08-01", "value": 58},
                        {"calendarDate": "2026-08-02", "value": 57.5},
                        {"calendarDate": "2026-08-03", "value": 0},
                        {"calendarDate": "not-a-date", "value": 60},
                        {"calendarDate": "2026-07-31", "value": 61},
                    ]
                }
            }
        }

        with (
            patch.object(
                client, "get_user_profile", new_callable=AsyncMock
            ) as mock_profile,
            patch.object(client, "_request", new_callable=AsyncMock) as mock_req,
        ):
            mock_profile.return_value = SimpleNamespace(display_name="test/user")
            mock_req.return_value = payload
            result = await history.get_resting_heart_rate_range(
                date(2026, 8, 1), date(2026, 8, 3)
            )

        assert result == {
            date(2026, 8, 1): 58.0,
            date(2026, 8, 2): 57.5,
        }
        assert mock_req.await_count == 1
        assert mock_req.await_args.args[:2] == (
            "GET",
            f"{USER_STATS_DAILY_URL}/test%2Fuser",
        )
        assert mock_req.await_args.kwargs["params"] == {
            "fromDate": "2026-08-01",
            "untilDate": "2026-08-03",
            "metricId": RESTING_HEART_RATE_METRIC_ID,
        }

    async def test_get_resting_heart_rate_range_handles_missing_metric(self):
        client = _make_client()
        history = GarminHistoryClient(client)

        with (
            patch.object(
                client, "get_user_profile", new_callable=AsyncMock
            ) as mock_profile,
            patch.object(client, "_request", new_callable=AsyncMock) as mock_req,
        ):
            mock_profile.return_value = SimpleNamespace(display_name="test")
            mock_req.return_value = {"allMetrics": {"metricsMap": {}}}
            result = await history.get_resting_heart_rate_range(date(2026, 8, 1))

        assert result == {}

    async def test_get_resting_heart_rate_range_rejects_reverse_range(self):
        client = _make_client()
        history = GarminHistoryClient(client)

        with pytest.raises(ValueError, match="start_date cannot be after end_date"):
            await history.get_resting_heart_rate_range(
                date(2026, 9, 2), date(2026, 9, 1)
            )

    async def test_get_activities_by_date_single_day(self):
        client = _make_client()
        history = GarminHistoryClient(client)
        payload = [{"activityId": 1, "activityName": "Walk"}]

        with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.side_effect = [payload, []]
            activities = await history.get_activities_by_date(date(2026, 9, 1))

        assert activities == payload
        assert mock_req.await_count == 2
        first_params = mock_req.await_args_list[0].kwargs["params"]
        assert first_params == {
            "start": 0,
            "limit": 20,
            "startDate": "2026-09-01",
            "endDate": "2026-09-01",
        }
        assert mock_req.await_args_list[0].args[:2] == ("GET", ACTIVITIES_URL)

    async def test_get_activities_by_date_paginates(self):
        client = _make_client()
        history = GarminHistoryClient(client)
        history._PAGE_SIZE = 2

        page_1 = [{"activityId": 3}, {"activityId": 2}]
        page_2 = [{"activityId": 1}]

        with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.side_effect = [page_1, page_2, []]
            activities = await history.get_activities_by_date(
                date(2026, 8, 1), date(2026, 9, 1)
            )

        assert [activity["activityId"] for activity in activities] == [3, 2, 1]
        starts = [call.kwargs["params"]["start"] for call in mock_req.await_args_list]
        assert starts == [0, 2, 4]

    async def test_get_activities_by_date_passes_optional_filters(self):
        client = _make_client()
        history = GarminHistoryClient(client)

        with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = []
            await history.get_activities_by_date(
                date(2026, 8, 1),
                date(2026, 9, 1),
                activity_type="walking",
                sort_order="asc",
            )

        params = mock_req.await_args.kwargs["params"]
        assert params["activityType"] == "walking"
        assert params["sortOrder"] == "asc"

    async def test_get_activities_by_date_rejects_reversed_range(self):
        client = _make_client()
        history = GarminHistoryClient(client)

        with pytest.raises(ValueError, match="start_date cannot be after end_date"):
            await history.get_activities_by_date(date(2026, 9, 2), date(2026, 9, 1))

    async def test_get_activities_by_date_rejects_unexpected_response(self):
        client = _make_client()
        history = GarminHistoryClient(client)

        with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"unexpected": "object"}
            with pytest.raises(GarminAPIError, match="expected a list"):
                await history.get_activities_by_date(date(2026, 8, 1), date(2026, 9, 1))

    async def test_get_activities_by_date_pagination_is_bounded(self):
        client = _make_client()
        history = GarminHistoryClient(client)
        history._PAGE_SIZE = 1
        history._MAX_PAGES = 2

        with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = [{"activityId": 1}]
            with pytest.raises(
                GarminAPIError, match="pagination exceeded safety limit"
            ):
                await history.get_activities_by_date(date(2026, 8, 1), date(2026, 9, 1))

        assert mock_req.await_count == 2

    async def test_fetch_activity_metrics_normalizes_and_deduplicates(self):
        client = _make_client()
        history = GarminHistoryClient(client)
        raw = [
            {
                "activityId": 2,
                "startTimeGMT": "2026-09-02T08:00:00",
                "startTimeLocal": "2026-09-02T10:00:00",
                "activityType": {"typeKey": "walking"},
                "duration": 1800,
                "activityTrainingLoad": 4,
            },
            {
                "activityId": 1,
                "startTimeGMT": "2026-09-01T08:00:00",
                "startTimeLocal": "2026-09-01T10:00:00",
                "activityType": {"typeKey": "walking"},
                "duration": 1200,
            },
            {
                "activityId": 2,
                "startTimeGMT": "2026-09-02T08:00:00",
                "startTimeLocal": "2026-09-02T10:00:00",
                "duration": 9999,
            },
        ]

        with patch.object(
            history, "get_activities_by_date", new_callable=AsyncMock
        ) as mock_activities:
            mock_activities.return_value = raw
            metrics = await history.fetch_activity_metrics(
                date(2026, 9, 1), date(2026, 9, 2)
            )

        assert [item.activity_id for item in metrics] == [1, 2]
        assert metrics[0].duration_minutes == 20.0
        assert metrics[1].duration_minutes == 30.0
        assert metrics[1].garmin_training_load == 4.0
