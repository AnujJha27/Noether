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
from dftcert.manifest import ArchitectureManifest, ManifestError
from dftcert.obligations import generate_obligations
from dftcert.policy import Policy, PolicyError
from dftcert.pt2 import inspect_pt2, pending_manifest
from dftcert.sandbox import BubblewrapExtractor, SandboxUnavailable
from dftcert.security import AuditLog, sign_attestation, verify_attestation
from dftcert.pipeline import LocalPipeline, LocalPipelineConfig, LocalRun
from extractors.torch_export_worker import inventory_node
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
