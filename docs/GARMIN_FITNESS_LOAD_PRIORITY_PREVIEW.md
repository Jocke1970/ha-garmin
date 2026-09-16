# Garmin Fitness — Load Priority preview (2026-09-16)

**Status: experimental, read-only, not integrated into Home Assistant.**

Branch: `experiment/fitness-load-priority-preview`, based on the HA-pinned `ha-garmin` commit `c5c2d7e62bb7d9d311c11200ab325f435a2da5c9`.

## Purpose

Choose one load measurement per **completed activity**, using a configurable priority order **per sport** with a clear fallback when required data is missing. This takes inspiration from the Load Priority workflow the user described in Intervals.icu; it does **not** claim that the service automatically switches from HR to power when intensity changes. Intensity-based selection within one sport is a separate, unimplemented design decision.

## Preview API

`ha_garmin.fitness.load_priority_preview.preview_activity_load(activity, *, profiles=None, resting_hr=None, user_max_hr=None, sex=None, ftp_watts=None, threshold_speed_mps=None, override=None)`

Accepts the existing normalized `ActivityMetrics` model and returns a frozen `ActivityLoadPreview` containing the sport, priority, selected method, calculated value, **unit**, attempted methods and explicit reasons for any missing source. A manual `override` disables fallback rather than quietly changing to another source.

Preview defaults (user-editable via `profiles`; NOT deployed preferences):

| Sport family | Load priority |
| --- | --- |
| Walking / hiking | HR → pace → Garmin |
| Cycling (including virtual/indoor) | Power → HR → pace → Garmin |
| Running | Pace → HR → power → Garmin |
| Rowing | Power → HR → Garmin |
| Strength | Garmin → HR |
| Other | Garmin → HR |

The first usable method wins. Zero Garmin Load is valid; missing values are **not** coerced to zero. Each unsupported source is reported in `attempts` (e.g., missing FTP, invalid power, missing resting HR). Unsupported activity types use `other` rather than guessing a measurement from their name.

## Data and units — DO NOT MIX

- **HR**: existing Banister TRIMP calculation with the actual activity's average HR, date-specific resting HR, personal maximum HR, sex and duration. Unit: `banister_trimp`.
- **Power**: preview power TSS = duration hours × (normalized power / FTP)² × 100. Requires normalized power **and** explicit FTP. Average power is deliberately not silently substituted: intervals would be understated. Unit: `power_tss`.
- **Pace**: EXPERIMENTAL speed proxy = duration hours × (mean speed / supplied threshold speed)² × 100. Requires distance, duration and an explicit threshold speed. It ignores terrain, elevation, wind and variation within the session. Unit: `pace_proxy_unvalidated`. It is **not** validated running TSS and is not safe to use for training recommendations.
- **Garmin**: Garmin's supplied `activityTrainingLoad` unchanged; unit: `garmin_training_load`.

Values from these four methods are not on a common scale. The selector **must not** sum them into daily TRIMP, silently replace Garmin Load, rebuild CTL/ATL/TSB/ACWR/Ramp/Strain, or feed the Daily Load Budget. Every `ActivityLoadPreview` has `canonical_compatible=False`. No production pipeline, HA manifest/pin, public API, entity or Lovelace file was modified.

## Example review

For a 30-minute walking activity with HR 105 bpm, resting HR 48, max HR 185 and Garmin Load 14.4, the preview picks **HR** if its context is provided, even if a power field is present. The result is Banister TRIMP, **not** Garmin Load 14.4; comparing those numbers as if they were the same unit is invalid.

For cycling with normalized power 180 W and FTP 200 W for 30 minutes, power TSS = 40.5. If FTP is unavailable, the next eligible method is HR (if HR context is complete). An explicitly forced `power` selection with missing FTP returns unavailable and does not fall back.

## Outstanding gates before any production release

1. Verify real Garmin activity fields (normalized power availability, source/device metadata, date-specific resting HR, FTP and pace thresholds) without exposing secrets or serials.
2. Decide with the user whether sport priority alone suffices or an *optional* intensity rule should override the first usable method. Do not classify a pass as low-intensity from the sport name alone.
3. Develop and validate a single calibrated load scale across HR/power/pace, or keep source-specific load histories; compare against actual sessions and ensure no double counting.
4. Explicitly define how changing priority affects historical statistics; no silent backfill or migration. Missing data must remain unknown, not zero.
5. Address the **separate** budget problem: V1's hard ACWR cap can return zero additional TRIMP even after a light walk. Display zero budget as an estimate about *additional training load*, not a prohibition on everyday movement. Budget V2 remains isolated.
6. Add real-data replay and regression tests, then review any HA configuration UX and the frontend's unrelated configuration error before deployment.

Run preview tests: `pytest -q tests/test_fitness_load_priority_preview.py`.
