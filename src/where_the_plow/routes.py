# src/where_the_plow/routes.py
import asyncio
import logging
import time
from collections import defaultdict
from datetime import datetime, timezone, timedelta

import httpx
from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import JSONResponse

from where_the_plow import cache

log = logging.getLogger(__name__)


# ── Generic in-memory rate limiter ────────────────────


class RateLimiter:
    """Sliding-window rate limiter keyed by an arbitrary string (typically IP)."""

    def __init__(self, max_hits: int, window_seconds: int):
        self.max_hits = max_hits
        self.window = window_seconds
        self._hits: dict[str, list[float]] = defaultdict(list)

    def is_limited(self, key: str) -> bool:
        now = time.monotonic()
        bucket = self._hits[key]
        self._hits[key] = [t for t in bucket if now - t < self.window]
        if len(self._hits[key]) >= self.max_hits:
            return True
        self._hits[key].append(now)
        return False


_signup_limiter = RateLimiter(max_hits=3, window_seconds=1800)  # 3 per 30 min
_viewport_limiter = RateLimiter(max_hits=60, window_seconds=300)  # 60 per 5 min
_search_limiter = RateLimiter(
    max_hits=6, window_seconds=60
)  # 6 searches per min per IP


# ── Nominatim search proxy with in-memory cache ──────

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
NOMINATIM_USER_AGENT = (
    "WhereThePlow/1.0 (St. John's snowplow tracker; https://plow.jackharrhy.dev)"
)
ST_JOHNS_VIEWBOX = "-52.85,47.45,-52.55,47.65"
SEARCH_CACHE_TTL = 86400  # 24 hours — addresses don't change often
SEARCH_CACHE_MAX = 500  # max entries before evicting oldest

_search_cache: dict[str, tuple[float, list[dict]]] = {}  # key -> (expires_at, results)
_nominatim_last_request: float = 0.0  # monotonic timestamp of last outbound request


def _search_cache_get(key: str) -> list[dict] | None:
    entry = _search_cache.get(key)
    if entry is None:
        return None
    expires_at, results = entry
    if time.monotonic() > expires_at:
        del _search_cache[key]
        return None
    return results


def _search_cache_put(key: str, results: list[dict]) -> None:
    # Evict oldest entries if cache is full
    if len(_search_cache) >= SEARCH_CACHE_MAX:
        oldest_key = min(_search_cache, key=lambda k: _search_cache[k][0])
        del _search_cache[oldest_key]
    _search_cache[key] = (time.monotonic() + SEARCH_CACHE_TTL, results)


def _client_ip(request: Request) -> str:
    return request.headers.get("x-forwarded-for", "").split(",")[0].strip() or (
        request.client.host if request.client else "unknown"
    )


from where_the_plow.models import (
    CoverageFeature,
    CoverageFeatureCollection,
    CoverageProperties,
    Feature,
    FeatureCollection,
    FeatureProperties,
    LineStringGeometry,
    Pagination,
    PointGeometry,
    SignupRequest,
    StatsResponse,
    ViewportTrack,
)

router = APIRouter()

DEFAULT_LIMIT = 200
MAX_LIMIT = 2000


def _rows_to_feature_collection(rows: list[dict], limit: int) -> FeatureCollection:
    features = []
    for r in rows:
        ts_str = (
            r["timestamp"].isoformat()
            if isinstance(r["timestamp"], datetime)
            else str(r["timestamp"])
        )
        features.append(
            Feature(
                geometry=PointGeometry(coordinates=[r["longitude"], r["latitude"]]),
                properties=FeatureProperties(
                    vehicle_id=r["vehicle_id"],
                    description=r["description"],
                    vehicle_type=r["vehicle_type"],
                    speed=r["speed"],
                    bearing=r["bearing"],
                    is_driving=r["is_driving"],
                    timestamp=ts_str,
                    source=r.get("source", "st_johns"),
                ),
            )
        )

    has_more = len(features) == limit
    next_cursor = features[-1].properties.timestamp if has_more else None

    return FeatureCollection(
        features=features,
        pagination=Pagination(
            limit=limit,
            count=len(features),
            next_cursor=next_cursor,
            has_more=has_more,
        ),
    )


