"""SQLite persistence for AEGIS runs (standard library only).

How it works
  The simulator is deterministic, so a run is fully described by
      scenario + strategy + the ordered journal of actions applied to it
  (step N ticks / run to the end / injected event). We store exactly that, plus a
  cached copy of the latest status, metrics and event log so history can be read
  without rebuilding anything. `replay()` rebuilds a live run by re-applying the
  journal, which is how runs survive a server restart or eviction from memory.

Configuration
  AEGIS_DB=path/to/file.db   use that file (default: data/aegis.db)
  AEGIS_DB=:memory:          in-memory only (used by the tests)
  AEGIS_DB=off               disable persistence entirely

Persistence never breaks a simulation: write failures are logged and ignored.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from services.simulation_service import SimulationService

log = logging.getLogger("aegis.persistence")

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "aegis.db"
MAX_SAVED_RUNS = 500  # oldest runs (and their journals) are pruned beyond this

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id        TEXT PRIMARY KEY,
    scenario      TEXT NOT NULL,
    strategy      TEXT NOT NULL,
    scenario_json TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    status        TEXT NOT NULL,
    tick          INTEGER NOT NULL,
    width         INTEGER NOT NULL,
    height        INTEGER NOT NULL,
    robots        INTEGER NOT NULL,
    tasks         INTEGER NOT NULL,
    metrics_json  TEXT NOT NULL,
    events_json   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS journal (
    seq          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id       TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    op           TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    tick         INTEGER NOT NULL,
    created_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS journal_run ON journal(run_id, seq);
CREATE TABLE IF NOT EXISTS benchmarks (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id     INTEGER NOT NULL,
    created_at   TEXT NOT NULL,
    scenario     TEXT NOT NULL,
    strategy     TEXT NOT NULL,
    metrics_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS runs_scenario ON runs(scenario, strategy, updated_at);
"""

JOURNAL_OPS = ("step", "run", "event")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Database:
    """Thin, thread-safe wrapper around one SQLite connection."""

    def __init__(self, path: str | Path = ":memory:"):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA foreign_keys = ON")
            if self.path != ":memory:":
                self._conn.execute("PRAGMA journal_mode = WAL")
            self._conn.executescript(SCHEMA)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ------------------------------------------------------------------ runs
    def save_run(self, run_id: str, scenario: dict, strategy: str, created_at: str, fields: dict) -> None:
        """Insert (or replace) a run and start its journal empty."""
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM runs WHERE run_id = ?", (run_id,))  # cascades the journal
            self._conn.execute(
                "INSERT INTO runs (run_id, scenario, strategy, scenario_json, created_at, updated_at,"
                " status, tick, width, height, robots, tasks, metrics_json, events_json)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (run_id, scenario.get("name", "adhoc"), strategy, json.dumps(scenario), created_at, _now(),
                 fields["status"], fields["tick"], fields["width"], fields["height"], fields["robots"],
                 fields["tasks"], json.dumps(fields["metrics"]), json.dumps(fields["events"])),
            )
            self._prune()

    def update_run(self, run_id: str, fields: dict) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE runs SET updated_at=?, status=?, tick=?, tasks=?, metrics_json=?, events_json=?"
                " WHERE run_id=?",
                (_now(), fields["status"], fields["tick"], fields["tasks"],
                 json.dumps(fields["metrics"]), json.dumps(fields["events"]), run_id),
            )

    def append_journal(self, run_id: str, op: str, payload: dict, tick: int, fields: dict) -> None:
        """Record one action and refresh the cached state in a single transaction."""
        if op not in JOURNAL_OPS:
            raise ValueError(f"unknown journal op {op!r}")
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO journal (run_id, op, payload_json, tick, created_at) VALUES (?,?,?,?,?)",
                (run_id, op, json.dumps(payload), tick, _now()),
            )
            self._conn.execute(
                "UPDATE runs SET updated_at=?, status=?, tick=?, tasks=?, metrics_json=?, events_json=?"
                " WHERE run_id=?",
                (_now(), fields["status"], fields["tick"], fields["tasks"],
                 json.dumps(fields["metrics"]), json.dumps(fields["events"]), run_id),
            )

    def clear_journal(self, run_id: str) -> None:
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM journal WHERE run_id = ?", (run_id,))

    def get_run(self, run_id: str) -> Optional[dict]:
        with self._lock:
            row = self._conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
            if row is None:
                return None
            actions = self._conn.execute(
                "SELECT COUNT(*) FROM journal WHERE run_id = ?", (run_id,)).fetchone()[0]
        return self._run_dict(row, actions)

    def list_runs(self, limit: int = 50, scenario: str | None = None, strategy: str | None = None) -> List[dict]:
        sql = ("SELECT r.*, (SELECT COUNT(*) FROM journal j WHERE j.run_id = r.run_id) AS n_actions"
               " FROM runs r")
        where, args = [], []
        if scenario is not None:
            where.append("r.scenario = ?")
            args.append(scenario)
        if strategy is not None:
            where.append("r.strategy = ?")
            args.append(strategy)
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY r.updated_at DESC, r.created_at DESC, r.rowid DESC LIMIT ?"
        args.append(limit)
        with self._lock:
            rows = self._conn.execute(sql, args).fetchall()
        return [self._run_dict(r, r["n_actions"]) for r in rows]

    def journal(self, run_id: str) -> List[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT op, payload_json, tick, created_at FROM journal WHERE run_id = ? ORDER BY seq",
                (run_id,)).fetchall()
        return [
            {"seq": i + 1, "op": r["op"], "payload": json.loads(r["payload_json"]),
             "tick": r["tick"], "created_at": r["created_at"]}
            for i, r in enumerate(rows)
        ]

    def delete_run(self, run_id: str) -> bool:
        with self._lock, self._conn:
            return self._conn.execute("DELETE FROM runs WHERE run_id = ?", (run_id,)).rowcount > 0

    def count_runs(self) -> int:
        with self._lock:
            return self._conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]

    def latest_finished(self, scenario: str, strategy: str) -> Optional[dict]:
        """Most recently updated run of this scenario+strategy that is finished or stalled."""
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM runs WHERE scenario=? AND strategy=? AND status IN ('finished','stalled')"
                " ORDER BY updated_at DESC, rowid DESC LIMIT 1", (scenario, strategy)).fetchone()
        return None if row is None else self._run_dict(row, 0)

    def _prune(self) -> None:
        self._conn.execute(
            "DELETE FROM runs WHERE run_id IN (SELECT run_id FROM runs ORDER BY created_at DESC, rowid DESC"
            " LIMIT -1 OFFSET ?)", (MAX_SAVED_RUNS,))

    @staticmethod
    def _run_dict(row: sqlite3.Row, actions: int) -> dict:
        return {
            "run_id": row["run_id"], "scenario": row["scenario"], "strategy": row["strategy"],
            "created_at": row["created_at"], "updated_at": row["updated_at"],
            "status": row["status"], "tick": row["tick"], "width": row["width"], "height": row["height"],
            "robots": row["robots"], "tasks": row["tasks"], "actions": actions,
            "metrics": json.loads(row["metrics_json"]), "events": json.loads(row["events_json"]),
            "scenario_def": json.loads(row["scenario_json"]),
        }

    # ------------------------------------------------------------ benchmarks
    def save_benchmark(self, rows: List[dict]) -> int:
        """Store one benchmark batch; returns its batch id."""
        with self._lock, self._conn:
            batch = (self._conn.execute("SELECT COALESCE(MAX(batch_id), 0) FROM benchmarks").fetchone()[0]) + 1
            now = _now()
            self._conn.executemany(
                "INSERT INTO benchmarks (batch_id, created_at, scenario, strategy, metrics_json)"
                " VALUES (?,?,?,?,?)",
                [(batch, now, r["scenario"], r["strategy"], json.dumps(r)) for r in rows],
            )
        return batch

    def list_benchmarks(self, limit: int = 100) -> List[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT batch_id, created_at, metrics_json FROM benchmarks ORDER BY id DESC LIMIT ?",
                (limit,)).fetchall()
        return [{**json.loads(r["metrics_json"]), "batch_id": r["batch_id"], "created_at": r["created_at"]}
                for r in rows]

    def clear(self) -> None:
        """Delete everything (used by tests and a manual reset)."""
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM benchmarks")
            self._conn.execute("DELETE FROM runs")  # cascades the journal


