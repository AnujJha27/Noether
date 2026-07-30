from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .models import SearchTask


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


@dataclass(slots=True)
class RunState:
    run_id: str
    status: str
    tasks: list[dict[str, Any]] = field(default_factory=list)
    blocked: list[dict[str, Any]] = field(default_factory=list)
    completed: list[dict[str, Any]] = field(default_factory=list)
    artifacts: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def new(cls, tasks: list[SearchTask]) -> "RunState":
        return cls(
            run_id=str(uuid.uuid4()),
            status="queued" if tasks else "empty",
            tasks=[
                {
                    "task_id": task.id,
                    "status": "queued",
                    "task": task.to_json(),
                    "artifact": None,
                }
                for task in tasks
            ],
        )

    @classmethod
    def from_json(cls, value: Any) -> "RunState":
        if not isinstance(value, dict):
            raise ValueError("run state must be a JSON object")
        run_id = value.get("run_id")
        status = value.get("status")
        if not isinstance(run_id, str) or not run_id:
            raise ValueError("run_id must be a non-empty string")
        if not isinstance(status, str) or not status:
            raise ValueError("run status must be a non-empty string")
        return cls(
            run_id=run_id,
            status=status,
            tasks=value.get("tasks", []) if isinstance(value.get("tasks", []), list) else [],
            blocked=value.get("blocked", []) if isinstance(value.get("blocked", []), list) else [],
            completed=value.get("completed", []) if isinstance(value.get("completed", []), list) else [],
            artifacts=value.get("artifacts", []) if isinstance(value.get("artifacts", []), list) else [],
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "tasks": self.tasks,
            "blocked": self.blocked,
            "completed": self.completed,
            "artifacts": self.artifacts,
        }


class RunStore:
    def __init__(self, directory: str | Path):
        self.directory = Path(directory)
        self.state_path = self.directory / "state.json"
        self.events_path = self.directory / "events.jsonl"
        self.artifacts_dir = self.directory / "artifacts"

    def create(self, tasks: list[SearchTask]) -> RunState:
        if self.state_path.exists():
            return self.load()
        state = RunState.new(tasks)
        self.save(state)
        self.append_event({"type": "run_created", "run_id": state.run_id, "task_count": len(tasks)})
        return state

    def load(self) -> RunState:
        return RunState.from_json(json.loads(self.state_path.read_text(encoding="utf-8")))

    def save(self, state: RunState) -> None:
        _atomic_json(self.state_path, state.to_json())

    def append_event(self, event: dict[str, Any]) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        with self.events_path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(event, sort_keys=True) + "\n")

    def record_task_started(self, state: RunState, task_id: str) -> None:
        state.status = "running"
        for item in state.tasks:
            if item.get("task_id") == task_id:
                item["status"] = "running"
        self.append_event({"type": "task_started", "task_id": task_id})
        self.save(state)

    def record_task_result(self, state: RunState, result: dict[str, Any]) -> Path:
        task_id = str(result.get("id", "unknown"))
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        artifact = self.artifacts_dir / f"{task_id}.json"
        _atomic_json(artifact, result)
        status = str(result.get("status", "unknown"))
        task_entry = {
            "task_id": task_id,
            "status": status,
            "artifact": str(artifact.relative_to(self.directory)),
        }
        for item in state.tasks:
            if item.get("task_id") == task_id:
                item.update(task_entry)
                break
        if status in {"verified", "approved"}:
            state.completed.append(task_entry)
        else:
            state.blocked.append(task_entry)
        state.artifacts.append({"kind": "search_result", **task_entry})
        if all(str(item.get("status")) not in {"queued", "running"} for item in state.tasks):
            state.status = "completed" if not state.blocked else "blocked"
        self.append_event({"type": "task_completed", **task_entry})
        self.save(state)
        return artifact

    def artifacts(self) -> list[Path]:
        if not self.artifacts_dir.exists():
            return []
        return sorted(self.artifacts_dir.glob("*.json"))
