# Garmin Fitness current status

> Updated: 2026-09-14  
> Active integrated branch: `feature/garmin-fitness`  
> Current integrated commit: `c5c2d7e62bb7d9d311c11200ab325f435a2da5c9`

This document is the concise current-state companion to the older roadmap and
design/audit documents. The roadmap remains useful historical design context,
but several milestones described there as future work are now implemented.

## Architecture status

The production/development boundary is established:

```text
Garmin Connect
  ↓
ha-garmin
  ├─ strict historical fetch / normalization
  ├─ canonical TRIMP Training calculations
  ├─ Insights V1 rules
  ├─ Activity Evaluation
  └─ Daily Load Budget policy
  ↓
home-assistant-garmin_connect
  ├─ coordinator lifecycle / caching
  ├─ entities / selectors
  ├─ Recorder statistics import
  └─ localized presentation / Lovelace handoff
```

`ha-garmin` owns calculation semantics. Home Assistant must not maintain a second
implementation of the same formulas or policy logic.

## Canonical Training engine — frozen semantics

The current canonical load source is TRIMP.

Core calculations remain intentionally stable:

- CTL: 42-day EMA
- ATL: 7-day EMA
- TSB: CTL - ATL
- ACWR: 7-day acute / 28-day chronic rolling averages
- Ramp Rate: CTL today minus CTL seven days ago
- Strain: bounded 0-21 transform from canonical TRIMP
- Load Focus: low aerobic / high aerobic / anaerobic split from Garmin Training
  Effect

No Daily Load Budget work may silently redefine those metrics.

## Strict history and normalization behavior

Implemented reliability rules include:

- strict exact-date historical access
- zero-filled genuine rest days
- incomplete activity days remain incomplete instead of becoming zero
- exact-current-day RHR fallback from Garmin daily summary when historical RHR
  propagation lags
- Garmin activity-ID deduplication preferring the richer record
- narrow cross-service shadow suppression when an incomplete record represents a
  complete matching workout
- repeated shadow-session cluster suppression: all complete matching workouts are
  preserved; any number of incomplete matching shadows can be removed

The last rule was added after live history exposed multiple MyFitnessPal copies
of the same cycling session with distinct Garmin activity IDs.

## Insights V1

Insights V1 is merged into `feature/garmin-fitness`.

The engine provides:

- exact-date `DailyRecoveryMetrics`
- immutable `InsightSnapshot`
- explicit `InsightDataQuality`
- deterministic `InsightResult`
- stable evidence codes and thresholds
- strict stale/missing-data handling

Rules V1 currently covers:

- `insufficient_or_stale_data`
- `load_spike`
- `recovery_caution`
- `low_recent_load`
- `load_focus_imbalance`
- `favourable_training_signal`

Regular Training Readiness and Morning Training Readiness are kept separate.
Snapshot completeness accepts either exact-date readiness source; rule evidence
preserves which source was actually used.

A source availability flag means the exact-date endpoint responded, not that every
field is populated. `missing_sources`, `missing_fields`, and `stale_fields` are
the authoritative data-quality explanation.

## Activity Evaluation

Activity Evaluation is merged and presentation-neutral.

It can:

- evaluate recent normalized activities
- classify Training Effect conservatively
- use activity-detail power samples when available
- calculate best mean power windows
- estimate cycling VO2max from supported power/body-weight inputs
- estimate FTP from a valid 20-minute power window
- expose confidence and provenance

FTP is intentionally unavailable for activities shorter than the required power
window. Estimates are not represented as Garmin-native or laboratory values.

## Daily Load Budget V1

Budget V1 is merged and remains the authoritative policy exposed to Home
Assistant.

It simulates today's total canonical TRIMP and finds the most conservative
structural ceiling across:

- ACWR (`1.30` normal hard limit)
- Strain
- TSB
- Ramp Rate

Recovery Insights can reduce remaining capacity; favourable signals never raise
the structural ceiling.

The policy is advisory. It is not a medical, injury, or overtraining guarantee.

### Known V1 policy limitation

Live observation confirmed a low-chronic-load edge case: current ACWR can remain
well above `1.30` after several rest days even while TSB, Ramp, and Strain have
otherwise normalized. Because V1 treats ACWR as a hard structural constraint, it
can continue returning zero remaining budget.

This is considered a policy limitation, not a defect in the canonical ACWR
formula.

## Daily Load Budget V2 preview

An isolated experiment lives on:

```text
experiment/daily-budget-v2-preview
```

It is deliberately not exported from the public Fitness package API and is not
wired into Home Assistant.

The preview keeps V1 unchanged in normal conditions. A conservative `reentry`
mode is considered only when V1 has zero capacity solely because the current
ACWR is already above the normal limit.

Re-entry requires:

- TSB >= 0
- Ramp Rate <= 0
- no `recovery_caution`
- no `insufficient_or_stale_data`

When eligible, capacity is bounded by:

- light Strain ceiling `4.0`
- existing V1 TSB floor
- existing V1 Ramp ceiling
- projected ACWR no more than 5% above the already-high current ACWR

The preview branch passed formatting, Ruff, mypy, tests on Python 3.11/3.12/3.13,
and package build. It remains a live-validation experiment; no promotion decision
has been made.

## Branch hygiene

Completed feature/fix branches were removed after their PRs had been merged.
Current intentional branches are:

```text
main
feature/garmin-fitness
feature/garmin-insights-audit
experiment/daily-budget-v2-preview
```

`feature/garmin-insights-audit` remains as historical/reference material. The V2
preview branch is active experimental work. `feature/garmin-fitness` is the
integrated development line.

## Current next step

Continue observing Budget V1 and V2 preview side by side across natural live
states. Do not alter the canonical Training formulas during that validation.

If V2 consistently avoids the binary high-ACWR deadlock without becoming too
permissive, the next deliberate change should be:

1. formalize V2 policy semantics and regression vectors in `ha-garmin`;
2. merge the policy into `feature/garmin-fitness`;
3. pin the merged library commit in `home-assistant-garmin_connect`;
4. expose any new policy/provenance fields without changing existing Fitness
   entity semantics.
