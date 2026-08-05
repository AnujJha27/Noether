from __future__ import annotations

import contextlib
import io
import json
import os
import pathlib
import sys
import tempfile
import unittest

from dftcert.tui import build_search_inspector, render_plain
from orchestrator.agents import AgentRegistry, AgentSpec
from orchestrator.cli import main as orchestrator_main, provider_routes_from_file
from orchestrator.engine import Orchestrator, SearchConfig
from orchestrator.models import SearchTask
from orchestrator.permissions import PermissionPolicy
from orchestrator.provider_router import ProviderRouter
from orchestrator.providers import CommandProvider, MockProvider, ProviderError
from orchestrator.replay import replay_search_result
from orchestrator.run_manager import RunStore
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


class ProjectNotBuiltVerifier(FakeBatchVerifier):
    def verify_batch(self, **request):
        self.batches.append(request)
        return {
            "status": "no_candidate_verified",
            "results": [
                {"id": candidate["id"], "status": "project_not_built",
                 "diagnostics": "Lean project is not built", "elapsed_ms": 0,
                 "cached": False}
                for candidate in request["candidates"]
            ],
        }


class CapturingProvider(MockProvider):
    def __init__(self, responses):
        super().__init__(responses)
        self.prompts = []

    def complete(self, *, agent, system, prompt, schema):
        self.prompts.append({"agent": agent, "prompt": prompt})
        return super().complete(agent=agent, system=system, prompt=prompt, schema=schema)


