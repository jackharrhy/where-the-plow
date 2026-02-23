from datetime import datetime, timezone

from where_the_plow.client import parse_aatracking_response, parse_avl_response


SAMPLE_RESPONSE = {
    "features": [
        {
            "attributes": {
                "ID": "281474984421544",
                "Description": "2222 SA PLOW TRUCK",
                "VehicleType": "SA PLOW TRUCK",
                "LocationDateTime": 1771491812000,
                "Bearing": 135,
                "Speed": "13.4",
                "isDriving": "maybe",
            },
            "geometry": {"x": -52.731, "y": 47.564},
        },
        {
            "attributes": {
                "ID": "281474992393189",
                "Description": "2037 LOADER",
                "VehicleType": "LOADER",
                "LocationDateTime": 1771492204000,
                "Bearing": 0,
                "Speed": "0.0",
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

    assert vehicles[0]["vehicle_id"] == "281474984421544"
    assert vehicles[0]["description"] == "2222 SA PLOW TRUCK"
    assert vehicles[0]["vehicle_type"] == "SA PLOW TRUCK"

    assert positions[0]["vehicle_id"] == "281474984421544"
    assert positions[0]["longitude"] == -52.731
    assert positions[0]["latitude"] == 47.564
    assert positions[0]["bearing"] == 135
    assert positions[0]["speed"] == 13.4
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


def test_parse_speed_conversion():
    """Speed comes as string from API, should be parsed to float."""
    resp = {
        "features": [
            {
                "attributes": {
                    "ID": "1",
                    "Description": "test",
                    "VehicleType": "LOADER",
                    "LocationDateTime": 1771491812000,
                    "Bearing": 0,
                    "Speed": "25.7",
                    "isDriving": "maybe",
                },
                "geometry": {"x": -52.0, "y": 47.0},
            }
        ]
    }
    _, positions = parse_avl_response(resp)
    assert positions[0]["speed"] == 25.7


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
    assert vehicles[0]["description"] == "21-21D"
    assert vehicles[0]["vehicle_type"] == "Large Snow Plow_Blue"

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
    assert positions[0]["timestamp"] == collected_at
    assert positions[0]["latitude"] == 48.986115
    assert positions[0]["speed"] is None


def test_parse_aatracking_empty():
    vehicles, positions = parse_aatracking_response([])
    assert vehicles == []
    assert positions == []
