"""Track which input files the agent has already processed (idempotency for always-on runs).

    python3 state.py              # list new / changed / removed files since the last committed run
    python3 state.py --json       # same, machine-readable
    python3 state.py --commit     # record the current files as processed (after a successful run)

state.json maps each file in issues/ and contracts/ to the sha256 of its contents. A file is
"new" if it isn't in state.json, "changed" if its hash differs, "removed" if it disappeared.
"""
import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STATE_FILE = ROOT / "state.json"
WATCHED = {"issues": "*.json", "contracts": "*.md"}


def file_hashes(root=ROOT):
    hashes = {}
    for folder, pattern in WATCHED.items():
        for f in sorted((root / folder).glob(pattern)):
            hashes[f.relative_to(root).as_posix()] = hashlib.sha256(f.read_bytes()).hexdigest()
    return hashes


def load_state(path=STATE_FILE):
    if path.exists():
        return json.loads(path.read_text())
    return {"last_run": None, "files": {}}


def diff(current, previous):
    prev = previous.get("files", {})
    return {
        "new": sorted(p for p in current if p not in prev),
        "changed": sorted(p for p in current if p in prev and prev[p] != current[p]),
        "removed": sorted(p for p in prev if p not in current),
        "unchanged": sorted(p for p in current if prev.get(p) == current[p]),
    }


def changed_files(root=ROOT, state_path=STATE_FILE):
    """New + changed files — what the agent should (re)process this run."""
    d = diff(file_hashes(root), load_state(state_path))
    return d["new"] + d["changed"]


def commit(root=ROOT, state_path=STATE_FILE):
    state = {"last_run": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "files": file_hashes(root)}
    state_path.write_text(json.dumps(state, indent=2) + "\n")
    return state


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--commit", action="store_true", help="record current files as processed")
    ap.add_argument("--json", action="store_true", help="print the diff as JSON")
    args = ap.parse_args()
    if args.commit:
        state = commit()
        print(f"state.json updated: {len(state['files'])} files recorded at {state['last_run']}")
        return 0
    previous = load_state()
    d = diff(file_hashes(), previous)
    if args.json:
        print(json.dumps({"last_run": previous.get("last_run"), **d}, indent=2))
        return 0
    print(f"last run: {previous.get('last_run') or 'never'}")
    for kind in ("new", "changed", "removed"):
        print(f"{kind:8} {len(d[kind])}" + ("".join(f"\n  - {p}" for p in d[kind]) if d[kind] else ""))
    print(f"unchanged {len(d['unchanged'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
