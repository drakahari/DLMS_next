#!/usr/bin/env python3
"""Video capture: isolated original content, configurable theme, 1080p Firefox.

No arguments captures the complete plan; preparation runs should use --only.
--list never starts the application or browser. See docs/demo-video/README.md.
"""
from __future__ import annotations
import argparse
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

import capture_user_manual_screenshots as manual
from demo_video_fixture import FIXTURE_VERSION, seed

ROOT = manual.ROOT
PROJECT = ROOT / 'docs/demo-video'
WIDTH, HEIGHT = 1920, 1080
THEMES = {'Purple & Gold':'purple-gold', 'Light':'light', 'Dark':'dark', 'Maroon & Gold':'maroon-gold'}

@dataclass(frozen=True)
class Frame:
    id: str
    filename: str
    title: str
    route: str
    ready: str
    state: str
    fixture: str
    focus: str = ''
    action: str = ''
    seconds: int = 10
    essential: bool = True
    scroll_margin: int = 24


def frame(number, slug, title, route, ready="document.querySelector('main')", state='Default controls; no search; no open dialogs.', fixture='Base synthetic library.', **kwargs):
    return Frame(f'{number:03}', f'{number:03}-{slug}.png', title, route, ready, state, fixture, **kwargs)


def addition(identifier, slug, title, route, ready="document.querySelector('main')", state='Default controls; no search; no open dialogs.', fixture='Base synthetic library.', **kwargs):
    identifier = str(identifier).strip().upper()
    return Frame(identifier, f'{identifier}-{slug}.png', title, route, ready, state, fixture, **kwargs)


def normalized_frame_id(value):
    raw = str(value).strip().upper()
    match = re.fullmatch(r'(\d+)([A-Z]*)', raw)
    return match[1].zfill(3) + match[2] if match else raw

