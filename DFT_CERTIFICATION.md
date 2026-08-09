# Legacy DFT V1 certification prototype

This document describes the retained V1 policy pipeline under
`dftcert.legacy`. Structural V2 is the primary architecture; see
[the Structural V2 workflow](examples/dft/STRUCTURAL_V2.md) and its
[translation specification](STRUCTURAL_V2_TRANSLATION_SPEC.md).

This implementation is the first executable slice of
[DFT_INTEGRATION_PLAN.md](DFT_INTEGRATION_PLAN.md). It establishes the trust
boundary and a policy-driven path into model-specific proof search.

## What is implemented

- versioned, validated policy bundles;
- the `dft-architecture-v1` policy with three mandatory obligations;
- canonical JSON manifests with SHA-256 integrity;
- field-level evidence provenance;
- LLM-assisted English interpretation that always produces a draft;
- mandatory explicit confirmation for English input;
- static PT2 ZIP validation with traversal, expansion, entry-count, and
  compression-ratio limits;
- a no-network, read-only bubblewrap extraction controller that fails closed;
- a `torch.export` graph-inventory worker whose output is artifact-hash bound;
- pending and partial extraction states;
- import of results from a separately sandboxed graph extractor;
- exact named-certificate and exact-type checking;
- manifest-hash binding in the proof-bearing Lean source;
- one persistent verifier/cache context per project/toolchain/policy
  fingerprint;
- policy-selected, hash-bound generated Lean obligations;
- LLM proof search over generated obligations through an explicitly gated
  verifier mode;
- a resumable Nexus-style proof graph where successor agents inherit promising
  patches and exact Lean diagnostics;
- verified-winner assembly into a final hash-bound Lean certificate and report;
- atomic local run directories, hash-chained event journals, resumable Nexus
  state, and signed sandbox attestations;
- refusal to compile untrusted certificates before a real container sandbox is
  active.

User confirmation and graph extraction do not constitute proofs. `assess`
returns `proof_required` until the generated Lean obligations and final
certificate have been checked.

## Policy

The initial policy is [policies/dft-architecture-v1.json](policies/dft-architecture-v1.json).
Its domain choices are data rather than branches in the verifier. It points to
the `Testv2` Lean library and requires:

- XC derivative-discontinuity compatibility;
- spatial coverage/nonlocality compatibility;
- self-adjointness.

The proof-bearing example is
[policies/lean/DFTArchitectureV1Example.lean](policies/lean/DFTArchitectureV1Example.lean).
It constructs an actual `ArchitectureManifest`, proves the final approval
theorem, and binds the canonical example-manifest hash.

For public submissions this source must be produced by the trusted obligation
generator. A user is allowed to submit proof-body patches for generated
obligations, but is not allowed to replace the generated model definition,
manifest hash, or final certificate statement.

## English workflow

For a front-facing sanity-check workflow, start with a hypothesis draft. This
extracts reviewable claims, records assumptions and traceability, asks
clarifying questions, and writes a report without treating the interpretation
as authoritative:

```bash
python3 -m dftcert.cli hypothesis-draft \
  --model-id my-hypothesis \
  --hypothesis "A DFT architecture with an XC derivative discontinuity, nonlocal coupling, and a self-adjoint operator." \
  --output build/my-hypothesis-draft.json \
  --report-output build/my-hypothesis-report.json
```

Inspect the policy coverage map:

```bash
python3 -m dftcert.cli coverage
```

The TUI and `hypothesis-draft` are intake tools. They do not prove claims and
do not replace the explicit confirmation, obligation generation, proof-search,
and certificate-check stages.

Create a draft manually:

```bash
python3 -m dftcert.cli english-draft \
  --model-id my-model \
  --description "A self-adjoint nonlocal model with an XC discontinuity." \
  --output build/my-model-draft.json
```

Or ask a configured command-model adapter to interpret it:

