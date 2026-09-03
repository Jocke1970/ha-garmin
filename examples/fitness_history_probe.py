"""Read-only Garmin Fitness history probe.

Uses an existing ha-garmin token file. It performs no login and writes no data.
The purpose is to validate historical activity retrieval and measure Garmin
``activityTrainingLoad`` coverage before selecting the canonical load source.
"""

from __future__ import annotations

import argparse
import asyncio
from collections import defaultdict
from datetime import date, timedelta

from ha_garmin import GarminAuth, GarminClient, GarminHistoryClient
from ha_garmin.fitness import (
    analyze_garmin_load_coverage,
    build_daily_garmin_load_series,
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
    return parser


async def _run(token_path: str, days: int) -> None:
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
    coverage = analyze_garmin_load_coverage(activities)
    daily = build_daily_garmin_load_series(activities, start_date, end_date)

    by_type: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for activity in activities:
        counts = by_type[activity.activity_type]
        counts[0] += 1
        if activity.garmin_training_load is not None:
            counts[1] += 1

    incomplete_days = [day for day in daily if not day.complete]

    print("Garmin Fitness history probe")
    print(f"Range: {start_date.isoformat()} -> {end_date.isoformat()} ({days} days)")
    print(f"Activities: {coverage.total_activities}")
    print(
        "Garmin Training Load coverage: "
        f"{coverage.activities_with_load}/{coverage.total_activities} "
        f"({coverage.coverage_percent:.1f}%)"
    )
    print(f"Activities without Garmin load: {coverage.activities_without_load}")
    print(f"Incomplete activity days: {len(incomplete_days)}")

    if by_type:
        print("\nCoverage by activity type:")
        for activity_type, (total, with_load) in sorted(by_type.items()):
            percent = (with_load / total) * 100.0 if total else 0.0
            print(f"  {activity_type}: {with_load}/{total} ({percent:.1f}%)")

    if incomplete_days:
        print("\nFirst incomplete days:")
        for day in incomplete_days[:10]:
            print(
                f"  {day.date.isoformat()}: "
                f"{day.loaded_activity_count}/{day.activity_count} activities with load"
            )


if __name__ == "__main__":
    args = _parser().parse_args()
    asyncio.run(_run(args.token_path, args.days))
