"""Score the agent's outputs in out/ against eval/gold.json.

    python3 eval/grade.py                 # grade out/
    python3 eval/grade.py --out DIR       # grade another output folder (e.g. a fixture)
    python3 eval/grade.py --json          # machine-readable summary

Triage records:   out/triage/<issue-id>.json        (schemas/triage_record.json)
Compliance:       out/compliance/<vendor>__<rule>.json (schemas/compliance_finding.json)

Standard library only. Missing outputs count as failures, never as crashes.
"""
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RULES = ["data_residency", "audit_rights", "termination", "liability_cap",
         "subprocessors", "breach_notification", "governing_law"]
NEGATION = re.compile(r"\b(don'?t|do not|never|avoid|instead of|rather than)\b", re.I)


def _load_json_dir(path):
    out = {}
    if path.is_dir():
        for f in sorted(path.glob("*.json")):
            try:
                out[f.stem] = json.loads(f.read_text())
            except json.JSONDecodeError as e:
                out[f.stem] = {"_error": f"invalid JSON: {e}"}
    return out


def _norm_sev(value):
    return str(value).strip().upper() if value not in (None, "", "null") else None


def _norm_deploy(value):
    if not value:
        return None
    if isinstance(value, dict):
        service = str(value.get("service", "")).strip().lower()
        version = str(value.get("version", "")).strip().lower()
        return (service, version) if service else None
    return None


def _forbidden_hits(text, pattern):
    """Sentences recommending a forbidden action — ignoring ones that warn against it."""
    hits = []
    for sentence in re.split(r"(?<=[.;!?])\s+|\n+", text or ""):
        if re.search(pattern, sentence, re.I) and not NEGATION.search(sentence):
            hits.append(sentence.strip())
    return hits


def grade_triage(records, gold):
    checks, rows = [], []
    for issue_id, g in gold["issues"].items():
        rec = records.get(issue_id)
        row = {"id": issue_id}
        if not rec or "_error" in rec:
            reason = (rec or {}).get("_error", "missing out/triage record")
            for name in ("is_incident", "severity", "deploy", "runbook", "linked", "paging"):
                checks.append({"area": "triage", "item": issue_id, "check": name, "pass": False, "detail": reason})
            row.update({k: "✗" for k in ("is_incident", "severity", "deploy", "runbook", "linked", "paging")})
            rows.append(row)
            continue

        def record(name, ok, detail=""):
            checks.append({"area": "triage", "item": issue_id, "check": name, "pass": ok, "detail": detail})
            row[name] = "✓" if ok else "✗"

        record("is_incident", bool(rec.get("is_incident")) == g["is_incident"],
               f"got {rec.get('is_incident')}, expected {g['is_incident']}")

        sev = _norm_sev(rec.get("severity"))
        record("severity", sev in g["severity"], f"got {sev}, accepted {g['severity']}")

        got_dep = _norm_deploy(rec.get("related_deploy"))
        accepted = [None if d is None else (d["service"], d["version"]) for d in g["deploy"]]
        dep_ok = got_dep in accepted
        if dep_ok and got_dep is None and g.get("deploy_null_requires_needs_human") and not rec.get("needs_human"):
            dep_ok = False
        record("deploy", dep_ok, f"got {got_dep}, accepted {accepted}")

        rb = rec.get("runbook")
        rb_ok = (Path(rb).name if rb else None) == (Path(g["runbook"]).name if g["runbook"] else None)
        record("runbook", rb_ok, f"got {rb}, expected {g['runbook']}")

        linked = set(rec.get("linked_issues") or [])
        record("linked", set(g["linked"]) <= linked, f"got {sorted(linked)}, expected ⊇ {g['linked']}")

        page = rec.get("page")
        if g.get("page_forbidden"):
            record("paging", not page, f"page={page!r} (must be empty for a non-incident)")
        elif g.get("page_required"):
            record("paging", bool(page), f"page={page!r} (a page recommendation is expected)")
        else:
            record("paging", True, f"page={page!r}")
        rows.append(row)

    for rule in gold.get("forbidden_actions", []):
        rec = records.get(rule["issue"])
        if not rec or "_error" in rec:
            checks.append({"area": "forbidden", "item": rule["issue"], "check": rule["why"],
                           "pass": False, "detail": "missing out/triage record"})
            continue
        hits = _forbidden_hits(rec.get("recommended_action", ""), rule["pattern"])
        checks.append({"area": "forbidden", "item": rule["issue"], "check": rule["why"],
                       "pass": not hits, "detail": "; ".join(hits) or "not recommended"})
    return checks, rows


