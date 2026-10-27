"""Deterministic tick-based simulator.

Two strategies run on identical inputs:
  baseline  greedy initial assignment; robots reroute locally around obstacles
            and defer unreachable tasks within their OWN queue; tasks owned by a
            failed robot are never reassigned.
  aegis     same initial assignment, plus fleet-wide recovery (see
            algorithms/recovery.py) after failures, blocks, unblocks, restores
            and new tasks.

Tick order: events -> robot preparation (arrivals, routing) -> conflict-checked
movement -> arrivals -> bookkeeping.
"""
from __future__ import annotations

import time
from typing import Dict, List, Optional

from algorithms.assignment import (
    DistanceOracle,
    build_plan,
    order_by_priority,
    robot_pending_ids,
)
from algorithms.astar import find_path
from algorithms.conflict import count_collisions, resolve_moves, validate_assignment
from algorithms.recovery import recover
from config import MAX_TICKS, REPLAN_AFTER_WAIT_TICKS, STALL_LIMIT, STRATEGIES
from simulation.robot import (
    PHASE_TO_DELIVERY,
    PHASE_TO_PICKUP,
    Robot,
    RobotStatus,
)
from simulation.task import Task, TaskStatus
from simulation.warehouse import Cell, Warehouse

EVENT_TYPES = {"robot_failure", "robot_restore", "block_cell", "unblock_cell", "add_task"}


