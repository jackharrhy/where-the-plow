# src/where_the_plow/agent_routes.py
"""Agent checkin, report, and self-registration API endpoints."""

import json
import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from where_the_plow.agent_auth import agent_id_from_public_key, verify_signature
from where_the_plow.collector import process_poll
from where_the_plow.coordinator import Coordinator
from where_the_plow.db import Database
from where_the_plow.snapshot import build_realtime_snapshot

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agents", tags=["agents"])


def _client_ip(request: Request) -> str:
    return request.headers.get("x-forwarded-for", "").split(",")[0].strip() or (
        request.client.host if request.client else "unknown"
    )


async def _authenticate_agent(
    request: Request,
) -> tuple[dict | None, bytes, str | None]:
    """Authenticate an agent request.

    Returns (agent_dict, body_bytes, error_string_or_None).
    If error_string is not None, the request should be rejected.
    """
    body = await request.body()

    agent_id = request.headers.get("X-Agent-Id")
    agent_ts = request.headers.get("X-Agent-Ts")
    agent_sig = request.headers.get("X-Agent-Sig")

    if not agent_id or not agent_ts or not agent_sig:
        return None, body, "Missing auth headers"

    if not Coordinator.validate_timestamp(agent_ts):
        return None, body, "Timestamp expired"

    db: Database = request.app.state.db
    agent = db.get_agent(agent_id)
    if agent is None:
        return None, body, "Unknown agent"

    if agent["status"] == "pending":
        return agent, body, "Agent pending approval"

    if agent["status"] == "revoked":
        return agent, body, "Agent revoked"

    if not verify_signature(agent["public_key"], body, agent_ts, agent_sig):
        return None, body, "Invalid signature"

    return agent, body, None


def _get_current_schedule(db: Database) -> dict:
    """List approved agents and compute the schedule."""
    agents = db.list_agents()
    approved_ids = [a["agent_id"] for a in agents if a["status"] == "approved"]
    return Coordinator.compute_schedule(approved_ids)


@router.post("/register")
async def agent_register(request: Request):
    """Self-registration for new agents. No auth required."""
    body = await request.body()
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return Response(status_code=400, content="Invalid JSON")

    name = data.get("name", "").strip()
    public_key = data.get("public_key", "").strip()
    system_info = data.get("system_info", "")

    if not name or not public_key:
        return Response(status_code=400, content="name and public_key required")

    try:
        agent_id = agent_id_from_public_key(public_key)
    except Exception:
        return Response(status_code=400, content="Invalid public key")

    db: Database = request.app.state.db
    existing = db.get_agent(agent_id)
    if existing:
        # Already registered — return current status
        return {"agent_id": agent_id, "status": existing["status"]}

    ip = _client_ip(request)
    db.register_agent(agent_id, name, public_key, ip=ip, system_info=system_info)
    logger.info("New agent registered: %s (%s) from %s", agent_id, name, ip)
    return {"agent_id": agent_id, "status": "pending"}


@router.post("/checkin")
async def checkin(request: Request):
    agent, body, error = await _authenticate_agent(request)

    if error == "Unknown agent":
        return JSONResponse({"error": error}, status_code=401)
    if error in ("Agent pending approval", "Agent revoked"):
        return JSONResponse(
            {"status": agent["status"] if agent else "unknown", "message": error},
            status_code=403,
        )
    if error is not None:
        return JSONResponse({"error": error}, status_code=401)

    db: Database = request.app.state.db
    schedule = _get_current_schedule(db)
    return Coordinator.build_schedule_response(agent["agent_id"], schedule)


@router.post("/report")
async def report(request: Request):
    agent, body, error = await _authenticate_agent(request)

    if error == "Unknown agent":
        return JSONResponse({"error": error}, status_code=401)
    if error in ("Agent pending approval", "Agent revoked"):
        return JSONResponse(
            {"status": agent["status"] if agent else "unknown", "message": error},
            status_code=403,
        )
    if error is not None:
        return JSONResponse({"error": error}, status_code=401)

    db: Database = request.app.state.db

    # Try to parse the body as valid AVL JSON
    try:
        data = json.loads(body)
        if not isinstance(data, dict) or "features" not in data:
            raise ValueError("Missing 'features' key")
    except (json.JSONDecodeError, ValueError):
        db.record_agent_report(agent["agent_id"], success=False)
        schedule = _get_current_schedule(db)
        return Coordinator.build_schedule_response(agent["agent_id"], schedule)

    # Process valid AVL data
    try:
        process_poll(db, data, source="st_johns", parser="avl")
        store = request.app.state.store
        if "realtime" not in store:
            store["realtime"] = {}
        store["realtime"]["st_johns"] = build_realtime_snapshot(db, source="st_johns")
        db.record_agent_report(agent["agent_id"], success=True)
    except Exception:
        logger.exception("Agent report processing failed for %s", agent["agent_id"])
        db.record_agent_report(agent["agent_id"], success=False)

    schedule = _get_current_schedule(db)
    return Coordinator.build_schedule_response(agent["agent_id"], schedule)
