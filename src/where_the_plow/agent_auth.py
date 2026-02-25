# src/where_the_plow/agent_auth.py
"""ECDSA P-256 key generation and signature verification for plow agents."""

import base64
import hashlib

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, utils


def generate_keypair() -> tuple[str, str]:
    """Generate an ECDSA P-256 keypair.

    Returns (private_pem, public_pem) where private uses TraditionalOpenSSL
    (EC PRIVATE KEY) format and public uses SubjectPublicKeyInfo (PUBLIC KEY).
    """
    private_key = ec.generate_private_key(ec.SECP256R1())

    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")

    public_pem = (
        private_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("utf-8")
    )

    return private_pem, public_pem


def agent_id_from_public_key(public_pem: str) -> str:
    """Derive a 16-char hex agent ID from SHA-256 of the DER-encoded public key."""
    public_key = serialization.load_pem_public_key(public_pem.encode("utf-8"))
    der_bytes = public_key.public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    digest = hashlib.sha256(der_bytes).hexdigest()
    return digest[:16]


def _compute_digest(body: bytes, timestamp: str) -> bytes:
    """Compute SHA-256(body || timestamp_bytes)."""
    return hashlib.sha256(body + timestamp.encode("utf-8")).digest()


def sign_payload(private_pem: str, body: bytes, timestamp: str) -> str:
    """Sign SHA-256(body || timestamp_bytes) with ECDSA P-256.

    Uses Prehashed since we compute the digest ourselves, matching
    the Go agent's ecdsa.SignASN1 which produces ASN.1 DER signatures.

    Returns base64-encoded signature.
    """
    private_key = serialization.load_pem_private_key(
        private_pem.encode("utf-8"), password=None
    )
    digest = _compute_digest(body, timestamp)
    signature = private_key.sign(digest, ec.ECDSA(utils.Prehashed(hashes.SHA256())))
    return base64.b64encode(signature).decode("utf-8")


def verify_signature(
    public_pem: str, body: bytes, timestamp: str, signature_b64: str
) -> bool:
    """Verify an ECDSA signature against body + timestamp.

    Returns True if valid, False on any failure (bad signature, malformed
    input, wrong key, etc.).
    """
    try:
        public_key = serialization.load_pem_public_key(public_pem.encode("utf-8"))
        digest = _compute_digest(body, timestamp)
        signature = base64.b64decode(signature_b64)
        public_key.verify(signature, digest, ec.ECDSA(utils.Prehashed(hashes.SHA256())))
        return True
    except (InvalidSignature, Exception):
        return False
