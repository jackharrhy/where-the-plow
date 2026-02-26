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
    min_coverage_zoom: int = 0  # below this zoom, hide in coverage view


def build_sources(settings) -> dict[str, SourceConfig]:
    """Build the SOURCES registry from application settings.

    Static data (center, zoom, parser) lives here; env-driven fields
    (enabled, api_url, poll_interval) come from the Settings model.
    """
    return {
        "st_johns": SourceConfig(
            name="st_johns",
            display_name="St. John's",
            api_url=settings.avl_api_url,
            poll_interval=settings.source_st_johns_poll_interval,
            center=(-52.71, 47.56),
            zoom=12,
            parser="avl",
            referer="https://map.stjohns.ca/avl/",
            enabled=settings.source_st_johns_enabled,
            min_coverage_zoom=10,
        ),
        "mt_pearl": SourceConfig(
            name="mt_pearl",
            display_name="Mount Pearl",
            api_url=settings.mt_pearl_api_url,
            poll_interval=settings.source_mt_pearl_poll_interval,
            center=(-52.81, 47.52),
            zoom=13,
            parser="aatracking",
            enabled=settings.source_mt_pearl_enabled,
            min_coverage_zoom=10,
        ),
        "provincial": SourceConfig(
            name="provincial",
            display_name="Provincial",
            api_url=settings.provincial_api_url,
            poll_interval=settings.source_provincial_poll_interval,
            center=(-53.5, 48.5),
            zoom=7,
            parser="aatracking",
            enabled=settings.source_provincial_enabled,
            min_coverage_zoom=0,
        ),
        "paradise": SourceConfig(
            name="paradise",
            display_name="Paradise",
            api_url=settings.paradise_api_url,
            poll_interval=settings.source_paradise_poll_interval,
            center=(-52.87, 47.52),
            zoom=13,
            parser="hitechmaps",
            enabled=settings.source_paradise_enabled,
            min_coverage_zoom=10,
        ),
        "cbs": SourceConfig(
            name="cbs",
            display_name="Conception Bay South",
            api_url=settings.cbs_api_url,
            poll_interval=settings.source_cbs_poll_interval,
            center=(-52.98, 47.51),
            zoom=12,
            parser="geotab",
            enabled=settings.source_cbs_enabled,
            min_coverage_zoom=10,
        ),
    }
