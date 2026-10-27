import os
import pytest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
pygame = pytest.importorskip("pygame")

from pathlib import Path
from ui.app import App

SC = str(Path(__file__).resolve().parent.parent / "scenarios")

@pytest.fixture
def app():
    pygame.init()
    screen = pygame.display.set_mode((1180, 780))
    a = App(SC, "robot_failure.json", "aegis")
    a.screen = screen
    yield a
    pygame.quit()

def click(app, cell):
    app.click_grid(cell)

def test_draws_without_error_and_steps(app):
    app.draw(app.screen)
    app.step_once(); app.step_once()
    assert app.snap["tick"] == 2
    app.draw(app.screen)

def test_pause_run_toggle_advances_time(app):
    app.toggle_pause()
    app.update(1000)            # 5 ticks/s default
    assert app.snap["tick"] >= 4

def test_fail_robot_needs_selection_then_works(app):
    app.step_once()
    app.fail_robot()
    assert "Select a robot" in app.notice[0]
    app.cycle_robot()
    rid = app.selected_robot
    app.fail_robot()
    status = {r["robot_id"]: r["status"] for r in app.snap["robots"]}[rid]
    assert status == "UNAVAILABLE"

def test_block_and_unblock_cell_and_reject_shelf(app):
    app.step_once()
    click(app, (4, 3)); app.toggle_block()
    assert (4, 3) in set(map(tuple, app.snap["blocked"]))
    app.toggle_block()
    assert (4, 3) not in set(map(tuple, app.snap["blocked"]))
    click(app, (2, 1)); app.toggle_block()      # shelf: must be rejected, not crash
    assert "shelf" in app.notice[0]
    assert app.service.metrics()["collisions"] == 0

def test_add_task_two_clicks(app):
    app.step_once()
    n = len(app.snap["tasks"])
    app.start_add_task()
    click(app, (0, 3)); click(app, (16, 9))
    assert len(app.snap["tasks"]) == n + 1
    assert app.add_stage is None

def test_add_task_rejects_shelf_click(app):
    app.start_add_task()
    click(app, (2, 1))
    assert app.add_stage == "pickup" and "open floor" in app.notice[0]

def test_strategy_scenario_reset_and_keys(app):
    app.toggle_strategy()
    assert app.strategy == "baseline" and app.snap["tick"] == 0
    first = app.service.scenario_name
    app.next_scenario()
    assert app.service.scenario_name != first
    ev = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_n)
    assert app.handle_event(ev) is True and app.snap["tick"] == 1
    assert app.handle_event(pygame.event.Event(pygame.QUIT)) is False

def test_run_ends_and_pauses(app):
    app.paused = False
    app.service.sim.run()
    app.update(2000)
    assert app.paused is True


# ---- custom grid size / robot count ------------------------------------
def test_more_and_fewer_robots_regenerates_world(app):
    n0 = len(app.snap["robots"])
    app.more_robots()
    assert len(app.snap["robots"]) == n0 + 1 and app.custom is not None
    assert len(app.snap["tasks"]) == 3 * (n0 + 1) and app.snap["tick"] == 0
    app.fewer_robots(); app.fewer_robots()
    assert len(app.snap["robots"]) == n0 - 1
    app.draw(app.screen)


def test_robot_count_limits(app):
    for _ in range(40):
        app.more_robots()
    assert len(app.snap["robots"]) == 17           # capped by grid width 17
    for _ in range(40):
        app.fewer_robots()
    assert len(app.snap["robots"]) == 1


def test_grid_bigger_smaller_and_view_resizes(app):
    w0, h0, cell0 = app.snap["width"], app.snap["height"], app.view.cell
    app.bigger_grid()
    assert (app.snap["width"], app.snap["height"]) == (w0 + 4, h0 + 3) and app.view.cell < cell0
    for _ in range(30):
        app.bigger_grid()
    assert (app.snap["width"], app.snap["height"]) == (45, 30) and app.view.compact
    app.draw(app.screen)                            # compact rendering must not crash
    for _ in range(30):
        app.smaller_grid()
    assert (app.snap["width"], app.snap["height"]) == (9, 7)
    app.draw(app.screen)


def test_custom_world_runs_and_strategy_toggle_keeps_it(app):
    app.bigger_grid(); app.more_robots()
    size = (app.snap["width"], len(app.snap["robots"]))
    app.toggle_strategy()
    assert (app.snap["width"], len(app.snap["robots"])) == size and app.strategy == "baseline"
    app.service.run_to_end()
    app._refresh()
    assert app.service.metrics()["collisions"] == 0


def test_new_layout_changes_tasks_and_scenario_key_leaves_custom(app):
    app.more_robots()
    before = [tuple(t["pickup"]) for t in app.snap["tasks"]]
    app.new_layout()
    assert [tuple(t["pickup"]) for t in app.snap["tasks"]] != before
    app.next_scenario()
    assert app.custom is None and not app.service.scenario_name.startswith("custom")


def test_quit_button_stops_the_loop(app):
    app.quit()
    assert app.running is False
