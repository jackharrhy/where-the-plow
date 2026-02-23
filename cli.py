"""Dev CLI for where-the-plow."""

import csv
import html as html_mod
import io
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

COMMANDS = {
    "dev": "Run uvicorn in development mode with auto-reload",
    "start": "Run uvicorn in production mode",
    "changelog": "Convert CHANGELOG.md to an HTML fragment",
    "db-pull": "Pull production DB into data/backups/ (stops/starts prod)",
    "db-use-prod": "Copy a backup to data/plow.db for local dev",
    "signups": "Export newsletter signups to CSV and HTML",
}

APP = "where_the_plow.main:app"
ROOT = Path(__file__).parent
BACKUPS_DIR = ROOT / "data" / "backups"

PROD_HOST = "jack@jackharrhy.dev"
PROD_COMPOSE_DIR = "~/cookie-ops/core"
PROD_DB_PATH = "~/cookie-ops/core/volumes/plow/plow.db"
PROD_SERVICE = "plow"


def dev():
    subprocess.run(
        [
            sys.executable,
            "-m",
            "uvicorn",
            APP,
            "--reload",
            "--host",
            "0.0.0.0",
            "--port",
            "8000",
        ],
        env={**__import__("os").environ, "DB_PATH": "./data/plow.db"},
    )


def start():
    subprocess.run(
        [
            sys.executable,
            "-m",
            "uvicorn",
            APP,
            "--host",
            "0.0.0.0",
            "--port",
            "8000",
        ],
    )


def _confirm(prompt: str) -> bool:
    """Ask for y/n confirmation. Returns True on yes."""
    reply = input(f"{prompt} [y/N] ").strip().lower()
    return reply in ("y", "yes")


def _ssh(cmd: str) -> None:
    """Run a command on the production host via SSH."""
    result = subprocess.run(["ssh", PROD_HOST, cmd])
    if result.returncode != 0:
        print(f"SSH command failed: {cmd}", file=sys.stderr)
        sys.exit(1)


def _next_backup_number() -> int:
    """Return the next backup number (1-indexed)."""
    BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
    existing = sorted(BACKUPS_DIR.glob("*.db"))
    if not existing:
        return 1
    # Parse the number prefix from the latest file
    last = existing[-1].stem  # e.g. "003_2026-02-23T14-30-00"
    try:
        return int(last.split("_", 1)[0]) + 1
    except ValueError:
        return len(existing) + 1


def _list_backups() -> list[Path]:
    """Return sorted list of backup files."""
    if not BACKUPS_DIR.exists():
        return []
    return sorted(BACKUPS_DIR.glob("*.db"))


def _find_backup(n: int | None) -> Path:
    """Find a backup by number, or the latest if n is None."""
    backups = _list_backups()
    if not backups:
        print("No backups found in data/backups/", file=sys.stderr)
        sys.exit(1)
    if n is None:
        return backups[-1]
    for b in backups:
        try:
            num = int(b.stem.split("_", 1)[0])
            if num == n:
                return b
        except ValueError:
            continue
    print(f"Backup #{n} not found", file=sys.stderr)
    sys.exit(1)


def db_pull():
    BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
    num = _next_backup_number()
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
    dest = BACKUPS_DIR / f"{num:03d}_{ts}.db"

    print(f"Will save backup #{num} to {dest.relative_to(ROOT)}")

    if not _confirm(f"Stop {PROD_SERVICE} on prod?"):
        print("Aborted.")
        return

    _ssh(f"cd {PROD_COMPOSE_DIR} && docker compose stop {PROD_SERVICE}")
    print(f"{PROD_SERVICE} stopped.")

    try:
        if not _confirm(f"SCP prod DB to {dest.name}?"):
            print("Skipping pull.")
            return

        result = subprocess.run(
            ["scp", f"{PROD_HOST}:{PROD_DB_PATH}", str(dest)],
        )
        if result.returncode != 0:
            print("SCP failed", file=sys.stderr)
            sys.exit(1)

        size_mb = dest.stat().st_size / (1024 * 1024)
        print(f"Backup #{num} saved: {dest.name} ({size_mb:.1f} MB)")
    finally:
        if not _confirm(f"Start {PROD_SERVICE} on prod?"):
            print(f"WARNING: {PROD_SERVICE} is still stopped on prod!")
            return
        _ssh(f"cd {PROD_COMPOSE_DIR} && docker compose start {PROD_SERVICE}")
        print(f"{PROD_SERVICE} started.")