@router.get(
    "/sources",
    summary="Available data sources",
    description="Returns metadata about each configured plow data source.",
    tags=["sources"],
)
def get_sources():
    from where_the_plow.config import SOURCES

    return {
        name: {
            "display_name": src.display_name,
            "center": list(src.center),
            "zoom": src.zoom,
            "enabled": src.enabled,
        }
        for name, src in SOURCES.items()
        if src.enabled
    }


def _merge_realtime_snapshots(snapshots: dict[str, dict]) -> dict:
    """Merge per-source realtime FeatureCollection dicts into one."""
    merged_features = []
    for fc in snapshots.values():
        merged_features.extend(fc.get("features", []))
    return {
        "type": "FeatureCollection",
        "features": merged_features,
    }


@router.get(
    "/vehicles",
    response_model=FeatureCollection,
    summary="Current vehicle positions",
    description="Returns the latest known position for every vehicle as a GeoJSON "
    "FeatureCollection with cursor-based pagination.",
    tags=["vehicles"],
)
def get_vehicles(
    request: Request,
    limit: int = Query(
        DEFAULT_LIMIT, ge=1, le=MAX_LIMIT, description="Max features per page"
    ),
    after: datetime | None = Query(
        None, description="Cursor: return features after this timestamp (ISO 8601)"
    ),
    source: str | None = Query(
        None,
        description="Filter by data source (e.g. 'st_johns', 'mt_pearl', 'provincial')",
    ),
):
    # Return cached realtime snapshot if available and no pagination cursor
    store = getattr(request.app.state, "store", {})
    if after is None and "realtime" in store:
        snapshots = store["realtime"]
        if source is not None:
            if source in snapshots:
                return JSONResponse(content=snapshots[source])
            # source not in cache — fall through to DB query
        else:
            return JSONResponse(content=_merge_realtime_snapshots(snapshots))

    db = request.app.state.db
    rows = db.get_latest_positions(limit=limit, after=after, source=source)
    return _rows_to_feature_collection(rows, limit)


@router.get(
    "/vehicles/nearby",
    response_model=FeatureCollection,
    summary="Nearby vehicles",
    description="Returns current vehicle positions within a radius of a given point. "
    "Uses DuckDB spatial ST_DWithin for fast lookups.",
    tags=["vehicles"],
)
def get_vehicles_nearby(
    request: Request,
    lat: float = Query(..., ge=-90, le=90, description="Latitude"),
    lng: float = Query(..., ge=-180, le=180, description="Longitude"),
    radius: float = Query(500, ge=1, le=5000, description="Radius in meters"),
    limit: int = Query(
        DEFAULT_LIMIT, ge=1, le=MAX_LIMIT, description="Max features per page"
    ),
    after: datetime | None = Query(
        None, description="Cursor: return features after this timestamp (ISO 8601)"
    ),
    source: str | None = Query(
        None,
        description="Filter by data source (e.g. 'st_johns', 'mt_pearl', 'provincial')",
    ),
):
    db = request.app.state.db
    rows = db.get_nearby_vehicles(
        lat=lat, lng=lng, radius_m=radius, limit=limit, after=after, source=source
    )
    return _rows_to_feature_collection(rows, limit)


