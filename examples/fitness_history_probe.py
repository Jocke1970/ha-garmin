"""Read-only Garmin Fitness history probe.

Uses an existing ha-garmin token file. It performs no login and writes no data.
The purpose is to validate historical activity retrieval and compare Garmin
Training Load coverage with the activity-level inputs needed for TRIMP.
"""

from __future__ import annotations

import argparse
import asyncio
from collections import defaultdict
from datetime import date, timedelta

from ha_garmin import GarminAuth, GarminClient, GarminHistoryClient
from ha_garmin.fitness import (
    analyze_garmin_load_coverage,
    analyze_trimp_input_coverage,
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
    garmin_coverage = analyze_garmin_load_coverage(activities)
    trimp_coverage = analyze_trimp_input_coverage(activities)
    daily = build_daily_garmin_load_series(activities, start_date, end_date)

    by_type: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
    for activity in activities:
        counts = by_type[activity.activity_type]
        counts[0] += 1
        if activity.garmin_training_load is not None:
            counts[1] += 1
        if activity.avg_hr is not None and activity.duration_minutes > 0:
            counts[2] += 1

    incomplete_days = [day for day in daily if not day.complete]

    print("Garmin Fitness history probe")
    print(f"Range: {start_date.isoformat()} -> {end_date.isoformat()} ({days} days)")
    print(f"Activities: {garmin_coverage.total_activities}")
    print(
        "Garmin Training Load coverage: "
        f"{garmin_coverage.activities_with_load}/{garmin_coverage.total_activities} "
        f"({garmin_coverage.coverage_percent:.1f}%)"
    )
    print(
        "TRIMP activity-input coverage (avg HR + duration): "
        f"{trimp_coverage.eligible_activities}/{trimp_coverage.total_activities} "
        f"({trimp_coverage.coverage_percent:.1f}%)"
    )
    print(f"Activities without Garmin load: {garmin_coverage.activities_without_load}")
    print(f"Activities missing average HR: {trimp_coverage.missing_average_hr}")
    print(f"Activities missing duration: {trimp_coverage.missing_duration}")
    print(f"Incomplete Garmin-load activity days: {len(incomplete_days)}")

    if by_type:
        print("\nCoverage by activity type:")
        for activity_type, (total, with_load, trimp_eligible) in sorted(by_type.items()):
            load_percent = (with_load / total) * 100.0 if total else 0.0
            trimp_percent = (trimp_eligible / total) * 100.0 if total else 0.0
            print(
                f"  {activity_type}: Garmin Load {with_load}/{total} "
                f"({load_percent:.1f}%), TRIMP inputs {trimp_eligible}/{total} "
                f"({trimp_percent:.1f}%)"
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
    asyncio.run(_run(args.token_path, args.days))
