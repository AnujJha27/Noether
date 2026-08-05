from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def load(path: str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def score(expected: dict[str, dict[str, bool]], value: Any) -> dict[str, float | int]:
    entries = value.get("results", value) if isinstance(value, dict) else value
    if not isinstance(entries, list):
        raise ValueError("results must be an array or an object containing results")
    by_case = {item.get("case"): item for item in entries if isinstance(item, dict)}
    exact = checks_correct = checks_total = bound = verified = 0
    for case, wanted in expected.items():
        item = by_case.get(case, {})
        observed = item.get("checks", {})
        exact += observed == wanted
        checks_correct += sum(observed.get(name) is answer for name, answer in wanted.items())
        checks_total += len(wanted)
        bound += bool(item.get("artifact_sha256") and item.get("ir_sha256"))
        verified += item.get("certificate_status") == "verified"
    count = len(expected)
    return {
        "case_count": count,
        "exact_case_accuracy": exact / count,
        "individual_check_accuracy": checks_correct / checks_total,
        "artifact_binding_rate": bound / count,
        "lean_verified_rate": verified / count,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Score direct-Qwen and Noether outputs on the same structural cases"
    )
    parser.add_argument("--direct", required=True)
    parser.add_argument("--harness", required=True)
    parser.add_argument(
        "--fixture", default="examples/dft/structural-v2-evaluation.json"
    )
    options = parser.parse_args()
    fixture = load(options.fixture)
    expected = {
        item["case"]: item["expected_checks"] for item in fixture["cases"]
    }
    print(json.dumps({
        "direct_qwen": score(expected, load(options.direct)),
        "noether_qwen": score(expected, load(options.harness)),
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
