from __future__ import annotations

import argparse
import curses
import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from .legacy.analysis import analyze_inventory
from .legacy.extraction import apply_extraction_result
from .manifest import ArchitectureManifest
from .legacy.model_assessment import (
    assessment_payload,
    confirm_assumptions_interactively,
    draft_with_llm,
    read_description,
)
from .legacy.hypothesis import draft_hypothesis
from .legacy.pipeline import (
    LocalPipeline, LocalPipelineConfig, LocalRun, PipelineError, command_tuple,
)
from .legacy.policy import Policy
from .legacy.pt2 import pending_manifest
from .legacy.report import sanity_report
from .sandbox import BubblewrapExtractor


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY = ROOT / "policies/dft-architecture-v1.json"
CLUSTER_LLM_PRESETS = {
    "maestro": {
        "base_url": "http://127.0.0.1:11434/v1/chat/completions",
        "model": "qwen3.6-64k:latest",
    },
    "piano": {
        "base_url": "http://pianoteg:11437/v1/chat/completions",
        "model": "qwen3.6:27b-q4_K_M",
    },
    "sitar": {
        "base_url": "http://sitarteg:11437/v1/chat/completions",
        "model": "qwen2.5-coder:14b-instruct-q4_K_M",
    },
    "violin": {
        "base_url": "http://violinteg:11437/v1/chat/completions",
        "model": "qwen3.6-64k:latest",
    },
}

DFT_DEMO_SCENARIOS = {
    "certified": {
        "description": "Canonical reviewed DFT architecture; runs the full Lean proof-search workflow.",
        "mode": "proof_search",
    },
    "non-self-adjoint": {
        "description": "Explicitly non-self-adjoint operator; the policy rejects it before proof search.",
        "mode": "assessment",
        "hypothesis": (
            "The architecture has an XC derivative discontinuity at electron-number "
            "boundaries and nonlocal spatial coupling, but its learned self-energy "
            "operator is explicitly non-self-adjoint."
        ),
    },
    "missing-assumptions": {
        "description": "Nonlocality is described, but two required physics claims are absent.",
        "mode": "assessment",
        "hypothesis": (
            "The proposed DFT model uses nonlocal message passing to propagate density "
            "information across sites."
        ),
    },
    "formalization-gap": {
        "description": "All three policy claims are described, but no reviewed Lean architecture profile is supplied.",
        "mode": "assessment",
        "hypothesis": (
            "The architecture supports an XC derivative discontinuity at electron-number "
            "boundaries, uses nonlocal spatial coupling, and enforces a self-adjoint "
            "learned self-energy operator."
        ),
    },
}


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


def _lake_executable() -> str:
    lake = shutil.which("lake")
    if lake is None:
        candidate = Path.home() / ".elan/bin/lake"
        lake = str(candidate) if candidate.exists() else "lake"
    return lake