DASH_READY = "document.getElementById('dailyReviewCount') && !['Loading…',''].includes(document.getElementById('dailyReviewCount').textContent.trim())"
LI_READY = "document.querySelector('#liRows tr') && !document.getElementById('liScopeSummary').textContent.includes('Loading')"
QUIZ_READY = "typeof quizRecoveryReady !== 'undefined' && quizRecoveryReady === true"
SCHEDULE_READY = "document.getElementById('nrsDue')?.textContent !== '—' && document.querySelector('#nrsRows tr')"
V2_FRAMES = (
    frame(1,'dashboard','A personal learning workspace','/',DASH_READY,fixture='Evidence, due questions, no browser Resume.'),
    frame(2,'todays-review','Choose a useful next step','/',DASH_READY,focus='.daily-review-panel',fixture='Real server-derived recommendations; no fabricated ranking.',seconds=12),
    frame(3,'quiz-library','Organize original study content','/library',focus='#quizList',action='library-overview',state='Visible; no Smart View/search; Core Skills expanded; all other groups collapsed.'),
    frame(4,'learning-scope','Choose active material','/learning-scope',state='Past Projects excluded; other folders and Uncategorized included.',fixture='One excluded saved source; no hiding or deletion.',seconds=12),
    frame(5,'scope-library','Saved does not mean active','/library',focus='#quizList',action='scope-folder',state='Visible; Past Projects expanded and excluded from Learning Scope; other groups collapsed.'),
    frame(6,'build-quiz','Bring your own content','/upload'),
    frame(7,'pdf-import','PDF and image import','/pdf-import',state='Empty form; no extraction claims.',seconds=10),
    frame(8,'ocr-source','An original image as input','/pdf-import',focus='.pdf-ocr-import-panel',action='ocr',state='Original study-skills.png selected; rights confirmed; not submitted.',fixture='Pillow-rendered original text; no external content.',seconds=12),
    frame(9,'review-repair','Inspect before publishing','/pdf-import/review/video_review',focus='.pdf-import-summary-grid',state='Seeded staged draft: one complete, one incomplete; nothing published.',fixture='Original synthetic staged parser draft; not a claim of OCR accuracy.',seconds=12),
    frame(10,'repair-detail','Missing answers remain your decision','/pdf-import/review/video_review',focus='.pdf-import-filter-row',action='incomplete',state='Incomplete filter selected; recovered question visible; no answer invented.',fixture='Same staged draft.',seconds=10),
    frame(11,'study-start','Start a self-paced session','@critical_quiz',QUIZ_READY,action='study',focus='.active-quiz-logo-banner',state='Study Mode, question 1; no answer selected.',fixture='Network Troubleshooting source quiz.'),
    frame(12,'study-feedback','Learn from an answer','@critical_quiz',QUIZ_READY,action='feedback',focus='.quiz-toolbar',state='Study Mode question 1, B selected; incorrect feedback visible.',fixture='Original network question.',seconds=12),
    frame(13,'question-tools','Use optional question tools','@critical_quiz',QUIZ_READY,action='feedback-complete',focus='.quiz-toolbar',scroll_margin=8,state='Correct answer selected after feedback; explanation and Question Tools visible; no provider opened.',fixture='Same original source question.',seconds=14),
    frame(14,'learning-intelligence','See the learning pattern','/learning-intelligence',LI_READY,state='All concepts, empty search; mastery explanation closed; scope summary visible.',fixture='Strong Data Safety; declining Networking; improving Access Control; low-evidence Cloud.',seconds=14),
    frame(15,'concept-trends','Compare evidence and trends','/learning-intelligence',LI_READY,focus='#liToolbar',state='All concepts, no filter; compare actual calculated values.',fixture='18 baseline responses per established concept plus demonstrated Study saves; one Cloud response.',seconds=14),
    frame(16,'mastery-model','Explainable intelligence','/learning-intelligence',LI_READY,action='model',state='How mastery works dialog open.',fixture='Same evidence; no invented percentages.',seconds=12),
    frame(17,'learning-profile','Turn results into a next action','/learning-profile',"document.getElementById('lpAccuracy')?.textContent !== '—'",fixture='Scoped evidence.',essential=False),
    frame(18,'review-schedule','Review when it is due','/review-schedule',SCHEDULE_READY,state='Queue expanded; All status; blank search; default batch size.',fixture='Recent and older source evidence; unseen Cloud questions.',seconds=12),
    frame(19,'due-queue','Inspect the source question queue','/review-schedule',SCHEDULE_READY,focus='#nrsQueuePanel',action='due',state='Overdue status; queue expanded; empty search.',fixture='Real overdue source backlog; Due now is a separate status.',seconds=12),
    frame(20,'topic-retention','Question timing and topic retention','/review-schedule',SCHEDULE_READY,action='collapse-queue',focus='.review-schedule-summary:not(.native-review-summary)',state='Question Queue collapsed; Topic Retention visible.',fixture='Derived concept evidence.',essential=False),
    frame(21,'generated-practice','A review built from your sources','/library',focus='#quizList',action='active-folder',state='Visible Library; active Generated Practice expanded; other groups collapsed.',fixture='Adaptive active plus a retained completed Smart Review.',seconds=12),
    frame(22,'source-provenance','Keep the connection to source material','/library?view=visible&smart=generated-practice',action='provenance',focus='.library-smart-active',state='Generated Practice Smart View (all review sessions); first source disclosure expanded; normal folder grouping.',fixture='Question Identity v2 payloads from three real source quiz rows.',seconds=12),
    frame(23,'finish-review','Explicitly close the review','@adaptive_quiz',QUIZ_READY,action='finish-ready',focus='.quiz-toolbar',scroll_margin=8,state='All 3 questions answered and saved; final question; Finish Review not yet clicked.',fixture='Fresh Adaptive Study session; completion marker absent.',seconds=12),
    frame(24,'review-finished','Finish with acknowledged saves','@adaptive_quiz',QUIZ_READY,action='finish',focus='.active-quiz-logo-banner',state='Finish Review succeeded; success status visible; checkpoint cleared.',fixture='Real Study saves and server completion handshake.',seconds=10),
    frame(25,'completed-practice','Completed is retained, not deleted','/library',action='completed',focus='#quizList',state='Completed Generated Practice expanded; other groups collapsed; quizzes playable.',fixture='Seeded retained Smart Review; Adaptive also completed during a full run.',seconds=12),
    frame(26,'history','Keep a record of learning','/history',"document.getElementById('historyTotalAttempts')?.textContent !== '—'",fixture='18 original synthetic Exam attempts, Demo Learner.'),
    frame(27,'analytics','Look back across your history','/dashboard',"Number(document.getElementById('analyticsTotalAttempts')?.textContent) === 18",fixture='Same completed attempts; all-history view.',seconds=10),
    frame(28,'bundles','Move content without moving personal history','/quiz-bundles',focus='.portable-bundle-workflows',state='Export/import landing; source candidates only; no upload yet.',fixture='Source quizzes eligible; generated sessions excluded.',seconds=12),
    frame(29,'duplicates','Find duplicate source questions','/library/duplicates',focus='.duplicate-question-summary',state='All types; page 1; small result groups expanded by current product default; no search.',fixture='One deliberate exact duplicate across source quizzes.'),
    frame(30,'duplicate-detail','Compare before editing','/library/duplicates?result_type=exact&search=risky',focus='.duplicate-question-group',state='Exact filter; search risky; one matching group expanded; page 1; no automatic deletion.',fixture='Change Readiness Checklist and Everyday Data Safety.',seconds=12),
    frame(31,'anki-tools','Take study material further','/anki',state='Tools overview; no external program launched.'),
    frame(32,'anki-selection','Choose an export deliberately','/anki/custom',"document.getElementById('customAnkiForm')",focus='.anki-custom-quiz-filter',action='anki-select',state='Filter Everyday Data Safety; expand source and select its first question; no download.',fixture='Original sources and missed records.',seconds=10),
    frame(33,'external-ai','An optional external workflow','/external-ai/quiz-builder',"document.getElementById('externalAiBuilderForm')",state='Provider-neutral builder; no provider opened; no claim of local AI.',essential=False),
    frame(34,'backup','Preserve your local workspace','/settings/backup',state='Backup/restore overview; no restore/reset initiated.',seconds=12),
    frame(35,'settings','Your workspace, your choices','/settings',state='Purple & Gold; isolated demo identity; no destructive action.',essential=False),
    frame(36,'closing-dashboard','Return to the next useful step','/',DASH_READY,fixture='No unwanted Resume; server recommendations may remain after a review.',seconds=10),
)

