from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from .certificate import CertificateError, parse_command, verify_certificate
from .assessment import assess_manifest
from .analysis import analyze_inventory
from .assembly import AssemblyError, assemble_certificate, load_proof_results
from .english import interpret_english
from .extraction import apply_extraction_result
from .manifest import ArchitectureManifest, ManifestError
from .obligations import generate_obligations
from .policy import Policy, PolicyError
from .pt2 import inspect_pt2, pending_manifest
from .sandbox import BubblewrapExtractor, ExtractionFailed, SandboxUnavailable
from orchestrator.providers import CommandProvider


DEFAULT_POLICY = Path(__file__).resolve().parents[1] / "policies/dft-architecture-v1.json"


def json_object(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="DFT architecture certification pipeline")
    root.add_argument("--policy", default=str(DEFAULT_POLICY))
    commands = root.add_subparsers(dest="command", required=True)

    commands.add_parser("policy-check")

    draft = commands.add_parser("english-draft")
    draft.add_argument("--model-id", required=True)
    draft.add_argument("--description", required=True)
    draft.add_argument("--proposed-facts")
    draft.add_argument("--output", required=True)

    interpret = commands.add_parser("english-interpret")
    interpret.add_argument("--model-id", required=True)
    interpret.add_argument("--description", required=True)
    interpret.add_argument("--llm-command", required=True)
    interpret.add_argument("--provider-timeout-s", type=int, default=120)
    interpret.add_argument("--output", required=True)

    confirm = commands.add_parser("confirm")
    confirm.add_argument("--manifest", required=True)
    confirm.add_argument("--facts", required=True)
    confirm.add_argument("--output", required=True)
    confirm.add_argument("--architecture-ir")

    inspect = commands.add_parser("inspect-pt2")
    inspect.add_argument("artifact")

    ingest = commands.add_parser("pt2-pending-manifest")
    ingest.add_argument("artifact")
    ingest.add_argument("--model-id", required=True)
    ingest.add_argument("--input-constraints", required=True)
    ingest.add_argument("--output", required=True)

    apply_extraction = commands.add_parser("apply-extraction")
    apply_extraction.add_argument("--manifest", required=True)
    apply_extraction.add_argument("--result", required=True)
    apply_extraction.add_argument("--output", required=True)
    apply_extraction.add_argument("--trusted-sandbox-result", action="store_true")
    apply_extraction.add_argument(
        "--attestation-key-env", default="DFTCERT_ATTESTATION_KEY"
    )

    extract = commands.add_parser("extract-pt2")
    extract.add_argument("artifact")
    extract.add_argument("--output", required=True)
    extract.add_argument("--bubblewrap", default="bwrap")
    extract.add_argument("--python", default=sys.executable)
    extract.add_argument("--input-constraints")

    certificate = commands.add_parser("certificate-check")
    certificate.add_argument("--project", required=True)
    certificate.add_argument("--source", required=True)
    certificate.add_argument("--manifest", required=True)
    certificate.add_argument("--lean-command", default="lake env lean -j 1")
    certificate.add_argument("--timeout-s", type=int, default=60)
    certificate.add_argument("--trusted-local", action="store_true")

    assess = commands.add_parser("assess")
    assess.add_argument("--manifest", required=True)

    generate = commands.add_parser("generate-obligations")
    generate.add_argument("--manifest", required=True)
    generate.add_argument("--output")
    generate.add_argument(
        "--jsonl", action="store_true",
        help="write one orchestrator-ready task per line to stdout"
    )

    assemble = commands.add_parser("assemble-certificate")
    assemble.add_argument("--manifest", required=True)
    assemble.add_argument("--proof-results", required=True)
    assemble.add_argument("--source-output", required=True)
    assemble.add_argument("--report-output", required=True)

    certify = commands.add_parser("certify-results")
    certify.add_argument("--manifest", required=True)
    certify.add_argument("--proof-results", required=True)
    certify.add_argument("--source-output", required=True)
    certify.add_argument("--report-output", required=True)
    certify.add_argument("--project", required=True)
    certify.add_argument("--lean-command", default="lake env lean -j 1")
    certify.add_argument("--timeout-s", type=int, default=60)
    certify.add_argument("--trusted-local", action="store_true")
    return root


