# tests/test_db.py
import os
import tempfile
from datetime import datetime, timezone

from where_the_plow.db import Database


def make_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.unlink(path)  # DuckDB needs to create the file itself
    db = Database(path)
    db.init()
    return db, path


def test_init_creates_tables():
    db, path = make_db()
    tables = db.conn.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema='main'"
    ).fetchall()
    table_names = {t[0] for t in tables}
    assert "vehicles" in table_names
    assert "positions" in table_names
    assert "viewports" in table_names
    db.close()
    os.unlink(path)


def test_insert_viewport():
    db, path = make_db()
    db.insert_viewport(
        zoom=14.5,
        center_lng=-52.73,
        center_lat=47.56,
        sw_lng=-52.75,
        sw_lat=47.55,
        ne_lng=-52.71,
        ne_lat=47.57,
    )
    row = db.conn.execute(
        "SELECT zoom, center_lng, center_lat FROM viewports"
    ).fetchone()
    assert row is not None
    assert row[0] == 14.5  # zoom
    assert row[1] == -52.73  # center_lng
    assert row[2] == 47.56  # center_lat
    db.close()
    os.unlink(path)


def test_get_coverage_trails_gap_splitting():
    """Gaps > 2 minutes should split into separate trail segments."""
    db, path = make_db()
    now = datetime.now(timezone.utc)

    db.upsert_vehicles(
        [{"vehicle_id": "v1", "description": "Plow 1", "vehicle_type": "LOADER"}],
        now,
    )
    # Two clusters of positions separated by a 5-minute gap
    positions = [
        # Cluster 1: t=0s, t=30s, t=60s
        {
            "vehicle_id": "v1",
            "timestamp": datetime(2026, 2, 19, 12, 0, 0, tzinfo=timezone.utc),
            "longitude": -52.73,
            "latitude": 47.56,
            "bearing": 0,
            "speed": 10.0,
            "is_driving": "maybe",
        },
        {
            "vehicle_id": "v1",
            "timestamp": datetime(2026, 2, 19, 12, 0, 30, tzinfo=timezone.utc),
            "longitude": -52.74,
            "latitude": 47.57,
            "bearing": 0,
            "speed": 10.0,
            "is_driving": "maybe",
        },
        {
            "vehicle_id": "v1",
            "timestamp": datetime(2026, 2, 19, 12, 1, 0, tzinfo=timezone.utc),
            "longitude": -52.75,
            "latitude": 47.58,
            "bearing": 0,
            "speed": 10.0,
            "is_driving": "maybe",
        },
        # 5-minute gap here
        # Cluster 2: t=6m, t=6m30s, t=7m
        {
            "vehicle_id": "v1",
            "timestamp": datetime(2026, 2, 19, 12, 6, 0, tzinfo=timezone.utc),
            "longitude": -52.80,
            "latitude": 47.50,
            "bearing": 0,
            "speed": 15.0,
            "is_driving": "maybe",
        },
        {
            "vehicle_id": "v1",
            "timestamp": datetime(2026, 2, 19, 12, 6, 30, tzinfo=timezone.utc),
            "longitude": -52.81,
            "latitude": 47.51,
            "bearing": 0,
            "speed": 15.0,
            "is_driving": "maybe",
        },
        {
            "vehicle_id": "v1",
            "timestamp": datetime(2026, 2, 19, 12, 7, 0, tzinfo=timezone.utc),
            "longitude": -52.82,
            "latitude": 47.52,
            "bearing": 0,
            "speed": 15.0,
            "is_driving": "maybe",
        },
    ]
    db.insert_positions(positions, now)

    since = datetime(2026, 2, 19, 12, 0, 0, tzinfo=timezone.utc)
    until = datetime(2026, 2, 19, 12, 7, 0, tzinfo=timezone.utc)
    trails = db.get_coverage_trails(since=since, until=until)

    # Should produce 2 trail segments, both for v1
    assert len(trails) == 2
    assert all(t["vehicle_id"] == "v1" for t in trails)
    assert len(trails[0]["coordinates"]) == 3  # cluster 1
    assert len(trails[1]["coordinates"]) == 3  # cluster 2

    db.close()
    os.unlink(path)