@router.get(
    "/vehicles/{vehicle_id}/history",
    response_model=FeatureCollection,
    summary="Vehicle position history",
    description="Returns the position history for a single vehicle over a time range "
    "as a GeoJSON FeatureCollection.",
    tags=["vehicles"],
)
def get_vehicle_history(
    request: Request,
    vehicle_id: str,
    since: datetime | None = Query(
        None, description="Start of time range (ISO 8601). Default: 4 hours ago."
    ),
    until: datetime | None = Query(
        None, description="End of time range (ISO 8601). Default: now."
    ),
    limit: int = Query(
        DEFAULT_LIMIT, ge=1, le=MAX_LIMIT, description="Max features per page"
    ),
    after: datetime | None = Query(
        None, description="Cursor: return features after this timestamp (ISO 8601)"
    ),
    source: str | None = Query(
        None,
        description="Filter by data source (e.g. 'st_johns', 'mt_pearl', 'provincial')",
    ),
):
    db = request.app.state.db
    now = datetime.now(timezone.utc)
    if since is None:
        since = now - timedelta(hours=4)
    if until is None:
        until = now
    rows = db.get_vehicle_history(
        vehicle_id, since=since, until=until, limit=limit, after=after, source=source
    )
    return _rows_to_feature_collection(rows, limit)


@router.get(
    "/coverage",
    response_model=CoverageFeatureCollection,
    summary="Coverage trails",
    description="Returns per-vehicle LineString trails within a time range, "
    "downsampled to ~1 point per 30 seconds. Each feature includes a "
    "parallel timestamps array for recency-based visualization.",
    tags=["coverage"],
)
def get_coverage(
    request: Request,
    since: datetime | None = Query(
        None, description="Start of time range (ISO 8601). Default: 24 hours ago."
    ),
    until: datetime | None = Query(
        None, description="End of time range (ISO 8601). Default: now."
    ),
    source: str | None = Query(
        None,
        description="Filter by data source (e.g. 'st_johns', 'mt_pearl', 'provincial')",
    ),
):
    db = request.app.state.db
    now = datetime.now(timezone.utc)
    if since is None:
        since = now - timedelta(hours=24)
    if until is None:
        until = now

    # Check file cache (only hits for fully-historical queries without source filter)
    if source is None:
        cached = cache.get(since, until)
        if cached is not None:
            trails = cached
        else:
            trails = db.get_coverage_trails(since=since, until=until)
            cache.put(since, until, trails)
    else:
        trails = db.get_coverage_trails(since=since, until=until, source=source)

    features = [
        CoverageFeature(
            geometry=LineStringGeometry(coordinates=t["coordinates"]),
            properties=CoverageProperties(
                vehicle_id=t["vehicle_id"],
                vehicle_type=t["vehicle_type"],
                description=t["description"],
                timestamps=t["timestamps"],
                source=t.get("source", "st_johns"),
            ),
        )
        for t in trails
    ]
    return CoverageFeatureCollection(features=features)


@router.get(
    "/stats",
    response_model=StatsResponse,
    summary="Collection statistics",
    description="Returns aggregate statistics about the collected plow tracking data.",
    tags=["stats"],
)
def get_stats(request: Request):
    db = request.app.state.db
    stats = db.get_stats()
    earliest = stats.get("earliest")
    latest = stats.get("latest")
    return StatsResponse(
        total_positions=stats["total_positions"],
        total_vehicles=stats["total_vehicles"],
        active_vehicles=stats.get("active_vehicles", 0),
        earliest=earliest.isoformat() if earliest else None,
        latest=latest.isoformat() if latest else None,
        db_size_bytes=stats.get("db_size_bytes"),
    )


@router.post(
    "/track",
    status_code=204,
    summary="Track viewport focus",
    description="Records an anonymous viewport focus event for analytics. "
    "Called by the frontend when a user settles on a map area.",
    tags=["analytics"],
)
def track_viewport(request: Request, body: ViewportTrack):
    ip = _client_ip(request)

    if _viewport_limiter.is_limited(ip):
        return Response(status_code=429)

    user_agent = request.headers.get("user-agent", "")
    db = request.app.state.db
    sw = body.bounds.get("sw", [0, 0])
    ne = body.bounds.get("ne", [0, 0])
    db.insert_viewport(
        ip=ip,
        user_agent=user_agent,
        zoom=body.zoom,
        center_lng=body.center[0],
        center_lat=body.center[1],
        sw_lng=sw[0],
        sw_lat=sw[1],
        ne_lng=ne[0],
        ne_lat=ne[1],
    )
    return Response(status_code=204)


