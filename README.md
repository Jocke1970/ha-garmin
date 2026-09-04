# ha-garmin

Python client for Garmin Connect API, designed for Home Assistant integration.

## Features

- **Native Garmin Connect API** integration
- **Robust authentication** with multiple login strategies and automatic fallbacks
- **MFA support** with automatic endpoint fallback
- **Token persistence** - save and restore sessions to avoid re-login
- **Automatic token refresh** - proactively refreshes before expiry
- **Retry with backoff** for rate limits (429) and server errors (5xx)
- **Midnight fallback** - automatically uses yesterday's data when today isn't ready yet
- **Coordinator-based fetch** - optimized data fetching for Home Assistant multi-coordinator pattern
- **Data transformations** - automatic unit conversions (seconds→minutes, grams→kg)
- **Dynamic activity type registry** - learns Garmin `typeId`/`typeKey`/`parentTypeId` from normal activity data and refreshes the canonical hierarchy on a 24-hour cache
- **Activity-driven Gear metadata** - maps recent activities to Gear with bounded/cached lookups instead of polling every Gear item

## Installation

```bash
pip install ha-garmin
```

Optional: install with improved browser UA generation:

```bash
pip install ha-garmin[ua]
```

## Usage

### Standalone script

Authentication is synchronous; data fetches run in a thread pool and are awaited.

```python
import asyncio
from datetime import date
from ha_garmin import GarminAuth, GarminClient, GarminMFARequired

# Auth is synchronous
auth = GarminAuth()

if not auth.load_session(".garmin_tokens.json"):
    try:
        auth.login("email@example.com", "password")
    except GarminMFARequired:
        mfa_code = input("Enter MFA code: ")
        auth.complete_mfa(mfa_code)
    auth.save_session(".garmin_tokens.json")

client = GarminClient(auth)


async def fetch_all():
    today = date.today()
    core_data     = await client.fetch_core_data(today)      # Steps, HR, sleep, stress
    body_data     = await client.fetch_body_data(today)      # Weight, body composition, fitness age
    activity_data = await client.fetch_activity_data(today)  # Activities, workouts
    training_data = await client.fetch_training_data(today)  # HRV, training status
    goals_data    = await client.fetch_goals_data()          # Goals, badges
    gear_data     = await client.fetch_gear_data()           # Gear, alarms, solar, devices


asyncio.run(fetch_all())
```

### Home Assistant integration

Set up auth during `async_setup_entry` and pass the client to your coordinators.

```python
from datetime import date, timedelta
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from ha_garmin import GarminAuth, GarminClient

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    auth = GarminAuth()

    token_path = hass.config.path(".storage/garmin_tokens.json")
    if not auth.load_session(token_path):
        # Initial login must have been completed via the config flow
        raise ConfigEntryAuthFailed("No valid Garmin session")

    client = GarminClient(auth)

    coordinator = GarminCoreCoordinator(hass, client)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    return True


class GarminCoreCoordinator(DataUpdateCoordinator):
    def __init__(self, hass: HomeAssistant, client: GarminClient) -> None:
        super().__init__(hass, logger=_LOGGER, name="Garmin core", update_interval=timedelta(minutes=15))
        self._client = client

    async def _async_update_data(self) -> dict:
        return await self._client.fetch_core_data(date.today())
```

## Coordinator Fetch Methods

Optimized methods that group related API calls for Home Assistant coordinators:

| Method | API Calls | Data Returned |
| ------ | --------- | ------------- |
| `fetch_core_data()` | 3 | Steps, distance, calories, HR, stress, sleep, body battery, SPO2 |
| `fetch_body_data()` | 3 | Weight, BMI, body fat, hydration, fitness age |
| `fetch_activity_data()` | 4+ | Activities, workouts, HR zones, polylines |
| `fetch_training_data()` | 7 | Training readiness, status, HRV, lactate, endurance/hill scores |
| `fetch_goals_data()` | 4 | Goals (active/future/history), badges, user level |
| `fetch_gear_data()` | 6+ | Gear items, stats, device alarms, solar intensity, devices, last sync |

> `fetch_gear_data()` also performs a best-effort activity-type hierarchy bootstrap when its 24-hour cache is stale. Normal recent activity fetches teach the registry at no additional API cost.
| `fetch_blood_pressure_data()` | 1 | Blood pressure measurements |
| `fetch_menstrual_data()` | 2 | Menstrual cycle data |
| `fetch_nutrition_data()` | 1 | Nutrition log: consumed macros, goals, per-meal breakdown |

## Gear and Activity Type Enrichment

`ha-garmin` enriches Gear from the existing Activity flow rather than polling every Gear item for history.

The dynamic Activity Type Registry stores Garmin's stable `typeId`, `typeKey`, and `parentTypeId` fields. It learns types for free from normal activity responses and uses Garmin's canonical activity-type hierarchy as a best-effort 24-hour cached bootstrap. This resolves Gear defaults such as `type_25` into stable keys such as `indoor_cycling` while still preserving the hierarchy in `defaultForActivityDetails`.

