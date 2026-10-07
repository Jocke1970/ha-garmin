# Garmin Fitness current status

> Updated: 2026-10-07  
> Library version: `0.1.40`  
> Active release flow: `dev → beta → main`  
> Current beta consumer: Garmin Connect `2026.10.0b2`

This is the concise source of truth for the currently deployed Garmin Fitness
runtime. Older roadmap, Sprint 1, algorithm-v1 and preview documents remain
historical design records unless explicitly stated otherwise.

## Architecture

```text
Garmin Connect
  ↓
ha-garmin
  ├─ Garmin API/auth-adjacent client behavior
  ├─ normalization
  ├─ activity-type registry
  ├─ activity-driven Gear cache
  ├─ canonical Fitness calculations
  ├─ Insights rules
  ├─ Activity Evaluation helpers
  └─ Daily Load Budget base policy
  ↓
home-assistant-garmin_connect
  ├─ coordinators / lifecycle / caching
  ├─ entities / selectors
  ├─ Recorder long-term statistics
  ├─ planning-only Load Priority adapter
  └─ localized/presentation frontend
```

`ha-garmin` owns calculation semantics. Home Assistant must not maintain a
second implementation of the same Training formulas.

## Canonical Training engine

Canonical source: **Banister TRIMP**.

Current algorithm:

```text
GARMIN_FITNESS_ALGORITHM_VERSION = 2
```

Algorithm v2 fixes the Banister TRIMP scale by applying both the sex-specific
multiplicative coefficient and exponential coefficient:

```text
male:   duration_minutes × HRR × 0.64 × exp(1.92 × HRR)
female: duration_minutes × HRR × 0.86 × exp(1.67 × HRR)
```

The canonical Training history does not mix Garmin Training Load, power TSS,
pace proxy and TRIMP.

Real Home Assistant validation after the v2 rebuild showed the expected male
profile correction from 84.0 TRIMP to 53.8 TRIMP for the same day.

## Current Training semantics

- history display: commonly 90 days in the frontend
- calculation context: 180 days with warm-up recovery support
- CTL: 42-day EMA
- ATL: 7-day EMA
- TSB: CTL - ATL
- ACWR: 7-day acute / 28-day chronic
- Ramp Rate: 7-day change
- Strain: calibrated against personal TRIMP history
- Load Focus: Garmin Training Effect source

Missing activity-day inputs remain explicit; incomplete canonical history must
not be silently converted to zero load.

## Load Priority and budget

Load Priority is used for **planning classification**, not to rewrite canonical
history.

The Home Assistant adapter currently exposes planning policy v2:

```text
planning_mode = load_priority
planning_policy_version = 2
```

A clearly low-intensity activity can be excluded from today's finite planning
budget while its actual TRIMP remains in Training history.

Source-specific values keep their own units. Power TSS, Garmin Load and pace
proxy values are not summed into TRIMP.

## Insights

Insights Rules V1 remain deterministic. The Home Assistant layer localizes the
presentation but does not change rule ordering, evidence or thresholds.

Important current examples include:

- load spike
- recovery caution
- load-focus imbalance
- insufficient/stale source data

Evidence is intentionally machine-readable so the frontend can visualize why a
rule fired.

## Activity-linked Gear

The activity/Gear cache is owned by the Garmin client layer.

The latest activity now exposes:

```text
linked_gear
linked_gear_count
```

with compact normalized fields such as Gear UUID, display name, Gear type,
brand, model and custom make/model.

This path was live-verified through Garmin Connect `2026.10.0b2`.

## Release hygiene

Only these long-lived branches are canonical:

```text
dev
beta
main
```

Feature/fix/experiment branches are temporary. Useful work must be merged into
`dev`, promoted through `beta`, validated in real Home Assistant where
applicable, and then the side branch should be removed.

## Current next steps

No canonical Training formula change is planned.

Near-term work is presentation/polish:

- visualize Insights evidence in the Garmin Fitness dashboard
- continue Gear UI polish
- normalize cosmetic Gear display quirks where useful
- soak-test beta before stable promotion
