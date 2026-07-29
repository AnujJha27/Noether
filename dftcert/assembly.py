from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .manifest import ArchitectureManifest, canonical_json
from .obligations import generate_obligations
from .policy import Policy, PolicyError


class AssemblyError(ValueError):
    pass


_FORBIDDEN = re.compile(r"\b(sorry|admit|axiom|unsafe)\b")


def _lean_string(value: str) -> str:
    if any(ord(character) < 32 for character in value):
        raise AssemblyError("model_id contains a control character")
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _result_map(value: Any) -> dict[str, dict[str, Any]]:
    entries = value.get("results") if isinstance(value, dict) and "results" in value else value
    if not isinstance(entries, list):
        raise AssemblyError("proof results must be an array or an object with results")
    result: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
            raise AssemblyError("each proof result needs a string id")
        if entry["id"] in result:
            raise AssemblyError(f"duplicate proof result {entry['id']!r}")
        result[entry["id"]] = entry
    return result


def assemble_certificate(*, manifest: ArchitectureManifest, policy: Policy,
                         proof_results: Any) -> tuple[str, dict[str, Any]]:
    generated = generate_obligations(manifest, policy)
    if generated["status"] != "obligations_generated":
        raise AssemblyError(generated.get("reason", "obligations were not generated"))
    profile = policy.generation_profile(generated["profile"])
    results = _result_map(proof_results)
    proof_lines: list[str] = []
    evidence: list[dict[str, Any]] = []
    for task in generated["obligations"]:
        result = results.get(task["id"])
        if not result or result.get("status") != "verified":
            raise AssemblyError(f"obligation {task['id']!r} has no verified result")
        winner = result.get("winner")
        patch = winner.get("patch") if isinstance(winner, dict) else None
        if not isinstance(patch, str) or not patch.strip() or _FORBIDDEN.search(patch):
            raise AssemblyError(f"obligation {task['id']!r} has an unsafe or missing winner")
        proof_lines.append(f"{task['theorem']} := {patch}\n")
        evidence.append({
            "id": task["id"],
            "fact": task["fact"],
            "preamble_sha256": task["preamble_sha256"],
            "proof_sha256": hashlib.sha256(patch.encode("utf-8")).hexdigest(),
            "orchestrator_status": "verified",
        })
    try:
        assembly = profile.assembly_template.read_text(encoding="utf-8")
    except OSError as error:
        raise PolicyError(f"cannot read assembly template: {error}") from error
    assembly = assembly.replace(
        "{{model_name}}", _lean_string(str(manifest.value["model_id"]))
    )
    if "{{" in assembly or "}}" in assembly:
        raise AssemblyError("assembly template contains an unresolved placeholder")
    source = (
        f"import {profile.module}\n\n"
        + generated["obligations"][0]["preamble"]
        + "\n"
        + "\n".join(proof_lines)
        + "\n"
        + assembly
    )
    report = {
        "report_schema_version": 1,
        "status": "assembled_pending_certificate_check",
        "manifest_sha256": manifest.value["manifest_sha256"],
        "policy": {"id": policy.id, "version": policy.version},
        "profile": profile.id,
        "source_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
        "obligations": evidence,
    }
    report["report_sha256"] = hashlib.sha256(canonical_json(report)).hexdigest()
    return source, report


def load_proof_results(path: str | Path) -> Any:
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as error:
        raise AssemblyError(f"cannot read proof results: {error}") from error
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        entries = []
        for line_number, line in enumerate(text.splitlines(), 1):
            if not line.strip():
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError as error:
                raise AssemblyError(
                    f"invalid JSONL proof result on line {line_number}"
                ) from error
        return entries
