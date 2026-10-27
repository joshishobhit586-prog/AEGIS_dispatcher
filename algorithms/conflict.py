"""Conflict detection: movement conflicts and assignment validation."""
from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Set, Tuple

from algorithms.astar import manhattan
from simulation.robot import Robot
from simulation.task import Task, TaskStatus
from simulation.warehouse import Cell, Warehouse


def validate_assignment(robot: Robot, task: Task) -> Optional[str]:
    """Return an error string if giving `task` to `robot` is invalid."""
    if not robot.available:
        return f"robot {robot.robot_id} is unavailable"
    if task.status is not TaskStatus.PENDING:
        return f"task {task.task_id} is {task.status.value}, not PENDING"
    return None


def validate_plan(
    queues: Dict[str, List[str]],
    robots: Dict[str, Robot],
    tasks: Dict[str, Task],
    reassignable: Set[str],
) -> List[str]:
    """Check a whole recovery plan before it is applied. Empty list == valid."""
    errors: List[str] = []
    seen: Set[str] = set()
    for rid, queue in queues.items():
        robot = robots.get(rid)
        if robot is None:
            errors.append(f"unknown robot {rid}")
            continue
        if not robot.available and queue:
            errors.append(f"robot {rid} is unavailable but was given tasks")
        for tid in queue:
            if tid not in tasks:
                errors.append(f"unknown task {tid}")
            elif tid not in reassignable:
                errors.append(f"task {tid} ({tasks[tid].status.value}) may not be reassigned")
            if tid in seen:
                errors.append(f"task {tid} assigned more than once")
            seen.add(tid)
    return errors


def resolve_moves(
    positions: Dict[str, Cell],
    desired: Dict[str, Cell],
    warehouse: Warehouse,
) -> Tuple[Dict[str, Cell], Dict[str, str]]:
    """Decide which desired one-step moves are allowed this tick.

    Rejects: moves into blocked/shelf cells, non-adjacent moves, moves into a cell
    held by a robot that is not leaving, two robots entering the same cell
    (lower robot id wins), and head-on edge swaps. Rejected robots simply wait,
    which can in turn block others, so rejection is iterated to a fixed point.

    Returns (approved_moves, {robot_id: rejection_reason}).
    """
    approved = dict(desired)
    rejected: Dict[str, str] = {}

    for rid, target in list(approved.items()):
        if not warehouse.is_walkable(target):
            del approved[rid]
            rejected[rid] = "blocked_cell"
        elif manhattan(positions[rid], target) != 1:
            del approved[rid]
            rejected[rid] = "non_adjacent"

    changed = True
    while changed:
        changed = False
        stay_cells = {pos for rid, pos in positions.items() if rid not in approved}
        claims: Dict[Cell, str] = {}
        for rid in sorted(approved):
            target = approved[rid]
            reason = None
            if target in stay_cells:
                reason = "cell_occupied"
            elif target in claims:
                reason = "cell_contested"
            else:
                for other, other_target in approved.items():
                    if (
                        other != rid
                        and other_target == positions[rid]
                        and positions[other] == target
                    ):
                        reason = "edge_swap"
                        break
            if reason:
                del approved[rid]
                rejected[rid] = reason
                changed = True
                break
            claims[target] = rid
    return approved, rejected


def count_collisions(positions: Iterable[Cell], warehouse: Warehouse) -> int:
    """Count prohibited states: robot pairs sharing a cell, robots inside shelves."""
    seen: Dict[Cell, int] = {}
    collisions = 0
    for pos in positions:
        if warehouse.is_shelf(pos):
            collisions += 1
        collisions += seen.get(pos, 0)
        seen[pos] = seen.get(pos, 0) + 1
    return collisions
