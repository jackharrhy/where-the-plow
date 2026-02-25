"""Add consecutive_failures column to agents table for health tracking."""

import duckdb


def _has_column(conn, table, column):
    rows = conn.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name=? AND column_name=?",
        [table, column],
    ).fetchall()
    return len(rows) > 0


def upgrade(conn: duckdb.DuckDBPyConnection) -> None:
    if not _has_column(conn, "agents", "consecutive_failures"):
        conn.execute(
            "ALTER TABLE agents ADD COLUMN consecutive_failures INTEGER DEFAULT 0"
        )
