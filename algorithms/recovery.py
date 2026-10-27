"""AEGIS recovery: build candidate fleet-wide plans, pick the cheapest feasible one.

Candidates
  keep_*       healthy robots keep their pending work; only orphaned/unassigned
               tasks are placed (least disruptive)
  rebalance_*  every not-yet-picked-up task is pooled and re-placed fleet-wide
Each is built with a priority-first or deadline-first ordering. The lowest-cost
candidate wins; ties go to the earlier (less disruptive) candidate.
Tasks already IN_PROGRESS are never reassigned. The plan is validated in full
and then applied atomically (all-or-nothing).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from algorithms.assignment import (
    DistanceOracle,
    build_plan,
    order_by_deadline,
    order_by_priority,
    robot_pending_ids,
)
from algorithms.conflict import validate_plan
from simulation.robot import Robot
from simulation.task import Task, TaskStatus
from simulation.warehouse import Warehouse

CANDIDATES = [
    ("keep_priority", "keep", order_by_priority),
    ("keep_deadline", "keep", order_by_deadline),
    ("rebalance_priority", "global", order_by_priority),
    ("rebalance_deadline", "global", order_by_deadline),
]


@dataclass
class RecoveryOutcome:
    status: str  # applied | partial | no_feasible_plan | nothing_to_do | rejected
    chosen: Optional[str] = None
    candidates: List[dict] = field(default_factory=list)
    reassigned: List[str] = field(default_factory=list)
    unassigned: Dict[str, str] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)


def recover(
    warehouse: Warehouse,
    robots: Dict[str, Robot],
    tasks: Dict[str, Task],
    now: int,
) -> RecoveryOutcome:
    extra = {r.position for r in robots.values() if not r.available}
    oracle = DistanceOracle(warehouse, extra)
    avail = {rid: r for rid, r in robots.items() if r.available}
    reassignable = sorted(
        tid for tid, t in tasks.items() if t.status in (TaskStatus.PENDING, TaskStatus.ASSIGNED)
    )
    if not reassignable:
        return RecoveryOutcome("nothing_to_do")

    plans = []
    for name, mode, order in CANDIDATES:
        if mode == "keep":
            base = {rid: robot_pending_ids(r, tasks) for rid, r in avail.items()}
        else:
            base = {}
        kept = {tid for q in base.values() for tid in q}
        pool = [tid for tid in reassignable if tid not in kept]
        plans.append(build_plan(name, pool, base, avail, tasks, oracle, now, order))

    best = min(plans, key=lambda p: p.cost)  # first minimum wins ties
    summaries = [
        {"name": p.name, "cost": round(p.cost, 2), "unserved": len(p.unassignable), **p.breakdown}
        for p in plans
    ]

    errors = validate_plan(best.queues, robots, tasks, set(reassignable))
    if errors:
        return RecoveryOutcome("rejected", best.name, summaries, errors=errors)

    reassigned = _apply(best.queues, robots, tasks, reassignable)

    served = sum(len(q) for q in best.queues.values())
    if best.unassignable and served == 0:
        status = "no_feasible_plan"
    elif best.unassignable:
        status = "partial"
    else:
        status = "applied"
    return RecoveryOutcome(status, best.name, summaries, reassigned, dict(best.unassignable))


def _apply(queues, robots, tasks, reassignable) -> List[str]:
    """Apply a pre-validated plan. Nothing here is expected to fail."""
    old_owner = {tid: tasks[tid].assigned_robot_id for tid in reassignable}
    for tid in reassignable:
        if tasks[tid].status is TaskStatus.ASSIGNED:
            tasks[tid].unassign()
    for rid, robot in robots.items():
        cur = tasks.get(robot.current_task_id) if robot.current_task_id else None
        if cur is not None and cur.status is not TaskStatus.IN_PROGRESS:
            robot.current_task_id = None
            robot.phase = None
            robot.clear_route()
        robot.queue = []
    for rid, queue in queues.items():
        robots[rid].queue = list(queue)
        for tid in queue:
            tasks[tid].assign(rid)
    return [
        tid
        for tid in reassignable
        if old_owner[tid] is not None and tasks[tid].assigned_robot_id != old_owner[tid]
    ]
