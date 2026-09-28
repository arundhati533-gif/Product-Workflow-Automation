"""SQLite storage for projects, meetings and stage runs."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from core import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS project (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS person (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT '',
    team TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS system (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS meeting (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    date TEXT NOT NULL,
    transcript_text TEXT NOT NULL,
    source_format TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'new',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS stage_run (
    id INTEGER PRIMARY KEY,
    meeting_id INTEGER NOT NULL REFERENCES meeting(id) ON DELETE CASCADE,
    stage TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('draft', 'approved', 'stale')),
    output_json TEXT NOT NULL,
    input_hash TEXT NOT NULL,
    model TEXT,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cached_tokens INTEGER NOT NULL DEFAULT 0,
    cost_usd REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY,
    stage_run_id INTEGER NOT NULL REFERENCES stage_run(id) ON DELETE CASCADE,
    item_id TEXT,
    text TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS backlog_item (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    meeting_id INTEGER REFERENCES meeting(id) ON DELETE SET NULL,
    type TEXT NOT NULL CHECK (type IN ('epic', 'story', 'task', 'raid')),
    item_key TEXT NOT NULL,
    data_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    UNIQUE (project_id, type, item_key)
);
CREATE INDEX IF NOT EXISTS idx_stage_run_meeting ON stage_run(meeting_id, stage);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Storage:
    def __init__(self, path: Path | str = config.DB_PATH):
        self.path = Path(path)
        if str(path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA)

    @contextmanager
    def _tx(self):
        with self.conn:
            yield self.conn

    # --- Projects ---------------------------------------------------------

    def create_project(self, name: str, description: str = "") -> int:
        with self._tx() as c:
            cur = c.execute(
                "INSERT INTO project (name, description, created_at) VALUES (?, ?, ?)",
                (name.strip(), description.strip(), _now()),
            )
            return cur.lastrowid

    def list_projects(self) -> list[dict]:
        return [dict(r) for r in self.conn.execute("SELECT * FROM project ORDER BY created_at DESC, id DESC")]

    def get_project(self, project_id: int) -> dict | None:
        row = self.conn.execute("SELECT * FROM project WHERE id = ?", (project_id,)).fetchone()
        return dict(row) if row else None

    def delete_project(self, project_id: int) -> None:
        with self._tx() as c:
            c.execute("DELETE FROM project WHERE id = ?", (project_id,))

    # --- Roster and systems ------------------------------------------------

    def add_person(self, project_id: int, name: str, role: str = "", team: str = "") -> int:
        with self._tx() as c:
            return c.execute(
                "INSERT INTO person (project_id, name, role, team) VALUES (?, ?, ?, ?)",
                (project_id, name.strip(), role.strip(), team.strip()),
            ).lastrowid

    def list_people(self, project_id: int) -> list[dict]:
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM person WHERE project_id = ? ORDER BY name", (project_id,))]

    def add_system(self, project_id: int, name: str, description: str = "") -> int:
        with self._tx() as c:
            return c.execute(
                "INSERT INTO system (project_id, name, description) VALUES (?, ?, ?)",
                (project_id, name.strip(), description.strip()),
            ).lastrowid

    def list_systems(self, project_id: int) -> list[dict]:
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM system WHERE project_id = ? ORDER BY name", (project_id,))]

    # --- Meetings ----------------------------------------------------------

    def create_meeting(self, project_id: int, title: str, date: str, transcript_text: str, source_format: str) -> int:
        with self._tx() as c:
            return c.execute(
                "INSERT INTO meeting (project_id, title, date, transcript_text, source_format, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (project_id, title.strip(), date, transcript_text, source_format, _now()),
            ).lastrowid

    def get_meeting(self, meeting_id: int) -> dict | None:
        row = self.conn.execute("SELECT * FROM meeting WHERE id = ?", (meeting_id,)).fetchone()
        return dict(row) if row else None

    def list_meetings(self, project_id: int) -> list[dict]:
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM meeting WHERE project_id = ? ORDER BY date DESC, id DESC", (project_id,))]

    def set_meeting_status(self, meeting_id: int, status: str) -> None:
        with self._tx() as c:
            c.execute("UPDATE meeting SET status = ? WHERE id = ?", (status, meeting_id))

    # --- Stage runs ----------------------------------------------------------

    def save_stage_run(
        self,
        meeting_id: int,
        stage: str,
        output: dict,
        input_hash: str,
        *,
        status: str = "draft",
        model: str | None = None,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cached_tokens: int = 0,
        cost_usd: float = 0.0,
    ) -> int:
        if stage not in config.STAGES:
            raise ValueError(f"Unknown stage: {stage}")
        with self._tx() as c:
            return c.execute(
                "INSERT INTO stage_run (meeting_id, stage, status, output_json, input_hash, model,"
                " input_tokens, output_tokens, cached_tokens, cost_usd, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (meeting_id, stage, status, json.dumps(output), input_hash, model,
                 input_tokens, output_tokens, cached_tokens, cost_usd, _now()),
            ).lastrowid

    def latest_stage_run(self, meeting_id: int, stage: str) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM stage_run WHERE meeting_id = ? AND stage = ? ORDER BY id DESC LIMIT 1",
            (meeting_id, stage),
        ).fetchone()
        if not row:
            return None
        run = dict(row)
        run["output"] = json.loads(run.pop("output_json"))
        return run

    def stage_runs(self, meeting_id: int, stage: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM stage_run WHERE meeting_id = ? AND stage = ? ORDER BY id", (meeting_id, stage))
        runs = []
        for r in rows:
            run = dict(r)
            run["output"] = json.loads(run.pop("output_json"))
            runs.append(run)
        return runs

    def stage_runs_for_project(self, project_id: int, stage: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT r.* FROM stage_run r JOIN meeting m ON m.id = r.meeting_id"
            " WHERE m.project_id = ? AND r.stage = ? ORDER BY r.id",
            (project_id, stage),
        )
        runs = []
        for r in rows:
            run = dict(r)
            run["output"] = json.loads(run.pop("output_json"))
            runs.append(run)
        return runs

    def set_stage_status(self, stage_run_id: int, status: str) -> None:
        with self._tx() as c:
            c.execute("UPDATE stage_run SET status = ? WHERE id = ?", (status, stage_run_id))

    def meeting_cost(self, meeting_id: int) -> float:
        row = self.conn.execute(
            "SELECT COALESCE(SUM(cost_usd), 0) FROM stage_run WHERE meeting_id = ?", (meeting_id,)).fetchone()
        return float(row[0])

    # --- Feedback ------------------------------------------------------------

    def add_feedback(self, stage_run_id: int, text: str, item_id: str | None = None) -> int:
        with self._tx() as c:
            return c.execute(
                "INSERT INTO feedback (stage_run_id, item_id, text, created_at) VALUES (?, ?, ?, ?)",
                (stage_run_id, item_id, text.strip(), _now()),
            ).lastrowid

    def list_feedback(self, stage_run_id: int) -> list[dict]:
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM feedback WHERE stage_run_id = ? ORDER BY id", (stage_run_id,))]

    # --- Project backlog -----------------------------------------------------

    def upsert_backlog_item(self, project_id: int, meeting_id: int | None, type_: str, item_key: str,
                            data: dict, status: str = "active") -> None:
        with self._tx() as c:
            c.execute(
                "INSERT INTO backlog_item (project_id, meeting_id, type, item_key, data_json, status)"
                " VALUES (?, ?, ?, ?, ?, ?)"
                " ON CONFLICT (project_id, type, item_key) DO UPDATE SET"
                " meeting_id = excluded.meeting_id, data_json = excluded.data_json, status = excluded.status",
                (project_id, meeting_id, type_, item_key, json.dumps(data), status),
            )

    def list_backlog(self, project_id: int, type_: str | None = None) -> list[dict]:
        sql = "SELECT * FROM backlog_item WHERE project_id = ?"
        args: list = [project_id]
        if type_:
            sql += " AND type = ?"
            args.append(type_)
        items = []
        for r in self.conn.execute(sql + " ORDER BY id", args):
            item = dict(r)
            item["data"] = json.loads(item.pop("data_json"))
            items.append(item)
        return items

    def close(self) -> None:
        self.conn.close()
