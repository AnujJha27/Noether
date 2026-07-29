from __future__ import annotations

import json
import os
import subprocess
import threading
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from collections import deque
from typing import Any, Iterable, Sequence


class ProviderError(RuntimeError):
    pass


class LlmProvider(ABC):
    """An adapter that returns one structured JSON object per model call."""

    @abstractmethod
    def complete(self, *, agent: str, system: str, prompt: str,
                 schema: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError


def _object_from_output(output: str) -> dict[str, Any]:
    output = output.strip()
    try:
        value = json.loads(output)
    except json.JSONDecodeError:
        start = output.find("{")
        end = output.rfind("}")
        if start < 0 or end <= start:
            raise ProviderError("LLM output did not contain a JSON object")
        try:
            value = json.loads(output[start:end + 1])
        except json.JSONDecodeError as error:
            raise ProviderError(f"LLM returned invalid JSON: {error}") from error
    if not isinstance(value, dict):
        raise ProviderError("LLM response must be a JSON object")
    return value


class CommandProvider(LlmProvider):
    """Runs an arbitrary model adapter command using a small JSON stdin/stdout contract."""

    def __init__(self, command: Sequence[str], timeout_s: int = 120):
        if not command:
            raise ValueError("LLM command cannot be empty")
        self.command = list(command)
        self.timeout_s = timeout_s

    def complete(self, *, agent: str, system: str, prompt: str,
                 schema: dict[str, Any]) -> dict[str, Any]:
        envelope = {"agent": agent, "system": system, "prompt": prompt, "schema": schema}
        try:
            process = subprocess.run(
                self.command, input=json.dumps(envelope), text=True,
                capture_output=True, timeout=self.timeout_s, check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise ProviderError(f"LLM command failed: {error}") from error
        if process.returncode != 0:
            detail = process.stderr.strip() or f"exit code {process.returncode}"
            raise ProviderError(f"LLM command failed: {detail}")
        return _object_from_output(process.stdout)


class HttpProvider(LlmProvider):
    """POSTs the same provider-neutral envelope to an HTTP model gateway."""

    def __init__(self, url: str, token: str | None = None, timeout_s: int = 120):
        if not url:
            raise ValueError("LLM URL cannot be empty")
        self.url = url
        self.token = token
        self.timeout_s = timeout_s

    def complete(self, *, agent: str, system: str, prompt: str,
                 schema: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(
            {"agent": agent, "system": system, "prompt": prompt, "schema": schema}
        ).encode()
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        request = urllib.request.Request(self.url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
                output = response.read().decode()
        except (urllib.error.URLError, TimeoutError) as error:
            raise ProviderError(f"LLM gateway request failed: {error}") from error
        return _object_from_output(output)


class MockProvider(LlmProvider):
    """Thread-safe scripted provider used by tests and local dry runs."""

    def __init__(self, responses: Iterable[dict[str, Any]] | None = None):
        self._responses = deque(responses or [])
        self._lock = threading.Lock()

    def complete(self, *, agent: str, system: str, prompt: str,
                 schema: dict[str, Any]) -> dict[str, Any]:
        del system, prompt, schema
        with self._lock:
            if self._responses:
                return self._responses.popleft()
        if agent == "critic":
            return {"ordered_ids": [], "feedback": "mock critic preserves proposal order"}
        return {"candidates": [{"patch": "by rfl", "rationale": "mock proof"}]}


def token_from_environment() -> str | None:
    return os.environ.get("LLM_API_TOKEN")
