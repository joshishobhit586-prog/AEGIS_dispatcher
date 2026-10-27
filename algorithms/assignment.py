"""Greedy task assignment and plan scoring.

Method implemented: greedy lowest-marginal-cost assignment (one task at a time,
in a chosen order), then a transparent whole-plan cost:

  total = DISTANCE_WEIGHT   * travel_steps
        + DELAY_WEIGHT      * total_delay_ticks
        + CONGESTION_WEIGHT * (longest_queue - shortest_queue)
        + PRIORITY_WEIGHT   * sum(priority * delay_ticks)
        + UNSERVED_PENALTY  * tasks_that_could_not_be_assigned
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from algorithms.astar import find_path
from config import (
    CONGESTION_WEIGHT,
    DELAY_WEIGHT,
    DISTANCE_WEIGHT,
    PRIORITY_WEIGHT,
    UNSERVED_PENALTY,
)
from simulation.robot import Robot
from simulation.task import Task, TaskStatus
from simulation.warehouse import Cell, Warehouse

INF = float("inf")
OrderFn = Callable[[List[str], Dict[str, Task]], List[str]]


class DistanceOracle:
    """Cached shortest-path lengths on the current map (None == unreachable)."""

    def __init__(self, warehouse: Warehouse, extra_blocked=()):
        self.warehouse = warehouse
        self.extra = frozenset(extra_blocked)
        self._cache: Dict[Tuple[Cell, Cell], Optional[int]] = {}

    def dist(self, a: Cell, b: Cell) -> Optional[int]:
        key = (a, b)
        if key not in self._cache:
            path = find_path(self.warehouse, a, b, self.extra)
            self._cache[key] = None if path is None else len(path) - 1
        return self._cache[key]


@dataclass
class Plan:
    name: str
    queues: Dict[str, List[str]]
    unassignable: Dict[str, str] = field(default_factory=dict)
    cost: float = 0.0
    breakdown: Dict[str, float] = field(default_factory=dict)


@dataclass
class QueueEval:
    travel: int
    completions: Dict[str, int]
    feasible_count: int
    end_pos: Cell
    end_time: int


def order_by_priority(ids: List[str], tasks: Dict[str, Task]) -> List[str]:
    return sorted(
        ids,
        key=lambda i: (-tasks[i].priority, tasks[i].deadline if tasks[i].deadline is not None else INF, i),
    )


def order_by_deadline(ids: List[str], tasks: Dict[str, Task]) -> List[str]:
    return sorted(
        ids,
        key=lambda i: (tasks[i].deadline if tasks[i].deadline is not None else INF, -tasks[i].priority, i),
    )


def robot_pending_ids(robot: Robot, tasks: Dict[str, Task]) -> List[str]:
    """Tasks a robot owns but has not picked up yet (current-if-not-started + queue)."""
    ids: List[str] = []
    if robot.current_task_id is not None:
        cur = tasks[robot.current_task_id]
        if cur.status is TaskStatus.ASSIGNED:
            ids.append(cur.task_id)
    return ids + list(robot.queue)


def robot_projection(robot: Robot, tasks: Dict[str, Task], oracle: DistanceOracle, now: int):
    """(position, tick) at which the robot is free for queued work; None if stuck."""
    pos, t = robot.position, now
    if robot.current_task_id is not None:
        cur = tasks[robot.current_task_id]
        if cur.status is TaskStatus.IN_PROGRESS:
            d = oracle.dist(pos, cur.delivery)
            if d is None:
                return None
            pos, t = cur.delivery, now + d
    return pos, t


def evaluate_queue(start_pos, start_time, ids, tasks, oracle) -> QueueEval:
    pos, t, travel, n = start_pos, start_time, 0, 0
    completions: Dict[str, int] = {}
    for tid in ids:
        task = tasks[tid]
        d1 = oracle.dist(pos, task.pickup)
        d2 = oracle.dist(task.pickup, task.delivery)
        if d1 is None or d2 is None:
            break
        t += d1 + d2
        travel += d1 + d2
        pos = task.delivery
        completions[tid] = t
        n += 1
    return QueueEval(travel, completions, n, pos, t)


def build_plan(
    name: str,
    pool_ids: List[str],
    base_queues: Dict[str, List[str]],
    robots: Dict[str, Robot],
    tasks: Dict[str, Task],
    oracle: DistanceOracle,
    now: int,
    order: OrderFn,
) -> Plan:
    """Keep `base_queues` (as far as they stay feasible), then greedily place the pool."""
    queues: Dict[str, List[str]] = {}
    state: Dict[str, Optional[Tuple[Cell, int]]] = {}
    displaced: List[str] = []
    for rid in sorted(robots):
        proj = robot_projection(robots[rid], tasks, oracle, now)
        base = list(base_queues.get(rid, []))
        if proj is None:
            queues[rid], state[rid] = [], None
            displaced.extend(base)
            continue
        ev = evaluate_queue(proj[0], proj[1], base, tasks, oracle)
        queues[rid] = base[: ev.feasible_count]
        displaced.extend(base[ev.feasible_count:])
        state[rid] = (ev.end_pos, ev.end_time)

    unassignable: Dict[str, str] = {}
    for tid in order(list(dict.fromkeys(list(pool_ids) + displaced)), tasks):
        task = tasks[tid]
        best = None
        for rid in sorted(robots):
            if state[rid] is None:
                continue
            pos, t = state[rid]
            d1 = oracle.dist(pos, task.pickup)
            d2 = oracle.dist(task.pickup, task.delivery)
            if d1 is None or d2 is None:
                continue
            finish = t + d1 + d2
            late = max(0, finish - task.deadline) if task.deadline is not None else 0
            score = (
                DISTANCE_WEIGHT * (d1 + d2)
                + DELAY_WEIGHT * late
                + PRIORITY_WEIGHT * task.priority * late
                + CONGESTION_WEIGHT * len(queues[rid])
            )
            if best is None or score < best[0]:
                best = (score, rid, finish)
        if best is None:
            unassignable[tid] = "no available robot can reach the pickup and delivery cells"
        else:
            _, rid, finish = best
            queues[rid].append(tid)
            state[rid] = (task.delivery, finish)

    plan = Plan(name, queues, unassignable)
    score_plan(plan, robots, tasks, oracle, now)
    return plan


def score_plan(plan: Plan, robots, tasks, oracle, now) -> None:
    dist = delay = prio = 0
    lens: List[int] = []
    for rid, queue in plan.queues.items():
        proj = robot_projection(robots[rid], tasks, oracle, now)
        if proj is None:
            continue
        ev = evaluate_queue(proj[0], proj[1], queue, tasks, oracle)
        dist += ev.travel
        for tid, done in ev.completions.items():
            task = tasks[tid]
            late = max(0, done - task.deadline) if task.deadline is not None else 0
            delay += late
            prio += task.priority * late
        lens.append(len(queue))
    congestion = (max(lens) - min(lens)) if lens else 0
    unserved = len(plan.unassignable)
    plan.breakdown = {
        "distance": dist,
        "delay": delay,
        "congestion": congestion,
        "priority_penalty": prio,
        "unserved": unserved,
    }
    plan.cost = (
        DISTANCE_WEIGHT * dist
        + DELAY_WEIGHT * delay
        + CONGESTION_WEIGHT * congestion
        + PRIORITY_WEIGHT * prio
        + UNSERVED_PENALTY * unserved
    )
