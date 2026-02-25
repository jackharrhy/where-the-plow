# Distributed Agent Network Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a distributed scraping network where trusted agents (Go binaries) fetch AVL data from their own IPs and report it to the plow server, bypassing the WAF IP ban.

**Architecture:** Go agent binary (`plow-agent`) fetches AVL data on a server-assigned schedule and POSTs signed results to the FastAPI backend. The coordinator (new Python module) manages agent registration, schedule assignment, signature verification, and feeds data into the existing collector pipeline. An admin panel at `/admin` provides agent management UI.

**Tech Stack:** Go 1.22+ (agent), Python/FastAPI (coordinator), DuckDB (agent registry), ECDSA P-256 (auth), vanilla HTML/CSS/JS (admin panel)

---

### Task 1: Database Migration — `agents` Table

**Files:**
- Create: `src/where_the_plow/migrations/003_add_agents_table.py`
- Test: `tests/test_migrate.py` (add test)

**Step 1: Write the migration file**

```python
# src/where_the_plow/migrations/003_add_agents_table.py
"""Add agents table for distributed fetch network."""

import duckdb


def upgrade(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS agents (
            agent_id       VARCHAR PRIMARY KEY,
            name           VARCHAR NOT NULL,
            public_key     VARCHAR NOT NULL,
            enabled        BOOLEAN DEFAULT TRUE,
            created_at     TIMESTAMPTZ NOT NULL,
            last_seen_at   TIMESTAMPTZ,
            total_reports  INTEGER DEFAULT 0,
            failed_reports INTEGER DEFAULT 0
        )
    """)
```

**Step 2: Write a test for the migration**

Add to `tests/test_migrate.py`:

```python
def test_003_adds_agents_table():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "test.db")
        db = Database(db_path)
        db.init()
        cur = db.conn.cursor()
        # Verify table exists with expected columns
        rows = cur.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='agents' ORDER BY ordinal_position"
        ).fetchall()
        col_names = [r[0] for r in rows]
        assert "agent_id" in col_names
        assert "public_key" in col_names
        assert "enabled" in col_names
        assert "total_reports" in col_names
        db.close()
```

**Step 3: Run tests**

Run: `uv run pytest tests/test_migrate.py -v`
Expected: All pass including new test

**Step 4: Commit**

```
git add src/where_the_plow/migrations/003_add_agents_table.py tests/test_migrate.py
git commit -m "feat: add agents table migration (003)"
```

---

### Task 2: Agent Database Methods

**Files:**
- Modify: `src/where_the_plow/db.py` (add agent CRUD methods)
- Create: `tests/test_agents_db.py`

**Step 1: Write failing tests**

Create `tests/test_agents_db.py`:

```python
import os
import tempfile
from datetime import datetime, timezone

import pytest

from where_the_plow.db import Database


@pytest.fixture
def db():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "test.db")
        d = Database(db_path)
        d.init()
        yield d
        d.close()


def test_create_agent(db):
    agent = db.create_agent("test-id-123", "Test Agent", "-----BEGIN PUBLIC KEY-----\nfake\n-----END PUBLIC KEY-----")
    assert agent["agent_id"] == "test-id-123"
    assert agent["name"] == "Test Agent"
    assert agent["enabled"] is True
    assert agent["total_reports"] == 0


def test_get_agent(db):
    db.create_agent("test-id", "Test", "fake-key")
    agent = db.get_agent("test-id")
    assert agent is not None
    assert agent["name"] == "Test"


def test_get_agent_not_found(db):
    assert db.get_agent("nonexistent") is None


def test_list_agents(db):
    db.create_agent("id-1", "Agent 1", "key-1")
    db.create_agent("id-2", "Agent 2", "key-2")
    agents = db.list_agents()
    assert len(agents) == 2


def test_disable_agent(db):
    db.create_agent("id-1", "Agent 1", "key-1")
    db.disable_agent("id-1")
    agent = db.get_agent("id-1")
    assert agent["enabled"] is False


def test_update_agent_seen(db):
    db.create_agent("id-1", "Agent 1", "key-1")
    db.record_agent_report("id-1", success=True)
    agent = db.get_agent("id-1")
    assert agent["last_seen_at"] is not None
    assert agent["total_reports"] == 1
    assert agent["failed_reports"] == 0


def test_record_failed_report(db):
    db.create_agent("id-1", "Agent 1", "key-1")
    db.record_agent_report("id-1", success=False)
    agent = db.get_agent("id-1")
    assert agent["total_reports"] == 0
    assert agent["failed_reports"] == 1
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_agents_db.py -v`
Expected: FAIL — methods don't exist

**Step 3: Implement the methods in `db.py`**

Add to end of `Database` class in `src/where_the_plow/db.py` (before `close()`):

```python
    # ── Agent management ─────────────────────────────────────────

    def create_agent(self, agent_id: str, name: str, public_key: str) -> dict:
        now = datetime.now(timezone.utc)
        self._cursor().execute(
            "INSERT INTO agents (agent_id, name, public_key, created_at) VALUES (?, ?, ?, ?)",
            [agent_id, name, public_key, now],
        )
        return self.get_agent(agent_id)

    def get_agent(self, agent_id: str) -> dict | None:
        row = self._cursor().execute(
            "SELECT agent_id, name, public_key, enabled, created_at, "
            "last_seen_at, total_reports, failed_reports "
            "FROM agents WHERE agent_id = ?",
            [agent_id],
        ).fetchone()
        if row is None:
            return None
        return {
            "agent_id": row[0],
            "name": row[1],
            "public_key": row[2],
            "enabled": row[3],
            "created_at": row[4],
            "last_seen_at": row[5],
            "total_reports": row[6],
            "failed_reports": row[7],
        }

    def list_agents(self) -> list[dict]:
        rows = self._cursor().execute(
            "SELECT agent_id, name, public_key, enabled, created_at, "
            "last_seen_at, total_reports, failed_reports "
            "FROM agents ORDER BY created_at"
        ).fetchall()
        return [
            {
                "agent_id": r[0], "name": r[1], "public_key": r[2],
                "enabled": r[3], "created_at": r[4], "last_seen_at": r[5],
                "total_reports": r[6], "failed_reports": r[7],
            }
            for r in rows
        ]

    def disable_agent(self, agent_id: str) -> None:
        self._cursor().execute(
            "UPDATE agents SET enabled = FALSE WHERE agent_id = ?", [agent_id]
        )

    def record_agent_report(self, agent_id: str, success: bool) -> None:
        now = datetime.now(timezone.utc)
        if success:
            self._cursor().execute(
                "UPDATE agents SET last_seen_at = ?, total_reports = total_reports + 1 "
                "WHERE agent_id = ?",
                [now, agent_id],
            )
        else:
            self._cursor().execute(
                "UPDATE agents SET last_seen_at = ?, failed_reports = failed_reports + 1 "
                "WHERE agent_id = ?",
                [now, agent_id],
            )
```

