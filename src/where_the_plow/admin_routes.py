# src/where_the_plow/admin_routes.py
"""Admin authentication and agent management API."""

import hashlib
import hmac
import logging
from datetime import datetime

from fastapi import APIRouter, Cookie, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from where_the_plow.agent_auth import generate_keypair, agent_id_from_public_key
from where_the_plow.db import Database

HEALTH_DEGRADED_THRESHOLD = 5
HEALTH_HIBERNATING_THRESHOLD = 30


def _agent_health(consecutive_failures: int) -> str:
    """Compute agent health status from consecutive failure count."""
    if consecutive_failures >= HEALTH_HIBERNATING_THRESHOLD:
        return "hibernating"
    if consecutive_failures >= HEALTH_DEGRADED_THRESHOLD:
        return "degraded"
    return "healthy"


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])

_SALT = b"plow-admin-salt"


class LoginRequest(BaseModel):
    password: str


class CreateAgentRequest(BaseModel):
    name: str


def _get_admin_password() -> str | None:
    from where_the_plow.config import settings

    return settings.admin_password


def _make_token(password: str) -> str:
    """Compute HMAC-SHA256(password, salt) hex digest."""
    return hmac.new(password.encode(), _SALT, hashlib.sha256).hexdigest()


def _check_auth(admin_token: str | None) -> bool:
    """Validate the admin cookie against the configured password."""
    password = _get_admin_password()
    if not password or not admin_token:
        return False
    expected = _make_token(password)
    return hmac.compare_digest(admin_token, expected)


@router.post("/login")
async def login(body: LoginRequest):
    password = _get_admin_password()
    if password is None:
        return JSONResponse({"error": "Admin password not configured"}, status_code=503)

    if not hmac.compare_digest(body.password, password):
        return JSONResponse({"error": "Wrong password"}, status_code=401)

    token = _make_token(password)
    response = JSONResponse({"ok": True})
    response.set_cookie(
        key="admin_token",
        value=token,
        httponly=True,
        samesite="strict",
    )
    return response


@router.get("/agents")
async def list_agents(request: Request, admin_token: str | None = Cookie(default=None)):
    if not _check_auth(admin_token):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    db: Database = request.app.state.db
    agents = db.list_agents()
    result = []
    for a in agents:
        consecutive = a.get("consecutive_failures", 0) or 0
        result.append(
            {
                "agent_id": a["agent_id"],
                "name": a["name"],
                "status": a["status"],
                "created_at": (
                    a["created_at"].isoformat()
                    if isinstance(a["created_at"], datetime)
                    else str(a["created_at"])
                ),
                "last_seen_at": (
                    a["last_seen_at"].isoformat()
                    if isinstance(a["last_seen_at"], datetime)
                    else a["last_seen_at"]
                ),
                "total_reports": a["total_reports"],
                "failed_reports": a["failed_reports"],
                "consecutive_failures": consecutive,
                "health": _agent_health(consecutive),
                "ip": a["ip"],
                "system_info": a["system_info"],
            }
        )
    return result


@router.post("/agents/create")
async def create_agent(
    body: CreateAgentRequest,
    request: Request,
    admin_token: str | None = Cookie(default=None),
):
    if not _check_auth(admin_token):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    private_pem, public_pem = generate_keypair()
    agent_id = agent_id_from_public_key(public_pem)

    db: Database = request.app.state.db
    db.create_agent(agent_id, body.name, public_pem)

    return {
        "agent_id": agent_id,
        "name": body.name,
        "private_key": private_pem,
    }


@router.post("/agents/{agent_id}/approve")
async def approve_agent(
    agent_id: str,
    request: Request,
    admin_token: str | None = Cookie(default=None),
):
    if not _check_auth(admin_token):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    db: Database = request.app.state.db
    db.approve_agent(agent_id)
    return {"ok": True}


@router.post("/agents/{agent_id}/revoke")
async def revoke_agent(
    agent_id: str,
    request: Request,
    admin_token: str | None = Cookie(default=None),
):
    if not _check_auth(admin_token):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    db: Database = request.app.state.db
    db.revoke_agent(agent_id)
    return {"ok": True}


@router.get("/status")
async def admin_status(
    request: Request, admin_token: str | None = Cookie(default=None)
):
    if not _check_auth(admin_token):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    db: Database = request.app.state.db
    agents = db.list_agents()
    total = len(agents)
    active = sum(
        1 for a in agents if a["status"] == "approved" and a["last_seen_at"] is not None
    )

    store = request.app.state.store
    paused_sources = list(store.get("collector_paused", set()))

    return {
        "total_agents": total,
        "active_agents": active,
        "using_agents": total > 0,
        "paused_sources": paused_sources,
    }


class CollectorPauseRequest(BaseModel):
    source: str


@router.post("/collector/pause")
async def pause_collector(
    body: CollectorPauseRequest,
    request: Request,
    admin_token: str | None = Cookie(default=None),
):
    if not _check_auth(admin_token):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    store = request.app.state.store
    if "collector_paused" not in store:
        store["collector_paused"] = set()
    store["collector_paused"].add(body.source)
    logger.info("Collector paused for source: %s", body.source)
    return {"ok": True, "paused_sources": list(store["collector_paused"])}


@router.post("/collector/resume")
async def resume_collector(
    body: CollectorPauseRequest,
    request: Request,
    admin_token: str | None = Cookie(default=None),
):
    if not _check_auth(admin_token):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    store = request.app.state.store
    paused = store.get("collector_paused", set())
    paused.discard(body.source)
    logger.info("Collector resumed for source: %s", body.source)
    return {"ok": True, "paused_sources": list(paused)}
