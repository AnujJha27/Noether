# Lean Proof-Search Service Roadmap

## Purpose

Build a local C++ service that accepts Lean proof attempts from other programs, checks them with Lean, and returns structured verification results. The service is a reliable verifier and coordinator; it does not generate proofs itself.

## Implementation status

V1 is implemented in this repository: JSONL verification and batches, bounded Lean workers, cancellation, process limits, SQLite caching and lineage, tests, and benchmarks are available through the documented Make targets.

The separate provider-neutral LLM orchestration layer is implemented. It calls this verifier and owns parallel proposer roles, critic ranking, diagnostic-driven retries, budgets, command/HTTP model integration, and full search traces. First-class dependency-aware theorem decomposition remains future work.

The next product track is architecture-level DFT certification from
user-confirmed English descriptions or sandbox-extracted `torch.export`
artifacts. The agreed design, trust boundary, security requirements, and
milestones are in [DFT_INTEGRATION_PLAN.md](DFT_INTEGRATION_PLAN.md).

Its first implementation slice is complete: configurable policy validation,
canonical hash-bound manifests, English draft/confirmation, safe static PT2
inspection, fail-closed graph extraction control, extraction-result provenance,
policy-driven obligation generation, exact certificate checking, and
project/toolchain/policy worker-context isolation. Broader graph analyzers and
public-upload hardening remain future work.

## V1: Local Lean verifier

Goal: reliably check externally supplied Lean proof patches on one machine.

### 1. Project foundation

- Add a `Makefile`, C++17 source layout, test layout, and bundled Lean/Lake example project.
- Confirm `make`, `make test`, and `lake env lean` work locally.

### 2. Single-request verifier

- Read JSON Lines from standard input.
- Validate `verify` requests.
- Write a temporary Lean check file from a target theorem and proposed proof.
- Run Lean and return `verified` or `lean_error`.

### 3. Reliable process handling

- Capture Lean stdout and stderr.
- Add wall-clock timeout, CPU limit, memory limit, process groups, and child cleanup.
- Return stable `timeout`, `memory_limit`, and `worker_failure` statuses.

### 4. Parallel candidate checks

- Add a bounded worker pool.
- Implement `search_batch`.
- Support cancellation and `stop_on_first_success`.

### 5. Persistent cache and attempt history

- Add an SQLite cache keyed by toolchain, project, and proof content.
- Store attempt IDs, parent attempts, and subgoal links.
- Cache successful and ordinary Lean-error results.

### 6. Tests and benchmarks

- Add valid, invalid, timeout, memory, cache, and concurrency fixtures.
- Add `make benchmark`.
- Record throughput, p50/p95 latency, cache-hit rate, and failure counts.

## V1 completion criteria

- A client can submit one proof or a parallel candidate batch over JSON Lines.
- Lean checks run under configured time and memory limits.
- No orphan Lean processes remain after success, failure, cancellation, or shutdown.
- The SQLite cache works across restarts.
- Tests and benchmarks run through Make targets.

## V1.1: Usability and debugging

- Human-readable CLI output in addition to JSON.
- Better extraction of Lean locations and error messages.
- Request logging and optional per-job artifact retention on failure.
- Config file for worker count, database location, project path, and default limits.
- Graceful shutdown: stop accepting work, cancel queued jobs, and clean up active workers.

## V2: Better proof-search coordination

- Support project paths outside the bundled sample project.
- Allow full source-file patches in addition to theorem-proof replacements.
- Add first-class subgoal/task records with dependencies and status views.
- Add a queue API for long-running agent workflows.
- Add priority scheduling and per-agent quotas.
- Add an HTTP adapter built on the same core as the JSON Lines interface.
- Extend the implemented LLM-agent orchestrator with first-class dependency-aware theorem decomposition.
- Add optional provider packages for popular local and hosted models while keeping the core provider-neutral.

## DFT architecture certification

- Use a configurable `dft-architecture-v1` policy backed by the external
  `Testv2` Lean project.
- Require XC derivative-discontinuity compatibility, spatial
  coverage/nonlocality compatibility, and self-adjointness.
- Translate English descriptions into draft manifests and require explicit
  user confirmation before generating obligations.
- Accept `torch.export` artifacts plus representative input and dynamic-shape
  constraints; do not execute arbitrary Python or load unsafe checkpoints in
  V1.
- Record field-level evidence provenance and bind reports to artifact,
  manifest, policy, project, toolchain, proof, and certificate hashes.
- Require an exact named Lean certificate rather than approving any module
  that happens to compile.
- Maintain one isolated worker/cache context per project, toolchain, and policy
  fingerprint.
- Treat all public uploads as hostile and complete sandbox hardening before
  enabling multi-tenant ingestion.

## V3: Faster Lean interaction

- Reuse prepared project snapshots where safe.
- Add more precise cache invalidation based on imported modules and source fingerprints.
- Explore long-lived Lean workers or Lean server integration.
- Measure cold-start cost separately from proof-check cost.
- Add distributed worker execution only after the single-host design is stable.

## V4: Stronger sandboxing and production operation

This work is a release gate for arbitrary public uploads and must be pulled
forward before multi-tenant DFT ingestion, even if V3 performance work remains
unfinished.

- Run workers in cgroups or containers.
- Add disk-space limits and network isolation.
- Add authentication if exposing HTTP beyond localhost.
- Export Prometheus-style metrics and structured logs.
- Add retention policies and database migrations.

## Defaults

- Build system: GNU Make.
- Language: C++17.
- Transport: JSON Lines over stdin/stdout.
- Storage: local SQLite.
- Execution model: one isolated Lean process per verification job.
- Scope: trusted local development tool, not a network-exposed or multi-tenant service.
