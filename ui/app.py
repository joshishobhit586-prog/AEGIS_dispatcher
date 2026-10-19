"""Pygame application. All simulation access goes through SimulationService."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import pygame

from evaluation.scenarios import scenario_paths
from services.simulation_service import SimulationService
from ui import panels
from ui.controls import key_map, make_buttons
from ui.renderer import BG, GridView

WIN_W, WIN_H = 1180, 780
SPEEDS = [1, 2, 5, 10, 20, 40]
TASK_DEADLINE_OFFSET = 40
TASK_PRIORITY = 3


class App:
    def __init__(self, scenarios_dir="scenarios", scenario: Optional[str] = None, strategy="aegis"):
        self.paths = scenario_paths(scenarios_dir)
        if not self.paths:
            raise SystemExit(f"no scenario files found in {scenarios_dir}")
        self.idx = 0
        if scenario:
            names = [p.name for p in self.paths]
            if Path(scenario).name in names:
                self.idx = names.index(Path(scenario).name)
        self.strategy = strategy
        self.service = SimulationService()
        self.fonts = {
            "tiny": pygame.font.Font(None, 15),
            "small": pygame.font.SysFont("dejavusansmono,consolas,menlo,couriernew,monospace", 14),
            "button": pygame.font.Font(None, 17),
            "bold": pygame.font.Font(None, 23),
        }
        self.speed_idx = 2
        self.show_routes = True
        self.accum = 0.0
        self.task_counter = 0
        self.notice = ("", 0)
        self._load()
        self.view = GridView(pygame.Rect(16, 56, 748, 450), self.snap["width"], self.snap["height"])
        self.buttons = make_buttons(self, pygame.Rect(16, 516, 748, 66))
        self.keys = key_map(self)

    # ---------------------------------------------------------------- state
    def _load(self) -> None:
        self.snap = self.service.create(self.paths[self.idx], self.strategy)
        self.paused = True
        self.selected_robot: Optional[str] = None
        self.selected_cell = None
        self.add_stage: Optional[str] = None   # None | "pickup" | "delivery"
        self.pending_pickup = None
        self.ticks_ms_notice(f"Loaded {self.service.scenario_name}")

    def ticks_ms_notice(self, text: str) -> None:
        self.notice = (text, pygame.time.get_ticks())

    def _refresh(self) -> None:
        self.snap = self.service.snapshot()

    def _status(self) -> str:
        return "paused" if self.paused and self.service.status() == "running" else self.service.status()

    # -------------------------------------------------------------- actions
    def toggle_pause(self) -> None:
        if self.service.status() != "running":
            self.ticks_ms_notice("Run is over - press R to reset (or add an event to continue)")
            return
        self.paused = not self.paused

    def step_once(self) -> None:
        self.service.step()
        self._refresh()

    def reset(self) -> None:
        self.service.reset()
        self.paused = True
        self.add_stage, self.pending_pickup = None, None
        self._refresh()
        self.ticks_ms_notice("Scenario reset")

    def _manual(self, fn, *args, ok: str) -> None:
        """Run a service action and surface a rejection as a notice."""
        before = len(self.service.sim.event_log)
        fn(*args)
        new = self.service.sim.event_log[before:]
        rejected = [e for e in new if e["type"] in ("event_rejected", "assignment_rejected")]
        self.ticks_ms_notice(rejected[0]["description"] if rejected else ok)
        self._refresh()

    def fail_robot(self) -> None:
        if not self.selected_robot:
            return self.ticks_ms_notice("Select a robot first (click it or press Tab)")
        self._manual(self.service.disable_robot, self.selected_robot, ok=f"{self.selected_robot} failed")

    def restore_robot(self) -> None:
        if not self.selected_robot:
            return self.ticks_ms_notice("Select a robot first (click it or press Tab)")
        self._manual(self.service.restore_robot, self.selected_robot, ok=f"{self.selected_robot} restored")

    def toggle_block(self) -> None:
        cell = self.selected_cell
        if cell is None:
            return self.ticks_ms_notice("Click a cell first")
        if cell in set(map(tuple, self.snap["blocked"])):
            self._manual(self.service.unblock_cell, cell, ok=f"unblocked {cell}")
        else:
            self._manual(self.service.block_cell, cell, ok=f"blocked {cell}")

    def start_add_task(self) -> None:
        self.add_stage, self.pending_pickup = "pickup", None
        self.ticks_ms_notice("Add task: click the PICKUP cell (Esc cancels)")

    def toggle_routes(self) -> None:
        self.show_routes = not self.show_routes

    def toggle_strategy(self) -> None:
        self.strategy = "baseline" if self.strategy == "aegis" else "aegis"
        self._load()
        self.ticks_ms_notice(f"Strategy: {self.strategy} (scenario reset)")

    def next_scenario(self) -> None:
        self.idx = (self.idx + 1) % len(self.paths)
        self._load()
        self.view = GridView(pygame.Rect(16, 56, 748, 450), self.snap["width"], self.snap["height"])

    def faster(self) -> None:
        self.speed_idx = min(len(SPEEDS) - 1, self.speed_idx + 1)

    def slower(self) -> None:
        self.speed_idx = max(0, self.speed_idx - 1)

    def cycle_robot(self) -> None:
        ids = [r["robot_id"] for r in self.snap["robots"]]
        cur = ids.index(self.selected_robot) if self.selected_robot in ids else -1
        self.selected_robot = ids[(cur + 1) % len(ids)]
        pos = next(r["position"] for r in self.snap["robots"] if r["robot_id"] == self.selected_robot)
        self.selected_cell = tuple(pos)

    def cancel(self) -> None:
        self.add_stage, self.pending_pickup = None, None
        self.selected_robot, self.selected_cell = None, None

    # ---------------------------------------------------------------- input
    def click_grid(self, cell) -> None:
        if self.add_stage:
            blocked = set(map(tuple, self.snap["blocked"]))
            if cell in set(map(tuple, self.snap["shelves"])) or cell in blocked:
                return self.ticks_ms_notice("Pick an open floor cell")
            if self.add_stage == "pickup":
                self.pending_pickup, self.add_stage = cell, "delivery"
                return self.ticks_ms_notice("Now click the DELIVERY cell")
            self.task_counter += 1
            tick = self.snap["tick"]
            self._manual(
                self.service.add_task, f"U{self.task_counter}", self.pending_pickup, cell,
                TASK_PRIORITY, tick + TASK_DEADLINE_OFFSET,
                ok=f"added U{self.task_counter} (priority {TASK_PRIORITY}, deadline +{TASK_DEADLINE_OFFSET})",
            )
            self.add_stage, self.pending_pickup = None, None
            return
        robot = next((r for r in self.snap["robots"] if tuple(r["position"]) == cell), None)
        self.selected_robot = robot["robot_id"] if robot else None
        self.selected_cell = cell

    def handle_event(self, ev) -> bool:
        """Returns False when the window should close."""
        if ev.type == pygame.QUIT:
            return False
        if ev.type == pygame.KEYDOWN:
            if ev.key == pygame.K_q:
                return False
            fn = self.keys.get(ev.key)
            if fn:
                fn()
        elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            for b in self.buttons:
                if b.hit(ev.pos):
                    b.action()
                    return True
            cell = self.view.cell_at(ev.pos)
            if cell is not None:
                self.click_grid(cell)
        return True

    def update(self, dt_ms: float) -> None:
        if self.paused:
            return
        self.accum += dt_ms
        interval = 1000.0 / SPEEDS[self.speed_idx]
        while self.accum >= interval:
            self.accum -= interval
            if self.service.status() != "running":
                self.paused = True
                self.ticks_ms_notice(f"Run {self.service.status()}")
                break
            self.service.step()
        self._refresh()

    # ----------------------------------------------------------------- draw
    def draw(self, screen) -> None:
        screen.fill(BG)
        now = pygame.time.get_ticks()
        notice = self.notice[0] if now - self.notice[1] < 4000 else ""
        panels.draw_status_bar(screen, pygame.Rect(0, 0, WIN_W, 44), self.fonts, {
            "scenario": self.service.scenario_name, "strategy": self.strategy,
            "tick": self.snap["tick"], "state": self._status(),
            "speed": SPEEDS[self.speed_idx], "notice": notice,
        })
        hint = self.pending_pickup if self.add_stage == "delivery" else None
        self.view.draw(screen, self.snap, self.fonts, self.show_routes,
                       self.selected_cell, self.selected_robot, hint)
        mouse = pygame.mouse.get_pos()
        for b in self.buttons:
            b.draw(screen, self.fonts["button"], b.rect.collidepoint(mouse),
                   active=(b.label.startswith("Routes") and self.show_routes)
                   or (b.label.startswith("Add task") and self.add_stage is not None))
        panels.draw_legend(screen, pygame.Rect(16, 588, 748, 40), self.fonts)
        panels.draw_event_log(screen, pygame.Rect(16, 636, 748, 128), self.fonts, self.service.events(60))
        panels.draw_robots(screen, pygame.Rect(780, 56, 384, 120), self.fonts, self.snap, self.selected_robot)
        panels.draw_tasks(screen, pygame.Rect(780, 184, 384, 330), self.fonts, self.snap)
        panels.draw_metrics(screen, pygame.Rect(780, 522, 384, 242), self.fonts, self.service.metrics())


def run_ui(scenarios_dir="scenarios", scenario=None, strategy="aegis") -> None:
    pygame.init()
    pygame.display.set_caption("AEGIS - Adaptive Multi-Robot Mission Recovery")
    screen = pygame.display.set_mode((WIN_W, WIN_H))
    clock = pygame.time.Clock()
    app = App(scenarios_dir, scenario, strategy)
    running = True
    while running:
        dt = clock.tick(30)
        for ev in pygame.event.get():
            running = app.handle_event(ev) and running
        app.update(dt)
        app.draw(screen)
        pygame.display.flip()
    pygame.quit()
