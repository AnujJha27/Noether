# Noether examples for the DFT policy library

These examples are specific to the DFT V1 policy profile in
`policies/dft-architecture-v1.json`.

## Inspect the context

The canonical example manifest is:

```bash
python3 -m dftcert.cli report \
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
a live LLM. It still requires `DFT_PROJECT` to point at a compatible local
`Testv2` Lean project.

```bash
make

PROOF_SEARCH_ALLOW_GENERATED_OBLIGATIONS=1 \
PROOF_SEARCH_PROJECT_DIR="$DFT_PROJECT" \
PROOF_SEARCH_DB=build/dft-noether-demo.db \
./noether agentic \
  --provider command \
  --llm-command "python3 examples/orchestrator/noether_demo_llm.py" \
  --verifier ./build/proof-search \
  --agents-file examples/orchestrator/agents.research.json \
  --run-dir build/runs/dft-noether-demo \
  --max-rounds 1 \
  < examples/dft/noether-obligations.jsonl

./noether replay build/runs/dft-noether-demo
./noether tui --run-dir build/runs/dft-noether-demo --once
```

## Run with a real model

Use the same tasks, but replace the deterministic adapter with your model
adapter and optional model routing:

```bash
PROOF_SEARCH_ALLOW_GENERATED_OBLIGATIONS=1 \
PROOF_SEARCH_PROJECT_DIR="$DFT_PROJECT" \
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