def test_insert_positions_dedup():
    db, path = make_db()
    now = datetime.now(timezone.utc)
    ts = datetime(2026, 2, 19, 12, 0, 0, tzinfo=timezone.utc)

    positions = [
        {
            "vehicle_id": "v1",
            "timestamp": ts,
            "longitude": -52.73,
            "latitude": 47.56,
            "bearing": 135,
            "speed": 13.4,
            "is_driving": "maybe",
        },
    ]

    inserted = db.insert_positions(positions, now)
    assert inserted == 1

    # Same data again — should be deduped
    inserted = db.insert_positions(positions, now)
    assert inserted == 0

    total = db.conn.execute("SELECT count(*) FROM positions").fetchone()[0]
    assert total == 1

    db.close()
    os.unlink(path)


def test_init_loads_spatial_extension():
    db, path = make_db()
    result = db.conn.execute("SELECT ST_AsText(ST_Point(1.0, 2.0))").fetchone()
    assert result[0] == "POINT (1 2)"
    db.close()
    os.unlink(path)


def test_positions_has_geom_column():
    db, path = make_db()
    cols = db.conn.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name='positions'"
    ).fetchall()
    col_names = {c[0] for c in cols}
    assert "geom" in col_names
    db.close()
    os.unlink(path)


def test_insert_positions_populates_geom():
    db, path = make_db()
    now = datetime.now(timezone.utc)
    ts = datetime(2026, 2, 19, 12, 0, 0, tzinfo=timezone.utc)
    positions = [
        {
            "vehicle_id": "v1",
            "timestamp": ts,
            "longitude": -52.73,
            "latitude": 47.56,
            "bearing": 135,
            "speed": 13.4,
            "is_driving": "maybe",
        },
    ]
    db.insert_positions(positions, now)
    row = db.conn.execute(
        "SELECT ST_X(geom), ST_Y(geom) FROM positions WHERE vehicle_id='v1'"
    ).fetchone()
    assert abs(row[0] - (-52.73)) < 0.001
    assert abs(row[1] - 47.56) < 0.001
    db.close()
    os.unlink(path)


def test_get_stats_empty():
    db, path = make_db()
    stats = db.get_stats()
    assert stats["total_positions"] == 0
    assert stats["total_vehicles"] == 0
    assert stats["db_size_bytes"] is not None
    assert stats["db_size_bytes"] > 0
    db.close()
    os.unlink(path)


def test_get_latest_positions():
    db, path = make_db()
    now = datetime.now(timezone.utc)
    ts1 = datetime(2026, 2, 19, 12, 0, 0, tzinfo=timezone.utc)
    ts2 = datetime(2026, 2, 19, 12, 0, 6, tzinfo=timezone.utc)

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
                "speed": 0.0,
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
                "speed": 5.0,
                "is_driving": "no",
            },
        ],
        now,
    )

    features = db.get_latest_positions(limit=200)
    assert len(features) == 2
    v1 = next(f for f in features if f["vehicle_id"] == "v1")
    assert abs(v1["longitude"] - (-52.74)) < 0.001

    db.close()
    os.unlink(path)


def test_get_latest_positions_pagination():
    db, path = make_db()
    now = datetime.now(timezone.utc)
    ts = datetime(2026, 2, 19, 12, 0, 0, tzinfo=timezone.utc)
    db.upsert_vehicles(
        [
            {"vehicle_id": "v1", "description": "Plow 1", "vehicle_type": "LOADER"},
            {"vehicle_id": "v2", "description": "Plow 2", "vehicle_type": "LOADER"},
        ],
        now,
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
                "is_driving": "maybe",
            },
            {
                "vehicle_id": "v2",
                "timestamp": ts,
                "longitude": -52.80,
                "latitude": 47.50,
                "bearing": 0,
                "speed": 0.0,
                "is_driving": "maybe",
            },
        ],
        now,
    )

    page1 = db.get_latest_positions(limit=1)
    assert len(page1) == 1

    db.close()
    os.unlink(path)


def test_get_nearby_vehicles():
    db, path = make_db()
    now = datetime.now(timezone.utc)
    ts = datetime(2026, 2, 19, 12, 0, 0, tzinfo=timezone.utc)
    db.upsert_vehicles(
        [
            {"vehicle_id": "v1", "description": "Near", "vehicle_type": "LOADER"},
            {"vehicle_id": "v2", "description": "Far", "vehicle_type": "LOADER"},
        ],
        now,
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
                "is_driving": "maybe",
            },
            {
                "vehicle_id": "v2",
                "timestamp": ts,
                "longitude": -53.00,
                "latitude": 47.00,
                "bearing": 0,
                "speed": 0.0,
                "is_driving": "maybe",
            },
        ],
        now,
    )

    results = db.get_nearby_vehicles(lat=47.56, lng=-52.73, radius_m=1000, limit=200)
    assert len(results) == 1
    assert results[0]["vehicle_id"] == "v1"

    db.close()
    os.unlink(path)


