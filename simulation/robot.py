"""Robot model. State changes go through small, controlled methods."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

from simulation.warehouse import Cell


class RobotStatus(str, Enum):
    IDLE = "IDLE"
    MOVING = "MOVING"
    WAITING = "WAITING"
    UNAVAILABLE = "UNAVAILABLE"


PHASE_TO_PICKUP = "to_pickup"
PHASE_TO_DELIVERY = "to_delivery"


@dataclass
class Robot:
    robot_id: str
    position: Cell
    status: RobotStatus = RobotStatus.IDLE
    queue: List[str] = field(default_factory=list)  # waiting task ids (excludes current)
    current_task_id: Optional[str] = None
    phase: Optional[str] = None
    route: Optional[List[Cell]] = None
    route_index: int = 0
    wait_ticks: int = 0
    distance_travelled: int = 0

    def __post_init__(self):
        self.position = (int(self.position[0]), int(self.position[1]))

    @property
    def available(self) -> bool:
        return self.status is not RobotStatus.UNAVAILABLE

    def set_route(self, route: List[Cell]) -> None:
        if not route or tuple(route[0]) != self.position:
            raise ValueError("route must start at the robot's current position")
        self.route = [tuple(c) for c in route]
        self.route_index = 0

    def clear_route(self) -> None:
        self.route = None
        self.route_index = 0

    def next_cell(self) -> Optional[Cell]:
        if self.route is None or self.route_index >= len(self.route) - 1:
            return None
        return self.route[self.route_index + 1]

    def advance(self) -> None:
        nxt = self.next_cell()
        if nxt is None:
            raise ValueError("no next cell on route")
        self.route_index += 1
        self.position = nxt
        self.distance_travelled += 1

    def mark_unavailable(self) -> None:
        self.status = RobotStatus.UNAVAILABLE
        self.clear_route()
        self.wait_ticks = 0

    def restore(self) -> None:
        if self.status is RobotStatus.UNAVAILABLE:
            self.status = RobotStatus.IDLE
