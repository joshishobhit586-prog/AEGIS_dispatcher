import sqlite3
from pathlib import Path

import pytest

from evaluation.scenarios import load_scenario
from services import persistence as P
from services.simulation_service import SimulationService

SCEN = Path(__file__).resolve().parent.parent / "scenarios"


@pytest.fixture
def db():
    d = P.Database(":memory:")
    yield d
    d.close()


def _live(db, name="robot_failure", strategy="aegis", run_id="run00001"):
    rec = P.Recorder(db)
    svc = SimulationService()
    svc.create_from_scenario(load_scenario(SCEN / f"{name}.json"), strategy)
    rec.created(run_id, svc, "2026-01-01T00:00:00+00:00")
    return rec, svc


def _step(rec, svc, run_id, n):
    done = 0
    for _ in range(n):
        if svc.status() != "running":
            break
        svc.step()
        done += 1
    rec.action(run_id, svc, "step", {"ticks": done})


def test_created_run_is_saved_with_state(db):
    _live(db)
    row = db.get_run("run00001")
    assert row["scenario"] == "robot_failure" and row["strategy"] == "aegis"
    assert row["tick"] == 0 and row["status"] == "running" and row["actions"] == 0
    assert row["robots"] == 3 and row["metrics"]["tasks_created"] == 10


def test_actions_update_cached_state_and_journal(db):
    rec, svc = _live(db)
    _step(rec, svc, "run00001", 5)
    svc.run_to_end()
    rec.action("run00001", svc, "run")
    row = db.get_run("run00001")
    assert row["tick"] == svc.sim.tick and row["status"] in ("finished", "stalled")
    assert row["metrics"]["tasks_completed"] == svc.metrics()["tasks_completed"]
    assert [j["op"] for j in db.journal("run00001")] == ["step", "run"]
    assert len(row["events"]) == len(svc.events(10_000))


def test_replay_reproduces_a_run_with_injected_events_exactly(db):
    rec, svc = _live(db, "small_warehouse", "aegis")
    _step(rec, svc, "run00001", 6)
    ev = {"type": "robot_failure", "robot_id": "R2"}
    svc.apply_event(ev)
    rec.action("run00001", svc, "event", ev)
    _step(rec, svc, "run00001", 4)
    ev2 = {"type": "add_task", "task": {"id": "TX", "pickup": [0, 0], "delivery": [8, 6], "priority": 3,
                                        "deadline": 60}}
    svc.apply_event(ev2)
    rec.action("run00001", svc, "event", ev2)
    svc.run_to_end()
    rec.action("run00001", svc, "run")

    row = db.get_run("run00001")
    clone = P.replay(row["scenario_def"], row["strategy"], db.journal("run00001"))
    assert clone.snapshot() == svc.snapshot()
    assert clone.sim.event_log == svc.sim.event_log
    a, b = clone.metrics(), svc.metrics()
    a.pop("planning_time_s"), b.pop("planning_time_s")  # wall-clock, not simulated
    assert a == b


def test_rejected_event_replays_the_same(db):
    rec, svc = _live(db)
    bad = {"type": "robot_restore", "robot_id": "R1"}  # R1 is healthy -> rejected by the simulation
    svc.apply_event(bad)
    rec.action("run00001", svc, "event", bad)
    assert any(e["type"] == "event_rejected" for e in svc.events(100))
    clone = P.replay(db.get_run("run00001")["scenario_def"], "aegis", db.journal("run00001"))
    assert clone.sim.event_log == svc.sim.event_log


def test_reset_clears_journal_and_state(db):
    rec, svc = _live(db)
    _step(rec, svc, "run00001", 5)
    svc.reset()
    rec.reset("run00001", svc)
    row = db.get_run("run00001")
    assert db.journal("run00001") == [] and row["tick"] == 0 and row["actions"] == 0


def test_survives_reopening_the_database_file(tmp_path):
    path = tmp_path / "aegis.db"
    d1 = P.Database(path)
    rec, svc = _live(d1)
    _step(rec, svc, "run00001", 8)
    d1.close()
    d2 = P.Database(path)  # "server restart"
    clone = P.replay(d2.get_run("run00001")["scenario_def"], "aegis", d2.journal("run00001"))
    assert clone.snapshot() == svc.snapshot()
    d2.close()


def test_list_filter_latest_and_delete(db):
    rec_a, svc_a = _live(db, "robot_failure", "aegis", "aaaa0001")
    rec_b, svc_b = _live(db, "robot_failure", "baseline", "bbbb0001")
    for rec, svc, rid in ((rec_a, svc_a, "aaaa0001"), (rec_b, svc_b, "bbbb0001")):
        svc.run_to_end()
        rec.action(rid, svc, "run")
    _live(db, "urgent_task", "aegis", "cccc0001")  # still running, never finished
    assert {r["run_id"] for r in db.list_runs()} == {"aaaa0001", "bbbb0001", "cccc0001"}
    assert [r["run_id"] for r in db.list_runs(strategy="baseline")] == ["bbbb0001"]
    assert db.latest_finished("robot_failure", "aegis")["run_id"] == "aaaa0001"
    assert db.latest_finished("urgent_task", "aegis") is None
    assert db.delete_run("aaaa0001") and db.get_run("aaaa0001") is None
    assert db.journal("aaaa0001") == [] and not db.delete_run("aaaa0001")


def test_old_runs_are_pruned(db, monkeypatch):
    monkeypatch.setattr(P, "MAX_SAVED_RUNS", 3)
    for i in range(5):
        _live(db, run_id=f"run{i:05d}")
    ids = {r["run_id"] for r in db.list_runs()}
    assert ids == {"run00002", "run00003", "run00004"}


def test_benchmark_batches(db):
    rows = [{"scenario": "s", "strategy": "baseline", "ticks": 1}, {"scenario": "s", "strategy": "aegis", "ticks": 2}]
    assert db.save_benchmark(rows) == 1 and db.save_benchmark(rows) == 2
    got = db.list_benchmarks()
    assert len(got) == 4 and got[0]["batch_id"] == 2 and got[-1]["batch_id"] == 1


def test_recorder_never_raises_when_db_is_broken(db):
    rec, svc = _live(db)
    db.close()
    rec.action("run00001", svc, "step", {"ticks": 1})  # sqlite3.ProgrammingError -> swallowed
    P.Recorder(None).created("x", svc, "now")          # disabled persistence is a no-op


def test_open_database_settings(tmp_path):
    assert P.open_database("off") is None
    d = P.open_database(str(tmp_path / "sub" / "x.db"))
    assert isinstance(d, P.Database) and (tmp_path / "sub" / "x.db").exists()
    d.close()
    assert P.open_database(":memory:").path == ":memory:"
