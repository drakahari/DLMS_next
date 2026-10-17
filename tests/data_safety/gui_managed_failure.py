"""Actual Qt bounded storage/cleanup failures before a separate-process retry."""
import argparse
import json
import sqlite3
import time

from tests.gate1.qt_checks import QtChecks


def rows(path):
    with sqlite3.connect(path / "results.db") as conn:
        return [list(row) for row in conn.execute("SELECT id,title FROM quizzes ORDER BY id")]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    parser.add_argument("--kind", choices=("receipt", "cleanup"), required=True)
    args = parser.parse_args()
    q = QtChecks(args.profile, fail_import_receipt=args.kind == "receipt",
                 fail_import_cleanup=args.kind == "cleanup")
    root, backend = q.paths["root"], q.paths["backend"]
    token = (root / "gate-a-token.txt").read_text().strip()
    out = {"profile": args.profile, "kind": args.kind, "before": rows(backend)}
    try:
        q.go("/quiz-bundles/import/" + token)
        q.js("(()=>{let f=document.querySelector('form[action$=\"/confirm\"]');f.elements.confirm_import.checked=true;f.requestSubmit();return true})()")
        q.wait("!!document.querySelector('.portable-bundle-error')", 25)
        out["message"] = q.js("document.querySelector('.portable-bundle-error').innerText")
        out["screenshot"] = str(q.screenshot("gate-a-" + args.kind + "-failure.png", width=1050, height=780))
        out["after"] = rows(backend)
        op = next((root / "portable-import-operations").rglob(token + ".json"))
        out["operation"] = json.loads(op.read_text())
        out["journals"] = [p.name for p in (backend / ".quiz_publications").glob("publication_*.json")]
        if args.kind == "receipt":
            assert len(out["after"]) == 2 and len(out["journals"]) == 1
        else:
            assert len(out["after"]) == 2 and not out["journals"]
        assert out["operation"]["state"] == ("running" if args.kind == "receipt" else "cleanup_pending")
        assert "durable receipts" in out["message"]
        out["pass"] = True
    finally:
        (root / ("gate-a-" + args.kind + "-failure.json")).write_text(json.dumps(out, indent=2) + "\n")
        q.close()
    print(json.dumps({k: out.get(k) for k in ("profile", "kind", "pass", "message", "before", "after", "journals")}, indent=2))


if __name__ == "__main__":
    main()