You'll also need to add `from datetime import datetime, timezone` at the top of `db.py` — check if it's already imported (it is, on line 6).

**Step 4: Run tests**

Run: `uv run pytest tests/test_agents_db.py -v`
Expected: All pass

**Step 5: Commit**

```
git add src/where_the_plow/db.py tests/test_agents_db.py
git commit -m "feat: add agent CRUD methods to Database"
```

---

### Task 3: ECDSA Signature Verification Module

**Files:**
- Create: `src/where_the_plow/agent_auth.py`
- Create: `tests/test_agent_auth.py`

**Step 1: Write failing tests**

Create `tests/test_agent_auth.py`:

```python
import time

import pytest

from where_the_plow.agent_auth import (
    generate_keypair,
    agent_id_from_public_key,
    sign_payload,
    verify_signature,
)


def test_generate_keypair():
    private_pem, public_pem = generate_keypair()
    assert "BEGIN EC PRIVATE KEY" in private_pem
    assert "BEGIN PUBLIC KEY" in public_pem


def test_agent_id_deterministic():
    _, public_pem = generate_keypair()
    id1 = agent_id_from_public_key(public_pem)
    id2 = agent_id_from_public_key(public_pem)
    assert id1 == id2
    assert len(id1) == 16  # first 16 hex chars of SHA-256


def test_sign_and_verify():
    private_pem, public_pem = generate_keypair()
    body = b'{"features": []}'
    ts = str(int(time.time()))
    sig = sign_payload(private_pem, body, ts)
    assert verify_signature(public_pem, body, ts, sig)


def test_verify_rejects_wrong_key():
    priv1, _ = generate_keypair()
    _, pub2 = generate_keypair()
    body = b"test"
    ts = str(int(time.time()))
    sig = sign_payload(priv1, body, ts)
    assert not verify_signature(pub2, body, ts, sig)


def test_verify_rejects_tampered_body():
    private_pem, public_pem = generate_keypair()
    body = b"original"
    ts = str(int(time.time()))
    sig = sign_payload(private_pem, body, ts)
    assert not verify_signature(public_pem, b"tampered", ts, sig)


def test_verify_rejects_wrong_timestamp():
    private_pem, public_pem = generate_keypair()
    body = b"test"
    ts = str(int(time.time()))
    sig = sign_payload(private_pem, body, ts)
    assert not verify_signature(public_pem, body, str(int(ts) + 100), sig)
```

**Step 2: Run to verify failure**

Run: `uv run pytest tests/test_agent_auth.py -v`
Expected: FAIL — module doesn't exist

**Step 3: Implement `agent_auth.py`**

Create `src/where_the_plow/agent_auth.py`:

```python
"""ECDSA P-256 key management and signature verification for plow agents."""

import base64
import hashlib

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.exceptions import InvalidSignature


def generate_keypair() -> tuple[str, str]:
    """Generate an ECDSA P-256 keypair. Returns (private_pem, public_pem)."""
    private_key = ec.generate_private_key(ec.SECP256R1())
    private_pem = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    ).decode()
    public_pem = private_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    return private_pem, public_pem


def agent_id_from_public_key(public_pem: str) -> str:
    """Derive a 16-char hex agent ID from a public key's SHA-256 fingerprint."""
    public_key = serialization.load_pem_public_key(public_pem.encode())
    der_bytes = public_key.public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return hashlib.sha256(der_bytes).hexdigest()[:16]


def _sign_data(body: bytes, timestamp: str) -> bytes:
    """Build the message to sign: SHA-256(body || timestamp)."""
    return hashlib.sha256(body + timestamp.encode()).digest()


def sign_payload(private_pem: str, body: bytes, timestamp: str) -> str:
    """Sign a payload with an ECDSA private key. Returns base64-encoded signature."""
    private_key = serialization.load_pem_private_key(private_pem.encode(), password=None)
    digest = _sign_data(body, timestamp)
    sig = private_key.sign(digest, ec.ECDSA(hashes.SHA256()))
    return base64.b64encode(sig).decode()


def verify_signature(public_pem: str, body: bytes, timestamp: str, signature_b64: str) -> bool:
    """Verify an ECDSA signature. Returns True if valid."""
    try:
        public_key = serialization.load_pem_public_key(public_pem.encode())
        digest = _sign_data(body, timestamp)
        sig_bytes = base64.b64decode(signature_b64)
        public_key.verify(sig_bytes, digest, ec.ECDSA(hashes.SHA256()))
        return True
    except (InvalidSignature, Exception):
        return False
```

**Step 4: Add `cryptography` dependency**

Run: `uv add cryptography`

**Step 5: Run tests**

Run: `uv run pytest tests/test_agent_auth.py -v`
Expected: All pass

**Step 6: Commit**

```
git add src/where_the_plow/agent_auth.py tests/test_agent_auth.py pyproject.toml uv.lock
git commit -m "feat: ECDSA key generation and signature verification"
```

---

### Task 4: Coordinator Module

**Files:**
- Create: `src/where_the_plow/coordinator.py`
- Create: `tests/test_coordinator.py`

**Step 1: Write failing tests**

Create `tests/test_coordinator.py`:

