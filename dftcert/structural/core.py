from __future__ import annotations

import hashlib
import re
import subprocess
import tempfile
import time
from pathlib import Path
from collections import deque
from collections.abc import Sequence
from typing import Any

from ..certificate import project_fingerprint
from ..manifest import ManifestError, sha256_value


IR_SCHEMA_VERSION = 2
ANALYZER_VERSION = "dft-structural-analysis-v2"
COMPILER_VERSION = "dft-structural-lean-v2"
POLICY_VERSION = "dft-structural-v2"
_FORBIDDEN = re.compile(r"\b(sorry|admit|axiom|unsafe)\b")


def _refs(value: Any) -> list[str]:
    if isinstance(value, dict):
        if set(value) == {"node"} and isinstance(value["node"], str):
            return [value["node"]]
        return [item for child in value.values() for item in _refs(child)]
    if isinstance(value, list):
        return [item for child in value for item in _refs(child)]
    return []


def _ancestors(nodes: list[dict[str, Any]], root: str) -> list[dict[str, Any]]:
    by_name = {
        node.get("name"): node for node in nodes
        if isinstance(node, dict) and isinstance(node.get("name"), str)
    }
    seen: set[str] = set()
    pending = [root]
    ordered: list[dict[str, Any]] = []
    while pending:
        name = pending.pop()
        if name in seen or name not in by_name:
            continue
        seen.add(name)
        node = by_name[name]
        ordered.append(node)
        pending.extend(_refs(node.get("args")))
        pending.extend(_refs(node.get("kwargs")))
    return ordered


def _output_roots(nodes: list[dict[str, Any]]) -> list[str]:
    outputs = [node for node in nodes if node.get("op") == "output"]
    if len(outputs) != 1:
        raise ManifestError("structural inventory requires exactly one output node")
    return _refs(outputs[0].get("args"))


def _target(node: dict[str, Any]) -> str:
    return str(node.get("target", "")).lower()


def _has_target(nodes: list[dict[str, Any]], *needles: str) -> bool:
    return any(any(needle in _target(node) for needle in needles) for node in nodes)


def _direct_ref(value: Any) -> str | None:
    refs = _refs(value)
    return refs[0] if len(refs) == 1 else None


def _operator_construction(
    nodes: list[dict[str, Any]], root: str,
) -> tuple[str, list[str]]:
    by_name = {node["name"]: node for node in nodes if isinstance(node.get("name"), str)}
    provenance = [node["name"] for node in _ancestors(nodes, root)]
    root_node = by_name.get(root, {})
    if _has_target([root_node], "zeros", "zero.default"):
        return "zero", provenance
    if _has_target([root_node], "eye"):
        return "identity", provenance
    if _has_target([root_node], "add"):
        arguments = _refs(root_node.get("args"))
        if len(arguments) >= 2:
            left, right = arguments[:2]
            for base, transformed in ((left, right), (right, left)):
                transformed_node = by_name.get(transformed, {})
                if _has_target(
                    [transformed_node], "transpose", "permute", "t.default", "numpy_t"
                ):
                    if _direct_ref(transformed_node.get("args")) == base:
                        return "symmetrized", provenance
    if root_node.get("op") in {"placeholder", "get_attr"}:
        return "unconstrained_parameter", provenance
    return "unsupported", provenance


def _xc_form(nodes: list[dict[str, Any]], root: str) -> tuple[str, list[str]]:
    ancestors = _ancestors(nodes, root)
    provenance = [node["name"] for node in ancestors]
    if _has_target(ancestors, "relu", "clamp_min", "maximum"):
        return "hinge", provenance
    if _has_target(ancestors, "sigmoid", "softplus", "tanh"):
        return "smooth", provenance
    return "unsupported", provenance


def _adjacency_aliases(nodes: list[dict[str, Any]], adjacency_inputs: list[str]) -> list[str]:
    aliases = set(adjacency_inputs)
    while True:
        additions = {
            node["name"] for node in nodes
            if isinstance(node.get("name"), str)
            and any(name in _target(node) for name in ("aten.to", "_to_copy", "convert_element_type"))
            and len(_refs(node.get("args"))) == 1
            and _refs(node.get("args"))[0] in aliases
        }
        if additions <= aliases:
            return [node["name"] for node in nodes if node.get("name") in aliases]
        aliases.update(additions)


