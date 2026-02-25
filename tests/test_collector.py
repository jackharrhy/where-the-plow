import asyncio
import os
import tempfile
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from where_the_plow.client import fetch_source
from where_the_plow.collector import poll_source, process_poll
from where_the_plow.db import Database
from where_the_plow.source_config import SourceConfig


SAMPLE_AVL_RESPONSE = {
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
        "SELECT source FROM positions WHERE vehicle_id='6819'"
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


# ── Helpers for async poll_source tests ──────────────────────────────


def _test_source_config(**overrides) -> SourceConfig:
    """Build a SourceConfig for testing with sensible defaults."""
    defaults = dict(
        name="test_source",
        display_name="Test Source",
        poll_interval=0,
        parser="aatracking",
        api_url="https://fake.example.com/api",
        center=(-52.8, 47.5),
        zoom=12,
    )
    defaults.update(overrides)
    return SourceConfig(**defaults)


def _make_aatracking_response(vehicle_id=17186, heading=90):
    """Build a valid AATracking response for one vehicle."""
    return [
        {
            "VEH_ID": vehicle_id,
            "VEH_NAME": f"test-{vehicle_id}",
            "VEH_EVENT_DATETIME": "2026-02-23T02:47:04",
            "VEH_EVENT_LATITUDE": 47.52,
            "VEH_EVENT_LONGITUDE": -52.84,
            "VEH_EVENT_HEADING": heading,
            "LOO_TYPE": "HEAVY_TYPE",
            "LOO_DESCRIPTION": "Large Loader",
        }
    ]


async def _run_poll_cycles(db, store, config, side_effects):
    """Run poll_source with mocked fetch_source, cancelling after N cycles.

    side_effects: list of (return_value_or_exception) for each poll cycle.
    The task is cancelled after all side_effects have been consumed.
    """
    target_cycles = len(side_effects)
    call_count = 0
    done_event = asyncio.Event()

    async def fake_fetch(client, source):
        nonlocal call_count
        idx = min(call_count, target_cycles - 1)
        call_count += 1
        effect = side_effects[idx]
        if isinstance(effect, Exception):
            raise effect
        return effect

    original_sleep = asyncio.sleep

    async def fake_sleep(seconds):
        # After each cycle completes (sleep is called at end of loop body),
        # check if we've done enough cycles
        if call_count >= target_cycles:
            done_event.set()
            # Block forever — we'll be cancelled
            await original_sleep(999)
        # Otherwise yield control briefly so the loop continues
        await original_sleep(0)

    with (
        patch("where_the_plow.collector.fetch_source", side_effect=fake_fetch),
        patch("where_the_plow.collector.asyncio.sleep", side_effect=fake_sleep),
    ):
        task = asyncio.create_task(poll_source(db, store, config))

        # Wait for all cycles to complete
        await asyncio.wait_for(done_event.wait(), timeout=5.0)

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    return call_count


# ── Async tests: poll_source recovery behavior ──────────────────────


async def test_poll_source_recovers_from_http_error():
    """A single HTTP error should not kill the poll loop — it logs and retries."""
    db, path = make_db()
    store = {}
    config = _test_source_config()

    effects = [
        httpx.HTTPStatusError(
            "Server Error",
            request=httpx.Request("GET", "http://x"),
            response=httpx.Response(500),
        ),
        _make_aatracking_response(),  # second poll succeeds
    ]

    cycles = await _run_poll_cycles(db, store, config, effects)

    assert cycles == 2, "Should have completed 2 poll cycles"
    # After recovery, data should be in the DB from the second successful poll
    count = db.conn.execute("SELECT count(*) FROM positions").fetchone()[0]
    assert count == 1, "Successful poll after error should insert data"

    db.close()
    os.unlink(path)


async def test_poll_source_recovers_from_timeout():
    """Network timeouts should not kill the poll loop."""
    db, path = make_db()
    store = {}
    config = _test_source_config()

    effects = [
        httpx.ConnectTimeout("Connection timed out"),
        httpx.ReadTimeout("Read timed out"),
        _make_aatracking_response(),  # third poll succeeds
    ]

    cycles = await _run_poll_cycles(db, store, config, effects)

    assert cycles == 3
    count = db.conn.execute("SELECT count(*) FROM positions").fetchone()[0]
    assert count == 1

    db.close()
    os.unlink(path)


async def test_poll_source_recovers_from_malformed_json():
    """If the API returns valid HTTP but unparseable data, poll should continue."""
    db, path = make_db()
    store = {}
    config = _test_source_config()

    # A response that's valid JSON but not the expected list format
    # will cause process_poll/parser to crash — poll_source should catch it
    effects = [
        {"unexpected": "format"},  # not a list — will cause TypeError in parser
        _make_aatracking_response(),
    ]

    cycles = await _run_poll_cycles(db, store, config, effects)

    assert cycles == 2
    count = db.conn.execute("SELECT count(*) FROM positions").fetchone()[0]
    assert count == 1

    db.close()
    os.unlink(path)


async def test_poll_source_updates_store_on_success():
    """Successful polls should update store['realtime'][source_name]."""
    db, path = make_db()
    store = {}
    config = _test_source_config()

    effects = [_make_aatracking_response()]

    await _run_poll_cycles(db, store, config, effects)

    assert "realtime" in store
    assert "test_source" in store["realtime"]
    snapshot = store["realtime"]["test_source"]
    assert snapshot["type"] == "FeatureCollection"
    assert len(snapshot["features"]) == 1

    db.close()
    os.unlink(path)


async def test_poll_source_store_not_updated_on_error():
    """Failed polls should not corrupt the store — previous snapshot stays."""
    db, path = make_db()
    store = {
        "realtime": {
            "test_source": {"type": "FeatureCollection", "features": [{"old": True}]}
        }
    }
    config = _test_source_config()

    effects = [
        httpx.HTTPStatusError(
            "Error",
            request=httpx.Request("GET", "http://x"),
            response=httpx.Response(502),
        ),
    ]

    await _run_poll_cycles(db, store, config, effects)

    # Old snapshot should be preserved, not wiped
    assert store["realtime"]["test_source"]["features"] == [{"old": True}]

    db.close()
    os.unlink(path)


async def test_poll_source_cancellation_is_clean():
    """CancelledError should propagate — not be swallowed by the broad except."""
    db, path = make_db()
    store = {}
    config = _test_source_config()

    # Provide a response that will succeed, but we cancel immediately
    async def slow_fetch(client, source):
        await asyncio.sleep(100)  # will be cancelled
        return _make_aatracking_response()

    with patch("where_the_plow.collector.fetch_source", side_effect=slow_fetch):
        task = asyncio.create_task(poll_source(db, store, config))
        await asyncio.sleep(0)  # let task start
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    db.close()
    os.unlink(path)


# ── Async test: fetch_source behavior ────────────────────────────────


async def test_fetch_source_raises_on_http_error():
    """fetch_source should propagate HTTP errors (raise_for_status)."""
    config = _test_source_config(
        parser="aatracking", api_url="https://fake.example.com/api"
    )

    mock_response = httpx.Response(500, request=httpx.Request("GET", config.api_url))
    client = AsyncMock(spec=httpx.AsyncClient)
    client.get = AsyncMock(return_value=mock_response)

    with pytest.raises(httpx.HTTPStatusError):
        await fetch_source(client, config)


async def test_fetch_source_avl_sends_referer():
    """AVL sources should send the Referer header."""
    config = _test_source_config(
        parser="avl",
        api_url="https://map.stjohns.ca/mapsrv/rest/services/AVL/MapServer/0/query",
        referer="https://map.stjohns.ca/avl/",
    )

    mock_response = httpx.Response(
        200,
        json={"features": []},
        request=httpx.Request("GET", config.api_url),
    )
    client = AsyncMock(spec=httpx.AsyncClient)
    client.get = AsyncMock(return_value=mock_response)

    result = await fetch_source(client, config)

    # Verify Referer was sent
    call_kwargs = client.get.call_args
    assert call_kwargs.kwargs["headers"]["Referer"] == "https://map.stjohns.ca/avl/"
    # No token should be present in params
    assert "token" not in call_kwargs.kwargs["params"]
    assert result == {"features": []}
