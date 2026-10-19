"""Grid rendering. Draws only; never changes simulation state."""
from __future__ import annotations

from typing import Dict, Optional, Tuple

import pygame

Cell = Tuple[int, int]

BG = (24, 26, 31)
PANEL = (36, 39, 46)
PANEL_EDGE = (70, 75, 86)
TEXT = (232, 234, 238)
DIM = (150, 156, 168)
FLOOR = (238, 237, 230)
FLOOR_LINE = (214, 212, 204)
SHELF = (122, 96, 70)
SHELF_IN = (150, 122, 92)
BLOCK_BG = (244, 200, 196)
BLOCK_X = (190, 40, 40)
UNASSIGNED = (130, 130, 138)
SELECT = (255, 196, 0)
GOOD = (90, 200, 120)
BAD = (240, 100, 100)
ROBOT_COLORS = [
    (40, 110, 220), (30, 150, 90), (200, 110, 20),
    (140, 60, 170), (0, 140, 150), (180, 45, 95),
]
STATUS_LETTER = {"IDLE": "I", "MOVING": "M", "WAITING": "W", "UNAVAILABLE": "X"}


def robot_color(index: int) -> Tuple[int, int, int]:
    return ROBOT_COLORS[index % len(ROBOT_COLORS)]


class GridView:
    def __init__(self, rect: pygame.Rect, width: int, height: int):
        self.cell = max(8, min(rect.w // width, rect.h // height))
        self.width, self.height = width, height
        self.ox = rect.x + (rect.w - self.cell * width) // 2
        self.oy = rect.y + (rect.h - self.cell * height) // 2

    def cell_rect(self, c: Cell) -> pygame.Rect:
        return pygame.Rect(self.ox + c[0] * self.cell, self.oy + c[1] * self.cell, self.cell, self.cell)

    def center(self, c: Cell) -> Tuple[int, int]:
        return self.cell_rect(c).center

    def cell_at(self, pos) -> Optional[Cell]:
        x, y = (pos[0] - self.ox) // self.cell, (pos[1] - self.oy) // self.cell
        if 0 <= x < self.width and 0 <= y < self.height and pos[0] >= self.ox and pos[1] >= self.oy:
            return int(x), int(y)
        return None

    def draw(self, surf, snap: dict, fonts: dict, show_routes: bool = True,
             selected_cell: Optional[Cell] = None, selected_robot: Optional[str] = None,
             add_mode_cell: Optional[Cell] = None) -> None:
        colors: Dict[str, Tuple[int, int, int]] = {
            r["robot_id"]: robot_color(i) for i, r in enumerate(snap["robots"])
        }
        shelves, blocked = set(map(tuple, snap["shelves"])), set(map(tuple, snap["blocked"]))
        for y in range(self.height):
            for x in range(self.width):
                rect = self.cell_rect((x, y))
                if (x, y) in shelves:
                    pygame.draw.rect(surf, SHELF, rect)
                    pygame.draw.rect(surf, SHELF_IN, rect.inflate(-10, -10), 2)
                elif (x, y) in blocked:
                    pygame.draw.rect(surf, BLOCK_BG, rect)
                    pygame.draw.rect(surf, FLOOR_LINE, rect, 1)
                    pygame.draw.line(surf, BLOCK_X, (rect.left + 6, rect.top + 6), (rect.right - 6, rect.bottom - 6), 4)
                    pygame.draw.line(surf, BLOCK_X, (rect.right - 6, rect.top + 6), (rect.left + 6, rect.bottom - 6), 4)
                else:
                    pygame.draw.rect(surf, FLOOR, rect)
                    pygame.draw.rect(surf, FLOOR_LINE, rect, 1)

        if show_routes:
            for r in snap["robots"]:
                pts = [self.center(tuple(c)) for c in r["route"]]
                if len(pts) >= 2:
                    pygame.draw.lines(surf, colors[r["robot_id"]], False, pts, 3)
                    pygame.draw.circle(surf, colors[r["robot_id"]], pts[-1], 5, 2)

        self._draw_tasks(surf, snap, fonts, colors)
        self._draw_robots(surf, snap, fonts, colors, selected_robot)

        if selected_cell is not None:
            pygame.draw.rect(surf, SELECT, self.cell_rect(selected_cell), 3)
        if add_mode_cell is not None:
            pygame.draw.rect(surf, (60, 160, 255), self.cell_rect(add_mode_cell), 3)

    def _draw_tasks(self, surf, snap, fonts, colors) -> None:
        stack: Dict[Cell, int] = {}
        for t in snap["tasks"]:
            if t["status"] in ("COMPLETED", "FAILED"):
                continue
            col = colors.get(t["assigned_robot_id"], UNASSIGNED)
            marks = []
            if t["status"] != "IN_PROGRESS":
                marks.append(("pickup", tuple(t["pickup"])))
            marks.append(("delivery", tuple(t["delivery"])))
            for kind, c in marks:
                n = stack.get(c, 0)
                stack[c] = n + 1
                rect = self.cell_rect(c)
                cx, cy = rect.left + 9, rect.top + 9 + n * 12
                if kind == "pickup":  # triangle = pickup
                    pygame.draw.polygon(surf, col, [(cx, cy - 5), (cx - 5, cy + 4), (cx + 5, cy + 4)])
                else:                 # hollow square = delivery
                    pygame.draw.rect(surf, col, pygame.Rect(cx - 5, cy - 5, 10, 10), 2)
                label = fonts["tiny"].render(t["task_id"], True, (40, 40, 46))
                surf.blit(label, (cx + 8, cy - 5))

    def _draw_robots(self, surf, snap, fonts, colors, selected_robot) -> None:
        tasks = {t["task_id"]: t for t in snap["tasks"]}
        for r in snap["robots"]:
            rect = self.cell_rect(tuple(r["position"])).inflate(-10, -10)
            down = r["status"] == "UNAVAILABLE"
            col = (110, 110, 118) if down else colors[r["robot_id"]]
            pygame.draw.rect(surf, col, rect, border_radius=8)
            outline = (255, 255, 255) if r["robot_id"] == selected_robot else (20, 20, 24)
            pygame.draw.rect(surf, outline, rect, 3 if r["robot_id"] == selected_robot else 1, border_radius=8)
            label = fonts["small"].render(r["robot_id"], True, (255, 255, 255))
            surf.blit(label, label.get_rect(center=rect.center))
            letter = fonts["tiny"].render(STATUS_LETTER.get(r["status"], "?"), True, (255, 255, 255))
            surf.blit(letter, (rect.left + 3, rect.bottom - 13))
            cur = tasks.get(r["current_task_id"]) if r["current_task_id"] else None
            if cur and cur["status"] == "IN_PROGRESS":  # filled dot = carrying cargo
                pygame.draw.circle(surf, (255, 255, 255), (rect.right - 7, rect.top + 7), 4)
            if down:
                pygame.draw.line(surf, BLOCK_X, rect.topleft, rect.bottomright, 4)
                pygame.draw.line(surf, BLOCK_X, rect.topright, rect.bottomleft, 4)
