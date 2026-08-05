# Noether Structural V2 Implementation Plan

## Objective

Replace fixed architecture-profile certification with an artifact-grounded
workflow:

```text
PyTorch .pt2 model -> sandboxed graph extraction --+
                                                   +-> common structural IR
Natural language -> Qwen draft -> human confirmation+
                                                           |
                                                           v
                                              deterministic IR -> Lean
                                                           |
                                                           v
                                      full agent proof-search workflow
                                                           |
                                                           v
                                          source-bound Lean certificate
```

V2 certifies structural facts only: graph reachability, message-passing depth,
XC construction form, and self-adjointness guaranteed by operator construction.
It does not certify numerical accuracy, tolerances, convergence, trained-weight
quality, or experimental agreement.

## Required behavior

- Accept a real `torch.export` `.pt2` artifact, hash it before loading, and load
  it only inside the existing no-network read-only sandbox.
- Extract graph operations, parameter names/shapes/sharing, output provenance,
  message-passing structure, XC form, and operator construction into one V2 IR.
- Preserve node-level provenance for every extracted structural fact.
- Compile the IR deterministically into generic Lean definitions and exact
  obligations. LLMs must never invent authoritative theorem statements.
- Run decomposer, all proposers, critic, Lean verification, diagnostic repair,
  and reporter stages. Only Lean may mark a proof verified.
- Bind the certificate to artifact hash, inventory hash, extractor/compiler
  versions, policy version, generated IR, and proof results.
- Support natural-language descriptions through the same IR, but mark them as
  human-confirmed specification certificates rather than artifact certificates.
- Produce explicit structural witnesses for uncovered couplings and unsupported
  operator/XC constructions.
- Keep V1 templates only as legacy regression fixtures; they must not decide V2
  production certification.

## Demo matrix

- `CertifiedRingGNN`: six-site ring, three message-passing stages, hinge XC,
  and self-energy constructed as `B + B.T`.
- `TooShallowRingGNN`: two stages, exposing the uncovered `0 -> 3` coupling.
- `UnconstrainedOperatorGNN`: direct learned operator with no structural
  self-adjointness guarantee.
- `SmoothXCGNN`: smooth XC path with no structural derivative discontinuity.

Demo `.pt2` files are generated under `build/`; they are not committed.

## Implementation checklist

- [x] Define and validate Structural IR V2 and source/evidence classes.
- [x] Extend the PT2 worker and analyzer to emit V2 IR plus provenance.
- [x] Add the generic Lean structural library and deterministic generator.
- [x] Add artifact-bound structural certificate assembly/checking.
- [x] Add the natural-language-to-IR review/confirmation path.
- [x] Add PyTorch demo models, exporter, CLI commands, and failure witnesses.
- [x] Ensure every configured agent stage remains present in V2 traces.
- [x] Add resumable inference epochs and stagnation pause semantics.
- [x] Add direct-Qwen versus harness-Qwen evaluation fixtures and metrics.
- [x] Run all verifier, orchestrator, DFT, replay, and certificate tests.

## Acceptance criteria

- No V2 approval depends on a fixed chain/ring/Fin1 template.
- Every artifact-derived fact names supporting exported graph nodes.
- Changing the graph or structural parameter layout invalidates the certificate.
- All four demo artifacts receive their expected structural disposition.
- Natural-language-only results can never claim artifact evidence.
- Unsupported patterns produce `formalization_required` or an explicit
  structural failure, never a guessed proof.
- Existing V1 behavior remains available only for regression/migration while V2
  becomes the default demonstrated workflow.

## Resume notes

Start with:

```bash
git status --short
python -m unittest tests.test_dftcert tests.test_orchestrator
```

Then continue from the first unchecked checklist item. Update this file whenever
an item is completed or a trust-boundary limitation is discovered.

Current environment notes:

- WSL Python has no Torch. Windows Python 3.12 has Torch 2.6, and PowerShell can
  export and analyze the four demo `.pt2` files; see
  `examples/dft/STRUCTURAL_V2.md`.
- The Python unit suite passes (73 tests). Windows Lake compiled both the generic
  Structural V2 library and an assembled certificate bound to the real
  `certified-ring.pt2` hash and IR hash.
- Structural instances use kernel-reduced `by decide`, not `native_decide`;
  the latter would add the native compiler to the trusted base unnecessarily.
- The existing orchestrator journal already supports resuming a search. The
  unchecked epoch item specifically means adding automatic stagnation detection
  across repeated resumed searches, not basic persistence.