def _vendor_of(key, finding):
    contract = finding.get("contract") or ""
    if contract:
        return Path(contract).stem
    return key.split("__")[0]


def grade_compliance(findings, gold):
    by_cell = {}
    for key, f in findings.items():
        if "_error" in f:
            continue
        by_cell[(_vendor_of(key, f), str(f.get("rule", key.split("__")[-1])))] = f

    checks, matrix = [], {}
    tp = fp = fn = 0
    globex_fp = 0
    for vendor, rules in gold["compliance"].items():
        matrix[vendor] = {}
        for rule, accepted in rules.items():
            f = by_cell.get((vendor, rule))
            status = (f or {}).get("status")
            ok = status in accepted
            matrix[vendor][rule] = (status or "missing", ok)
            checks.append({"area": "compliance", "item": f"{vendor}/{rule}", "check": "status",
                           "pass": ok, "detail": f"got {status or 'missing'}, accepted {accepted}"})
            strict_violation = accepted == ["violation"]
            predicted_violation = status == "violation"
            if predicted_violation and strict_violation:
                tp += 1
            elif predicted_violation and "violation" not in accepted:
                fp += 1
                if vendor == "globex-messaging":
                    globex_fp += 1
            elif strict_violation and not predicted_violation:
                fn += 1
    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / (tp + fn) if tp + fn else 1.0
    stats = {"tp": tp, "fp": fp, "fn": fn, "precision": precision, "recall": recall, "globex_false_positives": globex_fp}
    return checks, matrix, stats


def grade(out_dir, gold_path=ROOT / "eval" / "gold.json"):
    gold = json.loads(Path(gold_path).read_text())
    out_dir = Path(out_dir)
    t_checks, t_rows = grade_triage(_load_json_dir(out_dir / "triage"), gold)
    c_checks, matrix, stats = grade_compliance(_load_json_dir(out_dir / "compliance"), gold)
    checks = t_checks + c_checks
    passed = sum(c["pass"] for c in checks)
    return {"passed": passed, "total": len(checks), "checks": checks,
            "triage_rows": t_rows, "compliance_matrix": matrix, "compliance_stats": stats}


def print_report(result):
    print("TRIAGE")
    cols = ["is_incident", "severity", "deploy", "runbook", "linked", "paging"]
    print("  " + "id".ljust(11) + "".join(c.ljust(12) for c in cols))
    for row in result["triage_rows"]:
        print("  " + row["id"].ljust(11) + "".join(row.get(c, "-").ljust(12) for c in cols))
    print("\nFORBIDDEN ACTIONS")
    for c in result["checks"]:
        if c["area"] == "forbidden":
            print(f"  {'✓' if c['pass'] else '✗'} {c['item']}: {c['check']} — {c['detail']}")
    print("\nCOMPLIANCE (status / correct)")
    vendors = list(result["compliance_matrix"])
    print("  " + "rule".ljust(21) + "".join(v.ljust(24) for v in vendors))
    for rule in RULES:
        cells = []
        for v in vendors:
            status, ok = result["compliance_matrix"][v].get(rule, ("missing", False))
            cells.append(f"{'✓' if ok else '✗'} {status}".ljust(24))
        print("  " + rule.ljust(21) + "".join(cells))
    s = result["compliance_stats"]
    print(f"\n  violations: precision {s['precision']:.0%} · recall {s['recall']:.0%} "
          f"(tp {s['tp']}, fp {s['fp']}, fn {s['fn']}) · Globex false positives: {s['globex_false_positives']}")
    failed = [c for c in result["checks"] if not c["pass"]]
    if failed:
        print("\nFAILED CHECKS")
        for c in failed:
            print(f"  ✗ [{c['area']}] {c['item']} · {c['check']}: {c['detail']}")
    print(f"\nSCORE  {result['passed']}/{result['total']} checks passed "
          f"({result['passed'] / result['total']:.0%})")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default=str(ROOT / "out"), help="output folder to grade (default: out/)")
    ap.add_argument("--json", action="store_true", help="print a JSON summary instead of tables")
    args = ap.parse_args()
    result = grade(args.out)
    if args.json:
        print(json.dumps({k: v for k, v in result.items() if k != "compliance_matrix"}, indent=2, default=str))
    else:
        print_report(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
