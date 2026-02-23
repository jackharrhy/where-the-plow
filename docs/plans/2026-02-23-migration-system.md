# Migration System Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the ad-hoc inline migration hacks in `db.py` with a proper numbered-file migration system.

**Architecture:** A `src/where_the_plow/migrations/` package contains numbered Python files (`001_*.py`, `002_*.py`, ...). A lightweight runner in `src/where_the_plow/migrate.py` discovers and applies them in order, tracking progress in a `schema_version` table. `Database.init()` delegates all schema work to the runner.

**Tech Stack:** DuckDB, Python stdlib (`importlib`, `pathlib`, `logging`). No external migration library.

---

### Task 1: Migration runner (`migrate.py`)

**Files:**
- Create: `src/where_the_plow/migrate.py`
- Test: `tests/test_migrate.py`

**Step 1: Write failing tests for the runner**

```python
# tests/test_migrate.py
import duckdb
import pytest
from pathlib import Path
from where_the_plow.migrate import get_version, run_migrations


@pytest.fixture
def conn(tmp_path):
    db = duckdb.connect(str(tmp_path / "test.db"))
    return db


@pytest.fixture
def migrations_dir(tmp_path):
    d = tmp_path / "migrations"
    d.mkdir()
    return d


def _write_migration(directory: Path, name: str, upgrade_sql: str, downgrade_sql: str = ""):
    """Helper to write a migration file."""
    content = f'''
import duckdb

def upgrade(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute("""{upgrade_sql}""")

def downgrade(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute("""{downgrade_sql}""")
'''
    (directory / name).write_text(content)


def test_get_version_no_table(conn):
    """Version is 0 when schema_version table doesn't exist."""
    assert get_version(conn) == 0


def test_get_version_empty_table(conn):
    """Version is 0 when schema_version table exists but is empty."""
    conn.execute("""
        CREATE TABLE schema_version (
            version INTEGER NOT NULL,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    assert get_version(conn) == 0


def test_get_version_with_entries(conn):
    """Version is the max version in the table."""
    conn.execute("""
        CREATE TABLE schema_version (
            version INTEGER NOT NULL,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    conn.execute("INSERT INTO schema_version (version) VALUES (1)")
    conn.execute("INSERT INTO schema_version (version) VALUES (2)")
    assert get_version(conn) == 2


def test_run_migrations_fresh_db(conn, migrations_dir):
    """Migrations run in order on a fresh database."""
    _write_migration(migrations_dir, "001_create_foo.py",
                     "CREATE TABLE foo (id INTEGER)")
    _write_migration(migrations_dir, "002_create_bar.py",
                     "CREATE TABLE bar (id INTEGER)")

    run_migrations(conn, migrations_dir)

    assert get_version(conn) == 2
    # Tables should exist
    tables = {r[0] for r in conn.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema='main'"
    ).fetchall()}
    assert "foo" in tables
    assert "bar" in tables


def test_run_migrations_skips_already_applied(conn, migrations_dir):
    """Migrations already applied are skipped."""
    _write_migration(migrations_dir, "001_create_foo.py",
                     "CREATE TABLE foo (id INTEGER)")
    _write_migration(migrations_dir, "002_create_bar.py",
                     "CREATE TABLE bar (id INTEGER)")

    run_migrations(conn, migrations_dir)
    assert get_version(conn) == 2

    # Add a third migration and run again
    _write_migration(migrations_dir, "003_create_baz.py",
                     "CREATE TABLE baz (id INTEGER)")
    run_migrations(conn, migrations_dir)
    assert get_version(conn) == 3


def test_run_migrations_empty_dir(conn, migrations_dir):
    """No migrations to run is fine."""
    run_migrations(conn, migrations_dir)
    assert get_version(conn) == 0


def test_run_migrations_non_python_files_ignored(conn, migrations_dir):
    """Non-.py files and files without numeric prefixes are ignored."""
    (migrations_dir / "README.md").write_text("hello")
    (migrations_dir / "__init__.py").write_text("")
    (migrations_dir / "001_real.py").write_text('''
import duckdb
def upgrade(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute("CREATE TABLE real (id INTEGER)")
def downgrade(conn: duckdb.DuckDBPyConnection) -> None:
    pass
''')
    run_migrations(conn, migrations_dir)
    assert get_version(conn) == 1
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_migrate.py -v`
Expected: ImportError — `migrate` module doesn't exist yet.

