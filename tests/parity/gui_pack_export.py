"""Export installed synthetic Study Packs through Qt and compare ZIP contents."""
from __future__ import annotations

import argparse
import hashlib
import json
import time
import traceback
import zipfile

from tests.gate1.qt_checks import QtChecks


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--profile", required=True)
    a = p.parse_args()
    q = QtChecks(a.profile)
    out = {"profile": a.profile, "exports": {}}
    try:
        prior = json.loads((q.paths["root"] / "parity-subject-packs.json").read_text())
        for domain, item in prior["domains"].items():
            before = {str(p) for p in q.paths["downloads"].rglob("*.zip")}
            q.go(f"/content-packs/details/{item['folder']}")
            q.click_css("a[href^='/content-packs/export/']")
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                candidates = [p for p in q.paths["downloads"].rglob("*.zip") if str(p) not in before]
                if candidates and any(x.get("state") == "completed" for x in q.window.download_results):
                    break
                q.delay(.1)
            else:
                raise TimeoutError(f"{domain} pack export")
            archive = candidates[0]
            with zipfile.ZipFile(archive) as z:
                members = [name for name in z.namelist() if not name.endswith("/")]
                contents = {name: hashlib.sha256(z.read(name)).hexdigest() for name in members}
                crc_bad = z.testzip()
            original = item["installed_hashes"]
            expected = {f"{item['folder']}/{relative}": digest for relative, digest in original.items()}
            matched = len(members) == len(contents) == len(expected) and contents == expected
            out["exports"][domain] = {"path": str(archive), "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                                      "crc_bad": crc_bad, "contents": contents, "installed_match": matched,
                                      "completed": any(x.get("state") == "completed" for x in q.window.download_results)}
        out["pass"] = all(x["crc_bad"] is None and x["installed_match"] and x["completed"] for x in out["exports"].values())
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
        traceback.print_exc()
    finally:
        (q.paths["root"] / "parity-pack-export.json").write_text(json.dumps(out, indent=2) + "\n")
        q.close()
    print(json.dumps(out, indent=2))
    return 0 if out.get("pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
