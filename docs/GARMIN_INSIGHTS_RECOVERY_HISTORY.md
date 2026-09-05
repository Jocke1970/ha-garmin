# Garmin Insights — strict recovery history

**Status:** implementation baseline  
**Branch:** `feature/garmin-insights-audit`  
**Scope:** dated recovery inputs for a future deterministic Insight engine

## Purpose

Insight rules must not consume display-oriented Home Assistant sensor states as
source of truth. Those sensors may preserve the previous value or fall back to an
adjacent Garmin day for presentation. Recovery history instead needs exact-date
semantics so a recommendation never treats stale physiology as today's data.

The strict history boundary is `GarminHistoryClient`.

## DailyRecoveryMetrics

`DailyRecoveryMetrics` is one normalized record for one requested Garmin calendar
day. Missing measurements remain `None`; they are never converted to zero and are
never filled from yesterday or tomorrow.

Current fields:

- resting HR and Garmin 7-day resting-HR average
- HRV status, weekly average, last-night average, 5-minute high and Garmin baseline
- sleep score, total sleep, sleep need, deep sleep and REM sleep
- average stress
- Body Battery recent/high/low
- regular Training Readiness and readiness level
- morning Training Readiness
- recovery time in minutes
- per-source availability flags for summary, sleep, HRV and readiness contexts

## Strict source semantics

For a requested date `D`, the facade requests only `D` from:

1. Garmin daily summary
2. Garmin sleep
3. Garmin HRV
4. Garmin Training Readiness

Training Readiness is fetched once and split into regular and
`AFTER_WAKEUP_RESET` contexts. One context is never substituted for the other.

If a Garmin payload explicitly contains a `calendarDate`/`date` that does not
match `D`, that source is rejected for the daily record. If Garmin omits embedded
date metadata, the payload is accepted because `D` is already encoded in the
requested endpoint.

API failures are intentionally not swallowed by `_safe_call`. A failed request
must remain distinguishable from a successful response with no physiological
measurement.

## History API

```python
history = GarminHistoryClient(client)

one_day = await history.fetch_daily_recovery_metrics(target_date)

window = await history.fetch_recovery_history(start_date, end_date)
```

The date range is inclusive. Requests are sequential by design to avoid burst
traffic across several Garmin endpoints during backfill.

## Ownership boundary

`ha-garmin` owns:

- exact-date Garmin fetching
- source/date validation
- reusable `DailyRecoveryMetrics` normalization

Home Assistant will later own:

- current snapshot orchestration
- freshness/data-age calculation relative to HA local time
- Recorder/statistics persistence where useful
- Insight entities and presentation provenance

The future deterministic Insight engine can then combine strict recovery records
with the already locked Training V4 series without changing TRIMP, CTL, ATL, TSB,
ACWR, Ramp Rate, Strain or Load Focus.