def test_get_vehicle_history():
    db, path = make_db()
    now = datetime.now(timezone.utc)
    ts1 = datetime(2026, 2, 19, 12, 0, 0, tzinfo=timezone.utc)
    ts2 = datetime(2026, 2, 19, 12, 0, 6, tzinfo=timezone.utc)
    ts3 = datetime(2026, 2, 19, 12, 0, 12, tzinfo=timezone.utc)

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
                "speed": 0.0,
                "is_driving": "maybe",
            },
            {
                "vehicle_id": "v1",
                "timestamp": ts2,
                "longitude": -52.74,
                "latitude": 47.57,
                "bearing": 90,
                "speed": 5.0,
                "is_driving": "maybe",
            },
            {
                "vehicle_id": "v1",
                "timestamp": ts3,
                "longitude": -52.75,
                "latitude": 47.58,
                "bearing": 180,
                "speed": 10.0,
                "is_driving": "maybe",
            },
        ],
        now,
    )

    history = db.get_vehicle_history("v1", since=ts1, until=ts3, limit=200)
    assert len(history) == 3
    assert history[0]["timestamp"] <= history[1]["timestamp"]

    db.close()
    os.unlink(path)


def test_get_coverage():
    db, path = make_db()
    now = datetime.now(timezone.utc)
    ts1 = datetime(2026, 2, 19, 12, 0, 0, tzinfo=timezone.utc)
    ts2 = datetime(2026, 2, 19, 12, 0, 6, tzinfo=timezone.utc)

    db.upsert_vehicles(
        [
            {"vehicle_id": "v1", "description": "Plow 1", "vehicle_type": "LOADER"},
            {"vehicle_id": "v2", "description": "Plow 2", "vehicle_type": "LOADER"},
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
                "speed": 0.0,
                "is_driving": "maybe",
            },
            {
                "vehicle_id": "v2",
                "timestamp": ts2,
                "longitude": -52.80,
                "latitude": 47.50,
                "bearing": 0,
                "speed": 5.0,
                "is_driving": "maybe",
            },
        ],
        now,
    )

    coverage = db.get_coverage(since=ts1, until=ts2, limit=200)
    assert len(coverage) == 2

    db.close()
    os.unlink(path)


def test_get_coverage_trails():
    db, path = make_db()
    now = datetime.now(timezone.utc)
    ts1 = datetime(2026, 2, 19, 12, 0, 0, tzinfo=timezone.utc)
    ts2 = datetime(2026, 2, 19, 12, 0, 30, tzinfo=timezone.utc)
    ts3 = datetime(2026, 2, 19, 12, 1, 0, tzinfo=timezone.utc)

    db.upsert_vehicles(
        [
            {
                "vehicle_id": "v1",
                "description": "Plow 1",
                "vehicle_type": "TA PLOW TRUCK",
            },
            {"vehicle_id": "v2", "description": "Plow 2", "vehicle_type": "LOADER"},
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
                "speed": 10.0,
                "is_driving": "maybe",
            },
            {
                "vehicle_id": "v1",
                "timestamp": ts2,
                "longitude": -52.74,
                "latitude": 47.57,
                "bearing": 90,
                "speed": 15.0,
                "is_driving": "maybe",
            },
            {
                "vehicle_id": "v1",
                "timestamp": ts3,
                "longitude": -52.75,
                "latitude": 47.58,
                "bearing": 180,
                "speed": 20.0,
                "is_driving": "maybe",
            },
            # v2 has only one position — should be excluded (no trail)
            {
                "vehicle_id": "v2",
                "timestamp": ts1,
                "longitude": -52.80,
                "latitude": 47.50,
                "bearing": 0,
                "speed": 0.0,
                "is_driving": "no",
            },
        ],
        now,
    )

    trails = db.get_coverage_trails(since=ts1, until=ts3)
    assert len(trails) == 1  # only v1 has a trail
    trail = trails[0]
    assert trail["vehicle_id"] == "v1"
    assert trail["vehicle_type"] == "TA PLOW TRUCK"
    assert trail["description"] == "Plow 1"
    assert len(trail["coordinates"]) == 3
    assert len(trail["timestamps"]) == 3
    assert trail["coordinates"][0] == [-52.73, 47.56]
    assert trail["timestamps"][0] <= trail["timestamps"][1]

    db.close()
    os.unlink(path)


