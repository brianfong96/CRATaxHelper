"""
Tests for the local Archive sidecar service (archive-local/main.py).

These are standalone tests — they start the Archive service in-process
using httpx's ASGI transport, so no Docker or real server is needed.

Coverage:
  - All CRUD endpoints (projects, tables, rows)
  - Row insert + update + query round-trip
  - RLS / roles no-ops return 200
  - Health check
  - Data stored in a temp SQLite DB (cleaned up after each test)
"""

import importlib.util as _ilu
import json
import os
import sys
import tempfile
from pathlib import Path

import pytest
from starlette.testclient import TestClient

# ── Make archive-local importable ────────────────────────────────────────────
_ARCHIVE_DIR = Path(__file__).parent.parent / "archive-local"

_spec = _ilu.spec_from_file_location("archive_local_main", _ARCHIVE_DIR / "main.py")
_mod = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
sys.modules["archive_local_main"] = _mod
import archive_local_main as alm  # noqa: E402


@pytest.fixture()
def archive_app(tmp_path):
    """Return a TestClient wired to the Archive ASGI app with a temp database."""
    db_file = str(tmp_path / "test.db")
    original_db = alm.DB_PATH
    alm.DB_PATH = db_file
    alm._init_db(db_file)
    # Reset Fernet cache between tests
    with TestClient(alm.app, raise_server_exceptions=True) as client:
        yield client
    alm.DB_PATH = original_db


# ── Health ────────────────────────────────────────────────────────────────────

def test_health(archive_app):
    r = archive_app.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


# ── Projects ──────────────────────────────────────────────────────────────────

def test_list_projects_empty(archive_app):
    r = archive_app.get("/api/v1/projects")
    assert r.status_code == 200
    assert r.json() == []


def test_create_project(archive_app):
    r = archive_app.post(
        "/api/v1/projects",
        json={"name": "cra-taxhelper", "display_name": "CRA Tax Helper"},
    )
    assert r.status_code == 201
    assert r.json()["name"] == "cra-taxhelper"


def test_create_project_idempotent(archive_app):
    """Creating the same project twice should not error."""
    for _ in range(2):
        r = archive_app.post("/api/v1/projects", json={"name": "cra-taxhelper"})
        assert r.status_code == 201

    r = archive_app.get("/api/v1/projects")
    names = [p["name"] for p in r.json()]
    assert names.count("cra-taxhelper") == 1


def test_create_project_missing_name(archive_app):
    r = archive_app.post("/api/v1/projects", json={})
    assert r.status_code == 400


# ── Tables ────────────────────────────────────────────────────────────────────

def test_list_tables_empty(archive_app):
    r = archive_app.get("/api/v1/cra-taxhelper/tables")
    assert r.status_code == 200
    assert r.json() == {"tables": []}


def test_create_table(archive_app):
    r = archive_app.post(
        "/api/v1/cra-taxhelper/tables",
        json={
            "name": "form_saves",
            "columns": [
                {"name": "owner_email", "type": "text"},
                {"name": "form_name",   "type": "text"},
                {"name": "form_data",   "type": "text"},
                {"name": "saved_at",    "type": "text"},
            ],
        },
    )
    assert r.status_code == 201
    assert r.json()["name"] == "form_saves"


def test_create_table_idempotent(archive_app):
    for _ in range(2):
        r = archive_app.post(
            "/api/v1/cra-taxhelper/tables",
            json={"name": "form_saves", "columns": []},
        )
        assert r.status_code == 201

    r = archive_app.get("/api/v1/cra-taxhelper/tables")
    names = [t["name"] for t in r.json()["tables"]]
    assert names.count("form_saves") == 1


# ── RLS / Roles (no-ops) ──────────────────────────────────────────────────────

def test_rls_noop(archive_app):
    r = archive_app.post(
        "/api/v1/projects/cra-taxhelper/rls",
        json={"table_name": "form_saves", "user_column": "owner_email", "visibility": "private"},
    )
    assert r.status_code == 200
    assert r.json()["local_mode"] == "rls_disabled"


def test_roles_noop(archive_app):
    r = archive_app.post(
        "/api/v1/projects/cra-taxhelper/roles",
        json={"email": "test@example.com", "role": "rls-editor"},
    )
    assert r.status_code == 200
    assert r.json()["local_mode"] == "roles_disabled"


# ── Rows CRUD ─────────────────────────────────────────────────────────────────

def test_query_rows_empty(archive_app):
    r = archive_app.get("/api/v1/cra-taxhelper/form_saves")
    assert r.status_code == 200
    assert r.json() == {"rows": []}


def test_insert_and_query_row(archive_app):
    payload = {
        "data": {
            "owner_email": "local@cra-helper.local",
            "form_name": "t1",
            "form_data": "enc:v1:some_encrypted_blob",
            "saved_at": "2025-04-27T10:00:00Z",
        }
    }
    r = archive_app.post("/api/v1/cra-taxhelper/form_saves", json=payload)
    assert r.status_code == 201
    assert "id" in r.json()

    rows = archive_app.get("/api/v1/cra-taxhelper/form_saves").json()["rows"]
    assert len(rows) == 1
    assert rows[0]["form_name"] == "t1"
    assert rows[0]["form_data"] == "enc:v1:some_encrypted_blob"


