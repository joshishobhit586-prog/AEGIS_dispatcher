"""Application-facing API. The UI and the FastAPI layer only call this."""
from __future__ import annotations

from typing import List

from evaluation.metrics import compute_metrics
from evaluation.scenarios import build_simulator, load_scenario
from simulation.simulator import Simulator


class SimulationService:
    def __init__(self):
        self.sim: Simulator | None = None
        self._scenario: dict | None = None
        self._strategy = "aegis"

    def create(self, scenario_path, strategy: str = "aegis") -> dict:
        return self.create_from_scenario(load_scenario(scenario_path), strategy)

    def create_from_scenario(self, scenario: dict, strategy: str = "aegis") -> dict:
        self._scenario = scenario
        self._strategy = strategy
        self.sim = build_simulator(scenario, strategy)
        return self.snapshot()

    @property
    def scenario(self) -> dict:
        return self._scenario

    def robot_ids(self) -> List[str]:
        return list(self._require().robots)

    def reset(self) -> dict:
        self._require()
        self.sim = build_simulator(self._scenario, self._strategy)
        return self.snapshot()

    def step(self, n: int = 1) -> dict:
        self._require()
        for _ in range(n):
            self.sim.step()
        return self.snapshot()

    def run_to_end(self) -> dict:
        self._require()
        self.sim.run()
        return self.snapshot()

    def add_task(self, task_id, pickup, delivery, priority=1, deadline=None) -> None:
        self._act({
            "type": "add_task",
            "task": {"id": task_id, "pickup": list(pickup), "delivery": list(delivery),
                     "priority": priority, "deadline": deadline},
        })

    def apply_event(self, event: dict) -> None:
        """Apply a raw event dict now (used when replaying a saved run)."""
        self._act(event)

    def disable_robot(self, robot_id: str) -> None:
        self._act({"type": "robot_failure", "robot_id": robot_id})

    def restore_robot(self, robot_id: str) -> None:
        self._act({"type": "robot_restore", "robot_id": robot_id})

    def block_cell(self, cell) -> None:
        self._act({"type": "block_cell", "cell": list(cell)})

    def unblock_cell(self, cell) -> None:
        self._act({"type": "unblock_cell", "cell": list(cell)})

    def _act(self, event: dict) -> None:
        """Inject a manual event and apply it immediately (also while paused)."""
        sim = self._require()
        sim.inject_event(event)
        sim.apply_pending_events()

    @property
    def strategy(self) -> str:
        return self._strategy

    @property
    def scenario_name(self) -> str:
        return self._scenario["name"] if self._scenario else ""

    def status(self) -> str:
        sim = self._require()
        if sim.is_finished():
            return "finished"
        return "stalled" if sim.stalled else "running"

    def snapshot(self) -> dict:
        return self._require().snapshot()

    def events(self, last: int = 50) -> List[dict]:
        return self._require().event_log[-last:]

    def metrics(self) -> dict:
        return compute_metrics(self._require())

    def _require(self) -> Simulator:
        if self.sim is None:
            raise RuntimeError("no simulation created yet")
        return self.sim
