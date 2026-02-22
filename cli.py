"""Dev CLI for where-the-plow."""

import subprocess
import sys

COMMANDS = {
    "dev": "Run uvicorn in development mode with auto-reload",
    "start": "Run uvicorn in production mode",
}

APP = "where_the_plow.main:app"


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


def usage():
    print("Usage: uv run cli.py <command>\n")
    print("Commands:")
    for name, desc in COMMANDS.items():
        print(f"  {name:10s} {desc}")
    sys.exit(1)


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        usage()

    cmd = sys.argv[1]
    {"dev": dev, "start": start}[cmd]()


if __name__ == "__main__":
    main()
