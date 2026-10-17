"""Actual Qt WebEngine foundation exercise with neutral disposable content.

Run with the project's virtualenv and an explicit disposable --profile.
Each phase is a separate process. No browser automation or installed DLMS is used.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sqlite3
import sys
import time

from desktop.isolation import PROJECT, isolated_environment, profile_paths


def count_saved(db: Path) -> int:
    with sqlite3.connect(db) as conn:
        return conn.execute("SELECT count(*) FROM study_responses WHERE kind='response'").fetchone()[0]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    parser.add_argument("--phase", choices=("create", "reopen"), required=True)
    args = parser.parse_args()
    paths = profile_paths(args.profile)
    env = isolated_environment(paths)
    os.environ.clear()
    os.environ.update(env)
    os.environ["PYTHONNOUSERSITE"] = "1"

    from PySide6.QtCore import QTimer, QUrl
    from PySide6.QtWidgets import QApplication
    from desktop.shell import DesktopWindow

    application = QApplication(sys.argv[:1])
    window = DesktopWindow(paths, args.profile)
    window.show()
    result = {"profile": args.profile, "phase": args.phase, "status": "running"}
    active_timer = None
    deadline = time.monotonic() + 35

    def finish(ok: bool, reason: str = ""):
        nonlocal active_timer
        if active_timer is not None:
            active_timer.stop()
        result["status"] = "pass" if ok else "fail"
        result["reason"] = reason
        result["startup_ms"] = window.ready_ms
        out = paths["root"] / f"foundation-{args.phase}.json"
        out.write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result, indent=2), flush=True)
        application.quit()

    def wait_js(expression, callback, label):
        nonlocal active_timer
        if active_timer is not None:
            active_timer.stop()
        timer = QTimer()
        active_timer = timer
        busy = [False]

        def check():
            if time.monotonic() > deadline:
                finish(False, f"Timed out waiting for {label}")
                return
            if window.view is None or busy[0]:
                return
            busy[0] = True

            def answer(value):
                busy[0] = False
                if value:
                    timer.stop()
                    callback(value)

            window.view.page().runJavaScript(expression, answer)

        timer.timeout.connect(check)
        timer.start(180)
        check()

    def wait_saved():
        nonlocal active_timer
        timer = QTimer()
        active_timer = timer

        def check():
            if time.monotonic() > deadline:
                finish(False, "Study response was not saved")
            elif count_saved(paths["backend"] / "results.db") >= 1:
                timer.stop()
                result["saved_responses"] = count_saved(paths["backend"] / "results.db")
                window.view.page().runJavaScript("document.getElementById('nextBtn').click()")
                wait_js("document.body.innerText.includes('Which shape has three sides?')", capture_create, "question two")

        timer.timeout.connect(check)
        timer.start(180)
        check()

    def capture_create(_):
        window.view.page().runJavaScript(
            "JSON.stringify({url:location.href,checkpoint:localStorage.getItem('dlms.quiz-progress.v1:'+window.QUIZ_ID),text:document.body.innerText.slice(0,1100)})",
            lambda value: saved_create(value),
        )

    def saved_create(value):
        parsed = json.loads(value or "{}")
        result["quiz_url"] = parsed.get("url")
        result["checkpoint_present"] = bool(parsed.get("checkpoint"))
        result["question_two_visible"] = "Which shape has three sides?" in parsed.get("text", "")
        result["quiz_id"] = sqlite3.connect(paths["backend"] / "results.db").execute(
            "SELECT id FROM quizzes WHERE title='Gate 1 Neutral Quiz' ORDER BY id DESC LIMIT 1"
        ).fetchone()[0]
        QTimer.singleShot(900, lambda: screenshot_and_finish("foundation-study.png", result["checkpoint_present"] and result["question_two_visible"]))

    def screenshot_and_finish(name, ok):
        result["screenshot"] = str(paths["root"] / name)
        window.view.grab().save(result["screenshot"])
        finish(ok, "Study response and browser checkpoint saved" if ok else "Missing Study checkpoint or question two")

    def study_started(_):
        window.view.page().runJavaScript("document.querySelector('button.choice')?.click()")
        wait_saved()

    def quiz_ready(_):
        window.view.page().runJavaScript("document.querySelector('.study-mode-btn').click()")
        wait_js("document.querySelector('button.choice')?.innerText.includes('Three')", study_started, "Study question one")

    def quiz_loaded(link):
        result["quiz_url"] = f"http://127.0.0.1:{window.port}" + link
        window.view.setUrl(QUrl(result["quiz_url"]))
        wait_js("location.pathname.startsWith('/quizzes/') && quizRecoveryReady === true && quiz.length === 4 && document.querySelector('.study-mode-btn')?.disabled === false", quiz_ready, "quiz readiness")

    def library_loaded(_):
        wait_js("document.querySelector('a[href^=\"/quizzes/\"]')?.getAttribute('href')", quiz_loaded, "library quiz link")

    def import_done(value):
        detail = json.loads(value)
        result["import_http_status"] = detail["status"]
        if detail["status"] != 200:
            finish(False, f"Synthetic import returned {detail['status']}")
            return
        window.view.setUrl(QUrl(f"http://127.0.0.1:{window.port}/library"))
        wait_js("location.pathname === '/library' && document.body.innerText.includes('Gate 1 Neutral Quiz')", library_loaded, "imported library")

    def begin_import(_):
        text = (PROJECT / "fixtures" / "gate1-neutral-quiz.txt").read_text()
        script = """(async()=>{const data=TEXT; const form=new FormData();
        form.append('quiz_title','Gate 1 Neutral Quiz');
        form.append('file',new File([data],'neutral.txt',{type:'text/plain'}));
        const cookie=document.cookie.split('; ').find(x=>x.startsWith('dlms_csrf_token='));
        form.append('csrf_token',decodeURIComponent(cookie?.split('=')[1]||''));
        const response=await fetch('/process',{method:'POST',body:form,credentials:'same-origin'});
        window.__gate1Import=JSON.stringify({status:response.status,url:response.url});
        })()""".replace("TEXT", json.dumps(text))
        window.view.page().runJavaScript(script)
        wait_js("window.__gate1Import||null", import_done, "browser-side synthetic import")

    def begin_reopen(_):
        previous = json.loads((paths["root"] / "foundation-create.json").read_text())
        result["quiz_url"] = previous["quiz_url"]
        result["saved_responses"] = count_saved(paths["backend"] / "results.db")
        window.view.setUrl(QUrl(previous["quiz_url"]))
        wait_js("location.pathname.startsWith('/quizzes/') && quizRecoveryReady === true && quiz.length === 4 && document.querySelector('.study-mode-btn')?.disabled === false", reopen_ready, "reopened quiz")

    def reopen_ready(_):
        window.view.page().runJavaScript(
            "JSON.stringify({checkpoint:localStorage.getItem('dlms.quiz-progress.v1:'+window.QUIZ_ID),resume:document.querySelector('.quiz-recovery-resume')?.innerText||'',text:document.body.innerText.slice(0,950)})",
            reopen_state,
        )

    def reopen_state(value):
        state = json.loads(value or "{}")
        result["checkpoint_present"] = bool(state.get("checkpoint"))
        result["resume_control"] = state.get("resume", "")
        result["resume_screen_text"] = state.get("text", "")
        if not result["checkpoint_present"] or not result["resume_control"]:
            finish(False, "Browser checkpoint or Resume control missing after separate-process restart")
            return
        window.view.page().runJavaScript("document.querySelector('.quiz-recovery-resume').click()")
        wait_js("document.body.innerText.includes('Which shape has three sides?')", resumed, "resumed question two")

    def resumed(_):
        result["resumed_question_two"] = True
        QTimer.singleShot(850, lambda: screenshot_and_finish("foundation-reopen.png", result["saved_responses"] >= 1))

    def start_scenario():
        if window.view is None:
            QTimer.singleShot(100, start_scenario)
            return
        if args.phase == "create":
            wait_js("location.pathname === '/' && document.readyState === 'complete'", begin_import, "dashboard")
        else:
            wait_js("location.pathname === '/' && document.readyState === 'complete'", begin_reopen, "dashboard")

    window.start()
    QTimer.singleShot(80, start_scenario)
    application.exec()
    window.close()
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
