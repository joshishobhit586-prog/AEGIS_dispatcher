# AEGIS - Adaptive Multi-Robot Mission Recovery

Software-only warehouse fleet simulation. When a robot fails, a corridor is blocked,
or an urgent delivery appears, AEGIS replans routes and reassigns unfinished tasks
across the fleet, and is compared against a baseline that only reroutes locally.

**Status:** grid, A*, robots/tasks, disruptions, recovery, baseline, metrics, benchmarks,
Pygame UI, FastAPI backend, and user-chosen grid size / robot count are done.
Not built yet: SQLite persistence and charts.

## Setup
```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
python -m pip install -r requirements.txt
python -m pytest                                    # 104 tests
python main.py                                      # Pygame UI
python main.py --cli --scenario scenarios/robot_failure.json --strategy aegis --log
python main.py --benchmark                          # writes results/benchmark_results.{csv,json}
python main.py --api                                # FastAPI server, docs at http://127.0.0.1:8000/docs
```

## Using the UI
Click a robot or cell to select it. Every action is a button and a key:

| Key | Action |
|---|---|
| Space | start / pause (auto-pauses when the run finishes or stalls) |
| N or Right | step one tick |
| R | reset scenario |
| Tab / click | select robot |
| F / U | fail / restore the selected robot |
| B | block / unblock the selected cell |
| T | add a task: click pickup cell, then delivery cell (priority 3, deadline +40 ticks) |
| V | show / hide routes |
| S | switch strategy baseline <-> aegis (resets) |
| C | next scenario |
| - / + | slower / faster |
| Q | quit |

Map symbols: triangle = pickup, hollow square = delivery, grey = unassigned task,
red cross = blocked cell or failed robot, white dot on a robot = carrying cargo,
letter on a robot = M moving / W waiting / I idle / X failed.

Demo: load `robot_failure`, press Space, select R2 with Tab shortly after it starts moving,
press F, and watch the event log show the recovery decision. Press S to rerun with the baseline.

## Choosing grid size and number of robots
The map is generated from a few numbers (`evaluation/generator.py`): aisles every 4th column and
every 3rd row, shelves in between, robots start along the top row, tasks are random open cells
(seeded, so the same numbers always give the same world).

| Setting | Allowed |
|---|---|
| width x height | 5-60 x 4-40 (the window UI caps at 45 x 30 so cells stay readable) |
| robots | 1-20, and not more than the width |
| tasks | 0-80 (default: 3 per robot) |

- **Window:** buttons / keys `[` `]` change robots, `,` `.` change the grid, `G` rolls new random tasks.
  Fail a robot or block a cell on any generated world.
- **API:** `POST /simulations` with `{"custom": {"width": 30, "height": 20, "robots": 8, "seed": 5}}`.

## HTTP API (FastAPI)
Start with `python main.py --api` (local only by default) and open `/docs` for interactive docs.

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/health`, `/limits`, `/scenarios` | status, allowed sizes, named scenarios |
| POST | `/simulations` | create a run from `{"scenario": "robot_failure"}` or `{"custom": {...}}`, plus `"strategy"` |
| GET | `/simulations`, `/simulations/{id}` | list / info |
| GET | `/simulations/{id}/state` | robots, tasks, blocked cells, map |
| POST | `/simulations/{id}/step` | advance `{"ticks": n}` |
| POST | `/simulations/{id}/run`, `/reset` | run to the end / restart |
| POST | `/simulations/{id}/events` | `robot_failure`, `robot_restore`, `block_cell`, `unblock_cell`, `add_task` |
| GET | `/simulations/{id}/events`, `/metrics` | event log, measured metrics |
| DELETE | `/simulations/{id}` | discard a run |
| POST | `/benchmarks` | baseline vs aegis on identical inputs (named and/or custom) |

Invalid input returns 404 (unknown run/robot/scenario), 409 (rejected by the simulation, e.g. blocking
a shelf or failing a dead robot) or 422 (malformed / out of range). Runs live in memory (max 50, oldest
evicted). There is no authentication or rate limiting, so do not expose it to the internet as-is.

```bash
curl -X POST localhost:8000/simulations -H 'content-type: application/json' \
  -d '{"strategy":"aegis","custom":{"width":30,"height":20,"robots":8,"seed":5}}'
curl -X POST localhost:8000/simulations/<run_id>/run
curl localhost:8000/simulations/<run_id>/metrics
```

## Layout
`simulation/` grid, robot, task, tick simulator - `algorithms/` A*, assignment, conflicts,
recovery - `services/` UI-facing service layer - `api/` FastAPI app - `evaluation/` metrics, scenarios, benchmarks -
`scenarios/` fixed JSON inputs - `ui/` Pygame app (+ a text view).

## Strategies (precise definitions)
- **baseline**: greedy initial assignment; robots reroute around obstacles; a robot whose
  next pickup is unreachable defers it to the back of its *own* queue; tasks owned by a
  failed robot are never reassigned (they stay unserved); no fleet-wide replanning.
- **aegis**: same initial assignment, plus after each failure/block/unblock/restore/new task
  it builds 4 candidate fleet-wide plans (keep-vs-rebalance x priority-vs-deadline order),
  scores them with the cost function in `algorithms/assignment.py`, validates the winner,
  and applies it atomically. Unreachable tasks are reported, never faked.

Both strategies share identical traffic rules: no shared cells, no edge swaps, no moves into blocked
cells (robots wait instead); a robot stuck behind another detours only if it has lower priority (higher
id), and standoffs are resolved by one robot backing off along a short parking path. These rules were
added after scaling up the grid exposed deadlocks and livelocks; regression tests are in
`tests/test_traffic.py`.

## Modelling choices to know about
- Cargo already picked up by a robot that fails is lost (`FAILED`), for both strategies.
- A failed robot stays in its cell as an obstacle.
- Pickup/delivery take zero ticks; movement is 1 cell per tick.
- `recovery_duration_ticks` = sum over disruptions of ticks until every task the
  disruption affected is delivered (unresolved disruptions are counted separately).
- Cost weights in `config.py` are untuned starting values.

## Limitations
- Synthetic aisle-and-shelf maps only; results do not generalize to real warehouses and make no safety claims.
- Traffic handling is heuristic, not proven deadlock-free. In a stress run of 320 undisturbed generated
  scenarios (8 sizes up to 60x40 with 20 robots, 20 seeds, both strategies) 318 completed every task and
  2 (one 45x30 / 16-robot seed, both strategies) stalled with 4 of 48 tasks undelivered. No run in 512
  (including random failures and blocked cells) had a collision or crashed.
- Cost weights in `config.py` are untuned starting values.
- Seeds only affect generated task placement; the simulator itself is deterministic.
