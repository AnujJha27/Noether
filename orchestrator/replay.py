from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _load_json_value(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _event_lines(events: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for event in events:
        kind = event.get("type", "event")
        if kind == "supervisor_decision":
            lines.append(
                f"supervisor r{event.get('round')}: {event.get('action')} — {event.get('reason')}"
            )
        elif kind == "agent_turn_completed":
            lines.append(
                f"agent {event.get('agent')} r{event.get('round')} "
                f"{event.get('action')}: {event.get('status')} — {event.get('output_summary', '')}"
            )
        elif kind == "handoff_created":
            lines.append(
                f"handoff {event.get('id')}: {event.get('from_agent')} -> "
                f"{event.get('to_agent')} on {event.get('node_id')}"
            )
        elif kind == "handoff_receipt":
            verdict = "accepted" if event.get("accepted") else "refused"
            lines.append(
                f"handoff receipt {event.get('handoff_id')}: {event.get('receiver_agent')} "
                f"{verdict} — {event.get('receiver_summary')}"
            )
        elif kind == "verification_round":
            lines.append(
                f"verifier r{event.get('round')}: {event.get('status')} "
                f"for {event.get('attempt_count')} candidate(s)"
            )
        elif kind in {"decomposition_started", "decomposition_completed", "decomposition_failed"}:
            lines.append(f"{kind}: {event}")
    return lines


def replay_search_result(result: dict[str, Any]) -> str:
    lines = [
        f"REPLAY {result.get('id', 'unknown')} [{result.get('status', 'unknown')}]",
        f"model_calls={result.get('model_calls', 0)} unique_candidates={result.get('unique_candidates', 0)}",
        "",
        "SUPERVISOR / AGENT / VERIFIER TIMELINE",
    ]
    events = result.get("events", [])
    if isinstance(events, list):
        lines.extend(_event_lines([event for event in events if isinstance(event, dict)]))
    calls = result.get("model_call_records", [])
    if isinstance(calls, list) and calls:
        lines.extend(["", "MODEL CALLS"])
        for call in calls:
            if not isinstance(call, dict):
                continue
            prompt = " ".join(str(call.get("prompt", "")).split())
            if len(prompt) > 220:
                prompt = prompt[:217] + "..."
            response = call.get("response", call.get("error", ""))
            response_text = json.dumps(response, sort_keys=True)
            if len(response_text) > 220:
                response_text = response_text[:217] + "..."
            lines.append(
                f"#{call.get('call_index')} {call.get('agent')} "
                f"model={call.get('model')} [{call.get('status')}]"
            )
            lines.append(f"  prompt: {prompt}")
            lines.append(f"  response: {response_text}")
    lines.extend(["", "ATTEMPTS"])
    for attempt in result.get("attempts", []):
        if not isinstance(attempt, dict):
            continue
        diagnostics = " ".join(str(attempt.get("diagnostics", "")).split())
        if len(diagnostics) > 180:
            diagnostics = diagnostics[:177] + "..."
        lines.append(
            f"{attempt.get('id')} {attempt.get('agent')} r{attempt.get('round')} "
            f"[{attempt.get('status')}] {diagnostics}"
        )
    scorecard = result.get("agent_scorecard", {})
    if isinstance(scorecard, dict) and scorecard:
        lines.extend(["", "SCORECARD"])
        for agent, stats in scorecard.items():
            lines.append(f"{agent}: {stats}")
    winner = result.get("winner")
    if isinstance(winner, dict):
        lines.extend(["", f"WINNER {winner.get('id')}: {winner.get('patch')}"])
    return "\n".join(lines)


def replay_path(path: str | Path) -> str:
    root = Path(path)
    if root.is_file():
        value = _load_json_value(root)
        if isinstance(value, dict):
            return replay_search_result(value)
        if isinstance(value, list):
            return "\n\n".join(
                replay_search_result(item)
                for item in value
                if isinstance(item, dict)
            )
        raise ValueError(f"{root} must contain a search object or array of search objects")
    state = root / "state.json"
    if not state.exists():
        raise ValueError(f"{root} is neither a search JSON file nor a run directory")
    state_data = _load_json(state)
    lines = [
        f"RUN {state_data.get('run_id', 'unknown')} [{state_data.get('status', 'unknown')}]",
        "",
    ]
    events_path = root / "events.jsonl"
    if events_path.exists():
        lines.append("RUN EVENTS")
        for raw in events_path.read_text(encoding="utf-8").splitlines():
            if raw.strip():
                lines.append(raw)
        lines.append("")
    artifact_dir = root / "artifacts"
    for artifact in sorted(artifact_dir.glob("*.json")) if artifact_dir.exists() else []:
        lines.append(replay_search_result(_load_json(artifact)))
        lines.append("")
    return "\n".join(lines).rstrip()


def arguments(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Replay proof-search agent traces")
    parser.add_argument("path", help="search-result JSON file or durable run directory")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    options = arguments(argv)
    print(replay_path(options.path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
