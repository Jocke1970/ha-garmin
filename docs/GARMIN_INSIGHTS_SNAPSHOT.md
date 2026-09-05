# Garmin Insights – InsightSnapshot contract

**Status:** M1 input aggregation complete  
**Branch:** `feature/garmin-insights-audit`  
**Scope:** pure Insight input contract; no Insight rules, HA entities or Lovelace

## Purpose

`InsightSnapshot` is the immutable boundary between Garmin/Fitness data and the future deterministic Insight rule engine.

The snapshot does not read Home Assistant entity states and does not perform Garmin API calls. It combines:

- strict `DailyRecoveryMetrics`
- exact-date canonical Training V4 values
- existing Strain calculation
- existing Training Effect Load Focus calculation
- recent normalized activities
- explicit data-quality metadata

## Shape

```text
InsightSnapshot
├─ as_of
├─ recovery: DailyRecoveryMetrics
├─ training: TrainingSnapshot
│  ├─ daily_load
│  ├─ ctl / atl / tsb
│  ├─ acwr
│  ├─ ramp_rate
│  ├─ strain
│  ├─ source
│  └─ algorithm_version
├─ load_focus: LoadFocusSnapshot
│  ├─ low_aerobic
│  ├─ high_aerobic
│  ├─ anaerobic
│  └─ coverage/completeness
├─ recent_activities
└─ data_quality: InsightDataQuality
   ├─ complete
   ├─ recovery_current
   ├─ training_complete
   ├─ load_focus_complete
   ├─ missing_sources
   ├─ missing_fields
   └─ stale_fields
```

## Strict-date rules

The snapshot date is derived from timezone-aware `as_of`.

Training values are selected only when their `date` exactly matches the snapshot date. An older Training point is never substituted.

A recovery record from another day may be carried into the snapshot only so it can be explicitly marked as stale:

```text
stale_fields = ("recovery",)
recovery_current = false
complete = false
```

Future recovery-dependent rules must refuse to evaluate stale recovery data.

## Fitness ownership

`InsightSnapshot` does not duplicate Training V4 formulas.

It consumes `TrainingHistoryResult` and delegates derived presentation metrics to the existing canonical helpers:

- `compute_strain_score()`
- `build_daily_load_focus_series()`

No TRIMP, CTL, ATL, TSB, ACWR, Ramp Rate, Strain or Load Focus formula is reimplemented in Insights.

## Data quality

The first V1 quality contract treats these recovery source groups as required for a globally complete snapshot:

- daily summary
- sleep
- HRV
- Training Readiness

The minimum recovery fields checked are:

- resting HR
- last-night HRV average
- sleep score
- Training Readiness

Training completeness requires exact-date Daily Load, CTL, ATL, TSB, ACWR, Ramp Rate and Strain.

Load Focus must have complete Training Effect coverage for activities on the snapshot date. A rest day is valid complete Load Focus with zero bucket totals; an activity day with missing Training Effect remains incomplete and its buckets stay `None`.

`data_quality.complete` is deliberately conservative. Individual future rules may use a smaller explicitly documented subset of inputs, but they must inspect the relevant missing/stale metadata.

## Recent activity window

The default recent activity context is seven calendar days ending on the snapshot date. Activities are normalized `ActivityMetrics` values and are sorted newest first.

The window length is configurable by the pure builder and does not imply any rule threshold.

## Public API

```python
snapshot = build_insight_snapshot(
    as_of,
    recovery=recovery,
    training_history=context.history,
    activities=context.activities,
    personal_trimp_max=personal_trimp_max,
)
```

The HA integration can later create this object after its existing Fitness warm-up/recovery selection has chosen the effective canonical Fitness context.

## Scope guard

This step changes no:

- Fitness formula
- Fitness entity ID
- Garmin API auth/session code
- Gear/deviceId code
- Home Assistant entity
- Lovelace card

The next logical step is the pure deterministic Insight rule layer operating only on `InsightSnapshot`.
