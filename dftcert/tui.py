from __future__ import annotations

import argparse
import curses
import json
import textwrap
from pathlib import Path
from typing import Any

from .hypothesis import draft_hypothesis, policy_coverage
from .manifest import ArchitectureManifest
from .model_assessment import (
    apply_assumption_status,
    finalize_assumption_review,
)
from .policy import Policy
from .report import sanity_report


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY = ROOT / "policies/dft-architecture-v1.json"
DEFAULT_HYPOTHESIS = (
    "A DFT architecture with an XC derivative discontinuity, nonlocal spatial "
    "coupling, and a self-adjoint learned self-energy operator."
)
EXAMPLES = {
    "pass": (
        "A DFT architecture with an XC derivative discontinuity at an "
        "electron-number boundary, nonlocal spatial coupling, and a "
        "self-adjoint learned self-energy operator."
    ),
    "missing": (
        "The proposed model is nonlocal and uses message passing to propagate "
        "density information across sites, but it does not specify "
        "self-adjointness or the XC derivative discontinuity."
    ),
    "violation": (
        "The architecture has an XC derivative discontinuity and nonlocal "
        "coupling, but the learned self-energy operator is explicitly "
        "non-self-adjoint."
    ),
    "gap": (
        "The hypothesis proposes a rotationally equivariant DFT architecture "
        "with self-adjoint Fourier-space kernels and a long-range nonlocal "
        "receptive field."
    ),
}


def build_hypothesis_report(*, policy: Policy, model_id: str,
                            hypothesis: str) -> dict[str, Any]:
    manifest = draft_hypothesis(
        model_id=model_id, hypothesis=hypothesis, policy=policy
    )
    return {
        "status": "draft",
        "manifest": manifest.value,
        "report": sanity_report(manifest=manifest, policy=policy),
    }


