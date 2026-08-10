from __future__ import annotations

import argparse
import json
import shlex
import sys
from pathlib import Path
from typing import Any

from orchestrator.providers import CommandProvider

from ..legacy.assembly import load_proof_results
from ..manifest import ManifestError
from ..sandbox import BubblewrapExtractor, ExtractionFailed, SandboxUnavailable
from .core import (
    assemble_structural_certificate,
    confirmed_description_ir,
    generate_structural_obligations,
    structural_ir_from_inventory,
    structural_report,
    verify_structural_certificate,
)


CLAIMS_SCHEMA = {
    "type": "object",
    "required": ["topology", "message_passing", "xc", "operator", "requirements"],
    "properties": {
        "topology": {
            "type": "object",
            "required": ["site_count", "directed_edges"],
        },
        "message_passing": {"type": "object", "required": ["depth"]},
        "xc": {"type": "object", "required": ["form"]},
        "operator": {"type": "object", "required": ["construction"]},
        "requirements": {"type": "object", "required": ["couplings"]},
    },
}


def _object(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _ir(path: str | Path) -> dict[str, Any]:
    value = _object(path)
    nested = value.get("ir")
    return nested if isinstance(nested, dict) else value


def _write(path: str | Path, value: Any) -> None:
    Path(path).write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _atomic_claims(claims: dict[str, Any], *, description: str, reviewed: bool) -> list[dict[str, Any]]:
    """Keep each human-reviewable specification claim separate from the IR blob."""
    return [
        {
            "property": property_name,
            "proposed_value": value,
            "source_text": description,
            "source_span": None,
            "draft_interpretation": value,
            "reviewer_decision": "confirmed" if reviewed else "pending",
            "final_value": value if reviewed else None,
            "provenance": "human_confirmation" if reviewed else "llm_draft",
        }
        for property_name, value in claims.items()
    ]


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        prog="noether structural", description="Artifact-grounded Structural V2 workflow"
    )
    commands = root.add_subparsers(dest="command", required=True)

    analyze = commands.add_parser("analyze-pt2")
    analyze.add_argument("artifact")
    analyze.add_argument("--constraints", required=True)
    analyze.add_argument("--output", required=True)
    analyze.add_argument("--bubblewrap", default="bwrap")
    analyze.add_argument("--python", default=sys.executable)

    analyze_result = commands.add_parser(
        "analyze-extraction", help="analyze an already-produced trusted local extractor result"
    )
    analyze_result.add_argument("result")
    analyze_result.add_argument("--constraints", required=True)
    analyze_result.add_argument("--output", required=True)

    draft = commands.add_parser("draft-description")
    draft.add_argument("--description", required=True)
    draft.add_argument("--llm-command", required=True)
    draft.add_argument("--timeout-s", type=int, default=180)
    draft.add_argument("--output", required=True)

    confirm = commands.add_parser("confirm-description")
    confirm.add_argument("--draft", required=True)
    confirm.add_argument("--reviewed-claims")
    confirm.add_argument("--output", required=True)
    confirm.add_argument(
        "--confirmed", action="store_true",
        help="record that a human reviewed the structural claims",
    )

    generate = commands.add_parser("generate")
    generate.add_argument("--ir", required=True)
    generate.add_argument("--output")
    generate.add_argument("--jsonl", action="store_true")

    report = commands.add_parser("report")
    report.add_argument("--ir", required=True)
    report.add_argument("--output", required=True)

    assemble = commands.add_parser("assemble")
    assemble.add_argument("--ir", required=True)
    assemble.add_argument("--proof-results", required=True)
    assemble.add_argument("--source-output", required=True)
    assemble.add_argument("--report-output", required=True)

    check = commands.add_parser("check-certificate")
    check.add_argument("--project", required=True)
    check.add_argument("--source", required=True)
    check.add_argument("--lean-command", default="lake env lean -j 1")
    check.add_argument("--timeout-s", type=int, default=60)
    check.add_argument("--trusted-local", action="store_true")
    return root


