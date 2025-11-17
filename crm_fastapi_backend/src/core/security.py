from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from dataclasses import dataclass
from typing import Optional

# Tuning parameters for password hashing
PBKDF2_ITERATIONS = 200_000
SALT_BYTES = 16

# Token hashing algorithm (sufficient for random opaque tokens)
TOKEN_HASH_ALGO = "sha256"


@dataclass
class PasswordHash:
    """Represents a hashed password with its parameters."""
    algo: str
    iterations: int
    salt_b64: str
    hash_hex: str


def _pbkdf2_hash(password: str, salt: bytes, iterations: int = PBKDF2_ITERATIONS) -> str:
    """Derive a PBKDF2-HMAC-SHA256 hash as hex string."""
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return dk.hex()


# PUBLIC_INTERFACE
def hash_password(password: str) -> PasswordHash:
    """Generate a secure PBKDF2 password hash with random salt."""
    salt = secrets.token_bytes(SALT_BYTES)
    hash_hex = _pbkdf2_hash(password, salt)
    return PasswordHash(
        algo="pbkdf2_sha256",
        iterations=PBKDF2_ITERATIONS,
        salt_b64=base64.b64encode(salt).decode(),
        hash_hex=hash_hex,
    )


# PUBLIC_INTERFACE
def verify_password(password: str, ph: PasswordHash) -> bool:
    """Verify a password against stored PasswordHash."""
    try:
        salt = base64.b64decode(ph.salt_b64.encode())
    except Exception:
        return False
    computed = _pbkdf2_hash(password, salt, ph.iterations)
    return hmac.compare_digest(computed, ph.hash_hex)


# PUBLIC_INTERFACE
def generate_token(nbytes: int = 32) -> str:
    """Generate a cryptographically secure opaque token."""
    return secrets.token_urlsafe(nbytes)


# PUBLIC_INTERFACE
def hash_token(token: str) -> str:
    """Return a SHA-256 hex digest fingerprint of a bearer token for DB storage.

    Notes:
        - Tokens are high-entropy, randomly generated values; hashing with
          SHA-256 is sufficient to protect at-rest token values.
        - Use with constant-time comparison when verifying.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# PUBLIC_INTERFACE
def parse_bearer_token(authorization: Optional[str]) -> Optional[str]:
    """Parse 'Authorization: Bearer <token>' header and return the token or None."""
    if not authorization:
        return None
    parts = authorization.split()
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1]
    return None
