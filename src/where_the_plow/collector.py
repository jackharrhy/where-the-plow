import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx

from where_the_plow.client import (
    fetch_source,
    parse_avl_response,
    parse_aatracking_response,
    parse_hitechmaps_response,
    parse_geotab_response,
)
from where_the_plow.config import SOURCES
from where_the_plow.db import Database

logger = logging.getLogger(__name__)


@dataclass
class SourceState:
    """Last successfully processed state for one source."""

    position_timestamps: dict[str, datetime] = field(default_factory=dict)
    vehicle_metadata: dict[str, tuple[str, str]] = field(default_factory=dict)


@dataclass(frozen=True)
class PollResult:
    vehicles_received: int
    positions_received: int
    vehicles_changed: int
    positions_changed: int

    @property
    def has_changes(self) -> bool:
        return self.vehicles_changed > 0 or self.positions_changed > 0


def process_poll(
    db: Database,
    response,
    source: str,
    parser: str,
    state: SourceState | None = None,
) -> PollResult:
    """Parse response and store vehicles/positions for a given source."""
    now = datetime.now(timezone.utc)
    if parser == "avl":
        vehicles, positions = parse_avl_response(response)
    elif parser == "aatracking":
        vehicles, positions = parse_aatracking_response(response, collected_at=now)
    elif parser == "hitechmaps":
        vehicles, positions = parse_hitechmaps_response(response, collected_at=now)
    elif parser == "geotab":
        vehicles, positions = parse_geotab_response(response, collected_at=now)
    else:
        raise ValueError(f"Unknown parser: {parser}")

    position_timestamps = {
        position["vehicle_id"]: position["timestamp"] for position in positions
    }
    vehicle_metadata = {
        vehicle["vehicle_id"]: (
            vehicle["description"],
            vehicle["vehicle_type"],
        )
        for vehicle in vehicles
    }

    if state is None:
        changed_position_ids = set(position_timestamps)
        changed_metadata_ids = set(vehicle_metadata)
    else:
        changed_position_ids = {
            vehicle_id
            for vehicle_id, timestamp in position_timestamps.items()
            if state.position_timestamps.get(vehicle_id) != timestamp
        }
        changed_metadata_ids = {
            vehicle_id
            for vehicle_id, metadata in vehicle_metadata.items()
            if state.vehicle_metadata.get(vehicle_id) != metadata
        }

    # Keep last_seen meaningful without rewriting every vehicle on every poll:
    # update vehicles whose metadata or position changed.
    changed_vehicle_ids = changed_metadata_ids | changed_position_ids
    vehicles_to_write = [
        vehicle for vehicle in vehicles if vehicle["vehicle_id"] in changed_vehicle_ids
    ]
    positions_to_write = [
        position
        for position in positions
        if position["vehicle_id"] in changed_position_ids
    ]

    db.upsert_vehicles(vehicles_to_write, now, source=source)
    db.insert_positions(positions_to_write, now, source=source)

    # Only advance the in-memory state after both database operations succeed.
    if state is not None:
        state.position_timestamps.update(position_timestamps)
        state.vehicle_metadata.update(vehicle_metadata)

    return PollResult(
        vehicles_received=len(vehicles),
        positions_received=len(positions),
        vehicles_changed=len(vehicles_to_write),
        positions_changed=len(positions_to_write),
    )


async def poll_source(db: Database, store: dict, source_config):
    """Poll a single source in a loop at its configured interval."""
    logger.info(
        "Starting collector for %s — polling every %ds",
        source_config.display_name,
        source_config.poll_interval,
    )
    state = SourceState()
    async with httpx.AsyncClient() as client:
        while True:
            try:
                response = await fetch_source(client, source_config)
                result = process_poll(
                    db,
                    response,
                    source=source_config.name,
                    parser=source_config.parser,
                    state=state,
                )
                logger.info(
                    "[%s] %d vehicles seen, %d/%d positions changed",
                    source_config.name,
                    result.vehicles_received,
                    result.positions_changed,
                    result.positions_received,
                )
                if result.has_changes:
                    # Mark this source's snapshot as stale so the next
                    # /vehicles request rebuilds it on demand.
                    store.setdefault("dirty", {})[source_config.name] = True
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
    store["dirty"] = {}

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