The Activity fetch also scans its current recent-activity window newest-to-oldest and calls `get_activity_gear(activity_id)` for activities whose Gear mapping is not already cached. Matching Gear receives a compact `lastActivity` payload containing the activity ID, name, type metadata, UTC start time, distance, and duration when available.

Request behaviour is intentionally bounded:

- activity-to-Gear results are cached per activity ID;
- after the recent window is primed, normal operation is roughly one additional Gear lookup when a new activity appears;
- the newest activity can retry an empty Gear association up to three times to allow Garmin propagation delay;
- older empty results are treated as stable after one lookup;
- auxiliary activity-type or Gear lookup failures do not fail the primary coordinator data.

The current Home Assistant integration uses a 10-activity recent window for bootstrap/backfill. Gear last used outside that window can therefore have historical usage statistics without a cached `lastActivity` until it is used again.

## Write / Action Methods

Methods for logging data back to Garmin Connect, suitable for Home Assistant services:

| Method | Description |
| ------ | ----------- |
| `add_nutrition_log(calories, carbs, protein, fat, name)` | Log a Quick Add nutrition entry (requires Connect+) |
| `set_hydration(value_in_ml)` | Log hydration intake |
| `set_blood_pressure(systolic, diastolic, pulse)` | Log a blood pressure measurement |
| `add_body_composition(weight, percent_fat, ...)` | Log weight / body composition via FIT upload |
| `create_activity(name, type, start, duration_min)` | Create a manual activity |
| `upload_activity(file_path)` | Upload a FIT / GPX / TCX file |
| `set_active_gear(activity_type, setting, gear_uuid)` | Set default gear for an activity type |
| `add_gear_to_activity(gear_uuid, activity_id)` | Associate gear with an activity |

### Nutrition logging

Requires a **Garmin Connect+** subscription and initial setup through the Garmin Connect app (the app creates the meal slots that the API needs).

```python
await client.add_nutrition_log(
    calories=500,
    carbs=60,       # optional, grams
    protein=30,     # optional, grams
    fat=15,         # optional, grams
    name="Lunch",   # optional label
)
```

The method automatically fetches the correct meal slot ID and time for the day. If no meal slots are configured yet, open the Garmin Connect app and set up your nutrition plan first.

## Individual API Methods

| Method | Description |
| ------ | ----------- |
| `get_user_profile()` | User profile info |
| `get_daily_steps()` | Steps for date range |
| `get_body_composition()` | Weight, BMI, body fat |
| `get_fitness_age()` | Fitness age metrics |
| `get_hydration_data()` | Daily hydration |
| `get_activities()` | Most recent activities (newest first, no date filter) |
| `get_activity_types()` | Cached Garmin activity type hierarchy (`typeId`, `typeKey`, `parentTypeId`) |
| `get_activity_gear(activity_id)` | Gear associated with one Garmin activity |
| `get_activity(activity_id)` | Single activity summary (includes e-bike fields) |
| `get_activity_details()` | Detailed activity with polyline |
| `get_activity_hr_in_timezones()` | HR time in zones |
| `download_activity(activity_id, file_format)` | Download activity file (fit/original/tcx/gpx/kml/csv) |
| `get_workouts()` | Scheduled workouts |
| `get_training_readiness()` | Training readiness score |
| `get_training_status()` | Training status |
| `get_morning_training_readiness()` | Morning readiness |
| `get_endurance_score()` | Endurance score |
| `get_hill_score()` | Hill score |
| `get_lactate_threshold()` | Lactate threshold |
| `get_power_to_weight(target_date)` | FTP / power-to-weight data |
| `get_goals()` | User goals by status |
| `get_earned_badges()` | Earned badges |
| `get_gear()` | User gear items |
| `get_gear_stats()` | Gear statistics |
| `get_gear_defaults()` | Default gear settings |
| `get_devices()` | Connected devices |
| `get_sensors()` | Paired ANT+/BLE sensors and battery status |
| `get_device_alarms()` | Device alarms |
| `get_device_solar_data()` | Solar intensity data per device |
| `get_device_last_used()` | Last used device and last sync time |
| `get_device_settings()` | Device settings |
| `get_blood_pressure()` | Blood pressure data |
| `get_menstrual_data()` | Menstrual cycle data |
| `get_menstrual_calendar()` | Menstrual calendar |
| `get_nutrition_log()` | Daily nutrition log (Connect+) |

## Data Transformations

The library automatically adds computed fields for convenience:

- **Time conversions**: `sleepTimeSeconds` → `sleepTimeMinutes`
- **Activity time**: `highlyActiveSeconds` → `highlyActiveMinutes`
- **Weight**: `weight` (grams) → `weightKg`
- **Stress**: `stressQualifier` → `stressQualifierText` (capitalized)
- **Nested flattening**: HRV status, training readiness, scores

## License

MIT
