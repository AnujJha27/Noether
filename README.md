# Noether

Noether is a local research prototype for Lean proof-attempt verification,
LLM-driven proof-search orchestration, and policy-driven DFT architecture
certification. The key boundary is simple: LLMs and extraction tools can propose
claims or proof patches, but Lean is the authoritative proof checker.

The C++17 verifier accepts JSON Lines on standard input, runs Lean in isolated
process groups, supports bounded parallel candidate checking and cancellation,
caches deterministic results in SQLite, records subgoal lineage, and benchmarks
throughput and failure modes. The Python orchestration layer owns proposer
roles, critic ranking, diagnostic-driven repair rounds, provider adapters, and
resumable search traces.

The DFT certification slice uses versioned policy bundles, canonical manifests,
field-level provenance, generated Lean obligations, and exact hash-bound final
certificate checks. It is a local prototype, not a public upload service.

## Repository status

Implemented and covered by tests:

- bundled Lean verifier service;
- bounded batch verification and cancellation;
- SQLite cache and attempt history;
- provider-neutral LLM orchestrator with command, HTTP, and mock providers;
- structured agent registry, tool permissions, task queues, run-scoped memory,
  handoff receipts, replay, and terminal trace inspection;
- English-draft and confirmation workflow for DFT manifests;
- PT2 container validation and fail-closed sandbox controller tests;
- policy-driven generated obligations;
- verified-winner certificate assembly;
- exact named-certificate checking for the example policy.

Known limits:

- public/multi-tenant uploads are out of scope until the container/cgroup
  sandboxing requirements in `DFT_INTEGRATION_PLAN.md` are implemented;
- the DFT example certificate depends on an external Lean/Testv2 project
  supplied through `DFT_PROJECT`;
- the default benchmark is a smoke benchmark, not a full paper-scale evaluation.

## Build and run

```bash
make
make test
make benchmark
make clean
```

Lean is installed through `elan`. The Makefile discovers Lake from `PATH` or the current account's `.elan/bin` directory.

Start the service from the repository root:

```bash
./build/proof-search
```

Each input line receives exactly one JSON response line. A malformed request does not stop the service.

```json
{"version":1,"id":"health","type":"ping"}
{"version":1,"id":"attempt-1","type":"verify","project":"sample","module":"ProofSearch.Examples","declaration":"theorem client_name (n : Nat) : n + 0 = n","target":"ProofSearch.Examples.add_zero","patch":"by rfl"}
{"version":1,"id":"batch-1","type":"search_batch","project":"sample","module":"ProofSearch.Examples","declaration":"theorem client_name (n : Nat) : n + 0 = n","target":"ProofSearch.Examples.add_zero","candidates":[{"id":"candidate-a","patch":"by rfl"},{"id":"candidate-b","patch":"by simp"}],"max_parallel":2,"stop_on_first_success":true}
```

Optional environment variables are `PROOF_SEARCH_WORKERS`, `PROOF_SEARCH_DB`, `PROOF_SEARCH_PROJECT_DIR`, and `PROOF_SEARCH_LAKE`.

There is no target-name registry in the verifier. `module` selects the import, while `declaration` supplies the body-free theorem statement and local binder context. Lean compiles a fresh candidate declaration and then checks its complete type against `type_of% target`; a client cannot verify a patch for a weaker or unrelated statement.

## Architecture boundary

The service's worker pool contains Lean verification jobs, not LLM agents. The intended complete system is:

```text
LLM proof-search agents
        │ candidate patches, parent/subgoal IDs
        ▼
agent orchestration layer
        │ JSONL verify/search_batch
        ▼
this C++ service ── bounded workers ── isolated Lean processes
```

The orchestration layer is now implemented in the `orchestrator/` Python package. It owns structured agent roles, tool permissions, decomposition, parallel proposers, critic ranking, diagnostic-driven repair rounds, durable run state, model-provider routing, handoffs, replay, and terminal trace inspection. `search_batch`, `parent_attempt_id`, and `subgoal_links` are its verifier integration points. See [ORCHESTRATOR.md](ORCHESTRATOR.md) for WSL setup and provider contracts.

Run an agentic proof-search workflow over JSONL tasks:

```bash
noether agentic --provider mock --run-dir build/runs/demo < tasks.jsonl
noether replay build/runs/demo
noether tui --run-dir build/runs/demo --once
```

Run the bundled one-command demo:

```bash
make noether-demo
# or directly:
./noether demo physics-toy
```

Run the demo through a free-model API route:

```bash
./noether demo physics-toy --llm openrouter-free
```

Noether loads `.env` from the repo root for demo credentials. Keep real keys in
`.env`; commit only `.env.example`.

Run it against a cluster-hosted OpenAI-compatible model:

```bash
export NOETHER_OPENAI_BASE_URL="http://cluster-node:8000/v1"
export NOETHER_OPENAI_MODEL="local-lean-coder"
./noether demo physics-toy --llm openai-compatible
```

On the Maestro cluster, use the built-in presets:

```bash
./noether demo physics-toy --llm maestro
./noether demo physics-toy --llm piano
./noether demo physics-toy --llm sitar
./noether demo physics-toy --llm violin
```

Run its WSL end-to-end smoke test with:

```bash
make wsl-smoke
```

For a clean reproduction checklist, see [REPRODUCIBILITY.md](REPRODUCIBILITY.md).

Draft a physicist-facing sanity report from a hypothesis:

```bash
make sanity-demo
```

Run the terminal UI:

```bash
make tui
```

Render a later-stage artifact report:

```bash
python3 -m dftcert.tui --once \
  --manifest examples/dft/example-manifest.json \
  --proof-results examples/dft/example-proof-results.json
```

## Runtime limits

Jobs use process groups plus wall-clock, CPU (`RLIMIT_CPU`), and virtual address-space (`RLIMIT_AS`) limits. Lean 4.31 reserves substantial virtual address space at startup, so the local defaults are 15 seconds and 4096 MB; clients can override all values in the request's `limits` object. Deterministic `verified` and `lean_error` results are cached; resource and worker failures are not.

## Documentation

- [Roadmap](ROADMAP.md)
- [Reproducibility guide](REPRODUCIBILITY.md)
- [Step-by-step build guide](BUILD_GUIDE.md)
- [LLM orchestrator and WSL guide](ORCHESTRATOR.md)
- [DFT architecture certification plan](DFT_INTEGRATION_PLAN.md)
- [DFT certification prototype](DFT_CERTIFICATION.md)
- [Contribution guide](CONTRIBUTING.md)

## V1 defaults

- GNU Make and C++17
- JSON Lines over stdin/stdout
- SQLite cache
- One isolated Lean process per verification job
- Trusted local development use
