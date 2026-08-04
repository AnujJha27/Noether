# DFT Architecture Certification Plan

## Current implementation

The M1 trust boundary, structured canonical manifest, English confirmation
flow, fail-closed PT2 graph-inventory sandbox, context registry, policy-driven
generated obligations, structured agentic proof-search orchestration,
run-scoped memory, handoff/replay artifacts, terminal inspection,
verified-winner certificate assembly, and exact hash-bound example certificate
are implemented. See [DFT_CERTIFICATION.md](DFT_CERTIFICATION.md) for commands
and current limitations.

The current implementation is a local research workflow. It supports
deterministic demos, command adapters, OpenRouter free-model demos,
OpenAI-compatible local/cluster model endpoints, and Maestro cluster presets.
Broader graph-to-physics analyzers and
public-upload hardening remain future work.

## Product claim

The initial product certifies that a submitted ML architecture satisfies a
versioned set of formally stated DFT physics obligations. It does not certify
trained weights, numerical accuracy, convergence, generalization, or agreement
with experimental data.

The initial policy uses the vendored Testv2 Lean formalization in
`examples/dft/lean` by default. `DFT_PROJECT` may select a separate reviewed
checkout. It requires:

1. XC derivative-discontinuity compatibility;
2. spatial coverage/nonlocality compatibility;
3. self-adjointness of the learned operator.

The policy and final certificate shape remain configurable. V1 will ship an
example certificate that constructs an actual Lean `ArchitectureManifest` and
exposes a required named approval theorem.

## End-to-end flow

```text
English description                 torch.export artifact + input constraints
        │                                         │
        ▼                                         ▼
LLM-generated draft manifest           sandboxed deterministic extractor
        │                                         │
explicit user review/confirmation                 │
        └──────────────────────┬──────────────────┘
                               ▼
              canonical versioned architecture IR
                               │
                    policy obligation generator
                               ▼
             Lean declarations and proof obligations
                               │
              agentic LLM proof-search orchestration
                               ▼
              isolated project/toolchain Lean workers
                               │
             evidence-bearing certification report
```

## Trust boundary

Lean proves properties of the canonical architecture IR. The system must also
show where every IR fact came from; otherwise it might prove a correct theorem
about an inaccurate description of the uploaded model.

Every manifest field therefore records provenance:

```json
{
  "receptive_field": {
    "value": 3,
    "evidence": {
      "kind": "graph_analysis",
      "artifact_sha256": "...",
      "nodes": ["conv1", "message_passing_2"],
      "extractor_version": "..."
    }
  }
}
```

Allowed evidence kinds initially are:

- `graph_analysis`: deterministically derived from a submitted export;
- `user_attestation`: explicitly confirmed by the user after English parsing;
- `formal_derivation`: derived from other manifest facts by a checked rule.

LLM output alone is never authoritative evidence.

## Input track A: plain English

1. Accept a natural-language model and physics description.
2. Have an LLM translate it into a draft canonical manifest.
3. Highlight ambiguities, unsupported statements, and missing required facts.
4. Require explicit user confirmation of the complete normalized manifest.
5. Mark confirmed facts as `user_attestation`.
6. Generate obligations only after confirmation.

The final report must state that certification is against the user-confirmed
description, not against an inspected executable model.

## Input track B: PyTorch

V1 accepts:

- a `torch.export`/PT2 exported program;
- representative input specifications;
- dynamic shape/range constraints where applicable;
- optional human-readable model intent.

V1 does not directly accept or execute arbitrary Python model source, pickled
`nn.Module` objects, or legacy checkpoints. Raw Python support may be added
later only inside a stronger disposable execution sandbox.

The extractor:

1. hashes the original artifact;
2. validates format and size limits;
3. loads it in an isolated extraction worker;
4. derives a normalized graph and architecture facts;
5. records graph nodes and extractor version as provenance;
6. emits the canonical manifest and its hash.

The exact artifact certified for deployment must match the recorded artifact
hash. Input constraints are part of the claim and appear in the report.

## Configurable policy bundles

A policy bundle is data, not target-specific application code. It contains:

- policy ID and semantic version;
- canonical manifest schema version;
- Lean project path and project fingerprint;
- Lean toolchain fingerprint;
- required, optional, and mutually exclusive obligations;
- evidence kinds allowed for each fact;
- obligation-generation templates;
- Lean modules, declarations, and authoritative targets;
- pass, fail, and inconclusive rules;
- required final certificate declaration;
- report template and policy limitations.

The initial bundle is `dft-architecture-v1`, backed by `Testv2` and its
Lean `v4.25.0-rc2` toolchain.

## Certificate rule

Compilation of an arbitrary referenced module is not approval. A successful
run must locate and check the exact declaration required by the active policy.

The initial example certificate will have the logical shape:

```lean
def submittedManifest : ArchitectureManifest X := {
  -- model-specific data and positive evidence
}

theorem submittedManifest_approved :
    (verify X submittedManifest).approved = true := by
  rfl
```