**Step 3: Write the runner**

```python
# src/where_the_plow/migrate.py
"""Lightweight numbered-file migration runner for DuckDB."""

import importlib.util
import logging
import re
from pathlib import Path

import duckdb

logger = logging.getLogger(__name__)

_MIGRATION_RE = re.compile(r"^(\d+)_.+\.py$")


def get_version(conn: duckdb.DuckDBPyConnection) -> int:
    """Return the current schema version, or 0 if untracked."""
    try:
        row = conn.execute(
            "SELECT max(version) FROM schema_version"
        ).fetchone()
        return row[0] or 0
    except duckdb.CatalogException:
        return 0


def _discover(migrations_dir: Path) -> list[tuple[int, Path]]:
    """Return sorted list of (version, path) for migration files."""
    results = []
    for f in migrations_dir.iterdir():
        m = _MIGRATION_RE.match(f.name)
        if m:
            results.append((int(m.group(1)), f))
    results.sort(key=lambda x: x[0])
    return results


def _load_upgrade(path: Path):
    """Import a migration file and return its upgrade function."""
    spec = importlib.util.spec_from_file_location(path.stem, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.upgrade


def run_migrations(conn: duckdb.DuckDBPyConnection, migrations_dir: Path) -> None:
    """Discover and apply pending migrations."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_version (
            version    INTEGER NOT NULL,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)

    current = get_version(conn)
    pending = [(v, p) for v, p in _discover(migrations_dir) if v > current]

    if not pending:
        logger.info("Schema is up to date (version %d)", current)
        return

    for version, path in pending:
        logger.info("Applying migration %03d: %s", version, path.stem)
        upgrade_fn = _load_upgrade(path)
        upgrade_fn(conn)
        conn.execute(
            "INSERT INTO schema_version (version) VALUES (?)", [version]
        )
        logger.info("Migration %03d applied successfully", version)

    logger.info("Schema upgraded to version %d", get_version(conn))
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_migrate.py -v`
Expected: all 7 pass.

**Step 5: Commit**

```
git add src/where_the_plow/migrate.py tests/test_migrate.py
git commit -m "feat: add lightweight migration runner"
```

---

### Task 2: Migration 001 — baseline schema

This represents the production schema as seen in `data/og-prod-plow.db`. For fresh DBs it creates all tables. For existing DBs it's a no-op (uses `CREATE TABLE IF NOT EXISTS`). It also includes the older inline migrations (geom, ip/user_agent) since those are already applied in production but might not exist in a truly ancient DB.

**Files:**
- Create: `src/where_the_plow/migrations/__init__.py` (empty)
- Create: `src/where_the_plow/migrations/001_initial_schema.py`
- Test: `tests/test_migrate.py` (add test)

**Step 1: Write failing test**

Add to `tests/test_migrate.py`:

```python
def test_001_fresh_db_creates_tables(tmp_path):
    """Migration 001 creates the full baseline schema on a fresh DB."""
    conn = duckdb.connect(str(tmp_path / "fresh.db"))
    conn.execute("INSTALL spatial; LOAD spatial")

    migrations_dir = Path(__file__).parent.parent / "src" / "where_the_plow" / "migrations"
    run_migrations(conn, migrations_dir)

    tables = {r[0] for r in conn.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema='main'"
    ).fetchall()}
    assert "vehicles" in tables
    assert "positions" in tables
    assert "viewports" in tables
    assert "signups" in tables

    # Check baseline columns exist
    pos_cols = {r[0] for r in conn.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name='positions'"
    ).fetchall()}
    assert "geom" in pos_cols
    assert "vehicle_id" in pos_cols

    vp_cols = {r[0] for r in conn.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name='viewports'"
    ).fetchall()}
    assert "ip" in vp_cols
    assert "user_agent" in vp_cols
    conn.close()
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_migrate.py::test_001_fresh_db_creates_tables -v`
Expected: FAIL — no migration files exist yet.

**Step 3: Create the migrations package and 001**

Create empty `src/where_the_plow/migrations/__init__.py`.

