# where the plow

Real-time and historical tracking of snowplow vehicles across Newfoundland — St. John's, Mount Pearl, and Provincial.

Polls multiple AVL (Automatic Vehicle Location) APIs at configurable intervals, stores historical position data in DuckDB, serves it as GeoJSON, and visualizes it on a live map.

**Production:** https://plow.jackharrhy.dev

## Running

### Local

Requires [uv](https://docs.astral.sh/uv/):

```
uv run cli.py dev
```

This starts the app with auto-reload and sets `DB_PATH=./data/plow.db`. You can also run uvicorn directly:

```
uv run uvicorn where_the_plow.main:app --host 0.0.0.0 --port 8000
```

### Docker

```
docker compose up -d
```

Either way, the app starts at `http://localhost:8000`. DuckDB data persists to `./data/plow.db`.

### Environment variables

| Variable | Default | Description |
|---|---|---|
| `DB_PATH` | `/data/plow.db` | Path to DuckDB database file |
| `LOG_LEVEL` | `INFO` | Python log level |
| `AVL_API_URL` | St. John's AVL endpoint | Override the St. John's API URL |
| `SOURCE_ST_JOHNS_ENABLED` | `true` | Enable/disable St. John's source |
| `SOURCE_ST_JOHNS_POLL_INTERVAL` | `6` | St. John's poll interval (seconds) |
| `SOURCE_MT_PEARL_ENABLED` | `true` | Enable/disable Mount Pearl source |
| `SOURCE_MT_PEARL_POLL_INTERVAL` | `30` | Mount Pearl poll interval (seconds) |
| `SOURCE_PROVINCIAL_ENABLED` | `true` | Enable/disable Provincial source |
| `SOURCE_PROVINCIAL_POLL_INTERVAL` | `30` | Provincial poll interval (seconds) |
| `MT_PEARL_API_URL` | Mount Pearl AVL endpoint | Override Mount Pearl API URL |
| `PROVINCIAL_API_URL` | Provincial AVL endpoint | Override Provincial API URL |

## API

All geo endpoints return GeoJSON. Full OpenAPI docs at [`/docs`](https://plow.jackharrhy.dev/docs).

| Endpoint | Description |
|---|---|
| `GET /sources` | Available data sources and metadata |
| `GET /vehicles` | Latest position for every vehicle (with mini-trails) |
| `GET /vehicles/nearby?lat=&lng=&radius=` | Vehicles within radius (meters) |
| `GET /vehicles/{id}/history?since=&until=` | Position history for one vehicle |
| `GET /coverage?since=&until=` | Per-vehicle LineString trails with timestamps |
| `GET /search?q=` | Geocode an address via Nominatim (cached proxy) |
| `GET /stats` | Collection statistics |
| `GET /health` | Health check |
| `POST /track` | Record anonymous viewport focus event |
| `POST /signup` | Email signup for notifications |

Vehicle and coverage endpoints support a `?source=` query parameter to filter by data source. All GET list endpoints support cursor-based pagination via `limit` and `after` query parameters. Write endpoints (`/track`, `/signup`) are rate-limited per IP.

## Database schema

DuckDB with the spatial extension.

```sql
CREATE TABLE vehicles (
    vehicle_id    VARCHAR NOT NULL,
    source        VARCHAR NOT NULL DEFAULT 'st_johns',
    description   VARCHAR,
    vehicle_type  VARCHAR,
    first_seen    TIMESTAMPTZ NOT NULL,
    last_seen     TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (vehicle_id, source)
);

CREATE TABLE positions (
    id            BIGINT DEFAULT nextval('positions_seq'),
    vehicle_id    VARCHAR NOT NULL,
    source        VARCHAR NOT NULL DEFAULT 'st_johns',
    timestamp     TIMESTAMPTZ NOT NULL,
    collected_at  TIMESTAMPTZ NOT NULL,
    longitude     DOUBLE NOT NULL,
    latitude      DOUBLE NOT NULL,
    geom          GEOMETRY,
    bearing       INTEGER,
    speed         DOUBLE,
    is_driving    VARCHAR,
    PRIMARY KEY (vehicle_id, timestamp, source)
);
```

Deduplication is by `(vehicle_id, timestamp, source)` composite key -- if the API returns the same `LocationDateTime` for a vehicle from the same source, the row is skipped.

There are also `viewports` (analytics) and `signups` (email signups) tables -- see `db.py` for their full schemas.

## Stack

Python 3.12, FastAPI, DuckDB (spatial), httpx, MapLibre GL JS, noUiSlider, Docker.