def _from_extraction(result: dict[str, Any], constraints: dict[str, Any]) -> dict[str, Any]:
    artifact_hash = result.get("artifact_sha256")
    extractor_version = result.get("extractor_version")
    if not isinstance(artifact_hash, str) or not isinstance(extractor_version, str):
        raise ManifestError("extractor result is missing artifact hash or extractor version")
    return structural_ir_from_inventory(
        inventory=result.get("inventory", {}),
        artifact_sha256=artifact_hash,
        extractor_version=extractor_version,
        input_constraints=constraints,
    )


def main(argv: list[str] | None = None) -> int:
    try:
        options = parser().parse_args(argv)
        if options.command == "analyze-pt2":
            result = BubblewrapExtractor(
                bubblewrap=options.bubblewrap, python=options.python
            ).extract(options.artifact)
            ir = _from_extraction(result, _object(options.constraints))
            _write(options.output, ir)
            output = {"status": "analyzed", "output": str(Path(options.output).resolve())}
        elif options.command == "analyze-extraction":
            ir = _from_extraction(_object(options.result), _object(options.constraints))
            _write(options.output, ir)
            output = {"status": "analyzed", "output": str(Path(options.output).resolve())}
        elif options.command == "draft-description":
            description_path = Path(options.description)
            description = (
                description_path.read_text(encoding="utf-8")
                if description_path.exists() else options.description
            )
            proposal = CommandProvider(
                shlex.split(options.llm_command), options.timeout_s
            ).complete(
                agent="structural-spec-drafter",
                system=(
                    "Translate only explicit architectural claims into the supplied JSON schema. "
                    "Use unsupported when XC or operator construction is not specified."
                ),
                prompt=(
                    "Extract a finite directed topology, message-passing depth, XC form "
                    "(hinge, smooth, unsupported), operator construction (zero, identity, "
                    "symmetrized, unconstrained_parameter, unsupported), and required couplings. "
                    "Do not infer trained numerical behavior.\n\nDescription:\n" + description
                ),
                schema=CLAIMS_SCHEMA,
            )
            draft = {
                "status": "draft_requires_human_confirmation",
                "authoritative": False,
                "description": description,
                "proposed_claims": proposal,
                "atomic_claims": _atomic_claims(proposal, description=description, reviewed=False),
            }
            _write(options.output, draft)
            output = {"status": "draft", "output": str(Path(options.output).resolve())}
        elif options.command == "confirm-description":
            if not options.confirmed:
                raise ManifestError("confirmation requires --confirmed after human review")
            draft = _object(options.draft)
            description = draft.get("description")
            claims = (
                _object(options.reviewed_claims)
                if options.reviewed_claims else draft.get("proposed_claims")
            )
            if not isinstance(description, str) or not isinstance(claims, dict):
                raise ManifestError("draft is missing its description or proposed claims")
            ir = confirmed_description_ir(
                description=description,
                confirmed_claims=_atomic_claims(claims, description=description, reviewed=True),
                **claims,
            )
            _write(options.output, ir)
            output = {
                "status": "confirmed_specification",
                "output": str(Path(options.output).resolve()),
            }
        elif options.command == "generate":
            generated = generate_structural_obligations(_ir(options.ir))
            if options.output:
                _write(options.output, generated)
            if options.jsonl:
                for task in generated["obligations"]:
                    print(json.dumps(task, separators=(",", ":")))
                return 0
            output = generated
        elif options.command == "report":
            output = structural_report(_ir(options.ir))
            _write(options.output, output)
        elif options.command == "assemble":
            source, report = assemble_structural_certificate(
                _ir(options.ir), load_proof_results(options.proof_results)
            )
            Path(options.source_output).write_text(source, encoding="utf-8")
            _write(options.report_output, report)
            output = {
                "status": report["status"],
                "source": str(Path(options.source_output).resolve()),
                "report": str(Path(options.report_output).resolve()),
            }
        else:
            output = verify_structural_certificate(
                project_root=options.project,
                certificate_source=options.source,
                lean_command=shlex.split(options.lean_command),
                timeout_s=options.timeout_s,
                trusted_local=options.trusted_local,
            )
        print(json.dumps(output, sort_keys=True))
        return 0 if output.get("status") not in {"invalid", "lean_error", "timeout"} else 1
    except (
        ManifestError, SandboxUnavailable, ExtractionFailed, OSError,
        ValueError, json.JSONDecodeError,
    ) as error:
        print(json.dumps({"status": "invalid", "diagnostics": str(error)}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
