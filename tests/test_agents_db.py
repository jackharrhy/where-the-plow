# tests/test_agents_db.py
"""Tests for agent CRUD methods in Database."""

import os
import tempfile

import pytest

from where_the_plow.db import Database


@pytest.fixture
def db():
    """Create a temporary Database, initialise it, yield, then close."""
    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "test.db")
        database = Database(db_path)
        database.init()
        yield database
        database.close()


def test_create_agent(db):
    agent = db.create_agent("agent-1", "My Agent", "pk_abc123")
    assert agent["agent_id"] == "agent-1"
    assert agent["name"] == "My Agent"
    assert agent["public_key"] == "pk_abc123"
    assert agent["status"] == "approved"
    assert agent["created_at"] is not None
    assert agent["last_seen_at"] is None
    assert agent["total_reports"] == 0
    assert agent["failed_reports"] == 0
    assert agent["ip"] is None
    assert agent["system_info"] is None


def test_create_agent_custom_status(db):
    agent = db.create_agent("agent-1", "My Agent", "pk_abc123", status="pending")
    assert agent["status"] == "pending"


def test_get_agent(db):
    db.create_agent("agent-1", "My Agent", "pk_abc123")
    agent = db.get_agent("agent-1")
    assert agent is not None
    assert agent["agent_id"] == "agent-1"
    assert agent["name"] == "My Agent"


def test_get_agent_not_found(db):
    result = db.get_agent("nonexistent")
    assert result is None


def test_list_agents(db):
    db.create_agent("agent-1", "First", "pk_1")
    db.create_agent("agent-2", "Second", "pk_2")
    agents = db.list_agents()
    assert len(agents) == 2
    assert agents[0]["agent_id"] == "agent-1"
    assert agents[1]["agent_id"] == "agent-2"


def test_disable_agent(db):
    db.create_agent("agent-1", "My Agent", "pk_abc123")
    db.disable_agent("agent-1")
    agent = db.get_agent("agent-1")
    assert agent is not None
    assert agent["status"] == "revoked"


def test_approve_agent(db):
    agent = db.create_agent("agent-1", "My Agent", "pk_abc123", status="pending")
    assert agent["status"] == "pending"
    db.approve_agent("agent-1")
    agent = db.get_agent("agent-1")
    assert agent is not None
    assert agent["status"] == "approved"


def test_register_agent(db):
    agent = db.register_agent(
        "agent-1", "My Agent", "pk_abc123", ip="1.2.3.4", system_info="linux"
    )
    assert agent["agent_id"] == "agent-1"
    assert agent["status"] == "pending"
    assert agent["ip"] == "1.2.3.4"
    assert agent["system_info"] == "linux"
    assert agent["total_reports"] == 0


def test_register_then_approve(db):
    db.register_agent("agent-1", "My Agent", "pk_abc123")
    agent = db.get_agent("agent-1")
    assert agent is not None
    assert agent["status"] == "pending"
    db.approve_agent("agent-1")
    agent = db.get_agent("agent-1")
    assert agent is not None
    assert agent["status"] == "approved"


def test_update_agent_seen(db):
    db.create_agent("agent-1", "My Agent", "pk_abc123")
    db.record_agent_report("agent-1", success=True)
    agent = db.get_agent("agent-1")
    assert agent is not None
    assert agent["last_seen_at"] is not None
    assert agent["total_reports"] == 1
    assert agent["failed_reports"] == 0


def test_record_failed_report(db):
    db.create_agent("agent-1", "My Agent", "pk_abc123")
    db.record_agent_report("agent-1", success=False)
    agent = db.get_agent("agent-1")
    assert agent is not None
    assert agent["last_seen_at"] is not None
    assert agent["total_reports"] == 0
    assert agent["failed_reports"] == 1


# ── Consecutive failures tracking ─────────────────────────────────────


def test_consecutive_failures_increments_on_failure(db):
    db.create_agent("agent-1", "My Agent", "pk_abc123")
    db.record_agent_report("agent-1", success=False)
    db.record_agent_report("agent-1", success=False)
    db.record_agent_report("agent-1", success=False)
    agent = db.get_agent("agent-1")
    assert agent is not None
    assert agent["consecutive_failures"] == 3
    assert agent["failed_reports"] == 3


def test_consecutive_failures_resets_on_success(db):
    db.create_agent("agent-1", "My Agent", "pk_abc123")
    db.record_agent_report("agent-1", success=False)
    db.record_agent_report("agent-1", success=False)
    agent = db.get_agent("agent-1")
    assert agent is not None
    assert agent["consecutive_failures"] == 2

    db.record_agent_report("agent-1", success=True)
    agent = db.get_agent("agent-1")
    assert agent is not None
    assert agent["consecutive_failures"] == 0
    assert agent["total_reports"] == 1
    assert agent["failed_reports"] == 2


def test_consecutive_failures_starts_at_zero(db):
    agent = db.create_agent("agent-1", "My Agent", "pk_abc123")
    assert agent["consecutive_failures"] == 0
