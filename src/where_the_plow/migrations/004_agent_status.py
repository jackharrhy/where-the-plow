"""Replace agents.enabled with status field, add system info columns."""

import duckdb


def _has_column(conn, table, column):
    rows = conn.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name=? AND column_name=?",
        [table, column],
    ).fetchall()
    return len(rows) > 0


def upgrade(conn: duckdb.DuckDBPyConnection) -> None:
    if _has_column(conn, "agents", "enabled") and not _has_column(
        conn, "agents", "status"
    ):
        conn.execute("""
            ALTER TABLE agents ADD COLUMN status VARCHAR DEFAULT 'approved'
        """)
        conn.execute("""
            UPDATE agents SET status = CASE WHEN enabled THEN 'approved' ELSE 'revoked' END
        """)
        conn.execute("ALTER TABLE agents DROP COLUMN enabled")

    if not _has_column(conn, "agents", "ip"):
        conn.execute("ALTER TABLE agents ADD COLUMN ip VARCHAR")

    if not _has_column(conn, "agents", "system_info"):
        conn.execute("ALTER TABLE agents ADD COLUMN system_info VARCHAR")