@router.post(
    "/signup",
    status_code=204,
    summary="Email signup",
    description="Records an email signup for notifications about plow tracking, "
    "new projects, or the Silicon Harbour newsletter.",
    tags=["signup"],
)
def signup(request: Request, body: SignupRequest):
    ip = _client_ip(request)
    user_agent = request.headers.get("user-agent", "")

    if _signup_limiter.is_limited(ip):
        return Response(status_code=429)

    db = request.app.state.db
    db.insert_signup(
        email=body.email,
        ip=ip,
        user_agent=user_agent,
        notify_plow=body.notify_plow,
        notify_projects=body.notify_projects,
        notify_siliconharbour=body.notify_siliconharbour,
        note=body.note,
    )
    return Response(status_code=204)


@router.get(
    "/search",
    summary="Geocode an address via Nominatim (cached proxy)",
    description="Proxies search queries to Nominatim with server-side caching and "
    "rate limiting. Results are cached for 24 hours. Respects Nominatim's "
    "usage policy (max 1 req/sec, proper User-Agent, caching).",
    tags=["search"],
)
async def search_address(
    request: Request,
    q: str = Query(..., min_length=2, max_length=200, description="Search query"),
):
    global _nominatim_last_request

    ip = _client_ip(request)
    if _search_limiter.is_limited(ip):
        return Response(status_code=429)

    cache_key = q.strip().lower()

    cached = _search_cache_get(cache_key)
    if cached is not None:
        return JSONResponse(content=cached)

    # Enforce 1 req/sec to Nominatim across all users
    now = time.monotonic()
    wait = 1.0 - (now - _nominatim_last_request)
    if wait > 0:
        await asyncio.sleep(wait)

    params = {
        "q": q.strip() + ", St. John's Newfoundland",
        "format": "json",
        "addressdetails": "1",
        "limit": "5",
        "viewbox": ST_JOHNS_VIEWBOX,
        "bounded": "0",
    }

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                NOMINATIM_URL,
                params=params,
                headers={"User-Agent": NOMINATIM_USER_AGENT},
                timeout=10.0,
            )
        _nominatim_last_request = time.monotonic()

        if resp.status_code != 200:
            log.warning("Nominatim returned %s for query %r", resp.status_code, q)
            return Response(status_code=502)

        raw = resp.json()
        results = [_format_search_result(r) for r in raw]
        _search_cache_put(cache_key, results)
        return JSONResponse(content=results)

    except httpx.TimeoutException:
        log.warning("Nominatim timeout for query %r", q)
        return Response(status_code=504)
    except Exception:
        log.exception("Nominatim proxy error for query %r", q)
        return Response(status_code=502)


def _format_search_result(result: dict) -> dict:
    """Build a clean, short label from Nominatim's structured address fields."""
    addr = result.get("address", {})
    lat = result.get("lat")
    lon = result.get("lon")

    parts: list[str] = []

    # Primary name: building/POI name if it differs from the road
    name = result.get("name", "")
    road = addr.get("road", "")

    # House number + road (e.g. "100 Elizabeth Avenue")
    house = addr.get("house_number", "")
    road_part = f"{house} {road}".strip() if house else road

    if name and name != road:
        parts.append(name)
        if road_part:
            parts.append(road_part)
    elif road_part:
        parts.append(road_part)

    # Neighbourhood / quarter
    neighbourhood = (
        addr.get("neighbourhood") or addr.get("quarter") or addr.get("suburb")
    )
    if neighbourhood:
        parts.append(neighbourhood)

    # City — include it so results outside St. John's still make sense
    city = addr.get("city") or addr.get("town") or addr.get("village")
    if city:
        parts.append(city)

    label = ", ".join(parts) if parts else result.get("display_name", "Unknown")

    return {"lat": lat, "lon": lon, "label": label}
