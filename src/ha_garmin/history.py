"""Strict historical Garmin data access helpers.

This module intentionally avoids the display-oriented fallback behaviour used by
``fetch_core_data()`` and ``fetch_training_data()``. Historical/backfill callers
must receive data for the requested date range only.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Any

from .const import ACTIVITIES_URL
from .exceptions import GarminAPIError

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
