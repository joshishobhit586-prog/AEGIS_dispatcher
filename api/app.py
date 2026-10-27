"""AEGIS HTTP API (FastAPI). A thin layer over services.SimulationService.

Run:  uvicorn api.app:app --reload        (docs at http://127.0.0.1:8000/docs)
  or: python main.py --api

All planning/recovery logic lives in the application layer; this module only
validates requests, routes them, and shapes responses. Live simulations are held in
memory; every run is also saved to SQLite (see services/persistence.py, AEGIS_DB) so
history survives restarts and a saved run can be resumed. Do not expose this to the public internet as-is: there
is no authentication or rate limiting.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import Body, FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware

from api import schemas as S
from api.store import MAX_LIVE_SIMULATIONS, Entry, SimulationStore
from config import STRATEGIES
from evaluation import generator as gen
from evaluation.run_benchmarks import run_scenario
from evaluation.scenarios import load_scenario, scenario_paths
from services import persistence as P
from services.simulation_service import SimulationService

SCENARIO_DIR = Path(os.environ.get("AEGIS_SCENARIOS_DIR", Path(__file__).resolve().parent.parent / "scenarios"))
store = SimulationStore()
db = P.open_database(os.environ.get("AEGIS_DB"))  # None when AEGIS_DB=off
recorder = P.Recorder(db)

app = FastAPI(
    title="AEGIS API",
    version="0.2.0",
    description="Adaptive multi-robot mission recovery - warehouse fleet simulation. "
                "Create a run (from a named scenario or a generated grid with your own "
                "size and robot count), step it, inject disruptions, and read metrics.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_methods=["*"],
    allow_headers=["*"],
)


# ------------------------------------------------------------------ helpers
def _named_scenarios() -> Dict[str, Path]:
    return {p.stem: p for p in scenario_paths(SCENARIO_DIR)}


def _entry(run_id: str) -> Entry:
    entry = store.get(run_id)
    if entry is None:
        raise HTTPException(404, f"simulation {run_id!r} not found")
    return entry


def _db() -> P.Database:
    if db is None:
        raise HTTPException(503, "persistence is disabled (AEGIS_DB=off)")
    return db


def _history_run(row: dict) -> dict:
    return {k: row[k] for k in (
        "run_id", "scenario", "strategy", "status", "tick", "width", "height", "robots", "tasks",
        "actions", "created_at", "updated_at")} | {"live": store.get(row["run_id"]) is not None}


def _event_to_sim(ev) -> dict:
    d = ev.model_dump()
    if "cell" in d:
        d["cell"] = list(d["cell"])
    if "task" in d:
        d["task"]["pickup"] = list(d["task"]["pickup"])
        d["task"]["delivery"] = list(d["task"]["delivery"])
    return d


def _check_event(ev, in_bounds, robot_ids: List[str], task_ids=()) -> Optional[tuple]:
    """Return (status_code, message) if the event is invalid for this world."""
    if ev.type in ("robot_failure", "robot_restore") and ev.robot_id not in robot_ids:
        return 404, f"unknown robot {ev.robot_id!r}"
    if ev.type in ("block_cell", "unblock_cell") and not in_bounds(tuple(ev.cell)):
        return 422, f"cell {tuple(ev.cell)} is outside the grid"
    if ev.type == "add_task":
        t = ev.task
        if not in_bounds(tuple(t.pickup)) or not in_bounds(tuple(t.delivery)):
            return 422, "pickup/delivery cell is outside the grid"
        if t.id in task_ids:
            return 409, f"task id {t.id!r} already exists"
    return None


def _scenario_from_custom(cfg: S.CustomConfig) -> dict:
    width, height = cfg.width, cfg.height
    robot_ids = [f"R{i + 1}" for i in range(cfg.robots)]
    inb = lambda c: 0 <= c[0] < width and 0 <= c[1] < height
    events = []
    for se in cfg.events:
        err = _check_event(se.event, inb, robot_ids)
        if err and err[0] != 409:
            raise HTTPException(422, f"event at tick {se.tick}: {err[1]}")
        events.append({"tick": se.tick, **_event_to_sim(se.event)})
    return gen.generate_scenario(width, height, cfg.robots, cfg.tasks, cfg.seed, events)


def _state(entry: Entry, include_map: bool) -> S.StateResponse:
    svc = entry.service
    snap = svc.snapshot()
    return S.StateResponse(
        run_id=entry.run_id,
        tick=snap["tick"],
        strategy=snap["strategy"],
        status=svc.status(),
        blocked=snap["blocked"],
        robots=snap["robots"],
        tasks=snap["tasks"],
        map=S.MapState(width=snap["width"], height=snap["height"], shelves=snap["shelves"])
        if include_map else None,
    )


def _info(entry: Entry) -> S.SimulationInfo:
    svc = entry.service
    snap = svc.snapshot()
    return S.SimulationInfo(
        run_id=entry.run_id,
        scenario=svc.scenario_name,
        strategy=svc.strategy,
        tick=snap["tick"],
        status=svc.status(),
        width=snap["width"],
        height=snap["height"],
        robots=len(snap["robots"]),
        tasks=len(snap["tasks"]),
        created_at=entry.created_at,
    )


# ------------------------------------------------------------------- routes
@app.get("/health", tags=["meta"])
def health():
    return {
        "status": "ok", "version": app.version, "live_simulations": len(store.all()),
        "persistence": {"enabled": db is not None, "path": db.path if db else None,
                        "saved_runs": db.count_runs() if db else 0},
    }


@app.get("/limits", response_model=S.Limits, tags=["meta"])
def limits():
    return S.Limits(
        min_width=gen.MIN_WIDTH, max_width=gen.MAX_WIDTH,
        min_height=gen.MIN_HEIGHT, max_height=gen.MAX_HEIGHT,
        max_robots=gen.MAX_ROBOTS, max_tasks=gen.MAX_TASKS,
        max_live_simulations=MAX_LIVE_SIMULATIONS,
        note="Robots start on the top row, so robots <= width. Oldest runs are evicted past the live limit.",
    )


@app.get("/scenarios", response_model=List[S.ScenarioInfo], tags=["scenarios"])
def list_scenarios():
    out = []
    for name, path in _named_scenarios().items():
        sc = load_scenario(path)
        out.append(S.ScenarioInfo(
            name=name, description=sc.get("description", ""),
            width=len(sc["layout"][0]), height=len(sc["layout"]),
            robots=len(sc["robots"]), tasks=len(sc["tasks"]), events=len(sc["events"]),
        ))
    return out


@app.get("/simulations", response_model=List[S.SimulationInfo], tags=["simulations"])
def list_simulations():
    return [_info(e) for e in store.all()]


@app.post("/simulations", response_model=S.SimulationCreated, status_code=201, tags=["simulations"])
def create_simulation(req: S.CreateSimulation):
    if req.scenario is not None:
        named = _named_scenarios()
        if req.scenario not in named:
            raise HTTPException(404, f"unknown scenario {req.scenario!r}; see GET /scenarios")
        scenario = load_scenario(named[req.scenario])
    else:
        scenario = _scenario_from_custom(req.custom)
    svc = SimulationService()
    try:
        svc.create_from_scenario(scenario, req.strategy)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    entry = store.add(svc)
    recorder.created(entry.run_id, svc, entry.created_at)
    return S.SimulationCreated(info=_info(entry), state=_state(entry, include_map=True))


@app.get("/simulations/{run_id}", response_model=S.SimulationInfo, tags=["simulations"])
def get_simulation(run_id: str):
    entry = _entry(run_id)
    with entry.lock:
        return _info(entry)


@app.delete("/simulations/{run_id}", status_code=204, tags=["simulations"])
def delete_simulation(run_id: str):
    if not store.delete(run_id):
        raise HTTPException(404, f"simulation {run_id!r} not found")
    return Response(status_code=204)


@app.get("/simulations/{run_id}/state", response_model=S.StateResponse, tags=["simulations"])
def get_state(run_id: str, include_map: bool = Query(True, description="include grid size and shelves")):
    entry = _entry(run_id)
    with entry.lock:
        return _state(entry, include_map)


@app.post("/simulations/{run_id}/step", response_model=S.StateResponse, tags=["control"])
def step(run_id: str, req: S.StepRequest = Body(default_factory=S.StepRequest),
         include_map: bool = False):
    """Advance up to `ticks` ticks (stops early once the run is finished or stalled)."""
    entry = _entry(run_id)
    with entry.lock:
        executed = 0
        for _ in range(req.ticks):
            if entry.service.status() != "running":
                break
            entry.service.step()
            executed += 1
        if executed:
            recorder.action(run_id, entry.service, "step", {"ticks": executed})
        return _state(entry, include_map)


@app.post("/simulations/{run_id}/run", response_model=S.StateResponse, tags=["control"])
def run_to_end(run_id: str, include_map: bool = False):
    """Run until finished, stalled, or the scenario's tick cap."""
    entry = _entry(run_id)
    with entry.lock:
        entry.service.run_to_end()
        recorder.action(run_id, entry.service, "run")
        return _state(entry, include_map)


