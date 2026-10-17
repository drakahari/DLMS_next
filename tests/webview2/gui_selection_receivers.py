"""Synthetic source WebView2 chooser -> immutable File -> real receiver drill.

The native QFileDialog result and explicit owned-pipe eval gesture are supplied.
DOM clicks are untrusted; coordinate-input failure is investigated separately. Picker
ticket checks, ordinary-file capture, private staging, File reading and actual
forms/backend validators remain active. This is instrumented source evidence,
not normal-package or physical chooser/focus acceptance. Run --reopen in a
separate process after creation. --extended also installs the existing neutral
bundle/Study Pack fixtures and exercises PDF/image OCR draft receivers.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
import runpy
import shutil
import sqlite3
import sys
import time
import uuid


def until(q, condition, timeout=35):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = condition()
        if result:
            return result
        q.delay(.08)
    raise TimeoutError('The synthetic receiver did not reach its expected state.')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def rows(q, query, args=()):
    with sqlite3.connect(q.paths['backend'] / 'results.db') as connection:
        connection.row_factory = sqlite3.Row
        return [dict(row) for row in connection.execute(query, args)]


def oracle(q):
    tables = ('quizzes', 'questions', 'choices', 'matching_pairs', 'certifications',
              'certification_cycles', 'certification_training')
    result = {'rows': {table: rows(q, f'SELECT * FROM {table} ORDER BY rowid') for table in tables}}
    result['rows']['certification_attachments'] = rows(q,
        'SELECT id,mime,sha256,length(content) AS size FROM certification_attachments ORDER BY id')
    result['assets'] = {}
    for folder in ('static/logos', 'static/bg', 'content_packs'):
        root = q.paths['backend'] / folder
        if root.exists():
            for path in sorted(root.rglob('*')):
                if path.is_file():
                    result['assets'][path.relative_to(q.paths['backend']).as_posix()] = sha(path.read_bytes())
    result['appearance'] = json.loads((q.paths['backend'] / 'config/portal.json').read_text(encoding='utf-8'))
    return result


def choose(q, selector, paths, report):
    """Native chooser result stub; no page File/DOM replacement or OS input."""
    from PySide6.QtWidgets import QFileDialog
    from desktop.webview2_file_selection import SUCCESS
    paths = tuple(Path(path) for path in paths)
    expected = [{'name': path.name, 'size': path.stat().st_size, 'sha256': sha(path.read_bytes())} for path in paths]
    original_single, original_multiple = QFileDialog.getOpenFileName, QFileDialog.getOpenFileNames
    calls = []
    def one(parent, title, directory, *args, **kwargs):
        calls.append({'multiple': False, 'start': str(directory)})
        return str(paths[0]), ''
    def multiple(parent, title, directory, *args, **kwargs):
        calls.append({'multiple': True, 'start': str(directory)})
        return [str(path) for path in paths], ''
    QFileDialog.getOpenFileName, QFileDialog.getOpenFileNames = one, multiple
    try:
        assert q.window.file_selection_for_test is None
        state = q.js(f"""(()=>{{const e=document.querySelector({json.dumps(selector)});return {{exists:Boolean(e),disabled:e?.disabled,type:e?.type,visible:Boolean(e&&e.getClientRects().length)}}}})()""")
        report.setdefault('input_preconditions', []).append({'selector': selector, **state})
        assert state['exists'] and not state['disabled'], ('Receiver control unavailable before picker activation', selector, state)
        q.window.view.command('focus')
        rectangle = q.js(f"""(()=>{{const e=document.querySelector({json.dumps(selector)});
          if(!e||e.disabled)throw Error('Input missing/disabled');e.scrollIntoView({{block:'center',behavior:'instant'}});
          const r=e.getBoundingClientRect();return {{x:r.x+Math.min(20,r.width/2),y:r.y+r.height/2}}}})()""")
        reply, errors = [], []
        activation = {'selector': selector, 'coordinate_measurement': rectangle, 'source_eval_gesture': True,
                      'dom_click_trusted': False, 'reply': reply, 'errors': errors}
        report.setdefault('activation_requests', []).append(activation)
        q.window.view.command('eval', script=f'document.querySelector({json.dumps(selector)}).click();true',
                              world=0, gesture=True, callback=reply.append, on_error=errors.append)
        until(q, lambda: reply or errors)
        assert not errors, activation
        q.wait(f'document.querySelector({json.dumps(selector)}).files.length==={len(paths)}', 35)
        until(q, lambda: SUCCESS in q.window.statusBar().currentMessage())
        actual = q.js(f"""(async()=>{{const files=[...document.querySelector({json.dumps(selector)}).files];
          return await Promise.all(files.map(async f=>({{name:f.name,size:f.size,
            sha256:[...new Uint8Array(await crypto.subtle.digest('SHA-256',await f.arrayBuffer()))]
              .map(n=>n.toString(16).padStart(2,'0')).join('')}})))}})()""", 20)
        assert actual == expected, (actual, expected)
        assert calls and all(item['start'] == str(q.window.documents_folder) for item in calls), calls
        store = q.window.view._selection_store
        assert store and not store.closed
        for snapshot in store.snapshots:
            assert snapshot.path.is_file()
        report.setdefault('selections', []).append({'selector': selector, 'actual_browser_files': actual,
            'native_chooser_result_stub': True, 'documents_start_verified': True})
        return actual
    finally:
        QFileDialog.getOpenFileName, QFileDialog.getOpenFileNames = original_single, original_multiple


def fill(q, fields):
    q.js('(()=>{const values=' + json.dumps(fields) + ";for(const [name,value] of Object.entries(values)){"
         "const e=document.querySelector('[name=\"'+name+'\"]');if(!e)throw Error('Missing '+name);"
         "if(e.type==='checkbox')e.checked=Boolean(value);else e.value=value;}return true})()")


def submit(q, selector, expected):
    view = q.window.view
    generation = view._active_generation
    q.js(f'document.querySelector({json.dumps(selector)}).requestSubmit();true')
    until(q, lambda: view._active_generation > generation)
    q.wait(expected, 80)
    until(q, lambda: not view.page().isLoading())
    assert 200 <= view.page().last_http_status < 400, view.page().last_http_status


def generated_fixtures(q, project, ordinary, *, extended):
    from PIL import Image
    result = {}
    for name, content in {
        'questions 日本語.txt': (project / 'fixtures/gate1-neutral-quiz.txt').read_bytes(),
        'matching bank é.csv': b'term,definition\nAlpha,First\nBeta,Second\nGamma,Third\n',
    }.items():
        path = ordinary / name
        path.write_bytes(content)
        result['txt' if path.suffix == '.txt' else 'csv'] = path
    image = Image.new('RGB', (32, 24), (37, 91, 146))
    raster = io.BytesIO(); image.save(raster, format='PNG')
    result['image'] = ordinary / 'badge logo 日本語.png'
    result['image'].write_bytes(raster.getvalue() + b'\nSYNTHETIC-TRAILER-TO-STRIP')
    result['pdf'] = ordinary / 'training certificate é.pdf'
    image.save(result['pdf'], format='PDF')
    if extended:
        original_argv = sys.argv
        try:
            for key, generator, arguments in (
                ('bundle', 'make_portable_media_bundle.py', []),
                ('pack', 'make_pack_datasets.py', ['--output']),
            ):
                output = q.paths['tmp'] / (key + '-' + uuid.uuid4().hex + '.zip')
                sys.argv = [generator, *arguments, str(output)]
                namespace = runpy.run_path(str(project / 'fixtures' / generator))
                generated_status = namespace['main']()
                assert generated_status in (None, 0), f'Synthetic fixture generator failed: {generator}'
                result[key] = ordinary / (key + ' 日本語.zip')
                shutil.copyfile(output, result[key])
        finally:
            sys.argv = original_argv
        for key, source in (
            ('ocr_image', 'tests/fixtures/ocr/dlms-question.png'),
            ('ocr_pdf', 'tests/fixtures/ocr/pdf/fully-scanned.pdf'),
        ):
            result[key] = ordinary / ('OCR 日本語' + Path(source).suffix)
            shutil.copyfile(project / source, result[key])
    return result


def core(q, files, report):
    q.go('/upload')
    original = files['txt'].read_bytes()
    choose(q, 'input[name=file]', [files['txt']], report)
    choose(q, 'input[name=quiz_logo]', [files['image']], report)
    # A mutable source is no longer authority once the sealed copy was chosen.
    files['txt'].write_bytes(b'This replacement must not be imported.\n')
    current = q.js("""(async()=>{const f=document.querySelector('input[name=file]').files[0];
      return [...new Uint8Array(await crypto.subtle.digest('SHA-256',await f.arrayBuffer()))]
        .map(n=>n.toString(16).padStart(2,'0')).join('')})()""")
    assert current == sha(original)
    fill(q, {'quiz_title': 'Immutable chooser TXT'})
    submit(q, 'form.build-upload-form', "location.pathname!=='/upload'&&document.readyState==='complete'")
    text_quiz = rows(q, "SELECT id FROM quizzes WHERE title='Immutable chooser TXT'")
    assert len(text_quiz) == 1
    questions = rows(q, 'SELECT id,question_number,question_text FROM questions WHERE quiz_id=? ORDER BY question_number', (text_quiz[0]['id'],))
    assert len(questions) == 4 and questions[0]['question_text']
    correct = rows(q, '''SELECT c.label FROM choices c JOIN questions q ON q.id=c.question_id
        WHERE q.quiz_id=? AND c.is_correct=1 ORDER BY q.question_number,c.choice_order''', (text_quiz[0]['id'],))
    assert [item['label'] for item in correct] == ['B', 'C', 'A', 'B'], correct
    registry = json.loads((q.paths['backend'] / 'config/quizzes.json').read_text(encoding='utf-8'))
    entry = next(item for item in registry if item['title'] == 'Immutable chooser TXT')
    logo = q.paths['backend'] / 'static/logos' / entry['logo']
    assert logo.is_file() and b'SYNTHETIC-TRAILER' not in logo.read_bytes()
    report['txt_and_logo'] = {'questions': 4, 'correct_label_order': ['B', 'C', 'A', 'B'],
        'source_replacement_did_not_change_import': True, 'logo_reencoded': True}

    q.go('/matching_bank_import')
    choose(q, 'input[name=csv_file]', [files['csv']], report)
    fill(q, {'quiz_title': 'Immutable chooser CSV', 'round_size': '2', 'direction': 'definition_to_term'})
    submit(q, 'form.build-workspace', "location.pathname.startsWith('/edit_quiz/')&&document.readyState==='complete'")
    matching = rows(q, '''SELECT q.id,q.matching_direction,q.matching_round_size FROM questions q
        JOIN quizzes z ON z.id=q.quiz_id WHERE z.title='Immutable chooser CSV' ''')
    assert len(matching) == 1 and matching[0]['matching_direction'] == 'definition_to_term' and matching[0]['matching_round_size'] == 2
    pairs = rows(q, 'SELECT left_text,right_text FROM matching_pairs WHERE question_id=? ORDER BY pair_order', (matching[0]['id'],))
    assert [(item['left_text'], item['right_text']) for item in pairs] == [('Alpha', 'First'), ('Beta', 'Second'), ('Gamma', 'Third')]
    report['matching_csv'] = {'ordered_pairs': pairs, 'round_size': 2, 'direction': 'definition_to_term'}

    q.go('/certifications/new')
    choose(q, 'input[name=badge]', [files['image']], report)
    choose(q, 'input[name=certificate]', [files['pdf']], report)
    fill(q, {'field_name': 'Immutable chooser credential', 'field_issuer': 'Synthetic Test', 'field_earned': '2025-01-01'})
    submit(q, 'form.cert-form', "location.pathname!=='/certifications/new'&&location.pathname!=='/certifications/save'&&document.readyState==='complete'")
    credential = next(item for item in rows(q, 'SELECT id,data_json FROM certifications')
                      if json.loads(item['data_json'])['name'] == 'Immutable chooser credential')
    badge_id = json.loads(credential['data_json'])['badge']
    with sqlite3.connect(q.paths['backend'] / 'results.db') as connection:
        mime, stored, digest = connection.execute('SELECT mime,content,sha256 FROM certification_attachments WHERE id=?', (badge_id,)).fetchone()
    assert mime == 'image/png' and digest == sha(stored) and b'SYNTHETIC-TRAILER' not in stored
    from PIL import Image
    with Image.open(io.BytesIO(stored)) as image:
        assert image.size == (32, 24) and image.convert('RGB').getpixel((0, 0)) == (37, 91, 146)
    certificate = rows(q, 'SELECT data_json FROM certification_cycles WHERE certification_id=?', (credential['id'],))
    certificate_id = json.loads(certificate[0]['data_json'])['certificate']
    assert rows(q, 'SELECT sha256 FROM certification_attachments WHERE id=?', (certificate_id,))[0]['sha256'] == sha(files['pdf'].read_bytes())
    report['certification'] = {'badge_reencoded_pixels_preserved': True, 'certificate_pdf_exact_digest': True}

    q.go('/certifications/training/new')
    choose(q, 'input[name=certificate]', [files['pdf']], report)
    fill(q, {'field_name': 'Immutable chooser training', 'field_provider': 'Synthetic Test',
             'field_completed': '2026-10-15', 'duration_hours': '1', 'duration_minutes': '15'})
    submit(q, 'form.cert-form', "location.pathname!=='/certifications/training/new'&&location.pathname!=='/certifications/save'&&document.readyState==='complete'")
    training = next(json.loads(item['data_json']) for item in rows(q, 'SELECT data_json FROM certification_training')
                    if json.loads(item['data_json'])['name'] == 'Immutable chooser training')
    assert float(training['duration_minutes']) == 75
    assert rows(q, 'SELECT sha256 FROM certification_attachments WHERE id=?', (training['certificate'],))[0]['sha256'] == sha(files['pdf'].read_bytes())
    report['training'] = {'duration_minutes': 75, 'certificate_pdf_exact_digest': True}

    q.go('/settings/appearance')
    choose(q, 'input[name=background_image]', [files['image']], report)
    fill(q, {'portal_title': 'Immutable chooser appearance', 'theme': 'dark'})
    submit(q, 'form.settings-detail-card', "location.pathname==='/settings/appearance'&&location.search.includes('saved=1')&&document.readyState==='complete'")
    appearance = json.loads((q.paths['backend'] / 'config/portal.json').read_text(encoding='utf-8'))
    background = q.paths['backend'] / 'static/bg' / appearance['background_image']
    assert appearance['theme'] == 'dark' and appearance['title'] == 'Immutable chooser appearance'
    assert background.is_file() and b'SYNTHETIC-TRAILER' not in background.read_bytes()
    report['appearance'] = {'theme': 'dark', 'background_reencoded': True}


def extended(q, files, report):
    q.go('/quiz-bundles')
    choose(q, 'input[name=bundle_zip]', [files['bundle']], report)
    submit(q, 'form.portable-bundle-upload-form', "Boolean(document.querySelector('input[name=confirm_import]'))&&document.readyState==='complete'")
    q.js("document.querySelector('input[name=confirm_import]').checked=true;true")
    submit(q, "form[action$='/confirm']", "location.pathname==='/quiz-bundles'&&document.readyState==='complete'")
    portable = rows(q, "SELECT id FROM quizzes WHERE title='Synthetic Portable Media'")
    assert len(portable) == 1
    choices = rows(q, '''SELECT c.label,c.text,c.is_correct FROM choices c JOIN questions q ON q.id=c.question_id
        WHERE q.quiz_id=? ORDER BY q.question_number,c.choice_order''', (portable[0]['id'],))
    assert [(item['label'], item['text'], item['is_correct']) for item in choices] == [('C', 'Blue tile', 1), ('A', 'Red tile', 0)]
    report['portable_bundle'] = {'choice_identity_order_correctness': choices}

    q.go('/content-packs')
    choose(q, 'input[name=pack_zip]', [files['pack']], report)
    submit(q, 'form.content-pack-upload-form', "Boolean(document.querySelector('input[name=confirm_install]'))&&document.readyState==='complete'")
    q.js("document.querySelector('input[name=confirm_install]').checked=true;true")
    submit(q, 'form#packReviewInstallForm', "!location.pathname.includes('/import/')&&document.readyState==='complete'")
    manifests = list((q.paths['backend'] / 'content_packs').glob('*/manifest.json'))
    assert any(json.loads(path.read_text())['id'] == 'closure_datasets' for path in manifests)
    report['study_pack'] = {'installed_existing_neutral_fixture': True}

    for kind, field, action, form in (
        ('ocr_pdf', 'pdf_file', '/pdf-import/analyze', "form[action='/pdf-import/analyze']"),
        ('ocr_image', 'screenshots', '/pdf-import/screenshots', 'form#pdfOcrUploadForm'),
    ):
        q.go('/pdf-import')
        choose(q, f'input[name={field}]', [files[kind]], report)
        q.js(f"""(()=>{{const f=document.querySelector({json.dumps(form)});f.querySelector('[name=quiz_title]').value={json.dumps(kind+' chooser draft')};
          f.querySelector('[name=rights_ok]').checked=true;const t=f.querySelector('[name=pdf_content_type]');if(t)t.value='question_bank';return true}})()""")
        submit(q, form, "location.pathname!='/pdf-import'&&document.readyState==='complete'")
        # Preserve truthful staging evidence: these are reviewable drafts, not
        # saved question banks. OCR/result review/save has its own drill.
        draft_files = list((q.paths['backend'] / 'pdf_import_drafts').glob('*'))
        assert draft_files
        report[kind] = {'actual_chooser_upload_receiver_reached': True,
                        'destination_path': q.window.view.url().path(), 'review_draft_only': True}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--profile', required=True)
    parser.add_argument('--reopen', action='store_true')
    parser.add_argument('--extended', action='store_true')
    args = parser.parse_args()
    import package_windows_webview2
    package_windows_webview2.ACTIVE = True
    from desktop.webview2_shell import DesktopWindow
    from desktop.webview2_file_selection import _known_private_roots
    from PySide6.QtCore import QStandardPaths
    roots = _known_private_roots()
    documents = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation))
    import desktop.shell
    desktop.shell.DesktopWindow = lambda *a, **k: DesktopWindow(*a, selection_private_roots=roots,
                                                             documents_folder=documents, **k)
    from tests.gate1.qt_checks import QtChecks
    from desktop.isolation import PROJECT
    # Source mode has no _MEIPASS OCR closure. Supply only the already reviewed
    # project bundle after the original strict backend environment setup; the
    # frozen executable resolves its own bundled runtime independently.
    ocr_root = PROJECT / '.gate1/windows-native/ocr-bundle-final'
    inventory_path = PROJECT / '.gate1/windows-native/ocr-inventory.json'
    inventory = json.loads(inventory_path.read_text())
    for item in inventory:
        payload = ocr_root / item['path']
        assert payload.stat().st_size == item['bytes'] and sha(payload.read_bytes()) == item['sha256'], item['path']
    original_source_environment = desktop.shell.source_environment
    def source_ocr_environment(env, **kwargs):
        original_source_environment(env, **kwargs)
        env['DLMS_TESSERACT_EXECUTABLE'] = str(ocr_root / 'bin/tesseract.exe')
        env['DLMS_TESSDATA_PREFIX'] = str(ocr_root / 'tessdata')
    desktop.shell.source_environment = source_ocr_environment
    from desktop import webview2_browser as browser
    from desktop.webview2_file_selection import SelectionContext
    picker_events = []
    original_event = browser.View._event
    def observed_event(view, event):
        if event.get('event') in ('file-picker', 'file-picker-failed', 'console-warning'):
            item = dict(event)
            if event.get('event') == 'file-picker':
                try: item['controller_context_valid'] = SelectionContext.capture(view.page()).valid()
                except (RuntimeError, ValueError, OSError) as exc: item['controller_context_error'] = str(exc)
            if len(picker_events) < 256: picker_events.append(item)
        return original_event(view, event)
    browser.View._event = observed_event
    q = QtChecks(args.profile, automated=True)
    report = {'source_instrumented': True, 'normal_package': False, 'physical_picker_acceptance': False,
              'profile': args.profile, 'reopen': args.reopen, 'extended_requested': args.extended,
              'python_version': sys.version, 'python_executable': sys.executable}
    import PySide6
    report['pyside_version'] = PySide6.__version__
    report['source_ocr_bundle_inventory_sha256'] = sha(inventory_path.read_bytes())
    report['source_ocr_runtime_supplied_by_harness'] = True
    evidence = q.paths['root'] / 'wv-selection-receivers-oracle.json'
    stores = []
    try:
        if args.reopen:
            expected = json.loads(evidence.read_text(encoding='utf-8'))
            assert oracle(q) == expected
            q.go('/library')
            q.wait("document.body.innerText.includes('Immutable chooser TXT')&&document.body.innerText.includes('Immutable chooser CSV')")
            q.go('/certifications')
            q.wait("document.body.innerText.includes('Immutable chooser credential')")
            report['separate_process_rows_assets_and_appearance_equal'] = True
        else:
            assert not evidence.exists(), 'Use a fresh disposable profile; existing evidence is preserved.'
            assert rows(q, 'SELECT count(*) AS n FROM quizzes')[0]['n'] == 0
            ordinary = PROJECT / 'fixtures/webview2-ordinary' / (args.profile + '-' + uuid.uuid4().hex)
            ordinary.mkdir(mode=0o700, parents=True)
            report['synthetic_ordinary_folder'] = str(ordinary)
            files = generated_fixtures(q, PROJECT, ordinary, extended=args.extended)
            core(q, files, report)
            if args.extended:
                extended(q, files, report)
            store = q.window.view._selection_store
            stores.append(store)
            report['retained_selection_count'] = len(store.snapshots)
            report['all_seals_retained_across_navigation'] = all(item.path.is_file() for item in store.snapshots)
            assert report['all_seals_retained_across_navigation']
            evidence.write_text(json.dumps(oracle(q), indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
        report['runtime'] = q.window.view.runtime_info
        report['passed'] = True
    finally:
        if q.window.view is not None:
            current_store = q.window.view._selection_store
            if current_store is not None and current_store not in stores: stores.append(current_store)
        report['picker_events'] = picker_events
        report['status_message'] = q.window.statusBar().currentMessage()
        report['protocol_events'] = list(q.window.view.protocol_events) if q.window.view is not None else []
        q.close(); q.delay(.3)
        browser.View._event = original_event
        desktop.shell.source_environment = original_source_environment
        report['close_complete'] = q.window._close_complete
        report['sealed_store_cleanup'] = [{'closed': store.closed, 'errors': store.cleanup_errors,
                                           'root_removed': not store.path.exists()} for store in stores]
        output = q.paths['root'] / ('wv-selection-receivers-reopen.json' if args.reopen else 'wv-selection-receivers-create.json')
        output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(json.dumps({key: value for key, value in report.items() if key != 'protocol_events'}, indent=2), flush=True)
    assert report.get('passed') and report['close_complete']
    assert all(item['closed'] and not item['errors'] and item['root_removed'] for item in report['sealed_store_cleanup'])


if __name__ == '__main__':
    main()
