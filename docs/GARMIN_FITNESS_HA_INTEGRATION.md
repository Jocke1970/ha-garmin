# Garmin Fitness — Home Assistant Integration Handoff

> Status: design locked for Sprint 1 integration layer  
> Library branch: `feature/garmin-fitness`  
> Target HA integration: `cyberjunky/home-assistant-garmin_connect`

## Purpose

Define the boundary between the Home Assistant-neutral Garmin Fitness engine in
`ha-garmin` and the Home Assistant-specific persistence/entities/backfill layer.

The rule is simple:

```text
ha-garmin
    Garmin API + normalization + fitness math + export rows
                         |
                         v
home-assistant-garmin_connect
    config entry + coordinator + sensors + Recorder/LTS + backfill state
```

No Home Assistant imports belong in `ha-garmin`.

---

## Existing integration architecture

The current Garmin Connect integration creates one `GarminAuth` and one
`GarminClient` per config entry. The same client/auth objects are passed to all
coordinators (`CoreCoordinator`, `ActivityCoordinator`, `TrainingCoordinator`,
etc.).

Garmin Fitness must follow the same pattern.

Proposed addition:

```text
GarminConnectCoordinators
├── core
├── activity
├── training
├── fitness      <-- new
├── body
├── goals
├── gear
├── blood_pressure
├── menstrual
└── nutrition
```

`FitnessCoordinator` receives the **same existing `GarminClient`** and therefore
creates no second Garmin login, token store, or session.

---

## FitnessCoordinator responsibilities

The coordinator should own only application orchestration:

- request activity history through `GarminHistoryClient`
- inspect Garmin Load / TRIMP input coverage
- use the configured canonical load source
- request strict daily context when TRIMP requires it
- call the pure Garmin Fitness calculation pipeline
- expose current/latest calculated values to sensors
- trigger incremental historical persistence when new complete data exists
- keep rate-limited backfill work resumable

It should **not** reimplement CTL, ATL, TSB, ACWR, ramp rate, TRIMP, strain, or
load-focus formulas.

Those live in `ha_garmin.fitness`.

---

## Initial current-state sensors

Proposed entity keys:

```text
fitnessDailyLoad
fitnessStrain
fitnessCTL
fitnessATL
fitnessTSB
fitnessACWR
fitnessRampRate
fitnessLoadFocus
fitnessLoadCoverage
fitnessLoadSource
```

Suggested user-facing entity IDs will normally become:

```text
sensor.garmin_connect_fitness_daily_load
sensor.garmin_connect_fitness_strain
sensor.garmin_connect_fitness_ctl
sensor.garmin_connect_fitness_atl
sensor.garmin_connect_fitness_tsb
sensor.garmin_connect_fitness_acwr
sensor.garmin_connect_fitness_ramp_rate
sensor.garmin_connect_fitness_load_focus
sensor.garmin_connect_fitness_load_coverage
sensor.garmin_connect_fitness_load_source
```

Actual entity IDs must never be assumed by backfill code because users can
rename entities. Resolve the entity registry entry from the config-entry unique
ID before importing statistics.

---

## Sensor state classes

The numeric historical metrics should use measurement semantics:

```text
Daily Load     measurement
Strain         measurement
CTL            measurement
ATL            measurement
TSB            measurement
ACWR           measurement
Ramp Rate      measurement
```

`Load Focus`, `Load Source`, and diagnostic coverage are categorical/diagnostic
entities and do not need numeric long-term statistics.

CTL/ATL/TSB/load/ACWR/ramp are dimensionless calculated values, so initial
statistics metadata uses no physical unit converter:

```python
unit_class = None
unit_of_measurement = None
```

---

## Backfill should use the sensor statistic IDs

Do **not** create a second set of unrelated external statistic IDs for metrics
that also have Home Assistant sensors.

Home Assistant's recorder API distinguishes:

- valid entity statistic IDs -> `async_import_statistics`
- non-entity external statistic IDs -> `async_add_external_statistics`

For Garmin Fitness numeric sensors, use `async_import_statistics` so the current
sensor and its historical 90-day series are the same statistic.

Current Home Assistant 2026 recorder metadata shape:

```python
from homeassistant.components.recorder import DOMAIN as RECORDER_DOMAIN
from homeassistant.components.recorder.models import (
    StatisticMeanType,
    StatisticMetaData,
)

metadata: StatisticMetaData = {
    "source": RECORDER_DOMAIN,
    "name": None,
    "statistic_id": entity_id,
    "unit_class": None,
    "unit_of_measurement": None,
    "mean_type": StatisticMeanType.ARITHMETIC,
    "has_sum": False,
}
```

`mean_type` and `unit_class` must be supplied explicitly. Older metadata forms
are deprecated and become invalid in upcoming Home Assistant releases.

---

## Daily statistics representation

The Fitness engine exports one row per local Garmin calendar day:

```text
date
daily_load
ctl
atl
tsb
acwr
ramp_rate
```

For recorder import, represent each daily point as one hourly statistic sample
at **00:00 UTC for that calendar date**.

Example:

```python
StatisticData(
    start=datetime.combine(row.date, time.min, tzinfo=UTC),
    mean=row.ctl,
    min=row.ctl,
    max=row.ctl,
)
```

Why UTC midnight:

