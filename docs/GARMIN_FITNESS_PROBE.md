# Garmin Fitness — History Probe

The history probe is a read-only development tool for validating real Garmin
history before the project locks its canonical Training Load source.

It answers four questions:

1. Does Garmin's activity date-range request work against the real account?
2. How often is `activityTrainingLoad` available?
3. How often do activities contain the HR/duration inputs required for TRIMP?
4. Do those activity days also have strict historical resting-HR data?

It can optionally calculate complete Garmin Load and TRIMP Training series for
comparison.

## Safety properties

`examples/fitness_history_probe.py`:

- does **not** perform Garmin login
- does **not** write or edit Garmin data
- only accepts an already-existing `ha-garmin` token file
- uses `GarminHistoryClient`, so historical requests have no previous-day
  fallback
- never auto-selects Garmin Load or TRIMP
- never infers max HR or sex

## Important Home Assistant note

The current `home-assistant-garmin_connect` integration does **not** persist its
DI credentials as `.garmin_tokens.json`. It stores token, refresh token and
client ID in the Home Assistant config entry and reconstructs one shared
`GarminAuth`/`GarminClient` in memory.

Therefore do **not** create a second Garmin login/token file merely to run this
probe in a Home Assistant installation. That would violate the Garmin Fitness
architecture goal of using the existing integration authentication.

The standalone script is useful where an existing `ha-garmin` token file
already exists. For the Home Assistant project, the final live probe should be
invoked from a future `FitnessCoordinator`/diagnostic path using the integration's
already-authenticated client.

## Standalone usage

When an existing token file is available:

```bash
python examples/fitness_history_probe.py \
  --token-path /path/to/.garmin_tokens.json \
  --days 90
```

Machine-readable output:

```bash
python examples/fitness_history_probe.py \
  --token-path /path/to/.garmin_tokens.json \
  --days 90 \
  --json
```

## Optional full TRIMP calculation

TRIMP additionally requires a user max HR and the Banister sex constant.
They are deliberately explicit inputs in v1.

```bash
python examples/fitness_history_probe.py \
  --token-path /path/to/.garmin_tokens.json \
  --days 90 \
  --max-hr 180 \
  --sex male \
  --json
```

Use the actual configured values for the user. Do not substitute daily maximum
heart rate for user max HR.

Supplying only one of `--max-hr` / `--sex` is an error.

## Output

The JSON report contains:

```text
algorithm_version
range

garmin_load
trimp_activity_inputs
trimp_history_context
resting_hr_measurements
by_activity_type

garmin_load_incomplete_days

training.garmin
training.trimp

trimp_configuration
notes
```

When a source is complete, its Training payload contains one row per day:

```text
date
daily_load
ctl
atl
tsb
acwr
ramp_rate
```

ACWR begins only after a complete 28-day chronic window. Ramp rate begins after
7 days. Earlier unavailable values remain `null`; they are not fake zeros.

## Interpreting coverage

### Garmin Load

100% means every historical Garmin activity in the requested window includes
`activityTrainingLoad`.

Less than 100% means at least one activity day cannot safely be used for a pure
Garmin-Load CTL/ATL series unless Garmin later supplies the missing value.

### TRIMP activity inputs

An activity is eligible when it has:

- positive duration
- average heart rate

This does not by itself make the day fully TRIMP-ready.

### TRIMP history context

An activity day is fully eligible when:

- every activity that day has average HR + duration
- Garmin provides resting HR for that calendar day

A complete TRIMP calculation still needs explicit max HR and sex.

## Source-selection rule

The probe is diagnostic only.

Never create a hybrid daily series such as:

```text
Garmin Load when present
TRIMP when Garmin Load is missing
```

The two load values are not guaranteed to share a scale. CTL/ATL/TSB must be
built from one homogeneous canonical load source.

The source decision is made only after reviewing real-account coverage and the
resulting behavior of both complete candidate series.

## Expected first real test

For this project the initial target is 90 days.

Given the intentionally low recent training volume, visually exciting numbers
are **not** the success criterion. Success means:

- correct activity count
- correct local calendar-day grouping
- truthful missing-data diagnostics
- continuous zero-filled real rest days
- reproducible derived metrics

A nearly flat graph is allowed. A confidently wrong graph is not. 😄
