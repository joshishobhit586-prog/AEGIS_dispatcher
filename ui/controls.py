"""Buttons and keyboard map. Buttons only call App action methods."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, List

import pygame

from ui.renderer import PANEL_EDGE, TEXT


@dataclass
class Button:
    rect: pygame.Rect
    label: str
    action: Callable[[], None]

    def hit(self, pos) -> bool:
        return self.rect.collidepoint(pos)

    def draw(self, surf, font, hover: bool, active: bool = False) -> None:
        fill = (48, 76, 105) if hover else (29, 44, 64)
        if active:
            fill = (24, 91, 83)
        pygame.draw.rect(surf, fill, self.rect, border_radius=8)
        pygame.draw.rect(surf, (68, 91, 119) if hover or active else PANEL_EDGE,
                         self.rect, 1, border_radius=8)
        img = font.render(self.label, True, TEXT)
        surf.blit(img, img.get_rect(center=self.rect.center))


def make_buttons(app, area: pygame.Rect) -> List[Button]:
    spec = [
        ("Start/Pause [Space]", app.toggle_pause),
        ("Step [N]", app.step_once),
        ("Reset [R]", app.reset),
        ("Fail robot [F]", app.fail_robot),
        ("Restore robot [U]", app.restore_robot),
        ("Block/unblock [B]", app.toggle_block),
        ("Add task [T]", app.start_add_task),
        ("Routes [V]", app.toggle_routes),
        ("Strategy [S]", app.toggle_strategy),
        ("Scenario [C]", app.next_scenario),
        ("Slower [-]", app.slower),
        ("Faster [+]", app.faster),
        ("Grid robots -  ([)", app.fewer_robots),
        ("Grid robots +  (])", app.more_robots),
        ("Case robots -", app.fewer_case_robots),
        ("Case robots +", app.more_case_robots),
        ("Grid -  (key ,)", app.smaller_grid),
        ("Grid +  (key .)", app.bigger_grid),
        ("New layout [G]", app.new_layout),
        ("Quit [Q]", app.quit),
    ]
    per_row, gap, h = 6, 5, 25
    w = (area.w - gap * (per_row - 1)) // per_row
    buttons = []
    for i, (label, fn) in enumerate(spec):
        r, c = divmod(i, per_row)
        buttons.append(Button(pygame.Rect(area.x + c * (w + gap), area.y + r * (h + gap), w, h), label, fn))
    return buttons


def key_map(app) -> dict:
    return {
        pygame.K_SPACE: app.toggle_pause,
        pygame.K_n: app.step_once, pygame.K_RIGHT: app.step_once,
        pygame.K_r: app.reset,
        pygame.K_f: app.fail_robot,
        pygame.K_u: app.restore_robot,
        pygame.K_b: app.toggle_block,
        pygame.K_t: app.start_add_task,
        pygame.K_v: app.toggle_routes,
        pygame.K_s: app.toggle_strategy,
        pygame.K_c: app.next_scenario,
        pygame.K_MINUS: app.slower, pygame.K_KP_MINUS: app.slower,
        pygame.K_EQUALS: app.faster, pygame.K_PLUS: app.faster, pygame.K_KP_PLUS: app.faster,
        pygame.K_LEFTBRACKET: app.fewer_robots, pygame.K_RIGHTBRACKET: app.more_robots,
        pygame.K_COMMA: app.smaller_grid, pygame.K_PERIOD: app.bigger_grid,
        pygame.K_g: app.new_layout,
        pygame.K_TAB: app.cycle_robot,
        pygame.K_ESCAPE: app.cancel,
    }
