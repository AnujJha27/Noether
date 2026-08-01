from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .hypothesis import draft_hypothesis
from .manifest import ArchitectureManifest, sha256_value
from .policy import Policy
from .report import sanity_report


def read_description(value: str) -> str:
    path = Path(value)
    if path.exists():
        return path.read_text(encoding="utf-8")
    return value


def assumption_rows(manifest: ArchitectureManifest, policy: Policy) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    by_id = {
        item.get("id"): item
        for item in manifest.value.get("assumptions", [])
        if isinstance(item, dict)
    }
    trace_by_fact = {
        item.get("normalized_claim"): item
        for item in manifest.value.get("traceability", [])
        if isinstance(item, dict)
    }
    for obligation in policy.obligations:
        assumption = by_id.get(obligation.fact, {})
        fact = manifest.value.get("facts", {}).get(obligation.fact)
        value = fact.get("value") if isinstance(fact, dict) else assumption.get("value")
        evidence = fact.get("evidence", {}) if isinstance(fact, dict) else {}
        trace = trace_by_fact.get(obligation.fact, {})
        rows.append({
            "id": obligation.fact,
            "principle": obligation.description,
            "status": assumption.get("status", "needs_clarification"),
            "value": value,
            "evidence": trace.get("original_text") or evidence.get("rationale") or "",
            "confidence": assumption.get("confidence") or evidence.get("confidence") or "unknown",
            "question": next(
                (
                    item.get("question")
                    for item in manifest.value.get("clarification_questions", [])
                    if isinstance(item, dict) and item.get("fact") == obligation.fact
                ),
                None,
            ),
        })
    return rows


def _status_from_answer(answer: str) -> str:
    lowered = answer.strip().lower()
    if lowered in {"y", "yes", "confirm", "confirmed", "true"}:
        return "confirmed"
    if lowered in {"n", "no", "reject", "rejected", "false"}:
        return "rejected"
    return "unknown"


def confirm_assumptions_interactively(
    manifest: ArchitectureManifest, policy: Policy, *, input_stream: Any = sys.stdin,
    output_stream: Any = sys.stdout,
) -> None:
    facts = manifest.value.get("facts", {})
    assumptions = manifest.value.get("assumptions", [])
    if not isinstance(facts, dict) or not isinstance(assumptions, list):
        return
    print("Confirm inferred assumptions before verification.", file=output_stream)
    print("Answer y/n/u. Unknown assumptions make the verdict inconclusive.", file=output_stream)
    for item in assumptions:
        if not isinstance(item, dict):
            continue
        fact_id = item.get("id")
        if not isinstance(fact_id, str):
            continue
        value = item.get("value")
        if value is None:
            print(f"\n{fact_id}: missing", file=output_stream)
            question = item.get("question") or next(
                (
                    question.get("question")
                    for question in manifest.value.get("clarification_questions", [])
                    if isinstance(question, dict) and question.get("fact") == fact_id
                ),
                "Is this assumption satisfied?",
            )
            print(str(question), file=output_stream)
        else:
            print(f"\n{fact_id}: {json.dumps(value, sort_keys=True)}", file=output_stream)
            if item.get("confidence"):
                print(f"confidence: {item['confidence']}", file=output_stream)
        print("confirm? [y/n/u]: ", end="", file=output_stream, flush=True)
        answer = input_stream.readline()
        status = _status_from_answer(answer)
        item["status"] = status
        if status == "confirmed" and fact_id in facts:
            facts[fact_id]["evidence"]["kind"] = "user_attestation"
        elif status == "rejected" and fact_id in facts:
            value = facts[fact_id].get("value")
            if isinstance(value, dict) and "satisfied" in value:
                value["satisfied"] = False
            facts[fact_id]["evidence"]["kind"] = "user_attestation"
        elif status == "unknown" and fact_id in facts:
            facts.pop(fact_id, None)
    missing = [name for name in policy.required_facts if name not in facts]
    manifest.value["unresolved_facts"] = missing
    if missing:
        manifest.value["status"] = "draft"
    else:
        manifest.value["status"] = "confirmed"
        manifest.value["confirmed_at"] = datetime.now(timezone.utc).isoformat()
    manifest.refresh_hash()


def _extract_json_object(text: str) -> dict[str, Any]:
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("LLM response did not contain a JSON object")
        value = json.loads(text[start:end + 1])
    if not isinstance(value, dict):
        raise ValueError("LLM response JSON must be an object")
    return value


def _chat_completions(*, base_url: str, model: str, system: str, prompt: str,
                      schema: dict[str, Any], timeout_s: int) -> dict[str, Any]:
    endpoint = base_url.rstrip("/")
    if not endpoint.endswith("/chat/completions"):
        endpoint += "/chat/completions"
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system + "\n\nReturn only JSON matching:\n" + json.dumps(schema)},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.1,
        "max_tokens": int(os.environ.get("NOETHER_OPENAI_MAX_TOKENS", "4096")),
    }
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    api_key = os.environ.get("NOETHER_OPENAI_API_KEY")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(
        endpoint, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"assumption extraction failed: HTTP {error.code}: {detail}") from error
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise RuntimeError("assumption extraction response had no choices")
    message = choices[0].get("message")
    if not isinstance(message, dict) or not isinstance(message.get("content"), str):
        raise RuntimeError("assumption extraction response had no text content")
    return _extract_json_object(message["content"])


