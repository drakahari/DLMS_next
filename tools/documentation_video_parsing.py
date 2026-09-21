"""DLMS-152 opt-in recipes within the existing isolated capture lifecycle."""
import json
from pathlib import Path

SAMPLE = Path(__file__).resolve().parents[1] / "docs/demo-video/series/parsing-pasted-text/sample.txt"
TITLE = "Structured Text Practice"


def frames(frame):
    rows = [
        (301, "parsing-settings", "Parsing defaults", "/settings/parsing", "settings", ".settings-detail-card"),
        (302, "pasted-source", "Original two-question source", "/paste", "source", ".build-workspace"),
        (303, "paste-cleanup", "Remove repeated source labels", "/paste", "cleanup", ".build-section:nth-of-type(2)"),
        (304, "paste-preview", "Preview source before parsing", "/paste", "preview", "#origBox"),
        (305, "paste-differences", "Review actual cleanup differences", "/paste", "diff", "#diffPanel"),
        (306, "parsed-library", "Published quiz in the library", "/paste", "library", "#quizList"),
        (307, "parsed-single-answer", "Verify the single answer", "/paste", "single", "#qHeader"),
        (308, "parsed-multiple-answer", "Verify both correct answers", "/paste", "multi", "#qHeader"),
    ]
    return tuple(frame(n, slug, title, route, "document.querySelector('form')",
                       action="parsing-"+action, focus=focus,
                       fixture="Original sample.txt; real paste preview and publication in disposable data root.",
                       state=title) for n, slug, title, route, action, focus in rows)


def prepare(browser, item, metadata, data_root):
    action = item.action.removeprefix("parsing-")
    # Set the actual defaults through the real settings form, even when a
    # preceding capture changed settings. Never touch an existing user's root.
    if not (data_root.parent / "video-capture-owned").is_file():
        raise RuntimeError("Parsing recipes require an isolated capture root")
    browser.navigate(browser.evaluate("location.origin") + "/settings/parsing")
    browser.wait_for("document.querySelector('input[name=csrf_token]')")
    browser.evaluate("""(() => {
        const form=document.querySelector('form[action="/settings/parsing/save"]');
        for(const [key,value] of Object.entries({show_confidence:true,enable_regex_replace:false,
            auto_bom_clean:false,enable_show_invisibles:true})) form.elements[key].checked=value;
        form.requestSubmit(); return true;
    })()""")
    browser.wait_for("location.search.includes('saved=1')")
    if action == "settings":
        return
    browser.navigate(browser.evaluate("location.origin") + "/paste")
    browser.wait_for("document.querySelector('.build-workspace input[name=csrf_token]')")
    values = {"quiz_title": TITLE, "exam_minutes": "15", "quiz_text": SAMPLE.read_text().strip(),
              "strip_text": "" if action == "source" else "Practice copy"}
    browser.evaluate("""(() => {
        const form=document.querySelector('.build-workspace');
        for(const [key,value] of Object.entries(%s)) form.elements[key].value=value;
        return true;
    })()""" % json.dumps(values))
    if action in ("source", "cleanup"):
        return
    browser.evaluate("document.querySelector('.build-workspace').requestSubmit();true")
    browser.wait_for("document.getElementById('cleanBox') && typeof toggleDiff==='function'")
    if action == "preview":
        return
    if action == "diff":
        browser.evaluate("toggleDiff();true")
        return
    browser.wait_for("document.querySelector('form[action=\"/process_paste\"] input[name=csrf_token]')")
    browser.evaluate("document.querySelector('form[action=\"/process_paste\"]').requestSubmit();true")
    browser.wait_for("location.pathname==='/library' && document.getElementById('quizList')")
    # Find the newest actual publication by its title; IDs remain data-root local.
    route = browser.evaluate("""(() => {
        const rows=[...document.querySelectorAll('#quizList .library-quiz-card')].filter(el=>el.textContent.includes(%s));
        const row=rows.at(-1);
        const link=row && row.querySelector('a[href^="/quizzes/"]');
        if(!link) throw Error('Published quiz missing from library');
        return link.getAttribute('href');
    })()""" % json.dumps(TITLE))
    if action == "library":
        # Use the existing library search to display only this tutorial's output.
        browser.evaluate("""(() => {
            const search=document.querySelector('#librarySearch');
            if(!search) throw Error('Library search missing');
            search.value=%s; search.dispatchEvent(new Event('input',{bubbles:true}));return true;
        })()""" % json.dumps(TITLE))
        return
    browser.navigate(browser.evaluate("location.origin")+route)
    browser.wait_for("typeof quizRecoveryReady!=='undefined' && quizRecoveryReady && quiz.length===2")
    browser.click(".study-mode-btn")
    if action == "multi":
        browser.click("#nextBtn")
        browser.wait_for("index===1")
        browser.click("#choices .choice[data-index='0']")
        browser.click("#choices .choice[data-index='2']")
    else:
        browser.click("#choices .choice[data-index='0']")
    browser.wait_for("[...studyLearningEventSaves.values()].every(r=>r.state==='saved')")
