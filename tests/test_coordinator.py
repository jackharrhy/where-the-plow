# tests/test_coordinator.py
"""Tests for coordinator schedule computation and timestamp validation."""

import time

from where_the_plow.coordinator import Coordinator


def test_compute_schedule_single_agent():
    """Single agent gets interval=6, offset=0."""
    schedule = Coordinator.compute_schedule(["agent-a"])
    assert schedule == {
        "agent-a": {"interval_seconds": 6, "offset_seconds": 0},
    }


def test_compute_schedule_three_agents():
    """Three agents: interval=18, offsets 0/6/12 sorted by agent_id."""
    schedule = Coordinator.compute_schedule(["charlie", "alice", "bob"])
    assert schedule == {
        "alice": {"interval_seconds": 18, "offset_seconds": 0},
        "bob": {"interval_seconds": 18, "offset_seconds": 6},
        "charlie": {"interval_seconds": 18, "offset_seconds": 12},
    }


def test_compute_schedule_empty():
    """No agents returns empty dict."""
    schedule = Coordinator.compute_schedule([])
    assert schedule == {}


def test_validate_timestamp_valid():
    """Current timestamp passes validation."""
    ts = str(int(time.time()))
    assert Coordinator.validate_timestamp(ts) is True


def test_validate_timestamp_too_old():
    """Timestamp 60s in the past with 30s max_skew fails."""
    ts = str(int(time.time()) - 60)
    assert Coordinator.validate_timestamp(ts, max_skew=30) is False


def test_validate_timestamp_future():
    """Timestamp 60s in the future with 30s max_skew fails."""
    ts = str(int(time.time()) + 60)
    assert Coordinator.validate_timestamp(ts, max_skew=30) is False


def test_validate_timestamp_garbage():
    """Non-numeric string returns False."""
    assert Coordinator.validate_timestamp("not-a-number") is False


def test_build_schedule_response_known_agent():
    """Known agent gets correct schedule response with fetch URL and headers."""
    schedule = Coordinator.compute_schedule(["agent-a"])
    response = Coordinator.build_schedule_response("agent-a", schedule)
    assert "fetch_url" in response
    assert "f=json" in response["fetch_url"]
    assert response["interval_seconds"] == 6
    assert response["offset_seconds"] == 0
    assert response["headers"] == {"Referer": "https://map.stjohns.ca/avl/"}


def test_build_schedule_response_unknown_agent():
    """Unknown agent falls back to interval=6, offset=0."""
    schedule = Coordinator.compute_schedule(["agent-a"])
    response = Coordinator.build_schedule_response("unknown-agent", schedule)
    assert response["interval_seconds"] == 6
    assert response["offset_seconds"] == 0
    assert "fetch_url" in response