```python
import time

import pytest

from where_the_plow.coordinator import Coordinator


def test_compute_schedule_single_agent():
    sched = Coordinator.compute_schedule(agent_ids=["aaa"], target_interval=6)
    assert sched["aaa"]["interval_seconds"] == 6
    assert sched["aaa"]["offset_seconds"] == 0


def test_compute_schedule_three_agents():
    sched = Coordinator.compute_schedule(
        agent_ids=["aaa", "bbb", "ccc"], target_interval=6
    )
    assert sched["aaa"]["interval_seconds"] == 18
    assert sched["bbb"]["interval_seconds"] == 18
    assert sched["ccc"]["interval_seconds"] == 18
    # Offsets should be 0, 6, 12 (sorted by agent_id)
    assert sched["aaa"]["offset_seconds"] == 0
    assert sched["bbb"]["offset_seconds"] == 6
    assert sched["ccc"]["offset_seconds"] == 12


def test_compute_schedule_empty():
    sched = Coordinator.compute_schedule(agent_ids=[], target_interval=6)
    assert sched == {}


def test_validate_timestamp_valid():
    ts = str(int(time.time()))
    assert Coordinator.validate_timestamp(ts, max_skew=30)


def test_validate_timestamp_too_old():
    ts = str(int(time.time()) - 60)
    assert not Coordinator.validate_timestamp(ts, max_skew=30)


def test_validate_timestamp_future():
    ts = str(int(time.time()) + 60)
    assert not Coordinator.validate_timestamp(ts, max_skew=30)


def test_validate_timestamp_garbage():
    assert not Coordinator.validate_timestamp("not-a-number", max_skew=30)
```

**Step 2: Run to verify failure**

Run: `uv run pytest tests/test_coordinator.py -v`
Expected: FAIL — module doesn't exist

**Step 3: Implement coordinator**

Create `src/where_the_plow/coordinator.py`:

```python
"""Coordinator for distributed agent fetch network."""

import logging
import time

log = logging.getLogger(__name__)

# The AVL portal proxy URL and required headers.
AVL_FETCH_URL = (
    "https://map.stjohns.ca/portal/sharing/servers/"
    "e99efa79b60948dda2939a7d08204a61/rest/services/AVL/MapServer/0/query"
)
AVL_FETCH_PARAMS = "f=json&outFields=*&outSR=4326&returnGeometry=true&where=1%3D1"
AVL_FETCH_HEADERS = {"Referer": "https://map.stjohns.ca/avl/"}


class Coordinator:
    """Stateless helpers for agent schedule computation and request validation."""

    @staticmethod
    def compute_schedule(
        agent_ids: list[str], target_interval: int = 6
    ) -> dict[str, dict]:
        """Compute fetch schedules for active agents.

        Returns a dict keyed by agent_id with interval_seconds and offset_seconds.
        """
        if not agent_ids:
            return {}
        sorted_ids = sorted(agent_ids)
        n = len(sorted_ids)
        interval = target_interval * n
        return {
            aid: {
                "interval_seconds": interval,
                "offset_seconds": target_interval * i,
            }
            for i, aid in enumerate(sorted_ids)
        }

    @staticmethod
    def validate_timestamp(ts: str, max_skew: int = 30) -> bool:
        """Check that a timestamp string is within max_skew seconds of now."""
        try:
            ts_int = int(ts)
        except (ValueError, TypeError):
            return False
        now = int(time.time())
        return abs(now - ts_int) <= max_skew

    @staticmethod
    def build_schedule_response(agent_id: str, schedule: dict) -> dict:
        """Build the JSON schedule payload for an agent."""
        agent_schedule = schedule.get(agent_id, {"interval_seconds": 6, "offset_seconds": 0})
        return {
            "fetch_url": f"{AVL_FETCH_URL}?{AVL_FETCH_PARAMS}",
            "interval_seconds": agent_schedule["interval_seconds"],
            "offset_seconds": agent_schedule["offset_seconds"],
            "headers": AVL_FETCH_HEADERS,
        }
```

**Step 4: Run tests**

Run: `uv run pytest tests/test_coordinator.py -v`
Expected: All pass

**Step 5: Commit**

```
git add src/where_the_plow/coordinator.py tests/test_coordinator.py
git commit -m "feat: coordinator schedule computation and timestamp validation"
```

---

### Task 5: Agent API Endpoints

**Files:**
- Create: `src/where_the_plow/agent_routes.py`
- Create: `tests/test_agent_routes.py`
- Modify: `src/where_the_plow/main.py` (mount agent router)

**Step 1: Write failing tests**

Create `tests/test_agent_routes.py`:

```python
import os
import tempfile
import time
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from where_the_plow.agent_auth import generate_keypair, agent_id_from_public_key, sign_payload
from where_the_plow.db import Database


@pytest.fixture
def app_client():
    """Create a test app with a temp database."""
    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "test.db")
        db = Database(db_path)
        db.init()

        from where_the_plow.main import app
        app.state.db = db
        app.state.store = {}

        with TestClient(app, raise_server_exceptions=False) as client:
            yield client, db

        db.close()


def _register_agent(db, name="Test Agent"):
    """Helper: create a keypair and register the agent in the DB."""
    private_pem, public_pem = generate_keypair()
    aid = agent_id_from_public_key(public_pem)
    db.create_agent(aid, name, public_pem)
    return private_pem, public_pem, aid


def _signed_headers(private_pem: str, aid: str, body: bytes):
    ts = str(int(time.time()))
    sig = sign_payload(private_pem, body, ts)
    return {"X-Agent-Id": aid, "X-Agent-Ts": ts, "X-Agent-Sig": sig}


def test_checkin_valid(app_client):
    client, db = app_client
    priv, pub, aid = _register_agent(db)
    body = b"{}"
    headers = _signed_headers(priv, aid, body)
    resp = client.post("/agents/checkin", content=body, headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "fetch_url" in data
    assert "interval_seconds" in data


def test_checkin_unknown_agent(app_client):
    client, db = app_client
    priv, pub = generate_keypair()
    aid = agent_id_from_public_key(pub)
    body = b"{}"
    headers = _signed_headers(priv, aid, body)
    resp = client.post("/agents/checkin", content=body, headers=headers)
    assert resp.status_code == 401


def test_checkin_disabled_agent(app_client):
    client, db = app_client
    priv, pub, aid = _register_agent(db)
    db.disable_agent(aid)
    body = b"{}"
    headers = _signed_headers(priv, aid, body)
    resp = client.post("/agents/checkin", content=body, headers=headers)
    assert resp.status_code == 403


def test_report_valid_avl_data(app_client):
    client, db = app_client
    priv, pub, aid = _register_agent(db)
    body = b'{"features": [{"attributes": {"OBJECTID": 1, "VehicleType": "PLOW", "LocationDateTime": 1772017223000, "Bearing": 0, "isDriving": "maybe"}, "geometry": {"x": -52.7, "y": 47.5}}]}'
    headers = _signed_headers(priv, aid, body)
    resp = client.post("/agents/report", content=body, headers=headers)
    assert resp.status_code == 200
    agent = db.get_agent(aid)
    assert agent["total_reports"] == 1


def test_report_rejects_captcha_html(app_client):
    client, db = app_client
    priv, pub, aid = _register_agent(db)
    body = b"<html><body>captcha</body></html>"
    headers = _signed_headers(priv, aid, body)
    resp = client.post("/agents/report", content=body, headers=headers)
    assert resp.status_code == 200  # accepted but counted as failure
    agent = db.get_agent(aid)
    assert agent["failed_reports"] == 1
    assert agent["total_reports"] == 0


def test_report_rejects_bad_signature(app_client):
    client, db = app_client
    priv, pub, aid = _register_agent(db)
    body = b'{"features": []}'
    headers = {"X-Agent-Id": aid, "X-Agent-Ts": str(int(time.time())), "X-Agent-Sig": "badsig"}
    resp = client.post("/agents/report", content=body, headers=headers)
    assert resp.status_code == 401


def test_report_rejects_expired_timestamp(app_client):
    client, db = app_client
    priv, pub, aid = _register_agent(db)
    body = b'{"features": []}'
    ts = str(int(time.time()) - 120)  # 2 minutes old
    sig = sign_payload(priv, body, ts)
    headers = {"X-Agent-Id": aid, "X-Agent-Ts": ts, "X-Agent-Sig": sig}
    resp = client.post("/agents/report", content=body, headers=headers)
    assert resp.status_code == 401
```

