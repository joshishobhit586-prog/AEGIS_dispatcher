"""Grid rendering. Draws only; never changes simulation state."""
from __future__ import annotations

from typing import Dict, Optional, Tuple

import pygame

Cell = Tuple[int, int]

# AEGIS Control Room palette: deep navy, cool slate, and restrained cyan/amber accents.
BG = (12, 18, 30)
PANEL = (22, 32, 49)
PANEL_EDGE = (48, 67, 91)
TEXT = (229, 238, 249)
DIM = (143, 161, 184)
FLOOR = (25, 39, 57)
FLOOR_ALT = (28, 43, 62)
FLOOR_LINE = (43, 61, 82)
FLOOR_DOT = (49, 68, 90)
SHELF = (63, 84, 111)
SHELF_IN = (105, 132, 162)
BLOCK_BG = (75, 38, 53)
BLOCK_X = (255, 91, 112)
UNASSIGNED = (113, 132, 155)
SELECT = (255, 190, 75)
GOOD = (53, 211, 164)
BAD = (255, 91, 112)
ROBOT_COLORS = [
    (66, 153, 225), (53, 211, 164), (255, 177, 74), (180, 126, 255),
    (63, 207, 219), (255, 112, 153), (129, 140, 248), (190, 220, 94),
    (255, 130, 92), (83, 195, 184), (218, 139, 232), (211, 174, 122),
]
STATUS_LETTER = {"IDLE": "I", "MOVING": "M", "WAITING": "W", "UNAVAILABLE": "X"}


def robot_color(index: int) -> Tuple[int, int, int]:
    return ROBOT_COLORS[index % len(ROBOT_COLORS)]


