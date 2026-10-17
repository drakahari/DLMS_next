"""Published synthetic hotspot retains independent media after source clear."""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import traceback

from desktop.isolation import AREA
from tests.gate1.qt_checks import QtChecks


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rows(path):
    with sqlite3.connect(path) as conn:
        return {table: conn.execute(f'SELECT * FROM "{table}" ORDER BY rowid').fetchall()
                for table in ("quizzes", "questions", "choices", "study_sessions", "study_responses", "learning_events")}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--profile", required=True)
    a = p.parse_args()
    q = QtChecks(a.profile)
    out = {"profile": a.profile}
    try:
        prior = AREA / "retained" / f"{a.profile}-before" / "backend"
        current = q.paths["backend"]
        before, after = rows(prior / "results.db"), rows(current / "results.db")
        registry = json.loads((current / "config/quizzes.json").read_text())
        entry = next(item for item in registry if item["title"] == "Completion Hotspot — Practice")
        q.go("/quizzes/" + entry["html"])
        q.wait("document.querySelector('.study-mode-btn')?.disabled === false")
        q.js("document.querySelector('.study-mode-btn').click(); true")
        q.wait("document.querySelector('.hotspot-image')?.complete && document.querySelector('.hotspot-image')?.naturalWidth > 0")
        out["image_ui"] = json.loads(q.js("JSON.stringify({src:document.querySelector('.hotspot-image').getAttribute('src'),width:document.querySelector('.hotspot-image').naturalWidth,height:document.querySelector('.hotspot-image').naturalHeight})"))
        rel = out["image_ui"]["src"].removeprefix("/quiz-assets/")
        prior_asset = prior / "quiz_assets" / rel
        active_asset = current / "quiz_assets" / rel
        out["hashes"] = {"before": sha(prior_asset), "after": sha(active_asset),
                         "fixture": sha(AREA / "fixtures" / "gate1-ocr.png")}
        out["packs_removed"] = not list((current / "content_packs").glob("*/manifest.json"))
        out["same_records"] = {table: before[table] == after[table] for table in before}
        out["pass"] = (all(out["same_records"].values()) and out["packs_removed"]
                       and len(set(out["hashes"].values())) == 1)
        out["screenshot"] = str(q.screenshot("completion-source-media-after-clear.png", width=1000, height=800))
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
        traceback.print_exc()
    finally:
        (q.paths["root"] / "completion-source-media-after-clear.json").write_text(json.dumps(out, indent=2) + "\n")
        q.close()
    print(json.dumps(out, indent=2))
    return 0 if out.get("pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