def test_get_coverage_trails_downsampling():
    """Positions closer than 30s apart should be downsampled."""
    db, path = make_db()
    now = datetime.now(timezone.utc)

    db.upsert_vehicles(
        [{"vehicle_id": "v1", "description": "Plow 1", "vehicle_type": "LOADER"}],
        now,
    )
    # Insert 10 positions 6s apart (total 54s span)
    positions = []
    for i in range(10):
        ts = datetime(2026, 2, 19, 12, 0, i * 6, tzinfo=timezone.utc)
        positions.append(
            {
                "vehicle_id": "v1",
                "timestamp": ts,
                "longitude": -52.73 + i * 0.001,
                "latitude": 47.56,
                "bearing": 0,
                "speed": 10.0,
                "is_driving": "maybe",
            }
        )
    db.insert_positions(positions, now)

    since = datetime(2026, 2, 19, 12, 0, 0, tzinfo=timezone.utc)
    until = datetime(2026, 2, 19, 12, 0, 54, tzinfo=timezone.utc)
    trails = db.get_coverage_trails(since=since, until=until)
    assert len(trails) == 1
    # With 30s downsampling: keep t=0, skip t=6..24, keep t=30, skip t=36..48, keep t=54
    # Should have ~3 points, not 10
    assert len(trails[0]["coordinates"]) < 10
    assert len(trails[0]["coordinates"]) >= 2

    db.close()
    os.unlink(path)


def test_get_latest_positions_with_trails_basic():
    """Each vehicle gets a trail array of [lng, lat] pairs, current position is the latest."""
    db, path = make_db()
    now = datetime.now(timezone.utc)
    ts1 = datetime(2026, 2, 19, 12, 0, 0, tzinfo=timezone.utc)
    ts2 = datetime(2026, 2, 19, 12, 0, 6, tzinfo=timezone.utc)
    ts3 = datetime(2026, 2, 19, 12, 0, 12, tzinfo=timezone.utc)

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

    results = db.get_latest_positions_with_trails(trail_points=6)
    assert len(results) == 1

    v1 = results[0]
    # Current position should be the latest
    assert abs(v1["longitude"] - (-52.75)) < 0.001
    assert abs(v1["latitude"] - 47.58) < 0.001
    assert v1["bearing"] == 180
    assert v1["speed"] == 15.0

    # Trail should contain all 3 positions in chronological order
    assert len(v1["trail"]) == 3
    assert v1["trail"][0] == [-52.73, 47.56]
    assert v1["trail"][1] == [-52.74, 47.57]
    assert v1["trail"][2] == [-52.75, 47.58]

    db.close()
    os.unlink(path)


def test_get_latest_positions_with_trails_multiple_vehicles():
    """Multiple vehicles each get their own independent trail."""
    db, path = make_db()
    now = datetime.now(timezone.utc)
    ts1 = datetime(2026, 2, 19, 12, 0, 0, tzinfo=timezone.utc)
    ts2 = datetime(2026, 2, 19, 12, 0, 6, tzinfo=timezone.utc)

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
            {
                "vehicle_id": "v2",
                "timestamp": ts2,
                "longitude": -52.81,
                "latitude": 47.51,
                "bearing": 270,
                "speed": 8.0,
                "is_driving": "maybe",
            },
        ],
        now,
    )

    results = db.get_latest_positions_with_trails(trail_points=6)
    assert len(results) == 2

    v1 = next(r for r in results if r["vehicle_id"] == "v1")
    v2 = next(r for r in results if r["vehicle_id"] == "v2")

    assert len(v1["trail"]) == 2
    assert len(v2["trail"]) == 2
    assert v1["trail"][0] == [-52.73, 47.56]
    assert v2["trail"][1] == [-52.81, 47.51]

    # Current position fields should reflect the latest position
    assert v1["vehicle_type"] == "LOADER"
    assert v2["vehicle_type"] == "SA PLOW TRUCK"

    db.close()
    os.unlink(path)


def test_get_latest_positions_with_trails_capped():
    """Trail is capped to trail_points most recent positions."""
    db, path = make_db()
    now = datetime.now(timezone.utc)

    db.upsert_vehicles(
        [{"vehicle_id": "v1", "description": "Plow 1", "vehicle_type": "LOADER"}], now
    )
    # Insert 10 positions
    positions = []
    for i in range(10):
        positions.append(
            {
                "vehicle_id": "v1",
                "timestamp": datetime(2026, 2, 19, 12, 0, i * 6, tzinfo=timezone.utc),
                "longitude": -52.73 + i * 0.01,
                "latitude": 47.56,
                "bearing": 0,
                "speed": 10.0,
                "is_driving": "maybe",
            }
        )
    db.insert_positions(positions, now)

    results = db.get_latest_positions_with_trails(trail_points=4)
    assert len(results) == 1
    v1 = results[0]

    # Should only have 4 trail points (the 4 most recent)
    assert len(v1["trail"]) == 4
    # Current position is the last inserted (i=9)
    assert abs(v1["longitude"] - (-52.73 + 9 * 0.01)) < 0.001
    # Trail should start from position i=6 (10 - 4 = 6th oldest)
    assert abs(v1["trail"][0][0] - (-52.73 + 6 * 0.01)) < 0.001

    db.close()
    os.unlink(path)


