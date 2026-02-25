# tests/test_agent_auth.py
"""Tests for ECDSA key generation and signature verification."""

from where_the_plow.agent_auth import (
    agent_id_from_public_key,
    generate_keypair,
    sign_payload,
    verify_signature,
)


def test_generate_keypair():
    """Generated keypair has correct PEM headers."""
    private_pem, public_pem = generate_keypair()
    assert private_pem.startswith("-----BEGIN EC PRIVATE KEY-----")
    assert private_pem.strip().endswith("-----END EC PRIVATE KEY-----")
    assert public_pem.startswith("-----BEGIN PUBLIC KEY-----")
    assert public_pem.strip().endswith("-----END PUBLIC KEY-----")


def test_agent_id_deterministic():
    """Same public key always produces the same 16-char hex agent ID."""
    _, public_pem = generate_keypair()
    id1 = agent_id_from_public_key(public_pem)
    id2 = agent_id_from_public_key(public_pem)
    assert id1 == id2
    assert len(id1) == 16
    # Must be valid hex
    int(id1, 16)


def test_agent_id_differs_for_different_keys():
    """Different keys produce different agent IDs."""
    _, pub1 = generate_keypair()
    _, pub2 = generate_keypair()
    assert agent_id_from_public_key(pub1) != agent_id_from_public_key(pub2)


def test_sign_and_verify():
    """Round-trip: sign then verify succeeds."""
    private_pem, public_pem = generate_keypair()
    body = b'{"plows": [1, 2, 3]}'
    timestamp = "2026-02-25T12:00:00Z"

    signature = sign_payload(private_pem, body, timestamp)
    assert isinstance(signature, str)
    assert len(signature) > 0

    assert verify_signature(public_pem, body, timestamp, signature) is True


def test_verify_rejects_wrong_key():
    """Signature from one key is rejected by a different key."""
    priv1, _ = generate_keypair()
    _, pub2 = generate_keypair()
    body = b"some data"
    timestamp = "2026-02-25T12:00:00Z"

    signature = sign_payload(priv1, body, timestamp)
    assert verify_signature(pub2, body, timestamp, signature) is False


def test_verify_rejects_tampered_body():
    """Signature is rejected when the body has been tampered with."""
    private_pem, public_pem = generate_keypair()
    body = b"original body"
    timestamp = "2026-02-25T12:00:00Z"

    signature = sign_payload(private_pem, body, timestamp)
    assert verify_signature(public_pem, b"tampered body", timestamp, signature) is False


def test_verify_rejects_wrong_timestamp():
    """Signature is rejected when the timestamp differs."""
    private_pem, public_pem = generate_keypair()
    body = b"some data"
    timestamp = "2026-02-25T12:00:00Z"

    signature = sign_payload(private_pem, body, timestamp)
    assert (
        verify_signature(public_pem, body, "2026-02-25T13:00:00Z", signature) is False
    )
