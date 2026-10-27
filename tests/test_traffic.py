"""Regression tests for standoffs/livelocks found while scaling up the grid."""
import pytest

from evaluation.generator import generate_scenario
from evaluation.metrics import compute_metrics
from evaluation.scenarios import build_simulator
from simulation.robot import Robot
from simulation.task import Task, TaskStatus
from tests.helpers import make_sim


def test_head_on_in_one_wide_corridor_with_side_pocket():
    layout = [".......", "###.###"]          # the only passing place is (3, 1)
    tasks = [Task("T1", (1, 0), (6, 0)), Task("T2", (5, 0), (0, 0))]
    sim = make_sim("aegis", tasks, robots=[Robot("R1", (0, 0)), Robot("R2", (6, 0))], layout=layout).run()
    assert all(t.status is TaskStatus.COMPLETED for t in sim.tasks.values())
    assert sim.collisions == 0


@pytest.mark.parametrize("args", [
    (9, 7, 4, 12, 1),     # dead-end aisle packed with idle robots
    (9, 7, 4, 12, 3),     # corner pocket: three robots want each other's cells
    (17, 10, 6, 18, 5),   # idle robots queued down a one-wide column
    (25, 16, 5, 15, 5),   # symmetric head-on pair that used to detour forever
    (33, 22, 8, 24, 1),   # two robots each other's delivery cell in a bottom aisle
])
@pytest.mark.parametrize("strategy", ["baseline", "aegis"])
def test_generated_scenarios_that_used_to_deadlock(args, strategy):
    w, h, r, t, seed = args
    m = compute_metrics(build_simulator(generate_scenario(w, h, r, t, seed=seed), strategy).run())
    assert m["unserved_tasks"] == 0 and m["collisions"] == 0
