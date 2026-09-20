"""DLMS-139 recipes, used only by the existing disposable video capture server.

No external AI calls. Returned material is explicitly original author-supplied
demonstration content. Never run these fixtures against a user's data root.
"""
import json
from pathlib import Path
import shutil
import zipfile

LAW_PACKET = '''Case: Fictional Boundary Notice — Practice Case
Sources Used
Original fictional teaching exercise; not a reported decision or legal advice.
1. Case Brief
A visitor crosses a clearly marked boundary. How does notice affect expectations?
2. Socratic Review
1. Which fact changes reasonable expectations?
2. How would an unreadable notice change your analysis?
2A. Socratic Answer Key
1. The clear notice informs expectations.
2. An unreadable notice weakens that inference.
3. IRAC Drill
Identify the issue, state the assumed warning rule, apply the notice fact, and conclude.
4. Rule Flashcards
Q: What does the application step do?
A: Connects the stated rule to the relevant facts.
'''


def frames(frame):
    specs = [
        (201, 'it-study', 'IT Study', '/it', '', ''),
        (202, 'it-matching', 'IT terminology', '/it/matching', '', ''),
        (203, 'medical-study', 'Medical Study', '/medical', '', ''),
        (204, 'medical-terms', 'Medical terminology', '/medical/matching', '', ''),
        (205, 'other-studies', 'Other Studies', '/study-packs?domain_group=other', '', 'catalog'),
        (206, 'law-start', 'Create a Law Case Review', '/law/create', '', ''),
        (207, 'law-import', 'Original fictional packet', '/law/import', '.law-form', 'law-import'),
        (208, 'law-brief', 'Saved case brief', '/law/cases/phase2-fictional', '.law-case-detail-shell', ''),
        (209, 'law-irac', 'Write and save IRAC', '/law/cases/phase2-fictional', '.law-case-section:has(#lawIracIssue)', 'law-irac'),
        (210, 'law-socratic', 'Socratic review', '/law/cases/phase2-fictional', '.law-case-section:has(#socraticAnswersForm)', ''),
        (211, 'law-notes', 'Notes and export', '/law/cases/phase2-fictional', '#lawStudentNotesHeading', ''),
        (212, 'reset-results', 'Clear results versus learning evidence', '/settings/reset-remove', '.settings-reset-card', ''),
        (213, 'reset-learning', 'Reset Learning Intelligence', '/settings/reset-remove', '.settings-form-section:has([data-endpoint="/api/reset_learning_intelligence"])', ''),
        (214, 'reset-library', 'Reset quizzes versus sources', '/settings/reset-remove', '.settings-form-section:has([data-endpoint="/api/reset_quiz_library"])', ''),
        (215, 'reset-settings', 'Reset Application Settings', '/settings/reset-remove', '.settings-form-section:has([data-endpoint="/api/reset_app_settings"])', ''),
        (216, 'reset-fresh', 'Fresh state and permanent removal', '/settings/reset-remove', '.settings-form-section:has([data-endpoint="/api/reset_all_data"])', ''),
        (217, 'maintenance', 'Rebuild generated quiz pages', '/admin/maintenance', '', ''),
        (218, 'ai-settings', 'Optional AI Integration', '/settings/ai', '', ''),
        (219, 'ai-prompts', 'Editable prompt templates', '/settings/ai', '.settings-form-section:has(#aiPromptTemplate)', ''),
        (220, 'external-ai', 'Provider-neutral builder', '/external-ai/quiz-builder', '', 'external'),
        (221, 'pack-prompt', 'Request a structured pack', '/study-packs/ai-builder', '', 'pack-prompt'),
        (222, 'pack-return', 'Bring back a ZIP', '/study-packs/ai-builder', '.study-pack-builder-return-form', 'pack-prompt'),
        (223, 'pack-validate', 'Independent validation', '/study-packs/ai-builder', '', 'pack-validate'),
        (224, 'pack-installed', 'Installed original pack', '/study-packs/ai-builder', '', 'pack-install'),
        (225, 'anki-selection', 'Select cards', '/anki/custom', '.anki-source-card', 'anki-select'),
        (226, 'anki-preview', 'Preview and export', '/anki/custom', '#ankiPreview', 'anki-preview'),
        (227, 'print-front', 'Printable card fronts', '/anki/custom', '', 'print-front'),
        (228, 'print-back', 'Printable card backs', '/anki/custom', '', 'print-back'),
        (229, 'image-upload', 'Upload an original diagram', '/study-packs/image-builder', '', 'image-upload'),
        (230, 'image-question', 'Author a hotspot', '/study-packs/image-builder', '.image-builder-question-card', 'image-question'),
        (231, 'image-region', 'Place a target', '/study-packs/image-builder', '.q-hotspot-editor', 'image-region'),
        (232, 'image-saved', 'Use the saved question', '/study-packs/image-builder', '#qHeader', 'image-saved'),
        (233, 'image-editor', 'Refine an installed target', '/admin/image-editor?pack=practical_systems_lab&kind=hotspot&dataset=service_map', '.hotspot-editor-workspace', 'editor'),
        (234, 'image-prep', 'Non-destructive image preparation', '/admin/image-editor?pack=practical_systems_lab&kind=hotspot&dataset=service_map', '.hotspot-editor-workspace', 'prep'),
        (235, 'it-images', 'IT diagram datasets', '/it/images', '', ''),
        (236, 'clear-resume', 'Clear a browser resume point', '@critical_quiz', '', 'resume'),
        (237, 'ai-review', 'Review returned structured content', '/external-ai/quiz-builder', '.pdf-import-question-card', 'external-review'),
        (238, 'anki-export', 'Export and print controls', '/anki/custom', '#printableCards', 'anki-preview'),
    ]
    return tuple(frame(n, slug, title, route,
                       ready="typeof quizRecoveryReady !== 'undefined' && quizRecoveryReady === true" if route.startswith('@') else "document.querySelector('main')",
                       focus=focus, action='phase2-' + action,
                       scroll_margin=90 if n == 216 else 24,
                       state=title + '; real UI in an isolated original-content workspace.',
                       fixture='DLMS-139 opt-in original packs, fictional case and diagram.')
                 for n, slug, title, route, focus, action in specs)


