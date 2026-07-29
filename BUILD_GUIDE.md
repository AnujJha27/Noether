# Lean Proof-Search Service: Build Guide

## What you are building

A local C++ service that receives Lean proof attempts from other programs, checks them with Lean, and reports whether they compile. It handles many attempts at once, limits runaway checks, caches repeated work, and measures performance.

Another program or agent supplies the theorem, proposed Lean proof patch, and optional smaller subgoals. This service is the authoritative Lean verifier; it does not generate proofs.

## Target layout

```text
proof-search-engine/
  Makefile
  README.md
  ROADMAP.md
  BUILD_GUIDE.md
  lean/
    lakefile.toml
    lean-toolchain
    ProofSearch/
      Examples.lean
  src/
    main.cpp
    protocol.cpp
    worker_pool.cpp
    lean_runner.cpp
    cache.cpp
    benchmark.cpp
  include/
    protocol.hpp
    worker_pool.hpp
    lean_runner.hpp
    cache.hpp
  tests/
    fixtures/
    protocol_tests.cpp
    cache_tests.cpp
    integration_tests.cpp
```

Use C++17 or newer, `g++` or `clang++`, SQLite, and a JSON library such as `nlohmann/json`.

The Makefile should provide:

```make
make            # build the service
make test       # build and run tests
make benchmark  # run the benchmark suite
make clean      # remove local build output
```

Compile into `build/`. Use warning and debug flags by default, such as `-std=c++17 -Wall -Wextra -Wpedantic -g`. Offer `make RELEASE=1` for optimized builds.

## Step 0: Install prerequisites

Install:

- `g++` or `clang++` with C++17 support;
- GNU Make;
- Lean and `lake` through `elan`;
- SQLite development headers and library;
- `nlohmann/json` headers;
- a test framework, preferably Catch2 or GoogleTest.

Check the installation:

```bash
g++ --version
make --version
lean --version
lake --version
sqlite3 --version
```

All commands should succeed before continuing.

## Step 1: Create the build skeleton

Create the source, include, test, fixture, Lean, and `build/` directories shown in the target layout. Add the Makefile targets above and make `make` build `build/proof-search`.

Checkpoint:

```bash
make
```

Expected result: the executable `build/proof-search` exists.

## Step 2: Add the bundled Lean project

Add `lean/lean-toolchain`, `lean/lakefile.toml`, and `lean/ProofSearch/Examples.lean`. Start with a simple theorem:

```lean
theorem add_zero (n : Nat) : n + 0 = n := by
  rfl
```

Checkpoint:

```bash
cd lean
lake env lean ProofSearch/Examples.lean
```

Expected result: Lean exits successfully with no errors.

## Step 3: Implement the JSON Lines loop

In `main.cpp`:

1. Read standard input one line at a time.
2. Parse each line as JSON.
3. Validate `version`, `id`, and `type`.
4. Write exactly one JSON response line for each request.
5. Do not exit because one request is malformed.

Implement `ping` first:

```json
{"version":1,"id":"one","type":"ping"}
```

Expected response:

```json
{"version":1,"id":"one","status":"ok"}
```

## Step 4: Define the verification protocol

A `verify` request should use this shape:

```json
{
  "version": 1,
  "id": "attempt-42",
  "type": "verify",
  "project": "bundled",
  "module": "ProofSearch.Examples",
  "declaration": "theorem add_zero (n : Nat) : n + 0 = n",
  "target": "ProofSearch.Examples.add_zero",
  "patch": "by simp",
  "limits": {
    "wall_time_ms": 5000,
    "cpu_time_s": 4,
    "memory_mb": 2048
  }
}
```

Use these response statuses:

- `verified`: Lean accepted the proof.
- `lean_error`: Lean ran normally but rejected the code.
- `timeout`: wall-clock or CPU limit was reached.
- `memory_limit`: the process exceeded its memory limit.
- `worker_failure`: Lean could not be started, crashed, or returned an unexpected failure.
- `invalid_request`: malformed JSON or missing/invalid fields.
- `cancelled`: work was stopped by the client or because another candidate succeeded.

## Step 5: Implement one Lean verification job

Create `lean_runner.cpp`.

For every `verify` request:

1. Create a unique directory below `/tmp/proof-search-engine/`.
2. Write a temporary Lean source file there.
3. Import the request's `module` and recreate the body-free `declaration` under a fresh name.
4. Insert the submitted proof patch.
5. Require Lean to type-check the fresh theorem against `type_of% target`.
6. Execute `lake env lean <temporary-file>`.
7. Capture exit code, stdout, stderr, and elapsed time.
8. Delete the temporary directory after collecting results.

