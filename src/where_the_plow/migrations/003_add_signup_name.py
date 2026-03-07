"""Add name column to signups table.

Stores the user's name alongside their email. NOT NULL with DEFAULT ''
so existing rows get an empty string.

DuckDB doesn't support ALTER TABLE ADD COLUMN with constraints, so we
recreate the table (same pattern as migration 002).
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
    if not _has_column(conn, "signups", "name"):
        conn.execute("CREATE SEQUENCE IF NOT EXISTS signups_mig_seq")
        conn.execute("""
            CREATE TABLE signups_new (
                id              BIGINT DEFAULT nextval('signups_mig_seq') PRIMARY KEY,
                timestamp       TIMESTAMPTZ NOT NULL DEFAULT now(),
                name            VARCHAR NOT NULL DEFAULT '',
                email           VARCHAR NOT NULL,
                ip              VARCHAR,
                user_agent      VARCHAR,
                notify_plow     BOOLEAN NOT NULL DEFAULT FALSE,
                notify_projects BOOLEAN NOT NULL DEFAULT FALSE,
                notify_siliconharbour BOOLEAN NOT NULL DEFAULT FALSE,
                note            VARCHAR
            )
        """)
        conn.execute("""
            INSERT INTO signups_new
                (id, timestamp, name, email, ip, user_agent,
                 notify_plow, notify_projects, notify_siliconharbour, note)
            SELECT id, timestamp, '', email, ip, user_agent,
                   notify_plow, notify_projects, notify_siliconharbour, note
            FROM signups
        """)
        conn.execute("DROP TABLE signups")
        conn.execute("ALTER TABLE signups_new RENAME TO signups")
