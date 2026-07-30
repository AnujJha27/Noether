# Noether agentic orchestrator examples

These examples are meant to show the workflow shape, not to benchmark model
quality.

## Smoke workflow

This uses the mock provider and bundled Lean fixture project. It should run on a
fresh checkout after `make`:

```bash
make noether-demo
```

## Physics-toy workflow

This file contains richer Lean tasks over `ProofSearch.PhysicsToy`: conservation
laws, record projections, involution, and small algebraic obligations.

Run the deterministic one-command demo:

```bash
./noether demo physics-toy
```

Use the same task file with a real model adapter:

```bash
./noether agentic \
  --provider command \
  --llm-command "/path/to/adapter --model lean-prover" \
  --agents-file examples/orchestrator/agents.research.json \
  --provider-routes examples/orchestrator/provider-routes.example.json \
  --run-dir build/runs/physics-toy \
  --max-rounds 3 \
  < examples/orchestrator/physics-toy-tasks.jsonl

./noether replay build/runs/physics-toy
./noether tui --run-dir build/runs/physics-toy --once
```

`provider-routes.example.json` is a template. Replace the commands/URLs with
your own local or hosted model adapters before using it.