V3_ADDITIONS = (
    addition('013A','matching-question','Match concepts through direct interaction','@matching_quiz',QUIZ_READY,
             action='matching-complete',focus='#qHeader',
             state='Study Mode; all three matching answers placed correctly; answer pool empty; correctness feedback visible.',
             fixture='Original Recovery & Reliability matching activity from the synthetic Practical Systems Lab pack.',seconds=11),
    addition('013B','hotspot-question','Answer by selecting a region','@hotspot_quiz',QUIZ_READY,
             action='hotspot-correct',focus='.active-quiz-logo-banner',scroll_margin=8,
             state='Study Mode; Recovery copy region selected correctly; marker and explanation visible.',
             fixture='Original resilient-service diagram from the synthetic Practical Systems Lab pack.',seconds=11),
    addition('028A','content-packs','Manage reusable content packages','/content-packs/details/DLMS_Study_practical_systems_lab',
             state='Pack details; independently validated synthetic pack with matching, image, and mixed datasets; two generated quizzes tracked.',
             fixture='Installed Practical Systems Lab pack; original data and illustration only.',seconds=10),
    addition('028B','study-packs','Launch practice from installed datasets','/study-packs',
             action='pack-catalog',
             state='Installed catalog; Practical Systems Lab expanded; matching, image/hotspot, and prepared-question rows visible.',
             fixture='Same installed Practical Systems Lab pack; no quiz generated during capture.',seconds=12),
)

