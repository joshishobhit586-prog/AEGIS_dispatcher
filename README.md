# AEGIS - Adaptive Multi-Robot Mission Recovery

Software-only warehouse fleet simulation. When a robot fails, a corridor is blocked,
or an urgent delivery appears, AEGIS replans routes and reassigns unfinished tasks
across the fleet, and is compared against a baseline that only reroutes locally.

**Status:** Milestones 1-5 (UI part) done: grid, A*, robots/tasks, disruptions, recovery,
baseline, metrics, benchmarks, Pygame UI. Not built yet: SQLite persistence, charts,
optional FastAPI.

## Setup
```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
python -m pip install -r requirements.txt
python -m pytest                                    # 65 tests
python main.py                                      # Pygame UI
python main.py --cli --scenario scenarios/robot_failure.json --strategy aegis --log
python main.py --benchmark                          # writes results/benchmark_results.{csv,json}
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

## Layout
`simulation/` grid, robot, task, tick simulator - `algorithms/` A*, assignment, conflicts,
recovery - `services/` UI-facing API - `evaluation/` metrics, scenarios, benchmarks -
`scenarios/` fixed JSON inputs - `ui/` Pygame app (+ a text view).

## Strategies (precise definitions)
- **baseline**: greedy initial assignment; robots reroute around obstacles; a robot whose
  next pickup is unreachable defers it to the back of its *own* queue; tasks owned by a
  failed robot are never reassigned (they stay unserved); no fleet-wide replanning.
- **aegis**: same initial assignment, plus after each failure/block/unblock/restore/new task
  it builds 4 candidate fleet-wide plans (keep-vs-rebalance x priority-vs-deadline order),
  scores them with the cost function in `algorithms/assignment.py`, validates the winner,
  and applies it atomically. Unreachable tasks are reported, never faked.

Both use identical idle-robot "step aside" behaviour and the same conflict rules
(no shared cells, no edge swaps, no moves into blocked cells; robots wait instead).

## Modelling choices to know about
- Cargo already picked up by a robot that fails is lost (`FAILED`), for both strategies.
- A failed robot stays in its cell as an obstacle.
- Pickup/delivery take zero ticks; movement is 1 cell per tick.
- `recovery_duration_ticks` = sum over disruptions of ticks until every task the
  disruption affected is delivered (unresolved disruptions are counted separately).
- Cost weights in `config.py` are untuned starting values.

## Limitations
Small synthetic 17x10 map, one fixed scenario family, deterministic (no random seeds used yet).
Results do not generalize to real warehouses and make no safety claims.