def test_get_latest_positions_with_trails_single_position():
    """A vehicle with only 1 position still gets a trail with 1 entry."""
    db, path = make_db()
    now = datetime.now(timezone.utc)
    ts = datetime(2026, 2, 19, 12, 0, 0, tzinfo=timezone.utc)

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
                "bearing": 45,
                "speed": 0.0,
                "is_driving": "no",
            },
        ],
        now,
    )

    results = db.get_latest_positions_with_trails(trail_points=6)
    assert len(results) == 1
    v1 = results[0]
    assert len(v1["trail"]) == 1
    assert v1["trail"][0] == [-52.73, 47.56]
    assert v1["bearing"] == 45

    db.close()
    os.unlink(path)


def test_get_latest_positions_with_trails_gap_filtering():
    """Gaps > 120s in the trail should truncate to only the contiguous recent segment."""
    db, path = make_db()
    now = datetime.now(timezone.utc)

    db.upsert_vehicles(
        [{"vehicle_id": "v1", "description": "Plow 1", "vehicle_type": "LOADER"}], now
    )
    # 5 positions: first two are close together, then a 5-minute gap, then three more
    positions = [
        {
            "vehicle_id": "v1",
            "timestamp": datetime(2026, 2, 19, 12, 0, 0, tzinfo=timezone.utc),
            "longitude": -52.73,
            "latitude": 47.56,
            "bearing": 0,
            "speed": 10.0,
            "is_driving": "maybe",
        },
        {
            "vehicle_id": "v1",
            "timestamp": datetime(2026, 2, 19, 12, 0, 30, tzinfo=timezone.utc),
            "longitude": -52.74,
            "latitude": 47.57,
            "bearing": 0,
            "speed": 10.0,
            "is_driving": "maybe",
        },
        # 5-minute gap here (300s > 120s threshold)
        {
            "vehicle_id": "v1",
            "timestamp": datetime(2026, 2, 19, 12, 5, 30, tzinfo=timezone.utc),
            "longitude": -52.80,
            "latitude": 47.50,
            "bearing": 90,
            "speed": 15.0,
            "is_driving": "maybe",
        },
        {
            "vehicle_id": "v1",
            "timestamp": datetime(2026, 2, 19, 12, 6, 0, tzinfo=timezone.utc),
            "longitude": -52.81,
            "latitude": 47.51,
            "bearing": 90,
            "speed": 15.0,
            "is_driving": "maybe",
        },
        {
            "vehicle_id": "v1",
            "timestamp": datetime(2026, 2, 19, 12, 6, 30, tzinfo=timezone.utc),
            "longitude": -52.82,
            "latitude": 47.52,
            "bearing": 90,
            "speed": 15.0,
            "is_driving": "maybe",
        },
    ]
    db.insert_positions(positions, now)

    results = db.get_latest_positions_with_trails(trail_points=10)
    assert len(results) == 1
    v1 = results[0]

    # Should only have the 3 positions after the gap (contiguous recent segment)
    assert len(v1["trail"]) == 3
    assert v1["trail"][0] == [-52.80, 47.50]
    assert v1["trail"][1] == [-52.81, 47.51]
    assert v1["trail"][2] == [-52.82, 47.52]

    # Current position should be the most recent
    assert abs(v1["longitude"] - (-52.82)) < 0.001

    db.close()
    os.unlink(path)


def test_source_column_exists():
    db, path = make_db()
    cols = db.conn.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name='positions'"
    ).fetchall()
    col_names = {c[0] for c in cols}
    assert "source" in col_names

    cols = db.conn.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name='vehicles'"
    ).fetchall()
    col_names = {c[0] for c in cols}
    assert "source" in col_names
    db.close()
    os.unlink(path)


