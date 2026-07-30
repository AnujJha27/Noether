from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any

from .analysis import analyze_inventory
from .extraction import apply_extraction_result
from .manifest import ArchitectureManifest
from .pipeline import (
    LocalPipeline, LocalPipelineConfig, LocalRun, PipelineError, command_tuple,
)
from .policy import Policy
from .pt2 import pending_manifest
from .sandbox import BubblewrapExtractor


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY = ROOT / "policies/dft-architecture-v1.json"


def _object(path: str) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _default_lean_command() -> str:
    lake = shutil.which("lake")
    if lake is None:
        candidate = Path.home() / ".elan/bin/lake"
        lake = str(candidate) if candidate.exists() else "lake"
    return f"{lake} env lean -j 1"


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        prog="noether",
        description="Local, resumable DFT architecture certification",
    )
    root.add_argument("--policy", default=str(DEFAULT_POLICY))
    commands = root.add_subparsers(dest="command", required=True)

    certify = commands.add_parser("certify")
    certify.add_argument("--run-dir", required=True)
    certify.add_argument("--project", required=True)
    certify.add_argument("--llm-command", required=True)
    certify.add_argument("--verifier", default=str(ROOT / "build/proof-search"))
    certify.add_argument("--lean-command", default=_default_lean_command())
    certify.add_argument("--certificate-timeout-s", type=int, default=1800)
    certify.add_argument("--llm-timeout-s", type=int, default=600)
    certify.add_argument("--rounds-per-run", type=int, default=3)
    source = certify.add_mutually_exclusive_group(required=True)
    source.add_argument("--manifest")
    source.add_argument("--description")
    source.add_argument("--pt2")
    certify.add_argument("--model-id")
    certify.add_argument("--facts")
    certify.add_argument("--architecture-ir")
    certify.add_argument("--input-constraints")

    resume = commands.add_parser("resume")
    resume.add_argument("run_dir")

    status = commands.add_parser("status")
    status.add_argument("run_dir")

    replay = commands.add_parser("replay")
    replay.add_argument("path")

    agentic = commands.add_parser(
        "agentic",
        help="forward arguments to the multi-agent Lean proof-search orchestrator",
    )
    agentic.add_argument("orchestrator_args", nargs=argparse.REMAINDER)

    tui = commands.add_parser("tui")
    tui.add_argument("--model-id", default="terminal-hypothesis")
    tui.add_argument("--hypothesis")
    tui.add_argument("--manifest")
    tui.add_argument("--proof-results")
    tui.add_argument("--certificate-report")
    tui.add_argument("--search-result")
    tui.add_argument("--run-dir")
    tui.add_argument("--coverage", action="store_true")
    tui.add_argument("--once", action="store_true")
    return root


def _manifest(options: argparse.Namespace, policy: Policy) -> ArchitectureManifest:
    if options.manifest:
        return ArchitectureManifest.load(options.manifest)
    if not options.model_id:
        raise ValueError("--model-id is required for English or PT2 input")
    if options.description:
        if not options.facts or not options.architecture_ir:
            raise ValueError(
                "English certification requires --facts and --architecture-ir "
                "for explicit local confirmation"
            )
        facts = _object(options.facts)
        manifest = ArchitectureManifest.english_draft(
            model_id=options.model_id, description=options.description,
            policy=policy, proposed_facts=facts,
        )
        manifest.confirm_english(policy, facts)
        manifest.attach_architecture_ir(policy, _object(options.architecture_ir))
        return manifest
    if not options.input_constraints:
        raise ValueError("PT2 certification requires --input-constraints")
    constraints = _object(options.input_constraints)
    manifest = pending_manifest(
        path=options.pt2, model_id=options.model_id,
        policy=policy, input_constraints=constraints,
    )
    result = BubblewrapExtractor().extract(options.pt2)
    analysis = analyze_inventory(
        inventory=result["inventory"], policy=policy,
        input_constraints=constraints,
    )
    result["facts"] = analysis["facts"]
    if "architecture_ir" in analysis:
        result["architecture_ir"] = analysis["architecture_ir"]
    apply_extraction_result(
        manifest=manifest, policy=policy, result=result,
        trusted_sandbox_result=True,
    )
    return manifest


def _summary(state: dict[str, Any], run: LocalRun) -> dict[str, Any]:
    return {
        "status": state["status"],
        "run_dir": str(run.directory),
        "manifest_sha256": state["manifest"]["manifest_sha256"],
        "proofs": [
            {
                "id": item.get("id"), "status": item.get("status"),
                "frontier": item.get("search_graph", {}).get("frontier", []),
            }
            for item in state.get("proof_results", [])
        ],
        "report": (
            str(run.directory / state["report_file"])
            if state.get("report_file") else None
        ),
    }


def main(argv: list[str] | None = None) -> int:
    try:
        raw_args = list(argv) if argv is not None else sys.argv[1:]
        if "agentic" in raw_args:
            index = raw_args.index("agentic")
            options = parser().parse_args(raw_args[:index + 1])
            options.orchestrator_args = raw_args[index + 1:]
        else:
            options = parser().parse_args(raw_args)
        policy = Policy.load(options.policy)
        if options.command == "status":
            run = LocalRun(options.run_dir)
            state = run.load()
        elif options.command == "resume":
            run = LocalRun(options.run_dir)
            stored = run.load()
            config = LocalPipelineConfig.from_json(stored["config"])
            state = LocalPipeline(
                run=run, policy=policy, config=config
            ).resume()
        elif options.command == "tui":
            from .tui import DEFAULT_HYPOTHESIS, main as tui_main
            args = [
                "--policy", options.policy,
                "--model-id", options.model_id,
                "--hypothesis", options.hypothesis or DEFAULT_HYPOTHESIS,
            ]
            if options.manifest:
                args.extend(["--manifest", options.manifest])
            if options.proof_results:
                args.extend(["--proof-results", options.proof_results])
            if options.certificate_report:
                args.extend(["--certificate-report", options.certificate_report])
            if options.search_result:
                args.extend(["--search-result", options.search_result])
            if options.run_dir:
                args.extend(["--run-dir", options.run_dir])
            if options.coverage:
                args.append("--coverage")
            if options.once:
                args.append("--once")
            return tui_main(args)
        elif options.command == "replay":
            from orchestrator.replay import replay_path
            print(replay_path(options.path))
            return 0
        elif options.command == "agentic":
            from orchestrator.cli import main as orchestrator_main
            return orchestrator_main(options.orchestrator_args)
        else:
            run = LocalRun(options.run_dir)
            config = LocalPipelineConfig(
                project_root=str(Path(options.project).resolve()),
                verifier_command=(str(Path(options.verifier).resolve()),),
                verifier_cwd=str(ROOT),
                llm_command=command_tuple(options.llm_command),
                lean_command=command_tuple(options.lean_command),
                certificate_timeout_s=options.certificate_timeout_s,
                llm_timeout_s=options.llm_timeout_s,
                max_rounds_per_run=options.rounds_per_run,
            )
            state = LocalPipeline(
                run=run, policy=policy, config=config
            ).start(_manifest(options, policy))
        print(json.dumps(_summary(state, run), sort_keys=True))
        return 0 if state["status"] == "approved" else 1
    except Exception as error:
        print(json.dumps({
            "status": "invalid",
            "diagnostics": f"{type(error).__name__}: {error}",
        }, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
