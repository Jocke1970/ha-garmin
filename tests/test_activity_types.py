"""Tests for the dynamic Garmin activity type registry."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

from ha_garmin import GarminAuth, GarminClient
from ha_garmin.activity_types import _BaseGarminClient


def _make_client() -> GarminClient:
    auth = GarminAuth()
    auth.di_token = "fake_di_token"
    return GarminClient(auth)


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


async def test_get_activities_learns_type_metadata_without_extra_request() -> None:
    """Normal activity loading teaches the registry at zero extra API cost."""
    client = _make_client()
    activities = [
        {
            "activityId": 123,
            "activityType": {
                "typeId": 152,
                "typeKey": "virtual_ride",
                "parentTypeId": 2,
            },
        }
    ]

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


async def test_fetch_gear_data_resolves_all_default_activity_ids() -> None:
    """Gear defaults use Garmin's live hierarchy instead of type_XX fallbacks."""
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
    assert rower["defaultForActivity"] == ["indoor_rowing"]
    assert rower["defaultForActivityDetails"] == [
        {"typeId": 32, "typeKey": "indoor_rowing", "parentTypeId": 29}
    ]
    assert ignored["defaultForActivity"] == []