def db_use_prod():
    n = None
    if len(sys.argv) > 2:
        try:
            n = int(sys.argv[2])
        except ValueError:
            print(f"Invalid backup number: {sys.argv[2]}", file=sys.stderr)
            sys.exit(1)

    backup = _find_backup(n)
    local_db = ROOT / "data" / "plow.db"

    print(f"Copying {backup.name} -> data/plow.db")
    shutil.copy2(backup, local_db)
    size_mb = local_db.stat().st_size / (1024 * 1024)
    print(f"Done ({size_mb:.1f} MB)")


def _md_inline(text: str) -> str:
    """Convert inline markdown to HTML: bold, links, and issue references."""
    # Convert **text** to <strong>text</strong>
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    # Convert [text](url) to <a> tags
    text = re.sub(
        r"\[(.+?)\]\((.+?)\)",
        r'<a href="\2" target="_blank" rel="noopener">\1</a>',
        text,
    )
    # Convert standalone (#N) to issue links
    text = re.sub(
        r"\(#(\d+)\)",
        r'(<a href="https://github.com/jackharrhy/where-the-plow/issues/\1" target="_blank" rel="noopener">#\1</a>)',
        text,
    )
    return text


def changelog():
    root = Path(__file__).parent
    md_path = root / "CHANGELOG.md"
    out_path = root / "src" / "where_the_plow" / "static" / "changelog.html"

    content = md_path.read_text()

    # Extract changelog-id
    id_match = re.search(r"<!--\s*changelog-id:\s*(\d+)\s*-->", content)
    changelog_id = id_match.group(1) if id_match else "0"

    # Split on ## headings; first chunk is the header/preamble, skip it
    sections = re.split(r"^## ", content, flags=re.MULTILINE)

    articles = []
    for section in sections[1:]:
        lines = section.strip()
        # First line is the title
        title, _, body = lines.partition("\n")
        title = title.strip()
        body = body.strip()

        # Split body into paragraphs on double newlines
        paragraphs = re.split(r"\n\n+", body)
        p_html = []
        for para in paragraphs:
            if not para.strip():
                continue
            # Within a paragraph block, lines starting with [ (a link)
            # are separate paragraphs (e.g. "View changes" links)
            sub_parts: list[list[str]] = [[]]
            for line in para.strip().splitlines():
                stripped = line.strip()
                if not stripped:
                    continue
                if stripped.startswith("[") and sub_parts[-1]:
                    sub_parts.append([stripped])
                else:
                    sub_parts[-1].append(stripped)
            for part in sub_parts:
                if not part:
                    continue
                text = " ".join(part)
                text = _md_inline(text)
                p_html.append(f"<p>{text}</p>")

        article = (
            f"<article>\n<h2>{_md_inline(title)}</h2>\n"
            + "\n".join(p_html)
            + "\n</article>"
        )
        articles.append(article)

    html = f'<div class="changelog" data-changelog-id="{changelog_id}">\n'
    html += "\n".join(articles)
    html += "\n</div>\n"

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html)
    print(f"Wrote changelog.html (changelog-id: {changelog_id})")