def load_json_object(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def load_json_value(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_json_list(path: str | Path) -> list[dict[str, Any]]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise ValueError(f"{path} must contain a JSON array of objects")
    return value


def load_jsonl_objects(path: str | Path, *, limit: int | None = None) -> list[dict[str, Any]]:
    source = Path(path)
    if not source.exists():
        return []
    items: list[dict[str, Any]] = []
    for line in source.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            items.append(value)
    return items[-limit:] if limit is not None else items


def build_artifact_report(
    *,
    policy: Policy,
    manifest_path: str | Path,
    proof_results_path: str | Path | None = None,
    certificate_report_path: str | Path | None = None,
) -> dict[str, Any]:
    manifest = ArchitectureManifest.load(manifest_path)
    proof_results = load_json_list(proof_results_path) if proof_results_path else None
    certificate_report = (
        load_json_object(certificate_report_path)
        if certificate_report_path else None
    )
    return {
        "status": "artifact",
        "manifest": manifest.value,
        "proof_results": proof_results or [],
        "certificate_report": certificate_report,
        "report": sanity_report(
            manifest=manifest,
            policy=policy,
            proof_results=proof_results,
            certificate_report=certificate_report,
        ),
    }


def status_color(status: str) -> str:
    if status in {"consistent_with_policy", "approved", "verified"}:
        return "good"
    if status in {"violates_required_principle", "certificate_check_failed", "refuted", "rejected", "not_sound"}:
        return "bad"
    if status in {"formalization_gap"}:
        return "gap"
    if status in {
        "proof_required", "inconclusive_missing_assumption", "project_not_built",
        "needs_user_confirmation", "needs_clarification", "unknown", "inconclusive",
    }:
        return "warn"
    return "muted"


def label(value: Any) -> str:
    return str(value if value is not None else "unknown").replace("_", " ")


def wrap_lines(text: str, width: int, *, indent: str = "") -> list[str]:
    if width < 8:
        return [text[:width]]
    return textwrap.wrap(
        text, width=width, initial_indent=indent, subsequent_indent=indent
    ) or [indent]


def report_lines(data: dict[str, Any], width: int) -> list[tuple[str, str]]:
    report = data["report"]
    manifest = data.get("manifest", {})
    lines: list[tuple[str, str]] = []
    status = report["status"]
    lines.append((f"VERDICT  {label(status).upper()}", status_color(status)))
    for line in wrap_lines(report.get("summary", ""), width):
        lines.append((line, "muted"))
    lines.append(("", "muted"))
    lines.append(("PRINCIPLE CHECKS", "title"))
    for item in report.get("obligations", []):
        color = status_color(item["category"])
        lines.append((f"■ {item['fact']}  [{label(item['category'])}]", color))
        for line in wrap_lines(item["principle"], width - 2, indent="  "):
            lines.append((line, "muted"))
        claim = item.get("normalized_claim")
        claim_text = json.dumps(claim, sort_keys=True) if claim is not None else "No claim supplied"
        lines.append((f"  evidence: {item.get('evidence_kind') or 'missing'}", "muted"))
        lines.append((f"  lean: {item.get('lean_task_id') or 'not generated'}", "muted"))
        for line in wrap_lines(f"claim: {claim_text}", width - 2, indent="  "):
            lines.append((line, "muted"))
        for line in wrap_lines(f"reason: {item.get('reason', '')}", width - 2, indent="  "):
            lines.append((line, "muted"))
        lines.append(("", "muted"))
    questions = report.get("clarification_questions", [])
    if questions:
        lines.append(("CLARIFY BEFORE FORMALIZING", "title"))
        for item in questions:
            lines.append((f"? {item.get('fact', 'clarification')}", "warn"))
            for line in wrap_lines(item.get("question", ""), width - 2, indent="  "):
                lines.append((line, "muted"))
        lines.append(("", "muted"))
    issues = [
        item for item in report.get("assumptions", [])
        if item.get("status") in {"needs_clarification", "missing", "unresolved"}
        or item.get("source") == "missing"
    ]
    if issues:
        lines.append(("OPEN ISSUES", "title"))
        for item in issues:
            lines.append((f"! {item.get('id')}  [{label(item.get('status'))}]", "warn"))
            for line in wrap_lines(item.get("statement", ""), width - 2, indent="  "):
                lines.append((line, "muted"))
        lines.append(("", "muted"))
    lines.append(("TRACE", "title"))
    lines.append((f"manifest: {manifest.get('manifest_sha256', 'draft')}", "muted"))
    proof_results = data.get("proof_results") or []
    certificate_report = data.get("certificate_report")
    if proof_results:
        lines.append(("", "muted"))
        lines.append(("PROOF SEARCH ARTIFACTS", "title"))
        for item in proof_results:
            lines.append((
                f"■ {item.get('id', 'unknown')}  [{label(item.get('status'))}]",
                status_color(str(item.get("status"))),
            ))
            winner = item.get("winner")
            if isinstance(winner, dict) and winner.get("patch"):
                patch = " ".join(str(winner["patch"]).split())
                for line in wrap_lines(f"winner: {patch}", width - 2, indent="  "):
                    lines.append((line, "muted"))
    if certificate_report:
        lines.append(("", "muted"))
        lines.append(("CERTIFICATE CHECK", "title"))
        cert_status = certificate_report.get("status")
        lines.append((f"status: {label(cert_status)}", status_color(str(cert_status))))
        verification = certificate_report.get("certificate_verification", {})
        if isinstance(verification, dict):
            lines.append((
                f"lean check: {label(verification.get('status'))}",
                status_color(str(verification.get("status"))),
            ))
            if verification.get("elapsed_ms") is not None:
                lines.append((f"elapsed_ms: {verification['elapsed_ms']}", "muted"))
        if certificate_report.get("report_sha256"):
            lines.append((f"report: {certificate_report['report_sha256']}", "muted"))
    return lines


def _short_json(value: Any, width: int) -> str:
    text = json.dumps(value, sort_keys=True) if not isinstance(value, str) else value
    text = " ".join(text.split())
    return text if len(text) <= width else text[:max(0, width - 3)] + "..."


def event_summary(event: dict[str, Any]) -> tuple[str, str]:
    kind = str(event.get("type", "event"))
    when = str(event.get("time", ""))[11:19] if event.get("time") else "--:--:--"
    task = event.get("task_id") or event.get("task") or ""
    prefix = f"{when} {kind}"
    if task:
        prefix += f" {task}"
    color = "muted"
    detail = ""
    if kind == "model_call_started":
        color = "gap"
        detail = f"call={event.get('call_index')} agent={event.get('agent')} model={event.get('model')}"
    elif kind == "model_call_completed":
        color = "good"
        detail = f"call={event.get('call_index')} agent={event.get('agent')}"
    elif kind == "model_call_failed":
        color = "bad"
        detail = f"call={event.get('call_index')} agent={event.get('agent')} {event.get('message')}"
    elif kind == "round_started":
        color = "title"
        detail = (
            f"round={event.get('round')} frontier={event.get('frontier_width')} "
            f"model_calls={event.get('model_calls')} candidates={event.get('unique_candidates')}"
        )
    elif kind == "supervisor_decision":
        color = "warn" if event.get("action") == "stop" else "muted"
        detail = f"round={event.get('round')} action={event.get('action')} reason={event.get('reason')}"
    elif kind == "candidates_collected":
        detail = f"round={event.get('round')} count={event.get('candidate_count')}"
    elif kind == "verification_started":
        color = "gap"
        detail = f"round={event.get('round')} count={event.get('candidate_count')}"
    elif kind == "verification_completed":
        color = status_color(str(event.get("status")))
        detail = (
            f"round={event.get('round')} status={event.get('status')} "
            f"attempts={event.get('attempt_count')} winner={event.get('winner_id')}"
        )
    elif kind in {"task_started", "task_completed", "search_completed"}:
        color = status_color(str(event.get("status", "running")))
        detail = f"status={event.get('status', 'running')}"
    elif event.get("message"):
        color = "bad"
        detail = str(event.get("message"))
    text = f"{prefix}  {detail}".rstrip()
    return text, color


def event_summary_lines(event: dict[str, Any], width: int) -> list[tuple[str, str]]:
    text, color = event_summary(event)
    return [(line, color) for line in wrap_lines(text, width)]


def human_turn_summary(summary: Any) -> str:
    text = str(summary)
    if text.startswith("accepted ") and " candidate" in text:
        return "proposed " + text.removeprefix("accepted ")
    return text


def search_outcome(status: str, data: dict[str, Any]) -> str:
    if status == "verified":
        winner = data.get("winner")
        winner_id = winner.get("id") if isinstance(winner, dict) else data.get("winner_id")
        suffix = f"; winner={winner_id}" if winner_id else ""
        return "outcome: Lean verified a candidate proof" + suffix
    if status == "exhausted":
        calls = data.get("model_calls", 0)
        candidates = data.get("unique_candidates", 0)
        return f"outcome: no verified proof before search stopped; model_calls={calls}, candidates={candidates}"
    if status == "project_not_built":
        return "outcome: verifier infrastructure is missing compiled Lean modules"
    return f"outcome: {label(status)}"


def search_result_lines(data: dict[str, Any], width: int) -> list[tuple[str, str]]:
    lines: list[tuple[str, str]] = []
    status = str(data.get("status", "unknown"))
    lines.append((f"SEARCH  {data.get('id', 'unknown')}  [{label(status)}]", status_color(status)))
    lines.append((search_outcome(status, data), status_color(status)))
    lines.append((
        f"model_calls={data.get('model_calls', 0)}  "
        f"unique_candidates={data.get('unique_candidates', 0)}  "
        f"rounds={data.get('rounds_used', 0)}",
        "muted",
    ))
    task = data.get("task", {})
    if isinstance(task, dict):
        lines.append((f"target: {task.get('target') or '(generated obligation)'}", "muted"))
        for line in wrap_lines(f"theorem: {task.get('theorem', '')}", width, indent=""):
            lines.append((line, "muted"))
        subgoals = task.get("subgoals", [])
        if isinstance(subgoals, list) and subgoals:
            lines.append(("", "muted"))
            lines.append(("PROOF GRAPH / SUBGOAL DAG", "title"))
            for item in subgoals:
                if isinstance(item, dict):
                    deps = ", ".join(item.get("depends_on", [])) if isinstance(item.get("depends_on"), list) else ""
                    lines.append((f"◆ {item.get('id')}  deps=[{deps}]", "gap"))
                    for line in wrap_lines(str(item.get("theorem", "")), width - 2, indent="  "):
                        lines.append((line, "muted"))
    lines.append(("", "muted"))
    lines.append(("SUPERVISOR DECISIONS", "title"))
    for decision in data.get("supervisor_decisions", []):
        if isinstance(decision, dict):
            lines.append((
                f"■ r{decision.get('round')} {decision.get('action')} — {decision.get('reason')}",
                "warn" if decision.get("action") == "stop" else "good",
            ))
            lines.append((f"  assignments: {_short_json(decision.get('assignments', {}), width - 2)}", "muted"))
    lines.append(("", "muted"))
    lines.append(("AGENT TURNS", "title"))
    for turn in data.get("agent_turns", []):
        if isinstance(turn, dict):
            lines.append((
                f"■ {turn.get('agent')} r{turn.get('round')} {turn.get('action')} [{label(turn.get('status'))}]",
                status_color(str(turn.get("status"))),
            ))
            if turn.get("received_handoff_id"):
                lines.append((f"  routed input: {turn['received_handoff_id']}", "gap"))
            for line in wrap_lines(human_turn_summary(turn.get("output_summary", "")), width - 2, indent="  "):
                lines.append((line, "muted"))
    handoffs = data.get("handoffs", [])
    receipts = data.get("handoff_receipts", [])
    if handoffs or receipts:
        lines.append(("", "muted"))
        lines.append(("ROUTING HANDOFFS", "title"))
        lines.append(("These are advisory candidate routes between agents, not Lean proof verdicts.", "muted"))
        for item in handoffs:
            if isinstance(item, dict):
                state = "used later" if item.get("accepted") else "offered"
                lines.append((
                    f"↳ {item.get('id')} {item.get('from_agent')} -> {item.get('to_agent')} "
                    f"node={item.get('node_id')} [{state}]",
                    "gap",
                ))
        for item in receipts:
            if isinstance(item, dict):
                used = bool(item.get("accepted"))
                color = "good" if used else "muted"
                state = "used routed candidate" if used else "did not use routed candidate"
                lines.append((
                    f"→ {item.get('handoff_id')} receiver={item.get('receiver_agent')} [{state}]",
                    color,
                ))
                for line in wrap_lines(str(item.get("receiver_summary", "")), width - 2, indent="  "):
                    lines.append((line, "muted"))
    scorecard = data.get("agent_scorecard", {})
    if isinstance(scorecard, dict) and scorecard:
        lines.append(("", "muted"))
        lines.append(("SCORECARD", "title"))
        for agent, stats in scorecard.items():
            lines.append((f"■ {agent}: {_short_json(stats, width - len(agent) - 4)}", "muted"))
    attempts = data.get("attempts", [])
    if attempts:
        lines.append(("", "muted"))
        lines.append(("LEAN DIAGNOSTICS", "title"))
        for attempt in attempts:
            if isinstance(attempt, dict):
                color = status_color(str(attempt.get("status")))
                lines.append((
                    f"■ {attempt.get('id')} [{label(attempt.get('status'))}]",
                    color,
                ))
                if attempt.get("status") == "project_not_built":
                    lines.append(("  infrastructure issue: build the Lean project before running proof search", "warn"))
                diagnostics = str(attempt.get("diagnostics", "")) or "(none)"
                for line in wrap_lines(diagnostics, width - 2, indent="  "):
                    lines.append((line, "muted"))
    certificate = data.get("certificate_report")
    if isinstance(certificate, dict):
        lines.append(("", "muted"))
        lines.append(("CERTIFICATE STATUS", "title"))
        cert_status = str(certificate.get("status", "unknown"))
        lines.append((f"status: {label(cert_status)}", status_color(cert_status)))
    return lines


def assessment_lines(data: dict[str, Any], width: int) -> list[tuple[str, str]]:
    lines: list[tuple[str, str]] = []
    verdict = str(data.get("verdict", "inconclusive"))
    color = {
        "physically_sound": "good",
        "not_sound": "bad",
        "inconclusive": "warn",
    }.get(verdict, "muted")
    lines.append((f"VERDICT  {label(verdict).upper()}", color))
    for line in wrap_lines(str(data.get("summary", "")), width):
        lines.append((line, "muted"))
    lines.append(("", "muted"))
    lines.append(("ASSUMPTIONS", "title"))
    assumptions = data.get("assumptions", [])
    if isinstance(assumptions, list) and assumptions:
        for item in assumptions:
            if not isinstance(item, dict):
                continue
            status = str(item.get("status", "unknown"))
            lines.append((f"■ {item.get('id', 'assumption')}  [{label(status)}]", status_color(status)))
            evidence = str(item.get("evidence", "")).strip()
            if evidence:
                for line in wrap_lines(f"evidence: {evidence}", width - 2, indent="  "):
                    lines.append((line, "muted"))
            value = item.get("value")
            if value is not None:
                for line in wrap_lines(f"value: {_short_json(value, width - 9)}", width - 2, indent="  "):
                    lines.append((line, "muted"))
            question = str(item.get("question") or "").strip()
            if question:
                for line in wrap_lines(f"clarify: {question}", width - 2, indent="  "):
                    lines.append((line, "warn"))
            review = item.get("proof_review")
            if isinstance(review, dict):
                assessment = str(review.get("assessment", "insufficient"))
                lines.append((f"  rationale review: {label(assessment)} (not Lean-verified)", "warn"))
                rationale = str(review.get("review", "")).strip()
                if rationale:
                    for line in wrap_lines(rationale, width - 4, indent="    "):
                        lines.append((line, "muted"))
    else:
        lines.append(("No assumptions extracted yet.", "muted"))
    lines.append(("", "muted"))
    lines.append(("VERDICT EVIDENCE", "title"))
    checks = data.get("checks", [])
    if isinstance(checks, list) and checks:
        for item in checks:
            if not isinstance(item, dict):
                continue
            status = str(item.get("status", "unknown"))
            lines.append((f"◆ {item.get('id', 'check')}  [{label(status)}]", status_color(status)))
            for line in wrap_lines(str(item.get("reason", "")), width - 2, indent="  "):
                lines.append((line, "muted"))
    else:
        lines.append(("No formal checks have been mapped yet.", "muted"))
    lines.append(("", "muted"))
    lines.append(("NEXT ACTION", "title"))
    for action in data.get("next_actions", []) or ["Open proof details when you need to audit the decision."]:
        for line in wrap_lines(f"■ {action}", width):
            lines.append((line, "warn"))
    lines.append(("", "muted"))
    lines.append(("SYSTEM DIAGNOSTICS", "title"))
    lines.append((f"assessment: {data.get('assessment_sha256', 'draft')}", "muted"))
    artifacts = data.get("artifacts", {})
    if isinstance(artifacts, dict):
        for name, path in artifacts.items():
            lines.append((f"{name}: {path}", "muted"))
    return lines


def run_inspector_lines(data: dict[str, Any], width: int) -> list[tuple[str, str]]:
    state = data.get("state", {})
    artifacts = [item for item in data.get("artifacts", []) if isinstance(item, dict)]
    lines: list[tuple[str, str]] = []
    status = str(state.get("status", "unknown")) if isinstance(state, dict) else "unknown"
    lines.append((f"RUN  {state.get('run_id', 'unknown') if isinstance(state, dict) else 'unknown'}  [{label(status)}]", status_color(status)))
    if isinstance(state, dict):
        lines.append(("", "muted"))
        lines.append(("TASK QUEUE", "title"))
        for item in state.get("tasks", []):
            if isinstance(item, dict):
                lines.append((
                    f"■ {item.get('task_id')} [{label(item.get('status'))}] artifact={item.get('artifact')}",
                    status_color(str(item.get("status"))),
                ))
        if state.get("blocked"):
            lines.append(("", "muted"))
            lines.append(("BLOCKED", "warn"))
            for item in state.get("blocked", []):
                if isinstance(item, dict):
                    lines.append((f"! {item.get('task_id')} [{label(item.get('status'))}]", "warn"))
        if state.get("completed"):
            lines.append(("", "muted"))
            lines.append(("COMPLETED", "good"))
            for item in state.get("completed", []):
                if isinstance(item, dict):
                    lines.append((f"✓ {item.get('task_id')} [{label(item.get('status'))}]", "good"))
    events = data.get("events", [])
    if isinstance(events, list) and events:
        lines.append(("", "muted"))
        lines.append(("RECENT ACTIVITY", "title"))
        for event in events[-18:]:
            if isinstance(event, dict):
                lines.extend(event_summary_lines(event, width))
    lines.append(("", "muted"))
    if artifacts:
        selected = data.get("selected_artifact_index", len(artifacts) - 1)
        if not isinstance(selected, int):
            selected = len(artifacts) - 1
        selected = max(0, min(selected, len(artifacts) - 1))
        artifact = artifacts[selected]
        lines.append((f"PAST TASK  {selected + 1}/{len(artifacts)}  ([/] cycle)", "title"))
        lines.extend(search_result_lines(artifact, width))
    else:
        lines.append(("PAST TASKS", "title"))
        lines.append(("No completed task artifacts yet.", "muted"))
    return lines


def coverage_lines(data: dict[str, Any], width: int) -> list[tuple[str, str]]:
    lines: list[tuple[str, str]] = [
        (f"POLICY  {data['policy']['id']} v{data['policy']['version']}", "title"),
        (f"Lean library: {data['project']['lean_library']}", "muted"),
        (f"Toolchain: {data['project']['toolchain']}", "muted"),
        ("", "muted"),
        ("SUPPORTED CHECKS", "title"),
    ]
    for item in data["supported_claims"]:
        lines.append((f"■ {item['fact']}", "good"))
        for line in wrap_lines(item["description"], width - 2, indent="  "):
            lines.append((line, "muted"))
    lines.append(("", "muted"))
    lines.append(("FORMALIZATION PROFILES", "title"))
    for item in data["formalization_profiles"]:
        lines.append((f"◆ {item['id']}", "gap"))
        lines.append((f"  module: {item['module']}", "muted"))
        lines.append((f"  facts: {', '.join(item['facts'])}", "muted"))
    return lines


def confirm_assumptions_tui(manifest: ArchitectureManifest, policy: Policy) -> None:
    assumptions = [
        item for item in manifest.value.get("assumptions", [])
        if isinstance(item, dict)
    ]
    if not assumptions:
        finalize_assumption_review(manifest, policy)
        return

    index = 0
    message = "y accept · n reject · u unknown · ↑/↓ move · Enter finish · q cancel"

    def attr(name: str) -> int:
        pairs = {"muted": 1, "title": 2, "good": 3, "warn": 4, "bad": 5, "gap": 6}
        return curses.color_pair(pairs.get(name, 1)) if curses.has_colors() else 0

    def init_colors() -> None:
        if not curses.has_colors():
            return
        curses.start_color()
        curses.use_default_colors()
        palette = {
            "muted": curses.COLOR_WHITE,
            "title": curses.COLOR_RED,
            "good": curses.COLOR_GREEN,
            "warn": curses.COLOR_YELLOW,
            "bad": curses.COLOR_RED,
            "gap": curses.COLOR_MAGENTA,
        }
        for pair_index, name in enumerate(palette, start=1):
            curses.init_pair(pair_index, palette[name], -1)

    def draw_box(screen: Any, y: int, x: int, h: int, w: int, title: str) -> None:
        if h < 2 or w < 2:
            return
        screen.attron(attr("title"))
        screen.addstr(y, x, "┌" + "─" * (w - 2) + "┐")
        for row in range(y + 1, y + h - 1):
            screen.addstr(row, x, "│")
            screen.addstr(row, x + w - 1, "│")
        screen.addstr(y + h - 1, x, "└" + "─" * (w - 2) + "┘")
        screen.addstr(y, x + 2, f" {title} "[:max(0, w - 4)])
        screen.attroff(attr("title"))

    def row_status(item: dict[str, Any]) -> str:
        return str(item.get("status", "needs_user_confirmation"))

    def draw(screen: Any) -> None:
        screen.erase()
        height, width = screen.getmaxyx()
        if height < 20 or width < 78:
            screen.addstr(0, 0, "terminal too small; use at least 78x20")
            screen.refresh()
            return
        left_w = max(32, min(48, width // 3))
        right_x = left_w + 2
        right_w = width - left_w - 3
        screen.addstr(0, 2, "† NOETHER ASSUMPTION REVIEW", attr("title") | curses.A_BOLD)
        screen.addstr(0, 32, message[:max(0, width - 34)], attr("muted"))

        draw_box(screen, 2, 1, height - 3, left_w, "extracted assumptions")
        for row, item in enumerate(assumptions[:height - 7]):
            selected = row == index
            status = row_status(item)
            marker = "›" if selected else " "
            color = status_color(status)
            text = f"{marker} {item.get('id', 'assumption')} [{label(status)}]"
            screen.addstr(4 + row, 3, text[:left_w - 4], attr(color) | (curses.A_REVERSE if selected else 0))

        current = assumptions[index]
        status = row_status(current)
        draw_box(screen, 2, right_x, height - 3, right_w, "decision")
        y = 4
        screen.addstr(y, right_x + 2, f"{current.get('id', 'assumption')}  [{label(status)}]",
                      attr(status_color(status)) | curses.A_BOLD)
        y += 2
        statement = str(current.get("statement") or current.get("principle") or "")
        for line in wrap_lines(statement, right_w - 4):
            if y >= height - 9:
                break
            screen.addstr(y, right_x + 2, line[:right_w - 4], attr("muted"))
            y += 1
        y += 1
        value = current.get("value")
        if value is None:
            screen.addstr(y, right_x + 2, "value: missing from model text", attr("warn"))
            y += 1
        else:
            for line in wrap_lines(f"value: {_short_json(value, right_w - 11)}", right_w - 4):
                if y >= height - 7:
                    break
                screen.addstr(y, right_x + 2, line[:right_w - 4], attr("muted"))
                y += 1
        evidence = str(current.get("evidence") or current.get("rationale") or "").strip()
        if evidence and y < height - 7:
            y += 1
            for line in wrap_lines(f"evidence: {evidence}", right_w - 4):
                if y >= height - 7:
                    break
                screen.addstr(y, right_x + 2, line[:right_w - 4], attr("muted"))
                y += 1
        question = str(current.get("question") or "").strip()
        if question and y < height - 7:
            y += 1
            for line in wrap_lines(f"question: {question}", right_w - 4):
                if y >= height - 7:
                    break
                screen.addstr(y, right_x + 2, line[:right_w - 4], attr("warn"))
                y += 1

        reviewed = sum(
            1 for item in assumptions
            if row_status(item) in {"confirmed", "rejected", "unknown"}
        )
        footer = f"reviewed {reviewed}/{len(assumptions)} · Enter writes assessment when all are reviewed"
        screen.addstr(height - 4, right_x + 2, footer[:right_w - 4], attr("title"))
        screen.refresh()

    def main(screen: Any) -> None:
        nonlocal index, message
        try:
            curses.curs_set(0)
        except curses.error:
            pass
        screen.keypad(True)
        init_colors()
        while True:
            draw(screen)
            try:
                key = screen.get_wch()
            except curses.error:
                continue
            if key in ("q", "Q", "\x1b", "\x11"):
                raise KeyboardInterrupt("assumption review cancelled")
            if key in (curses.KEY_DOWN, "j"):
                index = min(len(assumptions) - 1, index + 1)
                continue
            if key in (curses.KEY_UP, "k"):
                index = max(0, index - 1)
                continue
            if key in ("y", "Y"):
                apply_assumption_status(
                    manifest, fact_id=str(assumptions[index].get("id")), status="confirmed"
                )
                index = min(len(assumptions) - 1, index + 1)
                continue
            if key in ("n", "N"):
                apply_assumption_status(
                    manifest, fact_id=str(assumptions[index].get("id")), status="rejected"
                )
                index = min(len(assumptions) - 1, index + 1)
                continue
            if key in ("u", "U"):
                apply_assumption_status(
                    manifest, fact_id=str(assumptions[index].get("id")), status="unknown"
                )
                index = min(len(assumptions) - 1, index + 1)
                continue
            if key in ("\n", "\r"):
                pending = [
                    item.get("id", "assumption")
                    for item in assumptions
                    if row_status(item) not in {"confirmed", "rejected", "unknown"}
                ]
                if pending:
                    message = f"still needs decision: {pending[0]}"
                    continue
                finalize_assumption_review(manifest, policy)
                return

    curses.wrapper(main)


def render_plain(data: dict[str, Any], *, coverage: bool = False,
                 width: int = 100) -> str:
    if data.get("inspector_kind") == "assessment":
        source = assessment_lines(data["assessment"], width)
    elif data.get("inspector_kind") == "search_result":
        source = search_result_lines(data["result"], width)
    elif data.get("inspector_kind") == "run":
        source = run_inspector_lines(data, width)
    else:
        source = coverage_lines(data, width) if coverage else report_lines(data, width)
    return "\n".join(text for text, _ in source)


class TuiApp:
    def __init__(self, *, policy: Policy, model_id: str, hypothesis: str,
                 mode: str = "report", data: dict[str, Any] | None = None,
                 refresh_path: str | Path | None = None):
        self.policy = policy
        self.model_id = model_id
        self.hypothesis = hypothesis
        self.example_names = list(EXAMPLES)
        self.example_index = 0
        self.mode = mode
        self.scroll = 0
        self.left_scroll = 0
        self.current_scroll = 0
        self.prompt_scroll = 0
        self.log_scroll = 0
        self.focus = "past"
        self.artifact_index: int | None = None
        self.refresh_path = Path(refresh_path) if refresh_path is not None else None
        self.message = "F5 run · F2 coverage · F3 example · Ctrl-U clear · q/Esc quit"
        self.data: dict[str, Any] = data or build_hypothesis_report(
            policy=policy, model_id=model_id, hypothesis=hypothesis
        )

    def run(self) -> None:
        curses.wrapper(self._main)

    def _main(self, screen: Any) -> None:
        try:
            curses.curs_set(1)
        except curses.error:
            pass
        screen.keypad(True)
        try:
            curses.mousemask(curses.ALL_MOUSE_EVENTS)
        except curses.error:
            pass
        screen.timeout(1000 if self.refresh_path is not None else -1)
        self._colors()
        while True:
            self._refresh_if_needed()
            self._draw(screen)
            try:
                key = screen.get_wch()
            except curses.error:
                continue
            if key == curses.KEY_MOUSE and self.mode == "inspector":
                self._handle_mouse(screen)
                continue
            if key in ("\x11", "\x1b", "q", "Q"):  # Ctrl-Q / Esc / q
                return
            if key == "\t" and self.mode == "inspector":
                self._next_focus()
                self.message = f"{self.focus} pane focused · arrows scroll · q/Esc quit"
                continue
            if key in ("[", curses.KEY_LEFT) and self.mode == "inspector":
                self._cycle_artifact(-1)
                continue
            if key in ("]", curses.KEY_RIGHT) and self.mode == "inspector":
                self._cycle_artifact(1)
                continue
            if key == "\x15":  # Ctrl-U
                self.hypothesis = ""
                self.message = "cleared hypothesis"
                continue
            if key in (curses.KEY_F5, "\x12"):  # F5 / Ctrl-R
                self._run_report()
                continue
            if key == curses.KEY_F2:
                self.mode = "coverage"
                self.data = policy_coverage(self.policy)
                self.scroll = 0
                self.focus = "past"
                self.message = "coverage loaded"
                continue
            if key == curses.KEY_F3:
                self._load_next_example()
                continue
            if key == curses.KEY_DOWN:
                self._scroll_focused(1)
                continue
            if key == curses.KEY_UP:
                self._scroll_focused(-1)
                continue
            if key in (curses.KEY_NPAGE,):
                self._scroll_focused(8)
                continue
            if key in (curses.KEY_PPAGE,):
                self._scroll_focused(-8)
                continue
            if key in ("\b", "\x7f", curses.KEY_BACKSPACE):
                self.hypothesis = self.hypothesis[:-1]
                continue
            if key in ("\n", "\r"):
                self.hypothesis += "\n"
                continue
            if isinstance(key, str) and key.isprintable():
                self.hypothesis += key

    def _refresh_if_needed(self) -> None:
        if self.refresh_path is None:
            return
        try:
            self.data = build_run_inspector(self.refresh_path)
            self.message = "live run inspector · Tab focus · mouse/arrows scroll · q/Esc quit"
        except Exception as error:
            self.message = f"{type(error).__name__}: {error}"

    def _scroll_focused(self, delta: int) -> None:
        if self.mode == "inspector":
            if self.focus in {"left", "past"}:
                self.left_scroll = max(0, self.left_scroll + delta)
                return
            if self.focus == "current":
                self.current_scroll = max(0, self.current_scroll + delta)
                return
            if self.focus == "prompt":
                self.prompt_scroll = max(0, self.prompt_scroll + delta)
                return
            if self.focus == "logs":
                self.log_scroll = max(0, self.log_scroll + delta)
                return
        self.scroll = max(0, self.scroll + delta)

    def _next_focus(self) -> None:
        if self.mode == "inspector" and self.data.get("inspector_kind") == "run":
            order = ["past", "current", "prompt", "logs"]
        else:
            order = ["left", "right"]
        try:
            index = order.index(self.focus)
        except ValueError:
            index = 0
        self.focus = order[(index + 1) % len(order)]

    def _cycle_artifact(self, delta: int) -> None:
        artifacts = self.data.get("artifacts", [])
        if not isinstance(artifacts, list) or not artifacts:
            self.message = "no past task artifacts yet"
            return
        current = self._selected_artifact_index(len(artifacts))
        self.artifact_index = (current + delta) % len(artifacts)
        self.left_scroll = 0
        self.focus = "past"
        self.message = (
                f"past task {self.artifact_index + 1}/{len(artifacts)} selected · "
            "[] cycle · Tab focus · mouse/arrows scroll · q/Esc quit"
        )

    def _selected_artifact_index(self, count: int) -> int:
        if count <= 0:
            return 0
        if self.artifact_index is None:
            return count - 1
        self.artifact_index = max(0, min(self.artifact_index, count - 1))
        return self.artifact_index

    def _handle_mouse(self, screen: Any) -> None:
        try:
            _, x, y, _, state = curses.getmouse()
        except curses.error:
            return
        self.focus = self._focus_at(y, x, *screen.getmaxyx())
        wheel_up = getattr(curses, "BUTTON4_PRESSED", 0)
        wheel_down = getattr(curses, "BUTTON5_PRESSED", 0)
        if wheel_up and state & wheel_up:
            self._scroll_focused(-3)
        elif wheel_down and state & wheel_down:
            self._scroll_focused(3)
        self.message = f"{self.focus} pane focused · mouse/arrows scroll · q/Esc quit"

    def _focus_at(self, y: int, x: int, height: int, width: int) -> str:
        if (
            self.data.get("inspector_kind") == "run"
            and height >= 24
            and width >= 100
        ):
            left_w = max(38, min(66, width // 3))
            if x <= left_w:
                return "past"
            right_x = left_w + 2
            content_h = height - 3
            current_h = max(8, content_h // 2)
            bottom_y = 2 + current_h + 1
            if y < bottom_y:
                return "current"
            right_w = width - left_w - 3
            prompt_w = max(34, right_w // 2)
            return "prompt" if x < right_x + prompt_w + 1 else "logs"
        left_w = max(34, min(58, width // 3))
        return "left" if x <= left_w else "right"

    def _colors(self) -> None:
        if not curses.has_colors():
            return
        curses.start_color()
        curses.use_default_colors()
        palette = {
            "muted": curses.COLOR_WHITE,
            "title": curses.COLOR_RED,
            "good": curses.COLOR_GREEN,
            "warn": curses.COLOR_YELLOW,
            "bad": curses.COLOR_RED,
            "gap": curses.COLOR_MAGENTA,
        }
        for index, name in enumerate(palette, start=1):
            curses.init_pair(index, palette[name], -1)

    def _attr(self, name: str) -> int:
        pairs = {"muted": 1, "title": 2, "good": 3, "warn": 4, "bad": 5, "gap": 6}
        return curses.color_pair(pairs.get(name, 1)) if curses.has_colors() else 0

    def _run_report(self) -> None:
        try:
            self.data = build_hypothesis_report(
                policy=self.policy, model_id=self.model_id,
                hypothesis=self.hypothesis,
            )
            self.mode = "report"
            self.scroll = 0
            self.message = "draft report generated"
        except Exception as error:
            self.message = f"{type(error).__name__}: {error}"

    def _load_next_example(self) -> None:
        name = self.example_names[self.example_index % len(self.example_names)]
        self.example_index += 1
        self.model_id = f"example-{name}"
        self.hypothesis = EXAMPLES[name]
        self._run_report()
        self.message = f"loaded example: {name}"

    def _box(self, screen: Any, y: int, x: int, h: int, w: int,
             title: str = "") -> None:
        if h < 2 or w < 2:
            return
        screen.attron(self._attr("title"))
        screen.addstr(y, x, "┌" + "─" * (w - 2) + "┐")
        for row in range(y + 1, y + h - 1):
            screen.addstr(row, x, "│")
            screen.addstr(row, x + w - 1, "│")
        screen.addstr(y + h - 1, x, "└" + "─" * (w - 2) + "┘")
        if title:
            screen.addstr(y, x + 2, f" {title} "[:max(0, w - 4)])
        screen.attroff(self._attr("title"))

    def _draw_wrapped(self, screen: Any, y: int, x: int, width: int,
                      height: int, text: str, attr: int = 0,
                      scroll: int = 0) -> int:
        lines: list[str] = []
        for paragraph in text.splitlines() or [""]:
            lines.extend(wrap_lines(paragraph, width))
        visible = lines[scroll:scroll + height]
        for row, line in enumerate(visible):
            screen.addstr(y + row, x, line[:width], attr)
        return len(lines)

    def _draw_lines(self, screen: Any, y: int, x: int, width: int,
                    height: int, lines: list[tuple[str, str]],
                    scroll: int = 0) -> int:
        visible = lines[scroll:scroll + height]
        for row, (text, color) in enumerate(visible):
            screen.addstr(y + row, x, text[:width], self._attr(color))
        return len(lines)

    def _focused_title(self, title: str, focus: str) -> str:
        return f"{title} [focused]" if self.focus == focus else title

    def _running_task(self) -> dict[str, Any] | None:
        state = self.data.get("state", {})
        if not isinstance(state, dict):
            return None
        for item in state.get("tasks", []):
            if isinstance(item, dict) and item.get("status") == "running":
                return item
        return None

    def _run_overview_lines(self, width: int) -> list[tuple[str, str]]:
        state = self.data.get("state", {})
        artifacts = [item for item in self.data.get("artifacts", []) if isinstance(item, dict)]
        lines: list[tuple[str, str]] = []
        if isinstance(state, dict):
            status = str(state.get("status", "unknown"))
            lines.append((f"RUN  {state.get('run_id', 'unknown')}", status_color(status)))
            lines.append((f"status: {label(status)}", status_color(status)))
            lines.append(("", "muted"))
            lines.append(("TASKS", "title"))
            for item in state.get("tasks", []):
                if isinstance(item, dict):
                    lines.append((
                        f"■ {item.get('task_id')} [{label(item.get('status'))}]",
                        status_color(str(item.get("status"))),
                    ))
            if state.get("blocked"):
                lines.append(("", "muted"))
                lines.append(("BLOCKED", "warn"))
                for item in state.get("blocked", []):
                    if isinstance(item, dict):
                        lines.append((f"! {item.get('task_id')} [{label(item.get('status'))}]", "warn"))
        lines.append(("", "muted"))
        if artifacts:
            selected = self._selected_artifact_index(len(artifacts))
            self.data["selected_artifact_index"] = selected
            lines.append((f"PAST TASK  {selected + 1}/{len(artifacts)}  ([/] cycle)", "title"))
            lines.extend(search_result_lines(artifacts[selected], width))
        else:
            lines.append(("PAST TASKS", "title"))
            lines.append(("No completed task artifacts yet.", "muted"))
        return lines

    def _current_task_lines(self, width: int) -> list[tuple[str, str]]:
        running = self._running_task()
        if not running:
            return [("No task is currently running.", "muted")]
        lines: list[tuple[str, str]] = []
        task = running.get("task", {})
        lines.append((f"TASK  {running.get('task_id', 'unknown')}  [{label(running.get('status'))}]", "title"))
        if isinstance(task, dict):
            lines.append((f"target: {task.get('target') or '(generated obligation)'}", "muted"))
            for line in wrap_lines(f"theorem: {task.get('theorem', '')}", width, indent=""):
                lines.append((line, "muted"))
            context = str(task.get("context", "")).strip()
            if context:
                lines.append(("", "muted"))
                lines.append(("CONTEXT", "title"))
                for line in wrap_lines(context, width, indent=""):
                    lines.append((line, "muted"))
            subgoals = task.get("subgoals", [])
            if isinstance(subgoals, list) and subgoals:
                lines.append(("", "muted"))
                lines.append(("SUBGOALS", "title"))
                for item in subgoals:
                    if isinstance(item, dict):
                        lines.append((f"◆ {item.get('id')}", "gap"))
                        for line in wrap_lines(str(item.get("context", "")), width - 2, indent="  "):
                            lines.append((line, "muted"))
        return lines

    def _recent_activity_lines(self, width: int) -> list[tuple[str, str]]:
        events = self.data.get("events", [])
        lines: list[tuple[str, str]] = []
        if isinstance(events, list) and events:
            for event in events[-28:]:
                if isinstance(event, dict):
                    lines.extend(event_summary_lines(event, width))
        else:
            lines.append(("No events yet.", "muted"))
        return lines

    def _run_prompt_text(self) -> str:
        events = self.data.get("events", [])
        if isinstance(events, list):
            for event in reversed(events):
                if not isinstance(event, dict):
                    continue
                if event.get("type") == "model_call_started" and event.get("prompt"):
                    header = (
                        f"agent: {event.get('agent', 'unknown')}\n"
                        f"model: {event.get('model', 'default')}\n"
                        f"call: {event.get('call_index', '?')}\n\n"
                    )
                    system = str(event.get("system", "")).strip()
                    prompt = str(event.get("prompt", "")).strip()
                    if system:
                        return header + "SYSTEM\n" + system + "\n\nPROMPT\n" + prompt
                    return header + prompt
        state = self.data.get("state", {})
        if isinstance(state, dict):
            for item in state.get("tasks", []):
                if not isinstance(item, dict) or item.get("status") != "running":
                    continue
                task = item.get("task", {})
                if isinstance(task, dict):
                    return (
                        f"task: {item.get('task_id', 'unknown')}\n"
                        f"target: {task.get('target') or '(generated obligation)'}\n\n"
                        f"THEOREM\n{task.get('theorem', '')}\n\n"
                        f"CONTEXT\n{task.get('context') or '(none supplied)'}"
                    )
        return "Waiting for the next model prompt."

    def _left_pane(self) -> tuple[str, str, str]:
        if self.mode == "inspector" and self.data.get("inspector_kind") == "run":
            state = self.data.get("state", {})
            running = ""
            if isinstance(state, dict):
                for item in state.get("tasks", []):
                    if isinstance(item, dict) and item.get("status") == "running":
                        running = str(item.get("task_id", "running task"))
                        break
            return (
                f"current task: {running}" if running else "current task",
                self._run_prompt_text(),
                "Tab focus · mouse/arrows scroll · q/Esc quit",
            )
        if self.mode == "inspector" and self.data.get("inspector_kind") == "assessment":
            manifest = self.data.get("manifest", {})
            source = manifest.get("source", {}) if isinstance(manifest, dict) else {}
            description = source.get("description", "") if isinstance(source, dict) else ""
            return (
                "architecture description",
                str(description) or "description unavailable",
                "LLM assessment is review-only · q/Esc quit",
            )
        return (
            "hypothesis",
            self.hypothesis,
            "type to edit · F5 run · F3 examples",
        )

    def _draw(self, screen: Any) -> None:
        screen.erase()
        height, width = screen.getmaxyx()
        if height < 18 or width < 72:
            screen.addstr(0, 0, "terminal too small; use at least 72x18")
            screen.refresh()
            return
        if (
            self.mode == "inspector"
            and self.data.get("inspector_kind") == "run"
            and height >= 24
            and width >= 100
        ):
            self._draw_run_dashboard(screen, height, width)
            return
        left_w = max(34, min(58, width // 3))
        right_w = width - left_w - 3
        screen.addstr(0, 2, "† PROOF VIBE", self._attr("title") | curses.A_BOLD)
        screen.addstr(0, 18, self.message[:width - 20], self._attr("muted"))

        left_title, left_text, left_footer = self._left_pane()
        if self.mode == "inspector" and self.focus == "left":
            left_title += " [focused]"
        self._box(screen, 2, 1, height - 3, left_w, left_title)
        left_height = height - 10
        left_scroll = self.left_scroll if self.mode == "inspector" else 0
        left_total = self._draw_wrapped(
            screen, 4, 3, left_w - 4, height - 10, left_text,
            self._attr("muted"), left_scroll,
        )
        self.left_scroll = min(self.left_scroll, max(0, left_total - left_height))
        screen.addstr(height - 5, 3, left_footer[:left_w - 4], self._attr("title"))
        screen.addstr(height - 4, 3, f"id: {self.model_id}"[:left_w - 4], self._attr("muted"))
        if self.left_scroll:
            screen.addstr(height - 6, 3, f"↑ prompt scrolled {self.left_scroll}"[:left_w - 4],
                          self._attr("warn"))

        title = (
            "coverage" if self.mode == "coverage"
            else "artifact report" if self.mode == "artifact"
            else "model assessment" if self.data.get("inspector_kind") == "assessment"
            else "agentic run inspector" if self.mode == "inspector"
            else "draft sanity report"
        )
        if self.mode == "inspector" and self.focus == "right":
            title += " [focused]"
        self._box(screen, 2, left_w + 2, height - 3, right_w, title)
        if self.mode == "coverage":
            source = coverage_lines(self.data, right_w - 4)
        elif self.mode == "inspector":
            if self.data.get("inspector_kind") == "assessment":
                source = assessment_lines(self.data["assessment"], right_w - 4)
            elif self.data.get("inspector_kind") == "run":
                artifacts = self.data.get("artifacts", [])
                if isinstance(artifacts, list):
                    self.data["selected_artifact_index"] = self._selected_artifact_index(len(artifacts))
                source = run_inspector_lines(self.data, right_w - 4)
            else:
                source = search_result_lines(self.data["result"], right_w - 4)
        else:
            source = report_lines(self.data, right_w - 4)
        visible = source[self.scroll:self.scroll + height - 7]
        for row, (text, color) in enumerate(visible):
            screen.addstr(4 + row, left_w + 4, text[:right_w - 4], self._attr(color))
        if self.scroll:
            screen.addstr(height - 4, left_w + 4, f"↑ scrolled {self.scroll}", self._attr("warn"))
        screen.refresh()

    def _draw_run_dashboard(self, screen: Any, height: int, width: int) -> None:
        left_w = max(38, min(66, width // 3))
        right_x = left_w + 2
        right_w = width - left_w - 3
        content_y = 2
        content_h = height - 3
        current_h = max(8, content_h // 2)
        bottom_h = content_h - current_h - 1
        bottom_y = content_y + current_h + 1
        prompt_w = max(34, right_w // 2)
        logs_x = right_x + prompt_w + 1
        logs_w = right_w - prompt_w - 1

        screen.addstr(0, 2, "† PROOF VIBE", self._attr("title") | curses.A_BOLD)
        screen.addstr(
            0, 18,
            "live run dashboard · Tab focus · [] past task · mouse/arrows scroll · q/Esc quit"[:width - 20],
            self._attr("muted"),
        )

        past_title = self._focused_title("run + past tasks", "past")
        self._box(screen, content_y, 1, content_h, left_w, past_title)
        past_height = content_h - 4
        past_lines = self._run_overview_lines(left_w - 4)
        past_total = self._draw_lines(
            screen, content_y + 2, 3, left_w - 4, past_height,
            past_lines, self.left_scroll,
        )
        self.left_scroll = min(self.left_scroll, max(0, past_total - past_height))
        if self.left_scroll:
            screen.addstr(content_y + content_h - 2, 3,
                          f"↑ scrolled {self.left_scroll}"[:left_w - 4], self._attr("warn"))

        current_title = self._focused_title("current task", "current")
        self._box(screen, content_y, right_x, current_h, right_w, current_title)
        current_height = current_h - 4
        current_lines = self._current_task_lines(right_w - 4)
        current_total = self._draw_lines(
            screen, content_y + 2, right_x + 2, right_w - 4, current_height,
            current_lines, self.current_scroll,
        )
        self.current_scroll = min(self.current_scroll, max(0, current_total - current_height))
        if self.current_scroll:
            screen.addstr(content_y + current_h - 2, right_x + 2,
                          f"↑ scrolled {self.current_scroll}"[:right_w - 4], self._attr("warn"))

        prompt_title = self._focused_title("active prompt", "prompt")
        self._box(screen, bottom_y, right_x, bottom_h, prompt_w, prompt_title)
        prompt_height = bottom_h - 4
        prompt_total = self._draw_wrapped(
            screen, bottom_y + 2, right_x + 2, prompt_w - 4, prompt_height,
            self._run_prompt_text(), self._attr("muted"), self.prompt_scroll,
        )
        self.prompt_scroll = min(self.prompt_scroll, max(0, prompt_total - prompt_height))
        if self.prompt_scroll:
            screen.addstr(bottom_y + bottom_h - 2, right_x + 2,
                          f"↑ scrolled {self.prompt_scroll}"[:prompt_w - 4], self._attr("warn"))

        logs_title = self._focused_title("recent logs", "logs")
        self._box(screen, bottom_y, logs_x, bottom_h, logs_w, logs_title)
        logs_height = bottom_h - 4
        log_lines = self._recent_activity_lines(logs_w - 4)
        log_total = self._draw_lines(
            screen, bottom_y + 2, logs_x + 2, logs_w - 4, logs_height,
            log_lines, self.log_scroll,
        )
        self.log_scroll = min(self.log_scroll, max(0, log_total - logs_height))
        if self.log_scroll:
            screen.addstr(bottom_y + bottom_h - 2, logs_x + 2,
                          f"↑ scrolled {self.log_scroll}"[:logs_w - 4], self._attr("warn"))
        screen.refresh()


def arguments(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Terminal UI for Noether")
    parser.add_argument("--policy", default=str(DEFAULT_POLICY))
    parser.add_argument("--model-id", default="terminal-hypothesis")
    parser.add_argument("--hypothesis", default=DEFAULT_HYPOTHESIS)
    parser.add_argument("--manifest")
    parser.add_argument("--proof-results")
    parser.add_argument("--certificate-report")
    parser.add_argument("--search-result")
    parser.add_argument("--run-dir")
    parser.add_argument("--coverage", action="store_true")
    parser.add_argument(
        "--once", action="store_true",
        help="print a non-interactive terminal report and exit",
    )
    parser.add_argument("--width", type=int, default=100)
    return parser.parse_args(argv)


def build_search_inspector(path: str | Path) -> dict[str, Any]:
    value = load_json_value(path)
    if isinstance(value, dict):
        return {"inspector_kind": "search_result", "result": value}
    if isinstance(value, list) and all(isinstance(item, dict) for item in value):
        return {
            "inspector_kind": "run",
            "state": {
                "run_id": str(path),
                "status": "loaded_artifacts",
                "tasks": [
                    {
                        "task_id": item.get("id", "unknown"),
                        "status": item.get("status", "unknown"),
                        "artifact": str(path),
                    }
                    for item in value
                ],
                "blocked": [
                    {"task_id": item.get("id", "unknown"), "status": item.get("status", "unknown")}
                    for item in value
                    if item.get("status") not in {"verified", "approved"}
                ],
                "completed": [
                    {"task_id": item.get("id", "unknown"), "status": item.get("status", "unknown")}
                    for item in value
                    if item.get("status") in {"verified", "approved"}
                ],
            },
            "artifacts": value,
        }
    raise ValueError(f"{path} must contain a search object or array of search objects")


def build_run_inspector(path: str | Path) -> dict[str, Any]:
    root = Path(path)
    assessment = root / "assessment.json"
    if assessment.exists():
        manifest = root / "manifest.json"
        return {
            "inspector_kind": "assessment",
            "assessment": load_json_object(assessment),
            "manifest": load_json_object(manifest) if manifest.exists() else {},
        }
    state = load_json_object(root / "state.json")
    if isinstance(state.get("proof_results"), list):
        results = {
            item.get("id"): item
            for item in state["proof_results"]
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        }
        generated = state.get("generation", {}).get("obligations", [])
        tasks = []
        if isinstance(generated, list):
            for task in generated:
                if not isinstance(task, dict) or not isinstance(task.get("id"), str):
                    continue
                result = results.get(task["id"])
                tasks.append({
                    "task_id": task["id"],
                    "status": result.get("status") if result else (
                        "running" if state.get("status") == "proof_search_running" else task.get("status", "pending")
                    ),
                    "task": task,
                    "artifact": str(root / "state.json"),
                })
        state = {
            "run_id": str(root),
            "status": state.get("status", "unknown"),
            "tasks": tasks,
            "blocked": [],
        }
    artifacts: list[dict[str, Any]] = []
    artifact_root = root / "artifacts"
    if artifact_root.exists():
        for artifact in sorted(artifact_root.glob("*.json")):
            artifacts.append(load_json_object(artifact))
    events = []
    for entry in load_jsonl_objects(root / "events.jsonl", limit=200):
        if not isinstance(entry, dict):
            continue
        if isinstance(entry.get("type"), str):
            normalized = dict(entry)
        else:
            fields = entry.get("fields", {})
            normalized = dict(fields) if isinstance(fields, dict) else {}
            normalized["type"] = entry.get("event", "event")
            normalized["time"] = entry.get("timestamp", "")
        events.append(normalized)
    return {"inspector_kind": "run", "state": state, "artifacts": artifacts, "events": events}


def main(argv: list[str] | None = None) -> int:
    options = arguments(argv)
    policy = Policy.load(options.policy)
    if options.coverage:
        data = policy_coverage(policy)
        if options.once:
            print(render_plain(data, coverage=True, width=options.width))
            return 0
        mode = "coverage"
    elif options.search_result:
        data = build_search_inspector(options.search_result)
        if options.once:
            print(render_plain(data, width=options.width))
            return 0
        mode = "inspector"
    elif options.run_dir:
        data = build_run_inspector(options.run_dir)
        if options.once:
            print(render_plain(data, width=options.width))
            return 0
        mode = "inspector"
    elif options.manifest:
        data = build_artifact_report(
            policy=policy,
            manifest_path=options.manifest,
            proof_results_path=options.proof_results,
            certificate_report_path=options.certificate_report,
        )
        if options.once:
            print(render_plain(data, width=options.width))
            return 0
        mode = "artifact"
    else:
        data = build_hypothesis_report(
            policy=policy, model_id=options.model_id,
            hypothesis=options.hypothesis,
        )
        if options.once:
            print(render_plain(data, width=options.width))
            return 0
        mode = "report"
    TuiApp(
        policy=policy, model_id=options.model_id,
        hypothesis=options.hypothesis,
        mode=mode,
        data=data,
        refresh_path=options.run_dir if options.run_dir and not options.once else None,
    ).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