@app.post("/simulations/{run_id}/reset", response_model=S.StateResponse, tags=["control"])
def reset(run_id: str, include_map: bool = False):
    entry = _entry(run_id)
    with entry.lock:
        entry.service.reset()
        recorder.reset(run_id, entry.service)
        return _state(entry, include_map)


@app.post("/simulations/{run_id}/events", response_model=S.EventResult, tags=["control"])
def post_event(run_id: str, ev: S.EventRequest):
    """Inject a disruption or a new task now. Rejected requests return 404/409/422."""
    entry = _entry(run_id)
    with entry.lock:
        svc = entry.service
        sim = svc.sim
        err = _check_event(ev, sim.warehouse.in_bounds, svc.robot_ids(), set(sim.tasks))
        if err:
            raise HTTPException(err[0], err[1])
        before = len(sim.event_log)
        if ev.type == "robot_failure":
            svc.disable_robot(ev.robot_id)
        elif ev.type == "robot_restore":
            svc.restore_robot(ev.robot_id)
        elif ev.type == "block_cell":
            svc.block_cell(ev.cell)
        elif ev.type == "unblock_cell":
            svc.unblock_cell(ev.cell)
        else:
            t = ev.task
            svc.add_task(t.id, t.pickup, t.delivery, t.priority, t.deadline)
        recorder.action(run_id, svc, "event", _event_to_sim(ev) | {"tick": sim.tick})
        new = sim.event_log[before:]
        rejected = [e for e in new if e["type"] in ("event_rejected", "assignment_rejected")]
        if rejected:
            raise HTTPException(409, rejected[0]["description"])
        return S.EventResult(applied=True, log=new, state=_state(entry, include_map=False))


