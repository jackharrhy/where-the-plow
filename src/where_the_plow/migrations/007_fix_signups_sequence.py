"""Fix signups auto-increment sequence.

Migration 006 recreated the signups table with a new sequence
(signups_mig_seq) that started at 1 instead of after the max existing id.
This caused primary key conflicts on new inserts.

Fix: recreate the table with a sequence seeded past max(id).
Idempotent: only acts if the current sequence would produce a conflict.
"""

import duckdb


def _find_signups_sequence(conn: duckdb.DuckDBPyConnection) -> str | None:
    """Return the name of the sequence used by signups.id, if any."""
    row = conn.execute(
        "SELECT column_default FROM information_schema.columns "
        "WHERE table_name='signups' AND column_name='id'"
    ).fetchone()
    if not row or not row[0]:
        return None
    # Default looks like: nextval('signups_mig_seq')
    default = row[0]
    if "nextval" in default and "'" in default:
        return default.split("'")[1]
    return None


def upgrade(conn: duckdb.DuckDBPyConnection) -> None:
    row = conn.execute("SELECT coalesce(max(id), 0) FROM signups").fetchone()
    max_id = row[0] if row else 0

    if max_id == 0:
        # Empty table — nothing to fix.
        return

    seq_name = _find_signups_sequence(conn)
    if not seq_name:
        return

    # Check if the sequence is already past max_id by peeking at nextval.
    next_id = conn.execute(f"SELECT nextval('{seq_name}')").fetchone()[0]

    if next_id > max_id:
        # Sequence is already ahead — no fix needed.  But we consumed one
        # value with the nextval above; that's harmless (just a gap).
        return

    # Need to recreate with a properly-seeded sequence.
    start = max_id + 1
    conn.execute(f"CREATE SEQUENCE signups_fix_seq START WITH {start}")
    conn.execute("""
        CREATE TABLE signups_fixed (
            id              BIGINT DEFAULT nextval('signups_fix_seq') PRIMARY KEY,
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
        INSERT INTO signups_fixed
            (id, timestamp, name, email, ip, user_agent,
             notify_plow, notify_projects, notify_siliconharbour, note)
        SELECT id, timestamp, name, email, ip, user_agent,
               notify_plow, notify_projects, notify_siliconharbour, note
        FROM signups
    """)
    conn.execute("DROP TABLE signups")
    conn.execute("ALTER TABLE signups_fixed RENAME TO signups")