def _message_chain(
    nodes: list[dict[str, Any]], root: str, adjacency_inputs: list[str],
) -> list[str]:
    """Follow only consecutive adjacency-fed matmuls from the declared output."""
    by_name = {node["name"]: node for node in nodes if isinstance(node.get("name"), str)}
    adjacency_aliases = set(_adjacency_aliases(nodes, adjacency_inputs))
    current, stages = root, []
    while True:
        node = by_name.get(current, {})
        refs = _refs(node.get("args"))
        if not any(name in _target(node) for name in ("matmul", "mm.default", "bmm")):
            return stages
        adjacency = [ref for ref in refs if ref in adjacency_aliases]
        state = [ref for ref in refs if ref not in adjacency_aliases]
        if len(adjacency) != 1 or len(state) != 1:
            return stages
        stages.append(current)
        current = state[0]


def _state_entry(inventory: dict[str, Any], requested: str | None) -> dict[str, Any] | None:
    state = inventory.get("state", {})
    if not isinstance(state, dict):
        return None
    if requested and isinstance(state.get(requested), dict):
        return state[requested]
    for name, value in state.items():
        if "adjacency" in name.lower() and isinstance(value, dict):
            return value
    return None


def _state_name(inventory: dict[str, Any], requested: str | None) -> str | None:
    state = inventory.get("state", {})
    if not isinstance(state, dict):
        return None
    if requested and isinstance(state.get(requested), dict):
        return requested
    return next(
        (name for name, value in state.items()
         if isinstance(name, str) and "adjacency" in name.lower() and isinstance(value, dict)),
        None,
    )


def _topology(
    inventory: dict[str, Any], input_constraints: dict[str, Any],
) -> tuple[int, list[list[int]], list[str], str]:
    state_name = _state_name(inventory, input_constraints.get("adjacency_state_name"))
    entry = _state_entry(inventory, state_name)
    if not entry:
        raise ManifestError("artifact has no extractable structural adjacency buffer")
    values = entry.get("structural_values")
    if not isinstance(values, list) or not values or any(not isinstance(row, list) for row in values):
        raise ManifestError("adjacency buffer must be a small exported boolean/integer matrix")
    size = len(values)
    if any(len(row) != size for row in values):
        raise ManifestError("adjacency buffer must be square")
    convention = input_constraints.get("adjacency_convention", "target_source")
    if convention not in {"target_source", "source_target"}:
        raise ManifestError("adjacency_convention must be target_source or source_target")
    edges = []
    for row, values_row in enumerate(values):
        for column, connected in enumerate(values_row):
            if bool(connected):
                edges.append(
                    [column, row] if convention == "target_source" else [row, column]
                )
    provenance = entry.get("graph_inputs", [])
    return size, edges, [str(item) for item in provenance if isinstance(item, str)], state_name


def _role_roots(
    nodes: list[dict[str, Any]], input_constraints: dict[str, Any],
) -> dict[str, str]:
    roots = _output_roots(nodes)
    contracts = input_constraints.get("output_contracts")
    if not isinstance(contracts, list):
        raise ManifestError("output_contracts must identify structural output roles")
    result: dict[str, str] = {}
    for contract in contracts:
        if not isinstance(contract, dict):
            raise ManifestError("output contracts must be objects")
        index, role = contract.get("index"), contract.get("role")
        if not isinstance(index, int) or not isinstance(role, str) or index < 0 or index >= len(roots):
            raise ManifestError("output contract index or role is invalid")
        result[role] = roots[index]
    required = {"xc_energy", "learned_self_energy", "message_state"}
    if set(result) != required:
        raise ManifestError("output_contracts must map xc_energy, learned_self_energy, and message_state")
    return result


