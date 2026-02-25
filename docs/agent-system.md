# Agent System — Operator Guide

How the distributed agent network works, how to operate it, and what to
do when things break.

## The problem

The production server's IP is blocked by the St. John's WAF (F5 BIG-IP).
The entire domain `map.stjohns.ca` returns a CAPTCHA challenge from the
server. Agents run on volunteer residential IPs that aren't blocked.

## Architecture

```
Volunteer 1           Volunteer 2           Volunteer N
┌─────────┐          ┌─────────┐          ┌─────────┐
│plow-agent│          │plow-agent│          │plow-agent│
└────┬─────┘          └────┬─────┘          └────┬─────┘
     │ signed reports      │                     │
     └─────────────────────┼─────────────────────┘
                           ▼
                   ┌───────────────┐
                   │  plow server  │
                   │  (FastAPI)    │
                   │               │
                   │ coordinator → │ assigns schedules
                   │ agent_routes → │ receives reports
                   │ collector   → │ skips direct fetch
                   └───────────────┘
```

**Data flow:**

1. Agent registers with the server (self-registration, generates its own
   ECDSA keypair, sends public key)
2. Admin approves the agent via `/admin`
3. Server assigns a fetch schedule — N agents each fetch every `6*N`
   seconds with staggered offsets, so globally there's a fetch every ~6s
4. Agent fetches AVL data from `map.stjohns.ca` using browser-like headers
5. Agent signs the response body with its private key and POSTs to
   `/agents/report`
6. Server verifies the signature, parses the AVL data, inserts into DuckDB
7. While agents are active (last report <30s ago), the server's own
   collector skips the St. John's source

## Day-to-day operations

### Admin panel

Go to `/admin` on the server. Login with the `ADMIN_PASSWORD` env var.

**What you see:**

- **Collector** section: pause/resume button for St. John's. Use this
  when setting up agents for the first time — pause the collector, get
  agents approved and running, then resume (or leave paused and let agents
  handle it)
- **Agents** table: name, ID, status, health, IP, last seen, reports
  (success/failed), and approve/revoke buttons
- **Health** column: `healthy` (green), `degraded` (orange, 5+ consecutive
  failures), `hibernating` (red, 30+ consecutive failures)

### Setting up a new agent

1. Have your volunteer download the binary from GitHub Releases, or pull
   the Docker image
2. They run it: `./plow-agent --server https://plow.jackharrhy.dev`
3. It generates a keypair, registers with the server, and prints
   "Waiting for approval..."
4. You see it appear as "pending" in the admin panel
5. Click "Approve"
6. The agent starts fetching and reporting within seconds

### When an agent gets WAF'd

The agent detects consecutive fetch failures and reacts:

- **Failures 1-4**: normal operation, errors reported to server
- **Failures 5-29**: exponential backoff (6s → 12s → 24s → ... → 10min
  cap). The admin panel shows `degraded` (orange)
- **Failures 30+**: agent enters **hibernate mode**. It stops fetching
  and instead checks in with the server every 10 minutes. Each checkin
  includes a single probe fetch to test if the block has lifted. The
  admin panel shows `hibernating` (red)
- **Recovery**: if any fetch succeeds, the agent resets to normal
  operation immediately

You don't need to restart agents manually. They'll come back on their own
if the WAF unblocks their IP.

### When the server's IP gets unblocked

If you get the city to whitelist the server IP, you can stop using agents
entirely:

1. Revoke all agents in the admin panel (or just leave them — the server's
   own collector will automatically start fetching when no agents have
   reported in the last 30 seconds)
2. The collector resumes direct fetching

### Collector pause behavior

The pause button in the admin panel only pauses the **server's direct
polling** of the St. John's AVL source. It does NOT pause agent report
processing — agent data still flows in. This is intentional: the pause
is for the server's own fetching, not for the entire data pipeline.

The pause state is **in-memory only**. If the server restarts, the
collector resumes automatically. This is deliberate — it's an operational
toggle, not a persistent config.

## Authentication

Two separate auth systems:

**Admin auth**: password-based. Set `ADMIN_PASSWORD` env var. Stored as
an HMAC cookie. Used for the `/admin` panel.

**Agent auth**: ECDSA P-256. Each agent generates its own keypair on first
run. The public key is sent during registration. All subsequent requests
(checkin, report) are signed: `SHA-256(body || timestamp_bytes)` signed
with the private key, sent as `X-Agent-Sig` header. The server verifies
against the stored public key. Timestamps must be within 30 seconds.

## Configuration

All via environment variables (or `.env` file — pydantic-settings handles
this automatically):

| Variable | Default | Purpose |
|---|---|---|
| `ADMIN_PASSWORD` | (none) | Required for admin panel |
| `DB_PATH` | `/data/plow.db` | DuckDB file location |
| `SOURCE_ST_JOHNS_ENABLED` | `true` | Enable St. John's source |
| `SOURCE_MT_PEARL_ENABLED` | `true` | Enable Mt. Pearl source |
| `SOURCE_PROVINCIAL_ENABLED` | `true` | Enable Provincial source |

See `.env.dist` for the full template.

## Database

The agents table is managed by migrations 003-005:

| Column | Purpose |
|---|---|
| `agent_id` | SHA-256 fingerprint of public key (16 hex chars) |
| `name` | Human-readable name (set by volunteer) |
| `public_key` | ECDSA P-256 public key PEM |
| `status` | `pending`, `approved`, or `revoked` |
| `consecutive_failures` | Resets to 0 on success, increments on failure |
| `total_reports` | Lifetime successful reports |
| `failed_reports` | Lifetime failed reports |
| `last_seen_at` | Last time the agent submitted any report |
| `ip` | Registration IP (from X-Forwarded-For) |
| `system_info` | OS/arch from agent |

## Release process

Any push to `main` that touches `agent/**` triggers the GitHub Actions
workflow `.github/workflows/release-agent.yml`. It:

1. Creates a tag `agent-YYYY.MM.DD-<short-sha>`
2. Runs goreleaser to cross-compile for linux/darwin/windows (amd64+arm64)
3. Publishes binaries to a GitHub Release

The server's Docker image is built by the existing
`.github/workflows/build-and-push.yml` on pushes to `main`.

## File map

```
src/where_the_plow/
  agent_auth.py      — ECDSA key generation, signing, verification
  agent_routes.py    — /agents/register, /checkin, /report
  admin_routes.py    — /admin/login, /agents/*, /collector/pause|resume
  coordinator.py     — schedule computation, timestamp validation
  collector.py       — background polling, pause checks, agent fallback
  db.py              — agent CRUD, consecutive_failures tracking
  migrations/
    003_add_agents_table.py
    004_agent_status.py
    005_agent_consecutive_failures.py
  static/admin/      — admin panel (HTML/JS/CSS)

agent/
  main.go            — entry point, backoff/hibernate loop
  client.go          — register, checkin, report HTTP calls
  fetch.go           — AVL fetch with browser mimicry
  config.go          — credential storage (~/.config/plow-agent/)
  crypto.go          — ECDSA signing
  .goreleaser.yml    — cross-compile config
  build.sh           — local dev build
  Dockerfile         — container build
  k8s.yaml           — Kubernetes manifest
```
