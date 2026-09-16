# Garmin Fitness — M0 Historical API Audit

> Branch: `feature/garmin-fitness`  
> Status: initial code-level audit complete; live Garmin validation still required

## Purpose

Identify which historical Garmin data capabilities already exist in `ha-garmin`, which methods are safe for historical backfill, and which gaps must be filled before Sprint 1.

## Executive summary

`ha-garmin` is already much closer to supporting Garmin Fitness than expected.

Most daily wellness/training metrics already accept an arbitrary date. The main Sprint 1 gap is **activity retrieval by date range**.

A second, more subtle issue is important: the existing grouped coordinator helpers (`fetch_core_data()` and `fetch_training_data()`) are designed for current Home Assistant sensor display and intentionally fall back to the previous day when today's Garmin data is not ready. That behaviour must **not** be used during historical backfill.

Historical import therefore needs a strict no-fallback path.

---

## Existing date-capable methods

### Core / wellness

| Method | Historical capability | Notes |
| --- | --- | --- |
| `_get_user_summary_raw(target_date)` | Yes, single day | Strict date request at API level |
| `_get_sleep_data_raw(target_date)` | Yes, single day | Strict date request at API level |
| `_get_hrv_data_raw(target_date)` | Yes, single day | Strict date request at API level |
| `get_daily_steps(start_date, end_date)` | Yes, range | Already ideal for history |
| `get_body_composition(target_date)` | Partial/derived | Internally searches a 30-day window ending on target date and may use latest fallback |
| `get_hydration_data(target_date)` | Yes, single day | Suitable where needed |
| `get_fitness_age(target_date)` | Yes, single day | Suitable where available |

### Training / fitness

| Method | Historical capability | Notes |
| --- | --- | --- |
| `get_training_readiness(target_date)` | Yes, single day | Returns regular readiness entry |
| `get_morning_training_readiness(target_date)` | Yes, single day | Filters `AFTER_WAKEUP_RESET` |
| `get_training_status(target_date)` | Yes, single day | Includes Garmin training status / VO2max-related data |
| `get_endurance_score(target_date)` | Yes, single day | `calendarDate` parameter |
| `get_hill_score(target_date)` | Yes, single day | `calendarDate` parameter |
| `get_power_to_weight(target_date)` | Yes, single day | FTP / power-to-weight data |
| `get_lactate_threshold()` | No date parameter | Treat as latest/episodic measurement, not daily history |

### Activities

| Method | Historical capability | Notes |
| --- | --- | --- |
| `get_activities(start, limit)` | Pagination only | Newest-first; no date range in current `ha-garmin` API |
| `get_activity(activity_id)` | Yes by ID | Activity summary |
| `get_activity_details(activity_id)` | Yes by ID | Detailed metrics/polyline |
| `get_activity_hr_in_timezones(activity_id)` | Yes by ID | HR-zone durations |

The existing activity trim already preserves many fields needed by Garmin Fitness, including:

- activity ID/type/time
- duration and distance
- average/max HR
- calories
- elevation
- cadence
- average/max/normalized power
- VO2max value
- aerobic/anaerobic Training Effect
- Garmin activity training load
- HR zones
- power zones
- selected running dynamics

This substantially reduces new Garmin parsing work for Sprint 1.

---

## Important historical-data rule: no fallback

### Existing current-state behaviour

`fetch_core_data(target_date)` contains a previous-day fallback when a daily summary is unavailable.

`fetch_training_data(target_date)` may also fall back to the previous day for:

- training status
- Endurance Score
- Hill Score
- HRV
- power-to-weight

This is appropriate for current Home Assistant display, especially around midnight when Garmin has not populated the new day yet.

### Historical backfill behaviour

Historical import must be strict:

```text
requested date 2026-08-15
        |
        +-- Garmin has value -> store value on 2026-08-15
        |
        +-- Garmin has no value -> store missing/None
```

Never:

```text
requested date 2026-08-15
Garmin has no value
        |
        v
copy 2026-08-14 value onto 2026-08-15
```

Therefore Garmin Fitness backfill must not call the fallback-oriented coordinator fetchers as its canonical source.

### Recommended solution

Add explicit strict-history helpers which call the raw/date-specific methods directly.

Possible shape:

```python
async def fetch_daily_history_day(self, target_date: date) -> dict[str, Any]:
    """Fetch exactly one historical day without previous-day fallbacks."""

async def fetch_training_history_day(self, target_date: date) -> dict[str, Any]:
    """Fetch exactly one historical training day without display fallbacks."""
```

A later range wrapper can iterate those safely with rate limiting/concurrency control.

---

## Activity date-range gap

Sprint 1 needs all activities in a fixed historical period, initially 90 days.

Current `ha-garmin` only exposes:

```python
get_activities(start=0, limit=10)
```