def structural_ir_from_inventory(
    *, inventory: dict[str, Any], artifact_sha256: str, extractor_version: str,
    input_constraints: dict[str, Any],
) -> dict[str, Any]:
    nodes = inventory.get("nodes")
    if not isinstance(nodes, list) or any(not isinstance(node, dict) for node in nodes):
        raise ManifestError("artifact graph inventory is malformed")
    roles = _role_roots(nodes, input_constraints)
    site_count, edges, topology_nodes, adjacency_state = _topology(inventory, input_constraints)
    stage_nodes = _message_chain(nodes, roles["message_state"], topology_nodes)
    depth = len(stage_nodes)
    xc_form, xc_nodes = _xc_form(nodes, roles["xc_energy"])
    operator, operator_nodes = _operator_construction(nodes, roles["learned_self_energy"])
    requirements = input_constraints.get("required_couplings", [])
    if not isinstance(requirements, list) or any(
        not isinstance(item, dict)
        or not isinstance(item.get("source"), int)
        or not isinstance(item.get("target"), int)
        for item in requirements
    ):
        raise ManifestError("required_couplings must contain integer source/target pairs")
    inventory_sha256 = sha256_value(inventory)
    state = inventory.get("state", {})
    parameter_structure = {
        name: {
            "shape": value.get("shape"),
            "dtype": value.get("dtype"),
            "sha256": value.get("sha256"),
            "state_kind": value.get("state_kind"),
            "aliases": value.get("aliases", [name]),
        }
        for name, value in state.items()
        if isinstance(name, str) and isinstance(value, dict)
    } if isinstance(state, dict) else {}
    translation = {
        "schema_version": 1,
        "inventory_sha256": inventory_sha256,
        "roles": roles,
        "topology": {
            "state_name": adjacency_state,
            "graph_inputs": topology_nodes,
            "adjacency_aliases": _adjacency_aliases(nodes, topology_nodes),
            "adjacency_convention": input_constraints.get("adjacency_convention", "target_source"),
        },
        "message_passing": {"root": roles["message_state"], "stages": stage_nodes},
        "xc": {"root": roles["xc_energy"], "form": xc_form},
        "operator": {"root": roles["learned_self_energy"], "construction": operator},
    }
    value = {
        "ir_schema_version": IR_SCHEMA_VERSION,
        "source": {
            "kind": "torch_export",
            "artifact_sha256": artifact_sha256,
            "inventory_sha256": inventory_sha256,
            "extractor_version": extractor_version,
            "analyzer_version": ANALYZER_VERSION,
            "parameter_structure_sha256": sha256_value(parameter_structure),
            "translation_sha256": sha256_value(translation),
        },
        "topology": {
            "site_count": site_count,
            "directed_edges": edges,
            "provenance_nodes": topology_nodes,
        },
        "message_passing": {"depth": depth, "provenance_nodes": stage_nodes},
        "xc": {"form": xc_form, "provenance_nodes": xc_nodes},
        "operator": {"construction": operator, "provenance_nodes": operator_nodes},
        "requirements": {
            "couplings": [
                {"source": item["source"], "target": item["target"]}
                for item in requirements
            ]
        },
        "translation": translation,
    }
    validate_structural_ir(value)
    value["translation_validation"] = validate_translation(
        inventory=inventory, value=value, input_constraints=input_constraints,
    )
    return value


def validate_structural_ir(value: dict[str, Any]) -> None:
    if not isinstance(value, dict) or value.get("ir_schema_version") != IR_SCHEMA_VERSION:
        raise ManifestError("structural IR must use schema version 2")
    source = value.get("source")
    if not isinstance(source, dict) or source.get("kind") not in {
        "torch_export", "confirmed_description"
    }:
        raise ManifestError("structural IR source is invalid")
    translation = value.get("translation")
    if source.get("kind") == "torch_export":
        if not isinstance(translation, dict) or source.get("translation_sha256") != sha256_value(translation):
            raise ManifestError("artifact structural IR needs a hash-bound translation derivation")
    topology = value.get("topology")
    message = value.get("message_passing")
    xc = value.get("xc")
    operator = value.get("operator")
    requirements = value.get("requirements")
    if not all(isinstance(item, dict) for item in (topology, message, xc, operator, requirements)):
        raise ManifestError("structural IR sections are missing")
    count = topology.get("site_count")
    edges = topology.get("directed_edges")
    if not isinstance(count, int) or isinstance(count, bool) or count <= 0:
        raise ManifestError("site_count must be positive")
    if not isinstance(edges, list) or any(
        not isinstance(edge, list) or len(edge) != 2
        or any(not isinstance(node, int) or node < 0 or node >= count for node in edge)
        for edge in edges
    ):
        raise ManifestError("directed_edges are invalid")
    depth = message.get("depth")
    if not isinstance(depth, int) or isinstance(depth, bool) or depth < 0:
        raise ManifestError("message-passing depth must be non-negative")
    if xc.get("form") not in {"hinge", "smooth", "unsupported"}:
        raise ManifestError("unsupported XC form value")
    if operator.get("construction") not in {
        "zero", "identity", "symmetrized", "unconstrained_parameter", "unsupported"
    }:
        raise ManifestError("unsupported operator construction value")
    couplings = requirements.get("couplings")
    if not isinstance(couplings, list) or any(
        not isinstance(item, dict)
        or not isinstance(item.get("source"), int)
        or not isinstance(item.get("target"), int)
        or item["source"] < 0 or item["source"] >= count
        or item["target"] < 0 or item["target"] >= count
        for item in couplings
    ):
        raise ManifestError("required couplings are invalid")


