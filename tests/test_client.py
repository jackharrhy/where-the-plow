from datetime import datetime, timedelta, timezone

from where_the_plow.client import (
    parse_aatracking_response,
    parse_avl_response,
    parse_geotab_response,
    parse_hitechmaps_response,
)


SAMPLE_RESPONSE = {
    "features": [
        {
            "attributes": {
                "OBJECTID": 6819,
                "VehicleType": "SA PLOW TRUCK",
                "LocationDateTime": 1771491812000,
                "Bearing": 135,
                "isDriving": "maybe",
            },
            "geometry": {"x": -52.731, "y": 47.564},
        },
        {
            "attributes": {
                "OBJECTID": 6820,
                "VehicleType": "LOADER",
                "LocationDateTime": 1771492204000,
                "Bearing": 0,
                "isDriving": "no",
            },
            "geometry": {"x": -52.726, "y": 47.595},
        },
    ]
}


def test_parse_avl_response():
    vehicles, positions = parse_avl_response(SAMPLE_RESPONSE)
    assert len(vehicles) == 2
    assert len(positions) == 2

    assert vehicles[0]["vehicle_id"] == "6819"
    assert vehicles[0]["description"] == "SA PLOW TRUCK"
    assert vehicles[0]["vehicle_type"] == "SA PLOW TRUCK"

    assert positions[0]["vehicle_id"] == "6819"
    assert positions[0]["longitude"] == -52.731
    assert positions[0]["latitude"] == 47.564
    assert positions[0]["bearing"] == 135
    assert positions[0]["speed"] is None
    assert positions[0]["is_driving"] == "maybe"
    assert positions[0]["timestamp"].year == 2026
    # Epoch 1771491812000 is NST local time; after +3:30 correction → 12:33:32 UTC
    assert positions[0]["timestamp"] == datetime(
        2026, 2, 19, 12, 33, 32, tzinfo=timezone.utc
    )


def test_parse_empty_response():
    vehicles, positions = parse_avl_response({"features": []})
    assert vehicles == []
    assert positions == []


SAMPLE_MT_PEARL_RESPONSE = [
    {
        "VEH_ID": 17186,
        "VEH_NAME": "21-21D",
        "VEH_UNIQUE_ID": "358013097968953",
        "VEH_EVENT_DATETIME": "2026-02-23T02:47:04",
        "VEH_EVENT_LATITUDE": 47.520455,
        "VEH_EVENT_LONGITUDE": -52.8394317,
        "VEH_EVENT_HEADING": 144.2,
        "LOO_TYPE": "HEAVY_TYPE",
        "LOO_CODE": "SnowPlowBlue_",
        "VEH_SEG_TYPE": "ST",
        "LOO_DESCRIPTION": "Large Snow Plow_Blue",
    }
]

SAMPLE_PROVINCIAL_RESPONSE = [
    {
        "VEH_ID": 15644,
        "VEH_NAME": "7452 F",
        "VEH_EVENT_LATITUDE": 48.986115,
        "VEH_EVENT_LONGITUDE": -55.55174,
        "VEH_EVENT_HEADING": 46.03,
        "LOO_TYPE": "TRUCK_TYPE",
        "LOO_CODE": "ng-Plow-Full-FS-Yellow_",
        "LOO_DESCRIPTION": "Large Plow Full Plow Side Yellow",
    }
]


def test_parse_aatracking_with_timestamp():
    """Mt Pearl response includes VEH_EVENT_DATETIME."""
    vehicles, positions = parse_aatracking_response(SAMPLE_MT_PEARL_RESPONSE)
    assert len(vehicles) == 1
    assert len(positions) == 1

    assert vehicles[0]["vehicle_id"] == "17186"
    assert vehicles[0]["description"] == "21-21D (Large Snow Plow_Blue)"
    assert vehicles[0]["vehicle_type"] == "LOADER"  # HEAVY_TYPE → LOADER

    assert positions[0]["vehicle_id"] == "17186"
    assert positions[0]["latitude"] == 47.520455
    assert positions[0]["longitude"] == -52.8394317
    assert positions[0]["bearing"] == 144
    assert positions[0]["speed"] is None
    assert positions[0]["is_driving"] is None
    assert positions[0]["timestamp"].year == 2026


