"""
Field-level encryption for CRA Tax Helper form data.

Encrypts JSON payloads before storing in Archive and decrypts on retrieval,
so sensitive tax data (income, SIN-adjacent fields, etc.) is protected at rest.

Algorithm: Fernet (AES-128-CBC + HMAC-SHA256, authenticated).
Stored format: "enc:v1:<fernet_token>"

Backward compatibility: blobs that don't start with "enc:v1:" are assumed to be
legacy plaintext JSON and are parsed directly.  This allows a zero-downtime
rollout — existing rows continue to be readable after the key is configured.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("taxhelper.crypto")

_ENC_PREFIX = "enc:v1:"

# Module-level Fernet instance (initialised lazily from settings).
_fernet = None
_init_done = False


def _get_fernet():
    """Return a configured Fernet instance, or None if no key is set."""
    global _fernet, _init_done
    if _init_done:
        return _fernet
    _init_done = True

    try:
        from cryptography.fernet import Fernet, InvalidToken  # noqa: F401
        from app.config import settings

        raw_key = settings.FIELD_ENCRYPTION_KEY.strip()
        if not raw_key:
            logger.warning(
                "FIELD_ENCRYPTION_KEY not set — form data will be stored as plaintext. "
                "Set this in your .env for production."
            )
            return None

        _fernet = Fernet(raw_key.encode())
        logger.info("Field encryption initialised (Fernet/AES-128-CBC)")
    except Exception as exc:
        logger.error("Failed to initialise field encryption: %s", exc)

    return _fernet


def encrypt_blob(plain_json: str) -> str:
    """Encrypt a JSON string and return an 'enc:v1:<token>' blob.

    Falls back to plaintext if no encryption key is configured.
    """
    fernet = _get_fernet()
    if fernet is None:
        return plain_json

    try:
        token = fernet.encrypt(plain_json.encode()).decode()
        return f"{_ENC_PREFIX}{token}"
    except Exception as exc:
        logger.error("Encryption failed, storing plaintext: %s", exc)
        return plain_json


def decrypt_blob(blob: str) -> str:
    """Decrypt a blob produced by encrypt_blob(), returning the original JSON.

    If the blob does not start with 'enc:v1:' it is returned as-is (legacy
    plaintext rows).  Raises ValueError if the blob is encrypted but the key
    is missing or the token is corrupt.
    """
    if not blob.startswith(_ENC_PREFIX):
        return blob  # Legacy plaintext — pass through

    fernet = _get_fernet()
    if fernet is None:
        raise ValueError(
            "Cannot decrypt: FIELD_ENCRYPTION_KEY is not configured. "
            "Set FIELD_ENCRYPTION_KEY in your environment to read encrypted data."
        )

    try:
        from cryptography.fernet import InvalidToken
        token = blob[len(_ENC_PREFIX):].encode()
        return fernet.decrypt(token).decode()
    except InvalidToken as exc:
        raise ValueError("Decryption failed — wrong key or corrupted data") from exc
    except Exception as exc:
        raise ValueError(f"Decryption error: {exc}") from exc