def signups():
    import duckdb

    db_path = ROOT / "data" / "plow.db"
    if not db_path.exists():
        print(f"Database not found: {db_path}", file=sys.stderr)
        sys.exit(1)

    conn = duckdb.connect(str(db_path), read_only=True)
    rows = conn.execute(
        """
        SELECT id, timestamp, email, notify_plow, notify_projects,
               notify_siliconharbour, note, ip, user_agent
        FROM signups
        ORDER BY timestamp DESC
        """
    ).fetchall()
    columns = [
        "id",
        "timestamp",
        "email",
        "notify_plow",
        "notify_projects",
        "notify_siliconharbour",
        "note",
        "ip",
        "user_agent",
    ]
    conn.close()

    out_dir = ROOT / "data"
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "signups.csv"
    html_path = out_dir / "signups.html"

    # ── CSV ──
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(columns)
    writer.writerows(rows)
    csv_path.write_text(buf.getvalue())

    # ── HTML ──
    def _esc(val):
        if val is None:
            return '<span class="null">-</span>'
        if isinstance(val, bool):
            return "yes" if val else "no"
        return html_mod.escape(str(val))

    def _bool_badge(val):
        if val:
            return '<span class="badge yes">yes</span>'
        return '<span class="badge no">no</span>'

    cards_html = []
    for row in rows:
        r = dict(zip(columns, row))
        flags = []
        if r["notify_plow"]:
            flags.append("Plow alerts")
        if r["notify_projects"]:
            flags.append("Other projects")
        if r["notify_siliconharbour"]:
            flags.append("Silicon Harbour")
        flags_str = ", ".join(flags) if flags else "None"

        note_block = ""
        if r["note"]:
            note_block = (
                f'<div class="note">'
                f'<div class="note-label">Note</div>'
                f"{_esc(r['note'])}"
                f"</div>"
            )

        cards_html.append(f"""\
<div class="card">
  <div class="card-header">
    <span class="email">{_esc(r["email"])}</span>
    <span class="id">#{r["id"]}</span>
  </div>
  <div class="meta">
    <span>{_esc(r["timestamp"])}</span>
    <span>{_esc(r["ip"])}</span>
  </div>
  <div class="flags">Subscriptions: {flags_str}</div>
  {note_block}
  <div class="ua">{_esc(r["user_agent"])}</div>
</div>""")

    page = f"""\
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Signups ({len(rows)})</title>
<style>
  :root {{
    --bg: #0f172a;
    --card-bg: #1e293b;
    --border: #334155;
    --text: #e2e8f0;
    --text-muted: #94a3b8;
    --accent: #60a5fa;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: system-ui, -apple-system, sans-serif;
    background: var(--bg); color: var(--text);
    padding: 24px; line-height: 1.5;
  }}
  h1 {{ font-size: 20px; margin-bottom: 16px; }}
  h1 span {{ color: var(--text-muted); font-weight: 400; }}
  .cards {{ display: flex; flex-direction: column; gap: 12px; max-width: 720px; }}
  .card {{
    background: var(--card-bg); border: 1px solid var(--border);
    border-radius: 8px; padding: 14px 18px;
  }}
  .card-header {{ display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 4px; }}
  .email {{ font-weight: 600; color: var(--accent); }}
  .id {{ color: var(--text-muted); font-size: 12px; }}
  .meta {{ font-size: 12px; color: var(--text-muted); display: flex; gap: 16px; margin-bottom: 6px; }}
  .flags {{ font-size: 13px; margin-bottom: 6px; }}
  .badge {{
    display: inline-block; padding: 1px 6px; border-radius: 4px;
    font-size: 11px; font-weight: 600;
  }}
  .badge.yes {{ background: rgba(34,197,94,0.2); color: #4ade80; }}
  .badge.no {{ background: rgba(239,68,68,0.15); color: #f87171; }}
  .note {{
    background: rgba(255,255,255,0.05); border-radius: 6px;
    padding: 8px 10px; margin: 6px 0; font-size: 13px;
    white-space: pre-wrap;
  }}
  .note-label {{ font-size: 11px; color: var(--text-muted); margin-bottom: 2px; text-transform: uppercase; letter-spacing: 0.05em; }}
  .ua {{ font-size: 11px; color: var(--text-muted); word-break: break-all; }}
  .null {{ color: var(--text-muted); }}
</style>
</head>
<body>
<h1>Newsletter Signups <span>({len(rows)})</span></h1>
<div class="cards">
{"".join(cards_html)}
</div>
</body>
</html>
"""
    html_path.write_text(page)

    print(f"Exported {len(rows)} signups")
    print(f"  CSV:  {csv_path.relative_to(ROOT)}")
    print(f"  HTML: {html_path.relative_to(ROOT)}")


def usage():
    print("Usage: uv run cli.py <command>\n")
    print("Commands:")
    for name, desc in COMMANDS.items():
        print(f"  {name:14s} {desc}")
    sys.exit(1)


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        usage()

    cmd = sys.argv[1]
    dispatch = {
        "dev": dev,
        "start": start,
        "changelog": changelog,
        "db-pull": db_pull,
        "db-use-prod": db_use_prod,
        "signups": signups,
    }
    dispatch[cmd]()


if __name__ == "__main__":
    main()