**Step 2: Run to verify failure**

Run: `uv run pytest tests/test_agent_routes.py -v`
Expected: FAIL — module doesn't exist

**Step 3: Implement agent routes**

Create `src/where_the_plow/agent_routes.py`:

```python
"""API endpoints for distributed fetch agents."""

import json
import logging

from fastapi import APIRouter, Request, Response

from where_the_plow.agent_auth import verify_signature
from where_the_plow.client import parse_avl_response
from where_the_plow.collector import process_poll
from where_the_plow.coordinator import Coordinator
from where_the_plow.snapshot import build_realtime_snapshot

log = logging.getLogger(__name__)

router = APIRouter(prefix="/agents", tags=["agents"])


async def _authenticate_agent(request: Request) -> tuple[dict | None, bytes, str | None]:
    """Verify agent identity from request headers.

    Returns (agent_dict, body_bytes, error_message).
    If error_message is not None, authentication failed.
    """
    agent_id = request.headers.get("X-Agent-Id", "")
    timestamp = request.headers.get("X-Agent-Ts", "")
    signature = request.headers.get("X-Agent-Sig", "")
    body = await request.body()

    if not agent_id or not timestamp or not signature:
        return None, body, "Missing auth headers"

    if not Coordinator.validate_timestamp(timestamp):
        return None, body, "Timestamp out of range"

    db = request.app.state.db
    agent = db.get_agent(agent_id)
    if agent is None:
        return None, body, "Unknown agent"

    if not verify_signature(agent["public_key"], body, timestamp, signature):
        return None, body, "Invalid signature"

    return agent, body, None


def _get_current_schedule(db) -> dict:
    """Compute schedule from currently enabled agents."""
    agents = db.list_agents()
    active_ids = [a["agent_id"] for a in agents if a["enabled"]]
    return Coordinator.compute_schedule(active_ids)


@router.post("/checkin")
async def agent_checkin(request: Request):
    agent, body, error = await _authenticate_agent(request)
    if error:
        if error == "Unknown agent":
            return Response(status_code=401, content=error)
        if agent and not agent["enabled"]:
            pass  # handled below
        return Response(status_code=401, content=error)

    if not agent["enabled"]:
        return Response(status_code=403, content="Agent disabled")

    db = request.app.state.db
    schedule = _get_current_schedule(db)
    return Coordinator.build_schedule_response(agent["agent_id"], schedule)


@router.post("/report")
async def agent_report(request: Request):
    agent, body, error = await _authenticate_agent(request)
    if error:
        log.warning("Agent report rejected: %s", error)
        return Response(status_code=401, content=error)

    if not agent["enabled"]:
        return Response(status_code=403, content="Agent disabled")

    db = request.app.state.db

    # Try to parse as valid AVL JSON
    try:
        data = json.loads(body)
        if not isinstance(data, dict) or "features" not in data:
            raise ValueError("Not a valid AVL response")
    except (json.JSONDecodeError, ValueError) as e:
        log.warning("Agent %s reported non-JSON/invalid data: %s", agent["agent_id"], e)
        db.record_agent_report(agent["agent_id"], success=False)
        schedule = _get_current_schedule(db)
        return Coordinator.build_schedule_response(agent["agent_id"], schedule)

    # Feed into existing pipeline
    try:
        process_poll(db, data, source="st_johns", parser="avl")
        # Rebuild realtime snapshot
        store = getattr(request.app.state, "store", {})
        if "realtime" not in store:
            store["realtime"] = {}
        store["realtime"]["st_johns"] = build_realtime_snapshot(db, source="st_johns")
        db.record_agent_report(agent["agent_id"], success=True)
        log.info("Agent %s (%s) reported %d features",
                 agent["agent_id"], agent["name"],
                 len(data.get("features", [])))
    except Exception:
        log.exception("Failed to process agent report from %s", agent["agent_id"])
        db.record_agent_report(agent["agent_id"], success=False)

    schedule = _get_current_schedule(db)
    return Coordinator.build_schedule_response(agent["agent_id"], schedule)
```

**Step 4: Mount the router in `main.py`**

Add after `app.include_router(router)` in `src/where_the_plow/main.py`:

```python
from where_the_plow.agent_routes import router as agent_router
app.include_router(agent_router)
```

**Step 5: Run tests**

Run: `uv run pytest tests/test_agent_routes.py -v`
Expected: All pass

**Step 6: Run full test suite**

Run: `uv run pytest tests/ -v`
Expected: All pass

**Step 7: Commit**

```
git add src/where_the_plow/agent_routes.py src/where_the_plow/main.py tests/test_agent_routes.py
git commit -m "feat: agent checkin and report API endpoints"
```

