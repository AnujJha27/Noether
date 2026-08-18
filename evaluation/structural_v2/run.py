"""Run the VISTA corpus through the production exporter, extractor, lowering and checker."""
from __future__ import annotations
import argparse, copy, csv, hashlib, json, platform, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from dftcert.manifest import ManifestError, sha256_value
from dftcert.structural import (assemble_structural_certificate, assess_structural_ir,
    generate_structural_obligations, structural_ir_from_inventory, validate_translation,
    verify_structural_certificate)

def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True); path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")

def constraints(case):
    value = {"adjacency_state_name":"adjacency", "adjacency_convention":"target_source",
      "output_contracts":[{"index":0,"role":"xc_energy"},{"index":1,"role":"learned_self_energy"},{"index":2,"role":"message_state"}],
      "required_couplings":[{"source":0,"target":2}]}
    spec = case.get("constraints", {})
    value["required_couplings"] = [{"source":s,"target":t} for s,t in spec.get("couplings", [[0, 2]])]
    if spec.get("convention"): value["adjacency_convention"] = spec["convention"]
    role = spec.get("role")
    if role == "missing_message": value["output_contracts"] = value["output_contracts"][:2]
    if role == "missing_operator": value["output_contracts"] = [value["output_contracts"][0], value["output_contracts"][2]]
    if role == "missing_xc": value["output_contracts"] = value["output_contracts"][1:]
    if role == "duplicate": value["output_contracts"].append({"index":0,"role":"xc_energy"})
    if role == "wrong_operator": value["output_contracts"][1]["index"] = 0
    if role == "wrong_xc": value["output_contracts"][0]["index"] = 1
    return value

def normalized(ir):
    status = assess_structural_ir(ir)["status"]
    return {"structurally_certifiable":"supported-and-compatible", "structural_requirements_not_met":"supported-but-incompatible", "formalization_required":"unsupported"}[status]

def extract(artifact):
    process = subprocess.run([sys.executable, str(ROOT / "extractors/torch_export_worker.py"), str(artifact)], text=True, capture_output=True)
    return json.loads(process.stdout)

def tamper(ir, inventory, input_constraints):
    mutations = {
      "message_depth": lambda x: x.__setitem__("message_passing", {**x["message_passing"], "depth": x["message_passing"]["depth"] + 1}),
      "xc_form": lambda x: x["xc"].__setitem__("form", "smooth" if x["xc"]["form"] != "smooth" else "hinge"),
      "operator_form": lambda x: x["operator"].__setitem__("construction", "unsupported"),
      "evidence_node": lambda x: x["translation"]["semantic_derivations"]["xc"]["evidence_nodes"].append("forged"),
      "root_node": lambda x: x["translation"]["semantic_derivations"]["operator"].__setitem__("root", "forged"),
      "rule_identifier": lambda x: x["translation"]["semantic_derivations"]["operator"].__setitem__("rule", "operator.forged"),
      "rule_version": lambda x: x["translation"]["semantic_derivations"]["operator"].__setitem__("rule_version", 99),
      "source_hash": lambda x: x["source"].__setitem__("artifact_sha256", "0" * 64),
      "ir_field": lambda x: x["topology"].__setitem__("site_count", x["topology"]["site_count"] + 1),
    }
    output = []
    for name, change in mutations.items():
        altered = copy.deepcopy(ir); change(altered)
        try: validate_translation(inventory=inventory, value=altered, input_constraints=input_constraints); result = "accepted"
        except ManifestError as error: result = "rejected:" + str(error)
        output.append({"tamper_id":name, "result":result, "detected":result.startswith("rejected:")})
    return output

