"""Run every scenario under every strategy and export measured results.

Usage:  python -m evaluation.run_benchmarks [--scenarios scenarios] [--out results]
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from config import STRATEGIES
from evaluation.metrics import compute_metrics
from evaluation.scenarios import build_simulator, load_scenario, scenario_paths

COLUMNS = [
    "scenario", "strategy", "ticks", "tasks_created", "tasks_completed", "completion_rate",
    "unserved_tasks", "total_distance", "total_delay", "disruptions",
    "recovery_duration_ticks", "unresolved_disruptions", "recovery_count",
    "collisions", "wait_ticks", "planning_time_s", "seed",
]


def run_scenario(scenario: dict, strategy: str) -> dict:
    sim = build_simulator(scenario, strategy).run()
    return compute_metrics(sim)


def run_all(scenarios_dir="scenarios", out_dir="results") -> list:
    rows = []
    for path in scenario_paths(scenarios_dir):
        sc = load_scenario(path)
        for strategy in STRATEGIES:
            rows.append(run_scenario(sc, strategy))
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "benchmark_results.csv", "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    with open(out / "benchmark_results.json", "w", encoding="utf-8") as fh:
        json.dump(rows, fh, indent=2)
    return rows


def format_table(rows) -> str:
    cols = ["scenario", "strategy", "completion_rate", "unserved_tasks", "total_distance",
            "total_delay", "recovery_duration_ticks", "unresolved_disruptions", "collisions"]
    widths = [max(len(c), *(len(str(r[c])) for r in rows)) for c in cols]
    line = "  ".join(c.ljust(w) for c, w in zip(cols, widths))
    out = [line, "-" * len(line)]
    for r in rows:
        out.append("  ".join(str(r[c]).ljust(w) for c, w in zip(cols, widths)))
    return "\n".join(out)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenarios", default="scenarios")
    ap.add_argument("--out", default="results")
    args = ap.parse_args()
    print(format_table(run_all(args.scenarios, args.out)))
