"""Real Qt retry of an already committed Study or Exam identity after cleanup."""
from __future__ import annotations

import argparse
import json
import sqlite3
from urllib.parse import urlsplit

from tests.gate1.qt_checks import QtChecks


def count(db, kind, identifier):
    with sqlite3.connect(db) as conn:
        if kind == "study":
            return conn.execute("SELECT count(*) FROM study_responses WHERE event_id=?", (identifier,)).fetchone()[0]
        columns = {row[1] for row in conn.execute("PRAGMA table_info(attempts)")}
        identity = "attempt_id" if "attempt_id" in columns else "id"
        return conn.execute(f"SELECT count(*) FROM attempts WHERE CAST({identity} AS TEXT)=?", (identifier,)).fetchone()[0]


def request(q, envelope):
    q.js("window.__identityResult=null; fetch('/_desktop/recovery/action', {method:'POST', "
         "headers:{'Content-Type':'application/json','X-DLMS-Recovery-Client':'1'}, "
         f"body:JSON.stringify({json.dumps(envelope)})}}).then(async r=>window.__identityResult={{status:r.status,body:await r.json()}})"
         ".catch(e=>window.__identityResult={error:String(e)}); true")
    q.wait("window.__identityResult !== null", 15)
    return json.loads(q.js("JSON.stringify(window.__identityResult)"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    parser.add_argument("--kind", choices=("study", "exam"), required=True)
    parser.add_argument("--phase", choices=("create", "retry"), required=True)
    args = parser.parse_args()
    q = QtChecks(args.profile, fail_action_cleanup=args.phase == "create")
    try:
        root = q.paths["root"]
        db = q.paths["backend"] / "results.db"
        quiz = urlsplit(json.loads((root / "foundation-create.json").read_text())["quiz_url"]).path
        q.go(quiz)
        if args.phase == "create":
            if args.kind == "study":
                q.js("document.querySelector('.study-mode-btn').click(); true")
            else:
                q.js("document.querySelector('.exam-mode-btn').click(); true")
            q.wait("document.querySelector('button.choice') !== null")
            q.js("document.querySelector('button.choice').click(); true")
            if args.kind == "exam":
                q.js("window.confirm=()=>true; document.getElementById('submitBtn').click(); true")
            q.wait("document.body.innerText.includes('cleanup is pending')", 20)
            files = list((root / "durable-actions").glob("*.json"))
            assert len(files) == 1
            record = json.loads(files[0].read_text())
            (root / f"{args.kind}-identity-envelope.json").write_text(json.dumps({
                "kind": args.kind, "payload": record["payload"], "fingerprint": record["fingerprint"]
            }))
            result = {"phase": "create", "id": record["id"], "durable_count": count(db, args.kind, record["id"])}
        else:
            envelope = json.loads((root / f"{args.kind}-identity-envelope.json").read_text())
            identifier = envelope["payload"]["eventId" if args.kind == "study" else "attemptId"]
            before = count(db, args.kind, identifier)
            exact = request(q, envelope)
            changed = json.loads(json.dumps(envelope))
            if args.kind == "study":
                changed["payload"]["sequence"] += 1
            else:
                changed["payload"]["score"] += 1
            conflict = request(q, changed)
            result = {"phase": "retry", "id": identifier, "before": before,
                      "exact": exact, "conflict": conflict,
                      "after": count(db, args.kind, identifier),
                      "journal": [p.name for p in (root / "durable-actions").glob("*.json")],
                      "screenshot": str(q.screenshot(f"{args.kind}-identity-retry.png"))}
            assert before == result["after"] == 1
            assert exact["status"] == 200 and exact["body"].get("already_recorded") is True
            assert conflict["status"] == 409 and not result["journal"]
        (root / f"{args.kind}-identity-{args.phase}.json").write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result, indent=2))
        return 0
    finally:
        q.close()


if __name__ == "__main__":
    raise SystemExit(main())
