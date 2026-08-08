# Noether

> Turn a structural belief about a model into a Lean-checked certificate.

You have an exported model and believe it has a property: information can reach
the sites that need to interact; an XC construction has the required hinge; an
operator is self-adjoint by construction. A test can sample outputs. Noether
turns the architectural claim into a theorem about the exact artifact.

```text
model.pt2 → artifact-grounded structural IR → generated Lean obligations → certificate
```

A certificate is bound to the exported artifact and IR hashes. Lean accepts or
rejects the generated theorem; language models may suggest a proof, but never
decide that it is valid.

## Quick start

```bash
make
make test

# Lean proof-search demo
./noether demo physics-toy

# DFT policy demo
./noether demo dft --scenario certified
```

Start a verifier service when driving it directly:

```bash
./build/proof-search
```

## Common workflows

Run an existing proof-search task set:

```bash
./noether agentic --provider mock --run-dir build/runs/demo < tasks.jsonl
./noether tui --run-dir build/runs/demo
./noether review --run-dir build/runs/demo
```

`tui` shows the live run. `review` is the separate read-only view for accepted
Lean proof patches and verifier diagnostics.

For seven artifact-backed pass/fail examples, use
[Structural V2 demos](STRUCTURAL_V2_DEMOS.md).

## Trust boundary

Noether certifies structural compatibility, not numerical accuracy,
convergence, trained weights, or experimental agreement. Lean checks the
generated theorem, not the PT2 binary itself.

## Documentation

- [Build guide](BUILD_GUIDE.md)
- [Orchestrator and provider guide](ORCHESTRATOR.md)
- [Structural V2 demo commands](STRUCTURAL_V2_DEMOS.md)
- [Structural V2 workflow and trust model](examples/dft/STRUCTURAL_V2.md)
- [DFT certification prototype](DFT_CERTIFICATION.md)
- [Reproducibility guide](REPRODUCIBILITY.md)
- [Contributing](CONTRIBUTING.md)

## Current scope

This is trusted-local research software. Public or multi-tenant uploads are
out of scope until the sandboxing work described in
[DFT_INTEGRATION_PLAN.md](DFT_INTEGRATION_PLAN.md) is complete.