def test_insert_flat_payload(archive_app):
    """userdata.py sometimes sends payload directly without a 'data' wrapper."""
    payload = {
        "owner_email": "local@cra-helper.local",
        "form_name": "bc428",
        "form_data": "enc:v1:another_blob",
        "saved_at": "2025-04-27T11:00:00Z",
    }
    r = archive_app.post("/api/v1/cra-taxhelper/form_saves", json=payload)
    assert r.status_code == 201


def test_update_row(archive_app):
    # Insert
    r = archive_app.post(
        "/api/v1/cra-taxhelper/form_saves",
        json={"data": {"owner_email": "local@cra-helper.local", "form_name": "t1",
                        "form_data": "old", "saved_at": "2025-01-01T00:00:00Z"}},
    )
    row_id = r.json()["id"]

    # Update
    r = archive_app.patch(
        f"/api/v1/cra-taxhelper/form_saves/{row_id}",
        json={"data": {"owner_email": "local@cra-helper.local", "form_name": "t1",
                        "form_data": "enc:v1:updated", "saved_at": "2025-04-27T12:00:00Z"}},
    )
    assert r.status_code == 200

    rows = archive_app.get("/api/v1/cra-taxhelper/form_saves").json()["rows"]
    assert rows[0]["form_data"] == "enc:v1:updated"


def test_multiple_forms_stored_separately(archive_app):
    for form in ("t1", "bc428", "schedule3"):
        archive_app.post(
            "/api/v1/cra-taxhelper/form_saves",
            json={"data": {"owner_email": "local@cra-helper.local", "form_name": form,
                            "form_data": f"enc:v1:{form}_data", "saved_at": "2025-04-27T00:00:00Z"}},
        )

    rows = archive_app.get("/api/v1/cra-taxhelper/form_saves").json()["rows"]
    assert len(rows) == 3
    form_names = {r["form_name"] for r in rows}
    assert form_names == {"t1", "bc428", "schedule3"}


def test_query_order_desc(archive_app):
    for i in range(3):
        archive_app.post(
            "/api/v1/cra-taxhelper/form_saves",
            json={"data": {"owner_email": "u@test.com", "form_name": f"form{i}",
                            "form_data": f"data{i}", "saved_at": "2025-01-01T00:00:00Z"}},
        )
    rows = archive_app.get(
        "/api/v1/cra-taxhelper/form_saves",
        params={"order_by": "id", "order": "desc"},
    ).json()["rows"]
    ids = [r["id"] for r in rows]
    assert ids == sorted(ids, reverse=True)


def test_query_limit(archive_app):
    for i in range(5):
        archive_app.post(
            "/api/v1/cra-taxhelper/form_saves",
            json={"data": {"owner_email": "u@test.com", "form_name": f"f{i}",
                            "form_data": "x", "saved_at": "2025-01-01T00:00:00Z"}},
        )
    rows = archive_app.get(
        "/api/v1/cra-taxhelper/form_saves", params={"limit": 2}
    ).json()["rows"]
    assert len(rows) == 2


# ── Full userdata.py round-trip simulation ────────────────────────────────────

def test_userdata_full_upsert_flow(archive_app):
    """Simulate exactly what userdata.py does: check for existing row, insert or patch."""
    project = "cra-taxhelper"
    table = "form_saves"
    email = "local@cra-helper.local"
    form = "t1"

    # Step 1: query (userdata.py checks for existing row)
    r = archive_app.get(f"/api/v1/{project}/{table}", params={"limit": 10, "order_by": "id"})
    existing_id = None
    for row in r.json().get("rows", []):
        if row.get("form_name") == form:
            existing_id = row.get("id")
            break
    assert existing_id is None

    # Step 2: insert (no existing row)
    payload = {
        "data": {
            "owner_email": email,
            "form_name": form,
            "form_data": "enc:v1:firstsave",
            "saved_at": "2025-04-27T10:00:00Z",
        }
    }
    r = archive_app.post(f"/api/v1/{project}/{table}", json=payload)
    assert r.status_code == 201
    new_id = r.json()["id"]

    # Step 3: query again — find existing row
    r = archive_app.get(f"/api/v1/{project}/{table}", params={"limit": 10, "order_by": "id"})
    existing_id = None
    for row in r.json().get("rows", []):
        if row.get("form_name") == form:
            existing_id = row.get("id")
            break
    assert existing_id == new_id

    # Step 4: patch (existing row found)
    r = archive_app.patch(
        f"/api/v1/{project}/{table}/{existing_id}",
        json={"data": {"owner_email": email, "form_name": form,
                        "form_data": "enc:v1:updated", "saved_at": "2025-04-27T11:00:00Z"}},
    )
    assert r.status_code == 200

    # Step 5: verify final state
    rows = archive_app.get(f"/api/v1/{project}/{table}").json()["rows"]
    assert len(rows) == 1  # no duplicates
    assert rows[0]["form_data"] == "enc:v1:updated"
