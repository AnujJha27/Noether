# Reproducibility

This file records the commands needed to reproduce the current artifact on a
fresh machine.

## Environment

Required:

- Linux or WSL2;
- GNU Make;
- `g++` or `clang++` with C++17 support;
- SQLite development headers and library;
- Python 3.11 or newer;
- Lean installed with `elan`;
- `nlohmann/json` headers.

Recommended checks:

```bash
g++ --version
make --version
python3 --version
lean --version
lake --version
```

## Core verifier and orchestration

From the repository root:

```bash
make clean
make test
make wsl-smoke
make benchmark
make benchmark-repeat
```

Expected result:

- `make test` builds the C++ verifier, builds the bundled Lean project, and
  runs C++, orchestrator, and DFT certification unit tests.
- `make wsl-smoke` sends a mock LLM proof through the real verifier.
- `make benchmark` writes `benchmark-results.json`.
- `make benchmark-repeat` writes `benchmark-repeat-results.json` with
  run-to-run variance.

## DFT certificate example

The DFT certificate example depends on an external Lean project containing the
`Testv2` formalization. Set `DFT_PROJECT` to that project root:

```bash
export DFT_PROJECT=/path/to/Testv2/project
make dftcert-obligations
make dftcert-assemble-example
make dftcert-certify-example
```

`dftcert-certify-example` requires `--trusted-local` internally and is intended
only for the repository-owned example certificate. Do not use that mode for
arbitrary uploaded Lean source.

## Benchmark interpretation

The default benchmark is a smoke benchmark, not a paper-scale evaluation. It
separates cold verification from warm-cache checks and reports:

- total attempts;
- verified attempts;
- cold-cache elapsed time;
- warm-cache elapsed time;
- cache hit rate;
- p50/p95 latency;
- configured resource limits.

For a paper or poster, run the benchmark repeatedly on the target machine and
report hardware, OS/WSL version, Lean version, and mean/standard deviation.
