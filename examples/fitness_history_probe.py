"""Read-only Garmin Fitness history probe.

Uses an existing ha-garmin token file. It performs no login and writes no data.
The purpose is to validate historical activity retrieval and compare Garmin
Training Load coverage with the activity-level inputs needed for TRIMP.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict
from datetime import date, timedelta
from typing import Any

from ha_garmin import GarminAuth, GarminClient, GarminHistoryClient
from ha_garmin.fitness import (
    GARMIN_FITNESS_ALGORITHM_VERSION,
    build_daily_garmin_load_series,
    compare_load_source_coverage,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--token-path",
        default=".garmin_tokens.json",
        help="Existing ha-garmin token file (default: .garmin_tokens.json)",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=90,
        help="Inclusive history window in days (default: 90)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Emit machine-readable JSON instead of the human summary",
    )
    return parser


def _json_ready(value: Any) -> Any:
    """Recursively convert probe values into JSON-safe primitives."""
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    return value


async def _run(token_path: str, days: int, json_output: bool = False) -> None:
    if days <= 0:
        raise SystemExit("--days must be greater than zero")

    auth = GarminAuth()
    if not auth.load_session(token_path):
        raise SystemExit(
            f"No valid existing Garmin session found at {token_path!r}; "
            "this probe intentionally does not perform login"
        )

    client = GarminClient(auth)
    history = GarminHistoryClient(client)

    end_date = date.today()
    start_date = end_date - timedelta(days=days - 1)
    activities = await history.fetch_activity_metrics(start_date, end_date)
    comparison = compare_load_source_coverage(activities)
    daily = build_daily_garmin_load_series(activities, start_date, end_date)
    incomplete_days = [day for day in daily if not day.complete]

    result = {
        "algorithm_version": GARMIN_FITNESS_ALGORITHM_VERSION,
        "range": {
            "start_date": start_date,
            "end_date": end_date,
            "days": days,
        },
        "garmin_load": asdict(comparison.garmin),
        "trimp_activity_inputs": asdict(comparison.trimp),
        "by_activity_type": [asdict(row) for row in comparison.by_activity_type],
        "garmin_load_incomplete_days": [
            {
                "date": day.date,
                "activity_count": day.activity_count,
                "activities_with_load": day.loaded_activity_count,
            }
            for day in incomplete_days
        ],
        "notes": {
            "read_only": True,
            "trimp_requires_additional_context": [
                "resting_hr_for_each_activity_day",
                "user_max_hr",
                "sex",
            ],
        },
    }

    if json_output:
        print(json.dumps(_json_ready(result), indent=2, sort_keys=True))
        return

    garmin = comparison.garmin
    trimp = comparison.trimp
    print("Garmin Fitness history probe")
    print(f"Algorithm version: {GARMIN_FITNESS_ALGORITHM_VERSION}")
    print(f"Range: {start_date.isoformat()} -> {end_date.isoformat()} ({days} days)")
    print(f"Activities: {garmin.total_activities}")
    print(
        "Garmin Training Load coverage: "
        f"{garmin.activities_with_load}/{garmin.total_activities} "
        f"({garmin.coverage_percent:.1f}%)"
    )
    print(
        "TRIMP activity-input coverage (avg HR + duration): "
        f"{trimp.eligible_activities}/{trimp.total_activities} "
        f"({trimp.coverage_percent:.1f}%)"
    )
    print(f"Activities without Garmin load: {garmin.activities_without_load}")
    print(f"Activities missing average HR: {trimp.missing_average_hr}")
    print(f"Activities missing duration: {trimp.missing_duration}")
    print(f"Incomplete Garmin-load activity days: {len(incomplete_days)}")

    if comparison.by_activity_type:
        print("\nCoverage by activity type:")
        for row in comparison.by_activity_type:
            print(
                f"  {row.activity_type}: Garmin Load "
                f"{row.garmin_load_activities}/{row.total_activities} "
                f"({row.garmin_load_percent:.1f}%), TRIMP inputs "
                f"{row.trimp_eligible_activities}/{row.total_activities} "
                f"({row.trimp_input_percent:.1f}%)"
            )

    if incomplete_days:
        print("\nFirst incomplete Garmin-load days:")
        for day in incomplete_days[:10]:
            print(
                f"  {day.date.isoformat()}: "
                f"{day.loaded_activity_count}/{day.activity_count} activities with load"
            )

    print(
        "\nNote: TRIMP also needs resting HR for each activity day and a configured "
        "max HR/sex. This probe only reports activity-level eligibility."
    )


if __name__ == "__main__":
    args = _parser().parse_args()
    asyncio.run(_run(args.token_path, args.days, args.json_output))
