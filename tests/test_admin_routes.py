# tests/test_admin_routes.py
"""Tests for admin authentication and agent management API."""

import os
import tempfile
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from where_the_plow.db import Database


ADMIN_SECRET = "test-secret"


@pytest.fixture
def admin_client():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "test.db")
        db = Database(db_path)
        db.init()

        from where_the_plow.main import app

        app.state.db = db
        app.state.store = {}

        client = TestClient(app, raise_server_exceptions=False)
        yield client, db

        db.close()


def _login(client, password=ADMIN_SECRET):
    """Helper: POST /admin/login and return response."""
    with patch(
        "where_the_plow.admin_routes._get_admin_password", return_value=ADMIN_SECRET
    ):
        return client.post("/admin/login", json={"password": password})


def _auth_cookies(client):
    """Login and return the session cookies for subsequent requests."""
    resp = _login(client)
    assert resp.status_code == 200
    return resp.cookies


# ── Login tests ───────────────────────────────────────────────────────


def test_login_success(admin_client):
    client, db = admin_client
    with patch(
        "where_the_plow.admin_routes._get_admin_password", return_value=ADMIN_SECRET
    ):
        resp = client.post("/admin/login", json={"password": ADMIN_SECRET})
    assert resp.status_code == 200
    assert "admin_token" in resp.cookies


def test_login_wrong_password(admin_client):
    client, db = admin_client
    with patch(
        "where_the_plow.admin_routes._get_admin_password", return_value=ADMIN_SECRET
    ):
        resp = client.post("/admin/login", json={"password": "wrong"})
    assert resp.status_code == 401


def test_login_no_password_configured(admin_client):
    client, db = admin_client
    with patch("where_the_plow.admin_routes._get_admin_password", return_value=None):
        resp = client.post("/admin/login", json={"password": "anything"})
    assert resp.status_code == 503


# ── Agent list tests ──────────────────────────────────────────────────


def test_agents_list_requires_auth(admin_client):
    client, db = admin_client
    resp = client.get("/admin/agents")
    assert resp.status_code == 401


def test_agents_list_with_auth(admin_client):
    client, db = admin_client
    cookies = _auth_cookies(client)
    with patch(
        "where_the_plow.admin_routes._get_admin_password", return_value=ADMIN_SECRET
    ):
        resp = client.get("/admin/agents", cookies=cookies)
    assert resp.status_code == 200
    assert resp.json() == []


# ── Create agent tests ────────────────────────────────────────────────


def test_create_agent(admin_client):
    client, db = admin_client
    cookies = _auth_cookies(client)
    with patch(
        "where_the_plow.admin_routes._get_admin_password", return_value=ADMIN_SECRET
    ):
        resp = client.post(
            "/admin/agents/create",
            json={"name": "my-agent"},
            cookies=cookies,
        )
    assert resp.status_code == 200
    data = resp.json()
    assert "agent_id" in data
    assert data["name"] == "my-agent"
    assert "private_key" in data
    assert data["private_key"].startswith("-----BEGIN EC PRIVATE KEY-----")


# ── Approve agent tests ──────────────────────────────────────────────


def test_approve_agent(admin_client):
    client, db = admin_client
    # Create a pending agent directly in DB
    db.create_agent("pending-1", "Pending Agent", "pk_test", status="pending")
    agent = db.get_agent("pending-1")
    assert agent is not None
    assert agent["status"] == "pending"

    cookies = _auth_cookies(client)
    with patch(
        "where_the_plow.admin_routes._get_admin_password", return_value=ADMIN_SECRET
    ):
        resp = client.post("/admin/agents/pending-1/approve", cookies=cookies)
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}

    agent = db.get_agent("pending-1")
    assert agent is not None
    assert agent["status"] == "approved"


# ── Revoke agent tests ───────────────────────────────────────────────