def run_case(case, artifact, output, repeat):
    evidence = {"case_id":case["id"], "repeat":repeat, "artifact":str(artifact), "artifact_sha256":hashlib.sha256(artifact.read_bytes()).hexdigest(), "input_constraints":constraints(case), "experiment": json.loads((HERE / "experiment.json").read_text())}
    try:
        raw = extract(artifact); evidence["raw_extraction"] = raw
        if raw.get("status") != "ok": raise ManifestError(raw.get("diagnostics", "extractor failed"))
        ir = structural_ir_from_inventory(inventory=raw["inventory"], artifact_sha256=raw["artifact_sha256"], extractor_version=raw["extractor_version"], input_constraints=evidence["input_constraints"])
        assessment, obligations = assess_structural_ir(ir), generate_structural_obligations(ir)
        evidence.update({"structural_ir":ir, "semantic_derivations":ir["translation"]["semantic_derivations"], "translation_validation":ir["translation_validation"], "policy":assessment, "generated_obligations":obligations})
        status, reason = normalized(ir), ""
        certificate_status, lean_status = "ineligible", "not_run"
        if status == "supported-and-compatible":
            proofs = [{"id":x["id"],"status":"verified","winner":{"patch":"by decide"}} for x in obligations["obligations"]]
            source, certificate = assemble_structural_certificate(ir, proofs); source_path = output / "Certificate.lean"; source_path.write_text(source)
            verification = verify_structural_certificate(project_root=ROOT / "lean", certificate_source=source_path, trusted_local=True)
            evidence.update({"certificate":certificate, "lean_verification":verification}); lean_status = verification["status"]; certificate_status = "verified" if lean_status == "verified" else "not_verified"
        if repeat == 0 and case["class"] != "malformed": evidence["tampering"] = tamper(ir, raw["inventory"], evidence["input_constraints"])
    except Exception as error:
        status, reason, lean_status, certificate_status = "malformed", f"{type(error).__name__}: {error}", "not_run", "ineligible"
    expected = case["expected"]["semantic_status"]
    row = {"case_id":case["id"],"domain":case["domain"],"class":case["class"],"split":case["split"],"repeat":repeat,"artifact_hash":evidence.get("artifact_sha256",""),"expected_status":expected,"observed_semantic_status":status,"observed_ir_value":"" if "structural_ir" not in evidence else json.dumps({"xc":evidence["structural_ir"]["xc"]["form"],"operator":evidence["structural_ir"]["operator"]["construction"],"depth":evidence["structural_ir"]["message_passing"]["depth"]},sort_keys=True),"translation_valid":evidence.get("translation_validation",{}).get("status") == "translation_validated","policy_status":evidence.get("policy",{}).get("status","not_run"),"lean_status":lean_status,"certificate_status":certificate_status,"correct":status == expected,"failure_reason":reason}
    dump(output / "evidence.json", evidence); return row

def main():
    parser=argparse.ArgumentParser(); parser.add_argument("--repeats",type=int,default=3); parser.add_argument("--artifacts",type=Path,default=ROOT / "build" / "vista-structural-v2-corpus"); parser.add_argument("--results",type=Path,default=HERE / "results" / "latest"); parser.add_argument("--generate",action="store_true"); options=parser.parse_args()
    if options.generate: subprocess.run([sys.executable,str(HERE / "generate.py"),"--output-dir",str(options.artifacts)],check=True)
    manifest=json.loads((HERE / "corpus_manifest.json").read_text()); options.results.mkdir(parents=True,exist_ok=True)
    experiment=json.loads((HERE / "experiment.json").read_text()); experiment["runtime"]={"python":sys.version,"platform":platform.platform(),"executed_at":datetime.now(timezone.utc).isoformat()}; dump(options.results / "experiment.json", experiment)
    rows=[]
    for case in manifest["cases"]:
        artifact=options.artifacts / f'{case["id"]}.pt2'
        if not artifact.exists():
            rows.append({"case_id":case["id"],"domain":case["domain"],"class":case["class"],"split":case["split"],"repeat":0,"artifact_hash":"","expected_status":case["expected"]["semantic_status"],"observed_semantic_status":"malformed","observed_ir_value":"","translation_valid":False,"policy_status":"not_run","lean_status":"not_run","certificate_status":"ineligible","correct":False,"failure_reason":"artifact missing; run with --generate in a PyTorch environment"}); continue
        for repeat in range(options.repeats): rows.append(run_case(case,artifact,options.results / case["id"] / str(repeat),repeat))
    with (options.results / "cases.csv").open("w",newline="") as file: writer=csv.DictWriter(file,fieldnames=rows[0]); writer.writeheader(); writer.writerows(rows)
    dump(options.results / "cases.json", rows)
    subprocess.run([sys.executable, str(HERE / "score.py"), str(options.results), "--manifest", str(HERE / "corpus_manifest.json")], check=False)
if __name__ == "__main__": main()