def draft_with_llm(
    *, model_id: str, description: str, policy: Policy, base_url: str, model: str,
    timeout_s: int,
) -> ArchitectureManifest:
    schema = {
        "type": "object",
        "properties": {
            "facts": {
                "type": "object",
                "description": "Only include facts explicitly supported by the description.",
            },
            "evidence": {"type": "object"},
            "questions": {"type": "array"},
        },
        "required": ["facts", "evidence", "questions"],
    }
    fact_schema = {
        obligation.fact: obligation.value_schema
        for obligation in policy.obligations
    }
    prompt = (
        "Extract draft DFT physics assumptions from the model description. "
        "Do not invent unstated assumptions. Use only these fact names and schemas:\n"
        f"{json.dumps(fact_schema, indent=2)}\n\n"
        "Description:\n"
        f"{description}"
    )
    result = _chat_completions(
        base_url=base_url,
        model=model,
        timeout_s=timeout_s,
        system="You extract provisional assumptions for Lean-backed DFT model assessment.",
        prompt=prompt,
        schema=schema,
    )
    proposed = result.get("facts", {})
    if not isinstance(proposed, dict):
        proposed = {}
    allowed = set(policy.required_facts)
    proposed = {key: value for key, value in proposed.items() if key in allowed}
    manifest = ArchitectureManifest.english_draft(
        model_id=model_id, description=description, policy=policy, proposed_facts=proposed
    )
    source_hash = manifest.value["source"]["description_sha256"]
    evidence = result.get("evidence", {}) if isinstance(result.get("evidence"), dict) else {}
    assumptions = []
    traceability = []
    for fact, value in proposed.items():
        ev = evidence.get(fact, {}) if isinstance(evidence.get(fact), dict) else {}
        manifest.value["facts"][fact]["evidence"] = {
            "kind": "unconfirmed_interpretation",
            "description_sha256": source_hash,
            "confidence": ev.get("confidence", "medium"),
            "rationale": ev.get("rationale", "LLM extracted this assumption from the description."),
        }
        assumptions.append({
            "id": fact,
            "statement": policy.obligation_for_fact(fact).description,
            "value": value,
            "source": "llm_interpretation",
            "status": "needs_user_confirmation",
            "confidence": ev.get("confidence", "medium"),
        })
        traceability.append({
            "original_text": ev.get("quote", ""),
            "normalized_claim": fact,
            "draft_value": value,
            "evidence_kind": "unconfirmed_interpretation",
            "confirmation_required": True,
        })
    questions = []
    for obligation in policy.obligations:
        if obligation.required and obligation.fact not in proposed:
            questions.append({
                "fact": obligation.fact,
                "question": f"Does the model satisfy: {obligation.description}",
                "reason": "The LLM did not find explicit support in the description.",
            })
            assumptions.append({
                "id": obligation.fact,
                "statement": obligation.description,
                "source": "missing",
                "status": "needs_clarification",
            })
    manifest.value["hypothesis_intake"] = {
        "status": "draft_requires_review",
        "extractor": f"llm:{model}",
        "extracted_claim_count": len(proposed),
        "ambiguous_or_missing_count": len(questions),
    }
    manifest.value["assumptions"] = assumptions
    manifest.value["clarification_questions"] = questions
    manifest.value["traceability"] = traceability
    manifest.refresh_hash()
    return manifest


def assessment_payload(
    *, manifest: ArchitectureManifest, policy: Policy,
    proof_results: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    report = sanity_report(manifest=manifest, policy=policy, proof_results=proof_results)
    if report["status"] == "consistent_with_policy":
        verdict = "physically_sound"
    elif report["status"] == "violates_required_principle":
        verdict = "not_sound"
    else:
        verdict = "inconclusive"
    next_actions: list[str] = []
    if any(row["status"] in {"needs_clarification", "unknown"} for row in assumption_rows(manifest, policy)):
        next_actions.append("Confirm or mark unknown assumptions before proof search.")
    if report["status"] in {"proof_required", "formalization_gap"}:
        next_actions.append("Run proof search for generated obligations when assumptions are confirmed.")
    if not next_actions:
        next_actions.append("Open the structured proof details if you need to audit the decision.")
    payload = {
        "assessment_schema_version": 1,
        "status": "complete",
        "verdict": verdict,
        "summary": report["summary"],
        "model_id": manifest.value.get("model_id"),
        "policy": report["policy"],
        "assumptions": assumption_rows(manifest, policy),
        "checks": [
            {
                "id": item["fact"],
                "status": item["category"],
                "principle": item["principle"],
                "reason": item["reason"],
                "theorem": item.get("lean_theorem"),
                "proof_status": item.get("proof_status"),
            }
            for item in report["obligations"]
        ],
        "next_actions": next_actions,
        "artifacts": {
            "manifest": "manifest.json",
            "report": "report.json",
        },
    }
    payload["assessment_sha256"] = sha256_value(payload)
    return payload

