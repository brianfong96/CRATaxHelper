"""
Unit tests for app.crypto — field-level encryption for form data at rest.
"""

import json
import os

import pytest
from cryptography.fernet import Fernet


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_key() -> str:
    return Fernet.generate_key().decode()


def _reload_crypto(monkeypatch, key: str = ""):
    """Reset crypto module state and patch settings with a given key."""
    import app.crypto as mod
    import app.config as config_mod
    # Patch the already-instantiated Settings singleton directly
    monkeypatch.setattr(config_mod.settings, "FIELD_ENCRYPTION_KEY", key)
    # Reset module-level cache so _get_fernet() re-initialises
    mod._fernet = None
    mod._init_done = False
    return mod


# ── encrypt_blob / decrypt_blob round-trip ─────────────────────────────────────

class TestEncryptDecryptRoundTrip:
    def test_basic_json_roundtrip(self, monkeypatch):
        key = _make_key()
        mod = _reload_crypto(monkeypatch, key)
        payload = json.dumps({"line_10100": 75000.5, "name": "Jane"})
        encrypted = mod.encrypt_blob(payload)
        assert encrypted.startswith("enc:v1:")
        assert encrypted != payload
        decrypted = mod.decrypt_blob(encrypted)
        assert json.loads(decrypted) == {"line_10100": 75000.5, "name": "Jane"}

    def test_empty_dict_roundtrip(self, monkeypatch):
        key = _make_key()
        mod = _reload_crypto(monkeypatch, key)
        payload = json.dumps({})
        assert json.loads(mod.decrypt_blob(mod.encrypt_blob(payload))) == {}

    def test_large_payload_roundtrip(self, monkeypatch):
        key = _make_key()
        mod = _reload_crypto(monkeypatch, key)
        big = {f"field_{i}": float(i) * 1.23 for i in range(200)}
        payload = json.dumps(big)
        assert json.loads(mod.decrypt_blob(mod.encrypt_blob(payload))) == big

    def test_encrypted_blob_is_different_each_call(self, monkeypatch):
        """Fernet uses a random IV — two encryptions of the same data differ."""
        key = _make_key()
        mod = _reload_crypto(monkeypatch, key)
        payload = json.dumps({"x": 1})
        assert mod.encrypt_blob(payload) != mod.encrypt_blob(payload)

    def test_decrypt_wrong_key_raises(self, monkeypatch):
        key1 = _make_key()
        key2 = _make_key()
        mod = _reload_crypto(monkeypatch, key1)
        encrypted = mod.encrypt_blob(json.dumps({"a": 1}))
        mod2 = _reload_crypto(monkeypatch, key2)
        with pytest.raises(ValueError, match="Decryption failed"):
            mod2.decrypt_blob(encrypted)


# ── Plaintext fallback (no key configured) ─────────────────────────────────────

class TestNoKeyFallback:
    def test_encrypt_without_key_returns_plaintext(self, monkeypatch):
        mod = _reload_crypto(monkeypatch, "")
        payload = json.dumps({"income": 50000})
        result = mod.encrypt_blob(payload)
        assert result == payload  # no encryption, returned as-is
        assert not result.startswith("enc:v1:")

    def test_decrypt_plaintext_passthrough(self, monkeypatch):
        mod = _reload_crypto(monkeypatch, "")
        payload = json.dumps({"income": 50000})
        assert mod.decrypt_blob(payload) == payload


# ── Backward-compatibility with legacy plaintext rows ─────────────────────────

class TestBackwardCompat:
    def test_decrypt_legacy_plain_json_with_key_set(self, monkeypatch):
        """Existing unencrypted rows should still be readable after key is added."""
        key = _make_key()
        mod = _reload_crypto(monkeypatch, key)
        legacy = json.dumps({"line_26000": 85000.0})
        result = mod.decrypt_blob(legacy)  # no enc:v1: prefix
        assert result == legacy

    def test_decrypt_encrypted_no_key_raises(self, monkeypatch):
        key = _make_key()
        mod = _reload_crypto(monkeypatch, key)
        encrypted = mod.encrypt_blob(json.dumps({"x": 99}))
        mod2 = _reload_crypto(monkeypatch, "")
        with pytest.raises(ValueError, match="FIELD_ENCRYPTION_KEY"):
            mod2.decrypt_blob(encrypted)

    def test_corrupted_token_raises(self, monkeypatch):
        key = _make_key()
        mod = _reload_crypto(monkeypatch, key)
        bad_blob = "enc:v1:notavalidtoken!!"
        with pytest.raises(ValueError):
            mod.decrypt_blob(bad_blob)
