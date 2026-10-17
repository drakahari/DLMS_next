"""Bounded, source-only Mac Desktop chooser/import/OCR qualification.

QTest targets this application's widgets only. A substituted app-owned QWidget
file dialog supplies the reviewed Documents fixtures; it does not automate the
host, bypass the file activation guard, or prove physical/native-sheet behavior.
No existing profiles are deleted, repaired or migrated.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import time
import traceback

TITLE = 'Mac synthetic four-question candidate'
LIMITATIONS = [
    'Source/instrumented Qt results do not qualify the normal packaged application.',
    'App-owned QWidget chooser automation does not qualify native macOS sheets or physical focus.',
    'Darwin user immutable flags can be deliberately cleared by another process running as this user.',
    'Crash-left private immutable snapshots remain evidence; no existing profile cleanup or migration is attempted.',
]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fixtures_at(raw):
    from desktop.macos_paths import real_home
    path = Path(raw)
    if not path.is_absolute() or '..' in path.parts or any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('Fixtures require an ordinary absolute Documents/Downloads folder without links')
    path = path.resolve(strict=True)
    if not any(path.is_relative_to(real_home()/name) for name in ('Documents', 'Downloads')):
        raise ValueError('Owner-facing fixtures must be in ordinary Documents or Downloads')
    sums = (path/'SHA256SUMS').read_text().splitlines()
    expected_names = {'EXPECTED.json', 'README.md', 'neutral-quiz.txt', 'ocr-question.png', 'scanned.pdf'}
    actual_names = set()
    for line in sums:
        wanted, name = line.split(maxsplit=1)
        name = name.lstrip('*')
        if name not in expected_names or name in actual_names:
            raise ValueError('Unexpected fixture manifest entry')
        actual_names.add(name)
        source = path/name
        if source.is_symlink() or not source.is_file() or digest(source) != wanted:
            raise ValueError('Fixture integrity differs: '+name)
    if actual_names != expected_names: raise ValueError('Incomplete fixture manifest')
    expected = json.loads((path/'EXPECTED.json').read_text())
    if expected.get('synthetic_only') is not True: raise ValueError('Synthetic fixture declaration required')
    return path


def click_css(q, selector):
    """Wait for this Cocoa view's surface and target its current focus proxy.

    Activation/focus requests and QTest events stay inside this application.
    A bounded retry is allowed only when the passive DOM observer saw no click
    and no document transition; delivered actions are never repeated.
    """
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    encoded = json.dumps(selector)
    attempts = q._macos_harness_report.setdefault('click_delivery', [])
    for attempt in range(2):
        view = q.window.view
        page = view.page()
        generation = page.document_generation
        q.window.showNormal(); q.window.raise_(); q.window.activateWindow()
        handle = q.window.windowHandle()
        if handle is not None: handle.requestActivate()
        view.setFocus(Qt.FocusReason.OtherFocusReason)
        q.js('document.querySelector('+encoded+').scrollIntoView({block:"center"});'
             'window.__macPaintTick=0;requestAnimationFrame(()=>requestAnimationFrame(()=>window.__macPaintTick=1));true')
        q.wait('window.__macPaintTick===1', 6)
        q.delay(.15)
        before = q.js('(globalThis.__dlmsMacFileObservations||[]).filter(e=>e.type==="click"&&e.trusted).length')
        geometry = json.loads(q.js('JSON.stringify((()=>{const e=document.querySelector('+encoded+');'
            'const r=e.getBoundingClientRect();return {x:Math.round(r.left+r.width/2),y:Math.round(r.top+r.height/2),'
            'disabled:!!e.disabled,width:r.width,height:r.height}})())'))
        if geometry['disabled'] or geometry['width']<=0 or geometry['height']<=0:
            raise AssertionError('Click target is disabled or invisible: '+selector)
        location = QPoint(geometry['x'], geometry['y'])
        proxy = view.focusProxy()
        # focusProxy follows the renderer after a cross-document surface swap;
        # childAt can still identify an old QWidget during Cocoa composition.
        target = proxy if proxy is not None and proxy.isVisible() else (view.childAt(location) or view)
        target.setFocus(Qt.FocusReason.OtherFocusReason)
        position = target.mapFrom(view, location)
        if not target.rect().contains(position): raise AssertionError('Click target falls outside current renderer widget')
        entry = {'selector': selector, 'attempt': attempt+1, 'geometry': geometry,
                 'target': type(target).__name__, 'target_object': target.objectName(),
                 'focus_proxy': target is proxy, 'window_active': q.window.isActiveWindow()}
        QTest.mouseMove(target, pos=position, delay=30)
        q.delay(.08)
        QTest.mouseClick(target, Qt.MouseButton.LeftButton, pos=position, delay=30)
        deadline = time.monotonic()+1.2
        delivered = False
        while time.monotonic()<deadline:
            q.delay(.06)
            if q.window.view is not view or page.document_generation != generation:
                delivered = True; entry['document_transition'] = True; break
            after = q.js('(globalThis.__dlmsMacFileObservations||[]).filter(e=>e.type==="click"&&e.trusted).length')
            if after > before: delivered = True; break
        entry['trusted_dom_delivered'] = delivered
        attempts.append(entry)
        print('MAC_CLICK_DELIVERY '+json.dumps(entry), flush=True)
        if delivered: return
    raise AssertionError('QTest click was not delivered to this app renderer: '+selector)


def native_state(q):
    page = q.window.view.page() if q.window.view is not None else None
    handoff = getattr(page, 'ai_handoff', None)
    fields = ('_closing', '_close_after_dialog', '_mode_switch_busy', '_settings_action_busy',
              '_backup_creating', '_close_active', '_settings_transition_refused', 'maintenance_transition',
              'import_in_progress', '_file_selection_active', '_browser_dialog_depth')
    return {'status': q.window.statusBar().currentMessage(),
            'page_url': page.url().toString() if page else None,
            'loading': page.isLoading() if page else None,
            'document_generation': getattr(page, 'document_generation', None),
            'guard_installed': getattr(page, '_macos_selection_guard', None),
            'native_epoch': getattr(handoff, 'epoch', None),
            'native_input_age': time.monotonic()-handoff.started if handoff and handoff.started else None,
            'file_used_epoch': getattr(page, '_macos_file_used_epoch', None),
            'window_active': q.window.isActiveWindow(),
            'focus_widget': type(q.app.focusWidget()).__name__ if q.app.focusWidget() else None,
            'state_flags': {name: getattr(q.window, name, None) for name in fields}}


def dom_state(q, selector=None):
    expression = """JSON.stringify((()=>{
      const e=SELECTOR?document.querySelector(SELECTOR):null;
      const r=e?.getBoundingClientRect();const hit=r?document.elementFromPoint(r.left+r.width/2,r.top+r.height/2):null;
      return {href:location.href,ready:document.readyState,focused:document.hasFocus(),
        active:{tag:document.activeElement?.tagName,name:document.activeElement?.name},
        target:e?{tag:e.tagName,type:e.type,name:e.name,disabled:e.disabled,files:e.files?.length,
          rect:{x:r.x,y:r.y,width:r.width,height:r.height},hit:{tag:hit?.tagName,type:hit?.type,name:hit?.name},
          style:{pointerEvents:getComputedStyle(e).pointerEvents,visibility:getComputedStyle(e).visibility}}:null,
        observations:globalThis.__dlmsMacFileObservations||[],body:document.body.innerText.slice(0,600)};
    })())""".replace('SELECTOR', json.dumps(selector))
    try: return json.loads(q.js(expression, 3))
    except Exception as exc: return {'diagnostic_error': repr(exc)}


@contextmanager
def instrument(q, report):
    """Observe original policy calls/results without changing their arguments."""
    from PySide6.QtWebEngineCore import QWebEngineScript
    from desktop import macos_file_selection as adapter
    q._macos_harness_report = report
    original_click = q.click_css
    q.click_css = lambda selector: click_css(q, selector)
    entries = report.setdefault('adapter_diagnostics', [])
    original_choose, original_activation = adapter.choose_files, adapter._take_activation
    def emit(entry):
        if len(entries) < 100: entries.append(entry)
        print('MAC_CHOOSER_DIAGNOSTIC '+json.dumps(entry, default=str), flush=True)
    def activation(page, valid):
        entry = {'call': '_take_activation', 'before': native_state(q)}
        started = time.monotonic()
        try:
            result = original_activation(page, valid)
            entry['result'] = result
            return result
        except Exception as exc:
            entry['exception'] = repr(exc); raise
        finally:
            entry.update(elapsed=time.monotonic()-started, after=native_state(q)); emit(entry)
    def choose(page, mode, *, server=False):
        entry = {'call': 'choose_files', 'mode': str(mode), 'server': server, 'before': native_state(q)}
        started = time.monotonic()
        try:
            result = original_choose(page, mode, server=server)
            entry['result_count'] = len(result)
            return result
        except Exception as exc:
            entry['exception'] = repr(exc); raise
        finally:
            entry.update(elapsed=time.monotonic()-started, after=native_state(q)); emit(entry)
    script = QWebEngineScript(); script.setName('dlms-source-chooser-diagnostics')
    script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
    script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
    script.setRunsOnSubFrames(False)
    script.setSourceCode("""(()=>{const a=globalThis.__dlmsMacFileObservations=[];
      for(const type of ['pointerdown','mousedown','mouseup','click','keydown','focusin','focusout']){
        document.addEventListener(type,e=>{if(a.length<80)a.push({type,trusted:e.isTrusted,
          target:{tag:e.target?.tagName,type:e.target?.type,name:e.target?.name},
          defaultPrevented:e.defaultPrevented,at:performance.now()});},true);
      }})();""")
    q.window.view.page().scripts().insert(script)
    adapter.choose_files, adapter._take_activation = choose, activation
    try: yield
    finally:
        adapter.choose_files, adapter._take_activation = original_choose, original_activation
        q.click_css = original_click


@contextmanager
def owned_picker(q, source=None, *, before_accept=None):
    """Exercise the actual chooser adapter without a test-path override."""
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QFileDialog
    previous = QFileDialog.getOpenFileName
    calls = []
    def pick(parent, title, start, filters):
        if parent is not q.window: raise AssertionError('Unexpected picker owner')
        dialog = QFileDialog(parent, title, str(source.parent) if source else start, filters)
        dialog.setOption(QFileDialog.Option.DontUseNativeDialog, True)
        dialog.setFileMode(QFileDialog.FileMode.ExistingFile)
        calls.append({'title': title, 'kind': 'app-owned QWidget chooser', 'selected': str(source) if source else None})
        timeout = QTimer(dialog); timeout.setSingleShot(True); timeout.timeout.connect(dialog.reject); timeout.start(4000)
        if source:
            dialog.selectFile(str(source))
            def accept_selected():
                if before_accept is not None:
                    before_accept()
                    calls[-1]['transition_before_accept'] = True
                dialog.accept()
            QTimer.singleShot(120, accept_selected)
        else: QTimer.singleShot(120, dialog.reject)
        try:
            accepted = dialog.exec()
            chosen = dialog.selectedFiles()
            calls[-1].update(result=int(accepted), chosen=chosen)
            if accepted != QFileDialog.DialogCode.Accepted: return '', ''
            if len(chosen) != 1 or Path(chosen[0]).resolve() != source.resolve():
                raise AssertionError('Picker did not select the explicit fixture')
            return chosen[0], dialog.selectedNameFilter()
        finally:
            timeout.stop(); dialog.deleteLater()
    QFileDialog.getOpenFileName = pick
    try: yield calls
    finally: QFileDialog.getOpenFileName = previous


def select(q, selector, source):
    if q.window.file_selection_for_test is not None:
        raise AssertionError('This harness must exercise the activation guard')
    # Single-file requests use the same adapter for a multiple-capable input,
    # but avoid replacing two Qt APIs for one explicit reviewed source.
    with owned_picker(q, source) as calls:
        try:
            q.click_css(selector)
            q.wait(f'document.querySelector({json.dumps(selector)}).files.length===1', 10)
        finally:
            details = {'selector': selector, 'source': str(source), 'picker_calls': calls,
                       'native': native_state(q), 'dom': dom_state(q, selector)}
            q._macos_harness_report.setdefault('selection_attempts', []).append(details)
            print('MAC_SELECTION_ATTEMPT '+json.dumps(details, default=str), flush=True)
    q.js('window.__macDigest=null;(async()=>{const f=document.querySelector('+json.dumps(selector)+').files[0];'
         'const b=await f.arrayBuffer();const d=await crypto.subtle.digest("SHA-256",b);'
         'window.__macDigest={name:f.name,size:f.size,sha:[...new Uint8Array(d)].map(x=>x.toString(16).padStart(2,"0")).join("")};})();true')
    q.wait('window.__macDigest!==null')
    value = json.loads(q.js('JSON.stringify(window.__macDigest)'))
    assert value == {'name': source.name, 'size': source.stat().st_size, 'sha': digest(source)}, value
    assert len(calls) == 1, calls
    store = q.window.view.page()._selected_snapshots
    assert str(store.items[-1][1]) != str(source)
    return {'renderer_file': value, 'dialog': calls[0], 'guard': 'real QTest native input + trusted main-frame lease',
            'snapshot_private': True}


def data_state(q):
    with sqlite3.connect(q.paths['backend']/'results.db') as connection:
        tables = ('quizzes', 'questions', 'choices', 'study_responses', 'attempts', 'attempt_answers')
        rows = {table: connection.execute('SELECT * FROM '+table+' ORDER BY rowid').fetchall() for table in tables}
    return hashlib.sha256(json.dumps(rows, sort_keys=True, default=str).encode()).hexdigest()


def import_quiz(q, fixtures, report):
    q.go('/upload')
    report['selected_txt'] = select(q, 'input[name=file]', fixtures/'neutral-quiz.txt')
    q.js('document.querySelector("[name=quiz_title]").value='+json.dumps(TITLE)+';'
         'document.querySelector("form[action=\\"/process\\"]").requestSubmit();true')
    q.wait("location.pathname==='/library' && document.readyState==='complete'", 35)
    with sqlite3.connect(q.paths['backend']/'results.db') as connection:
        matches = connection.execute('SELECT id FROM quizzes WHERE title=?', (TITLE,)).fetchall()
        assert len(matches) == 1, matches
        quiz_id = matches[0][0]
        questions = connection.execute('SELECT id,question_number,question_text FROM questions WHERE quiz_id=? ORDER BY question_number', (quiz_id,)).fetchall()
        assert len(questions) == 4, questions
        correct = [connection.execute('SELECT label FROM choices WHERE question_id=? AND is_correct=1 ORDER BY choice_order', (row[0],)).fetchall() for row in questions]
        assert correct == [[('B',)], [('C',)], [('A',)], [('B',)]], correct
        report['quiz_records'] = {'quiz_id': quiz_id, 'questions': questions, 'correct_labels': correct}
    link = q.js('document.querySelector("a[href^=\\"/quizzes/\\"]")?.getAttribute("href")')
    assert isinstance(link, str) and link.startswith('/quizzes/'), link
    report['quiz_path'] = link
    q.go(link)
    q.wait("quizRecoveryReady===true && document.querySelector('.study-mode-btn')?.disabled===false", 20)
    q.click_css('.study-mode-btn')
    q.wait("document.querySelector('button.choice') !== null")
    q.click_css('button.choice')
    deadline = time.monotonic()+15
    while time.monotonic()<deadline:
        with sqlite3.connect(q.paths['backend']/'results.db') as connection:
            saved = connection.execute("SELECT count(*) FROM study_responses WHERE kind='response'").fetchone()[0]
        if saved: break
        q.delay(.1)
    assert saved == 1, saved
    q.wait("!JSON.parse(localStorage.getItem('dlms.quiz-progress.v1:'+window.QUIZ_ID)||'null')?.unacknowledgedStudyEvents?.length", 15)
    report['accepted_study_response'] = True
    report['data_digest'] = data_state(q)
    with (q.paths['root']/'macos-source-import.json').open('x') as stream: json.dump(report, stream, indent=2)


def reopen(q, report):
    previous = json.loads((q.paths['root']/'macos-source-import.json').read_text())
    assert data_state(q) == previous['data_digest']
    report['exact_quiz_choice_response_records_equal'] = True
    q.go(previous['quiz_path'])
    q.wait("quizRecoveryReady===true", 20)
    assert q.js("!!document.querySelector('.quiz-recovery-resume')")
    report['browser_recovery_resume_visible'] = True


def chooser(q, fixtures, report):
    q.go('/upload')
    mode = q.window.view.page().FileSelectionMode.FileSelectOpen
    with owned_picker(q, fixtures/'neutral-quiz.txt') as calls:
        assert q.window.view.page().chooseFiles(mode, [], []) == []
        q.js('document.querySelector("input[name=file]").click();true')
        q.delay(.3)
        assert not calls, calls
        assert q.js('document.querySelector("input[name=file]").files.length') == 0
    report['unsolicited_and_direct_native_requests_refused'] = True
    with owned_picker(q, None) as calls:
        q.click_css('input[name=file]')
        assert len(calls) == 1, calls
        assert q.js('document.querySelector("input[name=file]").files.length') == 0
        assert 'canceled' in q.window.statusBar().currentMessage().lower()
    report['cancel'] = {'dialog_count': len(calls), 'files': 0,
                        'dom_focus': q.js('document.activeElement.name'), 'physical_focus_qualified': False}
    report['repeat_after_cancel'] = select(q, 'input[name=file]', fixtures/'neutral-quiz.txt')
    page = q.window.view.page()
    paths = [str(item[1]) for item in page._selected_snapshots.items]
    # Child frames receive their own real QTest input, but cannot mint the
    # top-document isolated-world lease. A passive child listener records
    # delivery only; it cannot call or alter the file authorization function.
    frame_html = '<input id="child-file" type="file" style="position:fixed;left:0;top:0;width:100%;height:100%">'
    q.js('(()=>{const f=document.createElement("iframe");f.id="mac-refused-frame";'
         'f.style.cssText="position:fixed;left:360px;top:120px;width:350px;height:100px;z-index:999999";'
         'f.srcdoc='+json.dumps(frame_html)+';document.body.append(f);return true})()')
    q.wait('!!document.querySelector("#mac-refused-frame")?.contentDocument?.querySelector("#child-file")', 5)
    q.js('(()=>{const d=document.querySelector("#mac-refused-frame").contentDocument;'
         'd.addEventListener("click",e=>globalThis.__dlmsMacFileObservations.push({type:"click",trusted:e.isTrusted,frame:true,'
         'target:{tag:e.target.tagName,type:e.target.type,name:e.target.name}}),true);return true})()')
    with owned_picker(q, fixtures/'neutral-quiz.txt') as calls:
        q.click_css('#mac-refused-frame')
        q.delay(.2)
        assert not calls, calls
        assert q.js('document.querySelector("#mac-refused-frame").contentDocument.querySelector("#child-file").files.length') == 0
        assert len(page._selected_snapshots.items) == len(paths)
    report['trusted_iframe_input_refused_no_picker_or_files'] = True
    q.js('document.querySelector("#mac-refused-frame").remove();true')
    report['stale_picker_transitions'] = []
    from PySide6.QtCore import QUrl
    for transition in ('navigation', 'same-url-reload'):
        q.go('/upload')
        before_generation = page.document_generation
        before_items = len(page._selected_snapshots.items)
        def change_document():
            if transition == 'navigation':
                q.window.view.setUrl(QUrl(f'http://127.0.0.1:{q.window.port}/library'))
            else: q.window.view.reload()
        with owned_picker(q, fixtures/'neutral-quiz.txt', before_accept=change_document) as calls:
            q.click_css('input[name=file]')
            q.wait("document.readyState==='complete' && location.pathname==="+json.dumps('/library' if transition=='navigation' else '/upload'), 20)
            assert len(calls) == 1 and calls[0].get('transition_before_accept'), calls
            assert page.document_generation > before_generation
            assert len(page._selected_snapshots.items) == before_items, 'Stale picker must not stage new files'
            if transition == 'same-url-reload':
                assert q.js('document.querySelector("input[name=file]").files.length') == 0
        report['stale_picker_transitions'].append({'kind': transition, 'dialog_selected_fixture': True,
            'document_generation_changed': True, 'new_snapshots': 0, 'prior_snapshots_preserved': all(Path(path).exists() for path in paths)})
    # A same-page ordinary navigation must not grant the prior file to a new
    # form. Actual page destruction (mode switch/window close) retires inodes.
    q.go('/library')
    report['prior_files_private_until_page_retirement'] = all(Path(path).exists() for path in paths)
    report['snapshot_paths_to_verify_after_close'] = paths


def ocr(q, fixtures, report):
    q.go('/pdf-import')
    assert q.js('!document.querySelector("input[name=screenshots]").disabled'), 'OCR unavailable in this runtime'
    # The screenshot input is multiple-capable; explicitly select one fixture
    # while retaining the normal multiple-open Qt entry point.
    from PySide6.QtWidgets import QFileDialog
    previous = QFileDialog.getOpenFileNames
    def multiple(parent, title, start, filters):
        source = fixtures/'ocr-question.png'
        with owned_picker(q, source):
            selected, selected_filter = QFileDialog.getOpenFileName(parent, title, start, filters)
        return ([selected] if selected else []), selected_filter
    QFileDialog.getOpenFileNames = multiple
    try:
        # select() wraps single-file API, while multiple() opens its own exact
        # app-owned dialog. Validate the renderer digest below independently.
        q.click_css('input[name=screenshots]')
        q.wait('document.querySelector("input[name=screenshots]").files.length===1')
    finally: QFileDialog.getOpenFileNames = previous
    report['png_chooser_guard'] = 'real QTest main-frame lease, app-owned QWidget picker'
    q.js('(()=>{const f=document.getElementById("pdfOcrUploadForm");f.elements.rights_ok.checked=true;'
         'f.elements.quiz_title.value="Mac synthetic OCR image";f.requestSubmit();return true})()')
    q.wait("location.pathname.startsWith('/pdf-import/review/')", 90)
    from tests.macos.fixture_expectations import assert_screenshot_fields
    fields = json.loads(q.js('JSON.stringify(Object.fromEntries([...document.querySelectorAll("input[name],textarea[name]")].map(x=>[x.name,x.value])))'))
    assert_screenshot_fields(fields)
    report['png_ocr_review_fields'] = {name: fields[name] for name in ('question_0', 'choice_0_A', 'choice_0_B', 'choice_0_C', 'choice_0_D')}
    report['png_ocr_review_recognized'] = True
    q.go('/pdf-import')
    report['selected_pdf'] = select(q, 'input[name=pdf_file]', fixtures/'scanned.pdf')
    q.js('(()=>{const f=document.querySelector("input[name=pdf_file]").form;f.elements.rights_ok.checked=true;'
         'f.elements.quiz_title.value="Mac synthetic scanned PDF";f.elements.pdf_content_type.value="question_bank";'
         'f.requestSubmit();return true})()')
    q.wait("!!document.querySelector('input[name=ocr_pages]')", 60)
    report['scanned_pdf_explicit_page_offer'] = True
    q.js('(()=>{const e=document.querySelector("input[name=ocr_pages]");e.checked=true;e.form.requestSubmit();return true})()')
    q.wait("location.pathname.startsWith('/pdf-import/review/')", 90)
    text = q.js('JSON.stringify([...document.querySelectorAll("input,textarea")].map(x=>x.value))')
    assert 'https' in text.lower() and '443' in text, text[:1200]
    report['scanned_pdf_ocr_review_recognized'] = True
    report['ocr_published'] = False


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-root', type=Path, required=True)
    parser.add_argument('--profile', required=True)
    parser.add_argument('--fixtures', type=Path, required=True)
    parser.add_argument('--phase', choices=('import', 'reopen', 'ocr', 'chooser'), required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    if sys.platform != 'darwin' or getattr(sys, 'frozen', False):
        parser.error('This harness qualifies source/instrumented macOS only')
    if not re.fullmatch(r'macqual[a-z0-9_-]{1,24}', args.profile): parser.error('Dedicated macqual profile required')
    repo = Path(__file__).resolve().parents[2]
    from desktop.macos_paths import prepare_root, real_home
    # Runtime profiles stay outside Documents/FileProvider metadata management;
    # evidence logs and screenshots remain in the checkout's .gate1 directory.
    scope = real_home()/'.cache/dlms-desktop-macos-candidate/qualification-data'
    if (not args.data_root.is_absolute() or '..' in args.data_root.parts
            or args.data_root.name != 'source-data' or args.data_root.parent.parent != scope
            or re.fullmatch(r'run-[a-z0-9_-]{1,64}', args.data_root.parent.name) is None):
        parser.error('Use '+str(scope/'run-<unique-name>'/'source-data'))
    if not args.output.is_absolute() or not args.output.is_relative_to(repo/'.gate1/macos') or args.output.exists():
        parser.error('Output must be a new absolute JSON path below .gate1/macos')
    if not args.output.parent.is_dir(): parser.error('Output parent must exist')
    import package_macos
    package_macos.ACTIVE = True
    root = prepare_root(args.data_root)
    os.environ.update(DLMS_MACOS_DATA_ROOT=str(root), DLMS_DESKTOP_DATA_ROOT=str(root),
                      DLMS_DESKTOP_ROOT_KIND='macos-candidate')
    fixtures = fixtures_at(args.fixtures)
    from desktop.isolation import profile_paths
    paths = profile_paths(args.profile, create=False)
    if args.phase == 'import' and (paths['backend']/'results.db').exists():
        parser.error('Import requires a new synthetic profile; existing data is preserved')
    report = {'phase': args.phase, 'profile': args.profile, 'data_root': str(root), 'fixtures': str(fixtures),
              'kind': 'source/instrumented Qt', 'physical_input': False, 'normal_package_qualified': False,
              'limitations': LIMITATIONS, 'status': 'running'}
    q = None
    try:
        from tests.gate1.qt_checks import QtChecks
        q = QtChecks(args.profile, automated=True, normal_identity=True)
        report['qt_platform'] = q.app.platformName()
        assert q.app.platformName() == 'cocoa', 'Native cocoa session required'
        with instrument(q, report):
            {'import': import_quiz, 'reopen': lambda q, fixtures, report: reopen(q, report),
             'ocr': ocr, 'chooser': chooser}[args.phase](q, fixtures, report)
        report['status'] = 'pass'
    except Exception as exc:
        report.update(status='fail', error=f'{type(exc).__name__}: {exc}')
        traceback.print_exc()
        if q is not None:
            report['failure_native'] = native_state(q)
            report['failure_dom'] = dom_state(q)
            screenshot = args.output.with_suffix('.failure.png')
            if q.window.view is not None and q.window.view.grab().save(str(screenshot)):
                report['failure_screenshot'] = str(screenshot)
    finally:
        if q is not None:
            try:
                q.close()
                assert getattr(q.window, '_close_complete', False), 'Native close incomplete'
                assert q.window.backend is None or q.window.backend.poll() is not None, 'Backend still running'
                report['ordered_close_complete'] = True
                for path in report.get('snapshot_paths_to_verify_after_close', []):
                    assert not Path(path).exists(), 'Snapshot survived orderly page retirement'
                report['close_result'] = getattr(q.window, 'close_result', None)
            except Exception as exc:
                report.update(status='fail', close_error=f'{type(exc).__name__}: {exc}')
        with args.output.open('x') as stream: json.dump(report, stream, indent=2)
        print(json.dumps(report, indent=2), flush=True)
    return 0 if report['status'] == 'pass' else 1


if __name__ == '__main__': raise SystemExit(main())