```python
# src/where_the_plow/migrations/001_initial_schema.py
"""Baseline schema — matches production as of 2026-02-23.

For fresh databases: creates all tables with sequences and indexes.
For existing databases: CREATE TABLE IF NOT EXISTS is a no-op.
Also applies legacy migrations (geom column, ip/user_agent columns)
using column-existence checks so they're idempotent.
"""

import duckdb


def upgrade(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute("CREATE SEQUENCE IF NOT EXISTS positions_seq")
    conn.execute("CREATE SEQUENCE IF NOT EXISTS viewports_seq")
    conn.execute("CREATE SEQUENCE IF NOT EXISTS signups_seq")

    conn.execute("""
        CREATE TABLE IF NOT EXISTS vehicles (
            vehicle_id    VARCHAR NOT NULL PRIMARY KEY,
            description   VARCHAR,
            vehicle_type  VARCHAR,
            first_seen    TIMESTAMPTZ NOT NULL,
            last_seen     TIMESTAMPTZ NOT NULL
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS positions (
            id            BIGINT DEFAULT nextval('positions_seq'),
            vehicle_id    VARCHAR NOT NULL,
            timestamp     TIMESTAMPTZ NOT NULL,
            collected_at  TIMESTAMPTZ NOT NULL,
            longitude     DOUBLE NOT NULL,
            latitude      DOUBLE NOT NULL,
            bearing       INTEGER,
            speed         DOUBLE,
            is_driving    VARCHAR,
            PRIMARY KEY (vehicle_id, timestamp)
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_positions_time_geo
            ON positions (timestamp, latitude, longitude)
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS viewports (
            id          BIGINT DEFAULT nextval('viewports_seq') PRIMARY KEY,
            timestamp   TIMESTAMPTZ NOT NULL DEFAULT now(),
            zoom        DOUBLE NOT NULL,
            center_lng  DOUBLE NOT NULL,
            center_lat  DOUBLE NOT NULL,
            sw_lng      DOUBLE NOT NULL,
            sw_lat      DOUBLE NOT NULL,
            ne_lng      DOUBLE NOT NULL,
            ne_lat      DOUBLE NOT NULL
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS signups (
            id              BIGINT DEFAULT nextval('signups_seq') PRIMARY KEY,
            timestamp       TIMESTAMPTZ NOT NULL DEFAULT now(),
            email           VARCHAR NOT NULL,
            notify_plow     BOOLEAN NOT NULL DEFAULT FALSE,
            notify_projects BOOLEAN NOT NULL DEFAULT FALSE,
            notify_siliconharbour BOOLEAN NOT NULL DEFAULT FALSE,
            note            VARCHAR
        )
    """)

    # Legacy migration: add geom column to positions
    cols = {r[0] for r in conn.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name='positions'"
    ).fetchall()}
    if "geom" not in cols:
        conn.execute("ALTER TABLE positions ADD COLUMN geom GEOMETRY")

    # Backfill geom
    conn.execute(
        "UPDATE positions SET geom = ST_Point(longitude, latitude) WHERE geom IS NULL"
    )

    # Legacy migration: add ip/user_agent to viewports
    vp_cols = {r[0] for r in conn.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name='viewports'"
    ).fetchall()}
    if "ip" not in vp_cols:
        conn.execute("ALTER TABLE viewports ADD COLUMN ip VARCHAR")
    if "user_agent" not in vp_cols:
        conn.execute("ALTER TABLE viewports ADD COLUMN user_agent VARCHAR")

    # Legacy migration: add ip/user_agent to signups
    su_cols = {r[0] for r in conn.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name='signups'"
    ).fetchall()}
    if su_cols:
        if "ip" not in su_cols:
            conn.execute("ALTER TABLE signups ADD COLUMN ip VARCHAR")
        if "user_agent" not in su_cols:
            conn.execute("ALTER TABLE signups ADD COLUMN user_agent VARCHAR")


def downgrade(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute("DROP TABLE IF EXISTS signups")
    conn.execute("DROP TABLE IF EXISTS viewports")
    conn.execute("DROP TABLE IF EXISTS positions")
    conn.execute("DROP TABLE IF EXISTS vehicles")
    conn.execute("DROP SEQUENCE IF EXISTS signups_seq")
    conn.execute("DROP SEQUENCE IF EXISTS viewports_seq")
    conn.execute("DROP SEQUENCE IF EXISTS positions_seq")
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_migrate.py::test_001_fresh_db_creates_tables -v`
Expected: PASS

