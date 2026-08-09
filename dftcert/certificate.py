from __future__ import annotations

import hashlib
import os
import shlex
import signal
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Sequence

from .manifest import ArchitectureManifest, sha256_file
from .legacy.policy import Policy


class CertificateError(RuntimeError):
    pass


def project_fingerprint(project_root: str | Path) -> str:
    root = Path(project_root).resolve()
    paths: list[Path] = []
    for directory, child_directories, filenames in os.walk(root, followlinks=False):
        child_directories[:] = sorted(
            name for name in child_directories if name not in {".lake", ".git"}
        )
        base = Path(directory)
        for filename in sorted(filenames):
            path = base / filename
            if path.suffix == ".lean" or path.name in {
                "lean-toolchain", "lakefile.toml", "lakefile.lean"
            }:
                paths.append(path)
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(b"\0")
        with path.open("rb") as file:
            for block in iter(lambda: file.read(1024 * 1024), b""):
                digest.update(block)
        digest.update(b"\0")
    return digest.hexdigest()


def build_check_source(source: str, policy: Policy, manifest_sha256: str) -> str:
    requirement = policy.certificate
    return (
        source.rstrip() + "\n\n"
        f"#check ({requirement.declaration} : {requirement.expected_type})\n"
        f"#check ({requirement.manifest_hash_declaration} : "
        f"{requirement.manifest_hash_constant} = \"{manifest_sha256}\")\n"
    )


def verify_certificate(*, policy: Policy, project_root: str | Path,
                       certificate_source: str | Path,
                       manifest: ArchitectureManifest,
                       lean_command: Sequence[str] = ("lake", "env", "lean", "-j", "1"),
                       timeout_s: int = 60, trusted_local: bool = False) -> dict[str, Any]:
    if not trusted_local:
        raise CertificateError(
            "certificate compilation is disabled for untrusted sources until the container sandbox is active"
        )
    root = Path(project_root).resolve()
    source_path = Path(certificate_source).resolve()
    expected_toolchain = policy.toolchain.strip()
    try:
        actual_toolchain = (root / "lean-toolchain").read_text(encoding="utf-8").strip()
        source = source_path.read_text(encoding="utf-8")
    except OSError as error:
        raise CertificateError(f"cannot read project or certificate source: {error}") from error
    if actual_toolchain != expected_toolchain:
        raise CertificateError(
            f"toolchain mismatch: policy requires {expected_toolchain!r}, project has {actual_toolchain!r}"
        )
    if not lean_command:
        raise CertificateError("lean command cannot be empty")
    manifest.validate(policy, require_confirmed=True)
    manifest_sha256 = manifest.value["manifest_sha256"]
    wrapper = build_check_source(source, policy, manifest_sha256)
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="dftcert-") as directory:
        check_file = Path(directory) / "CertificateCheck.lean"
        check_file.write_text(wrapper, encoding="utf-8")
        command = [*lean_command, str(check_file)]
        try:
            process = subprocess.Popen(
                command, cwd=root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, start_new_session=True,
            )
        except OSError as error:
            raise CertificateError(f"cannot start Lean: {error}") from error
        try:
            output, _ = process.communicate(timeout=timeout_s)
            timed_out = False
        except subprocess.TimeoutExpired:
            timed_out = True
            os.killpg(process.pid, signal.SIGKILL)
            output, _ = process.communicate()
    elapsed_ms = int((time.monotonic() - started) * 1000)
    status = "timeout" if timed_out else "verified" if process.returncode == 0 else "lean_error"
    return {
        "version": 1,
        "status": status,
        "policy": {"id": policy.id, "version": policy.version,
                   "sha256": sha256_file(policy.source_path)},
        "project": {"id": policy.project_id, "root": str(root),
                    "fingerprint": project_fingerprint(root)},
        "toolchain": {"value": actual_toolchain,
                      "fingerprint": hashlib.sha256(actual_toolchain.encode()).hexdigest()},
        "certificate": {
            "source_sha256": sha256_file(source_path),
            "declaration": policy.certificate.declaration,
            "expected_type": policy.certificate.expected_type,
            "manifest_hash_declaration": policy.certificate.manifest_hash_declaration,
        },
        "manifest_sha256": manifest_sha256,
        "elapsed_ms": elapsed_ms,
        "diagnostics": output,
    }


def parse_command(value: str) -> list[str]:
    command = shlex.split(value)
    if not command:
        raise CertificateError("lean command cannot be empty")
    return command
