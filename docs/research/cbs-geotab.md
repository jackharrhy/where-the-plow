# CBS Geotab Citizen Insights

**Status:** Implemented -- parser: `geotab`, source: `cbs`
**GitHub issue:** #16
**Tracker URL:** https://citizeninsights.geotab.com/#/equipment-tracker-cbs
**API type:** Two-step signed URL (Geotab -> GCS bucket)
**Platform:** Geotab Citizen Insights

## API Flow

The Geotab Citizen Insights platform uses a two-step fetch:

### Step 1: Get deployment config (one-time)

```
GET https://citizeninsights.geotab.com/config/equipment-tracker-cbs
```

Returns the full deployment configuration including service categories,
map center/zoom, and the `cacheLocation` ("Canada") used to construct
bucket file paths.

### Step 2: Get signed URL for bucket file

```
GET https://citizeninsights.geotab.com/urlForFileFromBucket/{cacheLocation}/{filename}
```

Returns `{"url": "<signed GCS URL>"}`. The signed URL has:
- `X-Goog-Expires=1800` (30 minutes)
- `X-Goog-Algorithm=GOOG4-RSA-SHA256`
- Credential: `gcebigdatp21-account@geotab-citizeninsights-prod`

### Step 3: Fetch data from signed URL

The signed URL points to a JSON file in a Google Cloud Storage bucket:
`geotab-citizen-insights-prod-bucket-canada/`

## File Naming Convention

Files in the bucket follow this pattern:

```
equipment-tracker-{publicURL}-{serviceCategoryId}-{serviceGroupId}-{dataType}.json
```

For CBS snow plows:
```
equipment-tracker-cbs-lp038h1u-b27A7-vehicle-locations.json
                  ^^^ ^^^^^^^^ ^^^^^
                  slug category group
```

### Service Categories (from config)

| Category ID | Group ID | Type | Icon | Availability |
|-------------|----------|------|------|--------------|
| `lp038h1u` | `b27A7` | Snow plows | ice-road | Oct-Mar (Range) |
| `lr84dhvu` | `b27A9` | Waste trucks | bin | Year-round |
| `lr84fate` | `b27AE` | Recycling | ecology-leaf | Year-round |

Only snow plows (`lp038h1u`/`b27A7`) are implemented. The other
categories could be added later if desired.

### Available Files Per Category

| Suffix | Exists | Content |
|--------|--------|---------|
| `vehicle-locations.json` | Yes | Vehicle positions |
| `routes.json` | Yes | GeoJSON FeatureCollection (often empty) |
| `trip-trails.json` | Yes | Historical trail data with metadata |
| `settings.json` | No | NoSuchKey error |
| `config.json` | No | NoSuchKey error |

## Vehicle Locations Response Shape

```json
{
    "b21": [-52.9353294, 47.5177231],
    "bBB": [-52.9379311, 47.5386467],
    "b42": [-52.9595337, 47.5173874]
}
```

A flat dictionary mapping vehicle IDs to `[longitude, latitude]` arrays.

**This is extremely minimal:**
- No timestamps
- No speed or bearing
- No vehicle names or types
- No is_driving indicator
- Just ID and coordinates

### Data Limitations

| Field | Available | Workaround |
|-------|-----------|------------|
| Timestamp | No | Use `collected_at` from poll time |
| Speed | No | None (could derive from position delta) |
| Bearing | No | None (could derive from position delta) |
| Vehicle name | No | Use vehicle ID as description |
| Vehicle type | No | Assume "SA PLOW TRUCK" (only snow plow category) |
| is_driving | No | None |

## Polling Characteristics

- Config `timeDelay`: 15 (seconds)
- Configured poll interval: **15 seconds**
- Server-side data update rate: unknown (positions were static during
  late-night testing, likely updates when plows are active)
- Signed URLs expire after **30 minutes** -- a new one is requested
  every poll (cheap GET, no auth)
- Vehicle count: **3 observed** (Feb 2026, late night)
- No authentication required for any step

## Config Details (from /config/equipment-tracker-cbs)

| Field | Value |
|-------|-------|
| `cacheLocation` | `"Canada"` |
| `publicURL` | `"equipment-tracker-cbs"` |
| `timeDelay` | `15` |
| `viewState.latitude` | `47.512` |
| `viewState.longitude` | `-52.976` |
| `viewState.zoom` | `12.07` |
| `hideVehicles.hideStoppedVehicles` | `true` |
| `hideVehicles.hideOffRouteVehicles` | `true` |
| `published` | `true` |
| `lastPublishedDate` | `"2025-02-06T13:00:13.260Z"` |

Note: `hideStoppedVehicles` is a frontend-only filter. The API still
returns all vehicles regardless of movement state.

## Implementation

**Implemented** as source `cbs` with parser `geotab`.

The `api_url` is set to the full `urlForFileFromBucket` endpoint for the
vehicle-locations file. The `fetch_source` function detects the `geotab`
parser and performs the two-step fetch (get signed URL, then fetch data).

Files changed:
- `src/where_the_plow/client.py` -- `parse_geotab_response()` + two-step
  fetch in `fetch_source()`
- `src/where_the_plow/source_config.py` -- `cbs` entry in `build_sources()`
- `src/where_the_plow/config.py` -- `cbs_api_url`, `source_cbs_enabled`,
  `source_cbs_poll_interval`
- `src/where_the_plow/collector.py` -- `geotab` parser dispatch
- `tests/test_client.py` -- parser tests
- `tests/test_collector.py` -- `process_poll` + `fetch_source` two-step test

## Brittleness Concerns

The main fragility risk is the **file path** containing hardcoded IDs:

```
equipment-tracker-cbs-lp038h1u-b27A7-vehicle-locations.json
```

If CBS reconfigures their Geotab deployment, the `serviceCategoryId`
(`lp038h1u`) or `serviceGroupId` (`b27A7`) could change. However:

1. The `/config/equipment-tracker-cbs` endpoint returns these IDs
   dynamically, so a more resilient implementation could fetch the config
   on startup and derive the file path.
2. In practice, these IDs appear stable -- `lastPublishedDate` is from
   Feb 2025, suggesting the config doesn't change often.
3. The `api_url` is configurable via the `CBS_API_URL` env var, so the
   path can be updated without a code change.

## Reusability

The Geotab Citizen Insights platform is used by multiple municipalities
across Canada. The same two-step fetch pattern would work for any
deployment -- only the `publicURL` slug and category/group IDs change.
The `/config/{slug}` endpoint provides all needed IDs programmatically.

## Map Center

- Center: (-52.98, 47.51)
- Zoom: 12
- Coverage: Town of Conception Bay South
