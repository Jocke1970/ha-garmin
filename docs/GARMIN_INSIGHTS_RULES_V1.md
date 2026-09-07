# Garmin Insights — Rules V1

**Status:** deterministic library rule layer  
**Branch:** `feature/garmin-insights-v1`  
**Ruleset version:** `1`

## Purpose

Rules V1 turns one immutable `InsightSnapshot` into zero or more stable
`InsightResult` records. The rule layer is pure: it performs no Garmin API calls,
reads no Home Assistant entity state, and does not modify Fitness calculations.

This is a transparent heuristic layer for training/recovery context. Thresholds
are implementation heuristics to validate and tune against real account data;
they are not medical limits and do not claim to predict injury or illness.

## Readiness source semantics

`DailyRecoveryMetrics` keeps regular Training Readiness and Garmin's
`AFTER_WAKEUP_RESET`/morning Training Readiness as separate normalized fields.
The strict recovery layer never rewrites one source as the other.

For a current-day Insight snapshot, readiness coverage is considered available
when either exact-date source is present. Rules prefer regular Training Readiness
when available and otherwise use exact-date morning Training Readiness. Evidence
keeps that provenance explicit through `training_readiness_*` versus
`morning_training_readiness_*` codes.

This avoids treating a normal current Garmin payload as incomplete merely because
only the after-wakeup record exists, while still preserving the source boundary.

## Output contract

Each result contains:

- stable `id`
- `severity`: `positive`, `info`, `caution`, or `warning`
- numeric `priority`
- `confidence`: `low`, `medium`, or `high`
- `title_key` and `message_key` for presentation/translation
- machine-readable `evidence`
- `ruleset_version`

`ha-garmin` deliberately does not own final user-facing prose. The Home Assistant
adapter can translate the stable keys while keeping rule semantics testable and
presentation-independent.

## V1 rules

### `insufficient_or_stale_data`

Priority 100. Emitted when the snapshot's conservative global quality flag is not
complete. Evidence identifies stale fields, missing source groups and missing
fields. This result does not automatically block rules whose own required input
subset is still current and complete.

### `load_spike`

Priority 95. Requires a ready canonical Training snapshot and ACWR.

- ACWR >= 1.5: caution
- ACWR >= 1.8: warning
- positive Ramp Rate and ATL > CTL are supporting evidence

The rule consumes the existing canonical ACWR/Ramp/CTL/ATL values; it does not
recalculate them.

### `recovery_caution`

Priority 90. Requires current recovery data and at least two independent negative
signals. Candidate signals are:

- current Training Readiness < 40 (regular preferred, otherwise morning)
- Sleep Score < 60
- Body Battery < 30
- average stress > 50
- Recovery Time > 24 hours
- resting HR >= 5 bpm above the Garmin 7-day average
- HRV below the balanced baseline, or Garmin HRV status `LOW`/`UNBALANCED`

Four or more signals, or current readiness < 20, raises severity to warning.
Multiple signals are required so one noisy metric does not generate a recovery
warning by itself.

### `low_recent_load`

Priority 45. Requires a ready Training snapshot, established CTL > 0 and ACWR <=
0.5. ACWR alone is intentionally insufficient; V1 also requires a declining Ramp
Rate and/or a sparse seven-day activity window (one or fewer activities).

### `load_focus_imbalance`

Priority 40. Uses the snapshot's recent activity window, normally seven days.
At least three activities are required. Every activity must have complete Training
Effect coverage; otherwise the rule refuses to infer a distribution.

The canonical Fitness Training Effect contribution helper supplies low-aerobic,
high-aerobic and anaerobic buckets. A bucket is considered dominant when it is at
least 1.5 times the sum of the other buckets, or when it is the only non-zero
bucket.

### `favourable_training_signal`

Priority 30. Requires current recovery data, current Training Readiness >= 70
(regular preferred, otherwise morning) and Sleep Score >= 75, plus at least one
additional positive signal from HRV, Body Battery, or resting HR relative to its
7-day average.

This is deliberately a positive context signal, not a prescription for a specific
workout.

## Conflict policy

Results are sorted by descending priority and then stable rule ID.

`load_spike` or `recovery_caution` suppresses `favourable_training_signal` so a
positive readiness message cannot conflict with a stronger caution/warning.
Independent observations such as low recent load or load-focus imbalance may
coexist.

## Scope guard

Rules V1 changes no:

- TRIMP / CTL / ATL / TSB formula
- ACWR or Ramp Rate formula
- Strain or Load Focus formula
- Garmin Gear behavior
- Garmin authentication/session behavior
- Home Assistant entity or Lovelace code

The next stage is Home Assistant orchestration: create the current
`InsightSnapshot`, evaluate Rules V1, expose stable results, and validate them on
real account data before treating the V1 thresholds as settled.
