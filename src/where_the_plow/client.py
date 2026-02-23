from datetime import datetime, timedelta, timezone

import httpx

from where_the_plow.config import settings

# The AVL API returns epoch-millisecond timestamps that represent
# Newfoundland Standard Time (UTC-3:30) but are encoded as if they were UTC.
# To get the real UTC time we must add the 3:30 offset back.
_NST_CORRECTION = timedelta(hours=3, minutes=30)


def parse_avl_response(data: dict) -> tuple[list[dict], list[dict]]:
    vehicles = []
    positions = []
    for feature in data.get("features", []):
        attrs = feature["attributes"]
        geom = feature.get("geometry", {})

        vehicle_id = str(attrs["ID"])
        naive_ts = datetime.fromtimestamp(
            attrs["LocationDateTime"] / 1000, tz=timezone.utc
        )
        ts = naive_ts + _NST_CORRECTION

        vehicles.append(
            {
                "vehicle_id": vehicle_id,
                "description": attrs.get("Description", ""),
                "vehicle_type": attrs.get("VehicleType", ""),
            }
        )

        speed_raw = attrs.get("Speed", "0.0")
        try:
            speed = float(speed_raw)
        except (ValueError, TypeError):
            speed = 0.0

        positions.append(
            {
                "vehicle_id": vehicle_id,
                "timestamp": ts,
                "longitude": geom.get("x", 0.0),
                "latitude": geom.get("y", 0.0),
                "bearing": attrs.get("Bearing", 0),
                "speed": speed,
                "is_driving": attrs.get("isDriving", ""),
            }
        )

    return vehicles, positions


async def fetch_vehicles(client: httpx.AsyncClient) -> dict:
    params = {
        "f": "json",
        "outFields": "ID,Description,VehicleType,LocationDateTime,Bearing,Speed,isDriving",
        "outSR": "4326",
        "returnGeometry": "true",
        "where": "1=1",
    }
    headers = {
        "Referer": settings.avl_referer,
    }
    resp = await client.get(
        settings.avl_api_url, params=params, headers=headers, timeout=10
    )
    resp.raise_for_status()
    return resp.json()


def _safe_bearing(value) -> int:
    """Convert bearing to int, handling None/invalid values."""
    try:
        return int(float(value))
    except (ValueError, TypeError):
        return 0


# Map AATracking LOO_TYPE to normalized vehicle types matching St. John's AVL.
# This keeps legend colors consistent across all sources.
_AATRACKING_TYPE_MAP = {
    "HEAVY_TYPE": "LOADER",
    "TRUCK_TYPE": "SA PLOW TRUCK",
}


def parse_aatracking_response(
    data: list, collected_at: datetime | None = None
) -> tuple[list[dict], list[dict]]:
    """Parse AATracking portal response (Mt Pearl, Provincial).

    If VEH_EVENT_DATETIME is present, use it. Otherwise fall back to collected_at.
    """
    vehicles = []
    positions = []
    for item in data:
        raw_id = item.get("VEH_ID")
        if raw_id is None:
            continue
        vehicle_id = str(raw_id)

        # Parse timestamp: present for Mt Pearl, absent for Provincial
        ts_str = item.get("VEH_EVENT_DATETIME")
        if ts_str:
            try:
                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                ts = collected_at or datetime.now(timezone.utc)
        else:
            ts = collected_at or datetime.now(timezone.utc)

        # Normalize vehicle type from LOO_TYPE to match St. John's categories.
        # LOO_DESCRIPTION (e.g. "Large Loader") goes into the description for detail popups.
        loo_type = item.get("LOO_TYPE", "")
        vehicle_type = _AATRACKING_TYPE_MAP.get(loo_type, loo_type or "Unknown")
        veh_name = item.get("VEH_NAME", "")
        loo_desc = item.get("LOO_DESCRIPTION", "")
        description = f"{veh_name} ({loo_desc})" if loo_desc else veh_name

        vehicles.append(
            {
                "vehicle_id": vehicle_id,
                "description": description,
                "vehicle_type": vehicle_type,
            }
        )

        positions.append(
            {
                "vehicle_id": vehicle_id,
                "timestamp": ts,
                "longitude": item.get("VEH_EVENT_LONGITUDE", 0.0),
                "latitude": item.get("VEH_EVENT_LATITUDE", 0.0),
                "bearing": _safe_bearing(item.get("VEH_EVENT_HEADING", 0)),
                "speed": None,
                "is_driving": None,
            }
        )

    return vehicles, positions


async def fetch_source(client: httpx.AsyncClient, source) -> dict | list:
    """Fetch data from any source. Returns raw JSON (dict for AVL, list for AATracking)."""
    headers = {}
    params = {}

    if source.parser == "avl":
        params = {
            "f": "json",
            "outFields": "ID,Description,VehicleType,LocationDateTime,Bearing,Speed,isDriving",
            "outSR": "4326",
            "returnGeometry": "true",
            "where": "1=1",
        }
        if source.referer:
            headers["Referer"] = source.referer

    resp = await client.get(source.api_url, params=params, headers=headers, timeout=10)
    resp.raise_for_status()
    return resp.json()
