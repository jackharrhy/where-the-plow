# tests/test_migrate.py
import textwrap
from pathlib import Path

import duckdb
import pytest

from where_the_plow.migrate import get_version, run_migrations


def _make_conn(tmp_path: Path) -> duckdb.DuckDBPyConnection:
    """Create an in-memory-ish DuckDB connection backed by a temp file."""
    return duckdb.connect(str(tmp_path / "test.db"))


def _write_migration(migrations_dir: Path, number: int, body: str) -> Path:
    """Write a numbered migration file into migrations_dir.

    `body` should be the Python source for upgrade(conn) / downgrade(conn).
    """
    filename = f"{number:03d}_test.py"
    path = migrations_dir / filename
    path.write_text(textwrap.dedent(body))
    return path


# ---------------------------------------------------------------------------
# get_version tests
# ---------------------------------------------------------------------------


def test_get_version_no_table(tmp_path):
    """Version is 0 when schema_version table doesn't exist."""
    conn = _make_conn(tmp_path)
    assert get_version(conn) == 0
    conn.close()


def test_get_version_empty_table(tmp_path):
    """Version is 0 when schema_version table exists but is empty."""
    conn = _make_conn(tmp_path)
    conn.execute(
        "CREATE TABLE schema_version ("
        "  version INTEGER NOT NULL,"
        "  applied_at TIMESTAMPTZ NOT NULL DEFAULT now()"
        ")"
    )
    assert get_version(conn) == 0
    conn.close()


def test_get_version_with_entries(tmp_path):
    """Version equals max(version) in the table."""
    conn = _make_conn(tmp_path)
    conn.execute(
        "CREATE TABLE schema_version ("
        "  version INTEGER NOT NULL,"
        "  applied_at TIMESTAMPTZ NOT NULL DEFAULT now()"
        ")"
    )
    conn.execute("INSERT INTO schema_version (version) VALUES (1)")
    conn.execute("INSERT INTO schema_version (version) VALUES (3)")
    conn.execute("INSERT INTO schema_version (version) VALUES (2)")
    assert get_version(conn) == 3
    conn.close()


# ---------------------------------------------------------------------------
# run_migrations tests
# ---------------------------------------------------------------------------


def test_run_migrations_fresh_db(tmp_path):
    """Migrations run in order on a fresh DB, create tables, stamp version."""
    conn = _make_conn(tmp_path)
    mig_dir = tmp_path / "migrations"
    mig_dir.mkdir()

    _write_migration(
        mig_dir,
        1,
        """\
        def upgrade(conn):
            conn.execute("CREATE TABLE t1 (id INTEGER)")

        def downgrade(conn):
            conn.execute("DROP TABLE t1")
        """,
    )
    _write_migration(
        mig_dir,
        2,
        """\
        def upgrade(conn):
            conn.execute("CREATE TABLE t2 (id INTEGER)")

        def downgrade(conn):
            conn.execute("DROP TABLE t2")
        """,
    )

    run_migrations(conn, mig_dir)

    # Both tables should exist
    tables = {
        r[0]
        for r in conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema='main'"
        ).fetchall()
    }
    assert "t1" in tables
    assert "t2" in tables

    # Version should be 2
    assert get_version(conn) == 2

    # schema_version should have two entries
    rows = conn.execute(
        "SELECT version FROM schema_version ORDER BY version"
    ).fetchall()
    assert [r[0] for r in rows] == [1, 2]

    conn.close()


def test_run_migrations_skips_already_applied(tmp_path):
    """Already-applied migrations are skipped, only new ones run."""
    conn = _make_conn(tmp_path)
    mig_dir = tmp_path / "migrations"
    mig_dir.mkdir()

    _write_migration(
        mig_dir,
        1,
        """\
        def upgrade(conn):
            conn.execute("CREATE TABLE t1 (id INTEGER)")

        def downgrade(conn):
            conn.execute("DROP TABLE t1")
        """,
    )

    # Run once — migration 1 applied
    run_migrations(conn, mig_dir)
    assert get_version(conn) == 1

    # Add migration 2
    _write_migration(
        mig_dir,
        2,
        """\
        def upgrade(conn):
            conn.execute("CREATE TABLE t2 (id INTEGER)")

        def downgrade(conn):
            conn.execute("DROP TABLE t2")
        """,
    )

    # Run again — only migration 2 should run
    run_migrations(conn, mig_dir)
    assert get_version(conn) == 2

    tables = {
        r[0]
        for r in conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema='main'"
        ).fetchall()
    }
    assert "t1" in tables
    assert "t2" in tables

    # schema_version should have exactly two entries
    rows = conn.execute(
        "SELECT version FROM schema_version ORDER BY version"
    ).fetchall()
    assert [r[0] for r in rows] == [1, 2]

    conn.close()


def test_run_migrations_empty_dir(tmp_path):
    """No migrations to run is fine, version stays 0."""
    conn = _make_conn(tmp_path)
    mig_dir = tmp_path / "migrations"
    mig_dir.mkdir()

    run_migrations(conn, mig_dir)

    assert get_version(conn) == 0
    conn.close()


def test_run_migrations_non_python_files_ignored(tmp_path):
    """README.md, __init__.py, etc. are ignored during discovery."""
    conn = _make_conn(tmp_path)
    mig_dir = tmp_path / "migrations"
    mig_dir.mkdir()

    # Non-migration files
    (mig_dir / "README.md").write_text("# Migrations\n")
    (mig_dir / "__init__.py").write_text("")
    (mig_dir / "helpers.py").write_text("# not a migration\n")

    # One real migration
    _write_migration(
        mig_dir,
        1,
        """\
        def upgrade(conn):
            conn.execute("CREATE TABLE t1 (id INTEGER)")

        def downgrade(conn):
            conn.execute("DROP TABLE t1")
        """,
    )

    run_migrations(conn, mig_dir)

    assert get_version(conn) == 1

    tables = {
        r[0]
        for r in conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema='main'"
        ).fetchall()
    }
    assert "t1" in tables

    conn.close()


def test_run_migrations_partial_failure(tmp_path):
    """Migration 1 succeeds, migration 2 fails — version stays at 1, error propagates."""
    conn = _make_conn(tmp_path)
    mig_dir = tmp_path / "migrations"
    mig_dir.mkdir()

    _write_migration(
        mig_dir,
        1,
        """\
        def upgrade(conn):
            conn.execute("CREATE TABLE t1 (id INTEGER)")

        def downgrade(conn):
            conn.execute("DROP TABLE t1")
        """,
    )
    _write_migration(
        mig_dir,
        2,
        """\
        def upgrade(conn):
            raise RuntimeError("boom")

        def downgrade(conn):
            pass
        """,
    )

    with pytest.raises(RuntimeError, match="boom"):
        run_migrations(conn, mig_dir)

    # Migration 1 succeeded, so version should be 1
    assert get_version(conn) == 1

    # t1 should exist (migration 1 ran)
    tables = {
        r[0]
        for r in conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema='main'"
        ).fetchall()
    }
    assert "t1" in tables

    conn.close()


def test_run_migrations_missing_upgrade_function(tmp_path):
    """Migration file without upgrade() raises ValueError."""
    conn = _make_conn(tmp_path)
    mig_dir = tmp_path / "migrations"
    mig_dir.mkdir()

    # Write a migration file that has no upgrade() function
    (mig_dir / "001_bad.py").write_text("def downgrade(conn): pass\n")

    with pytest.raises(ValueError, match="missing upgrade\\(\\)"):
        run_migrations(conn, mig_dir)

    conn.close()