```bash
python3 -m dftcert.cli english-interpret \
  --model-id my-model \
  --description "..." \
  --llm-command "/path/to/model-adapter" \
  --output build/my-model-draft.json
```

The interpreter reports ambiguities and missing facts and cannot mark its own
output authoritative.

After reviewing the full draft, explicitly confirm every policy fact:

```bash
python3 -m dftcert.cli confirm \
  --manifest build/my-model-draft.json \
  --facts examples/dft/confirmed-facts.json \
  --output build/my-model-confirmed.json
```

Check the current evidence state:

```bash
python3 -m dftcert.cli assess \
  --manifest build/my-model-confirmed.json
```

A confirmed description remains `not_approved` with `proof_required`
obligations.

## PT2 workflow

Inspect an exported program without importing PyTorch:

```bash
python3 -m dftcert.cli inspect-pt2 model.pt2
```

Create a pending extraction manifest:

```bash
python3 -m dftcert.cli pt2-pending-manifest model.pt2 \
  --model-id my-model \
  --input-constraints examples/dft/input-constraints.json \
  --output build/my-model-pending.json
```

Run the extractor:

```bash
python3 -m dftcert.cli extract-pt2 model.pt2 \
  --output build/model-extraction.json
```

This invokes `torch.export.load` only inside a bubblewrap process with no
network and a read-only application/artifact view. If bubblewrap namespaces or
PyTorch are unavailable, extraction fails closed; the service never falls
back to loading the upload in-process. The current inventory worker emits no
physics facts yet because operation names alone do not prove a receptive
field, discontinuity, or self-adjointness.

Attach a successful controller-owned result with:

```bash
python3 -m dftcert.cli apply-extraction \
  --manifest build/my-model-pending.json \
  --result extractor-result.json \
  --output build/my-model-extracted.json \
  --trusted-sandbox-result
```

Missing or unsupported facts produce `extracted_partial` and remain
inconclusive. `--trusted-sandbox-result` is reserved for the sandbox
controller; it must never be set merely because an uploader supplied a result
JSON file. Signed sandbox attestations will replace this development switch.

## Generated obligations and LLM proof search

Generation is selected by policy data in
`policies/dft-architecture-v1.json`, not by hardcoded theorem branches. A
manifest without a reviewed `formalization.profile` returns
`formalization_required`; this prevents an English assertion from being
silently converted into a theorem about an unrelated Lean model.

Generate the example task bundle:

```bash
make dftcert-obligations
```

Run all generated tasks through a configured LLM adapter and the vendored
Testv2 worker in ordinary WSL:

```bash
make DFT_PROJECT=examples/dft/lean \
  LLM_COMMAND="/path/to/your/json-llm-adapter" \
  dftcert-search-example
```

For the checked-in deterministic DFT obligation demo:

```bash
cd examples/dft/lean
lake update mathlib
lake exe cache get
lake build Testv2.Verifier
cd ../../..
./noether demo dft
./noether replay build/runs/noether-dft
./noether tui --run-dir build/runs/noether-dft --once
```

### Presentation scenarios

The DFT demo has four named scenarios. They deliberately separate a reviewed
Lean proof-search success from policy rejection, missing evidence, and an
unformalized-but-plausible description:

```bash
# Full agentic search over the reviewed canonical Lean architecture.
./noether demo dft --scenario certified --llm maestro --run-dir build/runs/dft-certified

# No proof search: the submitted claim explicitly contradicts self-adjointness.
./noether demo dft --scenario non-self-adjoint --run-dir build/runs/dft-non-self-adjoint

# No proof search: required architecture claims were not supplied.
./noether demo dft --scenario missing-assumptions --run-dir build/runs/dft-missing

# No proof search: all claims are present, but no reviewed Lean profile matches.
./noether demo dft --scenario formalization-gap --run-dir build/runs/dft-gap
```

