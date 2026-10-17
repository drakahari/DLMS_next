"""Separate-process Qt verification of the committed Study retry result."""
from __future__ import annotations

import argparse
import json
import sqlite3
from urllib.parse import urlsplit

from tests.gate1.qt_checks import QtChecks


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    name = parser.parse_args().profile
    q = QtChecks(name)
    root, db = q.paths["root"], q.paths["backend"] / "results.db"
    prior = json.loads((root / "data-safety-study-lost-ack.json").read_text())
    fixture = json.loads((root / "foundation-create.json").read_text())
    try:
        q.go(urlsplit(fixture["quiz_url"]).path)
        with sqlite3.connect(db) as conn:
            rows = conn.execute("SELECT * FROM study_responses WHERE event_id=?", (prior["event_id"],)).fetchall()
            count = conn.execute("SELECT count(*) FROM study_responses WHERE kind='response'").fetchone()[0]
        out = {"profile": name, "event_id": prior["event_id"], "exact_rows": len(rows),
               "response_count": count, "journal_empty": not list((root / "durable-actions").glob("*.json")),
               "library_page_loaded": q.js("location.pathname.startsWith('/quizzes/')"),
               "screenshot": str(q.screenshot("data-safety-study-lost-ack-reopen.png"))}
        out["pass"] = (out["exact_rows"] == 1 and
                       count == prior["response_count_before"] + 1 and out["journal_empty"] and
                       out["library_page_loaded"])
        (root / "data-safety-study-lost-ack-reopen.json").write_text(json.dumps(out, indent=2) + "\n")
        print(json.dumps(out, indent=2))
        return 0 if out["pass"] else 1
    finally:
        q.close()


if __name__ == "__main__":
    raise SystemExit(main())
