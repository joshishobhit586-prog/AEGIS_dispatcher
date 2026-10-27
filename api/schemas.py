"""Pydantic request/response models (also drive the OpenAPI docs at /docs)."""
from __future__ import annotations

from typing import Annotated, Any, Dict, List, Literal, Optional, Tuple, Union

from pydantic import BaseModel, Field, model_validator

from evaluation import generator as gen

Cell = Tuple[int, int]


# ----------------------------------------------------------------- requests
class RobotEvent(BaseModel):
    type: Literal["robot_failure", "robot_restore"]
    robot_id: str = Field(min_length=1, max_length=32)


class CellEvent(BaseModel):
    type: Literal["block_cell", "unblock_cell"]
    cell: Cell


class TaskSpec(BaseModel):
    id: str = Field(min_length=1, max_length=32)
    pickup: Cell
    delivery: Cell
    priority: int = Field(1, ge=1, le=10)
    deadline: Optional[int] = Field(None, ge=0)

    @model_validator(mode="after")
    def _distinct(self):
        if self.pickup == self.delivery:
            raise ValueError("pickup and delivery must differ")
        return self


class AddTaskEvent(BaseModel):
    type: Literal["add_task"]
    task: TaskSpec


EventRequest = Annotated[Union[RobotEvent, CellEvent, AddTaskEvent], Field(discriminator="type")]


class ScheduledEvent(BaseModel):
    """An event that fires at a given tick of a generated scenario."""
    tick: int = Field(ge=0, le=5000)
    event: EventRequest


class CustomConfig(BaseModel):
    """Generate a warehouse: you choose the grid size, robots and tasks."""
    width: int = Field(17, ge=gen.MIN_WIDTH, le=gen.MAX_WIDTH)
    height: int = Field(10, ge=gen.MIN_HEIGHT, le=gen.MAX_HEIGHT)
    robots: int = Field(3, ge=1, le=gen.MAX_ROBOTS)
    tasks: Optional[int] = Field(None, ge=0, le=gen.MAX_TASKS, description="default: 3 per robot")
    seed: int = Field(0, ge=0, le=2**31 - 1)
    events: List[ScheduledEvent] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def _check(self):
        gen.validate_params(self.width, self.height, self.robots,
                            gen.default_task_count(self.robots) if self.tasks is None else self.tasks)
        return self


class CreateSimulation(BaseModel):
    """Create a run from a named scenario file OR from custom generator settings."""
    scenario: Optional[str] = Field(None, description="name from GET /scenarios, e.g. robot_failure")
    custom: Optional[CustomConfig] = None
    strategy: Literal["baseline", "aegis"] = "aegis"

    @model_validator(mode="after")
    def _exactly_one(self):
        if (self.scenario is None) == (self.custom is None):
            raise ValueError("provide exactly one of 'scenario' or 'custom'")
        return self


class StepRequest(BaseModel):
    ticks: int = Field(1, ge=1, le=1000)


class BenchmarkRequest(BaseModel):
    """Run baseline AND aegis on the same inputs. Omit both fields to run all named scenarios."""
    scenarios: Optional[List[str]] = Field(None, max_length=20)
    custom: Optional[CustomConfig] = None


# ---------------------------------------------------------------- responses
class RobotState(BaseModel):
    robot_id: str
    status: str
    position: Cell
    current_task_id: Optional[str]
    queue: List[str]
    route: List[Cell]


class TaskState(BaseModel):
    task_id: str
    status: str
    assigned_robot_id: Optional[str]
    priority: int
    pickup: Cell
    delivery: Cell
    deadline: Optional[int]


class MapState(BaseModel):
    width: int
    height: int
    shelves: List[Cell]


class StateResponse(BaseModel):
    run_id: str
    tick: int
    strategy: str
    status: Literal["running", "finished", "stalled"]
    blocked: List[Cell]
    robots: List[RobotState]
    tasks: List[TaskState]
    map: Optional[MapState] = None


class SimulationInfo(BaseModel):
    run_id: str
    scenario: str
    strategy: str
    tick: int
    status: Literal["running", "finished", "stalled"]
    width: int
    height: int
    robots: int
    tasks: int
    created_at: str


class SimulationCreated(BaseModel):
    info: SimulationInfo
    state: StateResponse


class EventRecord(BaseModel):
    tick: int
    type: str
    description: str
    details: Dict[str, Any]


class EventResult(BaseModel):
    applied: bool
    log: List[EventRecord]
    state: StateResponse


class MetricsResponse(BaseModel):
    scenario: str
    strategy: str
    seed: int
    ticks: int
    tasks_created: int
    tasks_completed: int
    completion_rate: float
    unserved_tasks: int
    total_distance: int
    total_delay: int
    disruptions: int
    recovery_duration_ticks: int
    unresolved_disruptions: int
    recovery_count: int
    collisions: int
    wait_ticks: int
    planning_time_s: float


class ScenarioInfo(BaseModel):
    name: str
    description: str
    width: int
    height: int
    robots: int
    tasks: int
    events: int


class Limits(BaseModel):
    min_width: int
    max_width: int
    min_height: int
    max_height: int
    max_robots: int
    max_tasks: int
    max_live_simulations: int
    note: str


class BenchmarkResponse(BaseModel):
    count: int
    rows: List[MetricsResponse]


# ------------------------------------------------------------------ history
class HistoryRun(BaseModel):
    """A saved run (kept in SQLite; may or may not still be live in memory)."""
    run_id: str
    scenario: str
    strategy: str
    status: str
    tick: int
    width: int
    height: int
    robots: int
    tasks: int
    actions: int = Field(description="number of journaled actions (steps / runs / events)")
    created_at: str
    updated_at: str
    live: bool = Field(description="True if the run is currently loaded in memory")


class HistoryDetail(HistoryRun):
    metrics: MetricsResponse


class JournalEntry(BaseModel):
    seq: int
    op: Literal["step", "run", "event"]
    tick: int
    payload: Dict[str, Any]
    created_at: str


class CompareResponse(BaseModel):
    """Latest finished baseline vs aegis run of one scenario, straight from saved history."""
    scenario: str
    baseline: Optional[MetricsResponse] = None
    aegis: Optional[MetricsResponse] = None
    delta: Dict[str, float] = Field(
        default_factory=dict, description="aegis minus baseline (negative delay/unserved/ticks is better)")


class StoredBenchmarkRow(MetricsResponse):
    batch_id: int
    created_at: str
