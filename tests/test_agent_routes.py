# tests/test_agent_routes.py
"""Tests for agent checkin, report, and registration API endpoints."""

import json
import os
import tempfile
import time

import pytest
from fastapi.testclient import TestClient

from where_the_plow.agent_auth import (
    agent_id_from_public_key,
    generate_keypair,
    sign_payload,
)
from where_the_plow.db import Database
from where_the_plow.main import app


@pytest.fixture
def agent_client():
    """Set up app.state with a temp DB and store, yield TestClient.

    Does NOT use the lifespan (which starts the collector).
    """
    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "test.db")
        db = Database(db_path)
        db.init()

        app.state.db = db
        app.state.store = {"realtime": {}}

        client = TestClient(app, raise_server_exceptions=False)
        yield client

        db.close()


def _register_agent(db: Database, name: str = "test-agent"):
    """Register a new agent and return (private_pem, public_pem, agent_id, agent_dict)."""
    private_pem, public_pem = generate_keypair()
    agent_id = agent_id_from_public_key(public_pem)
    agent = db.create_agent(agent_id, name, public_pem)
    return private_pem, public_pem, agent_id, agent


def _sign_request(private_pem: str, agent_id: str, body: bytes):
    """Create auth headers for a signed request."""
    ts = str(int(time.time()))
    sig = sign_payload(private_pem, body, ts)
    return {
        "X-Agent-Id": agent_id,
        "X-Agent-Ts": ts,
        "X-Agent-Sig": sig,
    }


# ── Checkin tests ─────────────────────────────────────────────────────


def test_checkin_valid(agent_client):
    db = app.state.db
    private_pem, _, agent_id, _ = _register_agent(db)

    body = b""
    headers = _sign_request(private_pem, agent_id, body)
    resp = agent_client.post("/agents/checkin", content=body, headers=headers)

    assert resp.status_code == 200
    data = resp.json()
    assert "fetch_url" in data
    assert "interval_seconds" in data
    assert "offset_seconds" in data
    assert "headers" in data


def test_checkin_unknown_agent(agent_client):
    private_pem, public_pem = generate_keypair()
    agent_id = agent_id_from_public_key(public_pem)

    body = b""
    headers = _sign_request(private_pem, agent_id, body)
    resp = agent_client.post("/agents/checkin", content=body, headers=headers)

    assert resp.status_code == 401


def test_checkin_revoked_agent(agent_client):
    db = app.state.db
    private_pem, _, agent_id, _ = _register_agent(db)
    db.revoke_agent(agent_id)

    body = b""
    headers = _sign_request(private_pem, agent_id, body)
    resp = agent_client.post("/agents/checkin", content=body, headers=headers)

    assert resp.status_code == 403
    data = resp.json()
    assert data["status"] == "revoked"
    assert data["message"] == "Agent revoked"


def test_checkin_pending_agent(agent_client):
    db = app.state.db
    private_pem, public_pem = generate_keypair()
    agent_id = agent_id_from_public_key(public_pem)
    db.create_agent(agent_id, "pending-agent", public_pem, status="pending")

    body = b""
    headers = _sign_request(private_pem, agent_id, body)
    resp = agent_client.post("/agents/checkin", content=body, headers=headers)

    assert resp.status_code == 403
    data = resp.json()
    assert data["status"] == "pending"
    assert data["message"] == "Agent pending approval"


# ── Registration tests ────────────────────────────────────────────────


def test_register_new_agent(agent_client):
    private_pem, public_pem = generate_keypair()
    body = json.dumps(
        {"name": "new-agent", "public_key": public_pem, "system_info": "linux"}
    ).encode()
    resp = agent_client.post("/agents/register", content=body)

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "pending"
    assert "agent_id" in data

    # Verify in DB
    db = app.state.db
    agent = db.get_agent(data["agent_id"])
    assert agent is not None
    assert agent["status"] == "pending"
    assert agent["system_info"] == "linux"


