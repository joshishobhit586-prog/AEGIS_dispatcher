from pathlib import Path
import pytest
from evaluation.metrics import compute_metrics
from evaluation.run_benchmarks import run_all
from evaluation.scenarios import build_simulator, load_scenario, scenario_paths
from simulation.warehouse import Warehouse

SC_DIR = Path(__file__).resolve().parent.parent / "scenarios"

@pytest.mark.parametrize("path", scenario_paths(SC_DIR), ids=lambda p: p.stem)
def test_scenarios_are_valid(path):
    sc = load_scenario(path)
    wh = Warehouse.from_layout(sc["layout"])
    for t in sc["tasks"]:
        assert wh.is_walkable(tuple(t["pickup"])) and wh.is_walkable(tuple(t["delivery"]))

@pytest.mark.parametrize("strategy", ["baseline", "aegis"])
@pytest.mark.parametrize("path", scenario_paths(SC_DIR), ids=lambda p: p.stem)
def test_no_collisions_and_valid_state(path, strategy):
    sim = build_simulator(load_scenario(path), strategy).run()
    m = compute_metrics(sim)
    assert m["collisions"] == 0
    for r in sim.robots.values():
        assert sim.warehouse.is_walkable(r.position) or r.position in sim.warehouse.blocked

def test_no_disruption_all_tasks_complete():
    sim = build_simulator(load_scenario(SC_DIR / "small_warehouse.json"), "aegis").run()
    assert compute_metrics(sim)["completion_rate"] == 100.0

def test_runs_are_deterministic():
    sc = load_scenario(SC_DIR / "robot_failure.json")
    a = compute_metrics(build_simulator(sc, "aegis").run())
    b = compute_metrics(build_simulator(sc, "aegis").run())
    a.pop("planning_time_s"); b.pop("planning_time_s")
    assert a == b

def test_same_inputs_for_both_strategies_without_disruption():
    sc = load_scenario(SC_DIR / "small_warehouse.json")
    a = compute_metrics(build_simulator(sc, "baseline").run())
    b = compute_metrics(build_simulator(sc, "aegis").run())
    assert a["total_distance"] == b["total_distance"] and a["total_delay"] == b["total_delay"]

def test_benchmark_export(tmp_path):
    rows = run_all(SC_DIR, tmp_path)
    assert len(rows) == 2 * len(scenario_paths(SC_DIR))
    assert (tmp_path / "benchmark_results.csv").exists()

def test_manual_injection_via_service():
    from services.simulation_service import SimulationService
    s = SimulationService()
    s.create(SC_DIR / "small_warehouse.json", "aegis")
    s.step(3)
    s.disable_robot("R2")
    s.block_cell((99, 99))      # invalid: must be rejected, not corrupt state
    s.step(1)
    types = [e["type"] for e in s.events()]
    assert "robot_failure" in types and "event_rejected" in types
    s.run_to_end()
    assert s.metrics()["collisions"] == 0
