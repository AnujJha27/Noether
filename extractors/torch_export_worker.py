#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any


EXTRACTOR_VERSION = "torch-export-inventory-v2"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def json_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (list, tuple)):
        return [json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): json_value(child) for key, child in value.items()}
    if hasattr(value, "name") and hasattr(value, "op"):
        return {"node": str(value.name)}
    return repr(value)


def tensor_metadata(node: Any) -> dict[str, Any] | None:
    metadata = getattr(node, "meta", {})
    value = metadata.get("val") if isinstance(metadata, dict) else None
    if value is None:
        return None
    shape = getattr(value, "shape", None)
    dtype = getattr(value, "dtype", None)
    if shape is None and dtype is None:
        return None
    return {
        "shape": [str(item) for item in shape] if shape is not None else None,
        "dtype": str(dtype) if dtype is not None else None,
    }


def inventory_node(node: Any) -> dict[str, Any]:
    result = {
        "name": str(node.name),
        "op": str(node.op),
        "target": str(node.target),
        "args": json_value(node.args),
        "kwargs": json_value(node.kwargs),
    }
    tensor = tensor_metadata(node)
    if tensor is not None:
        result["tensor"] = tensor
    return result


def state_inventory(program: Any) -> dict[str, Any]:
    graph_inputs: dict[str, list[str]] = {}
    state_kinds: dict[str, str] = {}
    signature = getattr(program, "graph_signature", None)
    for spec in getattr(signature, "input_specs", []):
        target = getattr(spec, "target", None)
        argument = getattr(spec, "arg", None)
        name = getattr(argument, "name", None)
        if isinstance(target, str) and isinstance(name, str):
            graph_inputs.setdefault(target, []).append(name)
            state_kinds[target] = str(getattr(spec, "kind", "unknown"))
    aliases: dict[int, list[str]] = {}
    for name, tensor in program.state_dict.items():
        aliases.setdefault(tensor.untyped_storage().data_ptr(), []).append(str(name))
    result: dict[str, Any] = {}
    for name, tensor in program.state_dict.items():
        detached = tensor.detach().cpu().contiguous()
        raw = detached.numpy().tobytes()
        entry = {
            "shape": [int(item) for item in detached.shape],
            "dtype": str(detached.dtype),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "graph_inputs": graph_inputs.get(name, []),
            "state_kind": state_kinds.get(name, "unknown"),
            "aliases": sorted(aliases[tensor.untyped_storage().data_ptr()]),
        }
        if detached.dtype in {
            __import__("torch").bool,
            __import__("torch").int8,
            __import__("torch").int16,
            __import__("torch").int32,
            __import__("torch").int64,
        } and detached.numel() <= 4096:
            entry["structural_values"] = detached.tolist()
        result[str(name)] = entry
    return result


def extract(path: Path) -> dict[str, Any]:
    # This import and load are deliberately confined to the sandbox worker.
    import torch

    program = torch.export.load(str(path))
    graph_module = program.graph_module
    nodes = [inventory_node(node) for node in graph_module.graph.nodes]
    return {
        "status": "ok",
        "extractor_version": EXTRACTOR_VERSION,
        "torch_version": str(torch.__version__),
        "artifact_sha256": sha256_file(path),
        "inventory": {"nodes": nodes, "state": state_inventory(program)},
        # Inventory is evidence input, not a physics proof. Audited policy analyzers
        # may add facts in a later version; this worker does not infer them by name.
        "facts": {},
    }


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(json.dumps({"status": "error", "diagnostics": "expected one .pt2 path"}))
        return 2
    try:
        print(json.dumps(extract(Path(argv[1])), sort_keys=True, separators=(",", ":")))
        return 0
    except Exception as error:
        print(json.dumps({
            "status": "error",
            "diagnostics": f"{type(error).__name__}: {error}",
            "extractor_version": EXTRACTOR_VERSION,
        }, sort_keys=True, separators=(",", ":")))
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