def test_parse_aatracking_without_timestamp():
    """Provincial response has no VEH_EVENT_DATETIME — uses collected_at fallback."""
    collected_at = datetime(2026, 2, 23, 3, 0, 0, tzinfo=timezone.utc)
    vehicles, positions = parse_aatracking_response(
        SAMPLE_PROVINCIAL_RESPONSE, collected_at=collected_at
    )
    assert len(vehicles) == 1
    assert vehicles[0]["vehicle_type"] == "SA PLOW TRUCK"  # TRUCK_TYPE → SA PLOW TRUCK
    assert vehicles[0]["description"] == "7452 F (Large Plow Full Plow Side Yellow)"
    assert positions[0]["timestamp"] == collected_at
    assert positions[0]["latitude"] == 48.986115
    assert positions[0]["speed"] is None


def test_parse_aatracking_empty():
    vehicles, positions = parse_aatracking_response([])
    assert vehicles == []
    assert positions == []


def test_parse_aatracking_null_bearing():
    """VEH_EVENT_HEADING could be null or missing — should default to 0."""
    data = [
        {
            "VEH_ID": 999,
            "VEH_NAME": "test",
            "VEH_EVENT_LATITUDE": 47.5,
            "VEH_EVENT_LONGITUDE": -52.8,
            "VEH_EVENT_HEADING": None,
            "LOO_TYPE": "HEAVY_TYPE",
            "LOO_DESCRIPTION": "Large Loader",
        }
    ]
    _, positions = parse_aatracking_response(data)
    assert positions[0]["bearing"] == 0


def test_parse_aatracking_missing_veh_id():
    """Items without VEH_ID should be skipped, not crash."""
    data = [
        {
            "VEH_NAME": "ghost",
            "VEH_EVENT_LATITUDE": 47.5,
            "VEH_EVENT_LONGITUDE": -52.8,
            "VEH_EVENT_HEADING": 90,
            "LOO_TYPE": "TRUCK_TYPE",
            "LOO_DESCRIPTION": "Large Plow",
        },
        {
            "VEH_ID": 100,
            "VEH_NAME": "real",
            "VEH_EVENT_LATITUDE": 47.6,
            "VEH_EVENT_LONGITUDE": -52.7,
            "VEH_EVENT_HEADING": 180,
            "LOO_TYPE": "HEAVY_TYPE",
            "LOO_DESCRIPTION": "Large Loader",
        },
    ]
    vehicles, positions = parse_aatracking_response(data)
    assert len(vehicles) == 1
    assert vehicles[0]["vehicle_id"] == "100"
    assert len(positions) == 1


# ── HitechMaps (Paradise) parser tests ───────────────────────────────

SAMPLE_PARADISE_RESPONSE = [
    {
        "VID": "b19",
        "Latitude": "47.5292931",
        "longitude": "-52.8587875",
        "Bearing": "89",
        "IsDeviceCommunicating": "1",
        "Engine": "0",
        "Speed": "0",
        "DateTime": "2026-02-26 01:04:25",
        "Ignition": "1",
        "DeviceName": "070",
        "UpdateTime": "2026-02-26 01:05:39",
        "TruckType": "Loaders",
        "CurrentStateDuration": "00:00:01",
    },
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
        "CurrentStateDuration": "00:27:54",
    },
]


