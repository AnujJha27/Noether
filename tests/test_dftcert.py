from __future__ import annotations

import json
import os
import pathlib
import sys
import tempfile
import unittest
import zipfile

from dftcert.certificate import CertificateError, build_check_source, verify_certificate
from dftcert.assessment import assess_manifest
from dftcert.analysis import analyze_inventory
from dftcert.assembly import AssemblyError, assemble_certificate
from dftcert.context import ContextError, WorkerContextRegistry
from dftcert.english import interpret_english
from dftcert.extraction import apply_extraction_result
from dftcert.hypothesis import draft_hypothesis, policy_coverage
from dftcert.manifest import ArchitectureManifest, ManifestError
from dftcert.model_assessment import _extract_json_object, assessment_payload, assumption_rows
from dftcert.obligations import generate_obligations
from dftcert.policy import Policy, PolicyError
from dftcert.pt2 import inspect_pt2, pending_manifest
from dftcert.report import sanity_report
from dftcert.sandbox import BubblewrapExtractor, SandboxUnavailable
from dftcert.security import AuditLog, sign_attestation, verify_attestation
from dftcert.structural_v2 import (
    assemble_structural_certificate,
    assess_structural_ir,
    confirmed_description_ir,
    generate_structural_obligations,
    structural_ir_from_inventory,
    structural_failure_witnesses,
    validate_translation,
)
from dftcert.pipeline import LocalPipeline, LocalPipelineConfig, LocalRun
from dftcert.tui import assessment_lines, build_artifact_report, build_hypothesis_report, build_run_inspector, event_summary, render_plain
from extractors.torch_export_worker import inventory_node
from examples.dft.evaluate_structural_v2 import score as score_structural_v2
from orchestrator.providers import MockProvider


ROOT = pathlib.Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "policies/dft-architecture-v1.json"


class PolicyTests(unittest.TestCase):
    def test_policy_has_three_required_obligations(self):
        policy = Policy.load(POLICY_PATH)
        self.assertEqual(policy.id, "dft-architecture-v1")
        self.assertEqual(set(policy.required_facts), {
            "xc_discontinuity_compatible", "spatial_nonlocality_compatible", "self_adjoint",
        })

    def test_rejects_duplicate_facts(self):
        value = json.loads(POLICY_PATH.read_text())
        value["obligations"][1]["fact"] = value["obligations"][0]["fact"]
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "bad.json"
            path.write_text(json.dumps(value))
            with self.assertRaises(PolicyError):
                Policy.load(path)

    def test_llm_json_extractor_accepts_fenced_object_and_trailing_text(self):
        value = _extract_json_object("```json\n{\"facts\": {}}\n```\nignored")
        self.assertEqual(value, {"facts": {}})