---

### Task 6: Admin Authentication

**Files:**
- Create: `src/where_the_plow/admin_routes.py`
- Create: `tests/test_admin_routes.py`
- Modify: `src/where_the_plow/config.py` (add `admin_password` setting)
- Modify: `src/where_the_plow/main.py` (mount admin router)

**Step 1: Add setting**

In `src/where_the_plow/config.py`, add to `Settings`:

```python
    admin_password: str | None = None
```

**Step 2: Write failing tests**

Create `tests/test_admin_routes.py`:

```python
import os
import tempfile

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch

from where_the_plow.db import Database


@pytest.fixture
def admin_client():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "test.db")
        db = Database(db_path)
        db.init()

        with patch("where_the_plow.config.settings.admin_password", "test-secret"):
            from where_the_plow.main import app
            app.state.db = db
            app.state.store = {}

            with TestClient(app, raise_server_exceptions=False) as client:
                yield client, db

        db.close()


def _login(client, password="test-secret"):
    return client.post("/admin/login", json={"password": password})


def test_login_success(admin_client):
    client, db = admin_client
    resp = _login(client)
    assert resp.status_code == 200
    assert "admin_token" in resp.cookies


def test_login_wrong_password(admin_client):
    client, db = admin_client
    resp = _login(client, password="wrong")
    assert resp.status_code == 401


def test_login_no_password_configured(admin_client):
    client, db = admin_client
    with patch("where_the_plow.admin_routes._get_admin_password", return_value=None):
        resp = _login(client)
        assert resp.status_code == 503


def test_agents_list_requires_auth(admin_client):
    client, db = admin_client
    resp = client.get("/admin/agents")
    assert resp.status_code == 401


def test_agents_list_with_auth(admin_client):
    client, db = admin_client
    _login(client)
    resp = client.get("/admin/agents")
    assert resp.status_code == 200
    assert resp.json() == []


def test_create_agent(admin_client):
    client, db = admin_client
    _login(client)
    resp = client.post("/admin/agents/create", json={"name": "Test Agent"})
    assert resp.status_code == 200
    data = resp.json()
    assert "agent_id" in data
    assert "private_key" in data
    assert "BEGIN EC PRIVATE KEY" in data["private_key"]
    # Verify agent was stored
    agents_resp = client.get("/admin/agents")
    assert len(agents_resp.json()) == 1


def test_revoke_agent(admin_client):
    client, db = admin_client
    _login(client)
    create_resp = client.post("/admin/agents/create", json={"name": "Test"})
    aid = create_resp.json()["agent_id"]
    resp = client.post(f"/admin/agents/{aid}/revoke")
    assert resp.status_code == 200
    agents = client.get("/admin/agents").json()
    assert agents[0]["enabled"] is False
```

**Step 3: Run to verify failure**

Run: `uv run pytest tests/test_admin_routes.py -v`
Expected: FAIL

**Step 4: Implement admin routes**

Create `src/where_the_plow/admin_routes.py`:

```python
"""Admin panel API endpoints for agent management."""

import hashlib
import hmac
import logging

from fastapi import APIRouter, Cookie, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from where_the_plow.agent_auth import generate_keypair, agent_id_from_public_key

log = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


def _get_admin_password() -> str | None:
    from where_the_plow.config import settings
    return settings.admin_password


def _make_token(password: str) -> str:
    """Derive a cookie token from the admin password."""
    return hmac.new(
        b"plow-admin-salt", password.encode(), hashlib.sha256
    ).hexdigest()


def _check_auth(admin_token: str | None) -> bool:
    password = _get_admin_password()
    if not password or not admin_token:
        return False
    expected = _make_token(password)
    return hmac.compare_digest(admin_token, expected)


class LoginRequest(BaseModel):
    password: str


class CreateAgentRequest(BaseModel):
    name: str


@router.post("/login")
def admin_login(body: LoginRequest):
    password = _get_admin_password()
    if password is None:
        return Response(status_code=503, content="Admin password not configured")
    if not hmac.compare_digest(body.password, password):
        return Response(status_code=401, content="Invalid password")
    token = _make_token(password)
    response = JSONResponse(content={"ok": True})
    response.set_cookie(
        key="admin_token", value=token, httponly=True,
        samesite="strict", max_age=86400,
    )
    return response


@router.get("/agents")
def list_agents(request: Request, admin_token: str | None = Cookie(None)):
    if not _check_auth(admin_token):
        return Response(status_code=401, content="Not authenticated")
    db = request.app.state.db
    agents = db.list_agents()
    # Redact public keys for the list view, serialize datetimes
    return [
        {
            "agent_id": a["agent_id"],
            "name": a["name"],
            "enabled": a["enabled"],
            "created_at": a["created_at"].isoformat() if a["created_at"] else None,
            "last_seen_at": a["last_seen_at"].isoformat() if a["last_seen_at"] else None,
            "total_reports": a["total_reports"],
            "failed_reports": a["failed_reports"],
        }
        for a in agents
    ]


@router.post("/agents/create")
def create_agent(request: Request, body: CreateAgentRequest, admin_token: str | None = Cookie(None)):
    if not _check_auth(admin_token):
        return Response(status_code=401, content="Not authenticated")
    db = request.app.state.db
    private_pem, public_pem = generate_keypair()
    agent_id = agent_id_from_public_key(public_pem)
    db.create_agent(agent_id, body.name, public_pem)
    log.info("Created agent %s (%s)", agent_id, body.name)
    return {
        "agent_id": agent_id,
        "name": body.name,
        "private_key": private_pem,
    }


@router.post("/agents/{agent_id}/revoke")
def revoke_agent(request: Request, agent_id: str, admin_token: str | None = Cookie(None)):
    if not _check_auth(admin_token):
        return Response(status_code=401, content="Not authenticated")
    db = request.app.state.db
    db.disable_agent(agent_id)
    log.info("Revoked agent %s", agent_id)
    return {"ok": True}


@router.get("/status")
def admin_status(request: Request, admin_token: str | None = Cookie(None)):
    if not _check_auth(admin_token):
        return Response(status_code=401, content="Not authenticated")
    db = request.app.state.db
    agents = db.list_agents()
    active = [a for a in agents if a["enabled"] and a["last_seen_at"] is not None]
    return {
        "total_agents": len(agents),
        "active_agents": len(active),
        "using_agents": len(active) > 0,
    }
```

