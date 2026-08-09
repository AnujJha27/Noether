from __future__ import annotations

import fcntl
import json
import os
import shlex
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from orchestrator.engine import Orchestrator, SearchConfig
from orchestrator.models import SearchTask
from orchestrator.providers import CommandProvider
from orchestrator.verifier import VerifierClient

from .assembly import assemble_certificate
from .certificate import verify_certificate
from .manifest import ArchitectureManifest, canonical_json, sha256_value
from .obligations import generate_obligations
from .policy import Policy
from .report import sanity_report


class PipelineError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class LocalPipelineConfig:
    project_root: str
    verifier_command: tuple[str, ...]
    verifier_cwd: str
    llm_command: tuple[str, ...]
    lean_command: tuple[str, ...]
    certificate_timeout_s: int = 1800
    llm_timeout_s: int = 600
    max_rounds_per_run: int = 3

    def to_json(self) -> dict[str, Any]:
        value = asdict(self)
        for name in ("verifier_command", "llm_command", "lean_command"):
            value[name] = list(value[name])
        return value

    @classmethod
    def from_json(cls, value: dict[str, Any]) -> "LocalPipelineConfig":
        copied = dict(value)
        for name in ("verifier_command", "llm_command", "lean_command"):
            copied[name] = tuple(copied[name])
        return cls(**copied)


