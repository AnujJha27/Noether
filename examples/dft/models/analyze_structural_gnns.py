from __future__ import annotations

import argparse
import json
from pathlib import Path

from dftcert.structural import (
    assess_structural_ir,
    generate_structural_obligations,
    structural_ir_from_inventory,
)
from extractors.torch_export_worker import extract


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze exported VISTA V2 demo models")
    parser.add_argument("model_dir")
    parser.add_argument(
        "--constraints",
        default="examples/dft/structural-v2-input-constraints.json",
    )
    parser.add_argument("--output-dir", default="build/structural-v2-analysis")
    options = parser.parse_args()
    constraints = json.loads(Path(options.constraints).read_text(encoding="utf-8"))
    output = Path(options.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    summaries = []
    for artifact in sorted(Path(options.model_dir).glob("*.pt2")):
        extracted = extract(artifact)
        ir = structural_ir_from_inventory(
            inventory=extracted["inventory"],
            artifact_sha256=extracted["artifact_sha256"],
            extractor_version=extracted["extractor_version"],
            input_constraints=constraints,
        )
        assessment = assess_structural_ir(ir)
        obligations = generate_structural_obligations(ir)
        result = {"ir": ir, "assessment": assessment, "generation": obligations}
        destination = output / f"{artifact.stem}.json"
        destination.write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        summaries.append({
            "artifact": str(artifact),
            "status": assessment["status"],
            "checks": {
                name: check["satisfied"] for name, check in assessment["checks"].items()
            },
            "output": str(destination),
        })
    print(json.dumps(summaries, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