def test_revoke_agent(admin_client):
    client, db = admin_client
    cookies = _auth_cookies(client)
    with patch(
        "where_the_plow.admin_routes._get_admin_password", return_value=ADMIN_SECRET
    ):
        # Create an agent first
        create_resp = client.post(
            "/admin/agents/create",
            json={"name": "revoke-me"},
            cookies=cookies,
        )
        assert create_resp.status_code == 200
        agent_id = create_resp.json()["agent_id"]

        # Revoke it
        revoke_resp = client.post(
            f"/admin/agents/{agent_id}/revoke",
            cookies=cookies,
        )
        assert revoke_resp.status_code == 200
        assert revoke_resp.json() == {"ok": True}

    # Verify it's revoked in the DB
    agent = db.get_agent(agent_id)
    assert agent is not None
    assert agent["status"] == "revoked"


# ── Collector pause/resume tests ─────────────────────────────────────


def test_pause_collector(admin_client):
    client, db = admin_client
    cookies = _auth_cookies(client)
    with patch(
        "where_the_plow.admin_routes._get_admin_password", return_value=ADMIN_SECRET
    ):
        resp = client.post(
            "/admin/collector/pause",
            json={"source": "st_johns"},
            cookies=cookies,
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "st_johns" in data["paused_sources"]


def test_resume_collector(admin_client):
    client, db = admin_client
    cookies = _auth_cookies(client)
    with patch(
        "where_the_plow.admin_routes._get_admin_password", return_value=ADMIN_SECRET
    ):
        # Pause first
        client.post(
            "/admin/collector/pause",
            json={"source": "st_johns"},
            cookies=cookies,
        )
        # Then resume
        resp = client.post(
            "/admin/collector/resume",
            json={"source": "st_johns"},
            cookies=cookies,
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "st_johns" not in data["paused_sources"]


def test_status_includes_paused_sources(admin_client):
    client, db = admin_client
    cookies = _auth_cookies(client)
    with patch(
        "where_the_plow.admin_routes._get_admin_password", return_value=ADMIN_SECRET
    ):
        # Check status before pausing
        resp = client.get("/admin/status", cookies=cookies)
        assert resp.status_code == 200
        assert resp.json()["paused_sources"] == []

        # Pause and check again
        client.post(
            "/admin/collector/pause",
            json={"source": "st_johns"},
            cookies=cookies,
        )
        resp = client.get("/admin/status", cookies=cookies)
        assert resp.status_code == 200
        assert "st_johns" in resp.json()["paused_sources"]


def test_pause_requires_auth(admin_client):
    client, db = admin_client
    resp = client.post(
        "/admin/collector/pause",
        json={"source": "st_johns"},
    )
    assert resp.status_code == 401


def test_resume_requires_auth(admin_client):
    client, db = admin_client
    resp = client.post(
        "/admin/collector/resume",
        json={"source": "st_johns"},
    )
    assert resp.status_code == 401


# ── Agent health tests ───────────────────────────────────────────────


def test_agent_health_function():
    from where_the_plow.admin_routes import _agent_health

    assert _agent_health(0) == "healthy"
    assert _agent_health(4) == "healthy"
    assert _agent_health(5) == "degraded"
    assert _agent_health(15) == "degraded"
    assert _agent_health(29) == "degraded"
    assert _agent_health(30) == "hibernating"
    assert _agent_health(100) == "hibernating"


def test_agents_list_includes_health(admin_client):
    client, db = admin_client
    # Create an agent and record some failures
    db.create_agent("health-1", "Health Agent", "pk_test")
    for _ in range(6):
        db.record_agent_report("health-1", success=False)

    cookies = _auth_cookies(client)
    with patch(
        "where_the_plow.admin_routes._get_admin_password", return_value=ADMIN_SECRET
    ):
        resp = client.get("/admin/agents", cookies=cookies)
    assert resp.status_code == 200
    agents = resp.json()
    agent = [a for a in agents if a["agent_id"] == "health-1"][0]
    assert agent["consecutive_failures"] == 6
    assert agent["health"] == "degraded"