def open_database(spec: str | None) -> Optional[Database]:
    """Resolve the AEGIS_DB setting. None means persistence is disabled."""
    if spec is None or spec.strip() == "":
        spec = str(DEFAULT_DB_PATH)
    if spec.strip().lower() in ("off", "none", "false", "0"):
        return None
    try:
        return Database(spec)
    except (sqlite3.Error, OSError) as exc:  # e.g. read-only directory: run without persistence
        log.warning("persistence disabled, cannot open %s: %s", spec, exc)
        return None


# ---------------------------------------------------------------- recording
def _fields(svc: SimulationService) -> dict:
    snap = svc.snapshot()
    metrics = svc.metrics()
    return {
        "status": svc.status(), "tick": snap["tick"], "width": snap["width"], "height": snap["height"],
        "robots": len(snap["robots"]), "tasks": metrics["tasks_created"],
        "metrics": metrics, "events": svc.events(1_000_000),
    }


class Recorder:
    """Called by the API after each state-changing request. Never raises on DB errors."""

    def __init__(self, db: Optional[Database]):
        self.db = db

    @property
    def enabled(self) -> bool:
        return self.db is not None

    def created(self, run_id: str, svc: SimulationService, created_at: str) -> None:
        self._try(lambda: self.db.save_run(run_id, svc.scenario, svc.strategy, created_at, _fields(svc)))

    def action(self, run_id: str, svc: SimulationService, op: str, payload: dict | None = None) -> None:
        self._try(lambda: self.db.append_journal(
            run_id, op, payload or {}, svc.sim.tick, _fields(svc)))

    def reset(self, run_id: str, svc: SimulationService) -> None:
        def go():
            self.db.clear_journal(run_id)
            self.db.update_run(run_id, _fields(svc))
        self._try(go)

    def _try(self, fn) -> None:
        if self.db is None:
            return
        try:
            fn()
        except (sqlite3.Error, ValueError, TypeError) as exc:
            log.warning("could not persist run state: %s", exc)


# ------------------------------------------------------------------- replay
def replay(scenario: dict, strategy: str, journal: List[dict]) -> SimulationService:
    """Rebuild a live run by re-applying its journal to a fresh simulator."""
    svc = SimulationService()
    svc.create_from_scenario(scenario, strategy)
    for entry in journal:
        op, payload = entry["op"], entry["payload"]
        if op == "step":
            for _ in range(int(payload.get("ticks", 1))):
                svc.step()
        elif op == "run":
            svc.run_to_end()
        elif op == "event":
            svc.apply_event(payload)
        else:
            raise ValueError(f"unknown journal op {op!r}")
    return svc
