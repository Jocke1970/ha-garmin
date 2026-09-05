"""Reusable Garmin Gear source records and canonical item model.

This module intentionally keeps Garmin source identities separate. A physical
item may later be linked to more than one source record, but records are never
merged by display name.
"""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from typing import Any

from pydantic import Field, field_validator, model_validator

from .models import GarminModel

_CATEGORY_RE = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")


def _clean_text(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text or text.lower() in {
        "other",
        "unknown",
        "unknown bike",
        "unknown shoes",
    }:
        return None
    return text


def _as_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _first_present(data: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in data and data[key] is not None:
            return data[key]
    return None


def _private_hash(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def _sensor_identity(sensor: dict[str, Any]) -> tuple[str, str]:
    serial = sensor.get("serialNumber")
    if serial not in (None, ""):
        return f"serial:{serial}", "strong"

    parts = [
        str(sensor.get(key) or "")
        for key in (
            "sensorType",
            "productId",
            "partNumber",
            "deviceName",
            "manufacturer",
        )
    ]
    return "|".join(parts), "weak"


def _status_active(value: Any) -> bool | None:
    status = str(value or "").strip().lower()
    if status in {"active", "enabled"}:
        return True
    if status in {"retired", "inactive", "disabled"}:
        return False
    return None


def _validate_category(category: str) -> str:
    if not _CATEGORY_RE.fullmatch(category):
        raise ValueError("Gear categories must use lowercase snake_case")
    return category


class GearSourceRecord(GarminModel):
    """One normalized record from one Garmin identity domain."""

    source: str
    source_id: str
    name: str | None = None
    manufacturer: str | None = None
    model: str | None = None
    garmin_ids: dict[str, str | int] = Field(default_factory=dict)
    active: bool | None = None
    last_used_at: datetime | None = None
    last_seen_at: datetime | None = None
    activity_count: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class GearItem(GarminModel):
    """Canonical Gear item prepared for one or more source records."""

    id: str
    name: str
    manufacturer: str | None = None
    model: str | None = None
    garmin_ids: dict[str, str | int] = Field(default_factory=dict)
    categories: list[str] = Field(default_factory=list)
    primary_category: str | None = None
    sources: list[GearSourceRecord] = Field(default_factory=list)
    active: bool | None = None
    last_used_at: datetime | None = None
    last_seen_at: datetime | None = None
    activity_count: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("categories")
    @classmethod
    def validate_categories(cls, categories: list[str]) -> list[str]:
        result: list[str] = []
        for raw in categories:
            category = _validate_category(raw)
            if category not in result:
                result.append(category)
        return result

    @field_validator("primary_category")
    @classmethod
    def validate_primary_category_format(cls, value: str | None) -> str | None:
        return _validate_category(value) if value is not None else None

    @model_validator(mode="after")
    def validate_primary_membership(self) -> GearItem:
        if (
            self.primary_category is not None
            and self.primary_category not in self.categories
        ):
            raise ValueError("primary_category must be present in categories")
        return self


def _gear_display(stat: dict[str, Any]) -> tuple[str, str | None, str | None]:
    brand = _clean_text(stat.get("brand") or stat.get("gearMakeName"))
    model = _clean_text(stat.get("model") or stat.get("gearModelName"))
    structured = " ".join(part for part in (brand, model) if part)
    fallback = (
        _clean_text(stat.get("customMakeModel"))
        or _clean_text(stat.get("gearName"))
        or _clean_text(stat.get("name"))
        or "Garmin Gear"
    )
    return structured or fallback, brand, model


def _gear_source(stat: dict[str, Any]) -> GearSourceRecord | None:
    gear_uuid = _first_present(stat, "uuid", "gearUuid")
    if not gear_uuid:
        return None

    name, brand, model = _gear_display(stat)
    garmin_ids: dict[str, str | int] = {"gear_uuid": str(gear_uuid)}
    if stat.get("v2Uuid"):
        garmin_ids["gear_v2_uuid"] = str(stat["v2Uuid"])
    if stat.get("gearPk") is not None:
        garmin_ids["gear_pk"] = int(stat["gearPk"])

    raw_last_activity = stat.get("lastActivity")
    last_activity: dict[str, Any] = (
        raw_last_activity if isinstance(raw_last_activity, dict) else {}
    )
    activity_count = _first_present(stat, "numActivitiesLinked", "totalActivities")
    if (
        isinstance(activity_count, bool)
        or not isinstance(activity_count, int | float)
        or (isinstance(activity_count, float) and not activity_count.is_integer())
    ):
        activity_count = None
    else:
        activity_count = int(activity_count)

    metadata = {
        "gear_type": _first_present(stat, "gearType", "gearTypeName"),
        "usage_type": stat.get("usageType"),
        "first_use_date": _first_present(stat, "firstUseDate", "dateBegin"),
        "days_used": stat.get("daysUsed"),
        "distance_used_m": _first_present(stat, "distanceUsedMeters", "totalDistance"),
        "duration_used_s": stat.get("durationUsedSeconds"),
        "max_distance_m": stat.get("maximumMeters"),
        "max_duration_s": stat.get("maxUsageDurationSeconds"),
        "associated_activity_types": stat.get("associatedActivityTypes"),
        "default_for_activity": stat.get("defaultForActivity"),
        "last_activity": last_activity or None,
    }
    metadata = {key: value for key, value in metadata.items() if value is not None}

    return GearSourceRecord(
        source="garmin_gear",
        source_id=f"garmin_gear:{gear_uuid}",
        name=name,
        manufacturer=brand,
        model=model,
        garmin_ids=garmin_ids,
        active=_status_active(_first_present(stat, "status", "gearStatusName")),
        last_used_at=_as_datetime(last_activity.get("start")),
        last_seen_at=None,
        activity_count=activity_count,
        metadata=metadata,
    )


def _device_activity_last_used(
    device_id: Any, recent_activities: list[dict[str, Any]]
) -> datetime | None:
    if device_id is None:
        return None
    matches: list[datetime] = []
    for activity in recent_activities:
        if activity.get("deviceId") != device_id:
            continue
        started = _as_datetime(_first_present(activity, "startTimeGMT", "startTime"))
        if started is not None:
            matches.append(started)
    return max(matches, default=None)


def _device_source(
    device: dict[str, Any],
    recent_activities: list[dict[str, Any]],
    last_used_device: dict[str, Any],
) -> GearSourceRecord | None:
    device_id = device.get("deviceId")
    unit_id = device.get("unitId")
    source_basis = device_id if device_id is not None else unit_id
    if source_basis is None:
        return None

    garmin_ids: dict[str, str | int] = {}
    for target, source in (
        ("device_id", "deviceId"),
        ("unit_id", "unitId"),
        ("application_key", "applicationKey"),
        ("product_sku", "productSku"),
        ("part_number", "partNumber"),
    ):
        value = device.get(source)
        if isinstance(value, str | int) and not isinstance(value, bool) and value != "":
            garmin_ids[target] = value
    serial_hash = _private_hash(device.get("serialNumber"))
    if serial_hash:
        garmin_ids["serial_hash"] = serial_hash

    last_seen_at = None
    if device_id is not None and last_used_device.get("deviceId") == device_id:
        last_seen_at = _as_datetime(
            _first_present(last_used_device, "lastSyncTime", "lastSyncTimeGMT")
        )

    metadata = {
        "device_type_pk": device.get("deviceTypePk"),
        "device_type_name": device.get("deviceTypeName"),
        "device_categories": device.get("deviceCategories"),
        "firmware": device.get("currentFirmwareVersion"),
        "primary": device.get("primary"),
        "primary_activity_tracker": device.get("primaryActivityTrackerIndicator"),
        "image_url": device.get("imageUrl"),
    }
    metadata = {key: value for key, value in metadata.items() if value is not None}

    name = (
        _clean_text(device.get("productDisplayName") or device.get("displayName"))
        or "Garmin device"
    )
    model = _clean_text(device.get("productDisplayName") or device.get("displayName"))

    return GearSourceRecord(
        source="garmin_device",
        source_id=f"garmin_device:{source_basis}",
        name=name,
        manufacturer="Garmin",
        model=model,
        garmin_ids=garmin_ids,
        active=_status_active(device.get("deviceStatus")),
        last_used_at=_device_activity_last_used(device_id, recent_activities),
        last_seen_at=last_seen_at,
        activity_count=None,
        metadata=metadata,
    )


def _sensor_source(sensor: dict[str, Any]) -> GearSourceRecord | None:
    identity_basis, identity_strength = _sensor_identity(sensor)
    if not identity_basis:
        return None
    identity_hash = hashlib.sha256(identity_basis.encode()).hexdigest()[:16]

    garmin_ids: dict[str, str | int] = {"sensor_identity_hash": identity_hash}
    for target, source in (
        ("product_id", "productId"),
        ("part_number", "partNumber"),
    ):
        value = sensor.get(source)
        if isinstance(value, str | int) and not isinstance(value, bool) and value != "":
            garmin_ids[target] = value

    serial_hash = _private_hash(sensor.get("serialNumber"))
    if serial_hash:
        garmin_ids["serial_hash"] = serial_hash

    sensor_type = str(sensor.get("sensorType") or "unknown").lower()
    name = (
        _clean_text(sensor.get("deviceName")) or sensor_type.replace("_", " ").title()
    )
    metadata = {
        "sensor_type": sensor.get("sensorType"),
        "battery_level": sensor.get("batteryLevel"),
        "battery_status": sensor.get("batteryStatus"),
        "last_low_battery_notification": sensor.get("lastLowBatteryNotification"),
        "rechargeable_sensor_capable": sensor.get("rechargeableSensorCapable"),
        "software_version": sensor.get("softwareVersion"),
        "image_url": sensor.get("imageUrl"),
        "identity_strength": identity_strength,
    }
    metadata = {key: value for key, value in metadata.items() if value is not None}

    return GearSourceRecord(
        source="garmin_sensor",
        source_id=f"garmin_sensor:{identity_hash}",
        name=name,
        manufacturer=_clean_text(sensor.get("manufacturer")),
        model=_clean_text(sensor.get("partNumber")),
        garmin_ids=garmin_ids,
        active=None,
        last_used_at=None,
        last_seen_at=_as_datetime(sensor.get("lastConnected")),
        activity_count=None,
        metadata=metadata,
    )


def build_gear_source_records(
    data: dict[str, Any], recent_activities: list[dict[str, Any]] | None = None
) -> list[dict[str, Any]]:
    """Build normalized source records without cross-source name matching."""
    recent = recent_activities or []
    last_used_device = data.get("lastUsedDevice")
    if not isinstance(last_used_device, dict):
        last_used_device = {}

    records: list[GearSourceRecord] = []
    for stat in data.get("gearStats") or []:
        if isinstance(stat, dict) and (record := _gear_source(stat)) is not None:
            records.append(record)
    for device in data.get("devices") or []:
        if (
            isinstance(device, dict)
            and (record := _device_source(device, recent, last_used_device)) is not None
        ):
            records.append(record)
    for sensor in data.get("sensors") or []:
        if isinstance(sensor, dict) and (record := _sensor_source(sensor)) is not None:
            records.append(record)

    return [record.model_dump(mode="python") for record in records]
