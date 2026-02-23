import os
from dataclasses import dataclass


@dataclass
class SourceConfig:
    name: str
    display_name: str
    api_url: str
    poll_interval: int  # seconds
    center: tuple[float, float]  # (lng, lat)
    zoom: int
    parser: str  # "avl" or "aatracking"
    enabled: bool = True
    referer: str | None = None


SOURCES: dict[str, SourceConfig] = {
    "st_johns": SourceConfig(
        name="st_johns",
        display_name="St. John's",
        api_url=os.environ.get(
            "AVL_API_URL",
            "https://map.stjohns.ca/mapsrv/rest/services/AVL/MapServer/0/query",
        ),
        poll_interval=int(os.environ.get("POLL_INTERVAL", "6")),
        center=(-52.71, 47.56),
        zoom=12,
        parser="avl",
        referer="https://map.stjohns.ca/avl/",
        enabled=os.environ.get("SOURCE_ST_JOHNS_ENABLED", "true").lower() == "true",
    ),
    "mt_pearl": SourceConfig(
        name="mt_pearl",
        display_name="Mount Pearl",
        api_url=os.environ.get(
            "MT_PEARL_API_URL",
            "https://gps5.aatracking.com/api/MtPearlPortal/GetPlows",
        ),
        poll_interval=30,
        center=(-52.81, 47.52),
        zoom=13,
        parser="aatracking",
        enabled=os.environ.get("SOURCE_MT_PEARL_ENABLED", "true").lower() == "true",
    ),
    "provincial": SourceConfig(
        name="provincial",
        display_name="Provincial",
        api_url=os.environ.get(
            "PROVINCIAL_API_URL",
            "https://gps5.aatracking.com/api/NewfoundlandPortal/GetPlows",
        ),
        poll_interval=30,
        center=(-53.5, 48.5),
        zoom=7,
        parser="aatracking",
        enabled=os.environ.get("SOURCE_PROVINCIAL_ENABLED", "true").lower() == "true",
    ),
}


class Settings:
    def __init__(self):
        self.db_path: str = os.environ.get("DB_PATH", "/data/plow.db")
        self.poll_interval: int = int(os.environ.get("POLL_INTERVAL", "6"))
        self.log_level: str = os.environ.get("LOG_LEVEL", "INFO")
        # Legacy fields — still referenced by client.py for the AVL parser
        self.avl_api_url: str = SOURCES["st_johns"].api_url
        self.avl_referer: str = SOURCES["st_johns"].referer or ""


settings = Settings()