**Note:** There's a typo in the template — `hmac.new` should be `hmac.HMAC` or use `hmac.new`. Actually the correct stdlib call is `hmac.new(key, msg, digestmod)`. Verify this compiles.

**Step 5: Mount in `main.py`**

Add after the agent router mount:

```python
from where_the_plow.admin_routes import router as admin_router
app.include_router(admin_router)
```

**Step 6: Run tests**

Run: `uv run pytest tests/test_admin_routes.py -v`
Expected: All pass

**Step 7: Run full test suite**

Run: `uv run pytest tests/ -v`
Expected: All pass

**Step 8: Commit**

```
git add src/where_the_plow/admin_routes.py src/where_the_plow/config.py src/where_the_plow/main.py tests/test_admin_routes.py
git commit -m "feat: admin API for agent management with password auth"
```

---

### Task 7: Admin Panel Frontend

**Files:**
- Create: `src/where_the_plow/static/admin/index.html`
- Create: `src/where_the_plow/static/admin/admin.js`
- Create: `src/where_the_plow/static/admin/style.css`
- Modify: `src/where_the_plow/main.py` (add `/admin` route to serve the page)

**Step 1: Create admin HTML page**

The admin page should follow the same dark theme as the main app using CSS custom properties from the main `style.css`. Keep it simple: a login form, then once authenticated show the agent list with create/revoke buttons.

Create `src/where_the_plow/static/admin/index.html` — single-page admin panel with:
- Login form (password input + submit button)
- Agent table (name, ID, status, last seen, reports, actions)
- Create agent form (name input + button)
- Status bar (active agents, fallback mode)

Create `src/where_the_plow/static/admin/admin.js` — vanilla JS:
- `login(password)` — POST to `/admin/login`
- `loadAgents()` — GET `/admin/agents`, render table
- `createAgent(name)` — POST `/admin/agents/create`, show private key in a modal/textarea for copying
- `revokeAgent(id)` — POST `/admin/agents/{id}/revoke`
- Auto-refresh agent list every 10 seconds

Create `src/where_the_plow/static/admin/style.css` — reuse CSS custom properties from main app (`--color-bg`, `--color-text`, etc.), keep the dark theme consistent.

**Step 2: Mount the admin static files and page route**

In `src/where_the_plow/main.py`, add:

```python
ADMIN_STATIC_DIR = Path(__file__).parent / "static" / "admin"

@app.get("/admin", include_in_schema=False)
def admin_page():
    return FileResponse(str(ADMIN_STATIC_DIR / "index.html"))

app.mount("/static/admin", StaticFiles(directory=str(ADMIN_STATIC_DIR)), name="admin-static")
```

**Important:** The `/static/admin` mount must come BEFORE the `/static` mount, or put the admin mount as a sub-path that doesn't conflict. Actually since `/static` is already mounted and covers subdirectories, the admin files at `static/admin/` will be served automatically at `/static/admin/admin.js` etc. You only need the `/admin` route to serve the HTML page.

**Step 3: Test manually**

Run: `uv run uvicorn where_the_plow.main:app --reload`
Visit: `http://localhost:8000/admin`
Expected: Login form appears, styled with dark theme

**Step 4: Commit**

```
git add src/where_the_plow/static/admin/ src/where_the_plow/main.py
git commit -m "feat: admin panel frontend for agent management"
```

---

### Task 8: Collector Fallback Integration

**Files:**
- Modify: `src/where_the_plow/collector.py` (skip direct AVL fetch when agents are active)
- Modify: `tests/test_collector.py` (add fallback test)

**Step 1: Write failing test**

Add to `tests/test_collector.py`:

```python
async def test_poll_source_skips_when_agents_active():
    """When agents are actively reporting, the direct AVL poller should skip."""
    config = _test_source_config(parser="avl", api_url="https://example.com")

    from where_the_plow.collector import _should_skip_direct_fetch
    # Mock: agent reported 10 seconds ago
    assert _should_skip_direct_fetch(last_agent_report_age=10, threshold=30) is True
    # Mock: no recent agent report
    assert _should_skip_direct_fetch(last_agent_report_age=60, threshold=30) is False
    # Mock: no agents at all
    assert _should_skip_direct_fetch(last_agent_report_age=None, threshold=30) is False
```

**Step 2: Run to verify failure**

Run: `uv run pytest tests/test_collector.py::test_poll_source_skips_when_agents_active -v`
Expected: FAIL

**Step 3: Implement fallback logic**

In `src/where_the_plow/collector.py`, add:

```python
def _should_skip_direct_fetch(last_agent_report_age: float | None, threshold: int = 30) -> bool:
    """Return True if agents are actively reporting and direct fetch should be skipped."""
    if last_agent_report_age is None:
        return False
    return last_agent_report_age <= threshold
```

Then in `poll_source`, before the `fetch_source` call, add a check for AVL sources:

```python
if source_config.parser == "avl":
    # Check if agents are handling this source
    agents = db.list_agents()
    active = [a for a in agents if a["enabled"] and a.get("last_seen_at")]
    if active:
        from datetime import datetime, timezone
        most_recent = max(a["last_seen_at"] for a in active)
        age = (datetime.now(timezone.utc) - most_recent).total_seconds()
        if _should_skip_direct_fetch(age):
            await asyncio.sleep(source_config.poll_interval)
            continue
```

This requires access to `db` in `poll_source` — which it already has.

**Step 4: Run tests**

Run: `uv run pytest tests/ -v`
Expected: All pass

**Step 5: Commit**

```
git add src/where_the_plow/collector.py tests/test_collector.py
git commit -m "feat: skip direct AVL fetch when agents are actively reporting"
```

---

### Task 9: Go Agent Binary

**Files:**
- Create: `agent/` directory
- Create: `agent/main.go`
- Create: `agent/go.mod`
- Create: `agent/Dockerfile`

**Step 1: Initialize Go module**

```bash
mkdir -p agent
cd agent
go mod init github.com/jackharrhy/plow-agent
```

**Step 2: Write `agent/main.go`**