def main(argv: list[str] | None = None) -> int:
    try:
        options = parser().parse_args(argv)
        policy = Policy.load(options.policy)
        if options.command == "policy-check":
            output = {"status": "ok", "policy": policy.id, "version": policy.version,
                      "required_facts": policy.required_facts}
        elif options.command == "english-draft":
            proposed = json_object(options.proposed_facts) if options.proposed_facts else {}
            manifest = ArchitectureManifest.english_draft(
                model_id=options.model_id, description=options.description,
                policy=policy, proposed_facts=proposed,
            )
            manifest.write(options.output)
            output = {"status": "draft", "output": str(Path(options.output).resolve()),
                      "manifest_sha256": manifest.value["manifest_sha256"],
                      "unresolved_facts": manifest.value["unresolved_facts"]}
        elif options.command == "english-interpret":
            manifest = interpret_english(
                provider=CommandProvider(
                    parse_command(options.llm_command), options.provider_timeout_s
                ),
                policy=policy, model_id=options.model_id,
                description=options.description,
            )
            manifest.write(options.output)
            output = {
                "status": "draft", "output": str(Path(options.output).resolve()),
                "manifest_sha256": manifest.value["manifest_sha256"],
                "ambiguities": manifest.value["interpretation"]["ambiguities"],
                "unresolved_facts": manifest.value["unresolved_facts"],
            }
        elif options.command == "confirm":
            manifest = ArchitectureManifest.load(options.manifest)
            manifest.confirm_english(policy, json_object(options.facts))
            if options.architecture_ir:
                manifest.attach_architecture_ir(
                    policy, json_object(options.architecture_ir)
                )
            manifest.write(options.output)
            output = {"status": "confirmed", "output": str(Path(options.output).resolve()),
                      "manifest_sha256": manifest.value["manifest_sha256"]}
        elif options.command == "inspect-pt2":
            output = {"status": "valid_container", **inspect_pt2(options.artifact)}
        elif options.command == "pt2-pending-manifest":
            manifest = pending_manifest(
                path=options.artifact, model_id=options.model_id, policy=policy,
                input_constraints=json_object(options.input_constraints),
            )
            manifest.write(options.output)
            output = {"status": "extraction_pending",
                      "output": str(Path(options.output).resolve()),
                      "manifest_sha256": manifest.value["manifest_sha256"]}
        elif options.command == "apply-extraction":
            manifest = ArchitectureManifest.load(options.manifest)
            apply_extraction_result(
                manifest=manifest, policy=policy, result=json_object(options.result),
                trusted_sandbox_result=options.trusted_sandbox_result,
                attestation_key=(
                    os.environ[options.attestation_key_env].encode()
                    if options.attestation_key_env in os.environ else None
                ),
            )
            manifest.write(options.output)
            output = {
                "status": manifest.value["status"],
                "output": str(Path(options.output).resolve()),
                "manifest_sha256": manifest.value["manifest_sha256"],
                "unresolved_facts": manifest.value["unresolved_facts"],
            }
        elif options.command == "extract-pt2":
            result = BubblewrapExtractor(
                bubblewrap=options.bubblewrap, python=options.python
            ).extract(options.artifact)
            if options.input_constraints:
                analysis = analyze_inventory(
                    inventory=result.get("inventory", {}),
                    policy=policy,
                    input_constraints=json_object(options.input_constraints),
                )
                result["facts"] = analysis["facts"]
                result["analysis"] = {
                    key: value for key, value in analysis.items()
                    if key not in {"facts", "architecture_ir"}
                }
                if "architecture_ir" in analysis:
                    result["architecture_ir"] = analysis["architecture_ir"]
            Path(options.output).write_text(
                json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            output = {
                "status": "extracted_inventory",
                "output": str(Path(options.output).resolve()),
                "artifact_sha256": result["artifact_sha256"],
                "fact_count": len(result["facts"]),
            }
        elif options.command == "assess":
            manifest = ArchitectureManifest.load(options.manifest)
            output = assess_manifest(manifest, policy)
        elif options.command == "generate-obligations":
            output = generate_obligations(
                ArchitectureManifest.load(options.manifest), policy
            )
            if options.output:
                Path(options.output).write_text(
                    json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8"
                )
            if options.jsonl:
                if output["status"] != "obligations_generated":
                    print(json.dumps(output, sort_keys=True))
                    return 1
                for task in output["obligations"]:
                    print(json.dumps(task, sort_keys=True))
                return 0
        elif options.command in {"assemble-certificate", "certify-results"}:
            manifest = ArchitectureManifest.load(options.manifest)
            source, report = assemble_certificate(
                manifest=manifest, policy=policy,
                proof_results=load_proof_results(options.proof_results),
            )
            Path(options.source_output).write_text(source, encoding="utf-8")
            if options.command == "certify-results":
                verification = verify_certificate(
                    policy=policy, project_root=options.project,
                    certificate_source=options.source_output,
                    manifest=manifest,
                    lean_command=parse_command(options.lean_command),
                    timeout_s=options.timeout_s,
                    trusted_local=options.trusted_local,
                )
                report["status"] = (
                    "approved" if verification["status"] == "verified"
                    else "certificate_check_failed"
                )
                report["certificate_verification"] = verification
                report.pop("report_sha256", None)
                from .manifest import sha256_value
                report["report_sha256"] = sha256_value(report)
            Path(options.report_output).write_text(
                json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            output = {
                "status": report["status"],
                "source": str(Path(options.source_output).resolve()),
                "report": str(Path(options.report_output).resolve()),
                "report_sha256": report["report_sha256"],
            }
        else:
            output = verify_certificate(
                policy=policy, project_root=options.project,
                certificate_source=options.source,
                manifest=ArchitectureManifest.load(options.manifest),
                lean_command=parse_command(options.lean_command),
                timeout_s=options.timeout_s, trusted_local=options.trusted_local,
            )
        print(json.dumps(output, sort_keys=True))
        return 0 if output.get("status") in {
            "ok", "draft", "confirmed", "valid_container", "extraction_pending",
            "extracted", "extracted_partial", "verified", "not_approved", "approved",
            "extracted_inventory",
            "obligations_generated", "formalization_required",
            "assembled_pending_certificate_check",
        } else 1
    except (PolicyError, ManifestError, CertificateError, AssemblyError, SandboxUnavailable,
            ExtractionFailed, OSError,
            json.JSONDecodeError, ValueError) as error:
        print(json.dumps({"status": "invalid", "diagnostics": str(error)}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
