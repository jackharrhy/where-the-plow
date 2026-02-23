# src/where_the_plow/migrate.py
"""Lightweight numbered-file migration runner for DuckDB."""

import importlib.util
import logging
import re
from pathlib import Path

import duckdb

log = logging.getLogger(__name__)

_MIGRATION_RE = re.compile(r"^(\d+)_.+\.py$")


def get_version(conn: duckdb.DuckDBPyConnection) -> int:
    """Return current schema version, or 0 if table missing / empty."""
    try:
        row = conn.execute("SELECT max(version) FROM schema_version").fetchone()
    except duckdb.CatalogException:
        return 0
    if row is None or row[0] is None:
        return 0
    return int(row[0])


def _ensure_schema_version_table(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_version ("
        "  version    INTEGER NOT NULL,"
        "  applied_at TIMESTAMPTZ NOT NULL DEFAULT now()"
        ")"
    )


def _discover(migrations_dir: Path) -> list[tuple[int, Path]]:
    """Discover migration files matching NNN_*.py, sorted by number."""
    found: list[tuple[int, Path]] = []
    for p in migrations_dir.iterdir():
        m = _MIGRATION_RE.match(p.name)
        if m:
            found.append((int(m.group(1)), p))
    found.sort(key=lambda t: t[0])
    return found


def _load_upgrade(path: Path):
    """Import a migration file and return its upgrade function."""
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not hasattr(module, "upgrade"):
        raise ValueError(f"Migration {path.name} missing upgrade() function")
    return module.upgrade


def run_migrations(conn: duckdb.DuckDBPyConnection, migrations_dir: Path | str) -> None:
    """Discover and run pending migrations in order."""
    migrations_dir = Path(migrations_dir)
    _ensure_schema_version_table(conn)
    current = get_version(conn)
    pending = [(num, path) for num, path in _discover(migrations_dir) if num > current]
    if not pending:
        log.debug("No pending migrations (current version: %d)", current)
        return
    for num, path in pending:
        log.info("Applying migration %03d: %s", num, path.name)
        upgrade = _load_upgrade(path)
        try:
            upgrade(conn)
        except Exception:
            log.error("Migration %03d FAILED: %s", num, path.name)
            raise
        conn.execute("INSERT INTO schema_version (version) VALUES (?)", [num])
        log.info("Migration %03d applied", num)