class GridView:
    def __init__(self, rect: pygame.Rect, width: int, height: int):
        self.cell = max(8, min(rect.w // width, rect.h // height))
        self.compact = self.cell < 30  # small cells: no text labels, smaller markers
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
        inventory = {tuple(item["cell"]): int(item["quantity"]) for item in snap.get("inventory", [])}
        for y in range(self.height):
            for x in range(self.width):
                rect = self.cell_rect((x, y))
                if (x, y) in shelves:
                    pygame.draw.rect(surf, SHELF, rect)
                    # Shelves read as storage racks rather than solid wall tiles.
                    inner = rect.inflate(-6 if self.compact else -10, -6 if self.compact else -10)
                    pygame.draw.rect(surf, SHELF_IN, inner, 1 if self.compact else 2, border_radius=2)
                    if not self.compact:
                        # Stock cartons make each shelf read as stocked inventory,
                        # while keeping shelf tiles impassable to the robots.
                        pygame.draw.line(surf, (48, 65, 87), (inner.left + 2, inner.centery),
                                         (inner.right - 2, inner.centery), 2)
                        pygame.draw.line(surf, (48, 65, 87), (inner.left + 2, inner.top + 4),
                                         (inner.right - 2, inner.top + 4), 1)
                        carton_colors = ((74, 190, 171), (237, 174, 82), (135, 153, 235))
                        carton_w = max(3, min(7, inner.width // 4))
                        carton_h = max(3, min(6, inner.height // 5))
                        for n, carton_color in enumerate(carton_colors):
                            cx = inner.left + 4 + (n % 2) * (carton_w + 3)
                            cy = inner.top + 5 + (n // 2) * (carton_h + 2)
                            if cx + carton_w < inner.right and cy + carton_h < inner.bottom:
                                pygame.draw.rect(surf, carton_color,
                                                 pygame.Rect(cx, cy, carton_w, carton_h),
                                                 border_radius=1)
                        # Read the live stock from simulation state: pickup decrements,
                        # delivery increments. Fallback supports older snapshots.
                        stock = inventory.get((x, y), 4 + ((x * 7 + y * 3) % 20))
                        count_font = fonts.get("tiny")
                        if count_font:
                            label = count_font.render(str(stock), True, (238, 244, 252))
                            surf.blit(label, (inner.right - label.get_width() - 2,
                                              inner.bottom - label.get_height() - 1))
                    else:
                        # Tiny inventory marker remains legible on dense grids.
                        pygame.draw.circle(surf, (74, 190, 171),
                                           (rect.centerx - 3, rect.centery), 2)
                        pygame.draw.circle(surf, (237, 174, 82),
                                           (rect.centerx + 3, rect.centery), 2)
                        count_font = fonts.get("tiny")
                        if count_font and self.cell >= 18:
                            label = count_font.render(str(inventory.get((x, y), 0)), True, (238, 244, 252))
                            surf.blit(label, label.get_rect(center=(rect.centerx, rect.bottom - 5)))
                elif (x, y) in blocked:
                    pygame.draw.rect(surf, BLOCK_BG, rect)
                    pygame.draw.rect(surf, FLOOR_LINE, rect, 1)
                    m, w = (3, 2) if self.compact else (6, 3)
                    pygame.draw.line(surf, BLOCK_X, (rect.left + m, rect.top + m), (rect.right - m, rect.bottom - m), w)
                    pygame.draw.line(surf, BLOCK_X, (rect.right - m, rect.top + m), (rect.left + m, rect.bottom - m), w)
                else:
                    pygame.draw.rect(surf, FLOOR_ALT if (x + y) % 2 else FLOOR, rect)
                    pygame.draw.rect(surf, FLOOR_LINE, rect, 1)
                    if not self.compact:
                        # Tiny floor rivet gives the grid texture without competing with routes.
                        pygame.draw.circle(surf, FLOOR_DOT, (rect.right - 4, rect.bottom - 4), 1)

        if show_routes:
            # Draw a subdued underlay first so routes stay readable across every tile.
            route_layer = pygame.Surface(surf.get_size(), pygame.SRCALPHA)
            for r in snap["robots"]:
                pts = [self.center(tuple(c)) for c in r["route"]]
                if len(pts) >= 2:
                    col = colors[r["robot_id"]]
                    pygame.draw.lines(route_layer, (*col, 62), False, pts, 7 if not self.compact else 5)
                    pygame.draw.lines(route_layer, (*col, 205), False, pts, 2 if not self.compact else 1)
                    pygame.draw.circle(route_layer, (*col, 235), pts[-1], 4 if not self.compact else 3, 2)
            surf.blit(route_layer, (0, 0))

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
                if self.compact:
                    sz = max(3, self.cell // 6)
                    cx, cy = rect.left + sz + 2 + (n % 2) * (2 * sz + 2), rect.top + sz + 2 + (n // 2) * (2 * sz + 2)
                    if kind == "pickup":
                        pygame.draw.polygon(surf, col, [(cx, cy - sz), (cx - sz, cy + sz), (cx + sz, cy + sz)])
                    else:
                        pygame.draw.rect(surf, col, pygame.Rect(cx - sz, cy - sz, 2 * sz, 2 * sz), 2)
                    continue
                cx, cy = rect.left + 9, rect.top + 9 + n * 12
                if kind == "pickup":  # triangle = pickup
                    pygame.draw.polygon(surf, col, [(cx, cy - 5), (cx - 5, cy + 4), (cx + 5, cy + 4)])
                else:                 # hollow square = delivery
                    pygame.draw.rect(surf, col, pygame.Rect(cx - 5, cy - 5, 10, 10), 2)
                label = fonts["tiny"].render(t["task_id"], True, (229, 238, 249))
                surf.blit(label, (cx + 8, cy - 5))

    def _draw_robots(self, surf, snap, fonts, colors, selected_robot) -> None:
        tasks = {t["task_id"]: t for t in snap["tasks"]}
        for r in snap["robots"]:
            rect = self.cell_rect(tuple(r["position"])).inflate(-4, -4) if self.compact \
                else self.cell_rect(tuple(r["position"])).inflate(-10, -10)
            down = r["status"] == "UNAVAILABLE"
            col = (75, 87, 105) if down else colors[r["robot_id"]]
            # Offset shadow gives the robot marker a little depth while staying a simple square.
            shadow = rect.move(2, 2)
            pygame.draw.rect(surf, (9, 15, 25), shadow, border_radius=7)
            pygame.draw.rect(surf, col, rect, border_radius=7)
            outline = (255, 255, 255) if r["robot_id"] == selected_robot else (11, 20, 32)
            pygame.draw.rect(surf, outline, rect, 3 if r["robot_id"] == selected_robot else 1, border_radius=7)
            if self.compact:
                label = fonts["tiny"].render(r["robot_id"][1:], True, (255, 255, 255))
                surf.blit(label, label.get_rect(center=rect.center))
            else:
                label = fonts["small"].render(r["robot_id"], True, (255, 255, 255))
                surf.blit(label, label.get_rect(center=rect.center))
                letter = fonts["tiny"].render(STATUS_LETTER.get(r["status"], "?"), True, (255, 255, 255))
                surf.blit(letter, (rect.left + 3, rect.bottom - 13))
            cur = tasks.get(r["current_task_id"]) if r["current_task_id"] else None
            if cur and cur["status"] == "IN_PROGRESS":  # filled dot = carrying cargo
                pygame.draw.circle(surf, (255, 255, 255), (rect.right - 4, rect.top + 4) if self.compact
                                   else (rect.right - 7, rect.top + 7), 2 if self.compact else 4)
            if down:
                pygame.draw.line(surf, BLOCK_X, rect.topleft, rect.bottomright, 4)
                pygame.draw.line(surf, BLOCK_X, rect.topright, rect.bottomleft, 4)