**Step 5: Commit**

```
git add src/where_the_plow/migrations/__init__.py src/where_the_plow/migrations/001_initial_schema.py tests/test_migrate.py
git commit -m "feat: add migration 001 (baseline schema)"
```

---

### Task 3: Migration 002 — add source columns

This is the multi-source table recreation. Extracted from the current inline migration code in `db.py`.

**Files:**
- Create: `src/where_the_plow/migrations/002_add_source_columns.py`
- Test: `tests/test_migrate.py` (add test against copy of og-prod-plow.db)

**Step 1: Write failing test**

Add to `tests/test_migrate.py`:

```python
import shutil

def test_002_migrates_prod_db(tmp_path):
    """Migration 002 adds source columns to a real production DB copy."""
    prod_src = Path(__file__).parent.parent / "data" / "og-prod-plow.db"
    if not prod_src.exists():
        pytest.skip("og-prod-plow.db not available")

    test_db = tmp_path / "prod-copy.db"
    shutil.copy2(prod_src, test_db)

    conn = duckdb.connect(str(test_db))
    conn.execute("LOAD spatial")

    migrations_dir = Path(__file__).parent.parent / "src" / "where_the_plow" / "migrations"
    run_migrations(conn, migrations_dir)

    assert get_version(conn) == 2

    # Vehicles should have source column with composite PK
    veh_cols = {r[0] for r in conn.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name='vehicles'"
    ).fetchall()}
    assert "source" in veh_cols

    veh_pks = conn.execute(
        "SELECT constraint_column_names FROM duckdb_constraints() "
        "WHERE table_name='vehicles' AND constraint_type='PRIMARY KEY'"
    ).fetchone()
    assert set(veh_pks[0]) == {"vehicle_id", "source"}

    # Positions should have source column with composite PK
    pos_cols = {r[0] for r in conn.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name='positions'"
    ).fetchall()}
    assert "source" in pos_cols

    pos_pks = conn.execute(
        "SELECT constraint_column_names FROM duckdb_constraints() "
        "WHERE table_name='positions' AND constraint_type='PRIMARY KEY'"
    ).fetchone()
    assert set(pos_pks[0]) == {"vehicle_id", "timestamp", "source"}

    # All existing rows should have source='st_johns'
    non_stj = conn.execute(
        "SELECT count(*) FROM vehicles WHERE source != 'st_johns'"
    ).fetchone()[0]
    assert non_stj == 0

    # Row count should be preserved
    count = conn.execute("SELECT count(*) FROM positions").fetchone()[0]
    assert count > 0  # og-prod-plow.db has ~917k rows

    conn.close()
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_migrate.py::test_002_migrates_prod_db -v`
Expected: FAIL — migration 002 doesn't exist yet.

**Step 3: Write migration 002**

