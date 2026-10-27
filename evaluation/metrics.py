"""Metric definitions. All timing is in simulation ticks unless suffixed _s."""
from __future__ import annotations

from simulation.task import TaskStatus


def completion_rate(completed: int, created: int) -> float:
    """Completed / created * 100. An empty task set counts as 100 (nothing missed)."""
    return 100.0 if created == 0 else completed / created * 100.0


def compute_metrics(sim) -> dict:
    tasks = list(sim.tasks.values())
    created = len(tasks)
    completed = sum(1 for t in tasks if t.status is TaskStatus.COMPLETED)
    resolved = [d for d in sim.disruptions if d["resolved_tick"] is not None]
    return {
        "scenario": sim.name,
        "strategy": sim.strategy,
        "seed": sim.seed,
        "ticks": sim.tick,
        "tasks_created": created,
        "tasks_completed": completed,
        "completion_rate": round(completion_rate(completed, created), 2),
        "unserved_tasks": created - completed,
        "total_distance": sum(r.distance_travelled for r in sim.robots.values()),
        "total_delay": sum(t.delay_ticks for t in tasks),
        "disruptions": len(sim.disruptions),
        # ticks from each disruption until all tasks it affected were delivered
        "recovery_duration_ticks": sum(d["resolved_tick"] - d["tick"] for d in resolved),
        "unresolved_disruptions": len(sim.disruptions) - len(resolved),
        "recovery_count": sim.recovery_count,
        "collisions": sim.collisions,
        "wait_ticks": sim.total_wait_ticks,
        "planning_time_s": round(sim.planning_time_s, 6),
    }