def test_register_existing_agent(agent_client):
    db = app.state.db
    private_pem, public_pem, agent_id, _ = _register_agent(db)

    body = json.dumps({"name": "duplicate", "public_key": public_pem}).encode()
    resp = agent_client.post("/agents/register", content=body)

    assert resp.status_code == 200
    data = resp.json()
    assert data["agent_id"] == agent_id
    assert data["status"] == "approved"  # already approved via _register_agent


def test_register_missing_fields(agent_client):
    body = json.dumps({"name": ""}).encode()
    resp = agent_client.post("/agents/register", content=body)
    assert resp.status_code == 400


def test_register_invalid_json(agent_client):
    resp = agent_client.post("/agents/register", content=b"not json")
    assert resp.status_code == 400


def test_register_then_checkin_pending(agent_client):
    """Full flow: register -> pending -> checkin returns 403."""
    private_pem, public_pem = generate_keypair()

    # Register
    body = json.dumps({"name": "flow-agent", "public_key": public_pem}).encode()
    resp = agent_client.post("/agents/register", content=body)
    assert resp.status_code == 200
    agent_id = resp.json()["agent_id"]

    # Checkin should be rejected
    body = b""
    headers = _sign_request(private_pem, agent_id, body)
    resp = agent_client.post("/agents/checkin", content=body, headers=headers)
    assert resp.status_code == 403
    assert resp.json()["status"] == "pending"


# ── Report tests ──────────────────────────────────────────────────────


def _make_avl_body() -> bytes:
    """Create a minimal valid AVL response body."""
    return json.dumps(
        {
            "features": [
                {
                    "attributes": {
                        "OBJECTID": 9999,
                        "VehicleType": "SA PLOW TRUCK",
                        "LocationDateTime": int(time.time()) * 1000,
                        "Bearing": 90,
                        "isDriving": "maybe",
                    },
                    "geometry": {"x": -52.73, "y": 47.56},
                }
            ]
        }
    ).encode()


def test_report_valid_avl_data(agent_client):
    db = app.state.db
    private_pem, _, agent_id, _ = _register_agent(db)

    body = _make_avl_body()
    headers = _sign_request(private_pem, agent_id, body)
    resp = agent_client.post("/agents/report", content=body, headers=headers)

    assert resp.status_code == 200
    data = resp.json()
    assert "fetch_url" in data

    # Check that total_reports was incremented
    agent = db.get_agent(agent_id)
    assert agent["total_reports"] == 1
    assert agent["failed_reports"] == 0


def test_report_rejects_captcha_html(agent_client):
    db = app.state.db
    private_pem, _, agent_id, _ = _register_agent(db)

    body = b"<html><body>captcha check</body></html>"
    headers = _sign_request(private_pem, agent_id, body)
    resp = agent_client.post("/agents/report", content=body, headers=headers)

    assert resp.status_code == 200
    data = resp.json()
    assert "fetch_url" in data

    # Should be counted as a failed report
    agent = db.get_agent(agent_id)
    assert agent["total_reports"] == 0
    assert agent["failed_reports"] == 1


def test_report_rejects_bad_signature(agent_client):
    db = app.state.db
    _, _, agent_id, _ = _register_agent(db)

    # Sign with a different key
    other_private, _ = generate_keypair()
    body = _make_avl_body()
    headers = _sign_request(other_private, agent_id, body)
    resp = agent_client.post("/agents/report", content=body, headers=headers)

    assert resp.status_code == 401


def test_report_rejects_expired_timestamp(agent_client):
    db = app.state.db
    private_pem, _, agent_id, _ = _register_agent(db)

    body = _make_avl_body()
    # Use a timestamp from 60 seconds ago (beyond the 30s skew)
    ts = str(int(time.time()) - 60)
    sig = sign_payload(private_pem, body, ts)
    headers = {
        "X-Agent-Id": agent_id,
        "X-Agent-Ts": ts,
        "X-Agent-Sig": sig,
    }
    resp = agent_client.post("/agents/report", content=body, headers=headers)

    assert resp.status_code == 401
