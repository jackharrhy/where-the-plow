from pydantic_settings import BaseSettings, SettingsConfigDict

from where_the_plow.source_config import SourceConfig, build_sources


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )

    # Application
    db_path: str = "/data/plow.db"
    log_level: str = "INFO"

    # Polling
    poll_interval: int = 6  # St. John's AVL poll interval (seconds)

    # Source API URLs
    avl_api_url: str = (
        "https://map.stjohns.ca/mapsrv/rest/services/AVL/MapServer/0/query"
    )
    mt_pearl_api_url: str = "https://gps5.aatracking.com/api/MtPearlPortal/GetPlows"
    provincial_api_url: str = (
        "https://gps5.aatracking.com/api/NewfoundlandPortal/GetPlows"
    )

    # Source enable/disable
    source_st_johns_enabled: bool = True
    source_mt_pearl_enabled: bool = True
    source_provincial_enabled: bool = True


settings = Settings()
SOURCES: dict[str, SourceConfig] = build_sources(settings)
