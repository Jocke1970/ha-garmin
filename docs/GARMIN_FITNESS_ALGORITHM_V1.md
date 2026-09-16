# Garmin Fitness — Training Algorithm v1

> Algorithm version: `1`  
> Scope: Training engine only  
> Status: implementation baseline for Sprint 1

This document defines the exact semantics associated with
`GARMIN_FITNESS_ALGORITHM_VERSION = 1`.

Changing any behavior that materially changes historical output requires either:

- an explicit algorithm-version bump, or
- a documented bug fix with a deliberate history rebuild/migration decision.

The purpose is to prevent old and new calculations from being silently mixed in
Home Assistant long-term statistics.

---

## 1. Canonical load source

A Training series uses exactly one homogeneous source:

```text
garmin
```

or:

```text
trimp
```

Never mix values from the two sources within one CTL/ATL/TSB history.

### Garmin source

Per-activity input:

```text
activityTrainingLoad
```

Daily load:

```text
sum(activityTrainingLoad for all activities on local Garmin calendar day)
```

A real rest day has load `0`.

An activity day where one or more activities lack `activityTrainingLoad` is
**incomplete**. It is not silently treated as zero and no downstream Training
series is generated from the incomplete window.

### TRIMP source

Per-activity input:

- duration in minutes
- average HR
- resting HR for the local Garmin calendar day
- configured user max HR
- Banister sex constant

A real rest day has load `0`.

An activity day with missing required input is incomplete.

---

## 2. Local training day

Activity grouping uses Garmin's local calendar date.

Priority:

1. explicit Garmin `calendarDate`
2. date component of `startTimeLocal`
3. exact start timestamp date as fallback

The exact activity timestamp remains based on Garmin GMT/UTC data when
available.

Example:

```text
startTimeLocal = 2026-09-01 00:30
startTimeGMT   = 2026-08-31 22:30
```

Training day:

```text
2026-09-01
```

not `2026-08-31`.

---

## 3. Activity deduplication

Identity:

```text
Garmin activityId
```

When duplicate records for the same activity ID exist, v1 keeps the copy with
more calculation-relevant populated fields rather than blindly keeping the
first page result.

This protects backfill from Garmin propagation delays where a newly synced
activity can appear before fields such as Training Load or Training Effect are
fully populated.

---

## 4. Banister TRIMP

Heart-rate reserve ratio:

```text
HRR = (average_hr - resting_hr) / (user_max_hr - resting_hr)
```

v1 clamps HRR to:

```text
0.0 <= HRR <= 1.0
```

TRIMP:

```text
TRIMP = duration_minutes * HRR * exp(k * HRR)
```

Constants:

```text
male   k = 1.92
female k = 1.67
```

Invalid configuration:

```text
user_max_hr <= resting_hr
```

raises an error.

Missing average HR or non-positive duration returns missing/ineligible input,
not zero TRIMP.

A physiologically clamped zero-intensity activity can legitimately return
TRIMP `0.0`.

---

## 5. CTL — Chronic Training Load

Period:

```text
42 days
```

EMA alpha:

```text
alpha_ctl = 2 / (42 + 1)
```

Recurrence:

```text
CTL_today = alpha_ctl * load_today
          + (1 - alpha_ctl) * CTL_yesterday
```

Initialization:

```text
CTL_first_day = load_first_day
```

This initialization matches the PulseCoach reference behavior reviewed during
v1 design.

---

## 6. ATL — Acute Training Load

Period:

```text
7 days
```

EMA alpha:

```text
alpha_atl = 2 / (7 + 1)
```

Recurrence:

```text
ATL_today = alpha_atl * load_today
          + (1 - alpha_atl) * ATL_yesterday
```

Initialization:

```text
ATL_first_day = load_first_day
```

---

## 7. TSB — Training Stress Balance

```text
TSB = CTL - ATL
```

Interpretation is deliberately kept outside the mathematical primitive.

The engine calculates the number. User-facing labels such as fatigued/fresh are
an Insights/UI concern and can evolve without rewriting historical TSB values.

---

## 8. ACWR

v1 uses rolling averages:

```text
acute   = average(daily load, last 7 days)
chronic = average(daily load, last 28 days)

ACWR = acute / chronic
```

A chronic average of zero produces:

```text
ACWR = None
```

not infinity.

### Full-window rule

Garmin Fitness v1 intentionally emits no ACWR until a full 28-day chronic
window exists.

Therefore, for a newly backfilled series:

```text
days 1-27: ACWR unavailable
day 28+:   ACWR available when chronic load > 0
```

PulseCoach can calculate using shorter partial history at the beginning of a
series. Garmin Fitness deliberately differs here because an apparent workload
ratio based on only a few chronic-history days is easier to misinterpret.

