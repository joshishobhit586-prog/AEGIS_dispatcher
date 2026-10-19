from algorithms.conflict import count_collisions, resolve_moves, validate_assignment, validate_plan
from simulation.robot import Robot
from simulation.task import Task
from simulation.warehouse import Warehouse

W = Warehouse(5, 1)

def test_same_cell_contested_lower_id_wins():
    ok, bad = resolve_moves({"R1": (0, 0), "R2": (2, 0)}, {"R1": (1, 0), "R2": (1, 0)}, W)
    assert ok == {"R1": (1, 0)} and bad["R2"] == "cell_contested"

def test_edge_swap_rejected():
    ok, bad = resolve_moves({"R1": (0, 0), "R2": (1, 0)}, {"R1": (1, 0), "R2": (0, 0)}, W)
    assert ok == {} and set(bad) == {"R1", "R2"}

def test_move_into_stationary_robot_rejected():
    ok, bad = resolve_moves({"R1": (0, 0), "R2": (1, 0)}, {"R1": (1, 0)}, W)
    assert ok == {} and bad["R1"] == "cell_occupied"

def test_following_a_leaving_robot_is_allowed():
    ok, bad = resolve_moves({"R1": (0, 0), "R2": (1, 0)}, {"R1": (1, 0), "R2": (2, 0)}, W)
    assert len(ok) == 2 and not bad

def test_cascade_when_leader_is_blocked():
    ok, bad = resolve_moves({"R1": (0, 0), "R2": (1, 0), "R3": (2, 0)},
                            {"R1": (1, 0), "R2": (2, 0)}, W)
    assert ok == {}

def test_blocked_cell_rejected():
    w = Warehouse(3, 1); w.block((1, 0))
    ok, bad = resolve_moves({"R1": (0, 0)}, {"R1": (1, 0)}, w)
    assert ok == {} and bad["R1"] == "blocked_cell"

def test_collision_counter():
    assert count_collisions([(0, 0), (0, 0), (1, 0)], W) == 1
    assert count_collisions([(0, 0), (1, 0)], W) == 0

def test_assignment_validation():
    r = Robot("R1", (0, 0)); k = Task("T1", (0, 0), (1, 0))
    assert validate_assignment(r, k) is None
    r.mark_unavailable()
    assert "unavailable" in validate_assignment(r, k)

def test_plan_validation_catches_duplicates_and_dead_robots():
    robots = {"R1": Robot("R1", (0, 0)), "R2": Robot("R2", (1, 0))}
    robots["R2"].mark_unavailable()
    tasks = {"T1": Task("T1", (0, 0), (1, 0))}
    errs = validate_plan({"R1": ["T1"], "R2": ["T1"]}, robots, tasks, {"T1"})
    assert any("more than once" in e for e in errs) and any("unavailable" in e for e in errs)
