#!/usr/bin/env python3
"""OpenAI-compatible chat-completions adapter for Noether.

Works with many hosted local/cluster inference servers that expose:

  POST {NOETHER_OPENAI_BASE_URL}/chat/completions

or, when the base URL already ends in `/chat/completions`, exactly that URL.

Environment:

  NOETHER_OPENAI_BASE_URL=http://cluster-host:8000/v1
  NOETHER_OPENAI_MODEL=local-coder
  NOETHER_OPENAI_API_KEY=...          # optional for local servers
  NOETHER_OPENAI_MAX_TOKENS=1800      # optional
  NOETHER_OPENAI_TIMEOUT_S=180        # optional
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any


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


def endpoint_from_base(base_url: str) -> str:
    base_url = base_url.rstrip("/")
    if base_url.endswith("/chat/completions"):
        return base_url
    return base_url + "/chat/completions"


def complete(request: dict[str, Any]) -> dict[str, Any]:
    base_url = os.environ.get("NOETHER_OPENAI_BASE_URL")
    model = os.environ.get("NOETHER_OPENAI_MODEL")
    if not base_url:
        raise RuntimeError("NOETHER_OPENAI_BASE_URL is required")
    if not model:
        raise RuntimeError("NOETHER_OPENAI_MODEL is required")
    agent = str(request.get("agent", "agent"))
    schema = request.get("schema", {})
    max_tokens = int(os.environ.get("NOETHER_OPENAI_MAX_TOKENS", "1800"))
    timeout_s = int(os.environ.get("NOETHER_OPENAI_TIMEOUT_S", "180"))
    body = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    str(request.get("system", ""))
                    + "\n\nReturn only valid JSON matching this schema:\n"
                    + json.dumps(schema, ensure_ascii=False)
                ),
            },
            {
                "role": "user",
                "content": f"Noether agent: {agent}\n\n{request.get('prompt', '')}",
            },
        ],
        "temperature": 0.1 if agent == "critic" else 0.2,
        "max_tokens": max_tokens,
    }
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    api_key = os.environ.get("NOETHER_OPENAI_API_KEY")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    http_request = urllib.request.Request(
        endpoint_from_base(base_url),
        data=json.dumps(body).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(http_request, timeout=timeout_s) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"chat-completions request failed: HTTP {error.code}: {detail}") from error
    except (urllib.error.URLError, TimeoutError) as error:
        raise RuntimeError(f"chat-completions request failed: {error}") from error
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise RuntimeError("chat-completions response did not contain choices")
    message = choices[0].get("message")
    if not isinstance(message, dict):
        raise RuntimeError("chat-completions choice did not contain a message")
    content = message.get("content")
    if not isinstance(content, str):
        raise RuntimeError("chat-completions message content was not text")
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