def validate_translation(
    *, inventory: dict[str, Any], value: dict[str, Any], input_constraints: dict[str, Any],
) -> dict[str, Any]:
    """Independently recheck an artifact IR's derivation against raw graph inventory."""
    validate_structural_ir(value)
    if value["source"]["kind"] != "torch_export":
        raise ManifestError("only exported artifacts have a translation derivation")
    translation = value["translation"]
    if translation.get("schema_version") != 1:
        raise ManifestError("unsupported translation derivation schema")
    if translation.get("inventory_sha256") != sha256_value(inventory):
        raise ManifestError("translation derivation is bound to a different inventory")
    nodes = inventory.get("nodes")
    if not isinstance(nodes, list) or any(not isinstance(node, dict) for node in nodes):
        raise ManifestError("translation validation needs a graph-node inventory")
    roles = _role_roots(nodes, input_constraints)
    if translation.get("roles") != roles:
        raise ManifestError("translation output roles do not match the raw exported graph")
    count, edges, graph_inputs, state_name = _topology(inventory, input_constraints)
    topology = translation.get("topology")
    if topology != {
        "state_name": state_name,
        "graph_inputs": graph_inputs,
        "adjacency_aliases": _adjacency_aliases(nodes, graph_inputs),
        "adjacency_convention": input_constraints.get("adjacency_convention", "target_source"),
    } or value["topology"]["site_count"] != count or value["topology"]["directed_edges"] != edges:
        raise ManifestError("translation topology claim does not match its adjacency evidence")
    stages = _message_chain(nodes, roles["message_state"], graph_inputs)
    if translation.get("message_passing") != {"root": roles["message_state"], "stages": stages}:
        raise ManifestError("translation message-passing derivation is invalid")
    if value["message_passing"] != {"depth": len(stages), "provenance_nodes": stages}:
        raise ManifestError("IR message-passing claim does not match its derivation")
    xc_form, xc_nodes = _xc_form(nodes, roles["xc_energy"])
    if translation.get("xc") != {"root": roles["xc_energy"], "form": xc_form}:
        raise ManifestError("translation XC derivation is invalid")
    if value["xc"] != {"form": xc_form, "provenance_nodes": xc_nodes}:
        raise ManifestError("IR XC claim does not match its derivation")
    operator, operator_nodes = _operator_construction(nodes, roles["learned_self_energy"])
    if translation.get("operator") != {
        "root": roles["learned_self_energy"], "construction": operator,
    }:
        raise ManifestError("translation operator derivation is invalid")
    if value["operator"] != {"construction": operator, "provenance_nodes": operator_nodes}:
        raise ManifestError("IR operator claim does not match its derivation")
    return {
        "status": "translation_validated",
        "translation_sha256": sha256_value(translation),
        "inventory_sha256": sha256_value(inventory),
        "checked_claims": ["output_roles", "topology", "message_passing", "xc", "operator"],
    }


def shortest_path(
    edges: list[list[int]], source: int, target: int, max_depth: int,
) -> list[int] | None:
    adjacency: dict[int, list[int]] = {}
    for left, right in edges:
        adjacency.setdefault(left, []).append(right)
    pending: deque[list[int]] = deque([[source]])
    seen = {(source, 0)}
    while pending:
        path = pending.popleft()
        if path[-1] == target:
            return path
        if len(path) - 1 >= max_depth:
            continue
        for neighbor in adjacency.get(path[-1], []):
            state = (neighbor, len(path))
            if state not in seen:
                seen.add(state)
                pending.append([*path, neighbor])
    return None


