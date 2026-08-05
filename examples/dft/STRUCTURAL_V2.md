# Structural V2: real-model workflow

Structural V2 answers a deliberately narrow question: **does this exact model
artifact have the architectural constructions required by the DFT policy?** It
does not evaluate floating-point outputs or claim that trained weights are
physically accurate.

```text
model.py
   |
   | torch.export.export + torch.export.save
   v
model.pt2 --SHA-256--> sandboxed torch.export.load
                              |
                              v
                   graph + state inventory
                              |
               deterministic structural analysis
                              v
      topology / depth / XC form / operator construction
                              |
                              v
                    Structural IR V2
                              |
                deterministic Lean obligations
                              v
 decomposer -> all proposers -> critic -> Lean -> repair -> reporter
                              |
                              v
        certificate bound to artifact hash and exact IR hash
```

## Concrete demo

The bundled `CertifiedRingGNN` has six sites. Its exported graph contains three
matrix multiplications, so information can travel from site 0 to site 3 along
`0 -> 1 -> 2 -> 3`. Its XC output uses `relu`, which the V2 policy classifies as
a hinge construction. Its learned operator is returned as `B + B.T`, so
self-adjointness follows from construction rather than from checking numerical
entries.

Three variants each expose one useful failure witness:

| Model | Structural witness |
| --- | --- |
| `TooShallowRingGNN` | depth 2 cannot cover required coupling `0 -> 3` |
| `UnconstrainedOperatorGNN` | direct parameter has no guaranteed adjoint symmetry |
| `SmoothXCGNN` | sigmoid is smooth, not a hinge construction |

## Export with Windows Torch from WSL

The repository can stay in WSL while Windows Python performs only the export.
For this checkout, run:

```bash
/mnt/c/WINDOWS/System32/WindowsPowerShell/v1.0/powershell.exe -NoProfile -Command \
  "Set-Location 'D:\fun stuff\proof_vibe'; py -3 examples\dft\models\export_structural_gnns.py"
```

If `py -3` is not the Torch environment, replace it with the full Windows
Python path. The exporter writes `.pt2` files under
`build/structural-v2-models/`.

Production analysis uses the no-network bubblewrap boundary:

```bash
./noether structural analyze-pt2 build/structural-v2-models/certified-ring.pt2 \
  --constraints examples/dft/structural-v2-input-constraints.json \
  --output build/certified-ring-ir.json
```

When WSL has no Torch, a trusted local demo analysis may also be run with the
Windows Torch environment:

```bash
/mnt/c/WINDOWS/System32/WindowsPowerShell/v1.0/powershell.exe -NoProfile -Command \
  "Set-Location 'D:\fun stuff\proof_vibe'; py -3 examples\dft\models\analyze_structural_gnns.py build\structural-v2-models"
```

That local route is for artifacts you created yourself. Uploaded or untrusted
`.pt2` files must go through bubblewrap.

## Generate and prove the exact obligations

```bash
./noether structural generate --ir build/certified-ring-ir.json --jsonl \
  > build/certified-ring-tasks.jsonl

./noether agentic \
  --provider command \
  --llm-command "python examples/orchestrator/noether_demo_llm.py" \
  --verifier build/proof-search \
  --full-process \
  --small-model \
  --max-epochs 3 \
  --stagnation-epochs 2 \
  --journal-dir build/runs/certified-ring/journal \
  --run-dir build/runs/certified-ring \
  < build/certified-ring-tasks.jsonl \
  > build/certified-ring-proof-results.jsonl
```

`--small-model` shortens context; it does not skip a stage. `--full-process`
forces the decomposer, every configured proposer, critic, Lean verifier, and
reporter to appear in each task trace. Only a Lean `verified` result is accepted
during assembly. Epochs resume the existing search graph; if two consecutive
epochs add no nodes, the task is saved as `paused_stagnant` instead of burning
the remaining local-model budget.

```bash
./noether structural assemble \
  --ir build/certified-ring-ir.json \
  --proof-results build/certified-ring-proof-results.jsonl \
  --source-output build/CertifiedRingCertificate.lean \
  --report-output build/certified-ring-certificate.json

./noether structural check-certificate \
  --project examples/dft/lean \
  --source build/CertifiedRingCertificate.lean \
  --trusted-local
```

## Natural-language alternative

Natural language uses the same IR and Lean generator, but it cannot prove a
claim about a `.pt2` file. The result is labelled
`confirmed_specification`, not `artifact`.

```bash
./noether structural draft-description \
  --description architecture.md \
  --llm-command "your-local-qwen-adapter" \
  --output build/spec-draft.json

# Review proposed_claims in the draft, edit them if necessary, then confirm:
./noether structural confirm-description \
  --draft build/spec-draft.json \
  --reviewed-claims reviewed-claims.json \
  --confirmed \
  --output build/confirmed-spec-ir.json
```

The remaining generation, agent, assembly, and Lean-check commands are the
same. The distinction between a specification certificate and an artifact
certificate is permanent and recorded in the assembly report.

## Direct Qwen comparison

Do not compare systems by how convincing their prose sounds. Run direct Qwen
and Qwen inside Noether on the same four cases, then store each result as:

```json
{"case":"certified-ring","checks":{"xc_discontinuity_compatible":true,"spatial_nonlocality_compatible":true,"self_adjoint":true},"artifact_sha256":"...","ir_sha256":"...","certificate_status":"verified"}
```

Score both files with:

```bash
python examples/dft/evaluate_structural_v2.py \
  --direct build/direct-qwen-results.json \
  --harness build/noether-qwen-results.json
```

The scorer reports structural answer accuracy separately from artifact-binding
and Lean-verification rates. A direct prompt may match all three answers; it
still has not produced evidence tied to the exact `.pt2` file unless those
separate metrics are also present.
