"""Grid warehouse model. Coordinates are (x, y): x = column, y = row."""
from __future__ import annotations

from typing import Iterable, Iterator, List, Set, Tuple

Cell = Tuple[int, int]
DIRECTIONS = ((0, -1), (0, 1), (-1, 0), (1, 0))  # fixed order => deterministic


class Warehouse:
    def __init__(self, width: int, height: int, shelves: Iterable[Cell] = ()):
        if width <= 0 or height <= 0:
            raise ValueError("warehouse dimensions must be positive")
        self.width = width
        self.height = height
        self.shelves: Set[Cell] = set()
        self.blocked: Set[Cell] = set()  # temporary obstacles
        for cell in shelves:
            cell = (int(cell[0]), int(cell[1]))
            if not self.in_bounds(cell):
                raise ValueError(f"shelf {cell} is out of bounds")
            self.shelves.add(cell)

    @classmethod
    def from_layout(cls, rows: List[str]) -> "Warehouse":
        """Build from text rows: '#' = shelf, '.' = open floor."""
        if not rows:
            raise ValueError("layout is empty")
        width = len(rows[0])
        shelves = []
        for y, row in enumerate(rows):
            if len(row) != width:
                raise ValueError("layout rows must all have the same length")
            for x, ch in enumerate(row):
                if ch == "#":
                    shelves.append((x, y))
                elif ch != ".":
                    raise ValueError(f"unknown layout character {ch!r}")
        return cls(width, len(rows), shelves)

    def in_bounds(self, cell: Cell) -> bool:
        return 0 <= cell[0] < self.width and 0 <= cell[1] < self.height

    def is_shelf(self, cell: Cell) -> bool:
        return cell in self.shelves

    def is_walkable(self, cell: Cell, extra_blocked: Iterable[Cell] = ()) -> bool:
        return (
            self.in_bounds(cell)
            and cell not in self.shelves
            and cell not in self.blocked
            and cell not in extra_blocked
        )

    def neighbors(self, cell: Cell, extra_blocked: Iterable[Cell] = ()) -> Iterator[Cell]:
        for dx, dy in DIRECTIONS:
            nxt = (cell[0] + dx, cell[1] + dy)
            if self.is_walkable(nxt, extra_blocked):
                yield nxt

    def block(self, cell: Cell) -> bool:
        """Add a temporary obstacle. Returns True if newly blocked."""
        cell = (int(cell[0]), int(cell[1]))
        if not self.in_bounds(cell):
            raise ValueError(f"{cell} is out of bounds")
        if cell in self.shelves:
            raise ValueError(f"{cell} is a shelf and cannot be blocked")
        if cell in self.blocked:
            return False
        self.blocked.add(cell)
        return True

    def unblock(self, cell: Cell) -> bool:
        """Remove a temporary obstacle. Returns True if it was blocked."""
        cell = (int(cell[0]), int(cell[1]))
        if cell in self.blocked:
            self.blocked.remove(cell)
            return True
        return False