_ADDITIONS_BY_ID = {item.id: item for item in V3_ADDITIONS}
EXAM_ADDITIONS = (
    addition('011A','quiz-timing','Set a quiz-specific exam duration','@critical_edit',
             action='exam-timing',focus='.build-section',seconds=9,
             state='Quiz editor; Exam Mode Timer set to 20 minutes; unsaved demonstration.',
             fixture='Original Network Troubleshooting quiz; no source data changed.'),
    addition('011B','exam-mode','Answer in timed Exam Mode','@critical_quiz',QUIZ_READY,
             action='exam',focus='.active-quiz-logo-banner',seconds=9,
             state='Exam Mode; first answer selected without immediate Study feedback; timer and Pause visible.',
             fixture='Original Network Troubleshooting quiz; capture-only clock stopped at initial duration.'),
    addition('011C','exam-paused','Pause and cover the exam','@critical_quiz',QUIZ_READY,
             action='exam-paused',seconds=8,
             state='Exam Paused overlay; frosted underlying quiz; Resume action visible.',
             fixture='Original Network Troubleshooting quiz; real Pause control.'),
)
FRAMES = (
    *V2_FRAMES[:11], *EXAM_ADDITIONS, *V2_FRAMES[11:13], _ADDITIONS_BY_ID['013A'], _ADDITIONS_BY_ID['013B'],
    *V2_FRAMES[13:28], _ADDITIONS_BY_ID['028A'], _ADDITIONS_BY_ID['028B'],
    *V2_FRAMES[28:],
)

# Opt-in documentation recipes; never added to the frozen overview sequence.
DOCUMENTATION_FRAMES = (
    frame(101, 'reviewed-bank', 'Create practice from a reviewed bank',
          '/pdf-import/review/video_review', action='series-save-bank',
          state='Original incomplete item repaired; reviewed bank saved through the real form; generator visible.',
          fixture='Same original two-question staged draft; answer A supplied by its author.'),
    frame(102, 'bundle-preview', 'Validate a bundle before importing', '/quiz-bundles',
          action='series-bundle-preview',
          state='Real export staged back into the isolated workspace; title collision shown; not published.',
          fixture='Original Network Troubleshooting source quiz; no personal history exported.'),
    frame(103, 'smart-view', 'A Smart View does not move quizzes',
          '/library?view=visible&smart=generated-practice', focus='.library-smart-active',
          state='Generated Practice Smart View includes active and completed sessions.'),
    frame(104, 'matching-start', 'Choose a matching answer and its target',
          '@matching_quiz', QUIZ_READY, action='series-matching-start', focus='#qHeader',
          state='Study Mode; three empty targets and original answer pool; no feedback yet.'),
)


def serve():
    # Parent creates this root. Refuse direct --serve use against an existing
    # installation even if the operator inherited QUIZAPP_DATA_DIR.
    root = Path(os.environ['QUIZAPP_DATA_DIR']).resolve()
    if not (root.parent / 'video-capture-owned').is_file() or root.name != 'data':
        raise RuntimeError('Video server requires a capture-owned disposable data root')
    import app as dlms
    from werkzeug.serving import make_server
    seed(dlms)
    from PIL import Image, ImageDraw
    image = Image.new('RGB', (1200, 675), 'white')
    draw = ImageDraw.Draw(image)
    from PIL import ImageFont
    font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 32) if Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf').exists() else ImageFont.load_default(size=32)
    draw.multiline_text((70,80), 'Study Skills — Original Demo\n\n1. Which activity practices recall?\nA. Explain from memory\nB. Look at the answer\n\nAnswer: A\nExplanation: Recall retrieves an idea.', fill='black', font=font, spacing=12)
    image.save(root / 'study-skills.png')
    dlms.start_browser_presence_monitor('127.0.0.1')
    make_server('127.0.0.1',int(os.environ['DLMS_BROWSER_TEST_PORT']),dlms.app,threaded=True).serve_forever()


