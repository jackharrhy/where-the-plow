import asyncio
import logging
from datetime import datetime, timezone

import httpx

from where_the_plow.client import (
    fetch_source,
    parse_avl_response,
    parse_aatracking_response,
)
from where_the_plow.config import SOURCES
from where_the_plow.db import Database
from where_the_plow.snapshot import build_realtime_snapshot

logger = logging.getLogger(__name__)


def _should_skip_direct_fetch(
    last_agent_report_age: float | None, threshold: int = 30
) -> bool:
    """Return True if agents are actively reporting and direct fetch should be skipped."""
    if last_agent_report_age is None:
        return False
    return last_agent_report_age <= threshold


def process_poll(db: Database, response, source: str, parser: str) -> int:
    """Parse response and store vehicles/positions for a given source."""
    now = datetime.now(timezone.utc)
    if parser == "avl":
        vehicles, positions = parse_avl_response(response)
    elif parser == "aatracking":
        vehicles, positions = parse_aatracking_response(response, collected_at=now)
    else:
        raise ValueError(f"Unknown parser: {parser}")

    db.upsert_vehicles(vehicles, now, source=source)
    inserted = db.insert_positions(positions, now, source=source)
    return inserted


def _is_source_paused(store: dict, source_name: str) -> bool:
    """Return True if a source has been paused via the admin panel."""
    paused = store.get("collector_paused")
    if not paused:
        return False
    return source_name in paused


async def poll_source(db: Database, store: dict, source_config):
    """Poll a single source in a loop at its configured interval."""
    logger.info(
        "Starting collector for %s — polling every %ds",
        source_config.display_name,
        source_config.poll_interval,
    )
    async with httpx.AsyncClient() as client:
        while True:
            if _is_source_paused(store, source_config.name):
                logger.debug(
                    "Collector for %s is paused, sleeping %ds",
                    source_config.name,
                    source_config.poll_interval,
                )
                await asyncio.sleep(source_config.poll_interval)
                continue

            if source_config.parser == "avl":
                try:
                    agents = db.list_agents()
                    active = [
                        a
                        for a in agents
                        if a["status"] == "approved" and a.get("last_seen_at")
                    ]
                    if active:
                        most_recent = max(a["last_seen_at"] for a in active)
                        age = (datetime.now(timezone.utc) - most_recent).total_seconds()
                        if _should_skip_direct_fetch(age):
                            logger.debug(
                                "Skipping direct AVL fetch — agents active (last report %.0fs ago)",
                                age,
                            )
                            await asyncio.sleep(source_config.poll_interval)
                            continue
                except Exception:
                    pass  # If agent check fails, proceed with direct fetch

            try:
                response = await fetch_source(client, source_config)
                if isinstance(response, list):
                    count = len(response)
                else:
                    count = len(response.get("features", []))
                inserted = process_poll(
                    db, response, source=source_config.name, parser=source_config.parser
                )
                logger.info(
                    "[%s] %d vehicles seen, %d new positions",
                    source_config.name,
                    count,
                    inserted,
                )
                # Update this source's realtime snapshot
                if "realtime" not in store:
                    store["realtime"] = {}
                store["realtime"][source_config.name] = build_realtime_snapshot(
                    db, source=source_config.name
                )
            except asyncio.CancelledError:
                logger.info("Collector for %s shutting down", source_config.name)
                raise
            except Exception:
                logger.exception("Poll failed for %s", source_config.name)

            await asyncio.sleep(source_config.poll_interval)


async def run(db: Database, store: dict):
    """Start a collector task for each enabled source."""
    stats = db.get_stats()
    logger.info(
        "DB stats: %d positions, %d vehicles",
        stats["total_positions"],
        stats["total_vehicles"],
    )

    store["realtime"] = {}

    tasks = []
    for source_config in SOURCES.values():
        if source_config.enabled:
            tasks.append(asyncio.create_task(poll_source(db, store, source_config)))

    if not tasks:
        logger.warning("No sources enabled!")
        return

    logger.info("Collector starting with %d sources", len(tasks))

    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        logger.info("Collector shutting down")
        for t in tasks:
            t.cancel()
        raise