def seed(dlms):
    root = Path(dlms.APP_DATA_DIR)
    if not (root.parent / 'video-phase2-owned').is_file():
        raise RuntimeError('Phase 2 requires the disposable capture owner marker')
    original = Path(dlms.CONTENT_PACK_FOLDER) / 'DLMS_Study_practical_systems_lab'
    for identifier, name, domain in [('phase2_it', 'Original IT Recovery Lab', 'it'),
                                     ('phase2_medical', 'Original Anatomy Vocabulary', 'medical')]:
        target = original.parent / ('DLMS_Study_' + identifier)
        shutil.copytree(original, target)
        manifest = json.loads((target / 'manifest.json').read_text())
        manifest.update(id=identifier, name=name, content_domain=domain)
        if domain == 'medical':
            manifest.update(description='Original introductory anatomical direction terms; not clinical guidance.', image_datasets=[], quiz_datasets=[])
            descriptor = manifest['datasets'][0]
            descriptor.update(title='Anatomical Direction Terms', description='Three foundational spatial relationships.')
            path = target / descriptor['path']
            data = json.loads(path.read_text())
            data.update(title='Anatomical Direction Terms', category='Anatomy terminology', concepts=['anatomical-direction'], question_text='Match each anatomical direction with its meaning.')
            data['terms'] = [dict(id=term.lower(), term=term, definition=meaning, concepts=['anatomical-direction'])
                             for term, meaning in [('Anterior', 'Toward the front of the body.'), ('Posterior', 'Toward the back of the body.'), ('Superior', 'Toward the head or upper part.')]]
            path.write_text(json.dumps(data, indent=2))
        (target / 'manifest.json').write_text(json.dumps(manifest, indent=2))
        (target / 'PACK_VALIDATION.json').unlink(missing_ok=True)
    # A valid, original returned ZIP. Never imply this was generated by an AI.
    manifest = json.loads((original / 'manifest.json').read_text())
    manifest.update(id='phase2_returned', name='Original Returned Practice Pack')
    with zipfile.ZipFile(root / 'original-returned-pack.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(original.rglob('*')):
            if path.is_file() and path.name != 'PACK_VALIDATION.json':
                name = 'DLMS_Study_phase2_returned/' + path.relative_to(original).as_posix()
                archive.writestr(name, json.dumps(manifest, indent=2) if path.name == 'manifest.json' else path.read_bytes())
    shutil.copyfile(original / 'images/resilient-service-map.png', root / 'original-service-map.png')
    case = dict(id='phase2-fictional', type='law_case_review', title='Fictional Boundary Notice — Practice Case', course='Torts',
                created_at='2026-09-01T10:00:00', source_import='original-fictional-packet.txt',
                source_import_snapshot='Original fictional teaching exercise, not a real case or legal advice.',
                sections={'case_brief': 'Fictional exercise. A visitor crosses a clearly marked boundary.\nIssue: How does notice affect the stated duty?\nAssumed rule: A clear warning informs reasonable expectations.\nConclusion: Explain the effect of the notice using only these invented facts.',
                          'irac_drill': 'Identify the issue, state the assumed rule, apply the notice fact, and give a supported conclusion.',
                          'socratic_review': '1. Which fact changes reasonable expectations?\n2. How would an unreadable notice change your analysis?',
                          'socratic_answer_key': '1. The clear notice informs expectations.\n2. An unreadable notice weakens that inference.',
                          'rule_flashcards': 'Q: What does the application step do?\nA: Connects the stated rule to the relevant facts.'},
                student_notes='Original fictional exercise. Compare the notice fact with the assumed rule.',
                irac_student_response={'issue': 'How does the notice affect expectations?', 'rule': 'Use the assumed warning rule.', 'analysis': 'The clear boundary notice informs the visitor.', 'conclusion': 'The notice supports the stated expectation.'},
                socratic_student_answers={'q1': 'The clearly marked boundary.'})
    Path(dlms.LAW_CASES_FOLDER, 'phase2-fictional.json').write_text(json.dumps(case, indent=2))
    Path(dlms.LAW_IMPORTS_FOLDER, 'original-fictional-packet.txt').write_text(LAW_PACKET)
    registry = dlms.load_law_registry()
    registry['cases'].append(dict(id=case['id'], title=case['title'], course='Torts', file='phase2-fictional.json', hidden=False))
    dlms.save_law_registry(registry)


def set_value(browser, selector, value):
    browser.evaluate(f"(() => {{const e=document.querySelector({json.dumps(selector)}); if(!e) throw Error('Missing field'); e.value={json.dumps(value)}; e.dispatchEvent(new Event('input',{{bubbles:true}})); e.dispatchEvent(new Event('change',{{bubbles:true}})); return true;}})()")


def click_image(browser, selector, x, y):
    browser.evaluate(f"(() => {{const e=document.querySelector({json.dumps(selector)}),r=e.getBoundingClientRect();e.dispatchEvent(new MouseEvent('click',{{bubbles:true,clientX:r.left+r.width*{x},clientY:r.top+r.height*{y}}}));return true;}})()")


def prepare(browser, item, metadata, data_root):
    action = item.action.removeprefix('phase2-')
    if action == 'catalog':
        browser.evaluate("document.querySelectorAll('.study-pack-collapsible').forEach(e=>e.open=true);true")
    elif action == 'law-import':
        set_value(browser, '#lawRawPacketInput', LAW_PACKET)
    elif action == 'law-irac':
        browser.click('form[action$="update_irac_response"] button[type="submit"]')
        browser.wait_for("location.search.includes('irac_updated')")
    elif action in {'external', 'external-review'}:
        set_value(browser, '[name=topic]', 'Safe recovery checks for a personal computer')
        browser.click('button[formaction$="/prompt"]')
        browser.wait_for("document.querySelector('#externalAiPrompt')?.value.length > 100")
        if action == 'external-review':
            payload = dict(schema_version=1, content_type='quiz', title='Original Recovery Check',
                           source={'organization': 'Original documentation fixture', 'license': 'CC0-1.0'},
                           questions=[dict(question='What verifies a usable recovery copy?', answer_mode='single',
                                           choices=[dict(text='Restore a sample and check it.', is_correct=True), dict(text='Only read its filename.', is_correct=False)],
                                           explanation='A verified restoration tests the copy.', concepts=['recovery-readiness'])])
            set_value(browser, '#externalAiResponse', json.dumps(payload, indent=2))
            browser.click('#externalAiBuilderForm button[type=submit]:not([formaction])')
            browser.wait_for("location.pathname.includes('/review/')")
    elif action.startswith('pack-'):
        set_value(browser, '[name=topic]', 'Original recovery and reliability practice')
        browser.click('form button[type=submit]')
        browser.wait_for("document.querySelector('#studyPrompt')?.value.length > 100")
        if action in {'pack-validate', 'pack-install'}:
            browser.set_files('[name=pack_zip]', [str(data_root / 'original-returned-pack.zip')])
            browser.click('.study-pack-builder-return-form button[type=submit]')
            browser.wait_for("document.querySelector('#packReviewInstallForm')", timeout=30)
            if action == 'pack-install':
                browser.click('[name=confirm_install]')
                browser.click('button[form="packReviewInstallForm"]')
                browser.wait_for("!location.pathname.includes('/import/')", timeout=30)
    elif action.startswith('anki-') or action.startswith('print-'):
        set_value(browser, '[name=deck_name]', 'Original Recovery Practice')
        browser.evaluate("(() => {const g=[...document.querySelectorAll('.anki-custom-quiz-group')].find(e=>e.innerText.includes('Everyday Data Safety'));g.open=true;g.querySelectorAll('input[type=checkbox]').forEach(e=>{if(!e.checked)e.click()});return true;})()")
        if action != 'anki-select':
            browser.click('button[formaction="/anki/custom"]')
            browser.wait_for("document.querySelector('#ankiPreview')")
            if action == 'anki-preview':
                # Exercise real APKG export without a browser download dialog.
                result = browser.evaluate("""(async()=>{const r=await fetch('/anki/export/custom',{method:'POST',body:new FormData(document.querySelector('#customAnkiForm'))});const b=await r.arrayBuffer();return {ok:r.ok,length:b.byteLength,magic:[...new Uint8Array(b).slice(0,2)]};})()""")
                if not result['ok'] or result['length'] < 1000 or result['magic'] != [80, 75]:
                    raise RuntimeError('APKG export did not return a ZIP package')
            else:
                # Submit the actual print form in this context, not a native dialog.
                browser.evaluate("(() => {const f=document.querySelector('#customAnkiForm');f.action='/anki/printable';f.target='_self';f.submit();return true;})()")
                browser.wait_for("document.querySelector('.avery-sheet')")
                selector = '.front-sheet' if action == 'print-front' else '.back-sheet'
                browser.evaluate(f"window.scrollTo(0,document.querySelector('{selector}').offsetTop+15);true")
    elif action.startswith('image-'):
        browser.set_files('[name=study_images]', [str(data_root / 'original-service-map.png')])
        if action == 'image-upload':
            return
        browser.click('.image-builder-upload-form button[type=submit]')
        browser.wait_for("document.querySelector('#builderForm')")
        for selector, value in [('[name=pack_title]', 'Original Recovery Map Practice'), ('[name=source_note]', 'Original DLMS documentation diagram, CC0'), ('.image-alt-input', 'Gateway, application, primary data, recovery copy and health monitor.'), ('.q-text', 'Select the recovery copy.'), ('.q-explanation', 'The separate recovery copy provides a verified restore point.'), ('.q-type', 'hotspot'), ('.hotspot-label', 'Recovery copy')]:
            set_value(browser, selector, value)
        browser.wait_for("document.querySelector('.hotspot-preview').complete")
        click_image(browser, '.hotspot-preview', .82, .76)
        browser.click('[name=rights_ok]')
        if action == 'image-saved':
            browser.click('#builderForm button[type=submit]')
            browser.wait_for("typeof quizRecoveryReady !== 'undefined' && quizRecoveryReady === true", timeout=30)
            browser.click('.study-mode-btn')
            browser.wait_for("document.querySelector('.hotspot-image-wrap img')?.complete")
            click_image(browser, '.hotspot-image-wrap img', .82, .76)
            browser.wait_for("document.querySelector('.hotspot-click-marker.correct')")
    elif action in {'editor', 'prep'}:
        browser.wait_for("document.querySelector('#editorImage')?.complete")
        browser.click('#loadExistingBtn')
        if action == 'editor':
            browser.click('#testBtn')
            click_image(browser, '#editorImage', .82, .76)
        else:
            browser.click('#prepModeBtn')
            set_value(browser, '#maskStyle', 'white')
            set_value(browser, '#maskH', '0.10')
            click_image(browser, '#editorImage', .82, .74)
    elif action == 'resume':
        browser.wait_for("typeof quizRecoveryReady !== 'undefined' && quizRecoveryReady === true")
        browser.click('.study-mode-btn')
        browser.wait_for("document.querySelector('#choices .choice')")
        browser.click('#choices .choice[data-index="0"]')
        browser.wait_for('studyLearningEventSaves.size === 0')
        browser.click('#nextBtn')
        browser.wait_for('index === 1')
        browser.navigate(browser.evaluate('location.origin') + '/')
        browser.wait_for("document.querySelector('.daily-review-item .daily-review-remove')")
        browser.click('.daily-review-item .daily-review-remove')
        browser.wait_for("document.querySelector('#dailyReviewClearDialog[open]')")
