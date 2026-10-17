"""Read-only semantic audit of the interrupted ordinary receiver pre/post retry."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
import zipfile

from desktop.isolation import AREA


def matching(backend: Path, title: str) -> list[list]:
    with sqlite3.connect(backend / "results.db") as conn:
        quiz = conn.execute("SELECT id FROM quizzes WHERE title=?", (title,)).fetchone()
        assert quiz is not None, title
        questions = conn.execute("SELECT id,question_type FROM questions WHERE quiz_id=? ORDER BY question_number", quiz).fetchall()
        assert len(questions) == 1 and questions[0][1] == "matching"
        return [list(row) for row in conn.execute(
            "SELECT pair_order,left_text,right_text FROM matching_pairs WHERE question_id=? ORDER BY pair_order",
            (questions[0][0],))]


def audit(backend: Path, title: str, expected: dict) -> dict:
    pairs = matching(backend, title)
    expected_pairs = [[index, pair["left"], pair["right"]]
                      for index, pair in enumerate(expected["questions"][0]["pairs"], 1)]
    registry = json.loads((backend / "config/quizzes.json").read_text())
    entry = next(item for item in registry if item["title"] == title)
    html = backend / "quizzes" / entry["html"]
    data = backend / "data" / entry["html"].replace(".html", ".json")
    return {"title": title, "pairs": pairs, "expected_pairs": expected_pairs,
            "registry_id": entry["id"], "html_exists": html.is_file(), "json_exists": data.is_file(),
            "pass": pairs == expected_pairs and html.is_file() and data.is_file()}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    args = parser.parse_args()
    assert args.profile.startswith("datasafety")
    root = AREA / "profiles" / args.profile
    pre = AREA / "retained" / f"{args.profile}-before-retry" / "backend"
    backend = root / "backend"
    with zipfile.ZipFile(AREA / "fixtures/data-safety-two.zip") as archive:
        manifest = json.loads(archive.read("dlms-quiz-bundle.json"))
    first, second = manifest["quizzes"]
    out = {
        "before_retry_first": audit(pre, first["title"], first),
        "after_retry_first": audit(backend, first["title"], first),
        "after_retry_duplicate": audit(backend, first["title"] + " (Imported)", first),
        "after_retry_second": audit(backend, second["title"], second),
    }
    ids = [item["registry_id"] for item in out.values()]
    out["pass"] = all(item["pass"] for item in out.values()) and len(set(ids)) == 3
    output = root / "data-safety-ordinary-semantic-audit.json"
    output.write_text(json.dumps(out, indent=2) + "\n")
    print(json.dumps(out, indent=2))
    return 0 if out["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
