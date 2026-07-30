# LLM Proof-Search Orchestrator

## Nexus-style search graph

Proof workers are LLM agents, not fixed tactic workers. Each verified attempt
becomes a node containing its complete proof patch, Lean diagnostics, agent,
parent, depth, and progress score. The bounded frontier keeps several diverse
lineages alive. On the next round, each agent receives one frontier node and
repairs or extends that exact attempt; another agent can therefore continue
work started by its predecessor.

The orchestrator now records this as an explicit agentic framework trace:

- `supervisor_decisions`: deterministic per-round decisions, assignments, and
  budget state;
- `agent_turns`: one structured turn per proposer, critic, or decomposer role,
  including inherited node, received handoff, action, status, candidate IDs,
  and errors;
- `handoffs`: end-of-round handoff objects from the agent that produced a
  retained frontier node to the next assigned repair role;
- `handoff_receipts`: explicit receiver accept/refuse records with summary,
  plan, and risks;
- `agent_scorecard`: per-agent turns, candidate counts, verifier outcomes, and
  success rate;
- `model_call_records`: every provider prompt, schema, response/error, agent,
  model route, and call index;
- `memory`: run-scoped failed tactics, useful lemmas, successful proof
  patterns, theorem notes, and score history;
- `task.subgoals`: a dependency DAG supplied by the user or produced by the
  decomposer before proof search.

The critic influences ordering, but Lean remains the only success oracle.
Failed attempts with fewer unsolved goals can remain on the frontier, while
timeouts and worker failures are penalized. Search results include the entire
graph and current frontier.

## Agent registry and permissions

`orchestrator/roles.json` is now a structured agent registry. Legacy
`{"direct": "instructions"}` files still load, but structured entries can
define agent kind, model route, tools, temperature, candidate budget, and
handoff targets:

```json
{
  "direct": {
    "kind": "proposer",
    "model": "default",
    "tools": ["lean_diagnostics", "frontier_read", "candidate_submit"],
    "temperature": 0.2,
    "max_candidates": 2,
    "handoff_targets": ["automation", "structural"],
    "instructions": "Prefer short definitional and simplification proofs."
  }
}
```

Structured agents use exactly their declared tools. Legacy string roles receive
safe default permissions for compatibility. There is intentionally no
`mark_success` tool; only the verifier can return `verified`.

The first-class decomposer can turn a theorem/hypothesis into a subgoal DAG
before proposal rounds. The proposer prompt receives the DAG plus concrete run
memory, not vague chat state.

Persist and resume searches:

```bash
python3 -m orchestrator.cli ... \
  --journal-dir build/search-journal \
  --resume-journal
```

Journal updates are atomic. Resumed tasks restore all patches, diagnostics,
lineage edges, and frontier state before allocating new model calls.

For multi-task durable runs above individual theorem search:

```bash
noether agentic --provider command \
  --llm-command "/path/to/your-model-adapter --model lean-prover" \
  --run-dir build/runs/my-model \
  < tasks.jsonl > results.jsonl
```

The same runner is also available directly:

```bash
python3 -m orchestrator.cli ... \
  --run-dir build/runs/my-model \
  < tasks.jsonl > results.jsonl
```

The run directory contains `state.json`, `events.jsonl`, and per-task artifacts.
Inspect or replay it with:

```bash
noether tui --run-dir build/runs/my-model --once
noether replay build/runs/my-model
```

The orchestrator is a provider-neutral Python 3 layer above `build/proof-search`. It uses multiple LLM roles to generate and rank Lean patches, asks the C++ service to verify them, and feeds Lean diagnostics into later repair rounds.

It uses only Python's standard library and runs directly in WSL—no `pip install` or virtual environment is required.

## WSL smoke test

From the repository root:

```bash
make
make wsl-smoke
./noether demo physics-toy
```

The smoke test uses a deterministic mock LLM and the real C++/Lean verifier. It validates the complete process and pipe wiring but does not test model quality.

For a richer deterministic trace over bundled physics-flavored Lean tasks:

```bash
./noether demo physics-toy
./noether replay build/runs/noether-physics-toy
./noether tui --run-dir build/runs/noether-physics-toy --once
```