def _ensure_lean_project_built(project: Path, target: str | None = None) -> None:
    lake = _lake_executable()
    command = [lake, "build"]
    if target:
        command.append(target)
    try:
        process = subprocess.run(
            command,
            cwd=project,
            text=True,
            capture_output=True,
            check=False,
        )
    except OSError as error:
        raise ValueError(
            f"Lean build tool not found or not executable: {lake}. "
            "Install Lean/Lake or set PATH/PROOF_SEARCH_LAKE before proof search."
        ) from error
    if process.returncode != 0:
        detail = process.stderr.strip() or process.stdout.strip()
        rendered = " ".join(command)
        raise ValueError(f"Lean project build failed before proof search (`{rendered}`): {detail}")


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        prog="noether",
        description="Structural V2 certification with retained legacy V1 workflows",
    )
    root.add_argument("--policy", default=str(DEFAULT_POLICY))
    commands = root.add_subparsers(dest="command", required=True)

    certify = commands.add_parser("certify", help="run the legacy V1 policy pipeline")
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

    structural = commands.add_parser(
        "structural", help="run the primary Structural V2 workflow"
    )
    structural.add_argument("structural_args", nargs=argparse.REMAINDER)

    demo = commands.add_parser("demo", help="run a bundled Noether workflow demo")
    demo.add_argument(
        "kind",
        nargs="?",
        choices=("physics-toy", "dft"),
        default="physics-toy",
    )
    demo.add_argument("--run-dir")
    demo.add_argument(
        "--scenario",
        choices=tuple(DFT_DEMO_SCENARIOS),
        default="certified",
        help="DFT demo case; only 'certified' runs Lean proof search",
    )
    demo.add_argument(
        "--project",
        help="optional reviewed Testv2 project; defaults to examples/dft/lean for DFT",
    )
    demo.add_argument("--max-rounds", type=int, default=1)
    demo.add_argument(
        "--provider-timeout-s",
        type=int,
        default=300,
        help="seconds to wait for each live model adapter call",
    )
    demo.add_argument("--verifier", default=str(ROOT / "build/proof-search"))
    demo.add_argument(
        "--llm",
        choices=(
            "deterministic",
            "openrouter-free",
            "openai-compatible",
            "maestro",
            "piano",
            "sitar",
            "violin",
        ),
        default="deterministic",
        help="model backend for the demo",
    )
    demo.add_argument(
        "--model",
        default=None,
        help="model slug for --llm openrouter-free",
    )

    assess = commands.add_parser("assess", help="assess a model description against a physics policy")
    assess.add_argument("kind", choices=("dft",))
    assess.add_argument("--description", required=True, help="description text or path to a markdown/text file")
    assess.add_argument("--run-dir", required=True)
    assess.add_argument("--model-id", default="described-model")
    assess.add_argument(
        "--llm",
        choices=("deterministic", "openai-compatible", "maestro", "piano", "sitar", "violin"),
        default="deterministic",
        help="assumption extractor backend",
    )
    assess.add_argument("--model", default=None, help="model slug for --llm openai-compatible")
    assess.add_argument("--provider-timeout-s", type=int, default=180)
    assess.add_argument(
        "--non-interactive",
        action="store_true",
        help="write the draft assessment without asking for assumption confirmation",
    )

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
    tui.add_argument("--width", type=int, default=100)

    review = commands.add_parser("review", help="review accepted Lean proofs from an agentic run")
    review.add_argument("--run-dir", required=True)
    review.add_argument("--once", action="store_true")
    review.add_argument("--width", type=int, default=100)
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


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        value = value.strip().strip('"').strip("'")
        if name and name not in os.environ:
            os.environ[name] = value


def _write_dft_assessment_demo(
    *, options: argparse.Namespace, policy: Policy, scenario: str,
) -> int:
    spec = DFT_DEMO_SCENARIOS[scenario]
    hypothesis = spec["hypothesis"]
    run_dir = Path(options.run_dir or (ROOT / "build/runs" / f"noether-dft-{scenario}"))
    manifest = draft_hypothesis(
        model_id=f"demo-fixture:{scenario}", hypothesis=hypothesis, policy=policy,
    )
    report = sanity_report(manifest=manifest, policy=policy)
    assessment = assessment_payload(manifest=manifest, policy=policy)
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest.write(run_dir / "manifest.json")
    (run_dir / "report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (run_dir / "assessment.json").write_text(
        json.dumps(assessment, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "status": "demo_complete",
        "kind": "dft",
        "scenario": scenario,
        "scenario_description": spec["description"],
        "verdict": assessment["verdict"],
        "summary": assessment["summary"],
        "run_dir": str(run_dir),
        "inspect": f"./noether tui --run-dir {run_dir}",
        "note": "This scenario stops at policy assessment; it does not claim a Lean proof search ran.",
    }, sort_keys=True))
    return 0


