#!/usr/bin/env python3
"""OpenRouter free-model adapter for Noether.

Reads the Noether provider envelope from stdin and writes one JSON object to
stdout. Configure with:

  OPENROUTER_API_KEY=...
  OPENROUTER_MODEL=openrouter/free  # optional, default stays on free routing

This adapter is for demos and low-volume experiments. Free models have rate
limits and availability constraints.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any


API_URL = "https://openrouter.ai/api/v1/chat/completions"


def _extract_json_object(text: str) -> dict[str, Any]:
    text = text.strip()
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("model response did not contain a JSON object")
        value = json.loads(text[start:end + 1])
    if not isinstance(value, dict):
        raise ValueError("model response JSON must be an object")
    return value


def complete(request: dict[str, Any]) -> dict[str, Any]:
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is required")
    model = os.environ.get("OPENROUTER_MODEL", "openrouter/free")
    system = str(request.get("system", ""))
    prompt = str(request.get("prompt", ""))
    schema = request.get("schema", {})
    agent = str(request.get("agent", "agent"))
    body = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    system
                    + "\n\nReturn only valid JSON matching this schema:\n"
                    + json.dumps(schema, ensure_ascii=False)
                ),
            },
            {
                "role": "user",
                "content": f"Noether agent: {agent}\n\n{prompt}",
            },
        ],
        "temperature": 0.1 if agent == "critic" else 0.2,
        "max_tokens": 1800,
    }
    http_request = urllib.request.Request(
        API_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "HTTP-Referer": "https://github.com/AnujJha27/Noether",
            "X-Title": "Noether",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(http_request, timeout=120) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenRouter request failed: HTTP {error.code}: {detail}") from error
    except (urllib.error.URLError, TimeoutError) as error:
        raise RuntimeError(f"OpenRouter request failed: {error}") from error
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise RuntimeError("OpenRouter response did not contain choices")
    message = choices[0].get("message")
    if not isinstance(message, dict):
        raise RuntimeError("OpenRouter choice did not contain a message")
    content = message.get("content")
    if not isinstance(content, str):
        raise RuntimeError("OpenRouter message content was not text")
    return _extract_json_object(content)


def main() -> int:
    try:
        request = json.load(sys.stdin)
        if not isinstance(request, dict):
            raise ValueError("request must be a JSON object")
        print(json.dumps(complete(request), ensure_ascii=False))
        return 0
    except Exception as error:
        print(f"{type(error).__name__}: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
