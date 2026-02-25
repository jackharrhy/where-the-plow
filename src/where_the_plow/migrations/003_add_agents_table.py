"""Add agents table for distributed fetch network."""

import duckdb


def upgrade(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS agents (
            agent_id       VARCHAR PRIMARY KEY,
            name           VARCHAR NOT NULL,
            public_key     VARCHAR NOT NULL,
            enabled        BOOLEAN DEFAULT TRUE,
            created_at     TIMESTAMPTZ NOT NULL,
            last_seen_at   TIMESTAMPTZ,
            total_reports  INTEGER DEFAULT 0,
            failed_reports INTEGER DEFAULT 0
        )
    """)
