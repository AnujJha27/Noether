# Contributing

This repository is a research prototype. Contributions should preserve the
trust boundary: Lean is the proof oracle, LLM output is never authoritative
evidence, and public/uploaded artifacts must be treated as hostile.

## Development setup

Install:

- GNU Make;
- a C++17 compiler;
- SQLite development headers;
- Python 3.11 or newer;
- Lean through `elan`;
- `nlohmann/json` headers.

Then run:

```bash
make test
make wsl-smoke
make benchmark
```

## Change expectations

- Add or update tests for behavioral changes.
- Keep generated files under `build/` or another ignored directory.
- Do not hardcode machine-local paths in source or documentation.
- Document any new trust-boundary assumptions in `DFT_CERTIFICATION.md`.
- Keep public-upload or network-facing functionality disabled unless the
  sandboxing requirements in `DFT_INTEGRATION_PLAN.md` are satisfied.

## Review checklist

- `make test` passes.
- `make wsl-smoke` passes on a machine with Lean installed.
- DFT certificate commands that require an external Lean project explicitly set
  `DFT_PROJECT`.
- New policy facts have provenance and tests for incomplete evidence.
