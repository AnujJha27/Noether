from __future__ import annotations

import json
import os
import resource
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from .manifest import ManifestError, sha256_file
from .legacy.pt2 import inspect_pt2
from .security import sign_attestation


@dataclass(frozen=True, slots=True)
class SandboxLimits:
    wall_time_s: int = 30
    cpu_time_s: int = 20
    memory_mb: int = 2048
    max_processes: int = 32
    max_output_bytes: int = 2 * 1024 * 1024


class SandboxUnavailable(ManifestError):
    pass


class ExtractionFailed(ManifestError):
    pass


def _limit_process(limits: SandboxLimits) -> None:
    os.setsid()
    resource.setrlimit(resource.RLIMIT_CPU, (limits.cpu_time_s, limits.cpu_time_s))
    address_space = limits.memory_mb * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_AS, (address_space, address_space))
    resource.setrlimit(resource.RLIMIT_NPROC, (limits.max_processes, limits.max_processes))
    resource.setrlimit(resource.RLIMIT_FSIZE, (limits.max_output_bytes, limits.max_output_bytes))
    resource.setrlimit(resource.RLIMIT_NOFILE, (128, 128))


class BubblewrapExtractor:
    """Runs the only deserialization step inside a no-network bubblewrap sandbox."""

    def __init__(self, *, bubblewrap: str = "bwrap",
                 python: str = "/usr/bin/python3",
                 app_root: str | Path | None = None,
                 limits: SandboxLimits = SandboxLimits()):
        self.bubblewrap = bubblewrap
        self.python = python
        self.app_root = Path(app_root or Path(__file__).resolve().parents[1]).resolve()
        self.limits = limits

    def _runtime_binds(self) -> list[str]:
        arguments: list[str] = []
        for directory in ("/usr", "/usr/local", "/lib", "/lib64", "/bin"):
            if Path(directory).exists():
                arguments.extend(["--ro-bind", directory, directory])
        return arguments

    def command(self, artifact: str | Path) -> list[str]:
        artifact_path = Path(artifact).resolve()
        executable = shutil.which(self.bubblewrap)
        if executable is None:
            raise SandboxUnavailable(
                "bubblewrap is unavailable; refusing to deserialize an uploaded PT2 artifact"
            )
        return [
            executable,
            "--unshare-all",
            "--die-with-parent",
            "--new-session",
            "--clearenv",
            *self._runtime_binds(),
            "--ro-bind", str(self.app_root), "/app",
            "--ro-bind", str(artifact_path), "/input/model.pt2",
            "--tmpfs", "/tmp",
            "--proc", "/proc",
            "--dev", "/dev",
            "--chdir", "/app",
            "--setenv", "PATH", "/usr/local/bin:/usr/bin:/bin",
            "--setenv", "PYTHONPATH", "/app",
            self.python,
            "/app/extractors/torch_export_worker.py",
            "/input/model.pt2",
        ]

    def extract(self, artifact: str | Path) -> dict[str, Any]:
        inspection = inspect_pt2(artifact)
        command = self.command(artifact)
        try:
            with tempfile.TemporaryFile() as stdout_file, tempfile.TemporaryFile() as stderr_file:
                completed = subprocess.run(
                    command,
                    stdin=subprocess.DEVNULL,
                    stdout=stdout_file,
                    stderr=stderr_file,
                    timeout=self.limits.wall_time_s,
                    check=False,
                    preexec_fn=lambda: _limit_process(self.limits),
                )
                if (
                    stdout_file.tell() > self.limits.max_output_bytes
                    or stderr_file.tell() > self.limits.max_output_bytes
                ):
                    raise ExtractionFailed("extractor output exceeded its configured limit")
                stdout_file.seek(0)
                stderr_file.seek(0)
                stdout = stdout_file.read().decode("utf-8", errors="replace")
                stderr = stderr_file.read().decode("utf-8", errors="replace")
        except subprocess.TimeoutExpired as error:
            raise ExtractionFailed("sandboxed extractor exceeded its wall-time limit") from error
        except OSError as error:
            raise SandboxUnavailable(f"cannot start bubblewrap: {error}") from error
        if completed.returncode != 0:
            detail = stderr.strip() or stdout.strip() or f"exit code {completed.returncode}"
            if "Operation not permitted" in detail or "Creating new namespace failed" in detail:
                raise SandboxUnavailable(
                    "bubblewrap cannot create namespaces in this environment; "
                    "refusing unsandboxed PT2 deserialization"
                )
            raise ExtractionFailed(f"sandboxed extractor failed: {detail}")
        lines = [line for line in stdout.splitlines() if line.strip()]
        if len(lines) != 1:
            raise ExtractionFailed("extractor must emit exactly one JSON object")
        try:
            result = json.loads(lines[0])
        except json.JSONDecodeError as error:
            raise ExtractionFailed("extractor returned invalid JSON") from error
        if not isinstance(result, dict):
            raise ExtractionFailed("extractor result must be a JSON object")
        if result.get("status") != "ok":
            raise ExtractionFailed(str(result.get("diagnostics", "extractor did not succeed")))
        if result.get("artifact_sha256") != inspection["artifact_sha256"]:
            raise ExtractionFailed("extractor result is not bound to the submitted artifact")
        result.pop("status", None)
        attestation = {
            "runtime": "bubblewrap",
            "network": "unshared",
            "filesystem": "read_only",
            "artifact_sha256": sha256_file(artifact),
        }
        signing_key = os.environ.get("DFTCERT_ATTESTATION_KEY")
        result["sandbox_attestation"] = (
            sign_attestation(attestation, signing_key.encode())
            if signing_key else attestation
        )
        return result
