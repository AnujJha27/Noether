"""Score saved VISTA corpus results; never infer ground truth from the analyzer."""
from __future__ import annotations
import argparse, csv, json
from collections import defaultdict
from pathlib import Path

def rate(a,b): return "n/a" if not b else f"{a}/{b} ({a/b:.1%})"
def main():
    p=argparse.ArgumentParser(); p.add_argument("results",type=Path); p.add_argument("--manifest",type=Path,required=True); o=p.parse_args()
    rows=list(csv.DictReader((o.results / "cases.csv").open())); primary=[r for r in rows if r["repeat"] == "0"]
    groups=defaultdict(list)
    for row in primary: groups[(row["domain"],row["class"])].append(row)
    lines=["| domain | class | cases | correct | unsupported | malformed |", "|---|---:|---:|---:|---:|---:|"]
    for (domain, cls), items in sorted(groups.items()): lines.append(f"| {domain} | {cls} | {len(items)} | {sum(x['correct']=='True' for x in items)} | {sum(x['observed_semantic_status']=='unsupported' for x in items)} | {sum(x['observed_semantic_status']=='malformed' for x in items)} |")
    negatives=[r for r in primary if r["expected_status"] != "supported-and-compatible"]
    false_cert=[r for r in negatives if r["certificate_status"] == "verified"]
    positives=[r for r in primary if r["expected_status"] == "supported-and-compatible"]
    tamper=[]
    for row in primary:
        evidence = o.results / row["case_id"] / "0" / "evidence.json"
        if evidence.exists(): tamper.extend(json.loads(evidence.read_text()).get("tampering", []))
    deterministic = 0
    for _, items in __import__('itertools').groupby(sorted(rows, key=lambda r: r['case_id']), key=lambda r: r['case_id']):
        items = list(items)
        deterministic += int(len({(x["observed_semantic_status"], x["observed_ir_value"], x["certificate_status"]) for x in items}) == 1)
    summary={"cases":len(primary),"false_certification":rate(len(false_cert),len(negatives)),"positive_acceptance":rate(sum(r['certificate_status']=='verified' for r in positives),len(positives)),"near_miss_rejection":rate(sum(r['certificate_status']!='verified' for r in primary if r['class']=='near_miss'),sum(r['class']=='near_miss' for r in primary)),"unsupported_withheld":rate(sum(r['certificate_status']!='verified' for r in primary if r['expected_status']=='unsupported'),sum(r['expected_status']=='unsupported' for r in primary)),"malformed_rejection":rate(sum(r['observed_semantic_status']=='malformed' for r in primary if r['expected_status']=='malformed'),sum(r['expected_status']=='malformed' for r in primary)),"tamper_detection":rate(sum(x['detected'] for x in tamper),len(tamper)),"deterministic_obligation":rate(deterministic,len({r['case_id'] for r in rows})),"reproducible_disposition":rate(deterministic,len({r['case_id'] for r in rows}))}
    (o.results / "summary.json").write_text(json.dumps(summary,indent=2)+"\n"); (o.results / "summary.md").write_text("# VISTA Structural V2 evaluation\n\n"+"\n".join(lines)+"\n\n"+"\n".join(f"- {k.replace('_',' ')}: {v}" for k,v in summary.items())+"\n")
if __name__ == "__main__": main()
