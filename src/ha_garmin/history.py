"""Strict historical Garmin data access helpers.

This module intentionally avoids the display-oriented fallback behaviour used by
``fetch_core_data()`` and ``fetch_training_data()``. Historical/backfill callers
must receive data for the requested date range only.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

from .const import (
    ACTIVITIES_URL,
    RESTING_HEART_RATE_METRIC_ID,
    RESTING_HEART_RATE_METRIC_KEY,
    USER_STATS_DAILY_URL,
)
from .exceptions import GarminAPIError
from .fitness import (
    ActivityMetrics,
    Sex,
    TrainingHistoryResult,
    build_trimp_training_history,
    normalize_activities,
)

if TYPE_CHECKING:
    from .client import GarminClient


class GarminHistoryClient:
    """Historical Garmin API helper using an existing :class:`GarminClient`.

    The wrapped client owns authentication, token refresh, retries and request
    routing. This helper adds history-specific semantics without creating a
    second Garmin session.
    """

    _PAGE_SIZE = 20
    _MAX_PAGES = 2000

    def __init__(self, client: GarminClient) -> None:
        """Initialize a history helper around an authenticated Garmin client."""
        self._client = client

    async def get_daily_summary(self, target_date: date) -> dict[str, Any]:
        """Fetch exactly one Garmin daily summary without date fallback."""
        return await self._client._get_user_summary_raw(target_date)

    async def get_resting_heart_rate_range(
        self,
        start_date: date,
        end_date: date | None = None,
    ) -> dict[date, float]:
        """Return strict historical resting-HR measurements for a date range.

        Garmin's user-stats endpoint can return the whole window in one request,
        which is preferable to issuing one API call per day during backfill.
        Missing or malformed dates are omitted rather than filled from adjacent
        days.
        """
        if end_date is None:
            end_date = start_date
        if start_date > end_date:
            raise ValueError("start_date cannot be after end_date")

        profile = await self._client.get_user_profile()
        url = f"{USER_STATS_DAILY_URL}/{quote(profile.display_name, safe='')}"
        params = {
            "fromDate": start_date.isoformat(),
            "untilDate": end_date.isoformat(),
            "metricId": RESTING_HEART_RATE_METRIC_ID,
        }
        data = await self._client._request("GET", url, params=params)
        if not data:
            return {}
        if not isinstance(data, dict):
            raise GarminAPIError(
                "Unexpected resting-HR history response: expected an object"
            )

        all_metrics = data.get("allMetrics")
        metrics_map = (
            all_metrics.get("metricsMap") if isinstance(all_metrics, dict) else None
        )
        raw_values = (
            metrics_map.get(RESTING_HEART_RATE_METRIC_KEY)
            if isinstance(metrics_map, dict)
            else None
        )
        if raw_values is None:
            return {}
        if not isinstance(raw_values, list):
            raise GarminAPIError(
                "Unexpected resting-HR history response: metric was not a list"
            )

        result: dict[date, float] = {}
        for item in raw_values:
            if not isinstance(item, dict):
                continue
            raw_date = item.get("calendarDate")
            raw_value = item.get("value")
            if (
                not isinstance(raw_date, str)
                or isinstance(raw_value, bool)
                or not isinstance(raw_value, (int, float, str))
            ):
                continue
            try:
                measurement_date = date.fromisoformat(raw_date)
                value = float(raw_value)
            except ValueError:
                continue
            if value <= 0 or value != value or value in (float("inf"), float("-inf")):
                continue
            if start_date <= measurement_date <= end_date:
                result[measurement_date] = value
        return result

    async def get_activities_by_date(
        self,
        start_date: date,
        end_date: date | None = None,
        activity_type: str | None = None,
        sort_order: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return all activities in an inclusive calendar-date range.

        Results are returned in Garmin's requested/default ordering. Pagination
        continues until Garmin returns an empty page. A hard page cap prevents a
        broken server response from causing an unbounded loop.
        """
        if end_date is None:
            end_date = start_date
        if start_date > end_date:
            raise ValueError("start_date cannot be after end_date")

        activities: list[dict[str, Any]] = []

        for page_index in range(self._MAX_PAGES):
            params: dict[str, Any] = {
                "start": page_index * self._PAGE_SIZE,
                "limit": self._PAGE_SIZE,
                "startDate": start_date.isoformat(),
                "endDate": end_date.isoformat(),
            }
            if activity_type:
                params["activityType"] = activity_type
            if sort_order:
                params["sortOrder"] = sort_order

            page = await self._client._request("GET", ACTIVITIES_URL, params=params)
            if not page:
                return activities
            if not isinstance(page, list):
                raise GarminAPIError(
                    "Unexpected activities-by-date response: expected a list"
                )
            if not all(isinstance(item, dict) for item in page):
                raise GarminAPIError(
                    "Unexpected activities-by-date response: list contained non-object items"
                )

            activities.extend(page)

        raise GarminAPIError(
            "Activities-by-date pagination exceeded safety limit "
            f"({self._MAX_PAGES} pages)"
        )

    async def fetch_activity_metrics(
        self,
        start_date: date,
        end_date: date | None = None,
        activity_type: str | None = None,
        sort_order: str | None = None,
    ) -> list[ActivityMetrics]:
        """Fetch, normalize and deduplicate historical activities."""
        raw = await self.get_activities_by_date(
            start_date,
            end_date,
            activity_type=activity_type,
            sort_order=sort_order,
        )
        return normalize_activities(raw)

    async def fetch_trimp_training_history(
        self,
        start_date: date,
        end_date: date,
        *,
        user_max_hr: float,
        sex: Sex,
    ) -> TrainingHistoryResult:
        """Fetch strict Garmin history and derive the canonical TRIMP series.

        This facade deliberately reuses the wrapped authenticated client and
        performs only date-bound historical requests. It is the intended handoff
        point for Home Assistant coordinators once this library version is
        released: the integration should not duplicate Fitness formulas.
        """
        if start_date > end_date:
            raise ValueError("start_date cannot be after end_date")
        if user_max_hr <= 0:
            raise ValueError("user_max_hr must be positive")
        if sex not in ("male", "female"):
            raise ValueError("sex must be male or female")

        activities = await self.fetch_activity_metrics(start_date, end_date)
        resting_hr = await self.get_resting_heart_rate_range(start_date, end_date)
        return build_trimp_training_history(
            activities,
            start_date,
            end_date,
            resting_hr,
            user_max_hr,
            sex,
        )
