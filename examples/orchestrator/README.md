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

Run the same demo through OpenRouter's free-model route:

```bash
./noether demo physics-toy --llm openrouter-free
```

The demo command loads `.env` from the repository root. Keep your real
`OPENROUTER_API_KEY` there and commit only `.env.example`.

Run against a cluster-hosted OpenAI-compatible server:

```bash
export NOETHER_OPENAI_BASE_URL="http://cluster-node:8000/v1"
export NOETHER_OPENAI_MODEL="local-lean-coder"
./noether demo physics-toy --llm openai-compatible
```

If the endpoint requires a token:

```bash
export NOETHER_OPENAI_API_KEY="..."
```

For the Maestro cluster, shortcuts are built in:

```bash
# Login node, always-on model
./noether demo physics-toy --llm maestro

# Compute-node models after starting ollama serve through srun
./noether demo physics-toy --llm piano
./noether demo physics-toy --llm sitar
./noether demo physics-toy --llm violin
```

The presets map to:

- `maestro`: `http://127.0.0.1:11434/v1/chat/completions`, `qwen3.6-64k:latest`
- `piano`: `http://pianoteg:11437/v1/chat/completions`, `qwen3.6:27b-q4_K_M`
- `sitar`: `http://sitarteg:11437/v1/chat/completions`, `qwen2.5-coder:14b-instruct-q4_K_M`
- `violin`: `http://violinteg:11437/v1/chat/completions`, `qwen3.6-64k:latest`

By default this uses `OPENROUTER_MODEL=openrouter/free`. You can select a
specific free model with:

```bash
./noether demo physics-toy \
  --llm openrouter-free \
  --model meta-llama/llama-3.2-3b-instruct:free
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