def test_upsert_vehicles_with_source():
    db, path = make_db()
    now = datetime(2026, 2, 19, 12, 0, 0, tzinfo=timezone.utc)
    db.upsert_vehicles(
        [{"vehicle_id": "v1", "description": "Plow 1", "vehicle_type": "LOADER"}],
        now,
        source="mt_pearl",
    )
    row = db.conn.execute(
        "SELECT source FROM vehicles WHERE vehicle_id='v1'"
    ).fetchone()
    assert row[0] == "mt_pearl"
    db.close()
    os.unlink(path)


def test_insert_positions_with_source():
    db, path = make_db()
    now = datetime(2026, 2, 19, 12, 0, 0, tzinfo=timezone.utc)
    ts = datetime(2026, 2, 19, 12, 0, 0, tzinfo=timezone.utc)
    positions = [
        {
            "vehicle_id": "v1",
            "timestamp": ts,
            "longitude": -52.73,
            "latitude": 47.56,
            "bearing": 135,
            "speed": None,
            "is_driving": None,
        },
    ]
    inserted = db.insert_positions(positions, now, source="mt_pearl")
    assert inserted == 1
    row = db.conn.execute(
        "SELECT source FROM positions WHERE vehicle_id='v1'"
    ).fetchone()
    assert row[0] == "mt_pearl"
    db.close()
    os.unlink(path)


def test_same_vehicle_id_different_sources():
    db, path = make_db()
    now = datetime(2026, 2, 19, 12, 0, 0, tzinfo=timezone.utc)
    ts = datetime(2026, 2, 19, 12, 0, 0, tzinfo=timezone.utc)

    db.upsert_vehicles(
        [{"vehicle_id": "123", "description": "SJ Plow", "vehicle_type": "LOADER"}],
        now,
        source="st_johns",
    )
    db.upsert_vehicles(
        [{"vehicle_id": "123", "description": "MP Plow", "vehicle_type": "LOADER"}],
        now,
        source="mt_pearl",
    )
    count = db.conn.execute("SELECT count(*) FROM vehicles").fetchone()[0]
    assert count == 2

    db.insert_positions(
        [
            {
                "vehicle_id": "123",
                "timestamp": ts,
                "longitude": -52.73,
                "latitude": 47.56,
                "bearing": 0,
                "speed": 0.0,
                "is_driving": "maybe",
            }
        ],
        now,
        source="st_johns",
    )
    db.insert_positions(
        [
            {
                "vehicle_id": "123",
                "timestamp": ts,
                "longitude": -52.81,
                "latitude": 47.52,
                "bearing": 0,
                "speed": None,
                "is_driving": None,
            }
        ],
        now,
        source="mt_pearl",
    )
    count = db.conn.execute("SELECT count(*) FROM positions").fetchone()[0]
    assert count == 2
    db.close()
    os.unlink(path)


def test_get_latest_positions_with_source_filter():
    db, path = make_db()
    now = datetime(2026, 2, 19, 12, 0, 0, tzinfo=timezone.utc)
    ts = datetime(2026, 2, 19, 12, 0, 0, tzinfo=timezone.utc)

    db.upsert_vehicles(
        [{"vehicle_id": "v1", "description": "SJ", "vehicle_type": "LOADER"}],
        now,
        source="st_johns",
    )
    db.upsert_vehicles(
        [{"vehicle_id": "v2", "description": "MP", "vehicle_type": "LOADER"}],
        now,
        source="mt_pearl",
    )
    db.insert_positions(
        [
            {
                "vehicle_id": "v1",
                "timestamp": ts,
                "longitude": -52.73,
                "latitude": 47.56,
                "bearing": 0,
                "speed": 10.0,
                "is_driving": "maybe",
            }
        ],
        now,
        source="st_johns",
    )
    db.insert_positions(
        [
            {
                "vehicle_id": "v2",
                "timestamp": ts,
                "longitude": -52.81,
                "latitude": 47.52,
                "bearing": 0,
                "speed": None,
                "is_driving": None,
            }
        ],
        now,
        source="mt_pearl",
    )

    all_rows = db.get_latest_positions(limit=200)
    assert len(all_rows) == 2

    sj_rows = db.get_latest_positions(limit=200, source="st_johns")
    assert len(sj_rows) == 1
    assert sj_rows[0]["source"] == "st_johns"

    db.close()
    os.unlink(path)


