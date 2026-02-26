# Paradise HitechMaps API

**Status:** Implemented — parser: `hitechmaps`, source: `paradise`
**GitHub issue:** #15
**Tracker URL:** https://hitechmaps.com/townparadise/
**API type:** PHP backend, simple JSON REST
**Platform:** HitechMaps (likely Geotab-based backend)

## API Endpoint

```
GET https://hitechmaps.com/townparadise/db.php
```

No authentication, no special headers, no query parameters.
The frontend fetches with `{cache: "no-cache"}`.

## Response Shape

Returns a JSON array of vehicle objects. When no plows are active, returns
an empty array `[]`.

**Confirmed shape** (from live API data, Feb 2026):

```json
[
  {
    "VID": "b3C",
    "Latitude": "47.5314178",
    "longitude": "-52.8553162",
    "Bearing": "244",
    "IsDeviceCommunicating": "1",
    "Engine": "0",
    "Speed": "26",
    "DateTime": "2026-02-26 01:05:26",
    "Ignition": "1",
    "DeviceName": "101",
    "UpdateTime": "2026-02-26 01:05:39",
    "TruckType": "Plows",
    "CurrentStateDuration": "00:27:54"
  }
]
```

**Important differences from original JS source analysis:**
- All values are **strings**, not native numbers/booleans
- `DateTime` uses space separator (`"2026-02-26 01:05:26"`), not ISO 8601 with T
- `Engine` field exists (undocumented in original analysis)
- `UpdateTime` field exists — server-side refresh timestamp, same for all vehicles
- `Bearing` of `"0"` for stationary (not `-1` as originally expected)
- `TruckType` values observed: `"Plows"`, `"Loaders"`

### Field Details

| Field | Type | Notes |
|-------|------|-------|
| `VID` | string | Unique vehicle identifier (hex-like: `"b19"`, `"b3C"`) |
| `Latitude` | string | **Capital L** -- latitude as string (WGS84) |
| `longitude` | string | **Lowercase l** -- longitude as string (WGS84). Inconsistent casing! |
| `Speed` | string | Current speed as string; `"0"` = stationary |
| `Bearing` | string | Direction in degrees as string; `"0"` for unknown/stationary |
| `IsDeviceCommunicating` | string | `"0"` or `"1"` -- whether the GPS device is online |
| `Engine` | string | `"0"` or `"1"` -- engine status |
| `Ignition` | string | `"0"` or `"1"` -- whether the vehicle ignition is on |
| `DeviceName` | string | Human-readable vehicle name (numeric IDs like `"070"`, `"101"`) |
| `TruckType` | string | Vehicle type: `"Plows"`, `"Loaders"`, or empty |
| `CurrentStateDuration` | string | How long in current state (`HH:MM:SS` or `D.HH:MM:SS`) |
| `DateTime` | string | GPS update timestamp (`"YYYY-MM-DD HH:MM:SS"`, space-separated, NST) |
| `UpdateTime` | string | Server refresh timestamp, same across all vehicles in a response |

### Key Quirks

1. **Inconsistent field casing**: `Latitude` (capital L) vs `longitude`
   (lowercase l). This is a bug in their API, not a convention.
2. **All values are strings**: Unlike most JSON APIs, even numeric fields
   like `Speed`, `Bearing`, and coordinates are returned as strings.
3. **Bearing of 0 for unknown**: Stationary vehicles show `"0"`, not `-1`
   as originally expected from JS source analysis.
4. **Server-side refresh interval**: `UpdateTime` changes every ~20-30
   seconds, regardless of the frontend's 5-second poll interval.
5. **Empty when inactive**: Unlike St. John's which always shows vehicles,
   Paradise only returns data when plows are actively operating.

## Frontend Behavior (from source analysis)

- **Map center:** `{ lat: 47.5235, lng: -52.8693 }` at zoom 14
- **Poll interval:** 5000ms (5 seconds)
- **Marker colors:**
  - Default: `#4CBB17` (green)
  - Empty TruckType: Yellow
  - Several conditions (not communicating, ignition off, speed 0) have
    **commented-out** red coloring -- all vehicles currently appear green/yellow
- **Plow icon:** Custom SVG rotated by bearing, flipped horizontally when
  bearing <= 180
- **Boundary polygon:** A small polygon is defined in the source (Paradise
  area coordinates) but its usage is unclear

## Polling Characteristics

- Their frontend polls every **5 seconds**
- Server-side data refreshes every **~20-30 seconds** (observed from
  `UpdateTime` field changes)
- Configured poll interval: **10 seconds** (catches every server refresh)
- No authentication required
- Vehicle count: **17 observed** (mix of Plows and Loaders, Feb 2026)
- Coverage: Town of Paradise municipal boundaries

## Availability Concerns

This API only returns data when plows are actively out. During periods
between storms, it returns an empty array. The collector should handle
this gracefully (log and continue, don't treat empty as an error).

## Normalization to Common Schema

| Common Field | Source Field | Transform |
|-------------|-------------|-----------|
| `vehicle_id` | `VID` | `str(VID)` |
| `description` | `DeviceName` | Direct |
| `vehicle_type` | `TruckType` | Direct (empty string -> "Unknown") |
| `timestamp` | `DateTime` | Parse ISO 8601 |
| `latitude` | `Latitude` | Direct (note: capital L) |
| `longitude` | `longitude` | Direct (note: lowercase l) |
| `bearing` | `Bearing` | Direct, but map -1 to `None` |
| `speed` | `Speed` | Direct (float) |
| `is_driving` | Derived | `Ignition == "1" and Speed > 0` -> `"yes"`, else `"no"` |

### Additional Fields Available (not in common schema)

| Field | Use |
|-------|-----|
| `IsDeviceCommunicating` | Could be used to filter out stale vehicles |
| `Ignition` | Used to derive is_driving |
| `CurrentStateDuration` | Could be shown in vehicle details popup |

## Implementation

**Implemented** as source `paradise` with parser `hitechmaps`.

Files changed:
- `src/where_the_plow/client.py` — `HitechMapsItem` model + `parse_hitechmaps_response()`
- `src/where_the_plow/source_config.py` — `paradise` entry in `build_sources()`
- `src/where_the_plow/config.py` — `paradise_api_url`, `source_paradise_enabled`, `source_paradise_poll_interval`
- `src/where_the_plow/collector.py` — `hitechmaps` parser dispatch
- `tests/test_client.py` — parser tests with live data samples
- `tests/test_collector.py` — `process_poll` integration test

## Map Center

- Center: (-52.87, 47.52)
- Zoom: 14
- Coverage: Town of Paradise municipal boundaries