---

## 9. Ramp rate

Ramp rate is the absolute CTL change over seven calendar days:

```text
ramp_rate_today = CTL_today - CTL_7_days_ago
```

It becomes available after seven prior days exist.

No qualitative risk label is part of this primitive.

---

## 10. Load focus

Load focus is independent of the selected canonical load source.

It uses Garmin Training Effect:

```text
average_aerobic_TE
average_anaerobic_TE
```

Classification with dominance ratio `1.5`:

```text
if aerobic > anaerobic * 1.5:
    aerobic
elif anaerobic > aerobic * 1.5:
    anaerobic
else:
    mixed
```

If no usable aerobic/anaerobic Training Effect pairs exist:

```text
unknown
```

Activities missing either Training Effect value are excluded from the average
and make the summary incomplete. Missing values are never converted to zero.

This v1 design mirrors the conceptual PulseCoach load-focus rule rather than
weighting focus categories by Garmin Training Load.

---

## 11. Strain score

Strain is a TRIMP-derived user-facing metric and is not automatically the
canonical CTL/ATL load value.

Formula:

```text
strain = 21 * (1 - exp(-TRIMP / personal_trimp_max))
```

Bounds:

```text
0 <= strain <= 21
```

Default:

```text
personal_trimp_max = 250
```

Example test vector:

```text
TRIMP = 250
personal_trimp_max = 250
strain = 13.27
```

---

## 12. Personal TRIMP-max calibration

Personal calibration does not activate until at least:

```text
30 positive-TRIMP sessions
```

After that:

```text
personal_trimp_max = max(historical positive TRIMP) * 1.2
```

Before enough sessions exist, calibration returns missing and callers should use
the documented default rather than pretending sparse history is personalized.

---

## 13. Consecutive hard days

Default hard-day threshold:

```text
strain > 14
```

The helper counts consecutive hard days backward from the newest supplied day
and stops on the first non-hard day.

This is intended as an input for later Insights, not as a medical or injury-risk
diagnosis.

---

## 14. Missing-data policy

The engine distinguishes these cases explicitly.

### Real rest day

```text
activity_count = 0
load = 0
complete = true
```

### Activity day with missing canonical-load input

```text
activity_count > 0
load = None
complete = false
```

### Garmin API failure

No new historical value should be manufactured. The Home Assistant adapter must
preserve previously valid statistics.

### Missing early-window metric

Examples:

```text
ACWR before day 28
Ramp Rate before day 8
```

represented as unavailable, not zero.

---

## 15. Completeness gate

CTL/ATL/TSB and downstream Training metrics are calculated only when the
requested daily-load window is complete and contains consecutive dates.

If any activity day is incomplete:

```text
assessment.ready = false
assessment.incomplete_days = (...)
training_points = ()
acwr_points = ()
ramp_rate_points = ()
```

The engine fails closed rather than outputting a plausible but underestimated
fitness curve.

---

## 16. Source diagnostics

Before source selection, v1 compares:

### Garmin

```text
activities with activityTrainingLoad / total activities
```

### TRIMP activity inputs

```text
activities with average HR + positive duration / total activities
```

### TRIMP history context

An activity day is fully eligible when:

```text
all activities have HR + duration
AND historical resting HR exists for that local date
```

The comparison deliberately does not auto-select a winner.

Max HR and sex remain explicit configuration if TRIMP becomes canonical.

---

## 17. Resting-HR history

v1 uses Garmin's historical user-stats wellness endpoint with:

```text
metricId = 60
metric key = WELLNESS_RESTING_HEART_RATE
```

The entire requested date range can be fetched in one request.

Missing dates remain missing. No neighboring-day fallback is allowed.

---

## 18. Persistence contract

The pure Training engine does not import Home Assistant.

It exports daily rows containing:

```text
date
daily_load
ctl
atl
tsb
acwr
ramp_rate
```

The Home Assistant integration owns:

- sensor entities
- statistic IDs
- Recorder long-term-statistics import
- backfill state
- algorithm migration/rebuild orchestration

Every persisted history generation must record at least:

```text
algorithm_version = 1
load_source = garmin | trimp
```

---

## 19. Version-bump examples

Likely requires algorithm v2:

- changing CTL/ATL periods
- changing EMA initialization
- changing TRIMP constants/formula
- changing ACWR to EWMA ACWR
- changing full-window ACWR semantics
- changing canonical daily aggregation semantics

May not require v2:

- adding a dashboard card
- adding translations
- changing explanatory Insights wording
- fixing a parser without changing previously valid mathematical output

When uncertain, prefer a version bump plus explicit history rebuild over silently
mixing incompatible historical calculations.
