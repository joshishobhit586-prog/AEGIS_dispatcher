"""Task model with an explicit, validated lifecycle."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from simulation.warehouse import Cell


class TaskStatus(str, Enum):
    PENDING = "PENDING"
    ASSIGNED = "ASSIGNED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"  # cargo stranded on a failed robot; terminal


class InvalidTransition(ValueError):
    pass


_ALLOWED = {
    TaskStatus.PENDING: {TaskStatus.ASSIGNED},
    TaskStatus.ASSIGNED: {TaskStatus.PENDING, TaskStatus.IN_PROGRESS},
    TaskStatus.IN_PROGRESS: {TaskStatus.COMPLETED, TaskStatus.FAILED},
    TaskStatus.COMPLETED: set(),
    TaskStatus.FAILED: set(),
}


@dataclass
class Task:
    task_id: str
    pickup: Cell
    delivery: Cell
    priority: int = 1
    created_tick: int = 0
    deadline: Optional[int] = None
    status: TaskStatus = TaskStatus.PENDING
    assigned_robot_id: Optional[str] = None
    start_tick: Optional[int] = None
    completion_tick: Optional[int] = None

    def __post_init__(self):
        self.pickup = (int(self.pickup[0]), int(self.pickup[1]))
        self.delivery = (int(self.delivery[0]), int(self.delivery[1]))

    def _move(self, new: TaskStatus) -> None:
        if new not in _ALLOWED[self.status]:
            raise InvalidTransition(
                f"task {self.task_id}: {self.status.value} -> {new.value} is not allowed"
            )
        self.status = new

    def assign(self, robot_id: str) -> None:
        self._move(TaskStatus.ASSIGNED)
        self.assigned_robot_id = robot_id

    def unassign(self) -> None:
        self._move(TaskStatus.PENDING)
        self.assigned_robot_id = None

    def start(self, tick: int) -> None:
        self._move(TaskStatus.IN_PROGRESS)
        self.start_tick = tick

    def complete(self, tick: int) -> None:
        self._move(TaskStatus.COMPLETED)
        self.completion_tick = tick

    def fail(self) -> None:
        self._move(TaskStatus.FAILED)

    @property
    def is_terminal(self) -> bool:
        return self.status in (TaskStatus.COMPLETED, TaskStatus.FAILED)

    @property
    def delay_ticks(self) -> int:
        """Lateness beyond the deadline for a completed task (0 otherwise)."""
        if self.status is TaskStatus.COMPLETED and self.deadline is not None:
            return max(0, self.completion_tick - self.deadline)
        return 0