class TimeoutProvider(MockProvider):
    def complete(self, **kwargs):
        raise ProviderError("LLM command timed out after 120 seconds")


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
        decomposed = SearchTask.from_json({
            "id": "d", "target": "A.t", "theorem": "theorem t : True",
            "module": "A", "project": "sample",
            "subgoals": [
                {"id": "lemma-a", "theorem": "theorem a : True"},
                {"id": "lemma-b", "statement": "theorem b : True", "depends_on": ["lemma-a"]},
            ],
        })
        self.assertEqual(len(decomposed.subgoals), 2)
        with self.assertRaises(ValueError):
            SearchTask.from_json({
                "id": "bad", "target": "A.t", "theorem": "theorem t : True",
                "module": "A", "project": "sample",
                "subgoals": [{"id": "b", "theorem": "theorem b : True", "depends_on": ["missing"]}],
            })


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

    def test_missing_lean_build_stops_repair_rounds(self):
        verifier = ProjectNotBuiltVerifier()
        result = Orchestrator(
            MockProvider([{"candidates": [{"patch": "by decide"}]}]), verifier,
            SearchConfig(max_rounds=3, proposer_roles={"direct": "d"}),
        ).search(self.task())
        self.assertEqual(result["status"], "project_not_built")
        self.assertEqual(len(verifier.batches), 1)
        self.assertTrue(any(
            event["type"] == "search_blocked_infrastructure" for event in result["events"]
        ))

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

    def test_small_model_mode_uses_compact_prompt_and_keeps_critic(self):
        provider = CapturingProvider([
            {"candidates": [{"patch": "bad", "rationale": "first"}]},
            {"candidates": [{"patch": "good", "rationale": "second"}]},
            {
                "ordered_ids": ["search-r1-automation-1", "search-r1-direct-1"],
                "feedback": "prefer the second candidate",
            },
        ])
        config = SearchConfig(
            max_rounds=1,
            proposer_roles={"direct": "short proof", "automation": "try simp"},
            max_agent_parallelism=1,
            compact_prompts=True,
        )
        result = Orchestrator(provider, FakeBatchVerifier(), config).search(self.task())
        self.assertEqual(result["status"], "verified")
        self.assertEqual(len(result["model_call_records"]), 3)
        self.assertTrue(any(event["type"] == "critic" for event in result["events"]))
        self.assertIn("Theorem statement:", provider.prompts[0]["prompt"])
        self.assertNotIn("Run memory:", provider.prompts[0]["prompt"])
        self.assertIn("Subgoals from decomposition:", provider.prompts[0]["prompt"])
        self.assertIn("Useful prior facts:", provider.prompts[0]["prompt"])

    def test_rejects_placeholder_candidates(self):
        provider = MockProvider([{"candidates": [{"patch": "by sorry"}]}])
        verifier = FakeBatchVerifier()
        config = SearchConfig(max_rounds=1, proposer_roles={"direct": "d"}, max_model_calls=1)
        result = Orchestrator(provider, verifier, config).search(self.task())
        self.assertEqual(result["status"], "model_budget_exhausted")
        self.assertEqual(verifier.batches, [])

    def test_provider_timeouts_reduce_future_agent_parallelism(self):
        engine = Orchestrator(
            TimeoutProvider(), FakeBatchVerifier(),
            SearchConfig(max_rounds=1, proposer_roles={"direct": "d", "automation": "a"},
                         max_agent_parallelism=2),
        )
        result = engine.search(self.task())
        self.assertEqual(engine._active_agent_parallelism, 1)
        self.assertTrue(any(
            event["type"] == "model_parallelism_backoff" for event in result["events"]
        ))

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

    def test_full_process_keeps_every_agent_stage_for_structural_tasks(self):
        subgoal = {"id": "evaluate", "theorem": "theorem generated : True", "depends_on": []}
        registry = AgentRegistry({
            "direct": AgentSpec(name="direct", kind="proposer", instructions="prove",
                                tools=("candidate_submit", "lean_diagnostics"), explicit_tools=True),
            "critic": AgentSpec(name="critic", kind="critic", instructions="rank",
                                tools=("candidate_rank",), explicit_tools=True),
            "decomposer": AgentSpec(name="decomposer", kind="decomposer", instructions="review",
                                    tools=("task_decompose",), explicit_tools=True),
            "reporter": AgentSpec(name="reporter", kind="reporter", instructions="report",
                                  tools=("trace_read",), explicit_tools=True),
        })
        provider = MockProvider([
            {"subgoals": [subgoal], "rationale": "preserve trusted task"},
            {"candidates": [{"patch": "good"}]},
            {"ordered_ids": ["generated-r1-direct-1"]},
            {"summary": "verified trace only"},
        ])
        task = SearchTask.from_json({
            "id": "generated", "verification_mode": "generated_obligation",
            "preamble": "def trustedInput := 1", "theorem": "theorem generated : True",
            "module": "A", "project": "sample", "subgoals": [subgoal],
        })
        result = Orchestrator(
            provider, FakeBatchVerifier(),
            SearchConfig(max_rounds=1, max_model_calls=4, agent_registry=registry,
                         require_full_agent_process=True),
        ).search(task)
        self.assertEqual(result["status"], "verified")
        self.assertEqual(
            [record["kind"] for record in result["model_call_records"]],
            ["decomposer", "proposer", "critic", "reporter"],
        )
        self.assertEqual(result["reporter"]["summary"], "verified trace only")

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

    def test_agentic_trace_records_turns_supervisor_handoffs_and_scorecard(self):
        provider = MockProvider([
            {"candidates": [{"patch": "bad-direct"}]},
            {"candidates": [{"patch": "bad-auto"}]},
            {"ordered_ids": ["search-r1-direct-1", "search-r1-automation-1"]},
        ])
        verifier = FakeBatchVerifier()
        config = SearchConfig(
            max_rounds=1,
            proposer_roles={"direct": "d", "automation": "a"},
            max_agent_parallelism=2,
        )
        result = Orchestrator(provider, verifier, config).search(self.task())
        self.assertEqual(result["status"], "exhausted")
        self.assertGreaterEqual(len(result["agent_turns"]), 2)
        self.assertTrue(result["supervisor_decisions"])
        self.assertTrue(any(event["type"] == "handoff_created" for event in result["events"]))
        self.assertIn("direct", result["agent_scorecard"])
        self.assertGreaterEqual(result["agent_scorecard"]["direct"]["candidate_count"], 1)
        self.assertIn("model_call_records", result)

    def test_resume_accepts_prior_handoff_as_next_turn_input(self):
        first = Orchestrator(
            MockProvider([{"candidates": [{"patch": "bad"}]}]),
            FakeBatchVerifier(),
            SearchConfig(max_rounds=1, proposer_roles={"first": "try", "second": "repair"}),
        ).search(self.task())
        self.assertTrue(first["handoffs"])
        second = Orchestrator(
            MockProvider([{"candidates": [{"patch": "good"}]}, {"candidates": []}]),
            FakeBatchVerifier(),
            SearchConfig(max_rounds=1, proposer_roles={"first": "try", "second": "repair"}),
        ).search(self.task(), resume=first)
        received = [
            turn for turn in second["agent_turns"]
            if turn.get("received_handoff_id")
        ]
        self.assertTrue(received)
        self.assertTrue(second["handoff_receipts"])
        self.assertTrue(second["handoff_receipts"][0]["accepted"])

    def test_subgoal_dag_is_visible_to_agents_and_supervisor(self):
        provider = CapturingProvider([
            {"candidates": [{"patch": "good"}]},
        ])
        verifier = FakeBatchVerifier()
        config = SearchConfig(max_rounds=1, proposer_roles={"direct": "d"})
        task = SearchTask.from_json({
            "id": "decomposed", "target": "A.t",
            "theorem": "theorem t : True", "module": "A", "project": "sample",
            "subgoals": [
                {"id": "lemma-a", "theorem": "theorem a : True"},
                {"id": "lemma-b", "theorem": "theorem b : True", "depends_on": ["lemma-a"]},
            ],
        })
        result = Orchestrator(provider, verifier, config).search(task)
        self.assertEqual(result["status"], "verified")
        self.assertIn("lemma-a", provider.prompts[0]["prompt"])
        self.assertEqual(
            result["supervisor_decisions"][0]["budget_state"]["subgoal_count"], 2
        )

    def test_structured_registry_decomposer_memory_and_replay_trace(self):
        registry = AgentRegistry({
            "direct": AgentSpec(
                name="direct", kind="proposer", instructions="try exact",
                tools=("lean_diagnostics", "frontier_read", "candidate_submit"),
                max_candidates=1, explicit_tools=True,
            ),
            "decomposer": AgentSpec(
                name="decomposer", kind="decomposer", instructions="split goals",
                tools=("task_decompose", "policy_read"), explicit_tools=True,
            ),
            "critic": AgentSpec(
                name="critic", kind="critic", instructions="rank",
                tools=("candidate_rank", "frontier_read"), explicit_tools=True,
            ),
        })
        provider = CapturingProvider([
            {
                "subgoals": [{"id": "claim-a", "theorem": "theorem a : True"}],
                "rationale": "root theorem has one formal obligation",
            },
            {"candidates": [{"patch": "good", "rationale": "done"}]},
        ])
        result = Orchestrator(
            provider, FakeBatchVerifier(),
            SearchConfig(max_rounds=1, agent_registry=registry),
        ).search(self.task())
        self.assertEqual(result["status"], "verified")
        self.assertEqual(result["task"]["subgoals"][0]["id"], "claim-a")
        self.assertIn("claim-a", provider.prompts[1]["prompt"])
        self.assertIn("memory", result)
        self.assertEqual(len(result["model_call_records"]), 2)
        replayed = replay_search_result(result)
        self.assertIn("MODEL CALLS", replayed)
        self.assertIn("decomposition_completed", replayed)

    def test_structured_tool_permissions_are_enforced(self):
        strict = AgentSpec(
            name="strict", kind="proposer", instructions="try",
            tools=("frontier_read",), explicit_tools=True,
        )
        with self.assertRaises(RuntimeError):
            PermissionPolicy().require(strict, "candidate_submit")

    def test_provider_router_uses_agent_model_route(self):
        registry = AgentRegistry({
            "direct": AgentSpec(
                name="direct", kind="proposer", instructions="try",
                model="alternate",
                tools=("lean_diagnostics", "frontier_read", "candidate_submit"),
                explicit_tools=True,
            ),
        })
        default_provider = MockProvider([{"candidates": [{"patch": "bad"}]}])
        routed_provider = MockProvider([{"candidates": [{"patch": "good"}]}])
        result = Orchestrator(
            default_provider,
            FakeBatchVerifier(),
            SearchConfig(max_rounds=1, agent_registry=registry),
            provider_router=ProviderRouter(
                default_provider,
                {"alternate": routed_provider},
            ),
        ).search(self.task())
        self.assertEqual(result["status"], "verified")
        self.assertEqual(result["model_call_records"][0]["model"], "alternate")

    def test_provider_routes_file_loads_model_routes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "routes.json"
            path.write_text(json.dumps({
                "fast": {"provider": "mock"},
            }), encoding="utf-8")
            routes = provider_routes_from_file(path, default_timeout_s=5)
            self.assertIn("fast", routes)
            self.assertEqual(
                routes["fast"].complete(agent="x", system="", prompt="", schema={})["candidates"][0]["patch"],
                "by rfl",
            )

    def test_run_store_persists_task_queue_and_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            store = RunStore(directory)
            state = store.create([self.task()])
            store.record_task_started(state, "search")
            artifact = store.record_task_result(state, {
                "version": 1, "id": "search", "status": "verified",
                "attempts": [], "events": [],
            })
            self.assertTrue(artifact.exists())
            loaded = store.load()
            self.assertEqual(loaded.status, "completed")
            self.assertEqual(loaded.completed[0]["task_id"], "search")

    def test_cli_pauses_and_checkpoints_after_stagnant_epoch(self):
        task = json.dumps(self.task().to_json()) + "\n"
        with tempfile.TemporaryDirectory() as directory:
            journal = pathlib.Path(directory) / "journal"
            old_stdin = sys.stdin
            old_bad = os.environ.get("FAKE_LLM_BAD")
            sys.stdin = io.StringIO(task)
            os.environ["FAKE_LLM_BAD"] = "1"
            output = io.StringIO()
            try:
                with contextlib.redirect_stdout(output):
                    status = orchestrator_main([
                        "--provider", "command",
                        "--llm-command", f"{sys.executable} {ROOT / 'tests/fake_llm.py'}",
                        "--verifier", str(ROOT / "tests/fake_verifier.py"),
                        "--max-rounds", "1", "--max-epochs", "2",
                        "--stagnation-epochs", "1", "--journal-dir", str(journal),
                    ])
            finally:
                sys.stdin = old_stdin
                if old_bad is None:
                    os.environ.pop("FAKE_LLM_BAD", None)
                else:
                    os.environ["FAKE_LLM_BAD"] = old_bad
            self.assertEqual(status, 0)
            result = json.loads(output.getvalue().splitlines()[-1])
            self.assertEqual(result["status"], "paused_stagnant")
            saved = json.loads((journal / "search.json").read_text())
            self.assertEqual(saved["status"], "paused_stagnant")

    def test_terminal_inspector_renders_search_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "search.json"
            path.write_text(json.dumps({
                "version": 1, "id": "search", "status": "verified",
                "model_calls": 1, "unique_candidates": 1, "rounds_used": 1,
                "task": self.task().to_json(),
                "supervisor_decisions": [],
                "agent_turns": [],
                "attempts": [{
                    "id": "search-r1-direct-1",
                    "agent": "direct",
                    "round": 1,
                    "status": "verified",
                    "diagnostics": "",
                }],
            }), encoding="utf-8")
            rendered = render_plain(build_search_inspector(path), width=88)
            self.assertIn("SEARCH", rendered)
            self.assertIn("LEAN DIAGNOSTICS", rendered)

    def test_terminal_inspector_labels_handoffs_as_routing(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "search.json"
            path.write_text(json.dumps({
                "version": 1, "id": "search", "status": "exhausted",
                "model_calls": 1, "unique_candidates": 1, "rounds_used": 1,
                "task": self.task().to_json(),
                "supervisor_decisions": [],
                "agent_turns": [{
                    "agent": "direct",
                    "round": 1,
                    "action": "propose_proof_patch",
                    "status": "completed",
                    "output_summary": "accepted 1 candidate(s)",
                }],
                "handoffs": [{
                    "id": "handoff-r1-1",
                    "round": 1,
                    "from_agent": "direct",
                    "to_agent": "structural",
                    "node_id": "search-r1-direct-1",
                    "reason": "share candidate",
                    "state_summary": "candidate available",
                    "accepted": False,
                }],
                "handoff_receipts": [],
                "attempts": [],
            }), encoding="utf-8")
            rendered = render_plain(build_search_inspector(path), width=88)
            self.assertIn("ROUTING HANDOFFS", rendered)
            self.assertIn("[offered]", rendered)
            self.assertIn("proposed 1 candidate(s)", rendered)
            self.assertNotIn("accepted=False", rendered)

    def test_run_inspector_shows_selected_past_task(self):
        data = {
            "inspector_kind": "run",
            "state": {
                "run_id": "run",
                "status": "running",
                "tasks": [],
                "completed": [],
                "blocked": [],
            },
            "events": [],
            "selected_artifact_index": 0,
            "artifacts": [
                {
                    "version": 1,
                    "id": "first-task",
                    "status": "verified",
                    "model_calls": 1,
                    "unique_candidates": 1,
                    "rounds_used": 1,
                    "task": self.task().to_json(),
                    "supervisor_decisions": [],
                    "agent_turns": [],
                    "attempts": [],
                },
                {
                    "version": 1,
                    "id": "second-task",
                    "status": "exhausted",
                    "model_calls": 1,
                    "unique_candidates": 0,
                    "rounds_used": 1,
                    "task": self.task().to_json(),
                    "supervisor_decisions": [],
                    "agent_turns": [],
                    "attempts": [],
                },
            ],
        }
        rendered = render_plain(data, width=88)
        self.assertIn("PAST TASK  1/2", rendered)
        self.assertIn("SEARCH  first-task", rendered)
        self.assertNotIn("SEARCH  second-task", rendered)

    def test_terminal_inspector_marks_missing_lean_build_as_infrastructure(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "search.json"
            path.write_text(json.dumps({
                "version": 1, "id": "search", "status": "exhausted",
                "model_calls": 1, "unique_candidates": 1, "rounds_used": 1,
                "task": self.task().to_json(),
                "supervisor_decisions": [],
                "agent_turns": [],
                "attempts": [{
                    "id": "search-r1-direct-1",
                    "agent": "direct",
                    "round": 1,
                    "status": "project_not_built",
                    "diagnostics": "Lean project is not built",
                }],
            }), encoding="utf-8")
            rendered = render_plain(build_search_inspector(path), width=88)
            self.assertIn("infrastructure issue", rendered)
            self.assertIn("Lean project is not built", rendered)


if __name__ == "__main__":
    unittest.main()