def assess_structural_ir(value: dict[str, Any]) -> dict[str, Any]:
    validate_structural_ir(value)
    topology = value["topology"]
    depth = value["message_passing"]["depth"]
    coupling_results = []
    for coupling in value["requirements"]["couplings"]:
        path = shortest_path(
            topology["directed_edges"], coupling["source"], coupling["target"], depth
        )
        coupling_results.append({**coupling, "covered": path is not None, "path": path})
    spatial = all(item["covered"] for item in coupling_results)
    xc = value["xc"]["form"] == "hinge"
    self_adjoint = value["operator"]["construction"] in {"zero", "identity", "symmetrized"}
    supported = (
        value["xc"]["form"] != "unsupported"
        and value["operator"]["construction"] != "unsupported"
    )
    checks = {
        "xc_discontinuity_compatible": {
            "satisfied": xc,
            "form": value["xc"]["form"],
            "provenance_nodes": value["xc"].get("provenance_nodes", []),
        },
        "spatial_nonlocality_compatible": {
            "satisfied": spatial,
            "depth": depth,
            "couplings": coupling_results,
            "provenance_nodes": value["message_passing"].get("provenance_nodes", []),
        },
        "self_adjoint": {
            "satisfied": self_adjoint,
            "construction": value["operator"]["construction"],
            "provenance_nodes": value["operator"].get("provenance_nodes", []),
        },
    }
    disposition = (
        "formalization_required" if not supported
        else "structurally_certifiable" if all(item["satisfied"] for item in checks.values())
        else "structural_requirements_not_met"
    )
    return {
        "status": disposition,
        "ir_sha256": sha256_value(value),
        "source": value["source"],
        "checks": checks,
    }


def structural_failure_witnesses(value: dict[str, Any]) -> list[dict[str, Any]]:
    assessment = assess_structural_ir(value)
    witnesses: list[dict[str, Any]] = []
    xc = assessment["checks"]["xc_discontinuity_compatible"]
    if not xc["satisfied"]:
        witnesses.append({
            "fact": "xc_discontinuity_compatible",
            "kind": "construction_form",
            "observed": xc["form"],
            "required": "hinge",
            "provenance_nodes": xc["provenance_nodes"],
        })
    spatial = assessment["checks"]["spatial_nonlocality_compatible"]
    for coupling in spatial["couplings"]:
        if not coupling["covered"]:
            witnesses.append({
                "fact": "spatial_nonlocality_compatible",
                "kind": "uncovered_coupling",
                "source": coupling["source"],
                "target": coupling["target"],
                "message_passing_depth": spatial["depth"],
                "provenance_nodes": spatial["provenance_nodes"],
            })
    operator = assessment["checks"]["self_adjoint"]
    if not operator["satisfied"]:
        witnesses.append({
            "fact": "self_adjoint",
            "kind": "operator_construction",
            "observed": operator["construction"],
            "required": ["zero", "identity", "symmetrized"],
            "provenance_nodes": operator["provenance_nodes"],
        })
    return witnesses


def structural_report(value: dict[str, Any]) -> dict[str, Any]:
    """Human-facing evidence report; it does not upgrade any trust boundary."""
    assessment = assess_structural_ir(value)
    source = value["source"]
    checks = assessment["checks"]
    return {
        "report_schema_version": 2,
        "status": assessment["status"],
        "certificate_kind": "artifact" if source["kind"] == "torch_export" else "confirmed_specification",
        "plain_summary": (
            "The exported graph passed every supported structural requirement."
            if assessment["status"] == "structurally_certifiable" else
            "The model is not structurally certifiable under the selected requirements; see concrete witnesses."
            if assessment["status"] == "structural_requirements_not_met" else
            "The exported graph uses a construction outside the currently formalized structural vocabulary."
        ),
        "source_binding": source,
        "translation_validation": value.get("translation_validation"),
        "checks": [
            {
                "name": name,
                "satisfied": check["satisfied"],
                "what_was_checked": {
                    "xc_discontinuity_compatible": "The declared XC output path contains a supported hinge construction.",
                    "spatial_nonlocality_compatible": "Every required source-to-target coupling has a directed path within the extracted adjacency-fed layer count.",
                    "self_adjoint": "The declared operator output is structurally zero, identity, or a parameter plus its transpose.",
                }[name],
                "evidence": check,
            }
            for name, check in checks.items()
        ],
        "failure_witnesses": structural_failure_witnesses(value),
        "trust_boundary": [
            "The PT2 artifact is deserialized only by the extractor boundary; its SHA-256 binds this report to that file.",
            "The translation validator independently rechecks the IR claims against the exported graph inventory.",
            "Lean can verify the generated structural theorems, but it does not parse the PT2 binary itself.",
            "This report does not assess trained-weight quality, numerical accuracy, convergence, or experiment.",
        ],
    }