```python
# src/where_the_plow/migrations/002_add_source_columns.py
"""Add source column to vehicles and positions tables.

DuckDB doesn't support ALTER TABLE ADD COLUMN with NOT NULL/DEFAULT
constraints, and can't alter primary keys. We recreate both tables
with composite PKs that include the source column.

Existing rows are assigned source='st_johns'.
Idempotent: checks column existence before acting.
"""

import duckdb


def _table_has_column(conn: duckdb.DuckDBPyConnection, table: str, column: str) -> bool:
    rows = conn.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name=? AND column_name=?",
        [table, column],
    ).fetchall()
    return len(rows) > 0


def upgrade(conn: duckdb.DuckDBPyConnection) -> None:
    if not _table_has_column(conn, "vehicles", "source"):
        conn.execute("""
            CREATE TABLE vehicles_new (
                vehicle_id    VARCHAR NOT NULL,
                description   VARCHAR,
                vehicle_type  VARCHAR,
                first_seen    TIMESTAMPTZ NOT NULL,
                last_seen     TIMESTAMPTZ NOT NULL,
                source        VARCHAR NOT NULL DEFAULT 'st_johns',
                PRIMARY KEY (vehicle_id, source)
            )
        """)
        conn.execute("""
            INSERT INTO vehicles_new
                (vehicle_id, description, vehicle_type, first_seen, last_seen, source)
            SELECT vehicle_id, description, vehicle_type, first_seen, last_seen, 'st_johns'
            FROM vehicles
        """)
        conn.execute("DROP TABLE vehicles")
        conn.execute("ALTER TABLE vehicles_new RENAME TO vehicles")

    if not _table_has_column(conn, "positions", "source"):
        conn.execute("CREATE SEQUENCE IF NOT EXISTS positions_mig_seq")
        conn.execute("""
            CREATE TABLE positions_new (
                id            BIGINT DEFAULT nextval('positions_mig_seq'),
                vehicle_id    VARCHAR NOT NULL,
                timestamp     TIMESTAMPTZ NOT NULL,
                collected_at  TIMESTAMPTZ NOT NULL,
                longitude     DOUBLE NOT NULL,
                latitude      DOUBLE NOT NULL,
                geom          GEOMETRY,
                bearing       INTEGER,
                speed         DOUBLE,
                is_driving    VARCHAR,
                source        VARCHAR NOT NULL DEFAULT 'st_johns',
                PRIMARY KEY (vehicle_id, timestamp, source)
            )
        """)
        conn.execute("""
            INSERT INTO positions_new
                (id, vehicle_id, timestamp, collected_at, longitude, latitude,
                 geom, bearing, speed, is_driving, source)
            SELECT id, vehicle_id, timestamp, collected_at, longitude, latitude,
                   geom, bearing, speed, is_driving, 'st_johns'
            FROM positions
        """)
        conn.execute("DROP TABLE positions")
        conn.execute("ALTER TABLE positions_new RENAME TO positions")
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_positions_time_geo
                ON positions (timestamp, latitude, longitude)
        """)


def downgrade(conn: duckdb.DuckDBPyConnection) -> None:
    """Reverse: recreate tables without source column."""
    if _table_has_column(conn, "positions", "source"):
        conn.execute("""
            CREATE TABLE positions_old (
                id            BIGINT DEFAULT nextval('positions_seq'),
                vehicle_id    VARCHAR NOT NULL,
                timestamp     TIMESTAMPTZ NOT NULL,
                collected_at  TIMESTAMPTZ NOT NULL,
                longitude     DOUBLE NOT NULL,
                latitude      DOUBLE NOT NULL,
                geom          GEOMETRY,
                bearing       INTEGER,
                speed         DOUBLE,
                is_driving    VARCHAR,
                PRIMARY KEY (vehicle_id, timestamp)
            )
        """)
        conn.execute("""
            INSERT INTO positions_old
            SELECT id, vehicle_id, timestamp, collected_at, longitude, latitude,
                   geom, bearing, speed, is_driving
            FROM positions WHERE source = 'st_johns'
        """)
        conn.execute("DROP TABLE positions")
        conn.execute("ALTER TABLE positions_old RENAME TO positions")

    if _table_has_column(conn, "vehicles", "source"):
        conn.execute("""
            CREATE TABLE vehicles_old (
                vehicle_id    VARCHAR NOT NULL PRIMARY KEY,
                description   VARCHAR,
                vehicle_type  VARCHAR,
                first_seen    TIMESTAMPTZ NOT NULL,
                last_seen     TIMESTAMPTZ NOT NULL
            )
        """)
        conn.execute("""
            INSERT INTO vehicles_old
            SELECT vehicle_id, description, vehicle_type, first_seen, last_seen
            FROM vehicles WHERE source = 'st_johns'
        """)
        conn.execute("DROP TABLE vehicles")
        conn.execute("ALTER TABLE vehicles_old RENAME TO vehicles")
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_migrate.py::test_002_migrates_prod_db -v`
Expected: PASS

**Step 5: Commit**

```
git add src/where_the_plow/migrations/002_add_source_columns.py tests/test_migrate.py
git commit -m "feat: add migration 002 (source columns for multi-source)"
```

---

### Task 4: Wire into `Database.init()` and remove inline migrations

Replace all the inline schema/migration SQL in `db.py` with a single call to the runner.

**Files:**
- Modify: `src/where_the_plow/db.py:19-206` (the entire `init()` method)
- Test: run existing `tests/test_db.py` to verify nothing breaks

