# VISTA Structural V2 evaluation

This is an artifact-grounding evaluation, not a test of physical derivative discontinuities or LLM proof search. `corpus_manifest.json` is independently authored ground truth; `corpus_models.py` only constructs artifacts.

Run from the repository root in the frozen PyTorch/Lean environment:

```bash
python evaluation/structural_v2/run.py --generate
```

It exports 36 PT2 artifacts under `build/vista-structural-v2-corpus`, runs each three times through the production extractor, `dftcert.structural` lowering, translation validator, policy assessment, obligation compiler, and certificate checker, and writes `evaluation/structural_v2/results/latest/`. Each case has raw extraction, contracts, derivations, IR, validation, policy, obligations, Lean/certificate evidence, and tampering records. `score.py` writes CSV, JSON, and Markdown tables.

The 24 development and 12 held-out cases are fixed in the manifest. Unexpected outcomes remain in the result bundle; do not revise semantic rules or labels in place. Create a new experiment condition after any semantic-rule change.
