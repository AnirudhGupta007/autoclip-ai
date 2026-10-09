"""Password hashing (argon2id) and opaque session tokens."""
from __future__ import annotations
import hashlib
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

_hasher = PasswordHasher()  # argon2id with the library's current defaults

# Stored for accounts that must never log in with a password (demo user,
# placeholder legacy owner). Not a valid argon2 hash, so verify() is False.
UNUSABLE_PASSWORD = "!"

# Verifying against a dummy hash for unknown emails keeps the response time
# of "no such user" close to "wrong password" (no account enumeration).
_DUMMY_HASH = _hasher.hash("not-a-real-password-just-timing")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(stored_hash: str | None, password: str) -> bool:
    if not stored_hash or stored_hash == UNUSABLE_PASSWORD:
        try:
            _hasher.verify(_DUMMY_HASH, password)
        except Exception:
            pass
        return False
    try:
        return _hasher.verify(stored_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def has_usable_password(stored_hash: str | None) -> bool:
    return bool(stored_hash) and stored_hash != UNUSABLE_PASSWORD


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
