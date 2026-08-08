from __future__ import annotations

import argparse
from pathlib import Path

import torch

from structural_gnns import (
    AllFailuresRingGNN,
    CertifiedRingGNN,
    IdentityOperatorRingGNN,
    SmoothXCGNN,
    TooShallowRingGNN,
    UnconstrainedOperatorGNN,
    ZeroOperatorRingGNN,
)


MODELS = {
    "certified-ring": CertifiedRingGNN,
    "too-shallow-ring": TooShallowRingGNN,
    "unconstrained-operator": UnconstrainedOperatorGNN,
    "smooth-xc": SmoothXCGNN,
    "identity-operator-ring": IdentityOperatorRingGNN,
    "zero-operator-ring": ZeroOperatorRingGNN,
    "all-failures-ring": AllFailuresRingGNN,
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Export Noether Structural V2 demo models")
    parser.add_argument("--output-dir", default="build/structural-v2-models")
    options = parser.parse_args()
    output = Path(options.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    example = (torch.randn(6, 1),)
    for name, factory in MODELS.items():
        model = factory().eval()
        program = torch.export.export(model, example)
        destination = output / f"{name}.pt2"
        torch.export.save(program, destination)
        print(destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
