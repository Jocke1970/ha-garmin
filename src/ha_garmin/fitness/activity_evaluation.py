"""Deterministic evaluation primitives for recent Garmin activities.

The module deliberately keeps pass evaluation separate from Home Assistant
presentation. It interprets normalized activity metrics, optionally decodes the
Garmin activity-detail time series, and exposes conservative cycling performance
estimates when the source data supports them.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from statistics import median
from typing import Any, Literal

from .models import ActivityMetrics

EvaluationConfidence = Literal["low", "medium", "high", "unavailable"]

_CYCLING_ACTIVITY_TYPES = {
    "cycling",
    "road_biking",
    "virtual_ride",
    "indoor_cycling",
    "mountain_biking",
    "gravel_cycling",
    "e_bike_fitness",
    "e_bike_mountain",
}


@dataclass(frozen=True, slots=True)
class ActivityDetailSample:
    """One location-free sample decoded from Garmin activity details."""

    elapsed_seconds: float
    power_watts: float | None
    heart_rate: float | None


@dataclass(frozen=True, slots=True)
class ActivityEvaluation:
    """Presentation-neutral evaluation of one completed activity."""

    activity_id: int
    calendar_date: str
    activity_type: str
    duration_minutes: float
    garmin_training_load: float | None
    aerobic_training_effect: float | None
    anaerobic_training_effect: float | None
    avg_hr: float | None
    max_hr: float | None
    avg_power: float | None
    normalized_power: float | None
    assessment_id: str
    title_key: str
    message_key: str
    best_5m_power: float | None
    best_20m_power: float | None
    estimated_vo2max: float | None
    estimated_ftp_watts: float | None
    vo2max_confidence: EvaluationConfidence
    ftp_confidence: EvaluationConfidence
    performance_confidence: EvaluationConfidence


def _finite_number(value: Any) -> float | None:
    """Return a finite number or None."""
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _descriptor_indices(details: dict[str, Any]) -> dict[str, int]:
    """Return Garmin activity-detail metric indexes keyed by descriptor name."""
    raw_descriptors = details.get("metricDescriptors")
    if not isinstance(raw_descriptors, list):
        return {}

    result: dict[str, int] = {}
    for descriptor in raw_descriptors:
        if not isinstance(descriptor, dict):
            continue
        key = descriptor.get("key")
        index = descriptor.get("metricsIndex")
        if isinstance(key, str) and isinstance(index, int) and index >= 0:
            result[key] = index
    return result


def _metric(metrics: list[Any], index: int | None) -> float | None:
    """Read one finite positional Garmin metric safely."""
    if index is None or index < 0 or index >= len(metrics):
        return None
    return _finite_number(metrics[index])


def parse_activity_detail_samples(details: dict[str, Any]) -> tuple[ActivityDetailSample, ...]:
    """Decode timestamp, power and HR without relying on fixed metric positions.

    Garmin returns ``activityDetailMetrics`` as positional arrays whose indexes
    are described by ``metricDescriptors``. The order varies by activity and
    device, so hard-coded indexes are intentionally forbidden here.
    """
    indices = _descriptor_indices(details)
    timestamp_index = indices.get("directTimestamp")
    elapsed_index = indices.get("sumElapsedDuration")
    power_index = indices.get("directPower")
    hr_index = indices.get("directHeartRate")

    raw_rows = details.get("activityDetailMetrics")
    if not isinstance(raw_rows, list):
        return ()

    decoded: list[tuple[float, float | None, float | None]] = []
    first_timestamp: float | None = None

    for row in raw_rows:
        if not isinstance(row, dict):
            continue
        metrics = row.get("metrics")
        if not isinstance(metrics, list):
            continue

        timestamp = _metric(metrics, timestamp_index)
        elapsed = _metric(metrics, elapsed_index)

        if timestamp is not None:
            # Garmin directTimestamp is Unix epoch milliseconds in activity details.
            if abs(timestamp) > 10_000_000_000:
                timestamp /= 1000.0
            if first_timestamp is None:
                first_timestamp = timestamp
            elapsed_seconds = timestamp - first_timestamp
        elif elapsed is not None:
            elapsed_seconds = elapsed
        else:
            continue

        if elapsed_seconds < 0:
            continue
        decoded.append(
            (
                elapsed_seconds,
                _metric(metrics, power_index),
                _metric(metrics, hr_index),
            )
        )

    decoded.sort(key=lambda item: item[0])
    return tuple(
        ActivityDetailSample(
            elapsed_seconds=round(elapsed, 3),
            power_watts=power,
            heart_rate=hr,
        )
        for elapsed, power, hr in decoded
    )


def best_mean_power(
    samples: tuple[ActivityDetailSample, ...] | list[ActivityDetailSample],
    window_seconds: int,
) -> float | None:
    """Estimate best rolling mean power from Garmin's timestamped sample stream.

    The details endpoint can be downsampled. We therefore carry each recorded
    power value forward only across a bounded gap derived from the observed
    sample spacing and require at least 95% coverage inside a candidate window.
    """
    if window_seconds <= 0:
        raise ValueError("window_seconds must be positive")

    power_points = sorted(
        (
            sample.elapsed_seconds,
            sample.power_watts,
        )
        for sample in samples
        if sample.power_watts is not None
        and sample.elapsed_seconds >= 0
        and math.isfinite(sample.elapsed_seconds)
    )
    if len(power_points) < 2:
        return None

    start_time = power_points[0][0]
    end_time = power_points[-1][0]
    if end_time - start_time < window_seconds:
        return None

    gaps = [
        current[0] - previous[0]
        for previous, current in zip(power_points, power_points[1:], strict=False)
        if current[0] > previous[0]
    ]
    typical_gap = median(gaps) if gaps else 1.0
    max_hold_seconds = max(10.0, min(60.0, typical_gap * 3.0))

    origin = math.floor(start_time)
    end_second = math.floor(end_time)
    point_index = 0
    current_power: float | None = None
    current_timestamp: float | None = None

    values: deque[float | None] = deque()
    rolling_sum = 0.0
    rolling_count = 0
    required_count = math.ceil(window_seconds * 0.95)
    best: float | None = None

    for second in range(origin, end_second + 1):
        while (
            point_index < len(power_points)
            and power_points[point_index][0] <= second + 0.5
        ):
            current_timestamp, current_power = power_points[point_index]
            point_index += 1

        value: float | None = None
        if (
            current_power is not None
            and current_timestamp is not None
            and second - current_timestamp <= max_hold_seconds
        ):
            value = float(current_power)

        values.append(value)
        if value is not None:
            rolling_sum += value
            rolling_count += 1

        if len(values) > window_seconds:
            removed = values.popleft()
            if removed is not None:
                rolling_sum -= removed
                rolling_count -= 1

        if len(values) == window_seconds and rolling_count >= required_count:
            candidate = rolling_sum / rolling_count
            if best is None or candidate > best:
                best = candidate

    return round(best, 1) if best is not None else None


def _assessment_keys(activity: ActivityMetrics) -> tuple[str, str, str]:
    """Return stable assessment id plus presentation keys from Training Effect."""
    aerobic = activity.aerobic_training_effect
    anaerobic = activity.anaerobic_training_effect

    if aerobic is None and anaerobic is None:
        return (
            "insufficient_training_effect",
            "activity_eval_insufficient_title",
            "activity_eval_insufficient_message",
        )

    aerobic_value = aerobic or 0.0
    anaerobic_value = anaerobic or 0.0

    if aerobic_value >= 2.0 and anaerobic_value >= 2.0:
        return (
            "mixed_training",
            "activity_eval_mixed_title",
            "activity_eval_mixed_message",
        )
    if anaerobic_value >= 2.5 and anaerobic_value > aerobic_value:
        return (
            "anaerobic_training",
            "activity_eval_anaerobic_title",
            "activity_eval_anaerobic_message",
        )
    if aerobic_value >= 3.5:
        return (
            "aerobic_development",
            "activity_eval_aerobic_development_title",
            "activity_eval_aerobic_development_message",
        )
    if aerobic_value >= 1.5:
        if activity.duration_minutes < 20.0:
            return (
                "short_aerobic",
                "activity_eval_short_aerobic_title",
                "activity_eval_short_aerobic_message",
            )
        return (
            "aerobic_training",
            "activity_eval_aerobic_title",
            "activity_eval_aerobic_message",
        )
    if max(aerobic_value, anaerobic_value) < 1.0:
        return (
            "recovery",
            "activity_eval_recovery_title",
            "activity_eval_recovery_message",
        )
    return (
        "light_training",
        "activity_eval_light_title",
        "activity_eval_light_message",
    )


def _effort_confidence(
    activity: ActivityMetrics,
    user_max_hr: float | None,
) -> EvaluationConfidence:
    """Describe how strongly the pass resembles a hard performance effort."""
    score = 0
    aerobic = activity.aerobic_training_effect or 0.0
    if aerobic >= 4.0:
        score += 2
    elif aerobic >= 2.5:
        score += 1

    if user_max_hr is not None and user_max_hr > 0 and activity.max_hr is not None:
        ratio = activity.max_hr / user_max_hr
        if ratio >= 0.92:
            score += 2
        elif ratio >= 0.85:
            score += 1

    if score >= 3:
        return "high"
    if score >= 1:
        return "medium"
    return "low"


def _combined_confidence(
    vo2_confidence: EvaluationConfidence,
    ftp_confidence: EvaluationConfidence,
) -> EvaluationConfidence:
    """Return a conservative combined confidence across available estimates."""
    available = [
        value
        for value in (vo2_confidence, ftp_confidence)
        if value != "unavailable"
    ]
    if not available:
        return "unavailable"
    rank = {"low": 0, "medium": 1, "high": 2}
    return min(available, key=rank.__getitem__)


def evaluate_activity(
    activity: ActivityMetrics,
    *,
    detail_samples: tuple[ActivityDetailSample, ...] | list[ActivityDetailSample] = (),
    body_weight_kg: float | None = None,
    user_max_hr: float | None = None,
) -> ActivityEvaluation:
    """Evaluate one activity without inventing unsupported performance metrics.

    Cycling FTP uses the common 95% of best 20-minute mean-power field estimate.
    Cycling VO2max uses the ACSM/Hawley-Noakes power-to-oxygen relationship on
    best 5-minute mean power. Both are training estimates rather than laboratory
    measurements, and confidence reflects whether the activity itself looked
    sufficiently hard to support the inference.
    """
    assessment_id, title_key, message_key = _assessment_keys(activity)
    is_cycling = activity.activity_type in _CYCLING_ACTIVITY_TYPES

    best_5m = best_mean_power(detail_samples, 5 * 60) if is_cycling else None
    best_20m = best_mean_power(detail_samples, 20 * 60) if is_cycling else None
    effort_confidence = _effort_confidence(activity, user_max_hr)

    estimated_vo2max: float | None = None
    vo2_confidence: EvaluationConfidence = "unavailable"
    if (
        is_cycling
        and best_5m is not None
        and body_weight_kg is not None
        and body_weight_kg > 0
    ):
        estimated_vo2max = round((10.8 * best_5m / body_weight_kg) + 7.0, 1)
        vo2_confidence = effort_confidence

    estimated_ftp: float | None = None
    ftp_confidence: EvaluationConfidence = "unavailable"
    if is_cycling and best_20m is not None:
        estimated_ftp = round(best_20m * 0.95)
        ftp_confidence = effort_confidence

    return ActivityEvaluation(
        activity_id=activity.activity_id,
        calendar_date=activity.calendar_date.isoformat(),
        activity_type=activity.activity_type,
        duration_minutes=activity.duration_minutes,
        garmin_training_load=activity.garmin_training_load,
        aerobic_training_effect=activity.aerobic_training_effect,
        anaerobic_training_effect=activity.anaerobic_training_effect,
        avg_hr=activity.avg_hr,
        max_hr=activity.max_hr,
        avg_power=activity.avg_power,
        normalized_power=activity.normalized_power,
        assessment_id=assessment_id,
        title_key=title_key,
        message_key=message_key,
        best_5m_power=best_5m,
        best_20m_power=best_20m,
        estimated_vo2max=estimated_vo2max,
        estimated_ftp_watts=estimated_ftp,
        vo2max_confidence=vo2_confidence,
        ftp_confidence=ftp_confidence,
        performance_confidence=_combined_confidence(
            vo2_confidence,
            ftp_confidence,
        ),
    )