@app.get("/simulations/{run_id}/events", response_model=List[S.EventRecord], tags=["simulations"])
def get_events(run_id: str, limit: int = Query(100, ge=1, le=1000)):
    entry = _entry(run_id)
    with entry.lock:
        return entry.service.events(limit)


@app.get("/simulations/{run_id}/metrics", response_model=S.MetricsResponse, tags=["simulations"])
def get_metrics(run_id: str):
    entry = _entry(run_id)
    with entry.lock:
        return entry.service.metrics()


@app.post("/benchmarks", response_model=S.BenchmarkResponse, tags=["benchmarks"])
def benchmarks(req: S.BenchmarkRequest = Body(default_factory=S.BenchmarkRequest)):
    """Run baseline and aegis on identical inputs and return measured metrics.

    Runs synchronously; bounded by the scenario/size limits. With no body, runs every named scenario.
    """
    named = _named_scenarios()
    scenarios: List[dict] = []
    if req.scenarios is not None:
        missing = [n for n in req.scenarios if n not in named]
        if missing:
            raise HTTPException(404, f"unknown scenario(s): {missing}")
        scenarios += [load_scenario(named[n]) for n in req.scenarios]
    if req.custom is not None:
        scenarios.append(_scenario_from_custom(req.custom))
    if req.scenarios is None and req.custom is None:
        scenarios = [load_scenario(p) for p in named.values()]
    rows = [run_scenario(sc, strat) for sc in scenarios for strat in STRATEGIES]
    if db is not None:
        try:
            db.save_benchmark(rows)
        except Exception as exc:  # never fail a benchmark because history could not be saved
            P.log.warning("could not save benchmark history: %s", exc)
    return S.BenchmarkResponse(count=len(rows), rows=rows)


