# tests/test_snapshot.py
import os
import tempfile
from datetime import datetime, timedelta, timezone

from where_the_plow.db import Database
from where_the_plow.snapshot import build_realtime_snapshot


def make_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.unlink(path)
    db = Database(path)
    db.init()
    return db, path


def test_snapshot_returns_feature_collection():
    """build_realtime_snapshot returns a valid GeoJSON FeatureCollection."""
    db, path = make_db()
    now = datetime.now(timezone.utc)
    ts = now - timedelta(seconds=30)

    db.upsert_vehicles(
        [{"vehicle_id": "v1", "description": "Plow 1", "vehicle_type": "LOADER"}], now
    )
    db.insert_positions(
        [
            {
                "vehicle_id": "v1",
                "timestamp": ts,
                "longitude": -52.73,
                "latitude": 47.56,
                "bearing": 90,
                "speed": 10.0,
                "is_driving": "maybe",
            },
        ],
        now,
    )

    result = build_realtime_snapshot(db)

    assert result["type"] == "FeatureCollection"
    assert len(result["features"]) == 1

    feature = result["features"][0]
    assert feature["type"] == "Feature"
    assert feature["geometry"]["type"] == "Point"
    assert feature["geometry"]["coordinates"] == [-52.73, 47.56]

    props = feature["properties"]
    assert props["vehicle_id"] == "v1"
    assert props["description"] == "Plow 1"
    assert props["vehicle_type"] == "LOADER"
    assert props["bearing"] == 90
    assert props["speed"] == 10.0
    assert props["is_driving"] == "maybe"

    db.close()
    os.unlink(path)


def test_snapshot_includes_trail():
    """Features include a trail array from the DB method."""
    db, path = make_db()
    now = datetime.now(timezone.utc)
    ts1 = now - timedelta(seconds=18)
    ts2 = now - timedelta(seconds=12)
    ts3 = now - timedelta(seconds=6)

    db.upsert_vehicles(
        [{"vehicle_id": "v1", "description": "Plow 1", "vehicle_type": "LOADER"}], now
    )
    db.insert_positions(
        [
            {
                "vehicle_id": "v1",
                "timestamp": ts1,
                "longitude": -52.73,
                "latitude": 47.56,
                "bearing": 0,
                "speed": 5.0,
                "is_driving": "maybe",
            },
            {
                "vehicle_id": "v1",
                "timestamp": ts2,
                "longitude": -52.74,
                "latitude": 47.57,
                "bearing": 90,
                "speed": 10.0,
                "is_driving": "maybe",
            },
            {
                "vehicle_id": "v1",
                "timestamp": ts3,
                "longitude": -52.75,
                "latitude": 47.58,
                "bearing": 180,
                "speed": 15.0,
                "is_driving": "maybe",
            },
        ],
        now,
    )

    result = build_realtime_snapshot(db)
    trail = result["features"][0]["properties"]["trail"]

    assert len(trail) == 3
    assert trail[0] == [-52.73, 47.56]
    assert trail[2] == [-52.75, 47.58]

    # Geometry should be the latest position
    assert result["features"][0]["geometry"]["coordinates"] == [-52.75, 47.58]

    db.close()
    os.unlink(path)


def test_snapshot_empty_db():
    """Empty database produces an empty FeatureCollection."""
    db, path = make_db()

    result = build_realtime_snapshot(db)

    assert result["type"] == "FeatureCollection"
    assert result["features"] == []

    db.close()
    os.unlink(path)


def test_snapshot_timestamp_serialized():
    """Timestamps are serialized to ISO strings, not datetime objects."""
    db, path = make_db()
    now = datetime.now(timezone.utc)
    ts = now - timedelta(seconds=30)

    db.upsert_vehicles(
        [{"vehicle_id": "v1", "description": "Plow 1", "vehicle_type": "LOADER"}], now
    )
    db.insert_positions(
        [
            {
                "vehicle_id": "v1",
                "timestamp": ts,
                "longitude": -52.73,
                "latitude": 47.56,
                "bearing": 0,
                "speed": 0.0,
                "is_driving": "no",
            },
        ],
        now,
    )

    result = build_realtime_snapshot(db)
    ts_val = result["features"][0]["properties"]["timestamp"]

    assert isinstance(ts_val, str)
    # DuckDB may return in local timezone; just verify it parses as a valid ISO string
    from datetime import datetime as dt

    parsed = dt.fromisoformat(ts_val)
    assert parsed.year == now.year

    db.close()
    os.unlink(path)


def test_snapshot_multiple_vehicles():
    """Snapshot includes all vehicles, each with their own trail."""
    db, path = make_db()
    now = datetime.now(timezone.utc)
    ts1 = now - timedelta(seconds=12)
    ts2 = now - timedelta(seconds=6)

    db.upsert_vehicles(
        [
            {"vehicle_id": "v1", "description": "Plow 1", "vehicle_type": "LOADER"},
            {
                "vehicle_id": "v2",
                "description": "Plow 2",
                "vehicle_type": "SA PLOW TRUCK",
            },
        ],
        now,
    )
    db.insert_positions(
        [
            {
                "vehicle_id": "v1",
                "timestamp": ts1,
                "longitude": -52.73,
                "latitude": 47.56,
                "bearing": 0,
                "speed": 5.0,
                "is_driving": "maybe",
            },
            {
                "vehicle_id": "v1",
                "timestamp": ts2,
                "longitude": -52.74,
                "latitude": 47.57,
                "bearing": 90,
                "speed": 10.0,
                "is_driving": "maybe",
            },
            {
                "vehicle_id": "v2",
                "timestamp": ts1,
                "longitude": -52.80,
                "latitude": 47.50,
                "bearing": 180,
                "speed": 0.0,
                "is_driving": "no",
            },
        ],
        now,
    )

    result = build_realtime_snapshot(db)
    assert len(result["features"]) == 2

    ids = {f["properties"]["vehicle_id"] for f in result["features"]}
    assert ids == {"v1", "v2"}

    v1 = next(f for f in result["features"] if f["properties"]["vehicle_id"] == "v1")
    v2 = next(f for f in result["features"] if f["properties"]["vehicle_id"] == "v2")

    assert len(v1["properties"]["trail"]) == 2
    assert len(v2["properties"]["trail"]) == 1

    db.close()
    os.unlink(path)