Run the fast orchestration unit tests with:

```bash
make orchestrator-test
```

For artifact reproduction, run the top-level sequence in
[REPRODUCIBILITY.md](REPRODUCIBILITY.md).

## Task protocol

The CLI reads one JSON task per input line and emits one complete search result per line:

```json
{
  "id": "search-42",
  "project": "sample",
  "module": "ProofSearch.Examples",
  "target": "ProofSearch.Examples.add_zero",
  "theorem": "theorem add_zero (n : Nat) : n + 0 = n",
  "context": "Natural-number addition from the bundled project.",
  "limits": {
    "wall_time_ms": 30000,
    "memory_mb": 8192
  }
}
```

`theorem` is both prompt context and the body-free declaration used to recreate the candidate's binder context. `module` is imported by Lean. `target` is authoritative: the verifier checks that the candidate's complete type exactly matches it.

## Connect an LLM

### Command adapter

Run any executable that accepts one provider envelope on standard input and prints one JSON object on standard output:

```bash
python3 -m orchestrator.cli \
  --provider command \
  --llm-command "/path/to/your-model-adapter --model lean-prover" \
  < tasks.jsonl > results.jsonl
```

The adapter receives:

```json
{
  "agent": "direct",
  "system": "role instructions",
  "prompt": "the proof-search prompt",
  "schema": {"type": "object"}
}
```

Proposers must return:

```json
{"candidates":[{"patch":"by rfl","rationale":"definitional reduction"}]}
```

The critic must return:

```json
{"ordered_ids":["search-42-r1-direct-1"],"feedback":"shortest candidate first"}
```

The decomposer must return:

```json
{"subgoals":[{"id":"lemma-a","theorem":"theorem a : True","depends_on":[]}]}
```

This small contract keeps model SDKs, authentication, and vendor-specific response formats outside the search engine. The command can call a local WSL model, a Windows executable through `/mnt/c`, or a hosted-model SDK.

### HTTP gateway

An HTTP gateway can implement the identical JSON contract:

```bash
export LLM_API_TOKEN="your-token"
python3 -m orchestrator.cli \
  --provider http \
  --llm-url http://127.0.0.1:8080/generate \
  < tasks.jsonl > results.jsonl
```

The token is optional and is sent as a bearer token. The endpoint must return the proposer or critic JSON object directly.

## Search policy and budgets

Every round runs three proposer roles:

- `direct`: short exact, constructor, rewrite, and simplification proofs;
- `automation`: tactic and library automation;
- `structural`: introductions, cases, induction, and intermediate facts.

A critic ranks unique candidates before they are sent as one `search_batch`. Failed Lean diagnostics are included in the next round's prompts. The first verified candidate ends the search by default.

Useful CLI controls:

```text
--max-rounds 3
--candidates-per-agent 2
--max-model-calls 20
--max-candidates 24
--agent-parallelism 3
--verify-parallelism 4
--frontier-width 6
--provider-timeout-s 120
--agents-file orchestrator/roles.json
--roles-file orchestrator/roles.json
```

The result includes every candidate, Lean status and diagnostics, critic events, cache flags, model-call count, and the winning patch. `sorry` and `admit` candidates are rejected before verification.

Agent names, tool permissions, strategy instructions, model routes, and handoff
targets are data in `orchestrator/roles.json`, not branches in the engine.
Supply another JSON object with `--agents-file` to add, remove, or replace
agents without changing code.

## Provider routing

Agent `model` fields can route to different provider adapters. The default
provider still comes from `--provider`, while `--provider-routes` supplies
overrides by model name:

```json
{
  "fast-local": {
    "provider": "command",
    "command": ["/path/to/adapter", "--model", "fast-local"],
    "timeout_s": 60
  },
  "critic-hosted": {
    "provider": "http",
    "url": "http://127.0.0.1:8080/generate",
    "token_env": "LLM_API_TOKEN",
    "timeout_s": 120
  }
}
```

Then set an agent to `"model": "fast-local"` or `"model": "critic-hosted"`.
Replay artifacts record the selected model route for every call.
