# Garmin Fitness for Home Assistant

> Status: planning / architecture baseline  
> Working branch: `feature/garmin-fitness`

## Goal

Build a Home Assistant-native fitness and training analytics layer on top of the existing `ha-garmin` Garmin Connect client.

The project should recreate the useful concepts from PulseCoach — primarily **Training**, **Fitness**, **Insights**, and **Trends** — without recreating its separate application stack.

Garmin authentication, API access, token handling, and Garmin-specific normalization remain the responsibility of `ha-garmin`. Home Assistant becomes the application platform, history/statistics layer, and user interface.

## Inspiration and attribution

This project is conceptually inspired by **PulseCoach — AI Fitness Coaching App**, maintained by GitHub user [`askb`](https://github.com/askb) in [`askb/ha-garmin-fitness-coach-app`](https://github.com/askb/ha-garmin-fitness-coach-app).

PulseCoach demonstrates useful training-analysis concepts including CTL/ATL/TSB, ACWR, ramp rate, VO2max/race prediction views, long-term trends, and proactive insights. Its repository is licensed under the **Apache License 2.0**.

Garmin Fitness for Home Assistant is intended as an independent Home Assistant-native implementation built on the existing `ha-garmin` client. The architecture deliberately avoids PulseCoach's Next.js/PostgreSQL application stack and separate Garmin authentication. At project inception no PulseCoach source code is copied into this repository. If source code is reused in the future, applicable Apache-2.0 attribution and notice requirements must be preserved.

## Core architecture

```text
Garmin Connect
      |
      v
+----------------------+
|      ha-garmin       |
| Auth                 |
| Garmin API           |
| Garmin normalization |
+----------+-----------+
           |
           v
+------------------------------+
| Garmin Fitness Engine        |
| History / normalization      |
| Activity load                |
| Training metrics             |
| Fitness metrics              |
| Trend calculations           |
| Insight rule engine          |
+----------+-------------------+
           |
     +-----+---------+
     v               v
HA entities       HA statistics
current state     historical series
     |               |
     +-------+-------+
             v
        Lovelace UI
```

## Architectural rules

### `ha-garmin` owns

- Garmin authentication and MFA
- session/token persistence and refresh
- Garmin API endpoints
- retry/rate-limit handling
- Garmin-specific field normalization
- fetching historical Garmin data

### Garmin Fitness owns

- historical fitness/training model
- activity-load calculations
- CTL / ATL / TSB / ACWR / ramp rate
- fitness calculations
- baselines and trends
- deterministic insight rules
- Home Assistant-facing derived metrics

### Non-goals

At least for v1:

- no second Garmin authentication
- no PostgreSQL
- no Next.js
- no separate web server
- no Docker fitness stack
- no AI dependency for recommendations
- no automatic medical advice
- no replacement for Garmin Connect
- no copying the PulseCoach frontend

## Data model

### `DailyMetrics`

One normalized record per calendar day. Candidate fields:

```text
date
resting_hr
hrv
sleep_score
sleep_minutes
deep_sleep_minutes
rem_sleep_minutes
stress
body_battery_high
body_battery_low
training_readiness
recovery_hours
vo2max_running
vo2max_cycling
endurance_score
hill_score
weight
body_fat
steps
active_calories
```

Missing physiological data remains `None`; it must not silently become zero.

### `ActivityMetrics`

One normalized record per activity. Candidate fields:

```text
activity_id
start_time
activity_type
sport
duration
distance
avg_hr
max_hr
resting_hr
calories
aerobic_training_effect
anaerobic_training_effect
training_load
exercise_load
avg_power
normalized_power
ftp
elevation_gain
garmin_recovery_time
trimp
strain
```

The model must tolerate activities where many sport-specific fields are unavailable.

## Historical storage

Do not create a second fitness database. Use Home Assistant Recorder/statistics infrastructure wherever practical.

### Current-state entities

Examples:

```text
sensor.garmin_fitness_ctl
sensor.garmin_fitness_atl
sensor.garmin_fitness_tsb
sensor.garmin_fitness_acwr
```

### Historical numeric series

Candidate statistic IDs:

```text
garmin_fitness:daily_load
garmin_fitness:strain
garmin_fitness:ctl
garmin_fitness:atl
garmin_fitness:tsb
garmin_fitness:acwr
garmin_fitness:hrv
garmin_fitness:resting_hr
garmin_fitness:sleep_score
garmin_fitness:training_readiness
garmin_fitness:vo2max_running
garmin_fitness:vo2max_cycling
garmin_fitness:endurance_score
```

Historical backfill should use Home Assistant statistics/external statistics rather than synthesizing old entity states.

### Backfill

Initial target: **90 days**. Later target: **365 days**.

Backfill must be resumable and must not restart from scratch after every Home Assistant restart.

Suggested state:

```text
backfill_start
backfill_end
backfill_last_completed
backfill_status
```

Possible status values:

```text
idle
running
complete
partial
error
```

## M0 — Foundation / historical API audit

### Goal

Prepare `ha-garmin` and Garmin Fitness for historical analytics.

### Tasks

- [ ] audit Garmin endpoints currently exposed by `ha-garmin`
- [ ] identify which metrics already accept arbitrary dates/date ranges
- [ ] identify missing historical/date-range methods
- [ ] define `DailyMetrics`
- [ ] define `ActivityMetrics`
- [ ] add sanitized Garmin response fixtures
- [ ] establish Garmin Fitness package/integration placement
- [ ] document historical API gaps before implementation

### Candidate `ha-garmin` methods where gaps exist

```python
get_daily_summary(target_date)
get_sleep(target_date)
get_hrv(target_date)
get_training_readiness(target_date)
get_training_status(target_date)
get_activities_between(start_date, end_date)
fetch_daily_history(start_date, end_date)
fetch_activity_history(start_date, end_date)
```

Exact methods depend on the M0 audit; do not add duplicate wrappers where equivalent functionality already exists.

### Exit criterion

Given a date range, the client can return normalized daily metrics and activities without Home Assistant or Lovelace being involved.

## M1 — History engine

### Goal

Make 28/42/90-day calculations reliable.

### Tasks

- [ ] historical Garmin fetch
- [ ] daily zero-load rest days
- [ ] activity deduplication by Garmin activity ID
- [ ] timezone-safe day boundaries
- [ ] Home Assistant statistics import
- [ ] incremental update after Garmin sync
- [ ] initial 90-day backfill
- [ ] interrupted-backfill recovery

A day with no activity must still exist in the load series with `daily_load = 0`; otherwise CTL/ATL calculations are wrong.

### Exit criterion

Home Assistant contains a continuous daily training-load series covering at least 90 days.

## M2 — Training engine

This is the first user-visible feature set.

### Activity strain / load

Prefer a clearly defined canonical load source. Garmin-native load and calculated TRIMP must never be silently mixed in one CTL/ATL series.

Calculated Banister TRIMP may be used where appropriate:

```text
relative HR = (avg HR - resting HR) / (max HR - resting HR)
TRIMP = duration_minutes * relative HR * exp(k * relative HR)
```

Derived values must expose their source/algorithm.

### CTL — Fitness

42-day exponential moving average of daily load.

```text
sensor.garmin_fitness_ctl
```

### ATL — Fatigue

7-day exponential moving average of daily load.

```text
sensor.garmin_fitness_atl
```

### TSB — Form

```text
TSB = CTL - ATL
sensor.garmin_fitness_tsb
```

### ACWR

Initial implementation:

```text
7-day load / 28-day load
sensor.garmin_fitness_acwr
```

Optional later algorithm: EWMA ACWR.

### Ramp rate

```text
CTL today - CTL 7 days ago
sensor.garmin_fitness_ramp_rate
```

### Load focus

Use Garmin Training Effect where reliable:

```text
aerobic
anaerobic
mixed
unknown
```

Candidate entity:

```text
sensor.garmin_fitness_load_focus
```

### Training MVP entities

```text
sensor.garmin_fitness_daily_load
sensor.garmin_fitness_strain
sensor.garmin_fitness_ctl
sensor.garmin_fitness_atl
sensor.garmin_fitness_tsb
sensor.garmin_fitness_acwr
sensor.garmin_fitness_ramp_rate
sensor.garmin_fitness_load_focus
sensor.garmin_fitness_training_readiness
sensor.garmin_fitness_training_status
sensor.garmin_fitness_recovery_hours
```

### Exit criterion

A 90-day Lovelace chart can show CTL, ATL, TSB, and daily load and produces identical historical values after a Home Assistant restart/recalculation.

## M3 — Training dashboard

Create a Lovelace **Training** view.

Top-level cards:

```text
Training Readiness
Training Status
Recovery
Today's Load
```

Main Performance Management Chart:

```text
CTL
ATL
TSB
```

Secondary cards:

```text
ACWR
Ramp Rate
Load Focus
Recent activities
```

Prefer existing Home Assistant cards first: Mushroom, ApexCharts, native statistics/history cards, and button-card only where justified.

## M4 — Fitness

Expose and retain Garmin-native metrics where available:

```text
VO2max running
VO2max cycling
Endurance Score
Hill Score
Lactate Threshold
FTP
Power-to-weight
```

Add trends such as 7/28/90-day VO2max direction without treating a one-day fluctuation as a meaningful trend.

Later composite metrics may include a clearly named **Garmin Fitness Score** and sport-specific shape metrics. These are our calculations, not Garmin metrics, and must expose `source` and `algorithm_version`.

## M5 — Trends

Create Lovelace **Trends** view with periods such as:

```text
7 days
28 days
90 days
6 months
1 year
```

Priority metrics:

### Recovery

```text
HRV
resting HR
sleep score
training readiness
body battery
stress
```

### Training

```text
daily load
CTL
ATL
TSB
ACWR
```

### Fitness

```text
VO2max
Endurance Score
FTP
power-to-weight
weight
```

Implement reusable rolling baseline/trend calculations rather than metric-specific duplicated logic.

## M6 — Insights

Version 1 is deterministic and explainable; no AI is required.

Suggested insight model:

```text
id
category
severity
title
message
reason
metrics
created_at
expires_at
```

Categories:

```text
training
recovery
sleep
fitness
consistency
data_quality
```

Every recommendation must explain which metrics triggered it. Missing data should result in an explicit insufficient-data state rather than a guessed recommendation.

Example rules:

- HRV below baseline + resting HR above baseline + elevated ATL -> recovery-oriented recommendation
- high readiness + acceptable TSB + adequate sleep/HRV -> favourable quality-session signal
- high ACWR or excessive ramp rate -> recent-load-spike warning
- positive VO2max trend + positive CTL trend + stable recovery -> positive fitness insight

## M7 — Advanced fitness

Only after the foundations have sufficient historical data and validation:

- [ ] running shape
- [ ] cycling/general fitness shape
- [ ] 5 km prediction
- [ ] 10 km prediction
- [ ] half-marathon prediction
- [ ] marathon prediction
- [ ] confidence scoring
- [ ] sport-specific models

## Home Assistant entity philosophy

Keep entity states small and useful. Do not put months of JSON time-series data into sensor attributes. Historical data belongs in Home Assistant statistics/history.

Every derived metric should identify its origin, for example:

```text
source: garmin
```

or:

```text
source: garmin_fitness
algorithm: banister_ctl
algorithm_version: 1
```

Garmin/Firstbeat values and our calculations must always be distinguishable.

## Suggested calculation-engine package structure

Long-term conceptual target:

```text
garmin_fitness/
├── __init__.py
├── const.py
├── models.py
├── history/
│   ├── __init__.py
│   ├── fetcher.py
│   ├── backfill.py
│   └── statistics.py
├── training/
│   ├── __init__.py
│   ├── trimp.py
│   ├── load.py
│   ├── ctl.py
│   ├── acwr.py
│   └── focus.py
├── fitness/
│   ├── __init__.py
│   ├── vo2max.py
│   ├── fitness_score.py
│   └── race_prediction.py
├── trends/
│   ├── __init__.py
│   ├── baseline.py
│   └── trend.py
└── insights/
    ├── __init__.py
    ├── models.py
    ├── engine.py
    └── rules/
```

Exact placement is deliberately deferred until M0 establishes whether this belongs inside the Home Assistant integration, as a sibling package, or partly in `ha-garmin`. Calculation modules should remain testable without Garmin or Lovelace.

## Testing strategy

Required tests include:

### Load calculations

- zero activity
- one activity
- multiple activities same day
- rest days
- missing HR
- invalid HR ranges

### CTL / ATL / TSB

- fixed known input/output vectors
- 42-day behaviour
- 7-day behaviour
- rest-week decay
- large load spike

### ACWR

- zero chronic load
- stable training
- sudden spike
- insufficient history

### History

- timezone boundaries
- duplicate Garmin activity
- partial backfill
- restart during backfill
- missing Garmin day

### Insights

Every rule requires a trigger test, non-trigger test, boundary test, and missing-data test.

## Data-quality rules

Never silently invent physiological values.

- no HRV measurement -> `None`, not `0`
- no activity -> daily load `0`, because zero is meaningful
- no new VO2max measurement -> keep the historical measurement timestamp rather than inventing a new daily sample

Expose `last_measurement`, `sample_count`, and/or `data_age` where useful.

## Milestones

### M0 — Foundation

- [ ] historical API audit
- [ ] `DailyMetrics`
- [ ] `ActivityMetrics`
- [ ] historical Garmin fetch plan
- [ ] test fixtures

### M1 — History

- [ ] 90-day backfill
- [ ] activity deduplication
- [ ] continuous daily load
- [ ] HA statistics import
- [ ] incremental sync

### M2 — Training Engine

- [ ] daily load
- [ ] TRIMP
- [ ] CTL
- [ ] ATL
- [ ] TSB
- [ ] ACWR
- [ ] ramp rate
- [ ] load focus

### M3 — Training UI

- [ ] Training overview
- [ ] PMC graph
- [ ] readiness/status
- [ ] load cards
- [ ] recent activities

**First major release target: Garmin Fitness v0.1 — Training**

### M4 — Fitness

- [ ] VO2max history
- [ ] VO2max trend
- [ ] Endurance Score
- [ ] Lactate Threshold
- [ ] FTP / power-to-weight
- [ ] general fitness score

### M5 — Trends

- [ ] HRV baseline
- [ ] resting-HR baseline
- [ ] sleep baseline
- [ ] recovery trends
- [ ] training trends
- [ ] fitness trends
- [ ] 7/28/90/365-day UI

### M6 — Insights

- [ ] insight model
- [ ] rule engine
- [ ] recovery rules
- [ ] training-load rules
- [ ] fitness rules
- [ ] data-quality rules
- [ ] Insights dashboard

### M7 — Advanced Fitness

- [ ] shape metrics
- [ ] race predictions
- [ ] confidence scoring
- [ ] sport-specific models

## Definition of v1 success

Garmin Fitness v1 is successful when:

1. Garmin Connect is authenticated only once through the existing Garmin stack.
2. At least 90 days of history can be imported without a separate fitness database.
3. CTL, ATL, TSB, and ACWR survive Home Assistant restarts and produce reproducible values.
4. Garmin metrics and calculated Garmin Fitness metrics are clearly distinguishable.
5. Trends are available beyond ordinary short-term entity state history.
6. Missing Garmin data is handled explicitly.
7. Insights explain why a recommendation was generated.
8. Important calculations have unit tests.
9. The useful experience is available inside Home Assistant.
10. Removing Garmin Fitness does not break `ha-garmin` authentication or core Garmin data access.

## Sprint 1 — architectural proof

**Goal: display a correct 90-day CTL / ATL / TSB chart in Home Assistant.**

Do only what is necessary to prove the data path:

1. historical Garmin activities
2. normalize `ActivityMetrics`
3. calculate one canonical daily training-load series
4. fill rest days with zero load
5. calculate CTL / ATL / TSB
6. import/store historical statistics
7. expose current CTL / ATL / TSB entities
8. build one chart proof-of-concept
9. test restart/reload
10. compare recalculated history

Do not start Insights, race predictions, composite Fitness Score, or a large dashboard before this works.

If the 90-day CTL/ATL/TSB chart survives a restart, an incremental Garmin sync, and a full recalculation without historical drift, the foundation is considered proven.
