"""Crash the exact synthetic maintenance worker at a durable checkpoint."""
from __future__ import annotations

import argparse
import json
import time
import traceback

from desktop.isolation import AREA
from tests.gate1.qt_checks import QtChecks


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--profile", required=True)
    p.add_argument("--scope", required=True)
    p.add_argument("--checkpoint", choices=("prepared", "mutation_started", "after_source", "committed"), required=True)
    a = p.parse_args()
    out = {"profile": a.profile, "scope": a.scope, "checkpoint": a.checkpoint}
    q = QtChecks(a.profile, automated=True, maintenance_abort=a.checkpoint)
    try:
        if not (AREA / "retained" / f"{a.profile}-before").is_dir():
            raise AssertionError("External synthetic recovery copy is required")
        assert q.window.begin_maintenance(a.scope, confirmed=True)
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline and q.window.maintenance_worker is not None:
            q.delay(.1)
        marker = AREA / "maintenance" / a.profile / "active.json"
        out["marker"] = json.loads(marker.read_text()) if marker.exists() else None
        out["worker_stopped"] = q.window.maintenance_worker is None
        out["window_failed_closed"] = bool(q.window.failed_reason)
        out["pass"] = bool(out["worker_stopped"] and out["window_failed_closed"]
                           and out["marker"] and out["marker"]["phase"] ==
                           ("committed" if a.checkpoint == "committed" else
                            "mutation_started" if a.checkpoint in {"mutation_started", "after_source"} else "prepared"))
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
        traceback.print_exc()
    finally:
        (AREA / "retained" / f"{a.profile}-abort-{a.checkpoint}.json").write_text(json.dumps(out, indent=2) + "\n")
        q.close()
    print(json.dumps({k: v for k, v in out.items() if k != "marker"}, indent=2))
    return 0 if out.get("pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
