"""Tests for strict Garmin history access."""

from datetime import date
from unittest.mock import AsyncMock, patch

import pytest

from ha_garmin import GarminAuth, GarminClient, GarminHistoryClient
from ha_garmin.const import ACTIVITIES_URL
from ha_garmin.exceptions import GarminAPIError


def _make_client() -> GarminClient:
    auth = GarminAuth()
    auth.di_token = "fake_di_token"
    return GarminClient(auth)


class TestGarminHistoryClient:
    """Tests for history-specific Garmin access."""

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
            await history.get_activities_by_date(
                date(2026, 9, 2), date(2026, 9, 1)
            )

    async def test_get_activities_by_date_rejects_unexpected_response(self):
        client = _make_client()
        history = GarminHistoryClient(client)

        with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"unexpected": "object"}
            with pytest.raises(GarminAPIError, match="expected a list"):
                await history.get_activities_by_date(
                    date(2026, 8, 1), date(2026, 9, 1)
                )

    async def test_get_activities_by_date_pagination_is_bounded(self):
        client = _make_client()
        history = GarminHistoryClient(client)
        history._PAGE_SIZE = 1
        history._MAX_PAGES = 2

        with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = [{"activityId": 1}]
            with pytest.raises(GarminAPIError, match="pagination exceeded safety limit"):
                await history.get_activities_by_date(
                    date(2026, 8, 1), date(2026, 9, 1)
                )

        assert mock_req.await_count == 2