def test_get_latest_positions_with_trails_no_gap():
    """When all positions are within the gap threshold, the full trail is returned."""
    db, path = make_db()
    now = datetime.now(timezone.utc)

    db.upsert_vehicles(
        [{"vehicle_id": "v1", "description": "Plow 1", "vehicle_type": "LOADER"}], now
    )
    # 4 positions all 30s apart (well within 120s threshold)
    from datetime import timedelta

    base = datetime(2026, 2, 19, 12, 0, 0, tzinfo=timezone.utc)
    positions = [
        {
            "vehicle_id": "v1",
            "timestamp": base + timedelta(seconds=i * 30),
            "longitude": -52.73 + i * 0.01,
            "latitude": 47.56,
            "bearing": 0,
            "speed": 10.0,
            "is_driving": "maybe",
        }
        for i in range(4)
    ]
    db.insert_positions(positions, now)

    results = db.get_latest_positions_with_trails(trail_points=10)
    assert len(results) == 1
    # All 4 positions should be in the trail (no gaps to truncate)
    assert len(results[0]["trail"]) == 4

    db.close()
    os.unlink(path)


def test_migration_from_pre_source_schema():
    """Simulate migrating a production DB that has the old schema (no source column).

    Creates a DB with the old schema (vehicle PK=vehicle_id, position PK=(vehicle_id, timestamp)),
    populates it with data, then runs Database.init() which should migrate to the new schema
    with composite PKs including source.
    """
    import duckdb

    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.unlink(path)

    # Step 1: Create OLD schema (pre-multi-source) directly with DuckDB
    conn = duckdb.connect(path)
    conn.execute("INSTALL spatial")
    conn.execute("LOAD spatial")
    conn.execute("""
        CREATE TABLE vehicles (
            vehicle_id    VARCHAR PRIMARY KEY,
            description   VARCHAR,
            vehicle_type  VARCHAR,
            first_seen    TIMESTAMPTZ NOT NULL,
            last_seen     TIMESTAMPTZ NOT NULL
        )
    """)
    conn.execute("CREATE SEQUENCE IF NOT EXISTS positions_seq")
    conn.execute("""
        CREATE TABLE positions (
            id            BIGINT DEFAULT nextval('positions_seq'),
            vehicle_id    VARCHAR NOT NULL,
            timestamp     TIMESTAMPTZ NOT NULL,
            collected_at  TIMESTAMPTZ NOT NULL,
            longitude     DOUBLE NOT NULL,
            latitude      DOUBLE NOT NULL,
            geom          GEOMETRY,
            bearing       INTEGER,
            speed         DOUBLE,
            is_driving    VARCHAR,
            PRIMARY KEY (vehicle_id, timestamp)
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_positions_time_geo
            ON positions (timestamp, latitude, longitude)
    """)
    conn.execute("CREATE SEQUENCE IF NOT EXISTS viewports_seq")
    conn.execute("""
        CREATE TABLE viewports (
            id          BIGINT DEFAULT nextval('viewports_seq') PRIMARY KEY,
            timestamp   TIMESTAMPTZ NOT NULL DEFAULT now(),
            ip          VARCHAR,
            user_agent  VARCHAR,
            zoom        DOUBLE NOT NULL,
            center_lng  DOUBLE NOT NULL,
            center_lat  DOUBLE NOT NULL,
            sw_lng      DOUBLE NOT NULL,
            sw_lat      DOUBLE NOT NULL,
            ne_lng      DOUBLE NOT NULL,
            ne_lat      DOUBLE NOT NULL
        )
    """)
    conn.execute("CREATE SEQUENCE IF NOT EXISTS signups_seq")
    conn.execute("""
        CREATE TABLE signups (
            id              BIGINT DEFAULT nextval('signups_seq') PRIMARY KEY,
            timestamp       TIMESTAMPTZ NOT NULL DEFAULT now(),
            email           VARCHAR NOT NULL,
            ip              VARCHAR,
            user_agent      VARCHAR,
            notify_plow     BOOLEAN NOT NULL DEFAULT FALSE,
            notify_projects BOOLEAN NOT NULL DEFAULT FALSE,
            notify_siliconharbour BOOLEAN NOT NULL DEFAULT FALSE,
            note            VARCHAR
        )
    """)

    # Populate with sample data
    conn.execute("""
        INSERT INTO vehicles VALUES
            ('v1', 'Plow 1', 'SA PLOW TRUCK', '2026-02-19T00:00:00Z', '2026-02-19T12:00:00Z'),
            ('v2', 'Loader 1', 'LOADER', '2026-02-19T00:00:00Z', '2026-02-19T12:00:00Z')
    """)
    conn.execute("""
        INSERT INTO positions (vehicle_id, timestamp, collected_at, longitude, latitude, geom, bearing, speed, is_driving) VALUES
            ('v1', '2026-02-19T12:00:00Z', '2026-02-19T12:00:00Z', -52.73, 47.56, ST_Point(-52.73, 47.56), 135, 13.4, 'maybe'),
            ('v2', '2026-02-19T12:00:00Z', '2026-02-19T12:00:00Z', -52.80, 47.50, ST_Point(-52.80, 47.50), 0, 0.0, 'no')
    """)
    conn.close()

    # Step 2: Run Database.init() which should migrate the schema
    db = Database(path)
    db.init()

    # Step 3: Verify migration results

    # Source column exists on both tables
    veh_cols = {
        r[0]
        for r in db.conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name='vehicles'"
        ).fetchall()
    }
    assert "source" in veh_cols, "vehicles should have source column after migration"

    pos_cols = {
        r[0]
        for r in db.conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name='positions'"
        ).fetchall()
    }
    assert "source" in pos_cols, "positions should have source column after migration"

    # All existing data backfilled with 'st_johns'
    v_sources = db.conn.execute("SELECT DISTINCT source FROM vehicles").fetchall()
    assert v_sources == [("st_johns",)]

    p_sources = db.conn.execute("SELECT DISTINCT source FROM positions").fetchall()
    assert p_sources == [("st_johns",)]

    # Row counts preserved
    assert db.conn.execute("SELECT count(*) FROM vehicles").fetchone()[0] == 2
    assert db.conn.execute("SELECT count(*) FROM positions").fetchone()[0] == 2

    # PKs are correct (composite including source)
    veh_pk = db.conn.execute(
        "SELECT constraint_text FROM duckdb_constraints() "
        "WHERE table_name='vehicles' AND constraint_type='PRIMARY KEY'"
    ).fetchone()
    assert "source" in veh_pk[0], f"vehicles PK should include source: {veh_pk[0]}"

    pos_pk = db.conn.execute(
        "SELECT constraint_text FROM duckdb_constraints() "
        "WHERE table_name='positions' AND constraint_type='PRIMARY KEY'"
    ).fetchone()
    assert "source" in pos_pk[0], f"positions PK should include source: {pos_pk[0]}"

    # Cross-source inserts work
    now = datetime(2026, 2, 23, 0, 0, 0, tzinfo=timezone.utc)
    db.upsert_vehicles(
        [{"vehicle_id": "v1", "description": "MP Plow", "vehicle_type": "LOADER"}],
        now,
        source="mt_pearl",
    )
    v_count = db.conn.execute(
        "SELECT count(*) FROM vehicles WHERE vehicle_id='v1'"
    ).fetchone()[0]
    assert v_count == 2, "Same vehicle_id with different sources should create 2 rows"

    ts = datetime(2026, 2, 19, 12, 0, 0, tzinfo=timezone.utc)
    db.insert_positions(
        [
            {
                "vehicle_id": "v1",
                "timestamp": ts,
                "longitude": -52.81,
                "latitude": 47.52,
                "bearing": 0,
                "speed": None,
                "is_driving": None,
            }
        ],
        now,
        source="mt_pearl",
    )
    p_count = db.conn.execute(
        "SELECT count(*) FROM positions WHERE vehicle_id='v1'"
    ).fetchone()[0]
    assert p_count == 2, (
        "Same vehicle_id+timestamp with different sources should create 2 rows"
    )

    # Existing query methods still work with source filter
    rows = db.get_latest_positions(limit=200, source="st_johns")
    assert len(rows) == 2
    assert all(r["source"] == "st_johns" for r in rows)

    rows = db.get_latest_positions(limit=200, source="mt_pearl")
    assert len(rows) == 1
    assert rows[0]["source"] == "mt_pearl"

    db.close()
    os.unlink(path)


def test_migration_is_idempotent():
    """Running init() twice should not fail or duplicate data."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.unlink(path)

    db = Database(path)
    db.init()

    now = datetime(2026, 2, 23, 0, 0, 0, tzinfo=timezone.utc)
    db.upsert_vehicles(
        [{"vehicle_id": "v1", "description": "Plow", "vehicle_type": "LOADER"}],
        now,
    )
    db.insert_positions(
        [
            {
                "vehicle_id": "v1",
                "timestamp": now,
                "longitude": -52.73,
                "latitude": 47.56,
                "bearing": 0,
                "speed": 0.0,
                "is_driving": "no",
            }
        ],
        now,
    )

    # Run init again — should be a no-op since source column already exists
    db.init()

    assert db.conn.execute("SELECT count(*) FROM vehicles").fetchone()[0] == 1
    assert db.conn.execute("SELECT count(*) FROM positions").fetchone()[0] == 1

    db.close()
    os.unlink(path)
