"""Rotating audience-key and bounded token-lifetime helpers."""

from __future__ import annotations

import math
import re
import time

AUTH_VERSION = 2
AUTH_KEY_ROTATION_SECONDS = 259_200
AUTH_TOKEN_MAX_AGE_SECONDS = 21_600
AUTH_CLOCK_SKEW_SECONDS = 60
SIGNING_KEY_BYTES = 32
_KID_RE = re.compile(r"^(0|[1-9][0-9]{0,9})$")
_SECRET_HEX_RE = re.compile(r"^[0-9a-f]{64}$")


def key_id_at(now: float | None = None) -> str:
    """Return the canonical three-day UTC key-period identifier."""
    value = time.time() if now is None else now
    return str(math.floor(value / AUTH_KEY_ROTATION_SECONDS))


def key_context(audience: str, key_id: str) -> str:
    """Return the exact audience and period key-derivation context."""
    if not audience or not _KID_RE.fullmatch(key_id):
        raise ValueError("audience and canonical numeric key id are required")
    return f"aether-auth:v{AUTH_VERSION}:{audience}:{key_id}"


def decode_signing_key(secret_hex: str | None) -> bytes | None:
    """Decode one 32-byte key, failing closed on malformed input."""
    if not isinstance(secret_hex, str) or not _SECRET_HEX_RE.fullmatch(secret_hex):
        return None
    try:
        key = bytes.fromhex(secret_hex)
    except ValueError:
        return None
    return key if len(key) == SIGNING_KEY_BYTES else None


def load_required_keyring(
    previous: tuple[str, str | None],
    current: tuple[str, str | None],
    next_key: tuple[str, str | None],
    *,
    now: float | None = None,
    require_current_period: bool = False,
) -> dict[str, bytes] | None:
    """Load a complete consecutive previous/current/next keyring."""
    entries = (previous, current, next_key)
    keys: dict[str, bytes] = {}
    key_ids: list[str] = []
    for raw_key_id, secret_hex in entries:
        key_id = raw_key_id or ""
        key = decode_signing_key(secret_hex)
        if not _KID_RE.fullmatch(key_id) or key is None or key_id in keys:
            return None
        key_ids.append(key_id)
        keys[key_id] = key
    if [int(key_id) for key_id in key_ids] != [
        int(key_ids[1]) - 1,
        int(key_ids[1]),
        int(key_ids[1]) + 1,
    ]:
        return None
    if require_current_period and key_ids[1] != key_id_at(now):
        return None
    return keys


def token_window_valid(
    claims: dict, *, now: float | None = None, expected_key_id: str | None = None
) -> bool:
    """Enforce six-hour sessions and bounded three-day key acceptance."""
    current = time.time() if now is None else now
    key_id = claims.get("kid")
    issued_at = claims.get("iat")
    expires_at = claims.get("exp")
    if not isinstance(key_id, str) or not _KID_RE.fullmatch(key_id):
        return False
    if expected_key_id is not None and key_id != expected_key_id:
        return False
    if (
        isinstance(issued_at, bool)
        or not isinstance(issued_at, (int, float))
        or isinstance(expires_at, bool)
        or not isinstance(expires_at, (int, float))
        or not math.isfinite(float(issued_at))
        or not math.isfinite(float(expires_at))
    ):
        return False

    period_start = int(key_id) * AUTH_KEY_ROTATION_SECONDS
    period_end = period_start + AUTH_KEY_ROTATION_SECONDS
    return (
        expires_at > issued_at
        and expires_at - issued_at <= AUTH_TOKEN_MAX_AGE_SECONDS
        and expires_at > current
        and issued_at <= current + AUTH_CLOCK_SKEW_SECONDS
        and issued_at >= period_start - AUTH_CLOCK_SKEW_SECONDS
        and issued_at < period_end + AUTH_CLOCK_SKEW_SECONDS
        and current >= period_start - AUTH_CLOCK_SKEW_SECONDS
        and current <= period_end + AUTH_TOKEN_MAX_AGE_SECONDS + AUTH_CLOCK_SKEW_SECONDS
    )