def prepare(browser, item, metadata, data_root):
    action = item.action
    if action == 'series-save-bank':
        browser.click('input[name="correct_1"][value="A"]')
        browser.click('button.build-primary-button[form="pdfReviewForm"]')
        browser.wait_for("document.querySelector('.pdf-bank-generator-form')", timeout=20)
    elif action == 'series-bundle-preview':
        # Exercise export and staged validation without a native download dialog.
        destination = browser.evaluate("""(async () => {
            const headers = {'X-CSRFToken': window.dlmsCsrfToken};
            const source = new FormData(); source.append('quiz_ids', %s);
            const exported = await fetch('/quiz-bundles/export', {method:'POST', headers, body:source});
            if (!exported.ok) throw new Error('Bundle export failed');
            const upload = new FormData(); upload.append('bundle_zip', await exported.blob(), 'original-demo.zip');
            const staged = await fetch('/quiz-bundles/import', {method:'POST', headers, body:upload});
            if (!staged.ok || !staged.url.includes('/quiz-bundles/import/')) throw new Error('Bundle validation failed');
            return staged.url;
        })()""" % json.dumps(metadata['critical_id']))
        browser.navigate(destination)
        browser.wait_for("document.body.innerText.includes('RENAMED')")
    elif action == 'series-matching-start':
        browser.click('.study-mode-btn')
        browser.wait_for("document.querySelectorAll('.matching-drag-row').length === 3")
    elif action == 'exam-timing':
        browser.evaluate("document.querySelector('[name=exam_minutes]').value='20';true")
    elif action in {'exam','exam-paused'}:
        browser.click('.exam-mode-btn')
        browser.wait_for("document.querySelector('#choices .choice') && examMode")
        # Freeze only the disposable capture clock; render the real configured
        # duration through the product timer rather than replacing screen text.
        browser.evaluate('stopExamTimer(); timeRemaining=examDurationMinutes*60; startExamTimer(); stopExamTimer(); true')
        browser.click('#choices .choice[data-index="0"]')
        if action == 'exam-paused':
            browser.click('#pauseBtn')
            browser.wait_for("document.querySelector('#pauseOverlay.show') && document.body.classList.contains('blurred')")
    elif action in {'study','feedback','feedback-complete','finish-ready','finish'}:
        browser.click('.study-mode-btn')
        browser.wait_for("document.querySelector('#choices .choice')")
        if action in {'feedback','feedback-complete'}:
            browser.click('#choices .choice[data-index="1"]')
            browser.wait_for("document.querySelector('#choices .wrong-choice')")
            if action == 'feedback-complete':
                browser.click('#choices .choice[data-index="0"]')
                browser.wait_for('studyLearningEventSaves.size === 0')
        elif action in {'finish-ready','finish'}:
            for index in range(3):
                browser.click('#choices .choice[data-index="0"]')
                browser.wait_for('studyLearningEventSaves.size === 0')
                if index < 2:
                    browser.click('#nextBtn')
                    browser.wait_for(f'index === {index+1}')
            browser.wait_for("!document.getElementById('finishReviewBtn').hidden")
            if action == 'finish':
                browser.click('#finishReviewBtn')
                browser.wait_for("studyCompletionMessage.startsWith('Review completed.')",timeout=15)
                browser.wait_for("generatedPracticeStatus.completed && !quizRecoveryController.ownsState")
    elif action == 'model':
        browser.click('#liModelButton')
        browser.wait_for("!document.getElementById('liModel').hidden")
    elif action == 'due':
        browser.click('[data-question-status="overdue"]')
    elif action == 'collapse-queue':
        browser.click('#nrsQueueToggle')
    elif action in {'completed','library-overview','scope-folder','active-folder'}:
        label = {'completed':'Completed Generated Practice','library-overview':'Core Skills','scope-folder':'Past Projects','active-folder':'Generated Practice'}[action]
        browser.evaluate(f"""(() => {{
            document.querySelectorAll('.library-folder').forEach(folder => {{
                const button = folder.querySelector('.library-folder-toggle-button');
                const wanted = folder.dataset.folderLabel === {json.dumps(label)};
                if ((button.getAttribute('aria-expanded') === 'true') !== wanted) button.click();
            }}); return true;
        }})()""")
    elif action == 'incomplete':
        browser.click('[data-filter="incomplete"]')
    elif action == 'anki-select':
        browser.evaluate("(() => {const input=document.getElementById('ankiQuizFilter');input.value='Everyday Data Safety';input.dispatchEvent(new Event('input',{bubbles:true}));return true;})()")
        browser.click('.anki-custom-quiz-group:not([hidden]) summary')
        browser.click('.anki-custom-quiz-group:not([hidden]) input[type=checkbox]')
    elif action == 'provenance':
        browser.click('.library-source-provenance summary')
    elif action == 'ocr':
        browser.set_files("form[action='/pdf-import/screenshots'] input[type=file]", [str(data_root/'study-skills.png')])
        browser.click("form[action='/pdf-import/screenshots'] input[name='rights_ok']")
    elif action == 'matching-complete':
        browser.click('.study-mode-btn')
        browser.wait_for("document.querySelectorAll('.matching-drag-row').length === 3")
        browser.evaluate("commitMatchingAnswer(0,0);commitMatchingAnswer(1,1);commitMatchingAnswer(2,2);true")
        browser.wait_for("document.querySelectorAll('.matching-drag-row.matching-correct').length === 3 && document.querySelector('.matching-pool-empty')")
    elif action == 'hotspot-correct':
        browser.click('.study-mode-btn')
        browser.wait_for("document.querySelector('.hotspot-image-wrap')")
        browser.evaluate("(() => {const el=document.querySelector('.hotspot-image-wrap');const img=el.querySelector('img');const rect=img.getBoundingClientRect();el.dispatchEvent(new MouseEvent('click',{bubbles:true,clientX:rect.left+rect.width*.82,clientY:rect.top+rect.height*.76}));return true;})()")
        browser.wait_for("document.querySelector('.hotspot-click-marker.correct') && document.querySelector('.matching-study-feedback.is-correct')")
    elif action == 'pack-catalog':
        browser.evaluate("(() => {document.querySelectorAll('.study-pack-collapsible').forEach((item,index)=>item.open=index===0);return true;})()")


