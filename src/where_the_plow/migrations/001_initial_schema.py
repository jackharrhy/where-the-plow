"""Migration 001: baseline schema.

Represents the original production schema (before multi-source) as seen in
data/og-prod-plow.db.  On a fresh DB this creates everything; on an existing
DB the CREATE TABLE IF NOT EXISTS / CREATE SEQUENCE IF NOT EXISTS statements
are no-ops.

Also includes the legacy column-add migrations that are already baked into
production:
  - geom on positions  (+ backfill)
  - ip / user_agent on viewports
  - ip / user_agent on signups
"""

import duckdb


def _has_column(conn: duckdb.DuckDBPyConnection, table: str, column: str) -> bool:
    """Check whether *table* already has *column*."""
    rows = conn.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = ? AND column_name = ?",
        [table, column],
    ).fetchall()
    return len(rows) > 0


def upgrade(conn: duckdb.DuckDBPyConnection) -> None:
    # -- vehicles ---------------------------------------------------------------
    conn.execute("""
        CREATE TABLE IF NOT EXISTS vehicles (
            vehicle_id    VARCHAR NOT NULL PRIMARY KEY,
            description   VARCHAR,
            vehicle_type  VARCHAR,
            first_seen    TIMESTAMPTZ NOT NULL,
            last_seen     TIMESTAMPTZ NOT NULL
        )
    """)

    # -- positions --------------------------------------------------------------
    conn.execute("CREATE SEQUENCE IF NOT EXISTS positions_seq")
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

    # -- viewports --------------------------------------------------------------
    conn.execute("CREATE SEQUENCE IF NOT EXISTS viewports_seq")
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

    # -- signups ----------------------------------------------------------------
    conn.execute("CREATE SEQUENCE IF NOT EXISTS signups_seq")
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

    # =========================================================================
    # Legacy migrations (idempotent column adds)
    # =========================================================================

    # -- geom on positions ------------------------------------------------------
    if not _has_column(conn, "positions", "geom"):
        conn.execute("ALTER TABLE positions ADD COLUMN geom GEOMETRY")

    # Backfill geom for any rows where it is NULL
    conn.execute(
        "UPDATE positions SET geom = ST_Point(longitude, latitude) WHERE geom IS NULL"
    )

    # -- ip / user_agent on viewports ------------------------------------------
    if not _has_column(conn, "viewports", "ip"):
        conn.execute("ALTER TABLE viewports ADD COLUMN ip VARCHAR")
    if not _has_column(conn, "viewports", "user_agent"):
        conn.execute("ALTER TABLE viewports ADD COLUMN user_agent VARCHAR")

    # -- ip / user_agent on signups --------------------------------------------
    if not _has_column(conn, "signups", "ip"):
        conn.execute("ALTER TABLE signups ADD COLUMN ip VARCHAR")
    if not _has_column(conn, "signups", "user_agent"):
        conn.execute("ALTER TABLE signups ADD COLUMN user_agent VARCHAR")