The concrete parameters and namespace will be decided by the policy bundle.
The backend records the checked declaration name and full type.

## Worker contexts

Workers are pooled by:

```text
(project content fingerprint, Lean toolchain fingerprint, policy version)
```

Each context has its own prepared Lake project, cache namespace, process limits,
and immutable source snapshot. Requests never silently cross contexts.

## Arbitrary-upload security requirements

Public uploads are hostile by default. Before enabling them, model extraction,
LLM adapters, and Lean verification must run in separate disposable sandboxes
with:

- no network access;
- no host credentials or inherited secrets;
- a read-only base filesystem;
- per-job writable scratch space;
- CPU, memory, process-count, wall-time, file-size, and disk limits;
- strict upload and decompression limits;
- immutable project/toolchain images;
- process-group and descendant cleanup;
- audit logs keyed by content hash;
- retention and deletion policy;
- no direct loading of untrusted Python pickle objects.

The existing local RLIMIT worker remains a development backend, not the public
multi-tenant security boundary.

## Delivery milestones

### M1: Correct certificate boundary — implemented

- Define the example `dft-architecture-v1` policy bundle.
- Add a real example `ArchitectureManifest`.
- Require and check its named approval declaration.
- Replace “module compiled” approval in the current manifest script.
- Add positive, rejected, and inconclusive fixtures.

### M2: Canonical architecture IR — implemented

- Define a versioned JSON Schema.
- Add field-level evidence provenance and content hashes.
- Implement deterministic canonicalization.
- Separate asserted, extracted, derived, and unresolved facts.

### M3: English ingestion — implemented for local confirmed descriptions

- Generate a draft IR with ambiguity and missing-fact reporting.
- Add an explicit confirmation step.
- Preserve the original description and confirmed manifest hashes.
- Prevent proof search before confirmation.

### M4: PyTorch export ingestion — partial local implementation

- Accept PT2 exports and explicit input constraints.
- Build the isolated graph extractor.
- Derive receptive-field, dependency, symmetry, and operator facts supported by
  the first policy.
- Reject unsupported operators or incomplete graph capture as inconclusive.

### M5: Obligation generation and proof search — implemented for reviewed profiles

- Generate Lean declarations from the canonical IR and policy templates.
- Submit unresolved proofs to the structured agentic orchestration layer.
- Track dependency-aware subgoals, all Lean diagnostics, agent turns, handoffs,
  model prompts/responses, verifier results, and scorecards.
- Require the final named certificate before approval.

### M6: Multi-toolchain execution — implemented locally

- Add a context registry keyed by project/toolchain/policy fingerprints.
- Prepare and cache one isolated worker pool per context.
- Integrate the external Testv2 project without copying or hardcoding its
  theorems.
- Test simultaneous requests for different Lean versions.

### M7: Public-upload hardening — future release gate

- Move extraction and Lean jobs into disposable container/cgroup sandboxes.
- Add upload validation, quotas, authentication, audit logs, and retention.
- Perform adversarial tests for malicious archives, checkpoints, Lean code,
  process trees, resource exhaustion, and model-provider output.

## V1 acceptance criteria

- English submissions cannot proceed without explicit manifest confirmation.
- PyTorch submissions use exported graph artifacts and declared input
  constraints, not arbitrary executable Python or unsafe checkpoint loading.
- Each manifest fact has machine-readable provenance.
- All three initial physics obligations receive `proved`, `refuted`, or
  `inconclusive` results; missing evidence never becomes approval.
- Approval requires the policy's exact final Lean certificate.
- The report binds artifact, manifest, policy, project, toolchain, proofs, and
  certificate by cryptographic hashes.
- Arbitrary uploads never execute in the host verifier process.
- Worker and cache state are isolated by project/toolchain/policy fingerprint.

## Local model/provider options

The workflow remains provider-neutral. Current adapters include:

- deterministic checked-in demo adapter;
- arbitrary command adapters;
- OpenRouter free-model route through `.env`;
- generic OpenAI-compatible chat-completions endpoints;
- Maestro cluster presets:
  - `maestro`: always-on login-node model;
  - `piano`, `sitar`, `violin`: compute-node Ollama servers started through
    `srun`.

Examples:

```bash
./noether demo physics-toy
./noether demo physics-toy --llm openrouter-free
./noether demo physics-toy --llm maestro
./noether demo dft --project "$DFT_PROJECT" --llm maestro

# DFT presentation carousel: proof success, policy failure, missing evidence,
# and a formalization gap.
./noether demo dft --scenario certified --llm maestro
./noether demo dft --scenario non-self-adjoint
./noether demo dft --scenario missing-assumptions
./noether demo dft --scenario formalization-gap
```

## Deferred work

- Numerical validation and trained-weight certification;
- empirical accuracy or agreement with experiment;
- arbitrary Python execution;
- automatically treating an unconfirmed English interpretation as fact;
- distributed workers before the single-host sandbox is proven reliable.
