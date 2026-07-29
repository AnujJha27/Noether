from __future__ import annotations

import argparse
import curses
import json
import textwrap
from pathlib import Path
from typing import Any

from .hypothesis import draft_hypothesis, policy_coverage
from .manifest import ArchitectureManifest
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


def load_json_list(path: str | Path) -> list[dict[str, Any]]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise ValueError(f"{path} must contain a JSON array of objects")
    return value


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
    if status in {"violates_required_principle", "certificate_check_failed", "refuted"}:
        return "bad"
    if status in {"formalization_gap"}:
        return "gap"
    if status in {"proof_required", "inconclusive_missing_assumption"}:
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


def render_plain(data: dict[str, Any], *, coverage: bool = False,
                 width: int = 100) -> str:
    source = coverage_lines(data, width) if coverage else report_lines(data, width)
    return "\n".join(text for text, _ in source)


class TuiApp:
    def __init__(self, *, policy: Policy, model_id: str, hypothesis: str,
                 mode: str = "report", data: dict[str, Any] | None = None):
        self.policy = policy
        self.model_id = model_id
        self.hypothesis = hypothesis
        self.example_names = list(EXAMPLES)
        self.example_index = 0
        self.mode = mode
        self.scroll = 0
        self.message = "F5 run · F2 coverage · F3 example · Ctrl-U clear · Ctrl-Q quit"
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
        self._colors()
        while True:
            self._draw(screen)
            key = screen.get_wch()
            if key in ("\x11",):  # Ctrl-Q
                return
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
                self.message = "coverage loaded"
                continue
            if key == curses.KEY_F3:
                self._load_next_example()
                continue
            if key == curses.KEY_DOWN:
                self.scroll += 1
                continue
            if key == curses.KEY_UP:
                self.scroll = max(0, self.scroll - 1)
                continue
            if key in (curses.KEY_NPAGE,):
                self.scroll += 8
                continue
            if key in (curses.KEY_PPAGE,):
                self.scroll = max(0, self.scroll - 8)
                continue
            if key in ("\b", "\x7f", curses.KEY_BACKSPACE):
                self.hypothesis = self.hypothesis[:-1]
                continue
            if key in ("\n", "\r"):
                self.hypothesis += "\n"
                continue
            if isinstance(key, str) and key.isprintable():
                self.hypothesis += key

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
                      height: int, text: str, attr: int = 0) -> None:
        lines: list[str] = []
        for paragraph in text.splitlines() or [""]:
            lines.extend(wrap_lines(paragraph, width))
        for row, line in enumerate(lines[:height]):
            screen.addstr(y + row, x, line[:width], attr)

    def _draw(self, screen: Any) -> None:
        screen.erase()
        height, width = screen.getmaxyx()
        if height < 18 or width < 72:
            screen.addstr(0, 0, "terminal too small; use at least 72x18")
            screen.refresh()
            return
        left_w = max(34, min(58, width // 3))
        right_w = width - left_w - 3
        screen.addstr(0, 2, "† PROOF VIBE", self._attr("title") | curses.A_BOLD)
        screen.addstr(0, 18, self.message[:width - 20], self._attr("muted"))

        self._box(screen, 2, 1, height - 3, left_w, "hypothesis")
        self._draw_wrapped(
            screen, 4, 3, left_w - 4, height - 10, self.hypothesis,
            self._attr("muted"),
        )
        footer = "type to edit · F5 run · F3 examples"
        screen.addstr(height - 5, 3, footer[:left_w - 4], self._attr("title"))
        screen.addstr(height - 4, 3, f"id: {self.model_id}"[:left_w - 4], self._attr("muted"))

        title = (
            "coverage" if self.mode == "coverage"
            else "artifact report" if self.mode == "artifact"
            else "draft sanity report"
        )
        self._box(screen, 2, left_w + 2, height - 3, right_w, title)
        source = (
            coverage_lines(self.data, right_w - 4)
            if self.mode == "coverage"
            else report_lines(self.data, right_w - 4)
        )
        visible = source[self.scroll:self.scroll + height - 7]
        for row, (text, color) in enumerate(visible):
            screen.addstr(4 + row, left_w + 4, text[:right_w - 4], self._attr(color))
        if self.scroll:
            screen.addstr(height - 4, left_w + 4, f"↑ scrolled {self.scroll}", self._attr("warn"))
        screen.refresh()


def arguments(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Terminal UI for Proof Vibe")
    parser.add_argument("--policy", default=str(DEFAULT_POLICY))
    parser.add_argument("--model-id", default="terminal-hypothesis")
    parser.add_argument("--hypothesis", default=DEFAULT_HYPOTHESIS)
    parser.add_argument("--manifest")
    parser.add_argument("--proof-results")
    parser.add_argument("--certificate-report")
    parser.add_argument("--coverage", action="store_true")
    parser.add_argument(
        "--once", action="store_true",
        help="print a non-interactive terminal report and exit",
    )
    parser.add_argument("--width", type=int, default=100)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    options = arguments(argv)
    policy = Policy.load(options.policy)
    if options.coverage:
        data = policy_coverage(policy)
        if options.once:
            print(render_plain(data, coverage=True, width=options.width))
            return 0
        mode = "coverage"
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
    ).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