The agent binary:
- Parses `--server` and `--key` flags
- Loads the ECDSA private key from PEM
- Derives agent ID from public key fingerprint (SHA-256 of DER, first 16 hex chars)
- Checks in with the server at `POST /agents/checkin`
- Enters fetch loop: wait → pick random User-Agent → GET AVL URL → sign body → POST `/agents/report`
- Reads updated schedule from response

Key implementation details:
- User-Agent pool: ~10 common browser strings (Chrome/Firefox/Safari on Windows/Mac/Linux)
- Random jitter: ±1-3 seconds on each fetch cycle
- Sign: `SHA-256(body || timestamp_string)`, ECDSA P-256, base64-encode signature
- Headers: `X-Agent-Id`, `X-Agent-Ts`, `X-Agent-Sig`
- Browser-like headers: `Accept: application/json`, `Accept-Language: en-CA,en;q=0.9`, `Accept-Encoding: gzip, deflate, br`
- On fetch failure: still POST to `/agents/report` with the raw (non-JSON) body so server records it

```go
// agent/main.go
package main

import (
	"bytes"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/sha256"
	"crypto/x509"
	"encoding/base64"
	"encoding/json"
	"encoding/pem"
	"flag"
	"fmt"
	"io"
	"log"
	"math/big"
	mrand "math/rand"
	"net/http"
	"os"
	"strconv"
	"time"
)

var userAgents = []string{
	"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
	"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
	"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
	"Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:134.0) Gecko/20100101 Firefox/134.0",
	"Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:134.0) Gecko/20100101 Firefox/134.0",
	"Mozilla/5.0 (X11; Linux x86_64; rv:134.0) Gecko/20100101 Firefox/134.0",
	"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.3 Safari/605.1.15",
	"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36 Edg/133.0.0.0",
	"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
	"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
}

type Schedule struct {
	FetchURL        string            `json:"fetch_url"`
	IntervalSeconds int               `json:"interval_seconds"`
	OffsetSeconds   int               `json:"offset_seconds"`
	Headers         map[string]string `json:"headers"`
}

func loadPrivateKey(path string) (*ecdsa.PrivateKey, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("reading key file: %w", err)
	}
	return parsePrivateKey(data)
}

func parsePrivateKey(pemData []byte) (*ecdsa.PrivateKey, error) {
	block, _ := pem.Decode(pemData)
	if block == nil {
		return nil, fmt.Errorf("no PEM block found")
	}
	key, err := x509.ParseECPrivateKey(block.Bytes)
	if err != nil {
		return nil, fmt.Errorf("parsing EC private key: %w", err)
	}
	return key, nil
}

func deriveAgentID(pub *ecdsa.PublicKey) string {
	der, _ := x509.MarshalPKIXPublicKey(pub)
	h := sha256.Sum256(der)
	return fmt.Sprintf("%x", h[:])[:16]
}

func signPayload(key *ecdsa.PrivateKey, body []byte, ts string) (string, error) {
	h := sha256.Sum256(append(body, []byte(ts)...))
	r, s, err := ecdsa.Sign(rand.Reader, key, h[:])
	if err != nil {
		return "", err
	}
	// Encode as ASN.1 DER (same as Go's default)
	sig, err := asn1Marshal(r, s)
	if err != nil {
		return "", err
	}
	return base64.StdEncoding.EncodeToString(sig), nil
}

// asn1Marshal encodes an ECDSA signature as ASN.1 DER
func asn1Marshal(r, s *big.Int) ([]byte, error) {
	type ecdsaSig struct {
		R, S *big.Int
	}
	// Use encoding/asn1
	import "encoding/asn1" // This won't work inline — move to imports
	return asn1.Marshal(ecdsaSig{r, s})
}

func main() {
	server := flag.String("server", "", "Plow server URL (e.g. https://plow.jackharrhy.dev)")
	keyPath := flag.String("key", "", "Path to ECDSA private key PEM file")
	keyData := flag.String("key-data", "", "ECDSA private key PEM (inline, alternative to --key)")
	flag.Parse()

	if *server == "" {
		log.Fatal("--server is required")
	}

	var privKey *ecdsa.PrivateKey
	var err error
	if *keyData != "" {
		privKey, err = parsePrivateKey([]byte(*keyData))
	} else if *keyPath != "" {
		privKey, err = loadPrivateKey(*keyPath)
	} else {
		log.Fatal("--key or --key-data is required")
	}
	if err != nil {
		log.Fatalf("Failed to load private key: %v", err)
	}

	agentID := deriveAgentID(&privKey.PublicKey)
	log.Printf("Agent ID: %s", agentID)
	log.Printf("Server: %s", *server)

	client := &http.Client{Timeout: 15 * time.Second}

	// Check in
	schedule, err := checkin(client, *server, agentID, privKey)
	if err != nil {
		log.Fatalf("Checkin failed: %v", err)
	}
	log.Printf("Schedule: fetch every %ds, offset %ds", schedule.IntervalSeconds, schedule.OffsetSeconds)

	// Wait for offset
	time.Sleep(time.Duration(schedule.OffsetSeconds) * time.Second)

	// Fetch loop
	for {
		jitter := time.Duration(mrand.Intn(3000)-1500) * time.Millisecond
		time.Sleep(time.Duration(schedule.IntervalSeconds)*time.Second + jitter)

		body, err := fetchAVL(client, schedule)
		if err != nil {
			log.Printf("Fetch failed: %v", err)
			body = []byte(fmt.Sprintf(`{"error": "%s"}`, err.Error()))
		}

		newSchedule, err := report(client, *server, agentID, privKey, body)
		if err != nil {
			log.Printf("Report failed: %v", err)
			continue
		}
		if newSchedule.IntervalSeconds != schedule.IntervalSeconds ||
			newSchedule.OffsetSeconds != schedule.OffsetSeconds {
			log.Printf("Schedule updated: fetch every %ds, offset %ds",
				newSchedule.IntervalSeconds, newSchedule.OffsetSeconds)
			schedule = newSchedule
		}
	}
}

func checkin(client *http.Client, server, agentID string, key *ecdsa.PrivateKey) (Schedule, error) {
	body := []byte("{}")
	ts := strconv.FormatInt(time.Now().Unix(), 10)
	sig, err := signPayload(key, body, ts)
	if err != nil {
		return Schedule{}, err
	}

	req, _ := http.NewRequest("POST", server+"/agents/checkin", bytes.NewReader(body))
	req.Header.Set("X-Agent-Id", agentID)
	req.Header.Set("X-Agent-Ts", ts)
	req.Header.Set("X-Agent-Sig", sig)
	req.Header.Set("Content-Type", "application/octet-stream")

	resp, err := client.Do(req)
	if err != nil {
		return Schedule{}, err
	}
	defer resp.Body.Close()

	if resp.StatusCode != 200 {
		b, _ := io.ReadAll(resp.Body)
		return Schedule{}, fmt.Errorf("checkin returned %d: %s", resp.StatusCode, string(b))
	}

	var sched Schedule
	if err := json.NewDecoder(resp.Body).Decode(&sched); err != nil {
		return Schedule{}, err
	}
	return sched, nil
}

func fetchAVL(client *http.Client, schedule Schedule) ([]byte, error) {
	req, _ := http.NewRequest("GET", schedule.FetchURL, nil)

	// Set browser-like headers
	ua := userAgents[mrand.Intn(len(userAgents))]
	req.Header.Set("User-Agent", ua)
	req.Header.Set("Accept", "application/json, text/plain, */*")
	req.Header.Set("Accept-Language", "en-CA,en;q=0.9,en-US;q=0.8")
	req.Header.Set("Accept-Encoding", "identity") // keep it simple, no gzip

	for k, v := range schedule.Headers {
		req.Header.Set(k, v)
	}

	resp, err := client.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	return io.ReadAll(resp.Body)
}

func report(client *http.Client, server, agentID string, key *ecdsa.PrivateKey, body []byte) (Schedule, error) {
	ts := strconv.FormatInt(time.Now().Unix(), 10)
	sig, err := signPayload(key, body, ts)
	if err != nil {
		return Schedule{}, err
	}

	req, _ := http.NewRequest("POST", server+"/agents/report", bytes.NewReader(body))
	req.Header.Set("X-Agent-Id", agentID)
	req.Header.Set("X-Agent-Ts", ts)
	req.Header.Set("X-Agent-Sig", sig)
	req.Header.Set("Content-Type", "application/octet-stream")

	resp, err := client.Do(req)
	if err != nil {
		return Schedule{}, err
	}
	defer resp.Body.Close()

	if resp.StatusCode != 200 {
		b, _ := io.ReadAll(resp.Body)
		return Schedule{}, fmt.Errorf("report returned %d: %s", resp.StatusCode, string(b))
	}

	var sched Schedule
	if err := json.NewDecoder(resp.Body).Decode(&sched); err != nil {
		return Schedule{}, err
	}
	return sched, nil
}
```

