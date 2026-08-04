#!/usr/bin/env bash
set -euo pipefail

cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."

: "${NOETHER_OPENAI_BASE_URL:=http://127.0.0.1:11434/v1/chat/completions}"
: "${NOETHER_OPENAI_MODEL:=qwen3.6-64k:latest}"
: "${NOETHER_ASSESS_TIMEOUT_S:=600}"
export NOETHER_OPENAI_BASE_URL NOETHER_OPENAI_MODEL

test -x ./build/proof-search || { echo 'run make first' >&2; exit 1; }

./noether assess dft \
  --description examples/dft/gnn-ring6-3hop-description.txt \
  --model-id ring6-gnn \
  --llm maestro \
  --provider-timeout-s "$NOETHER_ASSESS_TIMEOUT_S" \
  --run-dir build/runs/ring6-assess

echo 'Assessment complete. Review the live TUI; press q to continue to Lean certification.'
./noether tui --run-dir build/runs/ring6-assess

run_certification() {
  if test -f build/runs/ring6-certify/state.json; then
    ./noether resume build/runs/ring6-certify
  else
  ./noether certify \
    --run-dir build/runs/ring6-certify \
    --description examples/dft/gnn-ring6-3hop-description.txt \
    --model-id ring6-gnn \
    --facts examples/dft/gnn-ring6-3hop-facts.json \
    --architecture-ir examples/dft/gnn-ring6-3hop-architecture-ir.json \
    --project examples/dft/lean \
    --llm-command "python3 examples/orchestrator/openai_compatible_adapter.py"
  fi
}

run_certification &
certification_pid=$!
while ! test -f build/runs/ring6-certify/state.json && kill -0 "$certification_pid" 2>/dev/null; do
  sleep 1
done
if test -f build/runs/ring6-certify/state.json; then
  echo 'Certification is running. The TUI refreshes live; press q to return to the shell and wait for completion.'
  ./noether tui --run-dir build/runs/ring6-certify
fi
wait "$certification_pid"