def structural_model_description(value: dict[str, Any]) -> str:
    """Readable, deterministic context for local proof agents and reports."""
    validate_structural_ir(value)
    topology = value["topology"]
    source = value["source"]
    translation = value.get("translation", {})
    lines = [
        "Artifact-derived model description (not an LLM interpretation):",
        f"- Source: {source['kind']}; binding hash: {source.get('artifact_sha256', source.get('description_sha256', 'unknown'))}.",
        f"- Topology: {topology['site_count']} sites and {len(topology['directed_edges'])} directed edges.",
        f"- Required couplings: {value['requirements']['couplings']}.",
        f"- Message passing: {value['message_passing']['depth']} consecutive adjacency-fed stage(s): {value['message_passing'].get('provenance_nodes', [])}.",
        f"- XC output construction: {value['xc']['form']}; supporting graph nodes: {value['xc'].get('provenance_nodes', [])}.",
        f"- Self-energy construction: {value['operator']['construction']}; supporting graph nodes: {value['operator'].get('provenance_nodes', [])}.",
    ]
    if source["kind"] == "torch_export":
        lines.extend([
            f"- Declared output roots: {translation.get('roles', {})}.",
            f"- Adjacency evidence: state {translation.get('topology', {}).get('state_name')!r}; graph nodes {translation.get('topology', {}).get('adjacency_aliases', [])}.",
            "- Translation validation rechecked these claims against the raw exported inventory.",
        ])
    lines.append(
        "Scope: structural compatibility only; this does not assess numerical outputs, trained weights, convergence, or experiment."
    )
    return "\n".join(lines)


def _lean_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _lean_edges(edges: list[list[int]]) -> str:
    return "[" + ", ".join(f"({left}, {right})" for left, right in edges) + "]"


def _lean_couplings(couplings: list[dict[str, int]]) -> str:
    return "[" + ", ".join(
        f"({item['source']}, {item['target']})" for item in couplings
    ) + "]"


def _lean_xc(form: str) -> str:
    return {"hinge": ".hinge", "smooth": ".smooth", "unsupported": ".unsupported"}[form]


def _lean_operator(construction: str) -> str:
    return {
        "zero": ".zero",
        "identity": ".identity",
        "symmetrized": '.add (.parameter "base") (.adjoint (.parameter "base"))',
        "unconstrained_parameter": '.parameter "unconstrained"',
        "unsupported": ".unsupported",
    }[construction]


