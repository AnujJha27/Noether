from __future__ import annotations

import json
import subprocess
import threading
from pathlib import Path
from typing import Any, Sequence


class VerifierError(RuntimeError):
    pass


class VerifierClient:
    """Owns a persistent proof-search JSONL subprocess."""

    def __init__(self, command: Sequence[str] = ("./build/proof-search",),
                 cwd: str | Path | None = None,
                 env: dict[str, str] | None = None):
        self.command = list(command)
        self.cwd = str(cwd) if cwd is not None else None
        self.env = dict(env) if env is not None else None
        self._process: subprocess.Popen[str] | None = None
        self._lock = threading.Lock()

    def start(self) -> None:
        if self._process is not None:
            return
        try:
            self._process = subprocess.Popen(
                self.command, cwd=self.cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True, bufsize=1, env=self.env,
            )
        except OSError as error:
            raise VerifierError(f"cannot start verifier: {error}") from error
        response = self.request({"version": 1, "id": "orchestrator-health", "type": "ping"})
        if response.get("status") != "ok":
            self.close()
            raise VerifierError(f"verifier health check failed: {response}")

    def request(self, value: dict[str, Any]) -> dict[str, Any]:
        if self._process is None:
            raise VerifierError("verifier has not been started")
        with self._lock:
            if self._process.poll() is not None:
                detail = self._process.stderr.read().strip() if self._process.stderr else ""
                raise VerifierError(f"verifier exited unexpectedly: {detail}")
            assert self._process.stdin is not None and self._process.stdout is not None
            try:
                self._process.stdin.write(json.dumps(value, separators=(",", ":")) + "\n")
                self._process.stdin.flush()
                line = self._process.stdout.readline()
            except (BrokenPipeError, OSError) as error:
                raise VerifierError(f"verifier communication failed: {error}") from error
            if not line:
                detail = self._process.stderr.read().strip() if self._process.stderr else ""
                raise VerifierError(f"verifier closed its output: {detail}")
            try:
                response = json.loads(line)
            except json.JSONDecodeError as error:
                raise VerifierError(f"verifier returned invalid JSON: {line.strip()}") from error
            if not isinstance(response, dict):
                raise VerifierError("verifier response was not an object")
            return response

    def verify_batch(self, *, request_id: str, target: str, project: str,
                     module: str, declaration: str,
                     candidates: list[dict[str, str]], max_parallel: int,
                     stop_on_first_success: bool, limits: dict[str, int],
                     parent_attempt_id: str | None = None) -> dict[str, Any]:
        request: dict[str, Any] = {
            "version": 1, "id": request_id, "type": "search_batch", "project": project,
            "module": module, "declaration": declaration, "target": target,
            "candidates": candidates, "max_parallel": max_parallel,
            "stop_on_first_success": stop_on_first_success,
        }
        if limits:
            request["limits"] = limits
        if parent_attempt_id:
            request["parent_attempt_id"] = parent_attempt_id
        return self.request(request)

    def verify_generated_batch(
        self, *, request_id: str, project: str, module: str, declaration: str,
        preamble: str, candidates: list[dict[str, str]], max_parallel: int,
        stop_on_first_success: bool, limits: dict[str, int],
        parent_attempt_id: str | None = None,
    ) -> dict[str, Any]:
        request: dict[str, Any] = {
            "version": 1,
            "id": request_id,
            "type": "search_batch",
            "project": project,
            "module": module,
            "verification_mode": "generated_obligation",
            "declaration": declaration,
            "preamble": preamble,
            "candidates": candidates,
            "max_parallel": max_parallel,
            "stop_on_first_success": stop_on_first_success,
        }
        if limits:
            request["limits"] = limits
        if parent_attempt_id:
            request["parent_attempt_id"] = parent_attempt_id
        return self.request(request)

    def close(self) -> None:
        process, self._process = self._process, None
        if process is None:
            return
        if process.stdin:
            process.stdin.close()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        if process.stdout:
            process.stdout.close()
        if process.stderr:
            process.stderr.close()

    def __enter__(self) -> "VerifierClient":
        self.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
