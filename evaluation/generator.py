"""Generate scenarios of any (bounded) size: grid, number of robots and tasks.

Layout rule (reproduces the hand-written 17x10 map): a column is an aisle when
x % 4 == 0 or it is the last column; a row is an aisle when y % 3 == 0 or it is
the last row. Cells in an aisle row OR aisle column are open floor, the rest are
shelves. Every open cell is connected, so any open cell can reach any other.
"""
from __future__ import annotations

import math
import random
from typing import List, Optional

from config import MAX_TICKS

MIN_WIDTH, MIN_HEIGHT = 5, 4
MAX_WIDTH, MAX_HEIGHT = 60, 40
MAX_ROBOTS, MAX_TASKS = 20, 80
AISLE_EVERY_X, AISLE_EVERY_Y = 4, 3


def make_layout(width: int, height: int) -> List[str]:
    rows = []
    for y in range(height):
        row_open = y % AISLE_EVERY_Y == 0 or y == height - 1
        rows.append("".join(
            "." if row_open or x % AISLE_EVERY_X == 0 or x == width - 1 else "#"
            for x in range(width)
        ))
    return rows


def validate_params(width: int, height: int, robots: int, tasks: int) -> None:
    if not MIN_WIDTH <= width <= MAX_WIDTH:
        raise ValueError(f"width must be {MIN_WIDTH}-{MAX_WIDTH}")
    if not MIN_HEIGHT <= height <= MAX_HEIGHT:
        raise ValueError(f"height must be {MIN_HEIGHT}-{MAX_HEIGHT}")
    if not 1 <= robots <= MAX_ROBOTS:
        raise ValueError(f"robots must be 1-{MAX_ROBOTS}")
    if robots > width:
        raise ValueError("robots cannot exceed the grid width (they start on the top row)")
    if not 0 <= tasks <= MAX_TASKS:
        raise ValueError(f"tasks must be 0-{MAX_TASKS}")


def default_task_count(robots: int) -> int:
    return min(MAX_TASKS, 3 * robots)


def generate_scenario(
    width: int = 17,
    height: int = 10,
    robots: int = 3,
    tasks: Optional[int] = None,
    seed: int = 0,
    events: Optional[list] = None,
    name: Optional[str] = None,
) -> dict:
    tasks = default_task_count(robots) if tasks is None else tasks
    validate_params(width, height, robots, tasks)
    rng = random.Random(seed)
    layout = make_layout(width, height)
    open_cells = [(x, y) for y, row in enumerate(layout) for x, ch in enumerate(row) if ch == "."]

    robot_list = [
        {"id": f"R{i + 1}", "position": [int((i + 0.5) * width / robots), 0]} for i in range(robots)
    ]

    task_list = []
    for i in range(tasks):
        pickup = rng.choice(open_cells)
        delivery = rng.choice(open_cells)
        while delivery == pickup:
            delivery = rng.choice(open_cells)
        wave = i // robots  # rough: each "wave" of tasks is served in turn
        trip = abs(pickup[0] - delivery[0]) + abs(pickup[1] - delivery[1])
        task_list.append({
            "id": f"T{i + 1}",
            "pickup": list(pickup),
            "delivery": list(delivery),
            "priority": rng.choices([1, 2, 3], weights=[6, 3, 1])[0],
            "deadline": int(1.5 * (width + height) * (1 + wave) + trip),
        })

    max_ticks = min(5000, max(MAX_TICKS, 8 * (width + height) * math.ceil(max(tasks, 1) / robots)))
    return {
        "name": name or f"custom_{width}x{height}_{robots}r_{tasks}t_s{seed}",
        "description": f"Generated {width}x{height} grid, {robots} robots, {tasks} tasks (seed {seed}).",
        "seed": seed,
        "max_ticks": max_ticks,
        "layout": layout,
        "robots": robot_list,
        "tasks": task_list,
        "events": list(events or []),
    }