def generate_structural_obligations(value: dict[str, Any]) -> dict[str, Any]:
    assessment = assess_structural_ir(value)
    source = value["source"]
    source_hash = (
        source.get("artifact_sha256") or source.get("description_sha256")
    )
    if not isinstance(source_hash, str) or not source_hash:
        raise ManifestError("structural IR source hash is missing")
    ir_hash = assessment["ir_sha256"]
    namespace = f"DFTCert.StructuralRun_{ir_hash[:12]}"
    preamble = f"""namespace {namespace}

def sourceSha256 : String := \"{_lean_string(source_hash)}\"
def irSha256 : String := \"{ir_hash}\"
def edges : List (Nat × Nat) := {_lean_edges(value['topology']['directed_edges'])}
def messageDepth : Nat := {value['message_passing']['depth']}
def requiredCouplings : List (Nat × Nat) := {_lean_couplings(value['requirements']['couplings'])}
def xcForm : Testv2.StructuralV2.XCForm := {_lean_xc(value['xc']['form'])}
def operatorForm : Testv2.StructuralV2.OperatorForm := {_lean_operator(value['operator']['construction'])}

end {namespace}
"""
    expected = {
        "xc_discontinuity_compatible": assessment["checks"]["xc_discontinuity_compatible"]["satisfied"],
        "spatial_nonlocality_compatible": assessment["checks"]["spatial_nonlocality_compatible"]["satisfied"],
        "self_adjoint": assessment["checks"]["self_adjoint"]["satisfied"],
    }
    statements = {
        "xc_discontinuity_compatible": (
            f"theorem generated_xc_structure : Testv2.StructuralV2.xcSupportsDiscontinuity "
            f"{namespace}.xcForm = {str(expected['xc_discontinuity_compatible']).lower()}"
        ),
        "spatial_nonlocality_compatible": (
            f"theorem generated_spatial_structure : Testv2.StructuralV2.allCovered "
            f"{namespace}.edges {namespace}.messageDepth {namespace}.requiredCouplings = "
            f"{str(expected['spatial_nonlocality_compatible']).lower()}"
        ),
        "self_adjoint": (
            f"theorem generated_operator_structure : Testv2.StructuralV2.guaranteedSelfAdjoint "
            f"{namespace}.operatorForm = {str(expected['self_adjoint']).lower()}"
        ),
    }
    tasks = []
    for fact, theorem in statements.items():
        tasks.append({
            "id": f"{ir_hash[:12]}-{fact}",
            "fact": fact,
            "status": "proof_required",
            "project": "testv2",
            "module": "Testv2.StructuralV2",
            "verification_mode": "generated_obligation",
            "theorem": theorem,
            "preamble": preamble,
            "preamble_sha256": hashlib.sha256(preamble.encode()).hexdigest(),
            "structural_expected": expected[fact],
            "ir_sha256": ir_hash,
            "source_sha256": source_hash,
            "context": (
                structural_model_description(value) + "\n\n"
                + "DFT Structural V2 obligation generated deterministically from the common IR. "
                "Prove the exact Boolean structural result. Prefer `by decide`, whose result "
                "is reduced by Lean's kernel for this small finite input."
            ),
            "subgoals": [{
                "id": f"evaluate-{fact}",
                "theorem": theorem,
                "depends_on": [],
                "context": "Reduce the generic structural checker on the generated finite data.",
            }],
            "limits": {"wall_time_ms": 600000, "cpu_time_s": 480, "memory_mb": 8192},
        })
    return {
        "status": "obligations_generated",
        "compiler_version": COMPILER_VERSION,
        "ir_sha256": ir_hash,
        "source_sha256": source_hash,
        "policy_version": POLICY_VERSION,
        "disposition": assessment["status"],
        "assessment": assessment,
        "failure_witnesses": structural_failure_witnesses(value),
        "obligations": tasks,
    }


def _proof_results(value: Any) -> dict[str, dict[str, Any]]:
    entries = value.get("results") if isinstance(value, dict) and "results" in value else value
    if not isinstance(entries, list):
        raise ManifestError("proof results must be an array or an object with results")
    result: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
            raise ManifestError("each proof result needs a string id")
        if entry["id"] in result:
            raise ManifestError(f"duplicate proof result {entry['id']!r}")
        result[entry["id"]] = entry
    return result


