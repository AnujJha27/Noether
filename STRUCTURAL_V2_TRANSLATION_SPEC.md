# Structural V2 translation specification

This document defines the reviewed translation implemented by
`dftcert.structural.core` (`dft-structural-analysis-v3`). It is part of the
trusted research surface: Lean proves consequences of the Structural IR, while
this translation determines what an exported Torch graph is allowed to assert
in that IR.

## Evidence classes

| Source | Authority for source → IR | Certificate meaning |
| --- | --- | --- |
| Human-reviewed description | The reviewer edits and confirms the proposed claims | Given this confirmed specification, the Lean-checked structural consequences hold |
| `.pt2` artifact | Sandboxed extractor, reviewed mappings below, node provenance, and translation validation | This exact SHA-256-bound exported artifact exhibits the recognized structures |
| Structural IR | Lean kernel | The generated conclusions follow from the encoded finite structure |

Human confirmation is not a proof. A confirmed specification still produces
Lean obligations, requires verified proof bodies, and receives the permanent
certificate kind `confirmed_specification`. It can never claim artifact
evidence. Artifact analysis does not ask a user to confirm what the graph
contains.

## Artifact extraction contract

The only `.pt2` deserialization occurs in the no-network, read-only bubblewrap
worker. The worker records every exported node's name, operation kind, target,
arguments, keyword arguments, and available tensor metadata. State entries
record shape, dtype, raw-value SHA-256, aliases, exported graph inputs, and
state kind. Literal `structural_values` are emitted only for boolean or integer
state tensors with at most 4096 elements.

The controller verifies the archive before execution, checks that the worker's
artifact SHA-256 matches the submitted file, and requires exactly one JSON
result. Hash binding establishes identity; it does not by itself establish the
semantic mapping below.

## Reviewed input constraints

These values describe the certification question and are not inferred from
operator names:

- `output_contracts` must map exactly three exported output indices to
  `xc_energy`, `learned_self_energy`, and `message_state`.
- `required_couplings` lists the directed source/target pairs whose coverage is
  to be proved.
- `adjacency_state_name` selects the exported structural adjacency state. If
  omitted, the only supported fallback is a state name containing `adjacency`.
- `adjacency_convention` is `target_source` by default or `source_target`.

The constraints are part of the translation derivation and IR hash. An invalid,
missing, or incomplete contract is rejected rather than guessed.

## Exact Torch-to-IR mappings

Targets are lower-cased and matched exactly. Unlisted spellings, custom
operators, and future Torch variants are `unsupported` until reviewed and
added with tests.

| Structural claim | Accepted exported target or pattern | IR value and assumption |
| --- | --- | --- |
| Adjacency cast alias | `aten.to.dtype`, `aten._to_copy.default`, `prims.convert_element_type.default` with exactly one reference to the adjacency state or an existing alias | The result may feed message passing as the same adjacency relation |
| Message-passing stage | `aten.matmul.default`, `aten.mm.default`, or `aten.bmm.default`, with exactly one adjacency reference and one previous-state reference | One consecutive adjacency-fed stage; depth is the chain length traced backward from `message_state` |
| Hinge XC | An ancestor of `xc_energy` is `aten.relu.default`, `aten.clamp_min.default`, or `aten.maximum.default` | `xc.form = hinge`; the architecture contains a recognized nonsmooth hinge construction |
| Smooth XC | No hinge ancestor exists and an ancestor is `aten.sigmoid.default`, `aten.softplus.default`, or `aten.tanh.default` | `xc.form = smooth`; this mapping does not support the required discontinuity |
| Zero operator | `learned_self_energy` root target is `aten.zeros.default` or `aten.zero.default` | `operator.construction = zero`, structurally self-adjoint |
| Identity operator | Root target is `aten.eye.default` | `operator.construction = identity`, structurally self-adjoint |
| Symmetrized operator | Root is `aten.add.Tensor`; one operand is a direct base reference and the other is `aten.transpose.int`, `aten.permute.default`, `aten.t.default`, or `aten.numpy_T.default` applied directly to the same base | `operator.construction = symmetrized`, interpreted as a `B + Bᵀ` construction |
| Unconstrained operator | Root node kind is `placeholder` or `get_attr` | `operator.construction = unconstrained_parameter`; no self-adjointness guarantee |

Topology requires a non-empty square boolean/integer structural matrix. Every
truthy entry becomes one directed edge according to the declared convention.
Message depth stops at the first non-matching or ambiguous stage; unrelated
matrix multiplications are never counted. An XC or operator graph that matches
none of the reviewed patterns becomes `unsupported`.

## Translation validation and provenance

Artifact IR creation records the raw inventory hash, output roots, adjacency
state and aliases, consecutive message-stage nodes, XC root/form, operator
root/construction, and provenance nodes. A second deterministic validation pass
recomputes those claims from the raw inventory and constraints, then rejects
any disagreement between inventory, derivation, and IR.

This is duplicate validation of the derivation, not an independently
formalized semantics for Torch. The extractor/analyzer and the reviewed mapping
table remain in the trusted base. Supporting a new operator therefore requires:

1. updating this specification and the analyzer version;
2. adding a positive mapping test and a near-name/custom-operator rejection test;
3. retaining node-level provenance and translation hash binding; and
4. confirming that the existing generic Lean predicate expresses the intended
   structural consequence.

## Lean obligations and reviewability

Both evidence routes compile the common IR deterministically into finite Lean
obligations for coupling coverage, XC discontinuity support, and guaranteed
self-adjointness. Human-approved claims are therefore only the input to proof
generation: they are not certified until the accepted proof bodies and final
certificate compile successfully in Lean. The run's proof-review view exposes
the generated theorem, accepted proof patch, and Lean diagnostics.

Structural certification does not assess weights, floating-point outputs,
training convergence, numerical accuracy, or experimental agreement.
