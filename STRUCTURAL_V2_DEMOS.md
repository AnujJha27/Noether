# Structural V2 demos

Run these commands from the repository root. They produce seven exported
artifacts and their corresponding structural reports.

## Build the demo array

```bash
make

cd examples/dft/lean
lake build
cd ../../..

PYTHONPATH=. python examples/dft/models/export_structural_gnns.py \
  --output-dir build/structural-v2-models

PYTHONPATH=. python examples/dft/models/analyze_structural_gnns.py \
  build/structural-v2-models \
  --constraints examples/dft/structural-v2-input-constraints.json \
  --output-dir build/structural-v2-analysis
```

If `lake` is not on `PATH` on Maestro, use `/home/anuj/.elan/bin/lake build`.

## Demo array

| Artifact | XC | Spatial coverage | Self-adjointness | Expected disposition |
| --- | --- | --- | --- | --- |
| `certified-ring` | pass | pass | pass | structurally certifiable |
| `identity-operator-ring` | pass | pass | pass | structurally certifiable |
| `zero-operator-ring` | pass | pass | pass | structurally certifiable |
| `too-shallow-ring` | pass | fail | pass | uncovered coupling witness |
| `smooth-xc` | fail | pass | pass | XC construction witness |
| `unconstrained-operator` | pass | pass | fail | operator construction witness |
| `all-failures-ring` | fail | fail | fail | three independent witnesses |

Write a report for every case:

```bash
for case in certified-ring identity-operator-ring zero-operator-ring \
  too-shallow-ring smooth-xc unconstrained-operator all-failures-ring; do
  ./noether structural report \
    --ir "build/structural-v2-analysis/$case.json" \
    --output "build/structural-v2-analysis/$case-report.json"
done
```

Inspect the resulting checks and witnesses:

```bash
for report in build/structural-v2-analysis/*-report.json; do
  printf '\n%s\n' "$report"
  jq '{status, checks: [.checks[] | {name, satisfied}], failure_witnesses}' "$report"
done
```

## Run the proof-carrying positive case

Only the three all-pass cases are certificate candidates. This example uses
`certified-ring`; replace the case name with either other all-pass case to run
it there.

```bash
export PROOF_SEARCH_ALLOW_GENERATED_OBLIGATIONS=1
export PROOF_SEARCH_PROJECT_DIR="$PWD/examples/dft/lean"
export PROOF_SEARCH_DB="$PWD/build/certified-ring.db"

./noether structural generate \
  --ir build/structural-v2-analysis/certified-ring.json \
  --jsonl > build/certified-ring-tasks.jsonl

./noether agentic \
  --provider command \
  --llm-command "python examples/orchestrator/noether_demo_llm.py" \
  --verifier ./build/proof-search \
  --full-process --small-model \
  --max-epochs 3 --stagnation-epochs 2 \
  --journal-dir build/runs/certified-ring/journal \
  --run-dir build/runs/certified-ring \
  < build/certified-ring-tasks.jsonl \
  > build/certified-ring-proof-results.jsonl

./noether structural assemble \
  --ir build/structural-v2-analysis/certified-ring.json \
  --proof-results build/certified-ring-proof-results.jsonl \
  --source-output build/CertifiedRingCertificate.lean \
  --report-output build/certified-ring-certificate.json

./noether structural check-certificate \
  --project examples/dft/lean \
  --source build/CertifiedRingCertificate.lean \
  --trusted-local
```

## Browse a completed run

```bash
./noether tui --run-dir build/runs/certified-ring
./noether review --run-dir build/runs/certified-ring
```
