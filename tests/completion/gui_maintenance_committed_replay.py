"""Separate-process Qt recovery after a committed worker loses its reply."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import traceback

from desktop.isolation import AREA
from desktop.maintenance import (_columns, _digest, _file_inventory, _tables,
                                 _validate_result, read_marker, run)
from tests.gate1.qt_checks import QtChecks


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--profile", required=True)
    p.add_argument("--scope", required=True)
    a = p.parse_args()
    abort = json.loads((AREA / "retained" / f"{a.profile}-abort-committed.json").read_text())
    marker = abort["marker"]
    out = {"profile": a.profile, "scope": a.scope, "operation_id": marker["operation_id"]}
    q = None
    try:
        if not abort["pass"] or marker["scope"] != a.scope:
            raise AssertionError("Committed synthetic abort evidence does not match")
        profile = AREA / "profiles" / a.profile
        root = profile / "backend"
        out["committed_hash_before_restart"] = _digest(_file_inventory(root))
        if out["committed_hash_before_restart"] != marker["postimage_sha256"]:
            raise AssertionError("Committed backend bytes changed before restart")
        before = AREA / "retained" / f"{a.profile}-before" / "backend" / "results.db"
        current = read_marker(a.profile)
        if current is not None and current["phase"] == "committed":
            first = subprocess.run([sys.executable, "-m", "desktop", "--profile", a.profile,
                                    "--automated"], timeout=25, check=False)
            out["first_recovery_exit"] = first.returncode
            current = read_marker(a.profile)
        if current is None or current["phase"] != "browser_check_pending":
            raise AssertionError("First Qt recovery did not retain a browser verification marker")
        q = QtChecks(a.profile, automated=True)
        out["marker_cleared"] = read_marker(a.profile) is None
        out["normal_page"] = q.js("location.pathname")
        _validate_result(a.scope, _tables(before), _tables(root / "results.db"), _columns(before))
        first = run(a.profile, a.scope, marker["operation_id"])
        second = run(a.profile, a.scope, marker["operation_id"])
        out["same_id_receipts"] = first == second and first.get("operation_id") == marker["operation_id"]
        out["receipt_phase"] = first.get("phase")
        out["pass"] = out["marker_cleared"] and out["normal_page"] == "/" and out["same_id_receipts"]
        out["screenshot"] = str(q.screenshot(f"completion-{a.scope}-committed-reopen.png", width=970, height=720))
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
        traceback.print_exc()
    finally:
        (AREA / "retained" / f"{a.profile}-committed-replay.json").write_text(json.dumps(out, indent=2) + "\n")
        if q is not None:
            q.close()
    print(json.dumps(out, indent=2))
    return 0 if out.get("pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
