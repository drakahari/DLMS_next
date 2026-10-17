"""Actual Qt: server accepted Review evidence survives browser read failure."""
from __future__ import annotations

import argparse
import json
import traceback

from tests.gate1.qt_checks import QtChecks


def main() -> int:
    p = argparse.ArgumentParser(); p.add_argument("--profile", required=True)
    args = p.parse_args()
    q = QtChecks(args.profile)
    result = {"profile": args.profile}
    try:
        from PySide6.QtWebEngineCore import QWebEngineScript
        script = QWebEngineScript()
        script.setName("synthetic-review-storage-read-failure")
        script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
        script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
        script.setSourceCode("""(()=>{const original=Storage.prototype.getItem;
          Storage.prototype.getItem=function(key){
            if(this===window.localStorage && String(key).startsWith('dlms.markAction.'))
              throw new Error('Synthetic localStorage read failure');
            return original.call(this,key);
          }})()""")
        q.window.profile.scripts().insert(script)
        before = len(list((q.paths["root"] / "pending-requests").glob("*.json")))
        q.go("/marked-questions")
        q.wait("document.getElementById('markActionStatus')?.innerText.includes('retained Review request')", 15)
        result["message"] = q.js("document.getElementById('markActionStatus').innerText")
        result["retry_visible"] = q.js("!document.getElementById('retryMarkAction').hidden")
        result["pending_unchanged"] = len(list((q.paths["root"] / "pending-requests").glob("*.json"))) == before
        q.js("document.getElementById('markActionStatus').scrollIntoView({block:'center'}); true")
        result["screenshot"] = str(q.screenshot("blockb-review-storage-recovery.png"))
        result["status"] = "pass" if before > 0 and result["retry_visible"] and result["pending_unchanged"] else "fail"
    except Exception as exc:
        result["status"] = "error"; result["error"] = f"{type(exc).__name__}: {exc}"
        traceback.print_exc()
    finally:
        (q.paths["root"] / "blockb-review-storage.json").write_text(json.dumps(result, indent=2) + "\n")
        q.close()
    print(json.dumps(result, indent=2), flush=True)
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
