from __future__ import annotations

import json
import pathlib
import sys
import unittest

from orchestrator.engine import Orchestrator, SearchConfig
from orchestrator.models import SearchTask
from orchestrator.providers import CommandProvider, MockProvider
from orchestrator.verifier import VerifierClient


ROOT = pathlib.Path(__file__).resolve().parents[1]


class FakeBatchVerifier:
    def __init__(self):
        self.batches = []
        self.generated_batches = []

    def verify_batch(self, **request):
        self.batches.append(request)
        results = []
        winner = None
        for candidate in request["candidates"]:
            status = "verified" if candidate["patch"] == "good" else "lean_error"
            results.append({"id": candidate["id"], "status": status,
                            "diagnostics": "bad proof" if status == "lean_error" else "",
                            "elapsed_ms": 1, "cached": False})
            if status == "verified":
                winner = candidate["id"]
                break
        return {"status": "verified" if winner else "no_candidate_verified", "results": results}

    def verify_generated_batch(self, **request):
        self.generated_batches.append(request)
        return self.verify_batch(**request)


class ModelTests(unittest.TestCase):
    def test_task_validation(self):
        task = SearchTask.from_json({"id": "x", "target": "A.t", "theorem": "theorem t : True",
                                     "module": "A", "project": "sample"})
        self.assertEqual(task.project, "sample")
        with self.assertRaises(ValueError):
            SearchTask.from_json({"id": "x", "target": "A.t"})
        generated = SearchTask.from_json({
            "id": "g", "verification_mode": "generated_obligation",
            "preamble": "def x := 1", "theorem": "theorem g : True",
            "module": "A", "project": "sample",
        })
        self.assertEqual(generated.target, "")


class ProviderTests(unittest.TestCase):
    def test_command_provider_contract(self):
        provider = CommandProvider([sys.executable, str(ROOT / "tests/fake_llm.py")])
        result = provider.complete(agent="direct", system="system", prompt="prompt", schema={})
        self.assertEqual(result["candidates"][0]["patch"], "by rfl")


class VerifierTests(unittest.TestCase):
    def test_persistent_jsonl_client(self):
        command = [sys.executable, str(ROOT / "tests/fake_verifier.py")]
        with VerifierClient(command, ROOT) as verifier:
            response = verifier.verify_batch(
                request_id="b", target="A.t", project="bundled",
                module="A", declaration="theorem t : True",
                candidates=[{"id": "c", "patch": "by rfl"}], max_parallel=1,
                stop_on_first_success=True, limits={},
            )
        self.assertEqual(response["status"], "verified")

    def test_generated_batch_has_explicit_trusted_mode_and_no_target(self):
        command = [sys.executable, str(ROOT / "tests/fake_verifier.py")]
        with VerifierClient(command, ROOT) as verifier:
            response = verifier.verify_generated_batch(
                request_id="generated", project="bundled", module="A",
                declaration="theorem generated : True", preamble="def input := 1",
                candidates=[{"id": "c", "patch": "by rfl"}],
                max_parallel=1, stop_on_first_success=True, limits={},
            )
        self.assertEqual(response["status"], "verified")


class EngineTests(unittest.TestCase):
    def task(self):
        return SearchTask(id="search", target="A.t", theorem="theorem t : True",
                          module="A", project="sample")

    def test_diagnostics_drive_a_repair_round(self):
        provider = MockProvider([
            {"candidates": [{"patch": "bad", "rationale": "first"}]},
            {"candidates": []},
            {"candidates": []},
            {"candidates": [{"patch": "good", "rationale": "repair"}]},
            {"candidates": []},
            {"candidates": []},
        ])
        verifier = FakeBatchVerifier()
        config = SearchConfig(max_rounds=2, proposer_roles={"direct": "d", "automation": "a", "structural": "s"},
                              max_agent_parallelism=1)
        result = Orchestrator(provider, verifier, config).search(self.task())
        self.assertEqual(result["status"], "verified")
        self.assertEqual(result["winner"]["patch"], "good")
        self.assertEqual(len(verifier.batches), 2)
        second_round = [
            node for node in result["search_graph"]["nodes"]
            if node["candidate"]["round"] == 2
        ]
        self.assertTrue(second_round)
        self.assertIsNotNone(second_round[0]["parent_id"])

    def test_critic_order_controls_verification_order(self):
        provider = MockProvider([
            {"candidates": [{"patch": "bad", "rationale": "a"}]},
            {"candidates": [{"patch": "good", "rationale": "b"}]},
            {"ordered_ids": ["search-r1-automation-1", "search-r1-direct-1"],
             "feedback": "prefer constructor"},
        ])
        verifier = FakeBatchVerifier()
        config = SearchConfig(max_rounds=1, proposer_roles={"direct": "d", "automation": "a"},
                              max_agent_parallelism=1)
        result = Orchestrator(provider, verifier, config).search(self.task())
        self.assertEqual(result["status"], "verified")
        self.assertEqual(verifier.batches[0]["candidates"][0]["patch"], "good")
        self.assertTrue(any(event["type"] == "critic" for event in result["events"]))

    def test_rejects_placeholder_candidates(self):
        provider = MockProvider([{"candidates": [{"patch": "by sorry"}]}])
        verifier = FakeBatchVerifier()
        config = SearchConfig(max_rounds=1, proposer_roles={"direct": "d"}, max_model_calls=1)
        result = Orchestrator(provider, verifier, config).search(self.task())
        self.assertEqual(result["status"], "model_budget_exhausted")
        self.assertEqual(verifier.batches, [])

    def test_generated_task_uses_generated_verifier_boundary(self):
        provider = MockProvider([{"candidates": [{"patch": "good"}]}])
        verifier = FakeBatchVerifier()
        task = SearchTask(
            id="generated", target="", theorem="theorem generated : True",
            module="A", project="sample", verification_mode="generated_obligation",
            preamble="def trustedInput := 1",
        )
        result = Orchestrator(
            provider, verifier,
            SearchConfig(max_rounds=1, proposer_roles={"direct": "d"}, max_model_calls=1),
        ).search(task)
        self.assertEqual(result["status"], "verified")
        self.assertEqual(verifier.generated_batches[0]["preamble"], task.preamble)

    def test_search_graph_can_resume_and_handoff_to_new_agent_round(self):
        first = Orchestrator(
            MockProvider([{"candidates": [{"patch": "bad"}]}]),
            FakeBatchVerifier(),
            SearchConfig(max_rounds=1, proposer_roles={"first": "try"}),
        ).search(self.task())
        self.assertEqual(first["status"], "exhausted")
        second = Orchestrator(
            MockProvider([{"candidates": [{"patch": "good"}]}]),
            FakeBatchVerifier(),
            SearchConfig(max_rounds=1, proposer_roles={"successor": "repair"}),
        ).search(self.task(), resume=first)
        self.assertEqual(second["status"], "verified")
        resumed = [
            node for node in second["search_graph"]["nodes"]
            if node["candidate"]["agent"] == "successor"
        ]
        self.assertEqual(resumed[0]["parent_id"], first["search_graph"]["frontier"][0])


if __name__ == "__main__":
    unittest.main()
