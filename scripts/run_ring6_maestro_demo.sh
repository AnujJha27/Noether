#!/usr/bin/env bash
set -euo pipefail

: "${NOETHER_OPENAI_BASE_URL:=http://127.0.0.1:11434/v1/chat/completions}"
: "${NOETHER_OPENAI_MODEL:=qwen3.6-64k:latest}"
export NOETHER_OPENAI_BASE_URL NOETHER_OPENAI_MODEL

test -x ./build/proof-search || { echo 'run make first' >&2; exit 1; }

./noether assess dft \
  --description examples/dft/gnn-ring6-3hop-description.txt \
  --model-id ring6-gnn \
  --llm maestro \
  --run-dir build/runs/ring6-assess

./noether certify \
  --run-dir build/runs/ring6-certify \
  --description examples/dft/gnn-ring6-3hop-description.txt \
  --model-id ring6-gnn \
  --facts examples/dft/gnn-ring6-3hop-facts.json \
  --architecture-ir examples/dft/gnn-ring6-3hop-architecture-ir.json \
  --project examples/dft/lean \
  --llm-command "python3 examples/orchestrator/openai_compatible_adapter.py"
