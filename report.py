"""Write out/run-report.md: what changed, what the agent recommended, what needs a human, and the score.

    python3 report.py          # usually called by run.py
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "eval"))
import grade  # noqa: E402  (eval/grade.py)


def _load(path):
    return [json.loads(f.read_text()) for f in sorted(path.glob("*.json"))] if path.is_dir() else []


def build(changes=None, writeback=None):
    triage = _load(ROOT / "out" / "triage")
    findings = _load(ROOT / "out" / "compliance")
    result = grade.grade(ROOT / "out")
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [f"# Always-On Ops Agent — run report", "", f"_Run at {now}. All data is synthetic._", ""]

    lines += ["## What changed since the last run", ""]
    if changes is None:
        lines.append("(state not checked)")
    elif not (changes["new"] or changes["changed"] or changes["removed"]):
        lines.append("No changes — nothing to triage or re-check.")
    else:
        for kind in ("new", "changed", "removed"):
            for p in changes[kind]:
                lines.append(f"- **{kind}:** `{p}`")
    lines.append("")

    lines += ["## Incident triage", "", "| Issue | Incident? | Severity | Related deploy | Runbook | Needs human |",
              "|---|---|---|---|---|---|"]
    for r in sorted(triage, key=lambda r: r.get("id", "")):
        dep = r.get("related_deploy") or {}
        dep_s = f"{dep.get('service')} {dep.get('version')}" if dep else "—"
        lines.append(f"| {r.get('id')} | {'yes' if r.get('is_incident') else 'no'} | {r.get('severity') or '—'} | "
                     f"{dep_s} | {Path(r['runbook']).name if r.get('runbook') else '—'} | {'⚠️ yes' if r.get('needs_human') else 'no'} |")
    if not triage:
        lines.append("| _no triage records in out/triage/_ | | | | | |")
    lines.append("")

    approvals = [r for r in triage if r.get("page") or (r.get("related_deploy") or {}).get("rollback_to")]
    lines += ["## Needs human approval (recommended, not executed)", ""]
    for r in approvals:
        dep = r.get("related_deploy") or {}
        parts = []
        if r.get("page"):
            parts.append(f"page **{r['page']}**")
        if dep.get("rollback_to"):
            parts.append(f"roll back **{dep.get('service')}** to **{dep['rollback_to']}**")
        lines.append(f"- **{r.get('id')}** ({r.get('severity') or '—'}): " + "; ".join(parts))
    review = [r for r in triage if r.get("needs_human")] + [f for f in findings if f.get("status") == "needs_review"]
    for item in review:
        if "rule" in item:
            lines.append(f"- **{item.get('vendor') or item.get('contract')} / {item.get('rule')}**: needs legal review — {item.get('reason', '')}")
        else:
            lines.append(f"- **{item.get('id')}**: low confidence — review the triage before acting")
    if not approvals and not review:
        lines.append("Nothing pending.")
    lines.append("")

    lines += ["## Compliance", "", "| Rule | " + " | ".join(result["compliance_matrix"]) + " |",
              "|---|" + "---|" * len(result["compliance_matrix"])]
    for rule in grade.RULES:
        cells = [result["compliance_matrix"][v].get(rule, ("missing", False))[0] for v in result["compliance_matrix"]]
        lines.append(f"| {rule} | " + " | ".join(cells) + " |")
    lines.append("")

    if writeback:
        t, c = writeback["triage"], writeback["compliance"]
        lines += [f"## Write-back ({writeback['mode']}{', GitHub' if writeback['github'] else ''})", "",
                  f"- Issues updated: {len(t['updated'])} {t['updated'] or ''}",
                  f"- Issues already up to date: {len(t['skipped'])}",
                  f"- Compliance issues opened: {len(c['opened'])}",
                  f"- Compliance issues already open: {len(c['skipped'])}",
                  f"- Findings sent for human review: {len(c['needs_review'])}", ""]

    s = result["compliance_stats"]
    lines += ["## Score (eval/grade.py vs eval/gold.json)", "",
              f"- **{result['passed']}/{result['total']} checks passed ({result['passed'] / result['total']:.0%})**",
              f"- Compliance violations: precision {s['precision']:.0%}, recall {s['recall']:.0%}; "
              f"Globex false positives: {s['globex_false_positives']}", ""]
    failed = [c for c in result["checks"] if not c["pass"]]
    if failed:
        lines.append("Failed checks:")
        lines += [f"- [{c['area']}] {c['item']} · {c['check']}: {c['detail']}" for c in failed]
        lines.append("")
    return "\n".join(lines), result


def write(changes=None, writeback=None):
    text, result = build(changes, writeback)
    (ROOT / "out").mkdir(exist_ok=True)
    (ROOT / "out" / "run-report.md").write_text(text)
    return result


if __name__ == "__main__":
    r = write()
    print(f"out/run-report.md written · score {r['passed']}/{r['total']}")
