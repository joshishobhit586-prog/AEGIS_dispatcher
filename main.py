"""AEGIS entry point.

  python main.py                      # Pygame UI (default)
  python main.py --cli --log          # text mode
  python main.py --benchmark          # all scenarios x strategies -> results/
  python main.py --api                # FastAPI server (docs at /docs)
"""
import argparse

from config import STRATEGIES
from evaluation.metrics import compute_metrics
from evaluation.run_benchmarks import format_table, run_all
from evaluation.scenarios import build_simulator, load_scenario
from ui.ascii_view import render_ascii


def main() -> None:
    ap = argparse.ArgumentParser(description="AEGIS warehouse recovery simulation")
    ap.add_argument("--scenario", default="scenarios/robot_failure.json")
    ap.add_argument("--strategy", choices=STRATEGIES, default="aegis")
    ap.add_argument("--cli", action="store_true", help="text mode instead of the Pygame window")
    ap.add_argument("--api", action="store_true", help="start the FastAPI server")
    ap.add_argument("--host", default="127.0.0.1", help="API host (default: local only)")
    ap.add_argument("--port", type=int, default=8000, help="API port")
    ap.add_argument("--benchmark", action="store_true", help="run all scenarios x strategies")
    ap.add_argument("--render-every", type=int, default=0, help="print the map every N ticks")
    ap.add_argument("--log", action="store_true", help="print the event log")
    args = ap.parse_args()

    if args.api:
        try:
            import uvicorn
        except ImportError:
            raise SystemExit("FastAPI/uvicorn not installed. Run: python -m pip install -r requirements.txt")
        uvicorn.run("api.app:app", host=args.host, port=args.port)
        return

    if args.benchmark:
        print(format_table(run_all()))
        print("\nSaved to results/benchmark_results.csv and .json")
        return

    if not args.cli:
        try:
            from ui.app import run_ui
        except ImportError:
            raise SystemExit("Pygame is not installed. Run: python -m pip install -r requirements.txt")
        run_ui("scenarios", args.scenario, args.strategy)
        return

    sim = build_simulator(load_scenario(args.scenario), args.strategy)
    while not sim.is_finished() and sim.tick < sim.max_ticks:
        if args.render_every and sim.tick % args.render_every == 0:
            print(render_ascii(sim.snapshot()), "\n")
        sim.step()
        if sim.stalled:
            break
    print(render_ascii(sim.snapshot()), "\n")
    if args.log:
        for e in sim.event_log:
            print(f"[t={e['tick']:>3}] {e['type']:<20} {e['description']}")
        print()
    for k, v in compute_metrics(sim).items():
        print(f"{k:>26}: {v}")


if __name__ == "__main__":
    main()
