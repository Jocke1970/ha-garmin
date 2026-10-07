"""Tests for activity-specific Garmin Gear enrichment."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from ha_garmin.client import GarminClient
from ha_garmin.const import GEAR_URL
from ha_garmin.exceptions import GarminAPIError


def _raw_activity() -> dict:
    return {
        "activityId": 24288164173,
        "activityName": "Test ride",
        "activityType": {"typeKey": "cycling"},
        "duration": 1586.0,
        "hasPolyline": False,
    }


async def test_get_activity_gear_normalizes_and_caches() -> None:
    """Per-activity Gear is normalized and normal polling reuses the cache."""
    client = GarminClient(MagicMock())
    client._request = AsyncMock(
        return_value=[
            {
                "uuid": "17a4e95158cf47a3af83655d90ff9d8c",
                "displayName": "Stages Power L Shimano Ultegra R8100",
                "gearTypeName": "Bike Component",
                "gearMakeName": "Stages",
                "gearModelName": "Stages Power L Shimano Ultegra R8100",
            },
            {
                "uuid": "540c8eeacead401bb7101e870319387e",
                "displayName": "Unknown",
                "customMakeModel": "Bontrager Ion 200 RT Flare",
                "gearTypeName": "Bike Component",
                "gearMakeName": "Bontrager",
                "gearModelName": "Ion 200 RT Flare",
            },
        ]
    )

    first = await client.get_activity_gear(24288164173)
    second = await client.get_activity_gear(24288164173)

    client._request.assert_awaited_once_with(
        "GET",
        GEAR_URL,
        params={"activityId": "24288164173"},
    )
    assert first == second
    assert first[0]["gear_uuid"] == "17a4e95158cf47a3af83655d90ff9d8c"
    assert first[1]["name"] == "Bontrager Ion 200 RT Flare"


async def test_get_activity_gear_rejects_invalid_activity_id() -> None:
    """Activity IDs must be positive integers."""
    client = GarminClient(MagicMock())

    with pytest.raises(ValueError, match="activity_id"):
        await client.get_activity_gear(0)


async def test_fetch_activity_data_exposes_linked_gear() -> None:
    """Newest activity and recent list expose the same linked Gear."""
    client = GarminClient(MagicMock())
    activity = _raw_activity()
    linked = [
        {
            "gear_uuid": "540c8eeacead401bb7101e870319387e",
            "name": "Bontrager Ion 200 RT Flare",
            "gear_type": "Bike Component",
            "brand": "Bontrager",
            "model": "Ion 200 RT Flare",
            "custom_make_model": "Bontrager Ion 200 RT Flare",
        }
    ]

    client.get_activities = AsyncMock(return_value=[activity])
    client._get_ebike_fields = AsyncMock(return_value={})
    client.get_activity_hr_in_timezones = AsyncMock(return_value={})
    client.get_activity_gear = AsyncMock(return_value=linked)
    client.get_workouts = AsyncMock(return_value=[])

    data = await client.fetch_activity_data()

    assert data["lastActivity"]["linked_gear"] == linked
    assert data["lastActivity"]["linked_gear_count"] == 1
    assert data["lastActivities"][0]["linked_gear"] == linked
    assert data["lastActivities"][0]["linked_gear_count"] == 1


async def test_optional_activity_gear_failure_keeps_activity_data() -> None:
    """A failed optional Gear lookup must not blank the normal activity payload."""
    client = GarminClient(MagicMock())
    activity = _raw_activity()

    client.get_activities = AsyncMock(return_value=[activity])
    client._get_ebike_fields = AsyncMock(return_value={})
    client.get_activity_hr_in_timezones = AsyncMock(return_value={})
    client.get_activity_gear = AsyncMock(side_effect=GarminAPIError("temporary"))
    client.get_workouts = AsyncMock(return_value=[])

    data = await client.fetch_activity_data()

    assert data["lastActivity"]["activityId"] == 24288164173
    assert "linked_gear" not in data["lastActivity"]
