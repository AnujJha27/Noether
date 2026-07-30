from __future__ import annotations

import argparse
import json
import shlex
import sys
from pathlib import Path
from typing import Any

from .agents import load_agent_registry
from .engine import DEFAULT_AGENTS_FILE, Orchestrator, SearchConfig
from .models import SearchTask
from .provider_router import ProviderRouter
from .providers import CommandProvider, HttpProvider, MockProvider, token_from_environment
from .run_manager import RunStore
from .verifier import VerifierClient


def arguments(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Multi-agent Lean proof-search orchestrator")
    parser.add_argument("--provider", choices=("command", "http", "mock"), required=True)
    parser.add_argument("--llm-command", help="quoted adapter command for --provider command")
    parser.add_argument("--llm-url", help="gateway endpoint for --provider http")
    parser.add_argument("--provider-timeout-s", type=int, default=120)
    parser.add_argument(
        "--provider-routes",
        help="JSON object mapping agent model names to provider specs",
    )
    parser.add_argument("--verifier", default="./build/proof-search")
    parser.add_argument("--max-rounds", type=int, default=3)
    parser.add_argument("--candidates-per-agent", type=int, default=2)
    parser.add_argument("--max-model-calls", type=int, default=20)
    parser.add_argument("--max-candidates", type=int, default=24)
    parser.add_argument("--agent-parallelism", type=int, default=3)
    parser.add_argument("--verify-parallelism", type=int, default=4)
    parser.add_argument("--frontier-width", type=int, default=6)
    parser.add_argument("--agents-file", help="structured agent registry JSON")
    parser.add_argument("--roles-file", help="legacy alias for --agents-file")
    parser.add_argument("--journal-dir")
    parser.add_argument("--run-dir", help="durable multi-task run state directory")
    parser.add_argument("--resume-journal", action="store_true")
    return parser.parse_args(argv)


def provider_from_args(options: argparse.Namespace):
    if options.provider == "mock":
        return MockProvider()
    if options.provider == "command":
        if not options.llm_command:
            raise ValueError("--llm-command is required for the command provider")
        return CommandProvider(shlex.split(options.llm_command), options.provider_timeout_s)
    if not options.llm_url:
        raise ValueError("--llm-url is required for the HTTP provider")
    return HttpProvider(options.llm_url, token_from_environment(), options.provider_timeout_s)


def provider_from_route_spec(spec: dict[str, Any], *, default_timeout_s: int):
    provider = spec.get("provider")
    timeout_s = spec.get("timeout_s", default_timeout_s)
    if not isinstance(timeout_s, int) or isinstance(timeout_s, bool) or timeout_s <= 0:
        raise ValueError("provider route timeout_s must be a positive integer")
    if provider == "mock":
        return MockProvider()
    if provider == "command":
        command = spec.get("command")
        if isinstance(command, str):
            command_value = shlex.split(command)
        elif isinstance(command, list) and all(isinstance(item, str) for item in command):
            command_value = command
        else:
            raise ValueError("command provider routes require command string or string array")
        return CommandProvider(command_value, timeout_s)
    if provider == "http":
        url = spec.get("url")
        if not isinstance(url, str) or not url:
            raise ValueError("http provider routes require url")
        token_env = spec.get("token_env", "LLM_API_TOKEN")
        if token_env is not None and (not isinstance(token_env, str) or not token_env):
            raise ValueError("token_env must be a non-empty string or null")
        token = token_from_environment() if token_env == "LLM_API_TOKEN" else None
        if token_env not in {None, "LLM_API_TOKEN"}:
            import os
            token = os.environ.get(token_env)
        return HttpProvider(url, token, timeout_s)
    raise ValueError("provider route provider must be one of: command, http, mock")


def provider_routes_from_file(path: str | Path, *, default_timeout_s: int) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("provider routes file must contain a JSON object")
    routes: dict[str, Any] = {}
    for model, spec in value.items():
        if not isinstance(model, str) or not model:
            raise ValueError("provider route model names must be non-empty strings")
        if not isinstance(spec, dict):
            raise ValueError(f"provider route {model!r} must be a JSON object")
        routes[model] = provider_from_route_spec(spec, default_timeout_s=default_timeout_s)
    return routes


def main(argv: list[str] | None = None) -> int:
    try:
        options = arguments(argv)
        provider = provider_from_args(options)
        route_providers = (
            provider_routes_from_file(
                options.provider_routes,
                default_timeout_s=options.provider_timeout_s,
            )
            if options.provider_routes else None
        )
        agents_file = options.agents_file or options.roles_file or str(DEFAULT_AGENTS_FILE)
        registry = load_agent_registry(agents_file)
        config = SearchConfig(
            max_rounds=options.max_rounds,
            candidates_per_agent=options.candidates_per_agent,
            max_model_calls=options.max_model_calls,
            max_total_candidates=options.max_candidates,
            max_agent_parallelism=options.agent_parallelism,
            max_parallel_verifications=options.verify_parallelism,
            frontier_width=options.frontier_width,
            agent_registry=registry,
        )
    except (ValueError, SystemExit) as error:
        if isinstance(error, SystemExit):
            raise
        print(f"configuration error: {error}", file=sys.stderr)
        return 2
    verifier = VerifierClient([options.verifier])
    try:
        verifier.start()
        engine = Orchestrator(
            provider,
            verifier,
            config,
            provider_router=ProviderRouter(provider, route_providers),
        )
        parsed_tasks: list[SearchTask] = []
        invalid_responses: list[dict[str, Any]] = []
        for line in sys.stdin:
            try:
                value = json.loads(line)
                task = SearchTask.from_json(value)
                parsed_tasks.append(task)
            except (json.JSONDecodeError, ValueError) as error:
                invalid_responses.append({
                    "version": 1, "id": "", "status": "invalid_task",
                    "diagnostics": str(error),
                })
        for response in invalid_responses:
            print(json.dumps(response, separators=(",", ":")), flush=True)
        run_store = RunStore(options.run_dir) if options.run_dir else None
        run_state = run_store.create(parsed_tasks) if run_store else None
        for task in parsed_tasks:
            resume = None
            if options.resume_journal and options.journal_dir:
                checkpoint = Path(options.journal_dir) / f"{task.id}.json"
                if checkpoint.exists():
                    resume = json.loads(checkpoint.read_text(encoding="utf-8"))
            if run_store and run_state:
                run_store.record_task_started(run_state, task.id)
            response = engine.search(task, resume=resume)
            if options.journal_dir:
                journal = Path(options.journal_dir)
                journal.mkdir(parents=True, exist_ok=True)
                destination = journal / f"{task.id}.json"
                temporary = destination.with_suffix(".json.tmp")
                temporary.write_text(
                    json.dumps(response, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                temporary.replace(destination)
            if run_store and run_state:
                run_store.record_task_result(run_state, response)
            print(json.dumps(response, separators=(",", ":")), flush=True)
    except Exception as error:
        print(f"orchestrator failure: {error}", file=sys.stderr)
        return 1
    finally:
        verifier.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
