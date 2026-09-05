"""Tests for Garmin Gear M1 source models."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from ha_garmin.gear import GearItem, GearSourceRecord, build_gear_source_records


def test_gear_item_supports_multiple_sources_and_nullable_activity_count() -> None:
    sources = [
        GearSourceRecord(source="garmin_gear", source_id="garmin_gear:abc"),
        GearSourceRecord(source="garmin_device", source_id="garmin_device:123"),
    ]
    item = GearItem(
        id="garmin_gear:abc",
        name="Example",
        categories=["cycling", "wearables"],
        primary_category="cycling",
        sources=sources,
        activity_count=None,
    )

    assert len(item.sources) == 2
    assert item.activity_count is None
    assert "device_id" not in item.__class__.model_fields


def test_categories_require_lowercase_snake_case() -> None:
    with pytest.raises(ValidationError):
        GearItem(id="x", name="Bad", categories=["Winter Sport"])

    with pytest.raises(ValidationError):
        GearItem(
            id="x",
            name="Bad primary",
            categories=["cycling"],
            primary_category="running",
        )


def test_source_identity_does_not_depend_on_display_name() -> None:
    first = {
        "uuid": "abc123",
        "brand": "Bontrager",
        "model": "Ion 200 RT Flare",
        "status": "ACTIVE",
        "numActivitiesLinked": 0,
    }
    renamed = dict(first, brand="Trek", model="CarBack Radar")

    first_record = build_gear_source_records({"gearStats": [first]})[0]
    second_record = build_gear_source_records({"gearStats": [renamed]})[0]

    assert (
        first_record["source_id"] == second_record["source_id"] == "garmin_gear:abc123"
    )


def test_device_last_used_requires_exact_device_id_and_count_stays_unknown() -> None:
    activity = {
        "activityId": 1,
        "deviceId": 123,
        "startTimeGMT": "2026-09-05T10:00:00+00:00",
    }
    data = {
        "devices": [{"deviceId": 123, "productDisplayName": "Edge 1040"}],
        "lastUsedDevice": {
            "deviceId": 999,
            "lastSyncTime": "2026-09-05T11:00:00+00:00",
        },
    }

    record = build_gear_source_records(data, [activity])[0]

    assert record["last_used_at"] == datetime(2026, 9, 5, 10, 0, tzinfo=UTC)
    assert record["last_seen_at"] is None
    assert record["activity_count"] is None


def test_sensor_serial_is_hashed_and_last_connected_is_last_seen_only() -> None:
    sensor = {
        "serialNumber": "SECRET-SERIAL",
        "sensorType": "HEART_RATE",
        "batteryLevel": 75,
        "lastConnected": "2026-09-05T12:00:00+00:00",
    }

    record = build_gear_source_records({"sensors": [sensor]})[0]

    assert "SECRET-SERIAL" not in str(record)
    assert record["last_used_at"] is None
    assert record["last_seen_at"] == datetime(2026, 9, 5, 12, 0, tzinfo=UTC)
    assert record["activity_count"] is None