which is pagination by recency.

The upstream/reference `cyberjunky/python-garminconnect` project currently exposes `get_activities_by_date(startdate, enddate, activitytype=None, sortorder=None)`, demonstrating that Garmin's API can support this use case.

### Recommended addition

Add an equivalent typed/date-safe method to `ha-garmin`, using Python `date` values rather than forcing callers to format strings:

```python
async def get_activities_by_date(
    self,
    start_date: date,
    end_date: date | None = None,
    activity_type: str | None = None,
    sort_order: str | None = None,
) -> list[dict[str, Any]]:
    ...
```

Requirements:

- validate `start_date <= end_date`
- paginate until the requested range is exhausted
- protect against unbounded pagination
- retain Garmin activity IDs for deduplication
- return newest/oldest ordering explicitly/documentedly
- do not fetch expensive details for every activity unless required

For the Training MVP, the normal activity-list fields already contain most required load inputs. Detailed activity endpoints should remain lazy/on-demand.

---

## Body composition caveat

`get_body_composition(target_date)` is intentionally display-friendly: it searches a 30-day window ending on `target_date` and can fall back to the latest weigh-in.

That makes it inappropriate as a literal daily historical measurement source.

For Trends we should later expose actual measurement timestamps/records rather than expanding a single weigh-in across multiple calendar days.

This is not a Sprint 1 blocker.

---

## Lactate-threshold caveat

`get_lactate_threshold()` has no date argument in the current client.

Treat lactate threshold as an episodic/latest measurement unless a Garmin endpoint with measurement history is discovered and validated later.

Do not manufacture a daily series by repeatedly copying the latest value backward through history.

This is not a Sprint 1 blocker.

---

## Sprint 1 minimum Garmin data

For the first CTL/ATL/TSB proof-of-concept, we do **not** need every Garmin Fitness metric.

Minimum activity fields:

```text
activityId
startTimeGMT / normalized startTime
duration
activityType
averageHR
maxHR
activityTrainingLoad
aerobicTrainingEffect
anaerobicTrainingEffect
vO2MaxValue (optional for later Fitness work)
```

Minimum daily context for TRIMP fallback:

```text
resting HR
user max HR / configured max HR
sex when sex-specific Banister constant is used
```

If Garmin `activityTrainingLoad` is sufficiently populated and stable across sports, it should be evaluated as the first canonical load source before choosing TRIMP as the default.

Do not mix Garmin activity load and TRIMP values inside one CTL/ATL time series.

---

## Proposed new API surface

### Required for Sprint 1

```python
get_activities_by_date(start_date, end_date, ...)
```

### Strongly recommended for historical correctness

```python
fetch_daily_history_day(target_date)
fetch_training_history_day(target_date)
```

### Later convenience wrappers

```python
fetch_daily_history(start_date, end_date)
fetch_training_history(start_date, end_date)
fetch_activity_history(start_date, end_date)
```

The range wrappers should be designed with Garmin rate limits in mind and should support resumable backfill at the Home Assistant layer rather than attempting hundreds of concurrent API calls.

---

## M0 decisions from audit

### Locked

- `ha-garmin` remains the single Garmin authentication/API layer.
- Existing date-specific Garmin methods should be reused rather than duplicated.
- Coordinator-style previous-day fallbacks are forbidden for historical backfill.
- Activity history needs a date-range API.
- Historical missing physiological values remain missing; they are not copied from adjacent dates.
- A no-activity day is explicitly represented as training load `0`.
- Garmin-native load and calculated TRIMP remain distinguishable.

### Still to validate live

- [ ] maximum practical date span for Garmin activity-date queries
- [ ] pagination behaviour/order of the activity date-range endpoint
- [ ] historical availability depth for Training Readiness
- [ ] historical availability depth for Training Status
- [ ] historical availability depth for HRV
- [ ] historical availability depth for Endurance/Hill Score
- [ ] percentage of recent activities containing `activityTrainingLoad`
- [ ] whether activity load is sufficiently comparable across cycling, rowing, walking, and strength activities for the intended CTL/ATL model

---

## M0 status

### Code audit

- [x] audit current Garmin endpoints relevant to Training/Fitness
- [x] identify date-capable daily/training methods
- [x] identify grouped-fetch fallback hazard
- [x] identify activity-date-range gap
- [x] identify lactate-threshold/body-composition historical caveats

### Remaining before M0 is fully closed

- [ ] implement and test `get_activities_by_date()`
- [ ] decide exact normalized `ActivityMetrics` model
- [ ] decide exact normalized `DailyMetrics` model
- [ ] add sanitized fixtures
- [ ] live-test historical Garmin availability on the target account

## Recommended next code task

**Implement `GarminClient.get_activities_by_date()` with unit tests.**

This is the smallest missing piece that directly unlocks the 90-day Training MVP.