class LocalRun:
    """Atomic, resumable on-disk state for one local certification run."""

    def __init__(self, directory: str | Path):
        self.directory = Path(directory).resolve()
        self.state_path = self.directory / "state.json"
        self.events_path = self.directory / "events.jsonl"
        self.lock_path = self.directory / ".lock"

    def create(self, *, manifest: ArchitectureManifest, policy: Policy,
               config: LocalPipelineConfig) -> dict[str, Any]:
        self.directory.mkdir(parents=True, exist_ok=True)
        if self.state_path.exists():
            raise PipelineError("run directory already contains state; use resume")
        state = {
            "run_schema_version": 1,
            "status": "initialized",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "manifest": manifest.value,
            "policy": {"id": policy.id, "version": policy.version},
            "config": config.to_json(),
            "proof_results": [],
        }
        self.write(state)
        self.event("run_created", {"manifest_sha256": manifest.value["manifest_sha256"]})
        return state

    def load(self) -> dict[str, Any]:
        try:
            value = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise PipelineError(f"cannot read local run state: {error}") from error
        if not isinstance(value, dict) or value.get("run_schema_version") != 1:
            raise PipelineError("unsupported or malformed local run state")
        return value

    def write(self, state: dict[str, Any]) -> None:
        state["updated_at"] = datetime.now(timezone.utc).isoformat()
        temporary = self.state_path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        temporary.replace(self.state_path)

    def event(self, event: str, fields: dict[str, Any]) -> None:
        previous = "0" * 64
        if self.events_path.exists():
            lines = [
                line for line in self.events_path.read_text(encoding="utf-8").splitlines()
                if line
            ]
            if lines:
                previous = json.loads(lines[-1])["event_sha256"]
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": event,
            "fields": fields,
            "previous_sha256": previous,
        }
        entry["event_sha256"] = sha256_value(entry)
        descriptor = os.open(
            self.events_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600
        )
        try:
            os.write(descriptor, canonical_json(entry) + b"\n")
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def lock(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(self.lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            os.close(descriptor)
            raise PipelineError("this local run is already active") from error
        return descriptor


class LocalPipeline:
    def __init__(self, *, run: LocalRun, policy: Policy,
                 config: LocalPipelineConfig):
        self.run = run
        self.policy = policy
        self.config = config

    def start(self, manifest: ArchitectureManifest) -> dict[str, Any]:
        manifest.validate(self.policy, require_confirmed=True)
        self.run.create(manifest=manifest, policy=self.policy, config=self.config)
        return self.execute()

    def resume(self) -> dict[str, Any]:
        state = self.run.load()
        stored = LocalPipelineConfig.from_json(state["config"])
        if stored != self.config:
            raise PipelineError("resume configuration differs from the original run")
        return self.execute()

    def _save(self, state: dict[str, Any], status: str,
              event_fields: dict[str, Any] | None = None) -> None:
        state["status"] = status
        self.run.write(state)
        self.run.event(status, event_fields or {})

    def execute(self) -> dict[str, Any]:
        lock = self.run.lock()
        try:
            return self._execute_locked()
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)
            os.close(lock)

    def _execute_locked(self) -> dict[str, Any]:
        state = self.run.load()
        if state["policy"] != {"id": self.policy.id, "version": self.policy.version}:
            raise PipelineError("run policy differs from the selected policy")
        if state["status"] in {"approved", "not_approved"}:
            return state
        manifest = ArchitectureManifest(state["manifest"])
        manifest.validate(self.policy, require_confirmed=True)
        generated = generate_obligations(manifest, self.policy)
        state["generation"] = generated
        if generated["status"] != "obligations_generated":
            self._save(state, generated["status"])
            return state
        rejected = [
            task for task in generated["obligations"]
            if task["status"] in {"refuted", "inconclusive"}
        ]
        if rejected:
            report = sanity_report(manifest=manifest, policy=self.policy)
            report_path = self.run.directory / "report.json"
            report_path.write_text(
                json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            state["report"] = report
            state["report_file"] = "report.json"
            state["non_approved_obligations"] = [
                {"id": task["id"], "fact": task["fact"], "status": task["status"]}
                for task in rejected
            ]
            self._save(state, "not_approved", {
                "report_sha256": report["report_sha256"],
                "obligations": state["non_approved_obligations"],
            })
            return state
        self._save(state, "proof_search_running")
        prior_results = {
            result["id"]: result
            for result in state.get("proof_results", [])
            if isinstance(result, dict) and isinstance(result.get("id"), str)
        }
        environment = os.environ.copy()
        environment.update({
            "PROOF_SEARCH_ALLOW_GENERATED_OBLIGATIONS": "1",
            "PROOF_SEARCH_PROJECT_DIR": self.config.project_root,
            "PROOF_SEARCH_DB": str(self.run.directory / "proof-search.db"),
        })
        provider = CommandProvider(
            list(self.config.llm_command), timeout_s=self.config.llm_timeout_s
        )
        with VerifierClient(
            list(self.config.verifier_command), cwd=self.config.verifier_cwd,
            env=environment,
        ) as verifier:
            for task_value in generated["obligations"]:
                if task_value["status"] != "proof_required":
                    continue
                previous = prior_results.get(task_value["id"])
                if previous and previous.get("status") == "verified":
                    continue
                engine = Orchestrator(
                    provider, verifier,
                    SearchConfig(max_rounds=self.config.max_rounds_per_run),
                    progress_sink=lambda event: self.run.event(
                        str(event.get("type", "progress")), event
                    ),
                )
                result = engine.search(
                    SearchTask.from_json(task_value), resume=previous
                )
                prior_results[task_value["id"]] = result
                state["proof_results"] = list(prior_results.values())
                self.run.write(state)
                self.run.event("proof_search_checkpoint", {
                    "obligation": task_value["id"],
                    "status": result["status"],
                    "frontier": result["search_graph"]["frontier"],
                })
                if result["status"] != "verified":
                    state["incomplete_obligation"] = task_value["id"]
                    self._save(state, "proof_search_incomplete")
                    return state
        state.pop("incomplete_obligation", None)
        source, report = assemble_certificate(
            manifest=manifest, policy=self.policy,
            proof_results=state["proof_results"],
        )
        source_path = self.run.directory / "Certificate.lean"
        report_path = self.run.directory / "report.json"
        source_path.write_text(source, encoding="utf-8")
        self._save(state, "certificate_check_running")
        verification = verify_certificate(
            policy=self.policy, project_root=self.config.project_root,
            certificate_source=source_path, manifest=manifest,
            lean_command=self.config.lean_command,
            timeout_s=self.config.certificate_timeout_s, trusted_local=True,
        )
        report["status"] = (
            "approved" if verification["status"] == "verified"
            else "certificate_check_failed"
        )
        report["certificate_verification"] = verification
        report.pop("report_sha256", None)
        report["report_sha256"] = sha256_value(report)
        report_path.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        state["report"] = report
        state["certificate_source"] = "Certificate.lean"
        state["report_file"] = "report.json"
        self._save(state, report["status"], {
            "report_sha256": report["report_sha256"]
        })
        return state


def command_tuple(value: str) -> tuple[str, ...]:
    result = tuple(shlex.split(value))
    if not result:
        raise PipelineError("command cannot be empty")
    return result
