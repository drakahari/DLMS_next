"""Real Qt scoped-maintenance check; exact rows retained in ignored evidence."""
from __future__ import annotations

import argparse
import json
import sqlite3
import time
import traceback

from tests.gate1.qt_checks import QtChecks
from desktop.isolation import AREA
from desktop.maintenance import _file_inventory, _validate_files


TABLES = ("quizzes", "questions", "choices", "matching_pairs", "attempts", "attempt_answers",
          "missed_questions", "study_sessions", "study_responses", "study_legacy_responses",
          "learning_events", "certifications", "certification_training", "certification_cycles",
          "certification_allocations", "study_mistake_passes", "review_marks", "exam_plans")


def rows(db):
    with sqlite3.connect(db) as conn:
        return {name: conn.execute(f'SELECT * FROM "{name}" ORDER BY rowid').fetchall() for name in TABLES}


def validate(scope, before, after):
    if scope == "study":
        changed = {"study_sessions", "study_responses", "study_legacy_responses", "learning_events",
                   "study_mistake_passes"}
        assert not after["study_sessions"] and not after["study_responses"]
        assert after["attempts"] == before["attempts"] and after["missed_questions"] == before["missed_questions"]
        assert [r for r in after["learning_events"] if r[1] not in {"study_answer", "study_action"}] == [
            r for r in before["learning_events"] if r[1] not in {"study_answer", "study_action"}]
    elif scope == "learning":
        changed = {"learning_events", "study_legacy_responses"}
        assert not after["learning_events"]
        assert after["study_sessions"] == before["study_sessions"]
        assert after["study_responses"] == before["study_responses"]
        assert after["attempts"] == before["attempts"]
    elif scope == "quiz":
        changed = {"quizzes", "questions", "choices", "matching_pairs", "attempts", "attempt_answers",
                   "missed_questions", "study_sessions", "study_responses", "study_legacy_responses",
                   "learning_events", "study_mistake_passes", "review_marks"}
        assert not after["quizzes"] and not after["questions"] and not after["attempts"]
    elif scope == "settings":
        changed = set()
    elif scope == "source":
        changed = {"questions", "attempt_answers"}
    elif scope == "fresh":
        changed = set(TABLES)
        assert not after["quizzes"] and not after["attempts"] and not after["study_sessions"]
        assert before["quizzes"] and before["study_sessions"]
    else:
        raise AssertionError(f"No test oracle for {scope}")
    assert all(after[name] == before[name] for name in TABLES if name not in changed)
    return sorted(changed)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    parser.add_argument("--scope", choices=("study", "learning", "quiz", "source", "settings", "fresh"), required=True)
    parser.add_argument("--phase", choices=("run", "reopen"), required=True)
    a = parser.parse_args()
    q = QtChecks(a.profile, automated=True)
    db = q.paths["backend"] / "results.db"
    out = {"profile": a.profile, "scope": a.scope, "phase": a.phase}
    try:
        marker_path = q.paths["root"].parent.parent / "maintenance" / a.profile / "active.json"
        if a.phase == "run":
            before = rows(db)
            before_files = _file_inventory(q.paths["backend"])
            if not (q.paths["root"].parent.parent / "retained" / f"{a.profile}-before").is_dir():
                raise AssertionError("Verified outside-target recovery copy is required")
            if not q.window.begin_maintenance(a.scope, confirmed=True):
                raise AssertionError("Qt maintenance action refused")
            q.window.grab().save(str(q.paths["root"] / f"completion-{a.scope}-progress.png"))
            deadline = time.monotonic() + 40
            while time.monotonic() < deadline:
                q.delay(.15)
                if marker_path.exists():
                    marker = json.loads(marker_path.read_text())
                    if marker["phase"] == "browser_check_pending":
                        break
            else:
                raise TimeoutError("Maintenance did not reach separate-process browser checkpoint")
            after = rows(db)
            after_files = _file_inventory(q.paths["backend"])
            marker_recovery = AREA / "recovery" / a.profile / marker["operation_id"]
            _validate_files(a.scope, before_files, after_files, marker_recovery / "backend")
            if a.scope in {"quiz", "fresh"}:
                assert json.loads((q.paths["backend"] / "config/quizzes.json").read_text()) == []
            if a.scope in {"settings", "fresh"}:
                portal = json.loads((q.paths["backend"] / "config/portal.json").read_text())
                assert portal["theme"] == "purple-gold" and portal["hidden_quiz_folders"] == []
            safety_name = marker.get("safety_backup")
            safety_path = marker_recovery / safety_name if safety_name else None
            if a.scope != "exam" and (not safety_path or not safety_path.is_file()):
                raise AssertionError("Verified external safety ZIP is missing")
            out.update(marker=marker, changed_allowed=validate(a.scope, before, after),
                       row_counts_before={k: len(v) for k, v in before.items()},
                       row_counts_after={k: len(v) for k, v in after.items()},
                       file_changes={"removed": sorted(set(before_files)-set(after_files)),
                                     "added": sorted(set(after_files)-set(before_files)),
                                     "modified": sorted(k for k in set(before_files)&set(after_files)
                                                        if before_files[k] != after_files[k])},
                       retained_safety_sha256=marker.get("retained_safety_sha256"))
            out["pass"] = True
            (q.paths["root"] / f"completion-{a.scope}-before.json").write_text(json.dumps(before, indent=2) + "\n")
            (q.paths["root"] / f"completion-{a.scope}-after.json").write_text(json.dumps(after, indent=2) + "\n")
            (q.paths["root"] / f"completion-{a.scope}-before-files.json").write_text(json.dumps(before_files, indent=2) + "\n")
            (q.paths["root"] / f"completion-{a.scope}-after-files.json").write_text(json.dumps(after_files, indent=2) + "\n")
        else:
            before = json.loads((q.paths["root"] / f"completion-{a.scope}-before.json").read_text())
            after = json.loads(json.dumps(rows(db)))
            out["changed_allowed"] = validate(a.scope, before, after)
            out["marker_absent"] = not marker_path.exists()
            out["normal_page"] = q.js("location.pathname")
            out["pass"] = out["marker_absent"] and out["normal_page"] == "/"
            q.screenshot(f"completion-{a.scope}-reopen.png", width=970, height=720)
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
        traceback.print_exc()
    finally:
        (q.paths["root"] / f"completion-{a.scope}-{a.phase}.json").write_text(json.dumps(out, indent=2) + "\n")
        q.close()
    print(json.dumps({k: v for k, v in out.items() if k not in {"marker"}}, indent=2))
    return 0 if out.get("pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
