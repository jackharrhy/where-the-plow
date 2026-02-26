from where_the_plow.config import Settings, settings, SOURCES
from where_the_plow.source_config import SourceConfig, build_sources


def test_default_settings():
    s = Settings()
    assert s.db_path == "/data/plow.db"
    assert s.source_st_johns_poll_interval == 6
    assert s.source_mt_pearl_poll_interval == 30
    assert s.source_provincial_poll_interval == 30
    assert s.source_paradise_poll_interval == 10
    assert s.log_level == "INFO"
    assert "MapServer" in s.avl_api_url
    assert "hitechmaps.com" in s.paradise_api_url


def test_settings_from_env(monkeypatch):
    monkeypatch.setenv("DB_PATH", "/tmp/test.db")
    monkeypatch.setenv("SOURCE_ST_JOHNS_POLL_INTERVAL", "10")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    s = Settings()
    assert s.db_path == "/tmp/test.db"
    assert s.source_st_johns_poll_interval == 10
    assert s.log_level == "DEBUG"


def test_source_enabled_from_env(monkeypatch):
    """SOURCE_*_ENABLED env vars control source enable/disable."""
    monkeypatch.setenv("SOURCE_ST_JOHNS_ENABLED", "false")
    monkeypatch.setenv("SOURCE_MT_PEARL_ENABLED", "true")
    monkeypatch.setenv("SOURCE_PROVINCIAL_ENABLED", "false")
    s = Settings()
    assert s.source_st_johns_enabled is False
    assert s.source_mt_pearl_enabled is True
    assert s.source_provincial_enabled is False


def test_source_api_url_from_env(monkeypatch):
    """API URLs can be overridden via env vars."""
    monkeypatch.setenv("AVL_API_URL", "https://custom.example.com/avl")
    monkeypatch.setenv("MT_PEARL_API_URL", "https://custom.example.com/mp")
    s = Settings()
    assert s.avl_api_url == "https://custom.example.com/avl"
    assert s.mt_pearl_api_url == "https://custom.example.com/mp"


def test_sources_registry_has_required_sources():
    assert "st_johns" in SOURCES
    assert "mt_pearl" in SOURCES
    assert "provincial" in SOURCES
    assert "paradise" in SOURCES


def test_source_config_has_required_fields():
    for name, src in SOURCES.items():
        assert src.name == name
        assert src.display_name
        assert src.api_url
        assert src.poll_interval > 0
        assert len(src.center) == 2
        assert src.zoom > 0
        assert src.parser in ("avl", "aatracking", "hitechmaps")
        assert src.min_coverage_zoom >= 0


def test_st_johns_has_referer():
    assert SOURCES["st_johns"].referer is not None


def test_build_sources_uses_settings():
    """build_sources should wire Settings fields into SourceConfig."""
    s = Settings()
    sources = build_sources(s)
    assert sources["st_johns"].api_url == s.avl_api_url
    assert sources["st_johns"].poll_interval == s.source_st_johns_poll_interval
    assert sources["st_johns"].enabled == s.source_st_johns_enabled
    assert sources["mt_pearl"].api_url == s.mt_pearl_api_url
    assert sources["mt_pearl"].enabled == s.source_mt_pearl_enabled


def test_source_min_coverage_zoom():
    assert SOURCES["st_johns"].min_coverage_zoom == 10
    assert SOURCES["mt_pearl"].min_coverage_zoom == 10
    assert SOURCES["provincial"].min_coverage_zoom == 0
    assert SOURCES["paradise"].min_coverage_zoom == 10


def test_build_sources_respects_disabled(monkeypatch):
    """Disabled sources should have enabled=False in the built config."""
    monkeypatch.setenv("SOURCE_MT_PEARL_ENABLED", "false")
    s = Settings()
    sources = build_sources(s)
    assert sources["mt_pearl"].enabled is False
    assert sources["st_johns"].enabled is True