**Step 1: Update `Database.init()`**

Replace the `init()` method body with:

```python
def init(self):
    cur = self._cursor()
    cur.execute("INSTALL spatial")
    cur.execute("LOAD spatial")

    from where_the_plow.migrate import run_migrations
    migrations_dir = Path(__file__).parent / "migrations"
    run_migrations(cur, migrations_dir)
```

Add `from pathlib import Path` to the top of `db.py`.

**Step 2: Run the full test suite**

Run: `uv run pytest --tb=short -q`
Expected: all tests pass (83 existing + new migration tests).

**Step 3: Verify against prod DB copy**

Run manually or in a test: copy `og-prod-plow.db` to a temp file, instantiate `Database` on it, call `init()`, verify schema is correct.

**Step 4: Commit**

```
git add src/where_the_plow/db.py
git commit -m "refactor: replace inline migrations with migration runner"
```

---

### Task 5: Stamp existing databases

Production already has the full schema (including source columns) but no `schema_version` table. When we deploy, migration 001 and 002 will both try to run. That's fine — they're idempotent. But we should add a test proving this path works: an already-migrated DB (with source columns) gets stamped to version 2 without errors.

**Files:**
- Test: `tests/test_migrate.py` (add test)

**Step 1: Write the test**

```python
def test_already_migrated_db_gets_stamped(tmp_path):
    """A DB that already has the full schema gets stamped without errors."""
    conn = duckdb.connect(str(tmp_path / "already.db"))
    conn.execute("INSTALL spatial; LOAD spatial")

    # Simulate a DB that was created by the old init() — has everything
    # including source columns, but no schema_version table.
    conn.execute("CREATE SEQUENCE IF NOT EXISTS positions_seq")
    conn.execute("""
        CREATE TABLE vehicles (
            vehicle_id VARCHAR NOT NULL,
            description VARCHAR,
            vehicle_type VARCHAR,
            first_seen TIMESTAMPTZ NOT NULL,
            last_seen TIMESTAMPTZ NOT NULL,
            source VARCHAR NOT NULL DEFAULT 'st_johns',
            PRIMARY KEY (vehicle_id, source)
        )
    """)
    conn.execute("""
        CREATE TABLE positions (
            id BIGINT DEFAULT nextval('positions_seq'),
            vehicle_id VARCHAR NOT NULL,
            timestamp TIMESTAMPTZ NOT NULL,
            collected_at TIMESTAMPTZ NOT NULL,
            longitude DOUBLE NOT NULL,
            latitude DOUBLE NOT NULL,
            geom GEOMETRY,
            bearing INTEGER,
            speed DOUBLE,
            is_driving VARCHAR,
            source VARCHAR NOT NULL DEFAULT 'st_johns',
            PRIMARY KEY (vehicle_id, timestamp, source)
        )
    """)

    migrations_dir = Path(__file__).parent.parent / "src" / "where_the_plow" / "migrations"
    run_migrations(conn, migrations_dir)

    # Should be stamped at version 2 with no errors
    assert get_version(conn) == 2
    conn.close()
```

**Step 2: Run test**

Run: `uv run pytest tests/test_migrate.py::test_already_migrated_db_gets_stamped -v`
Expected: PASS

**Step 3: Commit**

```
git add tests/test_migrate.py
git commit -m "test: verify already-migrated DBs get stamped correctly"
```

---

### Task 6: Clean up old migration tests in `test_db.py`

The existing `test_db.py` has tests for the old inline migration code (source column migration, idempotent migration, pre-source schema). These should be removed or updated since the migration logic has moved to migration files.

**Files:**
- Modify: `tests/test_db.py`

**Step 1: Review and update `test_db.py`**

Remove tests that were specifically testing the inline migration hacks:
- `test_migration_adds_source_columns`
- `test_migration_is_idempotent`
- `test_migrate_from_pre_source_schema`

These are now covered by `test_migrate.py`. Keep all other `test_db.py` tests (upsert, query, coverage, etc.).

**Step 2: Run full suite**

Run: `uv run pytest --tb=short -q`
Expected: all pass.

**Step 3: Commit**

```
git add tests/test_db.py
git commit -m "refactor: remove old inline migration tests (now in test_migrate.py)"
```
