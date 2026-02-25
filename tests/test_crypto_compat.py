"""Cross-language ECDSA compatibility test: Go signs, Python verifies."""

import json
import subprocess

import pytest

from where_the_plow.agent_auth import agent_id_from_public_key, verify_signature


@pytest.fixture(scope="module")
def go_signed_data():
    """Run the Go signtest helper and parse its output."""
    result = subprocess.run(
        ["go", "run", "./cmd/signtest"],
        capture_output=True,
        text=True,
        timeout=30,
        cwd="agent",
    )
    if result.returncode != 0:
        pytest.skip(f"Go signtest failed: {result.stderr}")
    return json.loads(result.stdout)


def test_go_signature_verifies_in_python(go_signed_data):
    """Verify that a Go-generated ECDSA signature passes Python verification."""
    data = go_signed_data
    assert verify_signature(
        data["public_key"],
        data["body"].encode(),
        data["timestamp"],
        data["signature"],
    )


def test_go_agent_id_matches_python(go_signed_data):
    """Verify that Go and Python derive the same agent ID from a public key."""
    data = go_signed_data
    python_id = agent_id_from_public_key(data["public_key"])
    assert python_id == data["agent_id"]