Inspect a scenario with `./noether tui --run-dir <run-directory>`. The latter
three are deterministic policy fixtures: they show why Noether refuses to run
proof search, rather than presenting a failed proof search as a physics result.

For local or cluster-hosted OpenAI-compatible models, use the demo presets or
the command adapter. The bundled physics-toy demo does not require Testv2:

```bash
./noether demo physics-toy --llm maestro

export NOETHER_OPENAI_BASE_URL=http://cluster-node:8000/v1
export NOETHER_OPENAI_MODEL=local-lean-coder
./noether demo physics-toy --llm openai-compatible
```

For the DFT tasks against the vendored Testv2 snapshot:

```bash
./noether demo dft --llm maestro
./noether demo dft --llm openai-compatible
```

To test a separate Testv2 checkout under review, pass
`--project /path/to/Testv2/project` explicitly.

On a fresh machine, initialize the vendored Lean 4.31 snapshot first:

```bash
cd examples/dft/lean
lake update mathlib
lake exe cache get
lake build Testv2.Verifier
```

`PROOF_SEARCH_ALLOW_GENERATED_OBLIGATIONS=1` is set only on this trusted local
pipeline. Generated mode accepts the reviewed policy preamble and generated
statement, while ordinary verifier requests still require an authoritative
existing target and reject preambles. Do not expose the opt-in verifier
directly to public callers; the controller must be its only writer.

Assemble or fully certify recorded verified winners:

```bash
make dftcert-assemble-example
make DFT_PROJECT=/path/to/Testv2/project dftcert-certify-example
```

The final Testv2/Mathlib check has a separate 30-minute default because cold
builds on WSL-mounted filesystems can exceed five minutes. Override it without
changing proof attempt limits:

```bash
make DFT_PROJECT=/path/to/Testv2/project DFT_CERT_TIMEOUT_S=3600 \
  dftcert-certify-example
```

## Local end-to-end runner

No server or upload API is involved. Start a certification directly from an
already confirmed/extracted manifest:

```bash
./noether certify \
  --run-dir build/runs/my-model \
  --manifest examples/dft/example-manifest.json \
  --project /path/to/Testv2/project \
  --llm-command '/path/to/json-llm-adapter'
```

The run directory owns `state.json`, an append-only hash-chained event journal,
the proof-search database, every Nexus graph and verified winner, the generated
`Certificate.lean`, and the final `report.json`. Atomic checkpoints are written
after every obligation.

If proof search exhausts its current round budget or the process is stopped,
continue on the same frontier without repeating completed obligations:

```bash
./noether resume build/runs/my-model
./noether status build/runs/my-model
```

English input can be confirmed and run locally in one command by supplying
`--description`, `--model-id`, `--facts`, and `--architecture-ir`. PT2 input
uses `--pt2`, `--model-id`, and `--input-constraints`; deserialization remains
inside bubblewrap.

## Testv2 certificate check in WSL

The normal WSL command is:

```bash
python3 -m dftcert.cli certificate-check \
  --project /path/to/Testv2/project \
  --source policies/lean/DFTArchitectureV1Example.lean \
  --manifest examples/dft/example-manifest.json \
  --trusted-local
```

`--trusted-local` is deliberately required. It is suitable only for this
repository-owned example. Arbitrary uploaded Lean source must not receive this
flag.

The Codex seccomp environment cannot launch the older Testv2 Lake/Elan
`v4.25.0-rc2` process because its `wait-timeout` signal helper receives
`EPERM`. Run the command in the ordinary WSL shell. This launcher failure is
separate from Lean diagnostics and must never be reported as a failed physics
obligation.

## Tests

```bash
make dftcert-test
make test
```

The tests cover policy validation, structured manifest facts, confirmation,
tamper detection, provenance, unsafe PT2 archives, fail-closed extraction,
generated-mode authorization, policy-driven task generation, exact
certificate checks, untrusted-source refusal, and context isolation.
