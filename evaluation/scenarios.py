"""Scenario loading. The same scenario file feeds every strategy."""
from __future__ import annotations

import json
from pathlib import Path
from typing import List

from simulation.robot import Robot
from simulation.simulator import Simulator
from simulation.task import Task
from simulation.warehouse import Warehouse

REQUIRED_KEYS = ("name", "layout", "robots", "tasks")


def load_scenario(path) -> dict:
    with open(path, encoding="utf-8") as fh:
        sc = json.load(fh)
    missing = [k for k in REQUIRED_KEYS if k not in sc]
    if missing:
        raise ValueError(f"{path}: missing keys {missing}")
    sc.setdefault("events", [])
    sc.setdefault("seed", 0)
    return sc


def build_simulator(scenario: dict, strategy: str) -> Simulator:
    wh = Warehouse.from_layout(scenario["layout"])
    robots = [Robot(r["id"], tuple(r["position"])) for r in scenario["robots"]]
    tasks = [
        Task(
            t["id"],
            tuple(t["pickup"]),
            tuple(t["delivery"]),
            priority=t.get("priority", 1),
            created_tick=0,
            deadline=t.get("deadline"),
        )
        for t in scenario["tasks"]
    ]
    return Simulator(
        wh, robots, tasks, scenario["events"], strategy, scenario["seed"], scenario["name"]
    )


def scenario_paths(directory) -> List[Path]:
    return sorted(Path(directory).glob("*.json"))
