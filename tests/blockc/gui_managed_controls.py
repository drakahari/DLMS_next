"""Legacy destructive controls stay visible and fail closed in Desktop."""
from __future__ import annotations

import argparse
import hashlib
import http.client
import json

from tests.gate1.qt_checks import QtChecks


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    args = parser.parse_args()
    q = QtChecks(args.profile)
    result = {}
    db = q.paths["backend"] / "results.db"
    try:
        q.go("/settings/backup")
        result["restore_notice"] = q.js("document.body.innerText.includes('Desktop-managed import for this profile')")
        result["web_restore_form_absent"] = q.js("!document.querySelector('form[action=\"/settings/backup/restore/stage\"]')")
        q.js("[...document.querySelectorAll('.settings-warning-panel')].find(x=>x.innerText.includes('Desktop-managed import'))?.scrollIntoView({block:'center'});true")
        q.delay(0.3)
        result["backup_screenshot"] = str(q.screenshot("blockc-managed-restore.png"))
        q.go("/settings/reset-remove")
        result["reset_notice"] = q.js("document.body.innerText.includes('native Desktop controls adjacent to this page')")
        result["disabled_controls"] = q.js("[...document.querySelectorAll('#clearDBBtn,.resetAction,#removeAllDlmsDataBtn,#removeDlmsConfirmation')].every(x=>x.disabled)")
        result["reset_screenshot"] = str(q.screenshot("blockc-managed-reset.png"))
        before = hashlib.sha256(db.read_bytes()).hexdigest()
        codes = {}
        for path in ("/api/clear_db_history", "/api/delete_study_history",
                     "/api/reset_quiz_library", "/api/remove_all_dlms_data",
                     "/settings/backup/restore/stage"):
            client = http.client.HTTPConnection("127.0.0.1", q.window.port, timeout=6)
            client.request("POST", path, headers={"Host": f"127.0.0.1:{q.window.port}",
                                              "X-DLMS-Desktop-Token": q.window.nonce})
            response = client.getresponse()
            codes[path] = response.status
            response.read()
            client.close()
        result["blocked_statuses"] = codes
        result["db_hash_unchanged"] = hashlib.sha256(db.read_bytes()).hexdigest() == before
        result["pass"] = bool(result["restore_notice"] and result["web_restore_form_absent"]
            and result["reset_notice"] and result["disabled_controls"] and
            all(code == 409 for code in codes.values()) and result["db_hash_unchanged"])
    finally:
        (q.paths["root"] / "blockc-managed-controls.json").write_text(json.dumps(result, indent=2) + "\n")
        q.close()
    print(json.dumps(result, indent=2))
    return 0 if result.get("pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
