"""SQLite storage for projects and render history."""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from . import config

DB = config.DATA / "app.db"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def conn():
    c = sqlite3.connect(DB, timeout=15)
    c.row_factory = sqlite3.Row
    return c


def init_db() -> None:
    with conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS projects (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            script TEXT NOT NULL,
            settings TEXT NOT NULL,
            owner TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS renders (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            status TEXT NOT NULL,
            stage TEXT,
            progress REAL DEFAULT 0,
            video_path TEXT,
            srt_path TEXT,
            poster_path TEXT,
            duration REAL,
            size INTEGER,
            error TEXT,
            settings TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_renders_project ON renders(project_id, created_at DESC);
        """)
        cols = [r["name"] for r in c.execute("PRAGMA table_info(projects)")]
        if "owner" not in cols:
            c.execute("ALTER TABLE projects ADD COLUMN owner TEXT NOT NULL DEFAULT ''")
    # Anything left "running" after a server restart cannot be resumed.
    with conn() as c:
        c.execute("UPDATE renders SET status='failed', error=?, updated_at=? "
                  "WHERE status IN ('running','queued')",
                  ("Сервер был перезапущен во время генерации. Запусти рендер заново.", _now()))


def list_projects(owner: str | None = None) -> list[dict]:
    with conn() as c:
        if owner is None:
            rows = c.execute("""
                SELECT p.*, (SELECT COUNT(*) FROM renders r WHERE r.project_id=p.id) AS renders
                FROM projects p ORDER BY p.updated_at DESC
            """).fetchall()
        else:
            rows = c.execute("""
                SELECT p.*, (SELECT COUNT(*) FROM renders r WHERE r.project_id=p.id) AS renders
                FROM projects p WHERE p.owner=? ORDER BY p.updated_at DESC
            """, (owner,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["settings"] = json.loads(d["settings"] or "{}")
        out.append(d)
    return out


def get_project(pid: str, owner: str | None = None) -> dict | None:
    with conn() as c:
        if owner is None:
            r = c.execute("SELECT * FROM projects WHERE id=?", (pid,)).fetchone()
        else:
            r = c.execute("SELECT * FROM projects WHERE id=? AND owner=?", (pid, owner)).fetchone()
    if not r:
        return None
    d = dict(r)
    d["settings"] = json.loads(d["settings"] or "{}")
    return d


def create_project(title: str, script: str, settings: dict, owner: str = "") -> dict:
    pid = uuid.uuid4().hex[:12]
    now = _now()
    with conn() as c:
        c.execute("INSERT INTO projects(id,title,script,settings,owner,created_at,updated_at) "
                  "VALUES(?,?,?,?,?,?,?)",
                  (pid, title, script, json.dumps(settings, ensure_ascii=False), owner, now, now))
    return get_project(pid)


def update_project(pid: str, title: str | None = None, script: str | None = None,
                   settings: dict | None = None, owner: str | None = None) -> dict | None:
    p = get_project(pid, owner)
    if not p:
        return None
    title = p["title"] if title is None else title
    script = p["script"] if script is None else script
    settings = p["settings"] if settings is None else settings
    with conn() as c:
        c.execute("UPDATE projects SET title=?, script=?, settings=?, updated_at=? WHERE id=?",
                  (title, script, json.dumps(settings, ensure_ascii=False), _now(), pid))
    return get_project(pid, owner)


def delete_project(pid: str, owner: str | None = None) -> None:
    if get_project(pid, owner) is None:
        return
    with conn() as c:
        c.execute("DELETE FROM renders WHERE project_id=?", (pid,))
        c.execute("DELETE FROM projects WHERE id=?", (pid,))
    import shutil

    shutil.rmtree(config.PROJECTS / pid, ignore_errors=True)


def create_render(pid: str, settings: dict) -> dict:
    rid = uuid.uuid4().hex[:12]
    now = _now()
    with conn() as c:
        c.execute("INSERT INTO renders(id,project_id,status,stage,progress,settings,created_at,updated_at) "
                  "VALUES(?,?,?,?,?,?,?,?)",
                  (rid, pid, "queued", "В очереди", 0,
                   json.dumps(settings, ensure_ascii=False), now, now))
    return get_render(rid)


def get_render(rid: str) -> dict | None:
    with conn() as c:
        r = c.execute("SELECT * FROM renders WHERE id=?", (rid,)).fetchone()
    if not r:
        return None
    d = dict(r)
    d["settings"] = json.loads(d["settings"] or "{}")
    return d


def update_render(rid: str, **fields) -> None:
    allowed = {"status", "stage", "progress", "video_path", "srt_path", "poster_path",
               "duration", "size", "error"}
    vals = {k: v for k, v in fields.items() if k in allowed}
    if not vals:
        return
    vals["updated_at"] = _now()
    cols = ", ".join(f"{k}=?" for k in vals)
    with conn() as c:
        c.execute(f"UPDATE renders SET {cols} WHERE id=?", (*vals.values(), rid))


def list_renders(pid: str) -> list[dict]:
    with conn() as c:
        rows = c.execute("SELECT * FROM renders WHERE project_id=? ORDER BY created_at DESC",
                         (pid,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["settings"] = json.loads(d["settings"] or "{}")
        out.append(d)
    return out


def delete_render(rid: str) -> dict | None:
    r = get_render(rid)
    if not r:
        return None
    with conn() as c:
        c.execute("DELETE FROM renders WHERE id=?", (rid,))
    import shutil

    shutil.rmtree(config.PROJECTS / r["project_id"] / "renders" / rid, ignore_errors=True)
    return r


def ensure_demo(owner: str = "") -> None:
    if list_projects(owner):
        return
    s = dict(config.DEFAULT_SETTINGS)
    create_project(config.DEFAULT_TITLE, config.DEFAULT_SCRIPT, s, owner)
