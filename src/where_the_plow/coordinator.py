"""Coordinator for distributed agent fetch network."""

import logging
import time

log = logging.getLogger(__name__)

AVL_FETCH_URL = (
    "https://map.stjohns.ca/portal/sharing/servers/"
    "e99efa79b60948dda2939a7d08204a61/rest/services/AVL/MapServer/0/query"
)
AVL_FETCH_PARAMS = "f=json&outFields=*&outSR=4326&returnGeometry=true&where=1%3D1"
AVL_FETCH_HEADERS = {"Referer": "https://map.stjohns.ca/avl/"}


class Coordinator:
    @staticmethod
    def compute_schedule(
        agent_ids: list[str], target_interval: int = 6
    ) -> dict[str, dict]:
        """Compute fetch schedules for active agents.

        With N agents and target_interval T:
        - Each agent fetches every T*N seconds
        - Agent offsets are 0, T, 2T, ... (sorted by agent_id)
        - Returns empty dict if no agents
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
        """Check timestamp string is within max_skew seconds of now.

        Return False on garbage input.
        """
        try:
            ts_int = int(ts)
        except (ValueError, TypeError):
            return False

        now = int(time.time())
        return abs(now - ts_int) <= max_skew

    @staticmethod
    def build_schedule_response(agent_id: str, schedule: dict) -> dict:
        """Build JSON schedule payload for an agent.

        Falls back to interval=6, offset=0 if agent not in schedule.
        """
        agent_schedule = schedule.get(
            agent_id, {"interval_seconds": 6, "offset_seconds": 0}
        )

        return {
            "fetch_url": f"{AVL_FETCH_URL}?{AVL_FETCH_PARAMS}",
            "interval_seconds": agent_schedule["interval_seconds"],
            "offset_seconds": agent_schedule["offset_seconds"],
            "headers": dict(AVL_FETCH_HEADERS),
        }
