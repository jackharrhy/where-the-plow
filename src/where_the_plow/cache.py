# src/where_the_plow/cache.py
"""Disk cache for JSON responses (coverage trails, search results, etc.).

Stores JSON in /tmp/where-the-plow-cache/ keyed by a hash of the
request parameters. Each entry carries an absolute expiry time.
Uses LRU-style eviction by file access time when total cache size
exceeds a budget.
"""

import hashlib
import json
import logging
import os
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

CACHE_DIR = Path(tempfile.gettempdir()) / "where-the-plow-cache"
MAX_CACHE_BYTES = 200 * 1024 * 1024  # 200 MB

# Cache policy tuned for coverage endpoint
RECENT_TTL_SECONDS = 5 * 60  # 5 minutes for live-ish windows
HISTORICAL_TTL_SECONDS = 24 * 60 * 60  # 1 day for immutable historical windows


def _cache_key(since: datetime, until: datetime, source: str | None) -> str:
    raw = f"{since.isoformat()}|{until.isoformat()}|{source or ''}"
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


def _is_historical(until: datetime) -> bool:
    """Return True if window is fully in the past (before today UTC)."""
    today_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    until_utc = until if until.tzinfo else until.replace(tzinfo=timezone.utc)
    return until_utc < today_start


def _ttl_for(until: datetime) -> int:
    return HISTORICAL_TTL_SECONDS if _is_historical(until) else RECENT_TTL_SECONDS


def _ensure_dir():
    CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _evict_if_needed():
    """Delete oldest-accessed files until total size is under budget."""
    try:
        files = list(CACHE_DIR.glob("*.json"))
        if not files:
            return
        total = sum(f.stat().st_size for f in files)
        if total <= MAX_CACHE_BYTES:
            return
        files.sort(key=lambda f: f.stat().st_atime)
        for f in files:
            if total <= MAX_CACHE_BYTES:
                break
            size = f.stat().st_size
            f.unlink(missing_ok=True)
            total -= size
            logger.debug("cache evict: %s (%d bytes)", f.name, size)
    except OSError:
        pass


def _delete_if_expired(path: Path, expires_at: float) -> bool:
    if time.time() <= expires_at:
        return False
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
    return True


def get(
    since: datetime, until: datetime, source: str | None = None
) -> list[dict] | None:
    """Return cached trails or None."""
    path = CACHE_DIR / f"{_cache_key(since, until, source)}.json"
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text())
        expires_at = float(payload.get("expires_at", 0))
        trails = payload.get("trails")
        if not isinstance(trails, list):
            return None
        if _delete_if_expired(path, expires_at):
            return None
        os.utime(path)
        logger.debug("cache hit: %s", path.name)
        return trails
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def put(
    since: datetime, until: datetime, trails: list[dict], source: str | None = None
):
    """Store trails in disk cache with endpoint-specific TTL policy."""
    _ensure_dir()
    _evict_if_needed()
    path = CACHE_DIR / f"{_cache_key(since, until, source)}.json"
    ttl = _ttl_for(until)
    payload = {
        "expires_at": time.time() + ttl,
        "trails": trails,
    }
    try:
        path.write_text(json.dumps(payload))
        logger.debug("cache put: %s (%d trails, ttl=%ds)", path.name, len(trails), ttl)
    except OSError:
        pass


# ── Search cache (Nominatim geocoding results) ───────

SEARCH_CACHE_TTL = 86400  # 24 hours — addresses don't change often


def _search_key(query: str) -> str:
    return "search_" + hashlib.sha256(query.encode()).hexdigest()[:24]


def search_get(query: str) -> list[dict] | None:
    """Return cached search results or None."""
    path = CACHE_DIR / f"{_search_key(query)}.json"
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text())
        expires_at = float(payload.get("expires_at", 0))
        results = payload.get("results")
        if not isinstance(results, list):
            return None
        if _delete_if_expired(path, expires_at):
            return None
        os.utime(path)
        logger.debug("search cache hit: %s", query)
        return results
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def search_put(query: str, results: list[dict]) -> None:
    """Store search results on disk."""
    _ensure_dir()
    _evict_if_needed()
    path = CACHE_DIR / f"{_search_key(query)}.json"
    payload = {
        "expires_at": time.time() + SEARCH_CACHE_TTL,
        "results": results,
    }
    try:
        path.write_text(json.dumps(payload))
        logger.debug("search cache put: %s (%d results)", query, len(results))
    except OSError:
        pass
