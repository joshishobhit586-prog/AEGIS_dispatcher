from evaluation.metrics import completion_rate, compute_metrics
from simulation.robot import Robot
from simulation.task import Task
from tests.helpers import make_sim

def test_hand_checked_single_delivery():
    # (0,0)->pickup(2,0): 2 steps, ->delivery(2,3): 3 steps => 5 moves, done on tick 4
    t = Task("T1", (2, 0), (2, 3), deadline=3)
    sim = make_sim("aegis", [t], robots=[Robot("R1", (0, 0))]).run()
    m = compute_metrics(sim)
    assert m["total_distance"] == 5
    assert sim.tasks["T1"].completion_tick == 4
    assert m["total_delay"] == 1 and m["completion_rate"] == 100.0 and m["collisions"] == 0

def test_empty_scenario_has_no_division_error():
    sim = make_sim("baseline", []).run()
    m = compute_metrics(sim)
    assert m["completion_rate"] == 100.0 and m["unserved_tasks"] == 0

def test_completion_rate():
    assert completion_rate(3, 4) == 75.0
    assert completion_rate(0, 0) == 100.0