@app.get("/benchmarks/history", response_model=List[S.StoredBenchmarkRow], tags=["benchmarks"])
def benchmark_history(limit: int = Query(100, ge=1, le=1000)):
    """Rows from earlier POST /benchmarks calls, newest first (grouped by batch_id)."""
    return _db().list_benchmarks(limit)


# ------------------------------------------------------------------ history
@app.get("/history", response_model=List[S.HistoryRun], tags=["history"])
def history(limit: int = Query(50, ge=1, le=500), scenario: Optional[str] = None,
            strategy: Optional[str] = Query(None, pattern="^(baseline|aegis)$")):
    """Saved runs, newest first. Survives restarts and eviction from memory."""
    return [_history_run(r) for r in _db().list_runs(limit, scenario, strategy)]


@app.get("/history/compare", response_model=S.CompareResponse, tags=["history"])
def history_compare(scenario: str):
    """Latest finished baseline vs aegis run of a scenario, with the difference."""
    d = _db()
    by = {strat: d.latest_finished(scenario, strat) for strat in STRATEGIES}
    if all(v is None for v in by.values()):
        raise HTTPException(404, f"no finished runs saved for scenario {scenario!r}")
    out = S.CompareResponse(
        scenario=scenario,
        baseline=by["baseline"]["metrics"] if by["baseline"] else None,
        aegis=by["aegis"]["metrics"] if by["aegis"] else None,
    )
    if by["baseline"] and by["aegis"]:
        b, a = by["baseline"]["metrics"], by["aegis"]["metrics"]
        out.delta = {k: round(a[k] - b[k], 2) for k in (
            "completion_rate", "unserved_tasks", "total_distance", "total_delay",
            "recovery_duration_ticks", "wait_ticks", "ticks")}
    return out


@app.get("/history/{run_id}", response_model=S.HistoryDetail, tags=["history"])
def history_detail(run_id: str):
    row = _db().get_run(run_id)
    if row is None:
        raise HTTPException(404, f"saved run {run_id!r} not found")
    return {**_history_run(row), "metrics": row["metrics"]}


@app.get("/history/{run_id}/events", response_model=List[S.EventRecord], tags=["history"])
def history_events(run_id: str, limit: int = Query(100, ge=1, le=1000)):
    row = _db().get_run(run_id)
    if row is None:
        raise HTTPException(404, f"saved run {run_id!r} not found")
    return row["events"][-limit:]


@app.get("/history/{run_id}/journal", response_model=List[S.JournalEntry], tags=["history"])
def history_journal(run_id: str):
    """The ordered actions that produced this run (replaying them rebuilds it exactly)."""
    d = _db()
    if d.get_run(run_id) is None:
        raise HTTPException(404, f"saved run {run_id!r} not found")
    return d.journal(run_id)


@app.post("/history/{run_id}/resume", response_model=S.SimulationCreated, status_code=201,
          tags=["history"])
def history_resume(run_id: str):
    """Bring a saved run back to life (after a restart or eviction) by replaying its journal."""
    d = _db()
    live = store.get(run_id)
    if live is not None:
        with live.lock:
            return S.SimulationCreated(info=_info(live), state=_state(live, include_map=True))
    row = d.get_run(run_id)
    if row is None:
        raise HTTPException(404, f"saved run {run_id!r} not found")
    try:
        svc = P.replay(row["scenario_def"], row["strategy"], d.journal(run_id))
    except (ValueError, KeyError) as exc:
        raise HTTPException(409, f"saved run could not be replayed: {exc}")
    entry = store.add(svc, run_id=run_id, created_at=row["created_at"])
    with entry.lock:
        return S.SimulationCreated(info=_info(entry), state=_state(entry, include_map=True))


@app.delete("/history/{run_id}", status_code=204, tags=["history"])
def history_delete(run_id: str):
    """Permanently delete a saved run (and drop it from memory if live)."""
    if not _db().delete_run(run_id):
        raise HTTPException(404, f"saved run {run_id!r} not found")
    store.delete(run_id)
    return Response(status_code=204)
