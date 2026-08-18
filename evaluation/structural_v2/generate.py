"""Generate only the corpus PT2 artifacts; labels live independently in corpus_manifest.json."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
import torch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from corpus_models import make_model

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", default=HERE / "corpus_manifest.json", type=Path)
    parser.add_argument("--output-dir", default=HERE.parent.parent / "build" / "vista-structural-v2-corpus", type=Path)
    options = parser.parse_args()
    manifest = json.loads(options.manifest.read_text())
    options.output_dir.mkdir(parents=True, exist_ok=True)
    for case in manifest["cases"]:
        model = make_model(case["model"]).eval()
        torch.export.save(torch.export.export(model, (torch.randn(case["model"]["sites"], 1),)), options.output_dir / f'{case["id"]}.pt2')
    return 0

if __name__ == "__main__": raise SystemExit(main())
