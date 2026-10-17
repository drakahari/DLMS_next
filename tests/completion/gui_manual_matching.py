"""Manual matching author/edit through the embedded Qt page and exact SQLite IDs."""
from __future__ import annotations

import argparse
import json
import sqlite3
import traceback

from tests.gate1.qt_checks import QtChecks


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--profile", required=True)
    p.add_argument("--verify-only", action="store_true")
    args = p.parse_args()
    name = args.profile
    q = QtChecks(name)
    out: dict = {"profile": name}
    db = q.paths["backend"] / "results.db"
    try:
        if args.verify_only:
            with sqlite3.connect(db) as conn:
                quiz = conn.execute("SELECT id FROM quizzes WHERE title='Completion Manual Matching'").fetchone()
                question = conn.execute("SELECT id,question_text,question_type,matching_direction FROM questions WHERE quiz_id=?", quiz).fetchone()
                pairs = conn.execute("SELECT id,pair_order,left_text,right_text FROM matching_pairs WHERE question_id=? ORDER BY pair_order", (question[0],)).fetchall()
            q.go(f"/edit_quiz/{quiz[0]}")
            out.update(quiz_id=quiz[0], question=question, pairs=pairs,
                       ui_value=q.js("document.querySelector('[name^=match_right_]')?.value"))
            out["pass"] = (question[1:] == ("Match the synthetic terms.", "matching", "definition_to_term")
                           and pairs == [(1, 1, "Alpha", "One edited"), (2, 2, "Beta", "Two"), (3, 3, "Gamma", "Three")]
                           and out["ui_value"] == "One edited")
            return 0 if out["pass"] else 1
        q.go("/create_short_quiz?count=1")
        q.js("""(()=>{const f=document.querySelector('form');
          f.elements.quiz_title.value='Completion Manual Matching';
          const block=document.querySelector('.question-block');
          const type=block.querySelector('.question-type');type.value='matching';changeQuestionType(type);
          block.querySelector('.question-text').value='Match the synthetic terms.';
          const rows=[...block.querySelectorAll('.build-match-pair')];
          [['Alpha','One'],['Beta','Two'],['Gamma','Three']].forEach((pair,i)=>{
            rows[i].querySelector('.match-left').value=pair[0];
            rows[i].querySelector('.match-right').value=pair[1];
          });
          rows[3].querySelector('.match-left').value='';
          rows[3].querySelector('.match-right').value='';
          block.querySelector('.matching-round-size').value='3';
          block.querySelector('.matching-direction').value='term_to_definition';
          return true})()""")
        q.click_css('button[type=submit]')
        q.wait("location.pathname.startsWith('/edit_quiz/')", 25)
        quiz_id = int(q.js("location.pathname.split('/').pop()"))
        with sqlite3.connect(db) as conn:
            question = conn.execute("SELECT id,question_text,question_type FROM questions WHERE quiz_id=?", (quiz_id,)).fetchone()
            pairs = conn.execute("SELECT id,pair_order,left_text,right_text FROM matching_pairs WHERE question_id=? ORDER BY pair_order", (question[0],)).fetchall()
        out.update(quiz_id=quiz_id, question=question, original_pairs=pairs)
        q.go(f"/edit_quiz/{quiz_id}")
        q.js("""(()=>{let f=document.getElementById('edit-quiz-form');
          const first=f.querySelector('[name^=match_right_]');first.value='One edited';
          f.querySelector('[name^=matching_direction_]').value='definition_to_term';
          return true})()""")
        q.click_css('#edit-quiz-form button.build-primary-button[type=submit]')
        q.wait("document.querySelector('[name^=match_right_]')?.value === 'One edited'", 20)
        with sqlite3.connect(db) as conn:
            edited = conn.execute("SELECT id,pair_order,left_text,right_text FROM matching_pairs WHERE question_id=? ORDER BY pair_order", (question[0],)).fetchall()
            current_question = conn.execute("SELECT id,question_text,question_type,matching_direction FROM questions WHERE id=?", (question[0],)).fetchone()
        out.update(edited_pairs=edited, edited_question=current_question)
        q.screenshot("completion-manual-matching.png", width=1040, height=760)
        out["pass"] = (question[1:] == ("Match the synthetic terms.", "matching")
                       and [(x[2], x[3]) for x in pairs] == [("Alpha", "One"), ("Beta", "Two"), ("Gamma", "Three")]
                       and [x[:3] for x in pairs] == [x[:3] for x in edited]
                       and edited[0][3] == "One edited" and edited[1:] == pairs[1:]
                       and current_question[3] == "definition_to_term")
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
        traceback.print_exc()
    finally:
        (q.paths["root"] / ("completion-manual-matching-reopen.json" if args.verify_only else "completion-manual-matching.json")).write_text(json.dumps(out, indent=2) + "\n")
        q.close()
    print(json.dumps(out, indent=2))
    return 0 if out.get("pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
