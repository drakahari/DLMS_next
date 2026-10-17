"""Show the captured Study Pack duplicate-ID policy in the Qt window."""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import traceback
import zipfile

from tests.gate1.qt_checks import QtChecks


def hashes(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob("*") if p.is_file()}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--profile", required=True)
    a = p.parse_args()
    q = QtChecks(a.profile)
    out = {"profile": a.profile}
    try:
        pack = q.paths["backend"] / "content_packs" / "DLMS_Study_parity_it"
        if not pack.is_dir():
            raise AssertionError("Expected synthetic installed pack is missing")
        old_hashes = hashes(pack)
        db = q.paths["backend"] / "results.db"
        with sqlite3.connect(db) as c:
            old_rows = {t: c.execute(f'SELECT * FROM "{t}" ORDER BY rowid').fetchall()
                        for t in ("quizzes", "questions", "matching_pairs")}
        archive = q.paths["tmp"] / "completion-pack-same-id-changed.zip"
        folder = pack.name
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
            for path in pack.rglob("*"):
                if not path.is_file():
                    continue
                raw = path.read_bytes()
                if path.name == "terms.json":
                    value = json.loads(raw)
                    value["terms"][0]["definition"] = "Changed synthetic definition."
                    raw = json.dumps(value).encode()
                z.writestr(f"{folder}/{path.relative_to(pack).as_posix()}", raw)
        q.go("/content-packs")
        q.window.file_selection_for_test = archive
        q.click_css('input[name="pack_zip"]')
        q.js("document.querySelector('form[action=\"/content-packs/import\"]').requestSubmit();true")
        q.wait("location.pathname.startsWith('/content-packs/import/') || document.body.innerText.includes('already installed')", 20)
        if q.js("!!document.getElementById('packReviewInstallForm')"):
            q.js("(()=>{const f=document.getElementById('packReviewInstallForm');f.elements.confirm_install.checked=true;f.requestSubmit();return true})()")
            q.wait("!!document.querySelector('.content-pack-flashes [role=alert]')", 15)
        out["after_attempt_url"] = q.js("location.href")
        out["flash"] = q.js("document.querySelector('.content-pack-flashes [role=alert]')?.innerText || ''")
        out["message"] = q.js("document.body.innerText.slice(-1200)")
        out["alert_role"] = q.js("document.querySelector('.content-pack-flashes [role=alert]')?.getAttribute('role')")
        out["screenshot"] = str(q.screenshot("completion-pack-replacement-refused.png", width=1000, height=760))
        with sqlite3.connect(db) as c:
            out["rows_unchanged"] = all(c.execute(f'SELECT * FROM "{t}" ORDER BY rowid').fetchall() == rows
                                        for t, rows in old_rows.items())
        out["pack_hashes_unchanged"] = hashes(pack) == old_hashes
        out["replacement_supported"] = False
        out["user_error_visible"] = "already installed" in out["flash"] and "does not replace" in out["flash"]
        out["pass"] = ("/content-packs/import/" in out["after_attempt_url"] and
                       out["alert_role"] == "alert" and out["user_error_visible"] and
                       out["rows_unchanged"] and out["pack_hashes_unchanged"])
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
        traceback.print_exc()
    finally:
        (q.paths["root"] / "completion-pack-replacement-limit.json").write_text(json.dumps(out, indent=2) + "\n")
        q.close()
    print(json.dumps(out, indent=2))
    return 0 if out.get("pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