class ManifestTests(unittest.TestCase):
    def setUp(self):
        self.policy = Policy.load(POLICY_PATH)
        self.facts = json.loads((ROOT / "examples/dft/confirmed-facts.json").read_text())

    def test_english_requires_confirmation(self):
        manifest = ArchitectureManifest.english_draft(
            model_id="english-model", description="A nonlocal self-adjoint architecture",
            policy=self.policy, proposed_facts=self.facts,
        )
        with self.assertRaises(ManifestError):
            manifest.validate(self.policy, require_confirmed=True)
        manifest.confirm_english(self.policy, self.facts)
        manifest.validate(self.policy, require_confirmed=True)
        self.assertTrue(all(
            fact["evidence"]["kind"] == "user_attestation"
            for fact in manifest.value["facts"].values()
        ))

    def test_confirmation_requires_every_policy_fact(self):
        manifest = ArchitectureManifest.english_draft(
            model_id="incomplete", description="Incomplete description", policy=self.policy,
        )
        with self.assertRaises(ManifestError):
            manifest.confirm_english(self.policy, {"self_adjoint": True})

    def test_hash_detects_tampering(self):
        manifest = ArchitectureManifest.english_draft(
            model_id="tamper", description="Original", policy=self.policy,
        )
        manifest.value["source"]["description"] = "Changed"
        with self.assertRaises(ManifestError):
            manifest.validate(self.policy)

    def test_confirmation_is_not_a_proof(self):
        manifest = ArchitectureManifest.english_draft(
            model_id="asserted", description="All properties are claimed",
            policy=self.policy, proposed_facts=self.facts,
        )
        manifest.confirm_english(self.policy, self.facts)
        assessment = assess_manifest(manifest, self.policy)
        self.assertEqual(assessment["status"], "not_approved")
        self.assertTrue(all(
            item["status"] == "proof_required" for item in assessment["obligations"]
        ))

    def test_descriptive_manifest_cannot_invent_a_formalization(self):
        manifest = ArchitectureManifest.english_draft(
            model_id="asserted", description="All properties are claimed",
            policy=self.policy, proposed_facts=self.facts,
        )
        manifest.confirm_english(self.policy, self.facts)
        result = generate_obligations(manifest, self.policy)
        self.assertEqual(result["status"], "formalization_required")
        self.assertEqual(result["obligations"], [])

    def test_policy_profile_generates_hash_bound_tasks(self):
        manifest = ArchitectureManifest.load(ROOT / "examples/dft/example-manifest.json")
        result = generate_obligations(manifest, self.policy)
        self.assertEqual(result["status"], "obligations_generated")
        self.assertEqual(len(result["obligations"]), 3)
        for task in result["obligations"]:
            self.assertEqual(task["verification_mode"], "generated_obligation")
            self.assertNotIn("target", task)
            self.assertIn(manifest.value["manifest_sha256"], task["preamble"])
            self.assertGreaterEqual(task["limits"]["wall_time_ms"], 600000)

    def test_three_hop_gnn_profile_generates_matching_tasks(self):
        manifest = ArchitectureManifest.english_draft(
            model_id="chain4-gnn",
            description=(ROOT / "examples/dft/gnn-3hop-description.txt").read_text(),
            policy=self.policy,
        )
        facts = json.loads((ROOT / "examples/dft/gnn-3hop-facts.json").read_text())
        architecture_ir = json.loads(
            (ROOT / "examples/dft/gnn-3hop-architecture-ir.json").read_text()
        )
        manifest.confirm_english(self.policy, facts)
        manifest.attach_architecture_ir(self.policy, architecture_ir)
        result = generate_obligations(manifest, self.policy)
        self.assertEqual(result["status"], "obligations_generated")
        self.assertEqual(result["profile"], "dft-v1-hinge-residual-chain4-k3")
        self.assertIn("Fin 4", result["obligations"][1]["theorem"])

    def test_ring_gnn_profile_generates_matching_tasks(self):
        manifest = ArchitectureManifest.english_draft(
            model_id="ring6-gnn",
            description=(ROOT / "examples/dft/gnn-ring6-3hop-description.txt").read_text(),
            policy=self.policy,
        )
        manifest.confirm_english(
            self.policy, json.loads((ROOT / "examples/dft/gnn-ring6-3hop-facts.json").read_text())
        )
        manifest.attach_architecture_ir(
            self.policy,
            json.loads((ROOT / "examples/dft/gnn-ring6-3hop-architecture-ir.json").read_text()),
        )
        result = generate_obligations(manifest, self.policy)
        self.assertEqual(result["profile"], "dft-v1-hinge-residual-ring6-k3")
        self.assertIn("Fin 6", result["obligations"][1]["theorem"])


class EnglishInterpreterTests(unittest.TestCase):
    def test_interpreter_output_remains_non_authoritative(self):
        policy = Policy.load(POLICY_PATH)
        provider = MockProvider([{
            "facts": {
                "self_adjoint": {
                    "satisfied": True,
                    "enforcement": "symmetric_parameterization",
                }
            },
            "ambiguities": ["Receptive field was not quantified"],
            "missing_facts": [
                "xc_discontinuity_compatible", "spatial_nonlocality_compatible"
            ],
        }])
        manifest = interpret_english(
            provider=provider, policy=policy, model_id="interpreted",
            description="The operator is self-adjoint.",
        )
        self.assertEqual(manifest.value["status"], "draft")
        self.assertFalse(manifest.value["interpretation"]["authoritative"])
        self.assertEqual(manifest.value["unresolved_facts"], [
            "xc_discontinuity_compatible", "spatial_nonlocality_compatible"
        ])


