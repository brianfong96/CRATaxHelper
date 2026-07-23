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
MAX_KEY_ID = 9_999_999_999
_SECRET_HEX_RE = re.compile(r"^[0-9a-f]{64}$")


def key_id_at(now: float | None = None) -> int:
    """Return the canonical three-day UTC key-period identifier."""
    value = time.time() if now is None else now
    return math.floor(value / AUTH_KEY_ROTATION_SECONDS)


def key_context(audience: str, key_id: int) -> str:
    """Return the exact audience and period key-derivation context."""
    if (
        not audience
        or isinstance(key_id, bool)
        or not isinstance(key_id, int)
        or not 0 <= key_id <= MAX_KEY_ID
    ):
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
) -> dict[int, bytes] | None:
    """Load a complete consecutive previous/current/next keyring."""
    entries = (previous, current, next_key)
    keys: dict[int, bytes] = {}
    key_ids: list[int] = []
    for raw_key_id, secret_hex in entries:
        candidate = str(raw_key_id or "")
        key = decode_signing_key(secret_hex)
        if (
            not candidate.isascii()
            or not candidate.isdigit()
            or (len(candidate) > 1 and candidate.startswith("0"))
            or len(candidate) > 10
        ):
            return None
        key_id = int(candidate)
        if key_id > MAX_KEY_ID or key is None or key_id in keys:
            return None
        key_ids.append(key_id)
        keys[key_id] = key
    if key_ids != [key_ids[1] - 1, key_ids[1], key_ids[1] + 1]:
        return None
    if require_current_period and key_ids[1] != key_id_at(now):
        return None
    return keys


def token_window_valid(
    claims: dict, *, now: float | None = None, expected_key_id: int | None = None
) -> bool:
    """Enforce six-hour sessions and bounded three-day key acceptance."""
    current = time.time() if now is None else now
    key_id = claims.get("kid")
    issued_at = claims.get("iat")
    expires_at = claims.get("exp")
    if (
        isinstance(key_id, bool)
        or not isinstance(key_id, int)
        or not 0 <= key_id <= MAX_KEY_ID
    ):
        return False
    if expected_key_id is not None and key_id != expected_key_id:
        return False
    if (
        isinstance(issued_at, bool)
        or not isinstance(issued_at, int)
        or isinstance(expires_at, bool)
        or not isinstance(expires_at, (int, float))
        or not math.isfinite(float(issued_at))
        or not math.isfinite(float(expires_at))
    ):
        return False

    period_start = key_id * AUTH_KEY_ROTATION_SECONDS
    period_end = period_start + AUTH_KEY_ROTATION_SECONDS
    return (
        expires_at > issued_at
        and expires_at - issued_at <= AUTH_TOKEN_MAX_AGE_SECONDS
        and expires_at > current
        and issued_at <= current + AUTH_CLOCK_SKEW_SECONDS
        and issued_at >= period_start - AUTH_CLOCK_SKEW_SECONDS
        and issued_at <= period_end + AUTH_CLOCK_SKEW_SECONDS
        and current >= period_start - AUTH_CLOCK_SKEW_SECONDS
        and current <= period_end + AUTH_CLOCK_SKEW_SECONDS
    )
