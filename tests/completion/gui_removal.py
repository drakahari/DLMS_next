"""Real Qt synthetic whole-profile removal with retained outside-target copy."""
from __future__ import annotations

import argparse
import json
import time
import traceback

from desktop.isolation import AREA
from desktop.maintenance import _digest, _file_inventory
from tests.gate1.qt_checks import QtChecks


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    name = parser.parse_args().profile
    q = QtChecks(name, automated=True)
    out = {"profile": name}
    output = AREA / "removal-tests" / f"{name}.json"
    output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        retained = AREA / "retained" / f"{name}-before"
        assert retained.is_dir()
        retained_digest = _digest(_file_inventory(retained))
        assert q.window.begin_removal(confirmed=True)
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline:
            q.delay(.15)
            marker_path = AREA / "removed" / f"{name}.json"
            if marker_path.exists():
                marker = json.loads(marker_path.read_text())
                if marker["phase"] == "removed":
                    break
        else:
            raise TimeoutError("Intentional-removal tombstone did not reach removed")
        recovery = AREA / "recovery" / name / marker["operation_id"]
        out.update(marker=marker, target_absent=not q.paths["root"].exists(),
                   retained_digest=retained_digest,
                   preimage_digest=_digest(_file_inventory(recovery / "profile")),
                   removed_digest=_digest(_file_inventory(recovery / "removed-profile")))
        out["pass"] = (out["target_absent"] and out["preimage_digest"] == out["removed_digest"]
                       and _digest(_file_inventory(retained)) == retained_digest)
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
        traceback.print_exc()
    finally:
        output.write_text(json.dumps(out, indent=2) + "\n")
        q.close()
    print(json.dumps({k:v for k,v in out.items() if k != "marker"}, indent=2))
    return 0 if out.get("pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