def _run_demo(options: argparse.Namespace, policy: Policy) -> int:
    _load_env_file(ROOT / ".env")
    if options.kind == "dft" and options.scenario != "certified":
        return _write_dft_assessment_demo(options=options, policy=policy, scenario=options.scenario)
    verifier = Path(options.verifier)
    if not verifier.exists():
        raise ValueError(f"verifier not found at {verifier}; run `make` first")
    demo_adapter = ROOT / "examples/orchestrator/noether_demo_llm.py"
    openrouter_adapter = ROOT / "examples/orchestrator/openrouter_free_adapter.py"
    openai_compatible_adapter = ROOT / "examples/orchestrator/openai_compatible_adapter.py"
    agents = ROOT / "examples/orchestrator/agents.research.json"
    if options.kind == "physics-toy":
        tasks = ROOT / "examples/orchestrator/physics-toy-tasks.jsonl"
        run_dir = options.run_dir or str(ROOT / "build/runs/noether-physics-toy")
        env = os.environ.copy()
        _ensure_lean_project_built(ROOT / "lean")
    else:
        tasks = ROOT / "examples/dft/noether-obligations.jsonl"
        project = options.project or os.environ.get("DFT_PROJECT") or str(ROOT / "examples/dft/lean")
        run_dir = options.run_dir or str(ROOT / "build/runs/noether-dft")
        _ensure_lean_project_built(Path(project), "Testv2.Verifier")
        env = os.environ.copy()
        env.update({
            "PROOF_SEARCH_ALLOW_GENERATED_OBLIGATIONS": "1",
            "PROOF_SEARCH_PROJECT_DIR": str(Path(project).resolve()),
            "PROOF_SEARCH_DB": str(Path(run_dir).resolve() / "proof-search.db"),
        })
    if options.llm == "openrouter-free":
        if not os.environ.get("OPENROUTER_API_KEY"):
            raise ValueError("OPENROUTER_API_KEY is required for --llm openrouter-free")
        llm_command = f"{shlex.quote(sys.executable)} {shlex.quote(str(openrouter_adapter))}"
        env["OPENROUTER_MODEL"] = options.model or "openrouter/free"
    elif options.llm in {"openai-compatible", *CLUSTER_LLM_PRESETS}:
        preset = CLUSTER_LLM_PRESETS.get(options.llm)
        if preset:
            env["NOETHER_OPENAI_BASE_URL"] = preset["base_url"]
            env["NOETHER_OPENAI_MODEL"] = options.model or preset["model"]
            env.setdefault("NOETHER_OPENAI_MAX_TOKENS", "8192")
            env.setdefault("NOETHER_OPENAI_TIMEOUT_S", str(options.provider_timeout_s))
        if not env.get("NOETHER_OPENAI_BASE_URL"):
            raise ValueError("NOETHER_OPENAI_BASE_URL is required for --llm openai-compatible")
        if not env.get("NOETHER_OPENAI_MODEL") and not options.model:
            raise ValueError("NOETHER_OPENAI_MODEL or --model is required for --llm openai-compatible")
        if options.model:
            env["NOETHER_OPENAI_MODEL"] = options.model
        llm_command = f"{shlex.quote(sys.executable)} {shlex.quote(str(openai_compatible_adapter))}"
    else:
        llm_command = f"{shlex.quote(sys.executable)} {shlex.quote(str(demo_adapter))}"
    command = [
        sys.executable, "-m", "orchestrator.cli",
        "--provider", "command",
        "--llm-command", llm_command,
        "--verifier", str(verifier),
        "--agents-file", str(agents),
        "--run-dir", run_dir,
        "--max-rounds", str(options.max_rounds),
        "--provider-timeout-s", str(options.provider_timeout_s),
        "--agent-parallelism", "1",
    ]
    input_text = tasks.read_text(encoding="utf-8")
    process = subprocess.run(
        command,
        input=input_text,
        text=True,
        cwd=ROOT,
        env=env,
        capture_output=True,
        check=False,
    )
    if process.returncode != 0:
        if process.stdout:
            print(process.stdout, end="")
        if process.stderr:
            print(process.stderr, end="", file=sys.stderr)
        return process.returncode
    result_lines = [
        line for line in process.stdout.splitlines()
        if line.strip()
    ]
    statuses = []
    for line in result_lines:
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        statuses.append({
            "id": item.get("id"),
            "status": item.get("status"),
        })
    Path(run_dir).mkdir(parents=True, exist_ok=True)
    (Path(run_dir) / "results.jsonl").write_text(
        "\n".join(result_lines) + ("\n" if result_lines else ""),
        encoding="utf-8",
    )
    print(json.dumps({
        "status": "demo_complete",
        "kind": options.kind,
        "llm": options.llm,
        "model": (
            (options.model or env.get("OPENROUTER_MODEL") or env.get("NOETHER_OPENAI_MODEL"))
            if options.llm in {"openrouter-free", "openai-compatible", *CLUSTER_LLM_PRESETS}
            else "deterministic"
        ),
        "run_dir": run_dir,
        "tasks": statuses,
        "results": str(Path(run_dir) / "results.jsonl"),
        "replay": f"./noether replay {run_dir}",
        "inspect": f"./noether tui --run-dir {run_dir} --once",
    }, sort_keys=True))
    return 0


