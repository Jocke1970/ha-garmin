"""Read-only Garmin Fitness history probe.

Uses an existing ha-garmin token file. It performs no login and writes no data.
The purpose is to validate historical activity retrieval, compare load-source
coverage and optionally calculate complete Garmin/TRIMP Training series.
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
    TrainingHistoryResult,
    analyze_trimp_history_context,
    build_daily_garmin_load_series,
    build_training_history_from_daily_loads,
    build_trimp_training_history,
    compare_load_source_coverage,
    export_training_history_rows,
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
        "--max-hr",
        type=float,
        default=None,
        help="Optional user max HR; enables full TRIMP calculation with --sex",
    )
    parser.add_argument(
        "--sex",
        choices=("male", "female"),
        default=None,
        help="Banister sex constant; enables full TRIMP calculation with --max-hr",
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


def _history_payload(history: TrainingHistoryResult) -> dict[str, Any]:
    """Serialize one calculated source without exposing raw Garmin responses."""
    payload: dict[str, Any] = {
        "source": history.source,
        "assessment": asdict(history.assessment),
        "latest": None,
        "rows": [],
    }
    if not history.assessment.ready:
        return payload

    rows = export_training_history_rows(history)
    payload["rows"] = [asdict(row) for row in rows]
    if rows:
        payload["latest"] = asdict(rows[-1])
    return payload


async def _run(
    token_path: str,
    days: int,
    json_output: bool = False,
    max_hr: float | None = None,
    sex: str | None = None,
) -> None:
    if days <= 0:
        raise SystemExit("--days must be greater than zero")
    if (max_hr is None) != (sex is None):
        raise SystemExit("--max-hr and --sex must be supplied together")
    if max_hr is not None and max_hr <= 0:
        raise SystemExit("--max-hr must be greater than zero")

    auth = GarminAuth()
    if not auth.load_session(token_path):
        raise SystemExit(
            f"No valid existing Garmin session found at {token_path!r}; "
            "this probe intentionally does not perform login"
        )

    client = GarminClient(auth)
    history_client = GarminHistoryClient(client)

    end_date = date.today()
    start_date = end_date - timedelta(days=days - 1)
    activities, resting_hr = await asyncio.gather(
        history_client.fetch_activity_metrics(start_date, end_date),
        history_client.get_resting_heart_rate_range(start_date, end_date),
    )
    comparison = compare_load_source_coverage(activities)
    trimp_context = analyze_trimp_history_context(activities, resting_hr)

    garmin_daily = build_daily_garmin_load_series(activities, start_date, end_date)
    garmin_history = build_training_history_from_daily_loads("garmin", garmin_daily)
    incomplete_days = [day for day in garmin_daily if not day.complete]

    trimp_history: TrainingHistoryResult | None = None
    if max_hr is not None and sex is not None:
        trimp_history = build_trimp_training_history(
            activities,
            start_date,
            end_date,
            resting_hr,
            user_max_hr=max_hr,
            sex=sex,
        )

    result: dict[str, Any] = {
        "algorithm_version": GARMIN_FITNESS_ALGORITHM_VERSION,
        "range": {
            "start_date": start_date,
            "end_date": end_date,
            "days": days,
        },
        "garmin_load": asdict(comparison.garmin),
        "trimp_activity_inputs": asdict(comparison.trimp),
        "trimp_history_context": asdict(trimp_context),
        "resting_hr_measurements": len(resting_hr),
        "by_activity_type": [asdict(row) for row in comparison.by_activity_type],
        "garmin_load_incomplete_days": [
            {
                "date": day.date,
                "activity_count": day.activity_count,
                "activities_with_load": day.loaded_activity_count,
            }
            for day in incomplete_days
        ],
        "training": {
            "garmin": _history_payload(garmin_history),
            "trimp": _history_payload(trimp_history) if trimp_history else None,
        },
        "trimp_configuration": {
            "configured": trimp_history is not None,
            "max_hr": max_hr,
            "sex": sex,
        },
        "notes": {
            "read_only": True,
            "canonical_source_selected": False,
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
    print(
        "TRIMP fully eligible activity days (including resting HR): "
        f"{trimp_context.fully_eligible_activity_days}/{trimp_context.activity_days} "
        f"({trimp_context.fully_eligible_percent:.1f}%)"
    )
    print(f"Resting-HR measurements in range: {len(resting_hr)}")
    print(f"Activity days missing resting HR: {len(trimp_context.missing_resting_hr_days)}")
    print(f"Activities without Garmin load: {garmin.activities_without_load}")
    print(f"Activities missing average HR: {trimp.missing_average_hr}")
    print(f"Activities missing duration: {trimp.missing_duration}")
    print(f"Incomplete Garmin-load activity days: {len(incomplete_days)}")
    print(f"Garmin Training pipeline ready: {garmin_history.assessment.ready}")

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

    if trimp_context.missing_resting_hr_days:
        print("\nFirst activity days missing resting HR:")
        for missing_date in trimp_context.missing_resting_hr_days[:10]:
            print(f"  {missing_date.isoformat()}")

    if trimp_history is None:
        print(
            "\nTRIMP calculation not configured. Add --max-hr <bpm> --sex male|female "
            "to calculate the complete TRIMP Training series."
        )
    else:
        print(f"TRIMP Training pipeline ready: {trimp_history.assessment.ready}")
        if trimp_history.assessment.ready and trimp_history.training_points:
            latest = trimp_history.training_points[-1]
            print(
                "TRIMP latest: "
                f"CTL {latest.ctl:.3f}, ATL {latest.atl:.3f}, TSB {latest.tsb:.3f}"
            )

    print("\nNo canonical load source is selected by this probe.")


if __name__ == "__main__":
    args = _parser().parse_args()
    asyncio.run(
        _run(
            args.token_path,
            args.days,
            args.json_output,
            args.max_hr,
            args.sex,
        )
    )
