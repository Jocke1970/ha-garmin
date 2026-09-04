"""Dynamic Garmin activity type registry and gear-default resolution.

Garmin exposes the canonical activity type hierarchy at
``/activity-service/activity/activityTypes``.  The public ``GarminClient``
subclass in this module loads that hierarchy lazily, caches it, and reuses it
when activity and gear data are fetched.

Keeping Garmin's numeric IDs out of presentation code means newly introduced
activity types can be understood automatically without maintaining a static
``type_XX`` mapping in Home Assistant.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

from .auth import GarminAuth
from .client import GarminClient as _BaseGarminClient
from .const import GARMIN_CONNECT_API

_ACTIVITY_TYPES_URL = f"{GARMIN_CONNECT_API}/activity-service/activity/activityTypes"
_ACTIVITY_TYPES_CACHE_TTL = timedelta(hours=24)


def _normalise_activity_type(raw: dict[str, Any]) -> dict[str, Any] | None:
    """Return the stable fields for one Garmin activity type."""
    type_id = raw.get("typeId")
    type_key = raw.get("typeKey")
    if type_id is None or not type_key:
        return None

    try:
        type_id = int(type_id)
    except (TypeError, ValueError):
        return None

    parent_type_id = raw.get("parentTypeId")
    if parent_type_id is not None:
        try:
            parent_type_id = int(parent_type_id)
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
        self._activity_type_registry: dict[int, dict[str, Any]] = {}
        self._activity_type_registry_refreshed: datetime | None = None
        self._activity_type_registry_lock = asyncio.Lock()

    def activity_type_registry(self) -> dict[int, dict[str, Any]]:
        """Return a defensive copy of the currently cached registry."""
        return {
            type_id: dict(activity_type)
            for type_id, activity_type in self._activity_type_registry.items()
        }

    async def get_activity_types(
        self, *, force_refresh: bool = False
    ) -> list[dict[str, Any]]:
        """Return Garmin's current activity type hierarchy.

        The hierarchy changes very rarely, so a 24-hour cache keeps this
        effectively free during normal coordinator polling while still making
        new Garmin activity types appear automatically.
        """
        now = datetime.now(UTC)
        if (
            not force_refresh
            and self._activity_type_registry
            and self._activity_type_registry_refreshed is not None
            and now - self._activity_type_registry_refreshed
            < _ACTIVITY_TYPES_CACHE_TTL
        ):
            return [
                dict(item)
                for _, item in sorted(self._activity_type_registry.items())
            ]

        async with self._activity_type_registry_lock:
            now = datetime.now(UTC)
            if (
                not force_refresh
                and self._activity_type_registry
                and self._activity_type_registry_refreshed is not None
                and now - self._activity_type_registry_refreshed
                < _ACTIVITY_TYPES_CACHE_TTL
            ):
                return [
                    dict(item)
                    for _, item in sorted(self._activity_type_registry.items())
                ]

            data = await self._request("GET", _ACTIVITY_TYPES_URL)
            if isinstance(data, dict):
                raw_types = data.get("activityTypes") or data.get("types") or []
            else:
                raw_types = data

            registry: dict[int, dict[str, Any]] = {}
            if isinstance(raw_types, list):
                for raw in raw_types:
                    if not isinstance(raw, dict):
                        continue
                    item = _normalise_activity_type(raw)
                    if item is not None:
                        registry[item["typeId"]] = item

            # A transient empty response must not wipe a previously good cache.
            if registry:
                self._activity_type_registry = registry
                self._activity_type_registry_refreshed = now

            return [
                dict(item)
                for _, item in sorted(self._activity_type_registry.items())
            ]

    def _resolve_activity_type(self, type_id: int) -> dict[str, Any]:
        """Resolve one numeric Garmin activity type ID."""
        item = self._activity_type_registry.get(type_id)
        if item is not None:
            return dict(item)
        return {
            "typeId": type_id,
            "typeKey": f"type_{type_id}",
            "parentTypeId": None,
        }

    async def fetch_activity_data(
        self, target_date: Any = None
    ) -> dict[str, Any]:
        """Fetch activity data and attach the current activity type registry."""
        activity_types = await self._safe_call(self.get_activity_types)
        data = await super().fetch_activity_data(target_date)
        data["activityTypes"] = activity_types or [
            dict(item)
            for _, item in sorted(self._activity_type_registry.items())
        ]
        return data

    async def fetch_gear_data(self, timezone: str | None = None) -> dict[str, Any]:
        """Fetch gear data and resolve default activity IDs via the registry."""
        activity_types = await self._safe_call(self.get_activity_types)
        data = await super().fetch_gear_data(timezone=timezone)

        defaults = data.get("gearDefaults")
        defaults_by_gear: dict[str, list[dict[str, Any]]] = {}
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

        for gear_stat in data.get("gearStats") or []:
            if not isinstance(gear_stat, dict):
                continue
            gear_uuid = gear_stat.get("uuid") or gear_stat.get("gearUuid")
            details = defaults_by_gear.get(str(gear_uuid), []) if gear_uuid else []
            gear_stat["defaultForActivity"] = [
                detail["typeKey"] for detail in details
            ]
            gear_stat["defaultForActivityDetails"] = details

        data["activityTypes"] = activity_types or [
            dict(item)
            for _, item in sorted(self._activity_type_registry.items())
        ]
        return data
