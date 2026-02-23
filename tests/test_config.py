from where_the_plow.config import Settings, settings, SOURCES


def test_default_settings():
    s = Settings()
    assert s.db_path == "/data/plow.db"
    assert s.poll_interval == 6
    assert s.log_level == "INFO"
    assert "MapServer" in s.avl_api_url


def test_settings_from_env(monkeypatch):
    monkeypatch.setenv("DB_PATH", "/tmp/test.db")
    monkeypatch.setenv("POLL_INTERVAL", "10")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    s = Settings()
    assert s.db_path == "/tmp/test.db"
    assert s.poll_interval == 10
    assert s.log_level == "DEBUG"


def test_sources_registry_has_required_sources():
    assert "st_johns" in SOURCES
    assert "mt_pearl" in SOURCES
    assert "provincial" in SOURCES


def test_source_config_has_required_fields():
    for name, src in SOURCES.items():
        assert src.name == name
        assert src.display_name
        assert src.api_url
        assert src.poll_interval > 0
        assert len(src.center) == 2
        assert src.zoom > 0
        assert src.parser in ("avl", "aatracking")


def test_st_johns_has_referer():
    assert SOURCES["st_johns"].referer is not None


def test_settings_still_has_legacy_fields():
    """Existing code references settings.avl_api_url — keep it working."""
    assert settings.avl_api_url
    assert settings.avl_referer
