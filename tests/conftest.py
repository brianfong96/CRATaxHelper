"""Shared pytest configuration for the CRA Tax Helper suite.

The application fails closed: when ``AUTH_ENABLED`` is true it always enforces a
valid Aether session and denies access if no usable audience-scoped signing key
is configured. There is no "missing secret ⇒ run open" shortcut.

The functional tests (routes, calculator, customize, PDF, …) exercise app
behaviour rather than authentication, so they run in explicit local mode. This
autouse fixture sets ``AUTH_ENABLED=False`` by default — the same switch a local
or desktop deployment uses. Tests that specifically cover authentication (see
``test_security.py``) override this by setting ``AUTH_ENABLED=True`` and
configuring a signing key in their own fixtures.
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _default_local_mode(monkeypatch):
    import app.config as cfg
    monkeypatch.setattr(cfg.settings, "AUTH_ENABLED", False)