def _run_assess(options: argparse.Namespace, policy: Policy) -> int:
    _load_env_file(ROOT / ".env")
    description = read_description(options.description)
    run_dir = Path(options.run_dir)
    if options.llm == "deterministic":
        from .legacy.hypothesis import draft_hypothesis

        manifest = draft_hypothesis(
            model_id=options.model_id,
            hypothesis=description,
            policy=policy,
        )
    else:
        preset = CLUSTER_LLM_PRESETS.get(options.llm)
        base_url = preset["base_url"] if preset else os.environ.get("NOETHER_OPENAI_BASE_URL")
        model = options.model or (preset["model"] if preset else os.environ.get("NOETHER_OPENAI_MODEL"))
        if not base_url:
            raise ValueError("NOETHER_OPENAI_BASE_URL is required for LLM assumption extraction")
        if not model:
            raise ValueError("NOETHER_OPENAI_MODEL or --model is required for LLM assumption extraction")
        manifest = draft_with_llm(
            model_id=options.model_id,
            description=description,
            policy=policy,
            base_url=base_url,
            model=model,
            timeout_s=options.provider_timeout_s,
        )
    if not options.non_interactive and sys.stdin.isatty():
        if sys.stdout.isatty():
            try:
                from .tui import confirm_assumptions_tui

                confirm_assumptions_tui(manifest, policy)
            except curses.error:
                confirm_assumptions_interactively(manifest, policy)
        else:
            confirm_assumptions_interactively(manifest, policy)
    report = sanity_report(manifest=manifest, policy=policy)
    assessment = assessment_payload(manifest=manifest, policy=policy)
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest.write(run_dir / "manifest.json")
    (run_dir / "report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (run_dir / "assessment.json").write_text(
        json.dumps(assessment, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "status": "assessment_complete",
        "kind": options.kind,
        "verdict": assessment["verdict"],
        "summary": assessment["summary"],
        "run_dir": str(run_dir),
        "inspect": f"./noether tui --run-dir {run_dir} --once",
        "artifacts": {
            "assessment": str(run_dir / "assessment.json"),
            "manifest": str(run_dir / "manifest.json"),
            "report": str(run_dir / "report.json"),
        },
    }, sort_keys=True))
    return 0


def main(argv: list[str] | None = None) -> int:
    try:
        raw_args = list(argv) if argv is not None else sys.argv[1:]
        forwarded = next(
            (name for name in ("agentic", "structural") if name in raw_args), None
        )
        if forwarded:
            index = raw_args.index(forwarded)
            options = parser().parse_args(raw_args[:index + 1])
            setattr(options, f"{forwarded}_args", raw_args[index + 1:])
        else:
            options = parser().parse_args(raw_args)
        if options.command == "structural":
            from .structural.cli import main as structural_main
            return structural_main(options.structural_args)
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
            args.extend(["--width", str(options.width)])
            return tui_main(args)
        elif options.command == "review":
            from .tui import main as tui_main
            args = ["--policy", options.policy, "--review-run-dir", options.run_dir,
                    "--width", str(options.width)]
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
        elif options.command == "demo":
            return _run_demo(options, policy)
        elif options.command == "assess":
            return _run_assess(options, policy)
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
