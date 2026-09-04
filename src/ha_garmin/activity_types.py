"""Dynamic Garmin activity type registry and gear-default resolution.

The registry learns activity types from the normal activity list response at
no additional API cost. Garmin's canonical activity type hierarchy is also
loaded lazily as a cached bootstrap when gear data is fetched, so old/default
activity types are resolved even when they have not appeared in recent
activities.

Keeping Garmin's numeric IDs out of presentation code means newly introduced
activity types can be understood automatically without maintaining a static
``type_XX`` mapping in Home Assistant.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, date, datetime, timedelta
from typing import Any, TypedDict

from .auth import GarminAuth
from .client import GarminClient as _BaseGarminClient
from .const import GARMIN_CONNECT_API
from .exceptions import GarminConnectError

_LOGGER = logging.getLogger(__name__)

_ACTIVITY_TYPES_URL = f"{GARMIN_CONNECT_API}/activity-service/activity/activityTypes"
_ACTIVITY_TYPES_CACHE_TTL = timedelta(hours=24)


class ActivityType(TypedDict):
    """Stable activity type fields exposed by Garmin."""

    typeId: int
    typeKey: str
    parentTypeId: int | None


def _copy_activity_type(item: ActivityType) -> ActivityType:
    """Return a defensive copy of an activity type record."""
    return {
        "typeId": item["typeId"],
        "typeKey": item["typeKey"],
        "parentTypeId": item["parentTypeId"],
    }


def _normalise_activity_type(raw: dict[str, Any]) -> ActivityType | None:
    """Return the stable fields for one Garmin activity type."""
    raw_type_id = raw.get("typeId")
    type_key = raw.get("typeKey")
    if raw_type_id is None or not type_key:
        return None

    try:
        type_id = int(raw_type_id)
    except (TypeError, ValueError):
        return None

    raw_parent_type_id = raw.get("parentTypeId")
    parent_type_id: int | None = None
    if raw_parent_type_id is not None:
        try:
            parent_type_id = int(raw_parent_type_id)
        except (TypeError, ValueError):
            parent_type_id = None

    return {
        "typeId": type_id,
        "typeKey": str(type_key),
        "parentTypeId": parent_type_id,
    }


class GarminClient(_BaseGarminClient):
    """Garmin client with a cached, live activity type registry."""

    def __init__(self, auth: GarminAuth, is_cn: bool = False) -> None:
        """Initialize the client and activity type registry cache."""
        super().__init__(auth, is_cn=is_cn)
        self._activity_type_registry: dict[int, ActivityType] = {}
        self._activity_type_registry_refreshed: datetime | None = None
        self._activity_type_registry_lock = asyncio.Lock()

    def activity_type_registry(self) -> dict[int, ActivityType]:
        """Return a defensive copy of the currently cached registry."""
        return {
            type_id: _copy_activity_type(activity_type)
            for type_id, activity_type in self._activity_type_registry.items()
        }

    def _activity_types_as_list(self) -> list[ActivityType]:
        """Return the cached registry sorted by Garmin type ID."""
        return [
            _copy_activity_type(item)
            for _, item in sorted(self._activity_type_registry.items())
        ]

    def _learn_activity_types(self, activities: list[dict[str, Any]]) -> None:
        """Merge type metadata already present in normal activity responses."""
        for activity in activities:
            raw_type = activity.get("activityType")
            if not isinstance(raw_type, dict):
                continue
            item = _normalise_activity_type(raw_type)
            if item is not None:
                self._activity_type_registry[item["typeId"]] = item

    async def get_activities(
        self, start: int = 0, limit: int = 10
    ) -> list[dict[str, Any]]:
        """Fetch activities and learn their Garmin activity type metadata."""
        activities = await super().get_activities(start, limit)
        self._learn_activity_types(activities)
        return activities

    async def get_activity_types(
        self, *, force_refresh: bool = False
    ) -> list[ActivityType]:
        """Return Garmin's current activity type hierarchy.

        The hierarchy changes very rarely, so a 24-hour cache keeps this
        effectively free during normal coordinator polling while still making
        new Garmin activity types appear automatically.
        """
        now = datetime.now(UTC)
        if (
            not force_refresh
            and self._activity_type_registry_refreshed is not None
            and now - self._activity_type_registry_refreshed < _ACTIVITY_TYPES_CACHE_TTL
        ):
            return self._activity_types_as_list()

        async with self._activity_type_registry_lock:
            now = datetime.now(UTC)
            if (
                not force_refresh
                and self._activity_type_registry_refreshed is not None
                and now - self._activity_type_registry_refreshed
                < _ACTIVITY_TYPES_CACHE_TTL
            ):
                return self._activity_types_as_list()

            data = await self._request("GET", _ACTIVITY_TYPES_URL)
            raw_types: Any
            if isinstance(data, dict):
                raw_types = data.get("activityTypes") or data.get("types") or []
            else:
                raw_types = data

            registry: dict[int, ActivityType] = {}
            if isinstance(raw_types, list):
                for raw in raw_types:
                    if not isinstance(raw, dict):
                        continue
                    item = _normalise_activity_type(raw)
                    if item is not None:
                        registry[item["typeId"]] = item

            # A transient empty response must not wipe types learned from
            # normal activity data or a previous successful hierarchy fetch.
            if registry:
                self._activity_type_registry.update(registry)
                self._activity_type_registry_refreshed = now

            return self._activity_types_as_list()

    async def _get_activity_types_best_effort(self) -> list[ActivityType]:
        """Refresh the auxiliary registry without breaking primary data fetches."""
        try:
            return await self.get_activity_types()
        except GarminConnectError as err:
            _LOGGER.debug("Activity type registry refresh failed: %s", err)
            return self._activity_types_as_list()

    def _resolve_activity_type(self, type_id: int) -> ActivityType:
        """Resolve one numeric Garmin activity type ID."""
        item = self._activity_type_registry.get(type_id)
        if item is not None:
            return _copy_activity_type(item)
        return {
            "typeId": type_id,
            "typeKey": f"type_{type_id}",
            "parentTypeId": None,
        }

    async def fetch_activity_data(
        self, target_date: date | None = None
    ) -> dict[str, Any]:
        """Fetch activity data and expose types learned during that fetch."""
        data = await super().fetch_activity_data(target_date)
        data["activityTypes"] = self._activity_types_as_list()
        return data

    async def fetch_gear_data(self, timezone: str | None = None) -> dict[str, Any]:
        """Fetch gear data and resolve default activity IDs via the registry."""
        activity_types = await self._get_activity_types_best_effort()
        data = await super().fetch_gear_data(timezone=timezone)

        defaults = data.get("gearDefaults")
        defaults_by_gear: dict[str, list[ActivityType]] = {}
        if isinstance(defaults, list):
            for default in defaults:
                if not isinstance(default, dict) or not default.get("defaultGear"):
                    continue
                gear_uuid = default.get("uuid")
                raw_type_id = default.get("activityTypePk")
                if not gear_uuid or raw_type_id is None:
                    continue
                try:
                    type_id = int(raw_type_id)
                except (TypeError, ValueError):
                    continue
                defaults_by_gear.setdefault(str(gear_uuid), []).append(
                    self._resolve_activity_type(type_id)
                )

        gear_stats = data.get("gearStats") or []
        if isinstance(gear_stats, list):
            for gear_stat in gear_stats:
                if not isinstance(gear_stat, dict):
                    continue
                gear_uuid = gear_stat.get("uuid") or gear_stat.get("gearUuid")
                details = defaults_by_gear.get(str(gear_uuid), []) if gear_uuid else []
                gear_stat["defaultForActivity"] = [
                    detail["typeKey"] for detail in details
                ]
                gear_stat["defaultForActivityDetails"] = [
                    _copy_activity_type(detail) for detail in details
                ]

        data["activityTypes"] = activity_types
        return data