def test_parse_hitechmaps_response():
    vehicles, positions = parse_hitechmaps_response(SAMPLE_PARADISE_RESPONSE)
    assert len(vehicles) == 2
    assert len(positions) == 2

    # First vehicle: loader, ignition on but speed 0 → not driving
    assert vehicles[0]["vehicle_id"] == "b19"
    assert vehicles[0]["description"] == "070"
    assert vehicles[0]["vehicle_type"] == "LOADER"

    assert positions[0]["vehicle_id"] == "b19"
    assert positions[0]["latitude"] == 47.5292931
    assert positions[0]["longitude"] == -52.8587875
    assert positions[0]["bearing"] == 89
    assert positions[0]["speed"] == 0.0
    assert positions[0]["is_driving"] == "no"  # ignition on but speed 0

    # Timestamp: 2026-02-26 01:04:25 NST (UTC-3:30)
    nst = timezone(timedelta(hours=-3, minutes=-30))
    assert positions[0]["timestamp"] == datetime(2026, 2, 26, 1, 4, 25, tzinfo=nst)

    # Second vehicle: plow, ignition on and speed > 0 → driving
    assert vehicles[1]["vehicle_id"] == "b3C"
    assert vehicles[1]["vehicle_type"] == "SA PLOW TRUCK"

    assert positions[1]["speed"] == 26.0
    assert positions[1]["is_driving"] == "yes"  # ignition on and moving


def test_parse_hitechmaps_empty():
    vehicles, positions = parse_hitechmaps_response([])
    assert vehicles == []
    assert positions == []


def test_parse_hitechmaps_missing_fields():
    """Items with missing optional fields should still parse with defaults."""
    data = [
        {
            "VID": "b99",
            "Latitude": "47.5",
            "longitude": "-52.8",
        }
    ]
    vehicles, positions = parse_hitechmaps_response(data)
    assert len(vehicles) == 1
    assert vehicles[0]["vehicle_id"] == "b99"
    assert vehicles[0]["vehicle_type"] == "Unknown"
    assert positions[0]["bearing"] == 0
    assert positions[0]["speed"] == 0.0
    assert positions[0]["is_driving"] == "no"


def test_parse_hitechmaps_bad_item_skipped():
    """Completely malformed items should be skipped, not crash."""
    data = [
        "not a dict",
        {
            "VID": "b42",
            "Latitude": "47.5",
            "longitude": "-52.8",
            "Speed": "15",
            "Ignition": "1",
            "TruckType": "Plows",
            "DeviceName": "042",
        },
    ]
    vehicles, positions = parse_hitechmaps_response(data)
    assert len(vehicles) == 1
    assert vehicles[0]["vehicle_id"] == "b42"
    assert positions[0]["is_driving"] == "yes"


# ── Geotab Citizen Insights (CBS) parser tests ──────────────────────

SAMPLE_CBS_RESPONSE = {
    "b21": [-52.9353294, 47.5177231],
    "bBB": [-52.9379311, 47.5386467],
    "b42": [-52.9595337, 47.5173874],
}


def test_parse_geotab_response():
    collected_at = datetime(2026, 2, 26, 1, 0, 0, tzinfo=timezone.utc)
    vehicles, positions = parse_geotab_response(SAMPLE_CBS_RESPONSE, collected_at)
    assert len(vehicles) == 3
    assert len(positions) == 3

    # Check first vehicle
    ids = {v["vehicle_id"] for v in vehicles}
    assert ids == {"b21", "bBB", "b42"}

    # All should be SA PLOW TRUCK (only plow data in this source)
    for v in vehicles:
        assert v["vehicle_type"] == "SA PLOW TRUCK"
        assert v["description"] == v["vehicle_id"]

    # Check coordinates for b21
    b21_pos = next(p for p in positions if p["vehicle_id"] == "b21")
    assert b21_pos["longitude"] == -52.9353294
    assert b21_pos["latitude"] == 47.5177231
    assert b21_pos["timestamp"] == collected_at
    assert b21_pos["bearing"] == 0
    assert b21_pos["speed"] is None
    assert b21_pos["is_driving"] is None


def test_parse_geotab_empty():
    vehicles, positions = parse_geotab_response({})
    assert vehicles == []
    assert positions == []


def test_parse_geotab_bad_coords_skipped():
    """Entries with invalid coordinates should be silently skipped."""
    data = {
        "good": [-52.9, 47.5],
        "bad_list": [None, None],
        "short": [-52.9],
        "not_list": "garbage",
    }
    vehicles, positions = parse_geotab_response(data)
    assert len(vehicles) == 1
    assert vehicles[0]["vehicle_id"] == "good"
