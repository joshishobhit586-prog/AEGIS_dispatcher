"""A* pathfinding on the 4-connected, unit-cost warehouse grid."""
from __future__ import annotations

import heapq
from typing import Dict, Iterable, List, Optional

from simulation.warehouse import Cell, Warehouse


def manhattan(a: Cell, b: Cell) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def find_path(
    warehouse: Warehouse,
    start: Cell,
    goal: Cell,
    extra_blocked: Iterable[Cell] = (),
) -> Optional[List[Cell]]:
    """Shortest path from start to goal inclusive, or None if none exists.

    The start cell is always allowed (a robot may stand on a cell that has just
    been blocked and must be able to leave). The goal must be walkable.
    """
    extra = frozenset(extra_blocked)
    if not warehouse.in_bounds(start) or warehouse.is_shelf(start):
        return None
    if not warehouse.is_walkable(goal, extra):
        return None
    if start == goal:
        return [start]

    counter = 0
    h0 = manhattan(start, goal)
    heap = [(h0, h0, counter, 0, start)]  # (f, h, tiebreak, g, cell)
    best_g: Dict[Cell, int] = {start: 0}
    parent: Dict[Cell, Cell] = {}

    while heap:
        _f, _h, _c, g, cur = heapq.heappop(heap)
        if g > best_g.get(cur, g):
            continue  # stale entry
        if cur == goal:
            path = [cur]
            while cur in parent:
                cur = parent[cur]
                path.append(cur)
            path.reverse()
            return path
        for nxt in warehouse.neighbors(cur, extra):
            ng = g + 1
            if ng < best_g.get(nxt, 1 << 30):
                best_g[nxt] = ng
                parent[nxt] = cur
                counter += 1
                h = manhattan(nxt, goal)
                heapq.heappush(heap, (ng + h, h, counter, ng, nxt))
    return None
