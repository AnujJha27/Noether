from __future__ import annotations

import hashlib
import json
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from ..manifest import ArchitectureManifest, ManifestError, sha256_file
from .policy import Policy


@dataclass(frozen=True, slots=True)
class Pt2Limits:
    max_archive_bytes: int = 512 * 1024 * 1024
    max_entries: int = 10_000
    max_uncompressed_bytes: int = 2 * 1024 * 1024 * 1024
    max_compression_ratio: int = 200


def inspect_pt2(path: str | Path, limits: Pt2Limits = Pt2Limits()) -> dict[str, Any]:
    artifact = Path(path)
    if artifact.suffix.lower() != ".pt2":
        raise ManifestError("PyTorch V1 accepts only .pt2 torch.export artifacts")
    size = artifact.stat().st_size
    if size <= 0 or size > limits.max_archive_bytes:
        raise ManifestError("PT2 archive size is outside configured limits")
    if not zipfile.is_zipfile(artifact):
        raise ManifestError("PT2 artifact is not a valid ZIP container")
    total_uncompressed = 0
    names: list[str] = []
    with zipfile.ZipFile(artifact) as archive:
        entries = archive.infolist()
        if not entries or len(entries) > limits.max_entries:
            raise ManifestError("PT2 archive entry count is outside configured limits")
        for entry in entries:
            name = PurePosixPath(entry.filename)
            if name.is_absolute() or ".." in name.parts:
                raise ManifestError("PT2 archive contains an unsafe path")
            total_uncompressed += entry.file_size
            if total_uncompressed > limits.max_uncompressed_bytes:
                raise ManifestError("PT2 archive expands beyond configured limits")
            if entry.compress_size and entry.file_size / entry.compress_size > limits.max_compression_ratio:
                raise ManifestError("PT2 archive contains a compression-ratio bomb")
            names.append(entry.filename)
    return {
        "artifact_sha256": sha256_file(artifact),
        "archive_bytes": size,
        "entry_count": len(names),
        "uncompressed_bytes": total_uncompressed,
        "entries_sha256": hashlib.sha256(
            json.dumps(sorted(names), separators=(",", ":")).encode()
        ).hexdigest(),
    }


def pending_manifest(*, path: str | Path, model_id: str, policy: Policy,
                     input_constraints: dict[str, Any]) -> ArchitectureManifest:
    if not model_id.strip() or not isinstance(input_constraints, dict) or not input_constraints:
        raise ManifestError("model_id and input_constraints are required")
    inspection = inspect_pt2(path)
    manifest = ArchitectureManifest({
        "manifest_schema_version": 1,
        "model_id": model_id,
        "policy": {"id": policy.id, "version": policy.version},
        "status": "extraction_pending",
        "source": {"kind": "torch_export", **inspection},
        "input_constraints": input_constraints,
        "facts": {},
        "unresolved_facts": list(policy.required_facts),
    })
    manifest.refresh_hash()
    manifest.validate(policy)
    return manifest
