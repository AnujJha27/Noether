from __future__ import annotations

from typing import Any

from .manifest import ManifestError
from .policy import Policy


ANALYZER_VERSION = "dft-graph-analysis-v1"


def _node_refs(value: Any) -> list[str]:
    refs: list[str] = []
    if isinstance(value, dict):
        if set(value) == {"node"} and isinstance(value["node"], str):
            refs.append(value["node"])
        else:
            for child in value.values():
                refs.extend(_node_refs(child))
    elif isinstance(value, list):
        for child in value:
            refs.extend(_node_refs(child))
    return refs


def _targets(nodes: list[dict[str, Any]], roots: list[str]) -> tuple[set[str], list[str]]:
    by_name = {node.get("name"): node for node in nodes if isinstance(node.get("name"), str)}
    visited: set[str] = set()
    stack = list(roots)
    provenance: list[str] = []
    while stack:
        name = stack.pop()
        if name in visited or name not in by_name:
            continue
        visited.add(name)
        node = by_name[name]
        if node.get("op") not in {"placeholder", "output", "get_attr"}:
            provenance.append(name)
        stack.extend(_node_refs(node.get("args")))
        stack.extend(_node_refs(node.get("kwargs")))
    return {
        str(by_name[name].get("target"))
        for name in visited
        if by_name[name].get("op") not in {"placeholder", "output", "get_attr"}
    }, sorted(provenance)


def _output_roots(nodes: list[dict[str, Any]]) -> list[str]:
    outputs = [node for node in nodes if node.get("op") == "output"]
    if len(outputs) != 1:
        raise ManifestError("graph inventory must contain exactly one output node")
    return _node_refs(outputs[0].get("args"))


def analyze_inventory(*, inventory: dict[str, Any], policy: Policy,
                      input_constraints: dict[str, Any]) -> dict[str, Any]:
    nodes = inventory.get("nodes")
    contracts = input_constraints.get("output_contracts")
    if not isinstance(nodes, list) or any(not isinstance(node, dict) for node in nodes):
        raise ManifestError("graph inventory nodes are malformed")
    if not isinstance(contracts, list) or not contracts:
        return {
            "analyzer_version": ANALYZER_VERSION,
            "facts": {},
            "diagnostics": ["output_contracts are required for physics analysis"],
        }
    config = policy.graph_analysis
    pass_through = set(config.get("pass_through_targets", []))
    relu_targets = set(config.get("xc_hinge_targets", []))
    zero_targets = set(config.get("zero_operator_targets", []))
    pointwise_targets = set(config.get("pointwise_targets", []))
    roots = _output_roots(nodes)
    facts: dict[str, Any] = {}
    ir: dict[str, Any] = {"ir_schema_version": 1}
    diagnostics: list[str] = []
    for contract in contracts:
        if not isinstance(contract, dict) or not isinstance(contract.get("index"), int):
            raise ManifestError("each output contract needs an integer index")
        index = contract["index"]
        role = contract.get("role")
        if index < 0 or index >= len(roots) or not isinstance(role, str):
            raise ManifestError("output contract index or role is invalid")
        targets, provenance = _targets(nodes, [roots[index]])
        semantic = targets - pass_through
        if role == "xc_energy":
            if len(semantic) == 1 and semantic <= relu_targets:
                value = {
                    "satisfied": True, "mechanism": "piecewise_hinge",
                    "electron_boundaries": [0],
                }
                facts["xc_discontinuity_compatible"] = {
                    "value": value, "nodes": provenance,
                }
                ir["xc"] = {
                    "representation": "piecewise_hinge",
                    "boundary": 0, "left_slope": 0, "right_slope": 1,
                }
            else:
                diagnostics.append("XC output is outside the exact hinge rule")
        elif role == "learned_self_energy":
            is_zero = len(semantic) == 1 and semantic <= zero_targets
            if is_zero:
                facts["self_adjoint"] = {
                    "value": {"satisfied": True, "enforcement": "zero_operator"},
                    "nodes": provenance,
                }
                ir["operator"] = {"construction": "zero", "sites": 1}
            else:
                diagnostics.append("operator output is not an exactly recognized zero operator")
            if semantic <= pointwise_targets | zero_targets:
                requirements = input_constraints.get("required_couplings", [])
                if not isinstance(requirements, list):
                    raise ManifestError("required_couplings must be an array")
                uncovered = [
                    item for item in requirements
                    if isinstance(item, dict) and item.get("distance", 0) > 0
                ]
                facts["spatial_nonlocality_compatible"] = {
                    "value": {
                        "satisfied": not uncovered,
                        "receptive_field": 0,
                        "required_couplings": requirements,
                        "uncovered_couplings": uncovered,
                    },
                    "nodes": provenance,
                }
                ir["spatial"] = {
                    "adjacency": "fin1_complete",
                    "receptive_field": 0,
                    "required_couplings": requirements,
                }
            else:
                diagnostics.append("operator output contains non-pointwise unsupported operations")
        else:
            diagnostics.append(f"unsupported output role {role!r}")
    if set(ir) == {"ir_schema_version", "xc", "operator", "spatial"}:
        architecture_ir: dict[str, Any] | None = ir
    else:
        architecture_ir = None
    output: dict[str, Any] = {
        "analyzer_version": ANALYZER_VERSION,
        "facts": facts,
        "diagnostics": diagnostics,
    }
    if architecture_ir is not None:
        output["architecture_ir"] = architecture_ir
    return output
