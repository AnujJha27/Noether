from __future__ import annotations

import argparse
import json
import shlex
import sys
from pathlib import Path

from .engine import DEFAULT_ROLES_FILE, Orchestrator, SearchConfig, load_roles
from .models import SearchTask
from .providers import CommandProvider, HttpProvider, MockProvider, token_from_environment
from .verifier import VerifierClient


def arguments(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Multi-agent Lean proof-search orchestrator")
    parser.add_argument("--provider", choices=("command", "http", "mock"), required=True)
    parser.add_argument("--llm-command", help="quoted adapter command for --provider command")
    parser.add_argument("--llm-url", help="gateway endpoint for --provider http")
    parser.add_argument("--provider-timeout-s", type=int, default=120)
    parser.add_argument("--verifier", default="./build/proof-search")
    parser.add_argument("--max-rounds", type=int, default=3)
    parser.add_argument("--candidates-per-agent", type=int, default=2)
    parser.add_argument("--max-model-calls", type=int, default=20)
    parser.add_argument("--max-candidates", type=int, default=24)
    parser.add_argument("--agent-parallelism", type=int, default=3)
    parser.add_argument("--verify-parallelism", type=int, default=4)
    parser.add_argument("--roles-file", default=str(DEFAULT_ROLES_FILE))
    parser.add_argument("--journal-dir")
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


def main(argv: list[str] | None = None) -> int:
    try:
        options = arguments(argv)
        provider = provider_from_args(options)
        config = SearchConfig(
            max_rounds=options.max_rounds,
            candidates_per_agent=options.candidates_per_agent,
            max_model_calls=options.max_model_calls,
            max_total_candidates=options.max_candidates,
            max_agent_parallelism=options.agent_parallelism,
            max_parallel_verifications=options.verify_parallelism,
            proposer_roles=load_roles(options.roles_file),
        )
    except (ValueError, SystemExit) as error:
        if isinstance(error, SystemExit):
            raise
        print(f"configuration error: {error}", file=sys.stderr)
        return 2
    verifier = VerifierClient([options.verifier])
    try:
        verifier.start()
        engine = Orchestrator(provider, verifier, config)
        for line in sys.stdin:
            try:
                value = json.loads(line)
                task = SearchTask.from_json(value)
                resume = None
                if options.resume_journal and options.journal_dir:
                    checkpoint = Path(options.journal_dir) / f"{task.id}.json"
                    if checkpoint.exists():
                        resume = json.loads(checkpoint.read_text(encoding="utf-8"))
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
            except (json.JSONDecodeError, ValueError) as error:
                response = {"version": 1, "id": "", "status": "invalid_task",
                            "diagnostics": str(error)}
            print(json.dumps(response, separators=(",", ":")), flush=True)
    except Exception as error:
        print(f"orchestrator failure: {error}", file=sys.stderr)
        return 1
    finally:
        verifier.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
