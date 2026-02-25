# Distributed Agent Network for AVL Data Collection

## Problem

The city's WAF (F5 BIG-IP bot defense) has blocked the production server's IP
from accessing `map.stjohns.ca`. The entire domain returns a captcha challenge
page instead of data. We need a way to fetch the public AVL data from multiple
residential/personal IPs to avoid any single IP being flagged.

## Overview

Two components: **agents** (Go binaries run by friends) and a **coordinator**
(inside the existing FastAPI app).

Agents periodically fetch AVL data from `map.stjohns.ca` using their own IP
addresses and POST the signed results to the plow server. The coordinator
manages agent registration, assigns fetch schedules, verifies signatures, and
feeds data into the existing collection pipeline.

## Agent (`plow-agent`)

### Binary

Lightweight Go binary. Distributed as:
- Static binaries (Linux amd64/arm64, macOS amd64/arm64)
- Minimal Docker image (`FROM scratch`)

### Configuration

- `--server` — plow server URL (e.g. `https://plow.jackharrhy.dev`)
- `--key` — ECDSA P-256 private key (PEM string or path to file)

### Startup

1. Load ECDSA private key
2. Derive agent ID from public key fingerprint (SHA-256 of DER-encoded public
   key, hex-encoded, first 16 chars)
3. `POST /agents/checkin` signed with key
4. Receive schedule: `{"fetch_url", "interval_seconds", "offset_seconds",
   "headers"}`
5. Enter fetch loop

### Fetch Loop

1. Wait for next scheduled time (interval + random jitter of +/-1-3s)
2. Pick a random User-Agent from built-in pool of ~10 common browser strings
3. Set browser-like headers: `Accept`, `Accept-Language`,
   `Accept-Encoding`, `Referer` (from schedule)
4. GET the AVL URL
5. POST raw response body to `/agents/report` with:
   - `X-Agent-Id` — agent fingerprint
   - `X-Agent-Sig` — ECDSA signature of `body + X-Agent-Ts` (base64)
   - `X-Agent-Ts` — Unix timestamp (seconds)
6. Read response for updated schedule
7. On fetch failure (timeout, non-JSON response, etc.), still POST to
   `/agents/report` with an error payload so coordinator knows

### Signature Scheme

- Sign: `SHA-256(body || timestamp_string)` using ECDSA P-256
- Encode signature as base64 in `X-Agent-Sig`
- Timestamp in `X-Agent-Ts` as Unix seconds string

## Coordinator (FastAPI)

### Database

New `agents` table in DuckDB:

```sql
CREATE TABLE IF NOT EXISTS agents (
    agent_id     VARCHAR PRIMARY KEY,  -- public key fingerprint
    name         VARCHAR NOT NULL,
    public_key   VARCHAR NOT NULL,     -- PEM-encoded ECDSA public key
    enabled      BOOLEAN DEFAULT TRUE,
    created_at   TIMESTAMPTZ NOT NULL,
    last_seen_at TIMESTAMPTZ,
    total_reports INTEGER DEFAULT 0,
    failed_reports INTEGER DEFAULT 0
)
```

### Agent-Facing Endpoints

**`POST /agents/checkin`**
- Headers: `X-Agent-Id`, `X-Agent-Sig`, `X-Agent-Ts`
- Body: empty or `{}`
- Verifies signature, checks agent exists and is enabled
- Updates `last_seen_at`
- Returns current schedule

**`POST /agents/report`**
- Headers: `X-Agent-Id`, `X-Agent-Sig`, `X-Agent-Ts`
- Body: raw JSON from AVL endpoint (or error payload)
- Verifies signature against stored public key
- Checks timestamp within +/-30s window (replay protection)
- Validates body is JSON with `features` array (rejects captcha pages)
- Feeds valid data into `parse_avl_response()` -> `process_poll()` pipeline
- Updates `last_seen_at`, increments `total_reports` (or `failed_reports`)
- Returns `200` with current schedule

### Schedule Assignment

Target: one AVL fetch every ~6 seconds (matching current poll interval).

When N agents are active:
- Each agent's interval = `6 * N` seconds
- Each agent's offset = `6 * agent_index` seconds
- Agent index assigned by sorted order of `agent_id`

Recalculated whenever agent count changes. New schedule delivered in the
response to `/agents/checkin` or `/agents/report`.

Example with 3 agents:
- Agent A: fetch every 18s, offset 0s
- Agent B: fetch every 18s, offset 6s
- Agent C: fetch every 18s, offset 12s

### Fallback

If no agent has reported successfully in the last 30 seconds, the coordinator
falls back to direct fetching (current behavior). The system degrades
gracefully — agents are an enhancement, not a requirement.

### Captcha / Failure Handling

When an agent reports a failed fetch (captcha, timeout, non-JSON):
- Server marks that agent's IP as on cooldown
- Other agents absorb the load temporarily
- After a cooldown period, the agent resumes normal schedule

## Admin Panel

### Authentication

- `ADMIN_PASSWORD` env var
- `POST /admin/login` — validates password, sets HTTP-only cookie with
  `HMAC-SHA256(password, server_secret)` where server secret is derived
  from the admin password + a salt
- All `/admin/*` API endpoints check the cookie
- Separate from agent auth (agents use ECDSA signatures)

### Page

Served at `/admin` as plain HTML/CSS/JS (no framework, consistent with
the rest of the frontend). Static files in `src/where_the_plow/static/admin/`.

### Features

- **Agent list** — name, ID, status (online/offline based on `last_seen_at`),
  last seen, total reports, failed reports
- **Create agent** — enter a name, server generates ECDSA P-256 keypair,
  displays private key once (copyable text + download), stores public key
  only. Private key is never stored server-side.
- **Revoke agent** — disables an agent so its reports are rejected
- **Live status** — which agents are active, successful/failed reports in
  last hour, whether system is in fallback mode

### Admin API Endpoints

- `GET /admin/agents` — list all agents with status
- `POST /admin/agents/create` — generate keypair, store public key, return
  private key
- `POST /admin/agents/{id}/revoke` — set `enabled = FALSE`
- `GET /admin/status` — overall system health (active agents, fallback mode,
  recent report counts)

## Data Flow

```
Friend's machine                    Plow server
────────────────                    ───────────
plow-agent starts
  -> POST /agents/checkin (signed)
  <- schedule: {interval: 18s, offset: 6s}

  loop:
    wait (interval + jitter)
    GET map.stjohns.ca/portal/...
    <- raw JSON response
    -> POST /agents/report (signed)
    <- 200 OK + updated schedule
                                    verify ECDSA signature
                                    check timestamp window
                                    validate JSON (reject captcha)
                                    parse_avl_response()
                                    upsert vehicles + insert positions
                                    rebuild realtime snapshot
```

**Failure cases:**
- Agent gets captcha -> reports failure, server skips that IP, others
  pick up slack
- Agent goes offline -> server recalculates schedules for remaining
  agents on next report
- All agents offline -> server falls back to direct fetching
- Invalid signature -> 401, logged
- Replay attempt -> 401 (timestamp outside +/-30s window)

## What Doesn't Change

The rest of the app is untouched:
- Frontend (`index.html`, `app.js`, `style.css`)
- Existing API endpoints (`/vehicles`, `/coverage`, `/stats`, etc.)
- DuckDB schema for positions/vehicles
- Realtime snapshot pipeline
- AATracking sources (Mt. Pearl, Provincial) — only AVL uses agents