Start with a fixed target theorem. Add arbitrary target lookup only after this works.

Checkpoint:

- A valid `by rfl` patch returns `verified`.
- An invalid patch returns `lean_error`.

## Step 6: Classify Lean output

Initially map:

- exit code zero to `verified`;
- ordinary Lean diagnostics to `lean_error`;
- start or unexpected process failure to `worker_failure`.

Return raw stderr at first. Later, parse diagnostics into message, severity, line, and column fields.

Checkpoint: integration tests assert the status field, not only a text substring.

## Step 7: Add limits and cleanup

In the child process before `exec`:

- call `setpgid` to create a process group;
- apply `RLIMIT_CPU`;
- apply `RLIMIT_AS`.

In the parent:

- track the job start time;
- poll with `waitpid(..., WNOHANG)`;
- kill the whole process group when wall time expires;
- wait until the child is reaped.

Checkpoint:

- A deliberately slow fixture returns `timeout`.
- No Lean process from that job remains after the response is returned.

## Step 8: Add a bounded worker pool

Create `worker_pool.cpp`.

- Default worker count: `max(1, hardware_concurrency() - 1)`.
- Keep a queue of pending jobs.
- Never run more Lean jobs than the configured worker count.
- Send completed results back to the JSON response layer.

Checkpoint: submit more work than workers and verify active Lean process count never exceeds the limit.

## Step 9: Implement `search_batch`

Accept a target and multiple candidate proof patches:

```json
{
  "version": 1,
  "id": "batch-7",
  "type": "search_batch",
  "project": "bundled",
  "module": "ProofSearch.Examples",
  "declaration": "theorem add_zero (n : Nat) : n + 0 = n",
  "target": "ProofSearch.Examples.add_zero",
  "candidates": [
    { "id": "a", "patch": "by simp" },
    { "id": "b", "patch": "by omega" }
  ],
  "max_parallel": 4,
  "stop_on_first_success": true
}
```

Turn each candidate into a normal verification job. When `stop_on_first_success` is enabled, cancel queued jobs and terminate active siblings after the first valid proof.

Checkpoint: a batch with one valid and several slow candidates returns the valid proof and marks remaining candidates `cancelled`.

## Step 10: Add the SQLite cache

Create `cache.cpp` and open `proof_search.db` in the project data directory.

Create these tables:

```text
verification_cache
  cache_key PRIMARY KEY
  status
  diagnostics_json
  elapsed_ms
  created_at

attempts
  attempt_id PRIMARY KEY
  cache_key
  target
  parent_attempt_id NULL
  status
  submitted_at

subgoal_links
  parent_attempt_id
  child_attempt_id
  description
```

The cache key includes the toolchain fingerprint, project fingerprint, target, patch, and relevant limits. Cache `verified` and `lean_error`, but do not initially cache timeouts, memory failures, or worker failures.

Checkpoint: submit the same valid request twice. The second response has `"cached": true`.

## Step 11: Add subgoal lineage

Allow requests to include `parent_attempt_id` and store parent-child relationships in SQLite. A checked child lemma is useful evidence but does not solve the parent automatically. A parent is solved only when Lean accepts its complete proof patch.

Checkpoint: inspect the database and reconstruct an agent's decomposition tree.

## Step 12: Add tests

Write:

- protocol unit tests;
- cache unit tests;
- process-limit integration tests;
- batch and cancellation tests;
- bundled Lean fixture tests.

`make test` should build and run all tests without manual setup.

## Step 13: Add benchmarks

Create fixtures for valid proofs, syntax/type errors, unfinished proofs, timeouts, memory pressure, and repeated cache hits. `make benchmark` should print and save:

- total attempts and verified attempts;
- checks per second;
- p50 and p95 latency;
- cold-cache and warm-cache results;
- failure counts grouped by status;
- worker count and configured limits.

Save benchmark output as JSON or CSV so it can be compared over time.

## Definition of done for V1

- `make` builds the service.
- `make test` runs all tests.
- `make benchmark` produces performance metrics.
- JSON Lines requests receive structured responses.
- Valid and invalid proofs are classified correctly.
- Timeouts and memory limits stop runaway checks without leaving processes behind.
- Concurrent work respects the worker limit.
- Repeated requests use SQLite cache entries.
- Batch verification can stop at the first accepted proof.
