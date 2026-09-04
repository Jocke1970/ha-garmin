"""Tests for dynamic activity types and latest gear activity metadata."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

from ha_garmin import GarminAuth, GarminClient
from ha_garmin.activity_types import _BaseGarminClient


def _make_client() -> GarminClient:
    auth = GarminAuth()
    auth.di_token = "fake_di_token"
    return GarminClient(auth)


def _ride() -> dict[str, object]:
    return {
        "activityId": 123,
        "activityName": "Morning ride",
        "startTimeGMT": "2026-09-04T06:30:00.000",
        "distance": 42318.0,
        "duration": 6432.0,
        "activityType": {
            "typeId": 152,
            "typeKey": "virtual_ride",
            "parentTypeId": 2,
        },
    }


def _walk() -> dict[str, object]:
    return {
        "activityId": 122,
        "activityName": "Stockholm Gång",
        "startTimeGMT": "2026-08-12T07:59:00.000",
        "distance": 2290.0,
        "duration": 1493.0,
        "activityType": {
            "typeId": 9,
            "typeKey": "walking",
            "parentTypeId": 1,
        },
    }


async def test_get_activity_types_normalises_and_caches() -> None:
    """The Garmin hierarchy is normalised and not fetched every poll."""
    client = _make_client()
    payload = [
        {
            "typeId": 25,
            "typeKey": "indoor_cycling",
            "parentTypeId": 2,
            "isHidden": False,
        },
        {
            "typeId": "32",
            "typeKey": "indoor_rowing",
            "parentTypeId": "29",
        },
        {"typeId": None, "typeKey": "broken"},
    ]

    with patch.object(client, "_request", new_callable=AsyncMock) as request:
        request.return_value = payload
        first = await client.get_activity_types()
        second = await client.get_activity_types()

    assert first == [
        {"typeId": 25, "typeKey": "indoor_cycling", "parentTypeId": 2},
        {"typeId": 32, "typeKey": "indoor_rowing", "parentTypeId": 29},
    ]
    assert second == first
    request.assert_awaited_once()


async def test_get_activities_learns_type_without_auxiliary_request() -> None:
    """Normal activity loading teaches types while retaining one API request."""
    client = _make_client()
    activities = [_ride()]

    with patch.object(
        _BaseGarminClient, "get_activities", new_callable=AsyncMock
    ) as base_get:
        base_get.return_value = activities
        result = await client.get_activities(0, 10)

    assert result == activities
    base_get.assert_awaited_once_with(0, 10)
    assert client.activity_type_registry() == {
        152: {"typeId": 152, "typeKey": "virtual_ride", "parentTypeId": 2}
    }
    assert client._recent_activities_raw == activities
    assert client._last_activity_by_gear == {}


async def test_activity_fetch_maps_latest_gear_once() -> None:
    """The Activity fetch flow performs one cached gear lookup per activity."""
    client = _make_client()
    activities = [_ride()]
    client._recent_activities_raw = activities

    with (
        patch.object(
            _BaseGarminClient, "fetch_activity_data", new_callable=AsyncMock
        ) as base_fetch,
        patch.object(client, "get_activity_gear", new_callable=AsyncMock) as gear_get,
    ):
        base_fetch.return_value = {"lastActivity": {}, "lastActivities": []}
        gear_get.return_value = [{"uuid": "gear-bike"}, {"uuid": "gear-shoes"}]
        await client.fetch_activity_data()
        await client.fetch_activity_data()

    assert base_fetch.await_count == 2
    gear_get.assert_awaited_once_with(123)
    expected = {
        "activity_id": 123,
        "name": "Morning ride",
        "type": "virtual_ride",
        "type_id": 152,
        "parent_type_id": 2,
        "start": "2026-09-04T06:30:00+00:00",
        "distance_m": 42318.0,
        "duration_s": 6432.0,
    }
    assert client._last_activity_by_gear["gear-bike"] == expected
    assert client._last_activity_by_gear["gear-shoes"] == expected


async def test_activity_fetch_scans_recent_window_for_each_gears_latest_use() -> None:
    """Older recent activities backfill gear without overriding newer matches."""
    client = _make_client()
    client._recent_activities_raw = [_ride(), _walk()]

    with (
        patch.object(
            _BaseGarminClient, "fetch_activity_data", new_callable=AsyncMock
        ) as base_fetch,
        patch.object(client, "get_activity_gear", new_callable=AsyncMock) as gear_get,
    ):
        base_fetch.return_value = {"lastActivity": {}, "lastActivities": []}
        gear_get.side_effect = [
            [{"uuid": "gear-rower"}],
            [{"uuid": "gear-nike"}],
        ]
        await client.fetch_activity_data()
        await client.fetch_activity_data()

    assert gear_get.await_count == 2
    assert client._last_activity_by_gear["gear-rower"]["activity_id"] == 123
    nike = client._last_activity_by_gear["gear-nike"]
    assert nike["activity_id"] == 122
    assert nike["name"] == "Stockholm Gång"
    assert nike["start"] == "2026-08-12T07:59:00+00:00"
    assert nike["distance_m"] == 2290.0


async def test_empty_activity_gear_is_retried_only_three_times() -> None:
    """A newly uploaded activity gets bounded retries while Garmin catches up."""
    client = _make_client()
    client._recent_activities_raw = [_ride()]

    with (
        patch.object(
            _BaseGarminClient, "fetch_activity_data", new_callable=AsyncMock
        ) as base_fetch,
        patch.object(client, "get_activity_gear", new_callable=AsyncMock) as gear_get,
    ):
        base_fetch.return_value = {"lastActivity": {}, "lastActivities": []}
        gear_get.return_value = []
        for _ in range(5):
            await client.fetch_activity_data()

    assert gear_get.await_count == 3
    assert client._last_activity_by_gear == {}


async def test_historical_empty_activity_is_not_retried() -> None:
    """Empty historical activity gear is stable after the first lookup."""
    client = _make_client()
    client._recent_activities_raw = [_ride(), _walk()]

    with (
        patch.object(
            _BaseGarminClient, "fetch_activity_data", new_callable=AsyncMock
        ) as base_fetch,
        patch.object(client, "get_activity_gear", new_callable=AsyncMock) as gear_get,
    ):
        base_fetch.return_value = {"lastActivity": {}, "lastActivities": []}
        gear_get.return_value = []
        await client.fetch_activity_data()
        await client.fetch_activity_data()
        await client.fetch_activity_data()

    # Newest activity retries on each poll; the older historical activity is
    # checked only once and then cached as a stable no-gear result.
    assert gear_get.await_count == 4


async def test_empty_refresh_keeps_previous_registry() -> None:
    """A transient empty Garmin response must not erase a good cache."""
    client = _make_client()
    client._activity_type_registry = {
        152: {
            "typeId": 152,
            "typeKey": "virtual_ride",
            "parentTypeId": 2,
        }
    }
    client._activity_type_registry_refreshed = datetime(2000, 1, 1, tzinfo=UTC)

    with patch.object(client, "_request", new_callable=AsyncMock) as request:
        request.return_value = []
        result = await client.get_activity_types(force_refresh=True)

    assert result == [{"typeId": 152, "typeKey": "virtual_ride", "parentTypeId": 2}]


async def test_fetch_activity_data_exposes_registry() -> None:
    """Activity coordinator data carries the registry for downstream consumers."""
    client = _make_client()
    client._activity_type_registry = {
        32: {
            "typeId": 32,
            "typeKey": "indoor_rowing",
            "parentTypeId": 29,
        }
    }
    client._activity_type_registry_refreshed = datetime.now(UTC)

    with patch.object(
        _BaseGarminClient,
        "fetch_activity_data",
        new_callable=AsyncMock,
    ) as base_fetch:
        base_fetch.return_value = {"lastActivity": {}, "lastActivities": []}
        result = await client.fetch_activity_data()

    assert result["activityTypes"] == [
        {"typeId": 32, "typeKey": "indoor_rowing", "parentTypeId": 29}
    ]


async def test_fetch_gear_data_resolves_defaults_and_last_activity() -> None:
    """Gear data gets resolved default types and cached last activity."""
    client = _make_client()
    client._activity_type_registry = {
        25: {
            "typeId": 25,
            "typeKey": "indoor_cycling",
            "parentTypeId": 2,
        },
        32: {
            "typeId": 32,
            "typeKey": "indoor_rowing",
            "parentTypeId": 29,
        },
        152: {
            "typeId": 152,
            "typeKey": "virtual_ride",
            "parentTypeId": 2,
        },
    }
    client._activity_type_registry_refreshed = datetime.now(UTC)
    client._last_activity_by_gear["trainer"] = {
        "activity_id": 123,
        "name": "Morning ride",
        "type": "virtual_ride",
    }

    base_data = {
        "gearDefaults": [
            {"uuid": "trainer", "activityTypePk": 25, "defaultGear": True},
            {"uuid": "trainer", "activityTypePk": 152, "defaultGear": True},
            {"uuid": "rower", "activityTypePk": 32, "defaultGear": True},
            {"uuid": "ignored", "activityTypePk": 1, "defaultGear": False},
        ],
        "gearStats": [
            {"gearUuid": "trainer", "defaultForActivity": ["type_25", "type_152"]},
            {"gearUuid": "rower", "defaultForActivity": ["type_32"]},
            {"gearUuid": "ignored", "defaultForActivity": []},
        ],
    }

    with patch.object(
        _BaseGarminClient,
        "fetch_gear_data",
        new_callable=AsyncMock,
    ) as base_fetch:
        base_fetch.return_value = base_data
        result = await client.fetch_gear_data()

    trainer = result["gearStats"][0]
    rower = result["gearStats"][1]
    ignored = result["gearStats"][2]

    assert trainer["defaultForActivity"] == ["indoor_cycling", "virtual_ride"]
    assert trainer["defaultForActivityDetails"] == [
        {"typeId": 25, "typeKey": "indoor_cycling", "parentTypeId": 2},
        {"typeId": 152, "typeKey": "virtual_ride", "parentTypeId": 2},
    ]
    assert trainer["lastActivity"] == {
        "activity_id": 123,
        "name": "Morning ride",
        "type": "virtual_ride",
    }
    assert rower["defaultForActivity"] == ["indoor_rowing"]
    assert rower["defaultForActivityDetails"] == [
        {"typeId": 32, "typeKey": "indoor_rowing", "parentTypeId": 29}
    ]
    assert "lastActivity" not in rower
    assert ignored["defaultForActivity"] == []
