"""One always-on pass after the agent has written out/: grade, write back, report, record state.

    python3 run.py               # dry run: grade + report; show planned write-back; state NOT recorded
    python3 run.py --apply       # write back, write the report, then record state.json
    python3 run.py --apply --github   # ...and open GitHub issues for violations

Order matters: write-back edits issues/*.json, so state is recorded AFTER write-back. Otherwise
the agent's own edits would look like "changed" files on the next run.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import report  # noqa: E402
import state  # noqa: E402
import writeback  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--apply", action="store_true", help="write back and record state (default: dry run)")
    ap.add_argument("--github", action="store_true", help="also open GitHub issues for violations")
    args = ap.parse_args()

    changes = state.diff(state.file_hashes(), state.load_state())
    print(f"changes since last run: {len(changes['new'])} new, {len(changes['changed'])} changed, "
          f"{len(changes['removed'])} removed")
    wb = writeback.run(apply=args.apply, github=args.github)
    print(f"writeback ({wb['mode']}): {len(wb['triage']['updated'])} issues updated, "
          f"{len(wb['compliance']['opened'])} compliance issues opened, "
          f"{len(wb['compliance']['needs_review'])} need review")
    result = report.write(changes, wb)
    print(f"out/run-report.md written · score {result['passed']}/{result['total']} checks")
    if args.apply:
        st = state.commit()
        print(f"state.json recorded ({len(st['files'])} files)")
    else:
        print("dry run: nothing written to issues/ or compliance-issues/, state.json not updated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
