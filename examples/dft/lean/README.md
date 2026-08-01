# Vendored Testv2 DFT Formalization

This is a source snapshot of the local `Testv2` Lean formalization used by the
Noether DFT demo. It is intentionally kept inside the Noether repo so demo runs
do not depend on an external checkout or branch state.

First-time setup on a machine:

```bash
lake update mathlib
lake exe cache get
lake build Testv2.Verifier
```

Then run the demo from the Noether repo root:

```bash
python ./noether demo dft --llm maestro --run-dir build/runs/dft-maestro-live-1
```
