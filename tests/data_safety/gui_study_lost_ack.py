"""Qt Study: committed action, withheld reply, edited source, same-ID retry."""
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
    fixture = json.loads((root / "foundation-create.json").read_text())
    outcome = {"profile": name}
    try:
        with sqlite3.connect(db) as conn:
            response_count_before = conn.execute(
                "SELECT count(*) FROM study_responses WHERE kind='response'").fetchone()[0]
        q.go(urlsplit(fixture["quiz_url"]).path)
        if q.js("!!document.querySelector('.quiz-recovery-start-over')"):
            q.js("window.confirm=()=>true;document.querySelector('.quiz-recovery-start-over').click();true")
            q.wait("document.querySelector('.quiz-recovery-panel')?.hidden === true")
        q.js("document.querySelector('.study-mode-btn').click();true")
        q.wait("document.querySelector('button.choice') !== null")
        q.js("""window.__realFetch=window.fetch.bind(window);
            window.__capturedStudy=null; window.__releaseStudy=null;
            window.fetch=async (...args)=>{
              if(String(args[0]).includes('/_desktop/recovery/action') && !window.__capturedStudy){
                const envelope=JSON.parse(args[1].body);
                const reply=await window.__realFetch(...args);
                window.__capturedStudy={status:reply.status,envelope};
                return await new Promise(resolve=>{
                  window.__releaseStudy=()=>resolve(new Response(JSON.stringify({error:'Synthetic lost reply'}),
                    {status:503,headers:{'Content-Type':'application/json'}}));
                });
              }
              return window.__realFetch(...args);
            }; true""")
        q.js("document.querySelector('button.choice').click();true")
        q.wait("window.__capturedStudy !== null && window.__releaseStudy !== null", 20)
        captured = json.loads(q.js("JSON.stringify(window.__capturedStudy)"))
        event_id = captured["envelope"]["payload"]["eventId"]
        with sqlite3.connect(db) as conn:
            conn.row_factory = sqlite3.Row
            saved = [dict(row) for row in conn.execute(
                "SELECT * FROM study_responses WHERE event_id=?", (event_id,))]
            assert captured["status"] == 200 and len(saved) == 1
            qid = conn.execute("SELECT id FROM questions WHERE quiz_id=? ORDER BY question_number LIMIT 1",
                               (fixture["quiz_id"],)).fetchone()[0]
            conn.execute("UPDATE questions SET question_text=question_text || ' [synthetic edit]' WHERE id=?", (qid,))
            conn.commit()
        assert not list((root / "durable-actions").glob("*.json"))
        q.js("window.__releaseStudy();true")
        q.wait("document.querySelector('#studyLearningEventStatus')?.innerText.includes('awaiting save confirmation')", 20)
        outcome["lost_reply_message"] = q.js("document.querySelector('#studyLearningEventStatus').innerText")
        assert q.js("[...studyLearningEventSaves.keys()][0]") == event_id
        q.js("document.querySelector('#studyLearningEventStatus .study-learning-save-retry').click();true")
        q.wait("studyLearningEventSaves.size===0", 20)
        with sqlite3.connect(db) as conn:
            conn.row_factory = sqlite3.Row
            after = [dict(row) for row in conn.execute(
                "SELECT * FROM study_responses WHERE event_id=?", (event_id,))]
            total = conn.execute("SELECT count(*) FROM study_responses WHERE kind='response'").fetchone()[0]
        outcome.update(event_id=event_id, original_reply_status=captured["status"],
                       same_row=after == saved, response_count=total,
                       journal_empty=not list((root / "durable-actions").glob("*.json")),
                       retry_message=q.js("document.querySelector('#studyLearningEventStatus')?.innerText"),
                       screenshot=str(q.screenshot("data-safety-study-lost-ack.png")))
        outcome["response_count_before"] = response_count_before
        assert after == saved and total == response_count_before + 1 and outcome["journal_empty"]
        outcome["pass"] = True
        return 0
    except Exception as exc:
        outcome.update(pass_=False, error=f"{type(exc).__name__}: {exc}")
        raise
    finally:
        (root / "data-safety-study-lost-ack.json").write_text(json.dumps(outcome, indent=2) + "\n")
        print(json.dumps(outcome, indent=2))
        q.close()


if __name__ == "__main__":
    raise SystemExit(main())
