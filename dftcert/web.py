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
    :root {
      color-scheme: light;
      --bg: #f5f7fb;
      --panel: #ffffff;
      --panel-soft: #f8fafc;
      --ink: #172033;
      --muted: #667085;
      --line: #d9e1ee;
      --brand: #335cff;
      --brand-dark: #243fd1;
      --good: #047857;
      --warn: #b45309;
      --bad: #b42318;
      --gap: #6d28d9;
      --shadow: 0 18px 48px rgba(16, 24, 40, 0.10);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      color: var(--ink);
      background:
        radial-gradient(circle at top left, rgba(51, 92, 255, 0.16), transparent 34rem),
        linear-gradient(180deg, #fbfcff 0%, var(--bg) 45%, #eef3fb 100%);
      line-height: 1.45;
    }
    header {
      max-width: 1180px;
      margin: 0 auto;
      padding: 2.8rem 1.25rem 1.2rem;
    }
    main {
      max-width: 1180px;
      margin: 0 auto;
      padding: 0 1.25rem 3rem;
    }
    h1 {
      margin: 0;
      font-size: clamp(2.3rem, 5vw, 4.8rem);
      line-height: 0.95;
      letter-spacing: -0.065em;
    }
    h2, h3 { margin: 0; letter-spacing: -0.02em; }
    p { margin: 0; }
    .hero {
      display: grid;
      grid-template-columns: minmax(0, 1.25fr) minmax(280px, 0.75fr);
      gap: 1rem;
      align-items: end;
    }
    .subtitle {
      margin-top: 1rem;
      max-width: 760px;
      color: var(--muted);
      font-size: 1.08rem;
    }
    .pill-row { display: flex; flex-wrap: wrap; gap: 0.5rem; margin-top: 1.2rem; }
    .pill {
      display: inline-flex;
      align-items: center;
      gap: 0.4rem;
      padding: 0.42rem 0.72rem;
      border: 1px solid var(--line);
      border-radius: 999px;
      background: rgba(255,255,255,0.78);
      color: #344054;
      font-size: 0.86rem;
      font-weight: 650;
      backdrop-filter: blur(10px);
    }
    .layout {
      display: grid;
      grid-template-columns: minmax(320px, 0.9fr) minmax(0, 1.45fr);
      gap: 1rem;
      align-items: start;
    }
    .panel {
      background: rgba(255,255,255,0.86);
      border: 1px solid rgba(217,225,238,0.9);
      border-radius: 24px;
      box-shadow: var(--shadow);
      backdrop-filter: blur(12px);
    }
    .composer { padding: 1.1rem; position: sticky; top: 1rem; }
    .field { margin-top: 1rem; }
    label {
      display: block;
      margin-bottom: 0.42rem;
      color: #344054;
      font-size: 0.86rem;
      font-weight: 750;
    }
    input, textarea {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 16px;
      background: #fff;
      color: var(--ink);
      font: inherit;
      outline: none;
      transition: border-color 140ms ease, box-shadow 140ms ease;
    }
    input { padding: 0.82rem 0.9rem; }
    textarea {
      min-height: 230px;
      resize: vertical;
      padding: 0.95rem;
    }
    input:focus, textarea:focus {
      border-color: rgba(51, 92, 255, 0.7);
      box-shadow: 0 0 0 4px rgba(51, 92, 255, 0.12);
    }
    .actions { display: flex; gap: 0.6rem; flex-wrap: wrap; margin-top: 1rem; }
    button {
      border: 0;
      border-radius: 14px;
      padding: 0.78rem 0.95rem;
      font: inherit;
      font-weight: 800;
      cursor: pointer;
      transition: transform 120ms ease, box-shadow 120ms ease, background 120ms ease;
    }
    button:hover { transform: translateY(-1px); }
    .primary {
      color: white;
      background: linear-gradient(135deg, var(--brand), var(--brand-dark));
      box-shadow: 0 10px 24px rgba(51, 92, 255, 0.25);
    }
    .secondary {
      color: #1d2939;
      background: #edf2ff;
      border: 1px solid #d7e0ff;
    }
    .examples {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 0.5rem;
      margin-top: 1rem;
    }
    .example {
      text-align: left;
      padding: 0.65rem;
      background: var(--panel-soft);
      border: 1px solid var(--line);
      color: #344054;
      font-size: 0.82rem;
      font-weight: 750;
    }
    .results { display: grid; gap: 1rem; }
    .summary {
      padding: 1.1rem;
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 1rem;
      align-items: center;
    }
    .status-badge {
      display: inline-flex;
      justify-self: start;
      align-items: center;
      gap: 0.45rem;
      padding: 0.5rem 0.75rem;
      border-radius: 999px;
      font-size: 0.82rem;
      font-weight: 850;
      text-transform: uppercase;
      letter-spacing: 0.035em;
      background: #eef4ff;
      color: var(--brand-dark);
    }
    .status-badge.good { background: #ecfdf3; color: var(--good); }
    .status-badge.warn { background: #fffaeb; color: var(--warn); }
    .status-badge.bad { background: #fef3f2; color: var(--bad); }
    .status-badge.gap { background: #f4f3ff; color: var(--gap); }
    .summary-text { color: var(--muted); margin-top: 0.45rem; }
    .metric-row {
      display: flex;
      gap: 0.6rem;
      flex-wrap: wrap;
      justify-content: end;
    }
    .metric {
      min-width: 112px;
      padding: 0.65rem 0.8rem;
      border-radius: 16px;
      background: var(--panel-soft);
      border: 1px solid var(--line);
      text-align: right;
    }
    .metric strong { display: block; font-size: 1.25rem; }
    .metric span { color: var(--muted); font-size: 0.76rem; font-weight: 750; }
    .section { padding: 1.1rem; }
    .section + .section { border-top: 1px solid var(--line); }
    .section-head {
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      gap: 1rem;
      margin-bottom: 0.85rem;
    }
    .section-head p { color: var(--muted); font-size: 0.9rem; }
    .cards { display: grid; gap: 0.75rem; }
    .obligation {
      border: 1px solid var(--line);
      border-radius: 18px;
      background: #fff;
      padding: 0.9rem;
    }
    .obligation-top {
      display: flex;
      justify-content: space-between;
      gap: 0.75rem;
      align-items: start;
    }
    .tag {
      display: inline-flex;
      padding: 0.25rem 0.5rem;
      border-radius: 999px;
      background: #eef2f6;
      color: #475467;
      font-size: 0.74rem;
      font-weight: 800;
      white-space: nowrap;
    }
    .tag.good { background: #ecfdf3; color: var(--good); }
    .tag.warn { background: #fffaeb; color: var(--warn); }
    .tag.bad { background: #fef3f2; color: var(--bad); }
    .tag.gap { background: #f4f3ff; color: var(--gap); }
    .principle { margin-top: 0.35rem; color: #475467; }
    .detail-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
      gap: 0.5rem;
      margin-top: 0.75rem;
    }
    .mini {
      padding: 0.65rem;
      border-radius: 14px;
      background: var(--panel-soft);
      border: 1px solid #e7edf6;
      min-width: 0;
    }
    .mini b { display: block; font-size: 0.76rem; color: #667085; margin-bottom: 0.25rem; }
    .mini code, code.inline {
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 0.79rem;
      overflow-wrap: anywhere;
    }
    .list { display: grid; gap: 0.55rem; }
    .list-item {
      padding: 0.75rem;
      border: 1px solid var(--line);
      border-radius: 16px;
      background: #fff;
    }
    .list-item p { color: #475467; margin-top: 0.25rem; }
    details {
      border: 1px solid var(--line);
      border-radius: 18px;
      overflow: hidden;
      background: #0b1020;
      color: #d6e0ff;
    }
    summary {
      cursor: pointer;
      padding: 0.9rem 1rem;
      font-weight: 850;
      background: #111936;
    }
    pre {
      margin: 0;
      padding: 1rem;
      overflow: auto;
      font-size: 0.78rem;
      line-height: 1.45;
    }
    .empty {
      color: var(--muted);
      background: var(--panel-soft);
      border: 1px dashed var(--line);
      border-radius: 16px;
      padding: 0.85rem;
    }
    .toast {
      min-height: 1.2rem;
      color: var(--muted);
      font-size: 0.88rem;
      margin-top: 0.75rem;
    }
    @media (max-width: 900px) {
      .hero, .layout, .summary { grid-template-columns: 1fr; }
      .composer { position: static; }
      .metric-row { justify-content: start; }
    }
    @media (max-width: 520px) {
      header { padding-top: 1.5rem; }
      .examples { grid-template-columns: 1fr; }
      .summary, .section, .composer { padding: 0.85rem; }
    }
  </style>
</head>
<body>
  <header>
    <div class="hero">
      <div>
        <h1>Proof Vibe</h1>
        <p class="subtitle">A local sanity-check console for physics hypotheses. It turns plain-language claims into reviewable assumptions, policy obligations, and Lean-traceable reports.</p>
        <div class="pill-row">
          <span class="pill">Lean-backed policy checks</span>
          <span class="pill">Assumption ledger</span>
          <span class="pill">No silent LLM authority</span>
        </div>
      </div>
      <div class="panel section">
        <h3>Current policy</h3>
        <p class="summary-text">DFT architecture v1: XC discontinuity, spatial nonlocality, and self-adjointness.</p>
      </div>
    </div>
  </header>
  <main class="layout">
    <section class="panel composer">
      <h2>Hypothesis intake</h2>
      <p class="summary-text">Paste a physics hypothesis. The app drafts claims and tells you what still needs confirmation or formalization.</p>
      <div class="field">
        <label for="modelId">Hypothesis id</label>
        <input id="modelId" value="demo-hypothesis">
      </div>
      <div class="field">
        <label for="hypothesis">Physics hypothesis</label>
        <textarea id="hypothesis">A DFT architecture with an XC derivative discontinuity, nonlocal spatial coupling, and a self-adjoint learned self-energy operator.</textarea>
      </div>
      <div class="actions">
        <button class="primary" id="run">Run sanity draft</button>
        <button class="secondary" id="coverage">Policy coverage</button>
      </div>
      <div class="examples">
        <button class="example" data-example="pass">Passing-style draft</button>
        <button class="example" data-example="missing">Missing assumptions</button>
        <button class="example" data-example="bad">Violates principle</button>
        <button class="example" data-example="gap">Formalization gap</button>
      </div>
      <div class="toast" id="toast"></div>
    </section>

    <section class="results">
      <div class="panel summary">
        <div>
          <span id="statusBadge" class="status-badge">Ready</span>
          <h2 id="summaryTitle" style="margin-top:0.7rem">Draft a hypothesis report</h2>
          <p id="summaryText" class="summary-text">Results will appear here with obligations, assumptions, clarifying questions, and traceability.</p>
        </div>
        <div class="metric-row">
          <div class="metric"><strong id="metricClaims">—</strong><span>claims</span></div>
          <div class="metric"><strong id="metricQuestions">—</strong><span>questions</span></div>
          <div class="metric"><strong id="metricObligations">—</strong><span>obligations</span></div>
        </div>
      </div>

      <div class="panel">
        <div class="section">
          <div class="section-head">
            <div>
              <h2>Principle checks</h2>
              <p>Each row maps a physics principle to evidence, generated Lean tasks, and current status.</p>
            </div>
          </div>
          <div id="obligations" class="cards"><div class="empty">No report yet.</div></div>
        </div>
        <div class="section">
          <div class="section-head">
            <div>
              <h2>Clarifying questions</h2>
              <p>Questions to ask before treating the draft as a formal claim.</p>
            </div>
          </div>
          <div id="questions" class="list"><div class="empty">No questions yet.</div></div>
        </div>
        <div class="section">
          <div class="section-head">
            <div>
              <h2>Assumption ledger</h2>
              <p>What the system extracted, what source it came from, and whether it needs review.</p>
            </div>
          </div>
          <div id="assumptions" class="list"><div class="empty">No assumptions yet.</div></div>
        </div>
        <div class="section">
          <details>
            <summary>Raw JSON artifact</summary>
            <pre id="rawJson">{}</pre>
          </details>
        </div>
      </div>
    </section>
  </main>
<script>
async function post(path, body) {
  const response = await fetch(path, {method: "POST", headers: {"content-type": "application/json"}, body: JSON.stringify(body)});
  return await response.json();
}
async function get(path) {
  const response = await fetch(path);
  return await response.json();
}
const examples = {
  pass: "A DFT architecture with an XC derivative discontinuity at an electron-number boundary, nonlocal spatial coupling, and a self-adjoint learned self-energy operator.",
  missing: "The proposed model is nonlocal and uses message passing to propagate density information across sites, but it does not specify self-adjointness or the XC derivative discontinuity.",
  bad: "The architecture has an XC derivative discontinuity and nonlocal coupling, but the learned self-energy operator is explicitly non-self-adjoint.",
  gap: "The hypothesis proposes a rotationally equivariant DFT architecture with self-adjoint Fourier-space kernels and a long-range nonlocal receptive field."
};
function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => {
    if (ch === "&") return "&amp;";
    if (ch === "<") return "&lt;";
    if (ch === ">") return "&gt;";
    if (ch === '"') return "&quot;";
    return "&#39;";
  });
}
function statusClass(status) {
  if (status === "consistent_with_policy") return "good";
  if (status === "violates_required_principle") return "bad";
  if (status === "formalization_gap") return "gap";
  if (status === "inconclusive_missing_assumption" || status === "proof_required") return "warn";
  return "";
}
function label(value) {
  return String(value ?? "unknown").replaceAll("_", " ");
}
function shortJson(value) {
  if (value === undefined || value === null) return "—";
  return JSON.stringify(value);
}
function renderList(containerId, items, renderer, empty) {
  const container = document.getElementById(containerId);
  if (!items || items.length === 0) {
    container.innerHTML = `<div class="empty">${escapeHtml(empty)}</div>`;
    return;
  }
  container.innerHTML = items.map(renderer).join("");
}
function renderReport(data) {
  const report = data.report;
  const manifest = data.manifest || {};
  const status = report.status || data.status || "draft";
  const cls = statusClass(status);
  const badge = document.getElementById("statusBadge");
  badge.className = `status-badge ${cls}`;
  badge.textContent = label(status);
  document.getElementById("summaryTitle").textContent = manifest.model_id || "Hypothesis report";
  document.getElementById("summaryText").textContent = report.summary || "Draft report generated.";
  document.getElementById("metricClaims").textContent = manifest.hypothesis_intake?.extracted_claim_count ?? Object.keys(manifest.facts || {}).length;
  document.getElementById("metricQuestions").textContent = (report.clarification_questions || []).length;
  document.getElementById("metricObligations").textContent = (report.obligations || []).length;
  renderList("obligations", report.obligations || [], (item) => `
    <article class="obligation">
      <div class="obligation-top">
        <div>
          <h3>${escapeHtml(item.fact)}</h3>
          <p class="principle">${escapeHtml(item.principle)}</p>
        </div>
        <span class="tag ${statusClass(item.category)}">${escapeHtml(label(item.category))}</span>
      </div>
      <div class="detail-grid">
        <div class="mini"><b>Assessment</b><code>${escapeHtml(label(item.assessment_status))}</code></div>
        <div class="mini"><b>Evidence</b><code>${escapeHtml(item.evidence_kind || "missing")}</code></div>
        <div class="mini"><b>Lean task</b><code>${escapeHtml(item.lean_task_id || "not generated")}</code></div>
        <div class="mini"><b>Proof status</b><code>${escapeHtml(item.proof_status || "not run")}</code></div>
      </div>
      <div class="detail-grid">
        <div class="mini"><b>Normalized claim</b><code>${escapeHtml(shortJson(item.normalized_claim))}</code></div>
        <div class="mini"><b>Reason</b>${escapeHtml(item.reason)}</div>
      </div>
    </article>
  `, "No principle checks available.");
  renderList("questions", report.clarification_questions || [], (item) => `
    <div class="list-item">
      <strong>${escapeHtml(item.fact || "clarification")}</strong>
      <p>${escapeHtml(item.question)}</p>
      <p><small>${escapeHtml(item.reason || "")}</small></p>
    </div>
  `, "No clarifying questions.");
  renderList("assumptions", report.assumptions || [], (item) => `
    <div class="list-item">
      <strong>${escapeHtml(item.id)}</strong> <span class="tag">${escapeHtml(label(item.status))}</span>
      <p>${escapeHtml(item.statement)}</p>
      <p><small>Source: ${escapeHtml(label(item.source))}</small></p>
    </div>
  `, "No assumptions recorded.");
  document.getElementById("rawJson").textContent = JSON.stringify(data, null, 2);
}
function renderCoverage(data) {
  const badge = document.getElementById("statusBadge");
  badge.className = "status-badge";
  badge.textContent = "Policy coverage";
  document.getElementById("summaryTitle").textContent = data.policy.id;
  document.getElementById("summaryText").textContent = `Backed by ${data.project.lean_library} on ${data.project.toolchain}.`;
  document.getElementById("metricClaims").textContent = data.supported_claims.length;
  document.getElementById("metricQuestions").textContent = data.not_supported.length;
  document.getElementById("metricObligations").textContent = data.formalization_profiles.length;
  renderList("obligations", data.supported_claims, (item) => `
    <article class="obligation">
      <div class="obligation-top">
        <div>
          <h3>${escapeHtml(item.fact)}</h3>
          <p class="principle">${escapeHtml(item.description)}</p>
        </div>
        <span class="tag good">supported</span>
      </div>
      <div class="detail-grid">
        <div class="mini"><b>Obligation id</b><code>${escapeHtml(item.obligation_id)}</code></div>
        <div class="mini"><b>Evidence</b><code>${escapeHtml(item.accepted_evidence.join(", "))}</code></div>
      </div>
    </article>
  `, "No supported claims listed.");
  renderList("questions", data.not_supported, (item) => `
    <div class="list-item"><strong>Not supported</strong><p>${escapeHtml(item)}</p></div>
  `, "No unsupported scope listed.");
  renderList("assumptions", data.formalization_profiles, (item) => `
    <div class="list-item">
      <strong>${escapeHtml(item.id)}</strong>
      <p>Lean module: <code class="inline">${escapeHtml(item.module)}</code></p>
      <p><small>Facts: ${escapeHtml(item.facts.join(", "))}</small></p>
    </div>
  `, "No formalization profiles listed.");
  document.getElementById("rawJson").textContent = JSON.stringify(data, null, 2);
}
document.getElementById("run").onclick = async () => {
  document.getElementById("toast").textContent = "Drafting report...";
  const data = await post("/api/hypothesis", {
    model_id: document.getElementById("modelId").value,
    hypothesis: document.getElementById("hypothesis").value
  });
  renderReport(data);
  document.getElementById("toast").textContent = "Draft complete. Review assumptions before treating claims as formal.";
};
document.getElementById("coverage").onclick = async () => {
  document.getElementById("toast").textContent = "Loading policy coverage...";
  const data = await get("/api/coverage");
  renderCoverage(data);
  document.getElementById("toast").textContent = "Coverage loaded.";
};
for (const button of document.querySelectorAll("[data-example]")) {
  button.addEventListener("click", () => {
    const key = button.getAttribute("data-example");
    document.getElementById("modelId").value = `example-${key}`;
    document.getElementById("hypothesis").value = examples[key];
  });
}
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
