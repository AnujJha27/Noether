# Noether

Noether is a local research harness for turning bounded architecture claims
into Lean-checked evidence. LLMs may propose proof patches; Lean decides
whether they verify.

It has three practical pieces:

- a C++ Lean-verification service with isolated, bounded workers;
- a Python agentic runner for proposing, ranking, and repairing proof patches;
- an artifact-grounded DFT Structural V2 workflow for exported PyTorch models.

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

Run proof search over generated JSONL tasks:

```bash
./noether agentic --provider mock --run-dir build/runs/demo < tasks.jsonl
./noether tui --run-dir build/runs/demo
./noether review --run-dir build/runs/demo
```

The operational TUI shows the live run. `review` is the separate read-only
view for accepted Lean proof patches and verifier diagnostics.

For the full Structural V2 demo array, use the copy-paste commands in
[Structural V2 demos](STRUCTURAL_V2_DEMOS.md).

## Trust boundary

Noether certifies structural compatibility only. It does not certify numerical
accuracy, convergence, trained weights, or experimental agreement. PT2-derived
reports bind claims to the artifact and generated IR hashes; Lean checks the
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