**Important note for implementer:** The inline `import "encoding/asn1"` in the `asn1Marshal` function above is invalid Go. Move `"encoding/asn1"` to the import block at the top of the file. The `asn1Marshal` function should use the `encoding/asn1` package. Alternatively, use `elliptic.Marshal` or just use `ecdsa.SignASN1` (Go 1.20+) which returns DER bytes directly, eliminating the need for manual ASN.1 encoding:

```go
func signPayload(key *ecdsa.PrivateKey, body []byte, ts string) (string, error) {
	h := sha256.Sum256(append(body, []byte(ts)...))
	sig, err := ecdsa.SignASN1(rand.Reader, key, h[:])
	if err != nil {
		return "", err
	}
	return base64.StdEncoding.EncodeToString(sig), nil
}
```

This is cleaner. Use `ecdsa.SignASN1` and remove the `asn1Marshal` function entirely.

**Step 3: Create `agent/Dockerfile`**

```dockerfile
FROM golang:1.22-alpine AS builder
WORKDIR /build
COPY go.mod ./
RUN go mod download
COPY *.go ./
RUN CGO_ENABLED=0 go build -ldflags="-s -w" -o /plow-agent .

FROM scratch
COPY --from=builder /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/
COPY --from=builder /plow-agent /plow-agent
ENTRYPOINT ["/plow-agent"]
```

**Step 4: Verify it compiles**

```bash
cd agent && go build -o plow-agent . && echo "Build OK"
```

**Step 5: Commit**

```
git add agent/
git commit -m "feat: plow-agent Go binary for distributed AVL fetching"
```

---

### Task 10: Update compose.yml and Config

**Files:**
- Modify: `compose.yml` (add `ADMIN_PASSWORD` env var)
- Modify: `src/where_the_plow/config.py` (already done in Task 6)

**Step 1: Update compose.yml**

Add `ADMIN_PASSWORD` to the environment section:

```yaml
    environment:
      - DB_PATH=/data/plow.db
      - POLL_INTERVAL=6
      - ADMIN_PASSWORD=${ADMIN_PASSWORD:-}
```

**Step 2: Commit**

```
git add compose.yml
git commit -m "chore: add ADMIN_PASSWORD env var to compose"
```

---

### Task 11: Full Integration Test

**Step 1: Run the full test suite**

Run: `uv run pytest tests/ -v`
Expected: All tests pass

**Step 2: Manual smoke test**

1. Start the server: `ADMIN_PASSWORD=test123 uv run uvicorn where_the_plow.main:app --reload`
2. Visit `http://localhost:8000/admin` — should see login page
3. Log in with `test123`
4. Create an agent — should show private key
5. Save the private key to a file
6. In another terminal: `cd agent && go run . --server http://localhost:8000 --key /path/to/key.pem`
7. Agent should check in and start fetching (will fail locally since map.stjohns.ca is being fetched from your IP)
8. Check admin panel — agent should show as active

**Step 3: Commit any fixes**

```
git add -A
git commit -m "fix: integration test fixes"
```

---

## Summary of Tasks

| Task | Description | Files |
|------|-------------|-------|
| 1 | DB migration — agents table | migration, test |
| 2 | Agent CRUD methods | db.py, test |
| 3 | ECDSA auth module | agent_auth.py, test |
| 4 | Coordinator module | coordinator.py, test |
| 5 | Agent API endpoints | agent_routes.py, test, main.py |
| 6 | Admin auth + API | admin_routes.py, test, config.py, main.py |
| 7 | Admin panel frontend | static/admin/*, main.py |
| 8 | Collector fallback | collector.py, test |
| 9 | Go agent binary | agent/*.go, Dockerfile |
| 10 | Compose config | compose.yml |
| 11 | Integration test | manual |