class Simulator:
    def __init__(
        self,
        warehouse: Warehouse,
        robots: List[Robot],
        tasks: List[Task],
        events: Optional[List[dict]] = None,
        strategy: str = "aegis",
        seed: int = 0,
        name: str = "adhoc",
        max_ticks: int = MAX_TICKS,
    ):
        if strategy not in STRATEGIES:
            raise ValueError(f"strategy must be one of {STRATEGIES}")
        self.warehouse = warehouse
        self.strategy = strategy
        self.seed = seed
        self.name = name
        self.max_ticks = max_ticks
        self.robots: Dict[str, Robot] = {}
        for r in robots:
            if r.robot_id in self.robots:
                raise ValueError(f"duplicate robot id {r.robot_id}")
            if not warehouse.is_walkable(r.position):
                raise ValueError(f"robot {r.robot_id} starts on a non-walkable cell")
            self.robots[r.robot_id] = r
        if len({r.position for r in robots}) != len(robots):
            raise ValueError("robots must start on distinct cells")
        self.tasks: Dict[str, Task] = {}
        for t in tasks:
            self._register_task(t)

        self._pending_events: List[dict] = []
        for ev in events or []:
            if ev.get("type") not in EVENT_TYPES:
                raise ValueError(f"unknown event type {ev.get('type')!r}")
            self._pending_events.append(dict(ev))
        self._pending_events.sort(key=lambda e: e["tick"])

        self.tick = 0
        self._started = False
        self._stall = 0
        self.event_log: List[dict] = []
        self.disruptions: List[dict] = []
        self.total_wait_ticks = 0
        self.collisions = 0
        self.rejected_moves = 0
        self.recovery_count = 0
        self.replans = 0
        self.planning_time_s = 0.0

    # ------------------------------------------------------------ helpers
    def _register_task(self, t: Task) -> None:
        if t.task_id in self.tasks:
            raise ValueError(f"duplicate task id {t.task_id}")
        for cell in (t.pickup, t.delivery):
            if not self.warehouse.is_walkable(cell):
                raise ValueError(f"task {t.task_id}: cell {cell} is not walkable")
        self.tasks[t.task_id] = t

    def _log(self, etype: str, description: str, **details) -> None:
        self.event_log.append(
            {"tick": self.tick, "type": etype, "description": description, "details": details}
        )

    def _unavailable_cells(self):
        return {r.position for r in self.robots.values() if not r.available}

    def _signature(self):
        return (
            tuple(r.position for r in self.robots.values()),
            tuple(t.status for t in self.tasks.values()),
        )

    # ---------------------------------------------------------- public API
    def inject_event(self, event: dict) -> None:
        """Schedule an event for the next step (used by UI / service layer)."""
        if event.get("type") not in EVENT_TYPES:
            raise ValueError(f"unknown event type {event.get('type')!r}")
        ev = dict(event)
        ev["tick"] = self.tick
        self._pending_events.append(ev)

    def is_finished(self) -> bool:
        if not self._started or self._pending_events:
            return False
        if all(t.is_terminal for t in self.tasks.values()):
            return True
        return not any(
            r.available and (r.current_task_id is not None or r.queue)
            for r in self.robots.values()
        )

    def run(self, max_ticks: Optional[int] = None) -> "Simulator":
        max_ticks = self.max_ticks if max_ticks is None else max_ticks
        while self.tick < max_ticks and not self.is_finished():
            self.step()
            if self.stalled:
                break
        return self

    def start(self) -> None:
        """Perform the initial assignment (idempotent)."""
        if not self._started:
            self._started = True
            self._initial_assignment()

    def apply_pending_events(self) -> bool:
        """Apply events due now without advancing time (manual UI actions)."""
        self.start()
        applied = self._apply_due_events()
        if applied:
            self._stall = 0
        return applied

    @property
    def stalled(self) -> bool:
        return self._stall >= STALL_LIMIT and not self._pending_events

    def step(self) -> None:
        before = self._signature()
        self.start()
        applied = self._apply_due_events()
        for rid in sorted(self.robots):
            self._prepare_robot(self.robots[rid])
        self._move_robots()
        for rid in sorted(self.robots):
            self._process_arrivals(self.robots[rid])
        self._update_disruptions()
        if self._signature() == before and not applied:
            self._stall += 1
        else:
            self._stall = 0
        self.tick += 1

    def snapshot(self) -> dict:
        return {
            "tick": self.tick,
            "strategy": self.strategy,
            "width": self.warehouse.width,
            "height": self.warehouse.height,
            "shelves": sorted(self.warehouse.shelves),
            "inventory": [{"cell": cell, "quantity": self.warehouse.inventory[cell]}
                          for cell in sorted(self.warehouse.shelves)],
            "blocked": sorted(self.warehouse.blocked),
            "robots": [
                {
                    "robot_id": r.robot_id,
                    "status": r.status.value,
                    "position": r.position,
                    "current_task_id": r.current_task_id,
                    "queue": list(r.queue),
                    "route": list(r.route[r.route_index:]) if r.route else [],
                }
                for r in self.robots.values()
            ],
            "tasks": [
                {
                    "task_id": t.task_id,
                    "status": t.status.value,
                    "assigned_robot_id": t.assigned_robot_id,
                    "priority": t.priority,
                    "pickup": t.pickup,
                    "delivery": t.delivery,
                    "deadline": t.deadline,
                }
                for t in self.tasks.values()
            ],
        }

    # ------------------------------------------------------------ assignment
    def _initial_assignment(self) -> None:
        ids = sorted(t.task_id for t in self.tasks.values() if t.status is TaskStatus.PENDING)
        self._assign_incremental(ids)
        self._log("initial_assignment", f"assigned {len(ids)} task(s)", strategy=self.strategy)

    def _assign_incremental(self, pool_ids: List[str]) -> None:
        oracle = DistanceOracle(self.warehouse, self._unavailable_cells())
        avail = {rid: r for rid, r in self.robots.items() if r.available}
        base = {rid: robot_pending_ids(r, self.tasks) for rid, r in avail.items()}
        plan = build_plan("greedy", pool_ids, base, avail, self.tasks, oracle, self.tick, order_by_priority)
        pool = set(pool_ids)
        for rid, queue in plan.queues.items():
            for tid in queue:
                if tid not in pool:
                    continue
                err = validate_assignment(self.robots[rid], self.tasks[tid])
                if err:
                    self._log("assignment_rejected", err, task_id=tid, robot_id=rid)
                    continue
                self.robots[rid].queue.append(tid)
                self.tasks[tid].assign(rid)
        for tid, reason in plan.unassignable.items():
            if tid in pool:
                self._log("task_unassignable", f"{tid}: {reason}", task_id=tid)

    def _run_recovery(self, trigger: str):
        t0 = time.perf_counter()
        outcome = recover(self.warehouse, self.robots, self.tasks, self.tick)
        self.planning_time_s += time.perf_counter() - t0
        if outcome.status == "nothing_to_do":
            return outcome
        self.recovery_count += 1
        self._log(
            "recovery",
            f"recovery after {trigger}: {outcome.status}"
            + (f", chose {outcome.chosen}" if outcome.chosen else ""),
            trigger=trigger,
            status=outcome.status,
            chosen=outcome.chosen,
            candidates=outcome.candidates,
            reassigned=outcome.reassigned,
            unassigned=outcome.unassigned,
            errors=outcome.errors,
        )
        for tid, reason in outcome.unassigned.items():
            self._log("task_unserved", f"{tid}: {reason}", task_id=tid)
        return outcome

    # ---------------------------------------------------------------- events
    def _apply_due_events(self) -> bool:
        due = [e for e in self._pending_events if e["tick"] <= self.tick]
        self._pending_events = [e for e in self._pending_events if e["tick"] > self.tick]
        for ev in due:
            handler = getattr(self, "_on_" + ev["type"])
            try:
                handler(ev)
            except (ValueError, KeyError) as exc:
                self._log("event_rejected", f"{ev['type']}: {exc}", event=ev)
        return bool(due)

    def _open_disruption(self, kind: str, affected, **details) -> dict:
        d = {
            "id": len(self.disruptions) + 1,
            "tick": self.tick,
            "type": kind,
            "affected": sorted(set(affected)),
            "resolved_tick": None,
            **details,
        }
        if not d["affected"]:
            d["resolved_tick"] = self.tick
        self.disruptions.append(d)
        return d

    def _invalidate_routes(self) -> set:
        """Drop routes that are no longer walkable; return affected task ids."""
        extra = self._unavailable_cells()
        affected = set()
        for r in self.robots.values():
            if r.available and r.route:
                remaining = r.route[r.route_index + 1:]
                if any(not self.warehouse.is_walkable(c, extra) for c in remaining):
                    r.clear_route()
                    if r.current_task_id:
                        affected.add(r.current_task_id)
        return affected

    def _unreachable_tasks(self) -> set:
        oracle = DistanceOracle(self.warehouse, self._unavailable_cells())
        avail = [r for r in self.robots.values() if r.available]
        out = set()
        for t in self.tasks.values():
            if t.status not in (TaskStatus.PENDING, TaskStatus.ASSIGNED):
                continue
            if oracle.dist(t.pickup, t.delivery) is None:
                out.add(t.task_id)
                continue
            owner = self.robots.get(t.assigned_robot_id) if t.assigned_robot_id else None
            sources = [owner.position] if owner and owner.available else [r.position for r in avail]
            if not any(oracle.dist(s, t.pickup) is not None for s in sources):
                out.add(t.task_id)
        return out

    def _on_robot_failure(self, ev: dict) -> None:
        robot = self.robots[ev["robot_id"]]
        if not robot.available:
            raise ValueError(f"robot {robot.robot_id} is already unavailable")
        affected = set()
        cur = self.tasks.get(robot.current_task_id) if robot.current_task_id else None
        if cur is not None:
            if cur.status is TaskStatus.IN_PROGRESS:
                cur.fail()  # cargo is stranded on the failed robot
                affected.add(cur.task_id)
                self._log("task_failed", f"{cur.task_id} stranded on {robot.robot_id}", task_id=cur.task_id)
            else:
                robot.queue.insert(0, cur.task_id)
        robot.current_task_id = None
        robot.phase = None
        affected |= set(robot.queue)
        robot.mark_unavailable()
        self._log("robot_failure", f"{robot.robot_id} failed at {robot.position}", robot_id=robot.robot_id)
        affected |= self._invalidate_routes()
        self._open_disruption("robot_failure", affected, robot_id=robot.robot_id)
        if self.strategy == "aegis":
            self._run_recovery(f"failure of {robot.robot_id}")

    def _on_robot_restore(self, ev: dict) -> None:
        robot = self.robots[ev["robot_id"]]
        if robot.available:
            raise ValueError(f"robot {robot.robot_id} is not unavailable")
        robot.restore()
        self._log("robot_restore", f"{robot.robot_id} restored", robot_id=robot.robot_id)
        if self.strategy == "aegis":
            self._run_recovery(f"restore of {robot.robot_id}")

    def _on_block_cell(self, ev: dict) -> None:
        cell = tuple(ev["cell"])
        newly = self.warehouse.block(cell)
        if not newly:
            raise ValueError(f"{cell} is already blocked")
        self._log("block_cell", f"cell {cell} blocked", cell=cell)
        affected = self._invalidate_routes() | self._unreachable_tasks()
        self._open_disruption("block_cell", affected, cell=cell)
        if self.strategy == "aegis":
            self._run_recovery(f"block at {cell}")

    def _on_unblock_cell(self, ev: dict) -> None:
        cell = tuple(ev["cell"])
        if not self.warehouse.unblock(cell):
            raise ValueError(f"{cell} was not blocked")
        self._log("unblock_cell", f"cell {cell} unblocked", cell=cell)
        if self.strategy == "aegis":
            self._run_recovery(f"unblock at {cell}")

    def _on_add_task(self, ev: dict) -> None:
        spec = ev["task"]
        task = Task(
            task_id=spec["id"],
            pickup=tuple(spec["pickup"]),
            delivery=tuple(spec["delivery"]),
            priority=spec.get("priority", 1),
            created_tick=self.tick,
            deadline=spec.get("deadline"),
        )
        self._register_task(task)
        self._log("add_task", f"new task {task.task_id} (priority {task.priority})", task_id=task.task_id)
        if self.strategy == "aegis":
            self._run_recovery(f"new task {task.task_id}")
        else:
            self._assign_incremental([task.task_id])

    def _nearest_shelf(self, cell: Cell):
        """Associate a floor pickup/delivery point with its nearest shelf."""
        if not self.warehouse.shelves:
            return None
        return min(self.warehouse.shelves,
                   key=lambda shelf: (abs(shelf[0] - cell[0]) + abs(shelf[1] - cell[1]), shelf))

    # ------------------------------------------------------- robot behaviour
    def _process_arrivals(self, robot: Robot) -> None:
        while robot.current_task_id is not None and robot.available:
            task = self.tasks[robot.current_task_id]
            if robot.phase == PHASE_TO_PICKUP and robot.position == task.pickup:
                source_shelf = self._nearest_shelf(task.pickup)
                stock_details = {}
                if source_shelf is not None:
                    stock = self.warehouse.inventory[source_shelf]
                    if stock > 0:
                        self.warehouse.inventory[source_shelf] = stock - 1
                    stock_details = {"shelf": source_shelf,
                                     "quantity": self.warehouse.inventory[source_shelf],
                                     "stock_changed": stock > 0}
                task.start(self.tick)
                robot.phase = PHASE_TO_DELIVERY
                robot.clear_route()
                self._log("pickup", f"{robot.robot_id} picked up {task.task_id}",
                          task_id=task.task_id, **stock_details)
            elif robot.phase == PHASE_TO_DELIVERY and robot.position == task.delivery:
                destination_shelf = self._nearest_shelf(task.delivery)
                stock_details = {}
                if destination_shelf is not None:
                    self.warehouse.inventory[destination_shelf] += 1
                    stock_details = {"shelf": destination_shelf,
                                     "quantity": self.warehouse.inventory[destination_shelf],
                                     "stock_changed": True}
                task.complete(self.tick)
                robot.current_task_id = None
                robot.phase = None
                robot.clear_route()
                self._log("delivery", f"{robot.robot_id} delivered {task.task_id}",
                          task_id=task.task_id, **stock_details)
            else:
                break

    def _prepare_robot(self, robot: Robot) -> None:
        if not robot.available:
            return
        extra = self._unavailable_cells()
        attempts = len(robot.queue) + 1
        if robot.route is not None and robot.next_cell() is None:
            robot.clear_route()  # finished a parking detour: re-plan the real route
        while True:
            self._process_arrivals(robot)
            if robot.current_task_id is None:
                if not robot.queue:
                    robot.status = RobotStatus.IDLE
                    return
                robot.current_task_id = robot.queue.pop(0)
                robot.phase = PHASE_TO_PICKUP
                robot.clear_route()
                continue
            if robot.route is not None:
                return
            task = self.tasks[robot.current_task_id]
            target = task.pickup if robot.phase == PHASE_TO_PICKUP else task.delivery
            route = find_path(self.warehouse, robot.position, target, extra)
            if route is not None:
                robot.set_route(route)
                return
            if robot.phase == PHASE_TO_PICKUP and robot.queue and attempts > 0:
                attempts -= 1  # local fallback: defer within own queue
                robot.queue.append(robot.current_task_id)
                robot.current_task_id = None
                robot.phase = None
                continue
            return  # no route: robot waits and retries next tick

    def _move_robots(self) -> None:
        positions = {rid: r.position for rid, r in self.robots.items()}
        desired = {
            rid: r.next_cell()
            for rid, r in self.robots.items()
            if r.available and r.next_cell() is not None
        }
        approved, rejected = resolve_moves(positions, desired, self.warehouse)
        self.rejected_moves += sum(1 for v in rejected.values() if v in ("blocked_cell", "non_adjacent"))

        for rid, r in self.robots.items():
            if not r.available:
                continue
            if rid in approved:
                r.advance()
                r.status = RobotStatus.MOVING
                r.wait_ticks = 0
            elif r.current_task_id is not None:
                r.status = RobotStatus.WAITING
                r.wait_ticks += 1
                self.total_wait_ticks += 1
            elif rid in rejected:
                r.status = RobotStatus.IDLE   # an idle robot stuck on a parking route
                r.wait_ticks += 1
            else:
                r.status = RobotStatus.IDLE
                r.wait_ticks = 0

        yielded_for = self._yield_blockers(rejected, desired)

        # Detour around robots that keep blocking the way.
        for rid, reason in rejected.items():
            r = self.robots[rid]
            if not r.route or rid in yielded_for:
                continue
            hard_reject = reason in ("blocked_cell", "non_adjacent")
            if not hard_reject:
                if r.wait_ticks < REPLAN_AFTER_WAIT_TICKS:
                    continue
                # Priority rule: against a working robot, only the lower-priority
                # (higher id) robot detours. Two robots detouring in the same tick
                # take opposite sides and meet head-on again (livelock).
                blocker = next((o for o in self.robots.values() if o.position == desired[rid]), None)
                working = (blocker is not None and blocker.available
                           and (blocker.current_task_id is not None or blocker.queue))
                if working and rid < blocker.robot_id:
                    continue
            others = {o.position for oid, o in self.robots.items() if oid != rid}
            new = find_path(self.warehouse, r.position, r.route[-1], others)
            if new is not None and len(new) > 1:
                r.set_route(new)
                self.replans += 1
            elif hard_reject:
                r.clear_route()

        self.collisions += count_collisions((r.position for r in self.robots.values()), self.warehouse)

    def _yield_blockers(self, rejected: Dict[str, str], desired: Dict[str, Cell]) -> set:
        """Resolve standoffs by making ONE robot back off along a short parking path.

        An idle blocker always yields. If the blocker is itself working, it yields
        only when both have been stuck a while and the requester has the lower id
        (a deterministic tie-break, so two robots never yield to each other).
        Returns the ids of robots that were yielded to (they keep their route this
        tick instead of planning a detour through the parking spot).
        """
        yielded_for = set()
        for rid, reason in sorted(rejected.items()):
            r = self.robots[rid]
            if reason not in ("cell_occupied", "edge_swap") or not r.route:
                continue
            target = desired[rid]
            blocker = next((o for o in self.robots.values() if o.position == target), None)
            if blocker is None or not blocker.available or blocker.robot_id == rid:
                continue
            idle = blocker.current_task_id is None and not blocker.queue
            keep_clear = set(r.route[r.route_index:]) | {target}
            if idle:
                if r.wait_ticks >= REPLAN_AFTER_WAIT_TICKS:
                    path = self._parking_path(blocker, keep_clear, avoid=r.position)
                    if path:
                        self._start_yield(blocker, path, rid)
                        yielded_for.add(rid)
                continue
            if blocker.status is not RobotStatus.WAITING:
                continue  # it is still moving; just wait
            # 1) lower-id requester asks the (stuck) blocker to back off
            if r.wait_ticks >= 2 * REPLAN_AFTER_WAIT_TICKS and rid < blocker.robot_id:
                path = self._parking_path(blocker, keep_clear, avoid=r.position)
                if path:
                    self._start_yield(blocker, path, rid)
                    yielded_for.add(rid)
                    continue
            # 2) blocker could not yield (e.g. boxed in): after a longer wait the
            #    requester backs off itself; the per-robot offset breaks symmetry
            rank = sorted(self.robots).index(rid)
            if r.wait_ticks >= 4 * REPLAN_AFTER_WAIT_TICKS + rank:
                clear = {blocker.position} | (set(blocker.route[blocker.route_index:]) if blocker.route else set())
                path = self._parking_path(r, clear, avoid=blocker.position)
                if path:
                    self._start_yield(r, path, blocker.robot_id)
                    yielded_for.add(rid)
        return yielded_for

    def _start_yield(self, robot: Robot, path, for_robot: str) -> None:
        robot.set_route(path)
        self._log("yield", f"{robot.robot_id} backs off to {path[-1]} for {for_robot}",
                  robot_id=robot.robot_id, for_robot=for_robot)

    def _parking_path(self, robot: Robot, keep_clear: set, avoid=None, max_depth: int = 14):
        """Shortest path to the nearest free cell that is off the requester's route.

        Other idle robots are passable (they can be asked to move in turn) but are
        never a destination; working and failed robots, and `avoid` (the requester's
        cell), are walls.
        """
        hard, soft = set(), set()
        for o in self.robots.values():
            if o is robot:
                continue
            idle = o.available and o.current_task_id is None and not o.queue
            (soft if idle else hard).add(o.position)
        if avoid is not None:
            soft.discard(avoid)
            hard.add(avoid)
        frontier, parent = [robot.position], {robot.position: None}
        for _ in range(max_depth):
            nxt_frontier = []
            for cell in frontier:
                for nb in self.warehouse.neighbors(cell, hard):
                    if nb in parent:
                        continue
                    parent[nb] = cell
                    if nb not in keep_clear and nb not in soft:
                        path = [nb]
                        while parent[path[-1]] is not None:
                            path.append(parent[path[-1]])
                        return path[::-1]
                    nxt_frontier.append(nb)
            frontier = nxt_frontier
            if not frontier:
                break
        return None

    def _update_disruptions(self) -> None:
        for d in self.disruptions:
            if d["resolved_tick"] is None and all(
                self.tasks[t].status is TaskStatus.COMPLETED for t in d["affected"]
            ):
                d["resolved_tick"] = self.tick
