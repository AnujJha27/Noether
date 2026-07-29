#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import platform
import statistics
import subprocess
import time
from pathlib import Path
from typing import Any


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the proof-search benchmark repeatedly and summarize variance."
    )
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--binary", default="build/benchmark")
    parser.add_argument("--fixture", default="tests/fixtures/benchmark.json")
    parser.add_argument("--output", default="benchmark-repeat-results.json")
    return parser.parse_args()


def mean(values: list[float]) -> float:
    return statistics.fmean(values) if values else 0.0


def stdev(values: list[float]) -> float:
    return statistics.stdev(values) if len(values) > 1 else 0.0


def main() -> int:
    options = arguments()
    if options.runs < 1:
        raise SystemExit("--runs must be at least 1")

    measurements: list[dict[str, Any]] = []
    for index in range(options.runs):
        started = time.time()
        completed = subprocess.run(
            [options.binary, options.fixture],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        measurement = json.loads(completed.stdout)
        measurement["run_index"] = index + 1
        measurement["wall_clock_s"] = time.time() - started
        measurements.append(measurement)

    cold = [item["cold_cache"]["elapsed_ms"] for item in measurements]
    warm = [item["warm_cache"]["elapsed_ms"] for item in measurements]
    throughput = [item["checks_per_second"] for item in measurements]
    p95 = [item["p95_latency_ms"] for item in measurements]

    summary = {
        "runs": options.runs,
        "environment": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "processor": platform.processor(),
        },
        "fixture": options.fixture,
        "metrics": {
            "cold_cache_elapsed_ms": {
                "mean": mean(cold),
                "stdev": stdev(cold),
                "values": cold,
            },
            "warm_cache_elapsed_ms": {
                "mean": mean(warm),
                "stdev": stdev(warm),
                "values": warm,
            },
            "checks_per_second": {
                "mean": mean(throughput),
                "stdev": stdev(throughput),
                "values": throughput,
            },
            "p95_latency_ms": {
                "mean": mean(p95),
                "stdev": stdev(p95),
                "values": p95,
            },
        },
        "measurements": measurements,
    }
    Path(options.output).write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