- the training day itself is already assigned using Garmin's local date
- UTC midnight is unambiguous across DST transitions
- it remains on the same displayed calendar day in European time zones
- no attempt is made to imply that CTL was physiologically measured at midnight;
  this is a daily analytical sample

ACWR and ramp rate naturally have unavailable values at the start of a newly
backfilled series. Do not import fake zeros for those dates.

---

## Initial backfill lifecycle

Default initial history window:

```text
90 days
```

Recommended flow:

```text
integration setup
      |
      v
Fitness sensors registered
      |
      v
resolve actual entity IDs
      |
      v
load small backfill metadata Store
      |
      +--> already complete for current algorithm/source?
      |        |
      |        +--> yes: incremental update only
      |
      v
fetch 90d activities
      |
      v
coverage analysis
      |
      v
canonical source pipeline
      |
      v
import complete historical sensor statistics
      |
      v
mark backfill complete
```

Backfill must not block normal Garmin entities from starting.

---

## Small persistent state is allowed

The "no separate database" rule does not mean "no state at all".

Use Home Assistant `Store` only for orchestration metadata, for example:

```json
{
  "version": 1,
  "algorithm_version": 1,
  "load_source": "garmin",
  "history_days": 90,
  "last_backfilled_date": "2026-09-03",
  "backfill_status": "complete"
}
```

Do **not** store 90/365 days of time-series values in this JSON file. Those
belong in Recorder long-term statistics.

---

## Backfill idempotency

The same history may be recalculated multiple times during development or after
an algorithm migration.

Required behavior:

- stable statistic IDs
- deterministic algorithm output for the same input/source/version
- importing an already-known timestamp must update/replace predictably rather
  than create duplicate conceptual samples
- algorithm/source changes require explicit migration/rebuild semantics

Store:

```text
algorithm_version
load_source
```

with the backfill metadata so a future formula change cannot silently leave old
statistics mixed with new calculations.

---

## Incremental update strategy

Do not refetch 90 days every five minutes.

After initial backfill:

1. inspect the newest Garmin activities
2. if no relevant activity/history date changed, do nothing
3. if a recent day changed, refetch/recalculate a limited look-back window
4. persist only affected/new daily statistics

Because CTL and ATL are recursive EMAs, changing an old daily load technically
changes all following values. For ordinary new-activity sync this is simple:
recalculate from the retained canonical history and append/update the recent
series.

For late edits to older Garmin activities, use a bounded rebuild beginning at
that changed day with enough prior state/history to produce deterministic EMA
values.

MVP may choose the simpler and safer option: rebuild the configured 90-day
window when a historical activity edit is detected. This is infrequent and much
safer than complex partial-state mutation.

---

## Load-source selection

Sprint 1 deliberately does not auto-mix Garmin Load and TRIMP.

Allowed canonical values:

```text
garmin
trimp
```

Diagnostic phase:

```text
Garmin activityTrainingLoad coverage
vs
TRIMP activity input coverage (average HR + duration)
```

TRIMP additionally requires:

- resting HR for each activity day
- configured/user max HR
- sex-specific Banister constant

The read-only `examples/fitness_history_probe.py` reports the activity-level
coverage needed to make the decision using real account history.

Do not implement:

```text
Garmin Load where available + TRIMP for missing activities
```

inside one CTL/ATL series. Those values are not guaranteed to be on the same
scale.

---

## Coordinator update cadence

The ordinary Garmin integration currently polls frequently for current health
state. Fitness history does not need the same network cadence.

Recommended split:

- current Fitness state may update after Activity/Training coordinator refreshes
- historical backfill/incremental work only runs when a new relevant Garmin day
  or activity is detected
- no 90-day daily API sweep on every coordinator poll

If TRIMP becomes canonical, resting-HR historical fetch must be chunked and
resumable rather than launching ~90 simultaneous Garmin requests.

---

## Failure behavior

Historical calculations should fail closed.

Examples:

```text
activity exists + canonical load missing -> incomplete, no derived series write
rest day                              -> real zero load
missing resting HR for TRIMP day     -> incomplete
Garmin temporary API error           -> preserve previous valid statistics
algorithm exception                  -> preserve previous valid statistics
```

Never overwrite valid history with zeros because a cloud request failed.

---

## Proposed integration implementation order

### HA-1 — Fitness coordinator shell

- add `FitnessCoordinator`
- add it to `GarminConnectCoordinators`
- reuse same client/auth
- expose coverage/source diagnostics

### HA-2 — Numeric sensor entities

- Daily Load
- CTL
- ATL
- TSB
- ACWR
- Ramp Rate
- Strain where TRIMP is available

### HA-3 — Backfill manager

- small `Store` metadata
- resolve actual entity IDs
- 90-day initial backfill
- `async_import_statistics`
- idempotent restart behavior

### HA-4 — Incremental sync

- detect new/changed activity day
- recalculate affected series
- update current sensor values
- update imported statistics

### HA-5 — Training dashboard proof

One chart first:

```text
Daily Load
CTL
ATL
TSB
```

Then add:

```text
ACWR
Ramp Rate
Load Focus
Readiness / Training Status / Recovery
```

---

## Current hard blocker

The development account currently has a writable fork of `ha-garmin` but no
writable fork of `cyberjunky/home-assistant-garmin_connect`.

Therefore Sprint 1 can continue to completion at the library/calculation layer,
but the Home Assistant coordinator/sensor/statistics implementation requires a
writable integration repository (or an upstream contribution branch) before it
can be committed.