class HypothesisIntakeTests(unittest.TestCase):
    def setUp(self):
        self.policy = Policy.load(POLICY_PATH)

    def test_hypothesis_draft_records_assumptions_and_traceability(self):
        manifest = draft_hypothesis(
            model_id="front-facing",
            hypothesis=(
                "A DFT architecture with an XC derivative discontinuity, "
                "nonlocal coupling, and a self-adjoint learned operator."
            ),
            policy=self.policy,
        )
        self.assertEqual(manifest.value["status"], "draft")
        self.assertEqual(
            manifest.value["hypothesis_intake"]["extracted_claim_count"], 3
        )
        self.assertTrue(manifest.value["assumptions"])
        self.assertTrue(manifest.value["traceability"])
        self.assertTrue(any(
            question["fact"] == "architecture_ir"
            for question in manifest.value["clarification_questions"]
        ))
        self.assertTrue(all(
            fact["evidence"]["kind"] == "unconfirmed_interpretation"
            for fact in manifest.value["facts"].values()
        ))

    def test_missing_assumption_becomes_clarifying_question(self):
        manifest = draft_hypothesis(
            model_id="missing",
            hypothesis="The architecture has nonlocal message passing.",
            policy=self.policy,
        )
        facts = set(manifest.value["facts"])
        self.assertEqual(facts, {"spatial_nonlocality_compatible"})
        questions = {
            question["fact"] for question in manifest.value["clarification_questions"]
        }
        self.assertIn("self_adjoint", questions)
        self.assertIn("xc_discontinuity_compatible", questions)

    def test_sanity_report_distinguishes_refutation_from_formalization_gap(self):
        manifest = draft_hypothesis(
            model_id="bad",
            hypothesis=(
                "The model has an XC derivative discontinuity and nonlocal "
                "coupling but is explicitly non-self-adjoint."
            ),
            policy=self.policy,
        )
        report = sanity_report(manifest=manifest, policy=self.policy)
        self.assertEqual(report["status"], "violates_required_principle")
        categories = {
            item["fact"]: item["category"] for item in report["obligations"]
        }
        self.assertEqual(categories["self_adjoint"], "violates_required_principle")

    def test_policy_coverage_lists_supported_and_unsupported_scope(self):
        coverage = policy_coverage(self.policy)
        self.assertEqual(coverage["policy"]["id"], "dft-architecture-v1")
        self.assertEqual(len(coverage["supported_claims"]), 3)
        self.assertTrue(any(
            "trained-weight" in item for item in coverage["not_supported"]
        ))

    def test_terminal_report_is_readable_without_curses(self):
        data = build_hypothesis_report(
            policy=self.policy,
            model_id="terminal",
            hypothesis="The architecture is nonlocal but does not specify self-adjointness.",
        )
        rendered = render_plain(data, width=88)
        self.assertIn("VERDICT", rendered)
        self.assertIn("PRINCIPLE CHECKS", rendered)
        self.assertIn("CLARIFY BEFORE FORMALIZING", rendered)

    def test_terminal_report_can_show_later_stage_artifacts(self):
        data = build_artifact_report(
            policy=self.policy,
            manifest_path=ROOT / "examples/dft/example-manifest.json",
            proof_results_path=ROOT / "examples/dft/example-proof-results.json",
        )
        rendered = render_plain(data, width=88)
        self.assertIn("PROOF SEARCH ARTIFACTS", rendered)
        self.assertIn("consistent with policy", rendered.lower())

    def test_assessment_payload_is_structured_without_raw_logs(self):
        manifest = draft_hypothesis(
            model_id="plain-english",
            hypothesis="The model is nonlocal and uses a self-adjoint learned operator.",
            policy=self.policy,
        )
        payload = assessment_payload(manifest=manifest, policy=self.policy)
        self.assertEqual(payload["verdict"], "inconclusive")
        self.assertIn("assumptions", payload)
        self.assertIn("checks", payload)
        rendered = render_plain(
            {"inspector_kind": "assessment", "assessment": payload},
            width=88,
        )
        self.assertIn("VERDICT", rendered)
        self.assertIn("ASSUMPTIONS", rendered)
        self.assertIn("VERDICT EVIDENCE", rendered)
        self.assertNotIn("events.jsonl", rendered)

    def test_assessment_carries_non_authoritative_rationale_review(self):
        manifest = draft_hypothesis(
            model_id="reviewed-rationale",
            hypothesis="The model has a self-adjoint learned operator.",
            policy=self.policy,
        )
        manifest.value["proof_reviews"] = [{
            "fact": "self_adjoint",
            "claimed_reasoning": "The operator is symmetric.",
            "assessment": "supports",
            "review": "This supports the claim, but requires Lean verification.",
            "formal_status": "not_lean_verified",
        }]
        manifest.refresh_hash()
        row = next(item for item in assumption_rows(manifest, self.policy) if item["id"] == "self_adjoint")
        self.assertEqual(row["proof_review"]["formal_status"], "not_lean_verified")
        rendered = "\n".join(text for text, _ in assessment_lines(
            assessment_payload(manifest=manifest, policy=self.policy), 88
        ))
        self.assertIn("rationale review", rendered)

    def test_run_dir_prefers_assessment_artifact(self):
        manifest = draft_hypothesis(
            model_id="assessment-run",
            hypothesis="The model has an XC derivative discontinuity and nonlocal coupling.",
            policy=self.policy,
        )
        payload = assessment_payload(manifest=manifest, policy=self.policy)
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory)
            (path / "assessment.json").write_text(json.dumps(payload), encoding="utf-8")
            (path / "manifest.json").write_text(
                json.dumps(manifest.value), encoding="utf-8"
            )
            data = build_run_inspector(path)
        self.assertEqual(data["inspector_kind"], "assessment")
        self.assertEqual(data["manifest"]["source"]["description"], manifest.value["source"]["description"])

    def test_run_inspector_renders_local_pipeline_generation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory)
            (path / "state.json").write_text(json.dumps({
                "status": "proof_search_running",
                "proof_results": [],
                "generation": {"obligations": [{
                    "id": "ring6-xc", "status": "proof_required",
                    "theorem": "theorem generated_xc : True",
                }]},
            }), encoding="utf-8")
            data = build_run_inspector(path)
        self.assertEqual(data["inspector_kind"], "run")
        self.assertEqual(data["state"]["tasks"][0]["status"], "running")

    def test_run_inspector_preserves_orchestrator_model_call_events(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory)
            (path / "state.json").write_text(json.dumps({"status": "running"}), encoding="utf-8")
            (path / "events.jsonl").write_text(json.dumps({
                "type": "model_call_started", "time": "2026-08-05T12:34:56+00:00",
                "agent": "direct", "model": "qwen3.6-64k:latest", "call_index": 1,
            }) + "\n", encoding="utf-8")
            event = build_run_inspector(path)["events"][0]
        self.assertEqual(event["type"], "model_call_started")
        self.assertIn("12:34:56 model_call_started", event_summary(event)[0])


