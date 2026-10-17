"""Reopen a refused changed-stage profile and compare canonical state to preimage."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from tests.data_safety.gui_staged_change import inventory
from tests.gate1.qt_checks import QtChecks


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    parser.add_argument("--kind", choices=("bundle", "pack"), required=True)
    args = parser.parse_args()
    q = QtChecks(args.profile)
    root = q.paths["root"]
    preimage = root.parent.parent / "retained" / f"{args.profile}-before" / "backend"
    prior = json.loads((root / f"data-safety-{args.kind}-stale-review.json").read_text())
    assert prior["pass"] is True and preimage.is_dir()
    actual, expected = inventory(q.paths["backend"]), inventory(preimage)
    stage_root = q.paths["backend"] / ("uploads/quiz_bundles" if args.kind == "bundle" else "content_pack_staging")
    retained = [path.relative_to(stage_root).as_posix() for path in stage_root.rglob("*") if path.is_file()]
    out = {"profile": args.profile, "kind": args.kind,
           "canonical_equal_preimage": actual == expected,
           "retained_stage_files": retained,
           "pass": actual == expected and bool(retained)}
    (root / f"data-safety-{args.kind}-stale-reopen.json").write_text(json.dumps(out, indent=2) + "\n")
    q.close()
    print(json.dumps(out, indent=2))
    return 0 if out["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
