# plow-agent

A lightweight agent that helps [Where the Plow](https://plow.jackharrhy.dev) collect snowplow GPS data from the City of St. John's.

## Why?

The city publishes real-time plow locations on their [AVL map](https://map.stjohns.ca/avl/), but their firewall blocks automated requests from server IPs. By running this agent on your own machine or home server, you contribute your residential IP to a pool of volunteers that fetch the data on behalf of the tracking service. The more people running the agent, the more resilient the data collection becomes.

## How it works

1. On first run, the agent generates a cryptographic keypair and registers itself with the plow server.
2. You wait for the server operator to approve your agent (this is manual -- only trusted volunteers are approved).
3. Once approved, the agent periodically fetches plow data from the city's public map and reports it to the plow server, signed with its key.
4. The server coordinates all active agents so they take turns fetching, spreading the load across IPs.

Your credentials are stored locally and reused on subsequent runs. The agent uses minimal resources and runs quietly in the background.

## Quick start (recommended)

Download the latest release for your platform, then just run it:

```
./plow-agent
```

This launches an interactive setup wizard that:
1. Asks for the server URL (defaults to `https://plow.jackharrhy.dev`)
2. Prompts for a name to identify your agent (e.g. "alice-laptop")
3. Generates your cryptographic keypair
4. Registers with the server
5. Installs itself as a **system service** (systemd on Linux, launchd on macOS, Windows service)
6. Starts the service automatically

After setup, the agent runs in the background and survives reboots. You don't need to keep a terminal open.

**Note:** Installing a system service usually requires administrator/root privileges. On Linux, run with `sudo`. On macOS, you may get a permissions prompt. On Windows, run as Administrator.

## Running interactively

If you prefer not to install a service (or for Docker/development use):

```
./plow-agent --run --server https://plow.jackharrhy.dev
```

This runs the agent in the foreground. Press Ctrl+C to stop.

## Managing the service

Once installed, you can control the service with:

```
plow-agent --service status      # Check if running
plow-agent --service stop        # Stop the service
plow-agent --service start       # Start the service
plow-agent --service restart     # Restart the service
plow-agent --service uninstall   # Remove the service
```

### Viewing logs

- **Linux (systemd):** `journalctl -u plow-agent -f`
- **macOS (launchd):** `log show --predicate 'process == "plow-agent"' --last 1h`
- **Windows:** Event Viewer > Application logs

## Docker

```
docker run -d \
  --name plow-agent \
  -e PLOW_SERVER=https://plow.jackharrhy.dev \
  -e PLOW_NAME=your-name-here \
  -v plow-agent-data:/data \
  ghcr.io/jackharrhy/plow-agent:latest
```

The volume keeps your keypair across container restarts. Set `PLOW_NAME` to something that identifies you -- the server operator sees this when approving agents.

To build the image yourself:

```
docker build -t plow-agent agent/
```

## Kubernetes

A ready-made manifest is included at [`k8s.yaml`](k8s.yaml). Edit `PLOW_NAME` to your name, then:

```
kubectl apply -f agent/k8s.yaml
```

This creates a small PVC for key persistence and a Deployment running the agent.

## Configuration

| Flag / Env Var | Required | Description |
|---|---|---|
| `--server` / `PLOW_SERVER` | Yes (for `--run`) | Plow server URL |
| `--run` | No | Run in foreground instead of installing as service |
| `--service <action>` | No | Control installed service: install, uninstall, start, stop, restart, status |
| `PLOW_NAME` | Docker/K8s only | Agent name (binary prompts interactively) |
| `PLOW_DATA_DIR` | No | Override config directory (default: `~/.config/plow-agent/`, or `/data` when set) |

## What gets stored locally

The agent saves two files in its config directory:

- `key.pem` -- your ECDSA private key (never sent to the server, only used to sign requests)
- `name` -- the name you chose for this agent

On a binary install these live in `~/.config/plow-agent/`. In Docker/K8s they live in the `/data` volume.

## Checking your status

The agent logs its current status on startup and during operation:

```
2026/02/25 14:30:00 Agent ID: a1b2c3d4e5f67890
2026/02/25 14:30:00 Server: https://plow.jackharrhy.dev
2026/02/25 14:30:01 Registered! Waiting for approval...
2026/02/25 14:30:01 Status: pending — waiting for approval (checking every 30s)
```

Once approved:

```
2026/02/25 14:35:01 Approved! Fetching every 18s (offset 6s)
```
