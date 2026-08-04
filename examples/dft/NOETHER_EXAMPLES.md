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

## DFT demo carousel

Use named scenarios when presenting the DFT workflow:

```bash
# Full agentic Lean proof search over the reviewed canonical architecture.
./noether demo dft --scenario certified --llm maestro --run-dir build/runs/dft-certified

# A stated non-self-adjoint operator: rejected by the policy before proof search.
./noether demo dft --scenario non-self-adjoint --run-dir build/runs/dft-non-self-adjoint

# Required assumptions are absent: deliberately inconclusive.
./noether demo dft --scenario missing-assumptions --run-dir build/runs/dft-missing

# All three claims are present, but no reviewed Lean architecture profile exists yet.
./noether demo dft --scenario formalization-gap --run-dir build/runs/dft-gap
```

Inspect any case with `./noether tui --run-dir <run-directory>`. The three
non-certified scenarios are deterministic policy fixtures and intentionally do
not invoke proof search.

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

## End-to-end three-hop GNN demo

This is the reviewed presentation architecture from the verifier material: a
four-site chain, three message-passing hops, the required endpoint coupling
`0 → 3`, a symmetric residual kernel, and the hinge XC functional. The LLM
first extracts the English claims; review the resulting draft before using the
checked facts and architecture IR to start proof search.

```bash
./noether assess dft \
  --description examples/dft/gnn-3hop-description.txt \
  --model-id chain4-gnn \
  --llm maestro \
  --run-dir build/runs/chain4-gnn-assess

./noether certify \
  --run-dir build/runs/chain4-gnn-certify \
  --description examples/dft/gnn-3hop-description.txt \
  --model-id chain4-gnn \
  --facts examples/dft/gnn-3hop-facts.json \
  --architecture-ir examples/dft/gnn-3hop-architecture-ir.json \
  --project examples/dft/lean \
  --llm-command "python3 examples/orchestrator/openai_compatible_adapter.py"
```

For `maestro`, the certificate command uses the same adapter environment as
the demo command:

```bash
export NOETHER_OPENAI_BASE_URL=http://127.0.0.1:11434/v1/chat/completions
export NOETHER_OPENAI_MODEL=qwen3.6-64k:latest
```

`certify` deliberately requires the reviewed facts and IR; the assessment
LLM cannot silently confirm its own interpretation.

For the fuller six-site ring from the Beamer presentation, substitute the
three `gnn-ring6-3hop-*` files above. It keeps the same three-hop antipodal
coupling (`0 → 3`) but has two equally short paths around the ring.

For the one-command bundled demos, use:

```bash
./noether demo physics-toy --llm maestro
./noether demo physics-toy --llm piano
./noether demo physics-toy --llm sitar
./noether demo physics-toy --llm violin
```