class Pt2Tests(unittest.TestCase):
    def setUp(self):
        self.policy = Policy.load(POLICY_PATH)

    def test_valid_pt2_becomes_pending_not_approved(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "model.pt2"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("model/serialized_exported_program.json", "{}")
                archive.writestr("model/version", "1")
            inspection = inspect_pt2(path)
            self.assertEqual(inspection["entry_count"], 2)
            manifest = pending_manifest(
                path=path, model_id="pt2-model", policy=self.policy,
                input_constraints={"inputs": [{"shape": [1, 4], "dtype": "float32"}]},
            )
            self.assertEqual(manifest.value["status"], "extraction_pending")
            self.assertEqual(manifest.value["facts"], {})

    def test_rejects_archive_path_traversal(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "evil.pt2"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("../escape", "bad")
            with self.assertRaises(ManifestError):
                inspect_pt2(path)

    def test_rejects_non_pt2_extension(self):
        with tempfile.NamedTemporaryFile(suffix=".pth") as file:
            with self.assertRaises(ManifestError):
                inspect_pt2(file.name)

    def test_extraction_result_is_bound_to_artifact_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "model.pt2"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("model/program.json", "{}")
            manifest = pending_manifest(
                path=path, model_id="extracted", policy=self.policy,
                input_constraints={"inputs": [{"shape": [1]}]},
            )
            result = {
                "extractor_version": "fixture-1",
                "sandbox_attestation": {"runtime": "test"},
                "facts": {
                    name: {"value": value, "nodes": [f"node:{name}"]}
                    for name, value in json.loads(
                        (ROOT / "examples/dft/confirmed-facts.json").read_text()
                    ).items()
                },
            }
            apply_extraction_result(
                manifest=manifest, policy=self.policy, result=result,
                trusted_sandbox_result=True,
            )
            self.assertEqual(manifest.value["status"], "extracted")
            artifact_hash = manifest.value["source"]["artifact_sha256"]
            self.assertTrue(all(
                fact["evidence"]["artifact_sha256"] == artifact_hash
                for fact in manifest.value["facts"].values()
            ))
            assessment = assess_manifest(manifest, self.policy)
            self.assertEqual(assessment["status"], "not_approved")

    def test_partial_extraction_stays_inconclusive(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "model.pt2"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("model/program.json", "{}")
            manifest = pending_manifest(
                path=path, model_id="partial", policy=self.policy,
                input_constraints={"inputs": [{"shape": [1]}]},
            )
            apply_extraction_result(
                manifest=manifest, policy=self.policy,
                result={
                    "extractor_version": "fixture-1",
                    "facts": {
                        "self_adjoint": {
                            "value": {
                                "satisfied": True,
                                "enforcement": "symmetric_parameterization",
                            },
                            "nodes": ["projection"],
                        }
                    },
                },
                trusted_sandbox_result=True,
            )
            self.assertEqual(manifest.value["status"], "extracted_partial")
            self.assertEqual(len(manifest.value["unresolved_facts"]), 2)

    def test_untrusted_extraction_result_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "model.pt2"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("model/program.json", "{}")
            manifest = pending_manifest(
                path=path, model_id="untrusted", policy=self.policy,
                input_constraints={"inputs": [{"shape": [1]}]},
            )
            with self.assertRaises(ManifestError):
                apply_extraction_result(
                    manifest=manifest, policy=self.policy,
                    result={"extractor_version": "forged", "facts": {}},
                )


class ExtractorSandboxTests(unittest.TestCase):
    def artifact(self, directory):
        path = pathlib.Path(directory) / "model.pt2"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("model/program.json", "{}")
        return path

    def test_missing_sandbox_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(SandboxUnavailable):
                BubblewrapExtractor(
                    bubblewrap="definitely-not-a-real-bwrap"
                ).extract(self.artifact(directory))

    def test_controller_requires_namespaces_and_binds_result_to_artifact(self):
        fake = ROOT / "tests/fake_bwrap.py"
        fake.chmod(0o755)
        with tempfile.TemporaryDirectory() as directory:
            artifact = self.artifact(directory)
            extractor = BubblewrapExtractor(bubblewrap=str(fake), app_root=ROOT)
            command = extractor.command(artifact)
            self.assertIn("--unshare-all", command)
            self.assertIn("--clearenv", command)
            self.assertIn("--ro-bind", command)
            result = extractor.extract(artifact)
            self.assertEqual(result["artifact_sha256"], inspect_pt2(artifact)["artifact_sha256"])
            self.assertEqual(result["sandbox_attestation"]["network"], "unshared")
            self.assertEqual(result["facts"], {})

    def test_inventory_normalizes_graph_nodes_without_torch(self):
        class Node:
            name = "add"
            op = "call_function"
            target = "aten.add.Tensor"
            args = (1, 2)
            kwargs = {"alpha": 1}
            meta = {}

        self.assertEqual(inventory_node(Node()), {
            "name": "add",
            "op": "call_function",
            "target": "aten.add.Tensor",
            "args": [1, 2],
            "kwargs": {"alpha": 1},
        })

    def test_exact_two_output_graph_derives_reviewed_ir(self):
        policy = Policy.load(POLICY_PATH)

        def node(name, op, target, args):
            return {
                "name": name, "op": op, "target": target,
                "args": args, "kwargs": {},
            }

        inventory = {"nodes": [
            node("x", "placeholder", "x", []),
            node("relu", "call_function", "aten.relu.default", [{"node": "x"}]),
            node("zero", "call_function", "aten.zeros_like.default", [{"node": "x"}]),
            node("output", "output", "output", [[
                {"node": "relu"}, {"node": "zero"},
            ]]),
        ]}
        result = analyze_inventory(
            inventory=inventory, policy=policy,
            input_constraints={
                "output_contracts": [
                    {"index": 0, "role": "xc_energy"},
                    {"index": 1, "role": "learned_self_energy"},
                ],
                "required_couplings": [],
            },
        )
        self.assertEqual(set(result["facts"]), set(policy.required_facts))
        self.assertEqual(result["architecture_ir"]["operator"]["construction"], "zero")

    def test_unsupported_graph_stays_inconclusive(self):
        policy = Policy.load(POLICY_PATH)
        inventory = {"nodes": [
            {"name": "x", "op": "placeholder", "target": "x",
             "args": [], "kwargs": {}},
            {"name": "sin", "op": "call_function", "target": "aten.sin.default",
             "args": [{"node": "x"}], "kwargs": {}},
            {"name": "output", "op": "output", "target": "output",
             "args": [[{"node": "sin"}]], "kwargs": {}},
        ]}
        result = analyze_inventory(
            inventory=inventory, policy=policy,
            input_constraints={
                "output_contracts": [{"index": 0, "role": "xc_energy"}]
            },
        )
        self.assertEqual(result["facts"], {})
        self.assertNotIn("architecture_ir", result)


class AssemblyTests(unittest.TestCase):
    def test_verified_winners_assemble_exact_certificate(self):
        policy = Policy.load(POLICY_PATH)
        manifest = ArchitectureManifest.load(ROOT / "examples/dft/example-manifest.json")
        results = json.loads(
            (ROOT / "examples/dft/example-proof-results.json").read_text()
        )
        source, report = assemble_certificate(
            manifest=manifest, policy=policy, proof_results=results
        )
        self.assertIn("theorem certificate", source)
        self.assertIn(manifest.value["manifest_sha256"], source)
        self.assertEqual(len(report["obligations"]), 3)

    def test_missing_verified_winner_cannot_assemble(self):
        policy = Policy.load(POLICY_PATH)
        manifest = ArchitectureManifest.load(ROOT / "examples/dft/example-manifest.json")
        with self.assertRaises(AssemblyError):
            assemble_certificate(
                manifest=manifest, policy=policy, proof_results=[]
            )


class LocalPipelineSecurityTests(unittest.TestCase):
    def test_signed_attestation_detects_tampering(self):
        signed = sign_attestation(
            {"artifact_sha256": "a" * 64, "network": "unshared"}, b"key"
        )
        self.assertTrue(verify_attestation(signed, b"key"))
        signed["network"] = "host"
        self.assertFalse(verify_attestation(signed, b"key"))

    def test_audit_log_is_hmac_chained(self):
        with tempfile.TemporaryDirectory() as directory:
            audit = AuditLog(pathlib.Path(directory) / "audit.jsonl", b"key")
            first = audit.append("one", {"x": 1})
            second = audit.append("two", {"x": 2})
            self.assertEqual(second["previous_hmac"], first["entry_hmac"])

    def test_pipeline_runs_search_assembly_and_final_check(self):
        policy = Policy.load(POLICY_PATH)
        manifest = ArchitectureManifest.load(ROOT / "examples/dft/example-manifest.json")
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            project = root / "project"
            project.mkdir()
            (project / "lean-toolchain").write_text(policy.toolchain)
            run = LocalRun(root / "run")
            pipeline = LocalPipeline(
                run=run, policy=policy,
                config=LocalPipelineConfig(
                    project_root=str(project),
                    verifier_command=(
                        sys.executable, str(ROOT / "tests/fake_verifier.py")
                    ),
                    verifier_cwd=str(ROOT),
                    llm_command=(sys.executable, str(ROOT / "tests/fake_llm.py")),
                    lean_command=(sys.executable, str(ROOT / "tests/fake_lean.py")),
                    certificate_timeout_s=10,
                ),
            )
            completed = pipeline.start(manifest)
            self.assertEqual(completed["status"], "approved")
            self.assertEqual(len(completed["proof_results"]), 3)
            self.assertTrue((run.directory / "Certificate.lean").exists())
            self.assertTrue((run.directory / "report.json").exists())
            inspector = build_run_inspector(run.directory)
            self.assertTrue(any(
                event["type"] == "model_call_started" for event in inspector["events"]
            ))
            self.assertEqual(pipeline.resume()["status"], "approved")


class CertificateTests(unittest.TestCase):
    def setUp(self):
        self.policy = Policy.load(POLICY_PATH)
        facts = json.loads((ROOT / "examples/dft/confirmed-facts.json").read_text())
        self.manifest = ArchitectureManifest.english_draft(
            model_id="certificate-model", description="Confirmed model",
            policy=self.policy, proposed_facts=facts,
        )
        self.manifest.confirm_english(self.policy, facts)

    def test_wrapper_checks_exact_named_declaration_and_type(self):
        wrapper = build_check_source(
            "import Testv2.Verifier\n", self.policy,
            self.manifest.value["manifest_sha256"],
        )
        self.assertIn(self.policy.certificate.declaration, wrapper)
        self.assertIn(self.policy.certificate.expected_type, wrapper)
        self.assertIn(self.manifest.value["manifest_sha256"], wrapper)

    def test_example_certificate_is_bound_to_example_manifest(self):
        manifest = ArchitectureManifest.load(ROOT / "examples/dft/example-manifest.json")
        manifest.validate(self.policy, require_confirmed=True)
        source = (ROOT / "policies/lean/DFTArchitectureV1Example.lean").read_text()
        self.assertIn(manifest.value["manifest_sha256"], source)

    def test_untrusted_compilation_is_refused(self):
        with self.assertRaises(CertificateError):
            verify_certificate(
                policy=self.policy, project_root=".", certificate_source=POLICY_PATH,
                manifest=self.manifest,
            )

    def test_trusted_checker_records_hashes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            (root / "lean-toolchain").write_text(self.policy.toolchain)
            source = root / "Certificate.lean"
            source.write_text("import Testv2.Verifier\n")
            result = verify_certificate(
                policy=self.policy, project_root=root, certificate_source=source,
                manifest=self.manifest,
                lean_command=[sys.executable, str(ROOT / "tests/fake_lean.py")],
                trusted_local=True,
            )
            self.assertEqual(result["status"], "verified")
            self.assertEqual(len(result["project"]["fingerprint"]), 64)
            self.assertEqual(result["certificate"]["declaration"],
                             "DFTCert.Example.certificate")


class StructuralV2Tests(unittest.TestCase):
    def inventory(self):
        ref = lambda name: {"node": name}
        return {
            "nodes": [
                {"name": "b_adjacency", "op": "placeholder", "target": "b_adjacency", "args": [], "kwargs": {}},
                {"name": "p_base", "op": "placeholder", "target": "p_base", "args": [], "kwargs": {}},
                {"name": "density", "op": "placeholder", "target": "density", "args": [], "kwargs": {}},
                {"name": "matmul", "op": "call_function", "target": "aten.matmul.default", "args": [ref("b_adjacency"), ref("density")], "kwargs": {}},
                {"name": "matmul_1", "op": "call_function", "target": "aten.matmul.default", "args": [ref("b_adjacency"), ref("matmul")], "kwargs": {}},
                {"name": "matmul_2", "op": "call_function", "target": "aten.matmul.default", "args": [ref("b_adjacency"), ref("matmul_1")], "kwargs": {}},
                {"name": "relu", "op": "call_function", "target": "aten.relu.default", "args": [ref("density")], "kwargs": {}},
                {"name": "numpy_t", "op": "call_function", "target": "aten.numpy_T.default", "args": [ref("p_base")], "kwargs": {}},
                {"name": "add", "op": "call_function", "target": "aten.add.Tensor", "args": [ref("p_base"), ref("numpy_t")], "kwargs": {}},
                {"name": "output", "op": "output", "target": "output", "args": [[ref("relu"), ref("add"), ref("matmul_2")]], "kwargs": {}},
            ],
            "state": {"adjacency": {
                "structural_values": [[False, True, False, False], [False, False, True, False], [False, False, False, True], [False, False, False, False]],
                "graph_inputs": ["b_adjacency"], "shape": [4, 4], "dtype": "torch.bool", "sha256": "a",
            }},
        }

    def constraints(self):
        return {
            "adjacency_state_name": "adjacency", "adjacency_convention": "source_target",
            "output_contracts": [
                {"index": 0, "role": "xc_energy"},
                {"index": 1, "role": "learned_self_energy"},
                {"index": 2, "role": "message_state"},
            ],
            "required_couplings": [{"source": 0, "target": 3}],
        }

    def test_translation_validation_rejects_ir_claim_tampering(self):
        inventory = self.inventory()
        ir = structural_ir_from_inventory(
            inventory=inventory, artifact_sha256="artifact", extractor_version="test",
            input_constraints=self.constraints(),
        )
        self.assertEqual(ir["translation_validation"]["status"], "translation_validated")
        ir["message_passing"]["depth"] = 2
        with self.assertRaises(ManifestError):
            validate_translation(inventory=inventory, value=ir, input_constraints=self.constraints())

    def ir(self, *, depth=3, xc="hinge", operator="symmetrized"):
        return confirmed_description_ir(
            description="Reviewed six-site structural model",
            topology={
                "site_count": 6,
                "directed_edges": [
                    [0, 1], [1, 2], [2, 3], [3, 4], [4, 5], [5, 0],
                    [1, 0], [2, 1], [3, 2], [4, 3], [5, 4], [0, 5],
                ],
                "provenance_nodes": [],
            },
            message_passing={"depth": depth, "provenance_nodes": []},
            xc={"form": xc, "provenance_nodes": []},
            operator={"construction": operator, "provenance_nodes": []},
            requirements={"couplings": [{"source": 0, "target": 3}]},
        )

    def test_structural_assessment_and_failure_witnesses(self):
        self.assertEqual(assess_structural_ir(self.ir())["status"], "structurally_certifiable")
        shallow = self.ir(depth=2)
        self.assertEqual(
            assess_structural_ir(shallow)["status"], "structural_requirements_not_met"
        )
        witness = structural_failure_witnesses(shallow)
        self.assertEqual(witness[0]["kind"], "uncovered_coupling")
        self.assertEqual((witness[0]["source"], witness[0]["target"]), (0, 3))

    def test_generated_tasks_are_ir_bound_and_not_fixed_templates(self):
        generated = generate_structural_obligations(self.ir())
        self.assertEqual(len(generated["obligations"]), 3)
        self.assertIn(generated["ir_sha256"], generated["obligations"][0]["preamble"])
        self.assertIn("allCovered", generated["obligations"][1]["theorem"])
        self.assertNotIn("Fin 6", generated["obligations"][1]["theorem"])
        self.assertIn("Topology: 6 sites", generated["obligations"][0]["context"])
        self.assertIn("Scope: structural compatibility only", generated["obligations"][0]["context"])

    def test_certificate_distinguishes_confirmed_specification(self):
        ir = self.ir()
        generated = generate_structural_obligations(ir)
        results = [
            {"id": task["id"], "status": "verified", "winner": {"patch": "by decide"}}
            for task in generated["obligations"]
        ]
        source, report = assemble_structural_certificate(ir, results)
        self.assertEqual(report["certificate_kind"], "confirmed_specification")
        self.assertIn(generated["source_sha256"], source)
        self.assertIn(generated["ir_sha256"], source)

    def test_certificate_rejects_placeholder_proofs(self):
        ir = self.ir()
        generated = generate_structural_obligations(ir)
        results = [
            {"id": task["id"], "status": "verified", "winner": {"patch": "by sorry"}}
            for task in generated["obligations"]
        ]
        with self.assertRaises(ManifestError):
            assemble_structural_certificate(ir, results)

    def test_evaluation_separates_answers_from_artifact_evidence(self):
        expected = {"demo": {"self_adjoint": True}}
        direct = [{"case": "demo", "checks": {"self_adjoint": True}}]
        harness = [{
            "case": "demo", "checks": {"self_adjoint": True},
            "artifact_sha256": "a", "ir_sha256": "b",
            "certificate_status": "verified",
        }]
        self.assertEqual(score_structural_v2(expected, direct)["exact_case_accuracy"], 1)
        self.assertEqual(score_structural_v2(expected, direct)["artifact_binding_rate"], 0)
        self.assertEqual(score_structural_v2(expected, harness)["lean_verified_rate"], 1)


class ContextRegistryTests(unittest.TestCase):
    def test_reuses_only_identical_project_toolchain_policy_context(self):
        policy = Policy.load(POLICY_PATH)
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            project = root / "project"
            cache = root / "cache"
            project.mkdir()
            (project / "lean-toolchain").write_text(policy.toolchain)
            (project / "Model.lean").write_text("def model := 1\n")
            registry = WorkerContextRegistry(
                verifier_command=[sys.executable, str(ROOT / "tests/fake_verifier.py")],
                service_cwd=ROOT, cache_dir=cache,
            )
            try:
                first = registry.get(policy, project)
                second = registry.get(policy, project)
                self.assertIs(first, second)
                self.assertTrue(first.key.cache_namespace)
                (project / "Model.lean").write_text("def model := 2\n")
                third = registry.get(policy, project)
                self.assertIsNot(first, third)
            finally:
                registry.close()

    def test_rejects_wrong_toolchain(self):
        policy = Policy.load(POLICY_PATH)
        with tempfile.TemporaryDirectory() as directory:
            project = pathlib.Path(directory)
            (project / "lean-toolchain").write_text("other")
            registry = WorkerContextRegistry(
                verifier_command=[sys.executable, str(ROOT / "tests/fake_verifier.py")],
                service_cwd=ROOT, cache_dir=project / "cache",
            )
            with self.assertRaises(ContextError):
                registry.get(policy, project)


if __name__ == "__main__":
    unittest.main()
