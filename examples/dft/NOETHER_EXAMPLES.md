# Noether examples for the DFT policy library

These examples are specific to the DFT V1 policy profile in
`policies/dft-architecture-v1.json`.

## Inspect the context

The canonical example manifest is:

```bash
python3 -m dftcert.cli sanity-report \
  --manifest examples/dft/example-manifest.json \
  --proof-results examples/dft/example-proof-results.json
```

The three proof-search obligations are checked against the external
`Testv2.Verifier` Lean project selected by the policy profile.

## Generate fresh obligations

```bash
python3 -m dftcert.cli generate-obligations \
  --manifest examples/dft/example-manifest.json \
  --jsonl
```

The checked-in file `examples/dft/noether-obligations.jsonl` is the same style
of task object, with extra `context` and `subgoals` fields for the agentic
orchestrator.

## Run the deterministic demo adapter

This demonstrates the orchestration trace and verifier boundary without needing
a live LLM. By default it uses the vendored `Testv2` snapshot in
`examples/dft/lean`.

```bash
make
cd examples/dft/lean
lake update mathlib
lake exe cache get
lake build Testv2.Verifier
cd ../../..
./noether demo dft

./noether replay build/runs/noether-dft
./noether tui --run-dir build/runs/noether-dft --once
```

To test against an external `Testv2` checkout instead, pass `--project` or set
`DFT_PROJECT`.

If this is the first time using the vendored snapshot on a machine, resolve the
Lean 4.31 Mathlib manifest before fetching caches:

```bash
cd examples/dft/lean
lake update mathlib
lake exe cache get
lake build Testv2.Verifier
```

## Run with a real model

Use the same tasks, but replace the deterministic adapter with your model
adapter and optional model routing:

```bash
PROOF_SEARCH_ALLOW_GENERATED_OBLIGATIONS=1 \
PROOF_SEARCH_PROJECT_DIR=examples/dft/lean \
PROOF_SEARCH_DB=build/dft-real-model.db \
./noether agentic \
  --provider command \
  --llm-command "/path/to/adapter --model lean-prover" \
  --agents-file examples/orchestrator/agents.research.json \
  --provider-routes examples/orchestrator/provider-routes.example.json \
  --verifier ./build/proof-search \
  --run-dir build/runs/dft-real-model \
  --max-rounds 3 \
  < examples/dft/noether-obligations.jsonl
```

On the Maestro cluster, use the one-command local-model presets:

```bash
./noether demo dft --llm maestro
./noether demo dft --llm piano
./noether demo dft --llm sitar
./noether demo dft --llm violin
```

For the one-command bundled demos, use:

```bash
./noether demo physics-toy --llm maestro
./noether demo physics-toy --llm piano
./noether demo physics-toy --llm sitar
./noether demo physics-toy --llm violin
```
