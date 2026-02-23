import os
import tempfile

import pytest

from where_the_plow.db import Database
from where_the_plow.collector import process_poll


SAMPLE_AVL_RESPONSE = {
    "features": [
        {
            "attributes": {
                "ID": "v1",
                "Description": "2222 SA PLOW TRUCK",
                "VehicleType": "SA PLOW TRUCK",
                "LocationDateTime": 1771491812000,
                "Bearing": 135,
                "Speed": "13.4",
                "isDriving": "maybe",
            },
            "geometry": {"x": -52.731, "y": 47.564},
        },
    ]
}

SAMPLE_AATRACKING_RESPONSE = [
    {
        "VEH_ID": 17186,
        "VEH_NAME": "21-21D",
        "VEH_EVENT_DATETIME": "2026-02-23T02:47:04",
        "VEH_EVENT_LATITUDE": 47.52,
        "VEH_EVENT_LONGITUDE": -52.84,
        "VEH_EVENT_HEADING": 144,
        "LOO_TYPE": "HEAVY_TYPE",
        "LOO_DESCRIPTION": "Large Snow Plow_Blue",
    }
]


def make_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.unlink(path)
    db = Database(path)
    db.init()
    return db, path


def test_process_poll_avl():
    db, path = make_db()
    inserted = process_poll(db, SAMPLE_AVL_RESPONSE, source="st_johns", parser="avl")
    assert inserted == 1
    row = db.conn.execute(
        "SELECT source FROM positions WHERE vehicle_id='v1'"
    ).fetchone()
    assert row[0] == "st_johns"
    db.close()
    os.unlink(path)


def test_process_poll_aatracking():
    db, path = make_db()
    inserted = process_poll(
        db, SAMPLE_AATRACKING_RESPONSE, source="mt_pearl", parser="aatracking"
    )
    assert inserted == 1
    row = db.conn.execute(
        "SELECT source FROM positions WHERE vehicle_id='17186'"
    ).fetchone()
    assert row[0] == "mt_pearl"
    db.close()
    os.unlink(path)


def test_process_poll_deduplicates():
    db, path = make_db()
    inserted1 = process_poll(db, SAMPLE_AVL_RESPONSE, source="st_johns", parser="avl")
    inserted2 = process_poll(db, SAMPLE_AVL_RESPONSE, source="st_johns", parser="avl")
    assert inserted1 == 1
    assert inserted2 == 0
    total = db.conn.execute("SELECT count(*) FROM positions").fetchone()[0]
    assert total == 1
    db.close()
    os.unlink(path)


def test_process_poll_unknown_parser():
    db, path = make_db()
    with pytest.raises(ValueError, match="Unknown parser"):
        process_poll(db, {}, source="test", parser="nonexistent")
    db.close()
    os.unlink(path)
