from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .hypothesis import draft_hypothesis, policy_coverage
from .policy import Policy
from .report import sanity_report


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY = ROOT / "policies/dft-architecture-v1.json"


HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Proof Vibe sanity check</title>
  <style>
    body { font-family: system-ui, sans-serif; max-width: 980px; margin: 2rem auto; padding: 0 1rem; line-height: 1.45; }
    textarea { width: 100%; min-height: 160px; font: inherit; }
    input, button { font: inherit; padding: 0.45rem; }
    button { cursor: pointer; }
    pre { background: #111827; color: #e5e7eb; padding: 1rem; overflow: auto; border-radius: 8px; }
    .grid { display: grid; gap: 1rem; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); }
    .card { border: 1px solid #d1d5db; border-radius: 8px; padding: 1rem; }
    .muted { color: #4b5563; }
  </style>
</head>
<body>
  <h1>Proof Vibe sanity check</h1>
  <p class="muted">Local prototype. It extracts reviewable claims, identifies missing assumptions, and reports what the selected Lean-backed policy can check.</p>
  <label>Model or hypothesis id<br><input id="modelId" value="demo-hypothesis"></label>
  <p><label>Physics hypothesis<br><textarea id="hypothesis">A DFT architecture with an XC derivative discontinuity, nonlocal spatial coupling, and a self-adjoint learned self-energy operator.</textarea></label></p>
  <button id="run">Draft sanity check</button>
  <button id="coverage">Show coverage</button>
  <div class="grid">
    <div class="card"><h2>Summary</h2><pre id="summary">{}</pre></div>
    <div class="card"><h2>Clarifications</h2><pre id="questions">[]</pre></div>
  </div>
  <h2>Full JSON</h2>
  <pre id="result">{}</pre>
<script>
async function post(path, body) {
  const response = await fetch(path, {method: "POST", headers: {"content-type": "application/json"}, body: JSON.stringify(body)});
  return await response.json();
}
async function get(path) {
  const response = await fetch(path);
  return await response.json();
}
document.getElementById("run").onclick = async () => {
  const data = await post("/api/hypothesis", {
    model_id: document.getElementById("modelId").value,
    hypothesis: document.getElementById("hypothesis").value
  });
  document.getElementById("summary").textContent = JSON.stringify({status: data.report.status, summary: data.report.summary}, null, 2);
  document.getElementById("questions").textContent = JSON.stringify(data.report.clarification_questions, null, 2);
  document.getElementById("result").textContent = JSON.stringify(data, null, 2);
};
document.getElementById("coverage").onclick = async () => {
  const data = await get("/api/coverage");
  document.getElementById("summary").textContent = JSON.stringify({policy: data.policy, supported_claims: data.supported_claims.length}, null, 2);
  document.getElementById("questions").textContent = JSON.stringify(data.not_supported, null, 2);
  document.getElementById("result").textContent = JSON.stringify(data, null, 2);
};
</script>
</body>
</html>
"""


def handler(policy: Policy):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("content-type", content_type)
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, value: dict[str, Any]) -> None:
            self._send(
                status,
                json.dumps(value, indent=2, sort_keys=True).encode("utf-8"),
                "application/json; charset=utf-8",
            )

        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/":
                self._send(200, HTML.encode("utf-8"), "text/html; charset=utf-8")
            elif self.path == "/api/coverage":
                self._json(200, policy_coverage(policy))
            else:
                self._json(404, {"status": "not_found"})

        def do_POST(self) -> None:  # noqa: N802
            try:
                length = int(self.headers.get("content-length", "0"))
                value = json.loads(self.rfile.read(length).decode("utf-8"))
                if self.path != "/api/hypothesis":
                    self._json(404, {"status": "not_found"})
                    return
                manifest = draft_hypothesis(
                    model_id=str(value.get("model_id") or "anonymous-hypothesis"),
                    hypothesis=str(value.get("hypothesis") or ""),
                    policy=policy,
                )
                self._json(200, {
                    "status": "draft",
                    "manifest": manifest.value,
                    "report": sanity_report(manifest=manifest, policy=policy),
                })
            except Exception as error:
                self._json(400, {
                    "status": "invalid",
                    "diagnostics": f"{type(error).__name__}: {error}",
                })

        def log_message(self, format: str, *args: Any) -> None:
            return

    return Handler


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Local Proof Vibe web UI")
    parser.add_argument("--policy", default=str(DEFAULT_POLICY))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    options = parser.parse_args(argv)
    policy = Policy.load(options.policy)
    server = ThreadingHTTPServer((options.host, options.port), handler(policy))
    print(f"Proof Vibe web UI listening on http://{options.host}:{options.port}")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