def capture(items, output, theme, *, check_only=False, replay_prefix=False):
    output.mkdir(parents=True, exist_ok=True)
    records = []
    with tempfile.TemporaryDirectory(prefix='dlms-video-capture-') as directory:
        work = Path(directory)
        (work/'video-capture-owned').touch()
        data_root = work/'data'
        server = firefox = browser = None
        try:
            server, url, env = manual._start_server(work,data_root,lan=False,reuse=False,entrypoint=Path(__file__).resolve())
            metadata = json.loads((data_root/'browser_fixture.json').read_text())
            firefox, browser = manual._start_firefox(work,env)
            browser.set_viewport(WIDTH,HEIGHT)
            browser.navigate(url+'/settings')
            browser.wait_for("typeof window.dlmsCsrfToken === 'string'")
            status = browser.evaluate("fetch('/api/theme',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({theme:"+json.dumps(theme)+"})}).then(r=>r.status)")
            if status != 200:
                raise RuntimeError(f'Theme selection failed: {status}')
            selected_ids = {item.id for item in items}
            if replay_prefix:
                final_index = max(index for index, item in enumerate(FRAMES) if item.id in selected_ids)
                steps = FRAMES[:final_index + 1]
            else:
                steps = items
            for item in steps:
                # Every frame is independently reproducible. No stale Resume
                # cards; this clears only the disposable automation profile.
                browser.navigate(url+'/settings')
                browser.wait_for_page_ready()
                browser.evaluate('localStorage.clear(); sessionStorage.clear(); true')
                route = item.route
                if route == '@critical_quiz': route = '/quizzes/'+metadata['critical_html']
                if route == '@critical_edit': route = '/edit_quiz/'+str(metadata['critical_id'])
                if route == '@adaptive_quiz': route = '/quizzes/'+metadata['adaptive_html']
                if route == '@matching_quiz': route = '/quizzes/'+metadata['matching_html']
                if route == '@hotspot_quiz': route = '/quizzes/'+metadata['hotspot_html']
                browser.navigate(url+route)
                browser.wait_for(item.ready,timeout=20)
                if browser.evaluate("document.title.includes('404') || document.body.innerText.includes('Internal Server Error')"):
                    raise RuntimeError(f'Route failed: {route}')
                prepare(browser,item,metadata,data_root)
                manual._stable_page(browser)
                if item.id not in selected_ids:
                    continue
                if item.route == '/' and browser.evaluate("document.querySelector('.daily-review-panel')?.innerText.includes('UNFINISHED')"):
                    raise RuntimeError('Unexpected Resume card in the clean video profile')
                if item.focus:
                    browser.wait_for(f'document.querySelector({json.dumps(item.focus)})')
                    browser.evaluate(f'window.scrollTo(0, Math.max(0, document.querySelector({json.dumps(item.focus)}).getBoundingClientRect().top + scrollY - {item.scroll_margin})); true')
                # Real pointer movement removes accidental hover styles and
                # tooltips without changing the application CSS or state.
                browser.command('input.performActions', {
                    'context': browser.context,
                    'actions': [{'type':'pointer','id':'video-pointer',
                                 'parameters':{'pointerType':'mouse'},
                                 'actions':[{'type':'pointerMove','x':1,'y':1,'origin':'viewport'}]}],
                })
                actual_viewport = browser.evaluate('[innerWidth,innerHeight,devicePixelRatio]')
                if actual_viewport != [WIDTH, HEIGHT, 1]:
                    raise RuntimeError(f'Unexpected viewport: {actual_viewport}')
                path = output/item.filename
                if not check_only:
                    manual._capture_png(browser,path)
                    if manual._png_dimensions(path) != (WIDTH,HEIGHT):
                        raise RuntimeError(f'Unexpected dimensions: {path}')
                records.append({**asdict(item),'theme':theme,'dimensions':[WIDTH,HEIGHT], 'status':'checked' if check_only else 'captured','fixture_version':FIXTURE_VERSION,'evidence_anchor':metadata['evidence_anchor']})
                print(f'{"Checked" if check_only else "Captured"} {item.id}: {path}',flush=True)
        finally:
            try:
                if browser: browser.close()
            finally:
                try:
                    if firefox: manual._stop_process(firefox)
                finally:
                    if server: manual._stop_process(server,interrupt=True)
    return records


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--list',action='store_true')
    parser.add_argument('--documentation',action='store_true',help='Use the opt-in instructional-series recipes, not the overview.')
    parser.add_argument('--check',action='store_true',help='Exercise selected states without writing screenshots')
    parser.add_argument('--replay-prefix',action='store_true',help='Replay earlier story actions before focused recaptures, without overwriting their images')
    parser.add_argument('--only',help='Comma-separated numeric frame IDs, e.g. 001,003,014')
    parser.add_argument('--theme',choices=tuple(THEMES),default='Purple & Gold')
    parser.add_argument('--output',type=Path,default=PROJECT/'captures')
    parser.add_argument('--serve',action='store_true',help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.serve:
        serve()
        return 0
    available = DOCUMENTATION_FRAMES if args.documentation else FRAMES
    if args.documentation and args.replay_prefix:
        parser.error('Documentation recipes are independent; do not replay the overview prefix.')
    requested = {normalized_frame_id(s) for s in args.only.split(',')} if args.only else {s.id for s in available}
    if requested - {s.id for s in available}:
        parser.error('Unknown frame ID')
    items = [s for s in available if s.id in requested]
    if args.list:
        print(json.dumps([asdict(s) for s in items],indent=2,ensure_ascii=False))
        return 0
    output = args.output.resolve()
    if PROJECT.resolve() not in output.parents:
        parser.error('Output must be a subdirectory of docs/demo-video (keeps manual assets separate)')
    records = capture(items,output,THEMES[args.theme],check_only=args.check,replay_prefix=args.replay_prefix)
    # Each run has its own sidecar: a focused refresh cannot silently relabel
    # old images as the new theme/fixture/revision.
    revision = subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    manifest = dict(version=manual._application_version(),revision=revision,
                    dirty=bool(subprocess.check_output(['git','status','--porcelain'],cwd=ROOT)),
                    captured_at=datetime.now(timezone.utc).isoformat(),theme=THEMES[args.theme],
                    viewport=dict(width=WIDTH,height=HEIGHT,device_scale=1),fixture_version=FIXTURE_VERSION,
                    replay_prefix=args.replay_prefix, captures=records)
    (output/(('check-' if args.check else 'capture-')+('-'.join(s.id for s in items) if args.only else 'all')+'.json')).write_text(json.dumps(manifest,indent=2,ensure_ascii=False)+'\n')
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
