# src/where_the_plow/snapshot.py
"""Build the cached realtime snapshot returned by /vehicles."""

from datetime import datetime

from where_the_plow.db import Database


def build_realtime_snapshot(db: Database, source: str | None = None) -> dict:
    """Query latest positions with mini-trails and return a GeoJSON FeatureCollection dict."""
    rows = db.get_latest_positions_with_trails(trail_points=6, source=source)
    features = []
    for r in rows:
        ts = r["timestamp"]
        ts_str = ts.isoformat() if isinstance(ts, datetime) else str(ts)
        features.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [r["longitude"], r["latitude"]],
                },
                "properties": {
                    "vehicle_id": r["vehicle_id"],
                    "description": r["description"],
                    "vehicle_type": r["vehicle_type"],
                    "speed": r["speed"],
                    "bearing": r["bearing"],
                    "is_driving": r["is_driving"],
                    "timestamp": ts_str,
                    "trail": r["trail"],
                    "source": r.get("source", "st_johns"),
                },
            }
        )
    return {
        "type": "FeatureCollection",
        "features": features,
    }
