from algorithms.recovery import recover
from simulation.robot import Robot
from simulation.task import Task, TaskStatus
from simulation.warehouse import Warehouse
from tests.helpers import make_sim

def tasks():
    return [Task(f"T{i}", (i, 2), (i, 3)) for i in range(1, 7)]

FAIL = [{"tick": 1, "type": "robot_failure", "robot_id": "R1"}]

def test_aegis_reassigns_after_failure():
    sim = make_sim("aegis", tasks(), FAIL).run()
    st = [t.status for t in sim.tasks.values()]
    failed = st.count(TaskStatus.FAILED)  # only cargo already on R1 can be lost
    assert failed <= 1 and st.count(TaskStatus.COMPLETED) == 6 - failed
    assert sim.recovery_count >= 1 and sim.collisions == 0

def test_baseline_strands_failed_robots_tasks():
    base = make_sim("baseline", tasks(), FAIL).run()
    aegis = make_sim("aegis", tasks(), FAIL).run()
    done = lambda s: sum(t.status is TaskStatus.COMPLETED for t in s.tasks.values())
    assert done(aegis) > done(base)

def test_unavailable_robot_receives_no_new_tasks():
    sim = make_sim("aegis", tasks(), FAIL)
    sim.run()
    assert sim.robots["R1"].queue == []

def test_unreachable_task_reported_not_completed():
    layout = ["...#....", "...#....", "...#....", "...#...."]
    ts = [Task("T1", (6, 1), (7, 1)), Task("T2", (1, 1), (2, 1))]
    sim = make_sim("aegis", ts, robots=[Robot("R1", (0, 0))], layout=layout).run()
    assert sim.tasks["T2"].status is TaskStatus.COMPLETED
    assert sim.tasks["T1"].status is TaskStatus.PENDING
    assert any(e["type"] == "task_unassignable" for e in sim.event_log)

def test_no_feasible_recovery_keeps_state_consistent():
    ev = [{"tick": 0, "type": "robot_failure", "robot_id": "R1"},
          {"tick": 0, "type": "robot_failure", "robot_id": "R2"}]
    sim = make_sim("aegis", tasks(), ev).run()
    assert all(t.status is TaskStatus.PENDING and t.assigned_robot_id is None for t in sim.tasks.values())
    rec = [e for e in sim.event_log if e["type"] == "recovery"][-1]
    assert rec["details"]["status"] == "no_feasible_plan"

def test_blocked_corridor_triggers_replan_and_completes():
    ev = [{"tick": 2, "type": "block_cell", "cell": [3, 1]}]
    sim = make_sim("aegis", tasks(), ev).run()
    assert sum(t.status is TaskStatus.COMPLETED for t in sim.tasks.values()) == 6 and sim.collisions == 0

def test_recover_never_duplicates_assignments():
    sim = make_sim("aegis", tasks(), FAIL)
    for _ in range(3):
        sim.step()
    owners = [tid for r in sim.robots.values() for tid in r.queue + ([r.current_task_id] if r.current_task_id else [])]
    assert len(owners) == len(set(owners))

def test_recover_on_already_feasible_state_keeps_assignment():
    robots = {"R1": Robot("R1", (0, 0))}
    ts = {"T1": Task("T1", (1, 0), (2, 0))}
    ts["T1"].assign("R1"); robots["R1"].queue = ["T1"]
    out = recover(Warehouse(4, 1), robots, ts, 0)
    assert out.status == "applied" and robots["R1"].queue == ["T1"]
