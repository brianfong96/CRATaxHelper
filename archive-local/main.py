"""
Local Archive sidecar — SQLite-backed storage compatible with the Aether Archive API.

Implements exactly the endpoints that userdata.py calls, so the CRA Tax Helper
can store and retrieve encrypted form data locally without any cloud dependency.

Single-user local mode:
  - No real authentication is enforced (all requests are trusted)
  - RLS is disabled (only one user exists locally)
  - Data is stored in a SQLite file at DB_PATH (/data/archive.db by default)
  - Compatible with the exact API contract expected by userdata.py

Endpoints implemented:
  GET  /health
  GET  /api/v1/projects
  POST /api/v1/projects
  GET  /api/v1/{project}/tables
  POST /api/v1/{project}/tables
  POST /api/v1/projects/{project}/rls
  POST /api/v1/projects/{project}/roles
  GET  /api/v1/{project}/{table}
  POST /api/v1/{project}/{table}
  PATCH /api/v1/{project}/{table}/{row_id}
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from contextlib import contextmanager
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

DB_PATH = os.environ.get("DB_PATH", "/data/archive.db")


@asynccontextmanager
async def _lifespan(app):
    _init_db(DB_PATH)
    yield


app = FastAPI(title="Local Archive", version="1.0.0", lifespan=_lifespan)

def _init_db(path: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS projects (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                name         TEXT UNIQUE NOT NULL,
                display_name TEXT DEFAULT '',
                description  TEXT DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS tables_meta (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                project_name TEXT NOT NULL,
                table_name   TEXT NOT NULL,
                columns_json TEXT DEFAULT '[]',
                UNIQUE(project_name, table_name)
            );
            CREATE TABLE IF NOT EXISTS rows (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                project_name TEXT NOT NULL,
                table_name   TEXT NOT NULL,
                owner_email  TEXT DEFAULT '',
                data_json    TEXT NOT NULL DEFAULT '{}',
                created_at   TEXT DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_rows_pt
                ON rows(project_name, table_name);
        """)


@contextmanager
def _db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    """Deserialise a DB row: merge the stored data_json back into a flat dict."""
    d = dict(row)
    try:
        data = json.loads(d.pop("data_json", "{}") or "{}")
    except Exception:
        data = {}
    d.update(data)
    return d


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "service": "local-archive"}


# ── Projects ──────────────────────────────────────────────────────────────────

@app.get("/api/v1/projects")
def list_projects():
    with _db() as conn:
        rows = conn.execute("SELECT name, display_name, description FROM projects").fetchall()
    return [dict(r) for r in rows]


@app.post("/api/v1/projects", status_code=201)
async def create_project(request: Request):
    body = await request.json()
    name = body.get("name", "")
    if not name:
        raise HTTPException(400, "name is required")
    with _db() as conn:
        try:
            conn.execute(
                "INSERT INTO projects (name, display_name, description) VALUES (?,?,?)",
                (name, body.get("display_name", ""), body.get("description", "")),
            )
        except sqlite3.IntegrityError:
            pass  # Already exists — idempotent
    return {"name": name, "created": True}


# ── Tables ────────────────────────────────────────────────────────────────────

@app.get("/api/v1/{project}/tables")
def list_tables(project: str):
    with _db() as conn:
        rows = conn.execute(
            "SELECT table_name AS name, columns_json FROM tables_meta WHERE project_name=?",
            (project,),
        ).fetchall()
    return {"tables": [dict(r) for r in rows]}


@app.post("/api/v1/{project}/tables", status_code=201)
async def create_table(project: str, request: Request):
    body = await request.json()
    table_name = body.get("name", "")
    if not table_name:
        raise HTTPException(400, "name is required")
    cols_json = json.dumps(body.get("columns", []))
    with _db() as conn:
        try:
            conn.execute(
                "INSERT INTO tables_meta (project_name, table_name, columns_json) VALUES (?,?,?)",
                (project, table_name, cols_json),
            )
        except sqlite3.IntegrityError:
            pass  # Already exists — idempotent
    return {"name": table_name, "created": True}


# ── RLS / Roles (no-ops in local single-user mode) ────────────────────────────

@app.post("/api/v1/projects/{project}/rls", status_code=200)
async def set_rls(project: str, request: Request):
    """RLS is a no-op in local single-user mode."""
    return {"ok": True, "local_mode": "rls_disabled"}


@app.post("/api/v1/projects/{project}/roles", status_code=200)
async def grant_role(project: str, request: Request):
    """Role management is a no-op in local single-user mode."""
    return {"ok": True, "local_mode": "roles_disabled"}


# ── Rows CRUD ─────────────────────────────────────────────────────────────────

@app.get("/api/v1/{project}/{table}")
def query_rows(
    project: str,
    table: str,
    limit: int = 50,
    order_by: str = "id",
    order: str = "asc",
):
    safe_order = "DESC" if order.lower() == "desc" else "ASC"
    safe_col = "id" if order_by not in ("id", "created_at") else order_by

    with _db() as conn:
        rows = conn.execute(
            f"SELECT id, owner_email, data_json, created_at "   # noqa: S608
            f"FROM rows WHERE project_name=? AND table_name=? "
            f"ORDER BY {safe_col} {safe_order} LIMIT ?",
            (project, table, limit),
        ).fetchall()

    return {"rows": [_row_to_dict(r) for r in rows]}


@app.post("/api/v1/{project}/{table}", status_code=201)
async def insert_row(project: str, table: str, request: Request):
    body = await request.json()
    # userdata.py sends {"data": {...payload...}}
    payload: dict = body.get("data", body)
    owner_email = payload.get("owner_email", "local@cra-helper.local")
    created_at = payload.get("saved_at", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    with _db() as conn:
        cur = conn.execute(
            "INSERT INTO rows (project_name, table_name, owner_email, data_json, created_at) "
            "VALUES (?,?,?,?,?)",
            (project, table, owner_email, json.dumps(payload), created_at),
        )
        row_id = cur.lastrowid
    return {"id": row_id, "inserted": True}


@app.patch("/api/v1/{project}/{table}/{row_id}", status_code=200)
async def update_row(project: str, table: str, row_id: int, request: Request):
    body = await request.json()
    payload: dict = body.get("data", body)
    owner_email = payload.get("owner_email", "local@cra-helper.local")
    saved_at = payload.get("saved_at", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    with _db() as conn:
        conn.execute(
            "UPDATE rows SET owner_email=?, data_json=?, created_at=? "
            "WHERE id=? AND project_name=? AND table_name=?",
            (owner_email, json.dumps(payload), saved_at, row_id, project, table),
        )
    return {"id": row_id, "updated": True}
