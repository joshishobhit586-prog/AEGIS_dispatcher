import pytest
from simulation.task import InvalidTransition, Task, TaskStatus

def t(**kw):
    return Task("T1", (0, 0), (1, 1), **kw)

def test_full_lifecycle():
    k = t(deadline=5)
    k.assign("R1"); k.start(2); k.complete(9)
    assert k.status is TaskStatus.COMPLETED and k.delay_ticks == 4

def test_unassign_returns_to_pending():
    k = t(); k.assign("R1"); k.unassign()
    assert k.status is TaskStatus.PENDING and k.assigned_robot_id is None

@pytest.mark.parametrize("bad", ["start", "complete", "unassign"])
def test_invalid_transitions_from_pending(bad):
    k = t()
    with pytest.raises(InvalidTransition):
        getattr(k, bad)(0) if bad != "unassign" else k.unassign()

def test_completed_task_cannot_be_reassigned():
    k = t(); k.assign("R1"); k.start(0); k.complete(1)
    with pytest.raises(InvalidTransition):
        k.assign("R2")

def test_in_progress_cannot_be_unassigned():
    k = t(); k.assign("R1"); k.start(0)
    with pytest.raises(InvalidTransition):
        k.unassign()
