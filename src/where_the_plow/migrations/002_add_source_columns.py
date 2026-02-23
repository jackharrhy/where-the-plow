# src/where_the_plow/migrations/002_add_source_columns.py
"""Add source column to vehicles and positions tables.

DuckDB doesn't support ALTER TABLE ADD COLUMN with NOT NULL/DEFAULT
constraints, and can't alter primary keys. We recreate both tables
with composite PKs that include the source column.

Existing rows are assigned source='st_johns'.
Idempotent: checks column existence before acting.
"""

import duckdb


def _has_column(conn: duckdb.DuckDBPyConnection, table: str, column: str) -> bool:
    rows = conn.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name=? AND column_name=?",
        [table, column],
    ).fetchall()
    return len(rows) > 0


def upgrade(conn: duckdb.DuckDBPyConnection) -> None:
    if not _has_column(conn, "vehicles", "source"):
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

    if not _has_column(conn, "positions", "source"):
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
    pass  # Not implementing downgrade for now