def assemble_structural_certificate(
    value: dict[str, Any], proof_results: Any,
) -> tuple[str, dict[str, Any]]:
    generated = generate_structural_obligations(value)
    translation_validation = value.get("translation_validation")
    if value["source"]["kind"] == "torch_export" and (
        not isinstance(translation_validation, dict)
        or translation_validation.get("status") != "translation_validated"
        or translation_validation.get("translation_sha256")
        != value["source"].get("translation_sha256")
    ):
        raise ManifestError("artifact certificate assembly requires a validated translation derivation")
    results = _proof_results(proof_results)
    declarations: list[str] = []
    evidence: list[dict[str, Any]] = []
    for task in generated["obligations"]:
        result = results.get(task["id"])
        if not result or result.get("status") != "verified":
            raise ManifestError(f"obligation {task['id']!r} has no verified result")
        winner = result.get("winner")
        patch = winner.get("patch") if isinstance(winner, dict) else None
        if not isinstance(patch, str) or not patch.strip() or _FORBIDDEN.search(patch):
            raise ManifestError(f"obligation {task['id']!r} has an unsafe or missing winner")
        declarations.append(f"{task['theorem']} := {patch}\n")
        evidence.append({
            "id": task["id"],
            "fact": task["fact"],
            "proof_sha256": hashlib.sha256(patch.encode()).hexdigest(),
            "orchestrator_status": "verified",
        })
    namespace = f"DFTCert.StructuralRun_{generated['ir_sha256'][:12]}"
    source = (
        "import Testv2.StructuralV2\n\n"
        + generated["obligations"][0]["preamble"] + "\n"
        + "\n".join(declarations) + "\n"
        + f"theorem generated_source_binding : {namespace}.sourceSha256 = "
        + f"\"{generated['source_sha256']}\" := rfl\n"
        + f"theorem generated_ir_binding : {namespace}.irSha256 = "
        + f"\"{generated['ir_sha256']}\" := rfl\n\n"
        + f"#check (generated_source_binding : {namespace}.sourceSha256 = "
        + f"\"{generated['source_sha256']}\")\n"
        + f"#check (generated_ir_binding : {namespace}.irSha256 = "
        + f"\"{generated['ir_sha256']}\")\n"
    )
    source_kind = value["source"]["kind"]
    report = {
        "report_schema_version": 2,
        "status": "assembled_pending_certificate_check",
        "certificate_kind": (
            "artifact" if source_kind == "torch_export" else "confirmed_specification"
        ),
        "policy_version": POLICY_VERSION,
        "compiler_version": COMPILER_VERSION,
        "source": value["source"],
        "source_sha256": generated["source_sha256"],
        "ir_sha256": generated["ir_sha256"],
        "certificate_source_sha256": hashlib.sha256(source.encode()).hexdigest(),
        "structural_disposition": generated["disposition"],
        "failure_witnesses": generated["failure_witnesses"],
        "translation_validation": translation_validation,
        "obligations": evidence,
    }
    report["report_sha256"] = sha256_value(report)
    return source, report


def verify_structural_certificate(
    *, project_root: str | Path, certificate_source: str | Path,
    lean_command: Sequence[str] = ("lake", "env", "lean", "-j", "1"),
    timeout_s: int = 60, trusted_local: bool = False,
) -> dict[str, Any]:
    if not trusted_local:
        raise ManifestError(
            "certificate compilation requires --trusted-local until a compiler sandbox is configured"
        )
    if not lean_command:
        raise ManifestError("Lean command cannot be empty")
    root = Path(project_root).resolve()
    source_path = Path(certificate_source).resolve()
    source = source_path.read_text(encoding="utf-8")
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="dftcert-v2-") as directory:
        check = Path(directory) / "StructuralCertificateCheck.lean"
        check.write_text(source, encoding="utf-8")
        try:
            process = subprocess.run(
                [*lean_command, str(check)], cwd=root, text=True,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                timeout=timeout_s, check=False,
            )
            status = "verified" if process.returncode == 0 else "lean_error"
            diagnostics = process.stdout
        except subprocess.TimeoutExpired as error:
            status = "timeout"
            diagnostics = str(error)
    return {
        "version": 2,
        "status": status,
        "project_root": str(root),
        "project_fingerprint": project_fingerprint(root),
        "certificate_source_sha256": hashlib.sha256(source.encode()).hexdigest(),
        "elapsed_ms": int((time.monotonic() - started) * 1000),
        "diagnostics": diagnostics,
    }


def confirmed_description_ir(
    *, description: str, topology: dict[str, Any], message_passing: dict[str, Any],
    xc: dict[str, Any], operator: dict[str, Any], requirements: dict[str, Any],
) -> dict[str, Any]:
    description_hash = hashlib.sha256(description.encode()).hexdigest()
    value = {
        "ir_schema_version": IR_SCHEMA_VERSION,
        "source": {
            "kind": "confirmed_description",
            "description_sha256": description_hash,
            "confirmation_sha256": sha256_value({
                "topology": topology,
                "message_passing": message_passing,
                "xc": xc,
                "operator": operator,
                "requirements": requirements,
            }),
        },
        "topology": topology,
        "message_passing": message_passing,
        "xc": xc,
        "operator": operator,
        "requirements": requirements,
    }
    validate_structural_ir(value)
    return value
