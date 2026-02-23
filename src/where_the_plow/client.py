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


def parse_aatracking_response(
    data: list, collected_at: datetime | None = None
) -> tuple[list[dict], list[dict]]:
    """Parse AATracking portal response (Mt Pearl, Provincial).

    If VEH_EVENT_DATETIME is present, use it. Otherwise fall back to collected_at.
    """
    vehicles = []
    positions = []
    for item in data:
        vehicle_id = str(item["VEH_ID"])

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

        vehicles.append(
            {
                "vehicle_id": vehicle_id,
                "description": item.get("VEH_NAME", ""),
                "vehicle_type": item.get("LOO_DESCRIPTION", "Unknown"),
            }
        )

        positions.append(
            {
                "vehicle_id": vehicle_id,
                "timestamp": ts,
                "longitude": item.get("VEH_EVENT_LONGITUDE", 0.0),
                "latitude": item.get("VEH_EVENT_LATITUDE", 0.0),
                "bearing": int(item.get("VEH_EVENT_HEADING", 0)),
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
