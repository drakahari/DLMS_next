"""Original, synthetic video content. Used only inside a disposable capture server."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

FIXTURE_VERSION = 'dlms-demo-video-v3'
IDENTITY = 'DLMS Demo Training & Practice Center'
# Correct choice is always A; event selections below match their recorded result.
SOURCES = (
    ('safe', 'Everyday Data Safety', 'Data Safety', 'Core Skills', [
        ('What verifies that a backup is usable?', 'Restore a sample file and check it', 'Only check its filename', 'Never open it'),
        ('Where should a recovery copy be kept?', 'Separate from the original device', 'Only beside the original file', 'Only in memory'),
        ('What should happen before a risky change?', 'Create and verify a recovery point', 'Delete all older copies', 'Disable all checks'),
    ], [1, 1, 1, 1, 1, 1]),
    ('network', 'Network Troubleshooting', 'Networking', 'Core Skills', [
        ('What should be recorded before changing a network setting?', 'The current setting and observed problem', 'Only the desired result', 'An unrelated password'),
        ('What makes a troubleshooting test useful?', 'Change one variable and compare results', 'Change every setting together', 'Skip the baseline'),
        ('What should you do after resolving a connection problem?', 'Verify the result and document the change', 'Discard the working settings', 'Assume every device is fixed'),
    ], [0, 1, 1, 1, 0, 0]),
    ('access', 'Practical Access Decisions', 'Access Control', 'Core Skills', [
        ('How much access should a new helper receive?', 'Only what the assigned task needs', 'Every available permission', 'Another person’s account'),
        ('What should happen when a temporary task ends?', 'Remove the temporary access', 'Keep all access forever', 'Publish the credentials'),
        ('How should two helpers access a shared service?', 'Use separate named accounts', 'Share one secret in public', 'Disable account records'),
    ], [0, 0, 0, 1, 1, 1]),
    ('cloud', 'Cloud Planning Basics', 'Cloud Concepts', 'New Horizons', [
        ('What does elastic capacity allow?', 'Adjust resources as demand changes', 'Avoid measuring demand', 'Guarantee zero cost'),
        ('What helps explain a service bill?', 'A record of resource use over time', 'Only the service logo', 'An unrelated device name'),
        ('What helps a service survive one component failure?', 'Plan and test an alternate path', 'Depend on one untested copy', 'Remove monitoring'),
    ], []),
)


def questions(source):
    return [dict(number=i, type='choice', question=row[0],
                 choices=[dict(label=label, text=text, is_correct=label == 'A')
                          for label, text in zip('ABC', row[1:])], correct=['A'],
                 explanation=row[1] + '. This provides a deliberate, checkable action.',
                 concepts=[source[2]]) for i, row in enumerate(source[4], 1)]


def _write_demo_study_pack(dlms):
    """Install one original pack that exercises the real catalog and manager."""
    from PIL import Image, ImageDraw, ImageFont

    root = Path(dlms.CONTENT_PACK_FOLDER) / 'DLMS_Study_practical_systems_lab'
    data = root / 'data'
    images = root / 'images'
    data.mkdir(parents=True, exist_ok=True)
    images.mkdir(parents=True, exist_ok=True)

    source = {
        'organization': 'DLMS Demo Fixture',
        'license': 'CC0-1.0',
        'attribution': 'Original synthetic illustration created for the DLMS demo.',
    }
    manifest = {
        'schema_version': 1,
        'id': 'practical_systems_lab',
        'name': 'Practical Systems Lab',
        'version': '1.0.0',
        'content_domain': 'general',
        'description': 'Reusable practice for resilient services, recovery checks, and clear operational decisions.',
        'datasets': [{
            'id': 'recovery_terms', 'title': 'Recovery & Reliability Terms',
            'type': 'matching', 'path': 'data/recovery-terms.json',
            'description': 'Match everyday reliability terms with concise operational meanings.',
        }],
        'image_datasets': [{
            'id': 'service_map', 'title': 'Resilient Service Map',
            'type': 'hotspot', 'path': 'data/service-map.json',
            'description': 'Locate recovery and monitoring components in an original system map.',
        }],
        'quiz_datasets': [{
            'id': 'readiness_checks', 'title': 'Change Readiness Checks',
            'type': 'quiz', 'path': 'data/readiness-checks.json',
            'description': 'Short prepared questions about safe, reversible changes.',
        }],
    }
    matching = {
        'schema_version': 1, 'id': 'recovery_terms',
        'title': 'Recovery & Reliability Terms',
        'category': 'Operational Foundations', 'source': source,
        'question_text': 'Match each reliability term with its practical meaning.',
        'concepts': ['service-reliability', 'safe-change'],
        'terms': [
            {'id': 'baseline', 'term': 'Baseline', 'definition': 'A recorded state used for comparison.', 'concepts': ['safe-change']},
            {'id': 'recovery-copy', 'term': 'Recovery copy', 'definition': 'A separate copy tested for restoration.', 'concepts': ['recovery-readiness']},
            {'id': 'health-check', 'term': 'Health check', 'definition': 'A repeatable test that confirms service status.', 'concepts': ['service-reliability']},
        ],
    }

    image_path = images / 'resilient-service-map.png'
    image = Image.new('RGB', (1200, 675), '#f5f1ff')
    draw = ImageDraw.Draw(image)
    font_path = Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')
    bold_path = Path('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf')
    font = ImageFont.truetype(str(font_path), 25) if font_path.exists() else ImageFont.load_default(size=25)
    bold = ImageFont.truetype(str(bold_path), 32) if bold_path.exists() else ImageFont.load_default(size=32)
    small = ImageFont.truetype(str(font_path), 20) if font_path.exists() else ImageFont.load_default(size=20)
    draw.rounded_rectangle((35, 30, 1165, 645), radius=30, fill='#ffffff', outline='#7042b8', width=5)
    draw.text((75, 62), 'Resilient Service Map', fill='#2c1748', font=bold)
    draw.text((75, 108), 'Original synthetic diagram · select the requested component', fill='#675978', font=small)
    boxes = [
        ((85, 215, 340, 365), '#e7dcff', '#5a2e9c', 'Gateway', 'Receives requests'),
        ((470, 215, 730, 365), '#fff0c2', '#8b6200', 'Application', 'Processes work'),
        ((855, 215, 1110, 365), '#dff2ff', '#17628f', 'Primary data', 'Stores current state'),
        ((855, 445, 1110, 585), '#dcf8e8', '#176a42', 'Recovery copy', 'Verified restore point'),
        ((470, 445, 730, 585), '#f3e7ff', '#7042b8', 'Health monitor', 'Checks service status'),
    ]
    for coords, fill, outline, title, subtitle in boxes:
        draw.rounded_rectangle(coords, radius=20, fill=fill, outline=outline, width=4)
        draw.text((coords[0] + 24, coords[1] + 30), title, fill=outline, font=bold)
        draw.text((coords[0] + 24, coords[1] + 83), subtitle, fill='#41394a', font=font)
    for start, end in [((340, 290), (470, 290)), ((730, 290), (855, 290)), ((980, 365), (980, 445)), ((855, 515), (730, 515))]:
        draw.line((start, end), fill='#7042b8', width=8)
        x, y = end
        tip = x - 18 if x >= start[0] else x + 18
        draw.polygon([(x, y), (tip, y-12), (tip, y+12)], fill='#7042b8')
    image.save(image_path)

    image_dataset = {
        'schema_version': 1, 'id': 'service_map', 'title': 'Resilient Service Map',
        'category': 'System Diagrams', 'source': source,
        'concepts': ['service-reliability', 'recovery-readiness'],
        'images': [{
            'id': 'resilient-map', 'file': 'images/resilient-service-map.png',
            'alt_text': 'Diagram connecting a gateway, application, primary data, recovery copy, and health monitor.',
            'license': 'CC0-1.0', 'source': source,
            'concepts': ['service-reliability'],
            'hotspots': [
                {
                    'id': 'recovery-copy', 'label': 'Recovery copy',
                    'prompt': 'Select the verified recovery copy.',
                    'shape': {'type': 'polygon', 'points': [[.712, .659], [.925, .659], [.925, .867], [.712, .867]]},
                    'explanation': 'A separate, verified copy provides a practical recovery path.',
                    'verification': {'status': 'source-checked', 'reference_basis': 'Original DLMS demo diagram'},
                    'concepts': ['recovery-readiness'],
                },
                {
                    'id': 'health-monitor', 'label': 'Health monitor',
                    'prompt': 'Select the component that checks service status.',
                    'shape': {'type': 'polygon', 'points': [[.392, .659], [.608, .659], [.608, .867], [.392, .867]]},
                    'concepts': ['service-reliability'],
                },
            ],
        }],
    }
    prepared = {
        'schema_version': 1, 'id': 'readiness_checks',
        'title': 'Change Readiness Checks', 'source': source,
        'concepts': ['safe-change'], 'images': [],
        'questions': [
            {'type': 'choice', 'question': 'What makes a change easier to reverse?', 'concepts': ['safe-change'], 'choices': [
                {'text': 'A tested recovery step', 'is_correct': True},
                {'text': 'An undocumented assumption', 'is_correct': False},
                {'text': 'Removing the baseline', 'is_correct': False},
            ]},
            {'type': 'choice', 'question': 'What should a health check report?', 'concepts': ['service-reliability'], 'choices': [
                {'text': 'An unrelated file name', 'is_correct': False},
                {'text': 'A repeatable service signal', 'is_correct': True},
                {'text': 'A hidden configuration change', 'is_correct': False},
            ]},
            {'type': 'choice', 'question': 'Where should a recovery copy be kept?', 'concepts': ['recovery-readiness'], 'choices': [
                {'text': 'Only beside the original', 'is_correct': False},
                {'text': 'Only in temporary memory', 'is_correct': False},
                {'text': 'Separate from the original system', 'is_correct': True},
            ]},
        ],
    }
    (root / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    (data / 'recovery-terms.json').write_text(json.dumps(matching, indent=2), encoding='utf-8')
    (data / 'service-map.json').write_text(json.dumps(image_dataset, indent=2), encoding='utf-8')
    (data / 'readiness-checks.json').write_text(json.dumps(prepared, indent=2), encoding='utf-8')
    (root / 'PACK_VALIDATION.json').write_text(json.dumps({
        'schema_version': 1, 'pack_id': 'practical_systems_lab',
        'overall_status': 'PASS', 'checks': [],
    }, indent=2), encoding='utf-8')
    return matching, image_dataset


def seed(dlms):
    # Relative evidence stays representative on later capture dates. The UTC
    # anchor is recorded, not concealed as bit-for-bit date determinism.
    now = datetime.now(timezone.utc).replace(hour=12, minute=0, second=0, microsecond=0)
    portal = dlms.load_portal_config()
    portal.update(title=IDENTITY, theme='purple-gold', excluded_learning_folders=['Past Projects'])
    dlms._write_settings_portal_config(portal)
    matching_data, image_data = _write_demo_study_pack(dlms)
    published = {}
    folders = {}
    for source in SOURCES:
        key, title, _, folder, _, _ = source
        published[key] = dlms._publish_quiz(title, questions(source), filename_prefix='video_' + key)
        folders[published[key][0]] = folder
    # A cross-source exact duplicate, deliberate and useful for the review screen.
    published['duplicate'] = dlms._publish_quiz('Change Readiness Checklist', [questions(SOURCES[0])[2]], filename_prefix='video_duplicate')
    folders[published['duplicate'][0]] = 'Core Skills'
    published['past'] = dlms._publish_quiz('Past Project — File Organization', [questions(SOURCES[0])[0]], filename_prefix='video_past')
    folders[published['past'][0]] = 'Past Projects'
    matching_question = {
        'number': 1, 'type': 'matching',
        'question': matching_data['question_text'],
        'pairs': [
            {'left': item['term'], 'right': item['definition']}
            for item in matching_data['terms']
        ],
        'round_size': 3, 'direction': 'term_to_definition',
        'concepts': matching_data['concepts'],
        'source': matching_data['source'],
    }
    published['matching'] = dlms._publish_quiz(
        'Recovery & Reliability — Matching Practice', [matching_question],
        filename_prefix='video_matching', source_pack_id='practical_systems_lab',
        source_dataset_id='recovery_terms',
    )
    folders[published['matching'][0]] = 'Core Skills'
    demo_image = image_data['images'][0]
    demo_hotspot = demo_image['hotspots'][0]
    hotspot_runtime = [{
        'number': 1, 'type': 'hotspot', 'question': demo_hotspot['prompt'],
        'image_url': '/content-packs/practical_systems_lab/assets/' + demo_image['file'],
        'image_alt': demo_image['alt_text'], 'image_edits': [],
        'target': demo_hotspot['shape'], 'target_label': demo_hotspot['label'],
        'explanation': demo_hotspot['explanation'],
        'verification': demo_hotspot['verification'], 'concepts': demo_hotspot['concepts'],
        'image_source': demo_image['source'],
    }]
    hotspot_db = [{
        'number': 1, 'type': 'choice',
        'question': demo_hotspot['prompt'] + ' [Image hotspot]',
        'choices': [{'label': 'A', 'text': demo_hotspot['label'], 'is_correct': True}],
        'concepts': demo_hotspot['concepts'], 'source': image_data['source'],
    }]
    published['hotspot'] = dlms._publish_quiz(
        'Resilient Service Map — Image Practice', hotspot_runtime, hotspot_db,
        filename_prefix='video_hotspot', source_pack_id='practical_systems_lab',
        source_dataset_id='service_map',
    )
    folders[published['hotspot'][0]] = 'Core Skills'
    conn = dlms.get_db()
    payloads = []
    for source in SOURCES:
        key = source[0]
        quiz_id = published[key][0]
        rows = conn.execute('SELECT id,question_number,question_text FROM questions WHERE quiz_id=? ORDER BY question_number', (quiz_id,)).fetchall()
        if key != 'cloud':
            payloads.append(dlms._question_payload_from_db(conn.cursor(), rows[0][0]))
        # Use exam attempts with complete answer rows plus event evidence.
        for run, result in enumerate(source[5]):
            stamp = now - timedelta(days=18 - run * 3)
            attempt = f'video-{key}-{run}'
            conn.execute('INSERT INTO attempts (id,quiz_id,user_name,started_at,completed_at,score,total,percent,time_remaining,mode) VALUES (?,?,?,?,?,?,?,?,?,?)',
                         (attempt, quiz_id, 'Demo Learner', (stamp-timedelta(minutes=4)).isoformat(), stamp.isoformat(), result*3, 3, result*100, 120, 'Exam'))
            for row in rows:
                selected = 'A' if result else 'B'
                conn.execute('INSERT INTO attempt_answers (attempt_id,question_id,selected_labels,was_correct) VALUES (?,?,?,?)', (attempt, row[0], selected, result))
                conn.execute("INSERT INTO learning_events (event_type,quiz_id,question_id,attempt_id,mode,was_correct,response_json,occurred_at) VALUES ('exam_answer',?,?,?,?,?,?,?)", (quiz_id, row[0], attempt, 'Exam', result, json.dumps({'selected':[selected], 'question_type':'choice'}), stamp.isoformat()))
                if not result:
                    conn.execute('INSERT INTO missed_questions (attempt_id,question_id,correct_letters,question_text,choices_text,selected_letters,selected_text,correct_text,attempt_question_number,question_type) VALUES (?,?,?,?,?,?,?,?,?,?)', (attempt,row[0],'A',row[2], '\n'.join(c['label']+'. '+c['text'] for c in questions(source)[row[1]-1]['choices']), selected, questions(source)[row[1]-1]['choices'][1]['text'], questions(source)[row[1]-1]['choices'][0]['text'],row[1],'choice'))
    # One low-evidence answer; remaining Cloud questions are unscheduled.
    cloud_q = conn.execute('SELECT id FROM questions WHERE quiz_id=? ORDER BY question_number LIMIT 1', (published['cloud'][0],)).fetchone()[0]
    conn.execute("INSERT INTO learning_events (event_type,quiz_id,question_id,attempt_id,mode,was_correct,response_json,occurred_at) VALUES ('study_answer',?,?,?,'Study',1,?,?)", (published['cloud'][0],cloud_q,'video-low-evidence',json.dumps({'selected':['A'],'question_type':'choice'}),(now-timedelta(days=2)).isoformat()))
    conn.commit()
    conn.close()
    for i, payload in enumerate(payloads, 1):
        payload['number'] = i
    published['adaptive'] = dlms._publish_quiz('Adaptive Study — What I Need Most', payloads, filename_prefix='video_adaptive', generation_kind='adaptive_study')
    published['completed'] = dlms._publish_quiz('Smart Review — Core Skills', payloads, filename_prefix='video_completed', generation_kind='smart_review')
    registry = dlms.load_registry()
    for entry in registry:
        entry['folder'] = folders.get(entry['id'], 'Uncategorized')
        # Fixture-only retained historical lifecycle marker. Frame 24 separately
        # exercises the real server-verified Finish Review flow on Adaptive.
        if entry['id'] == published['completed'][0]:
            entry['generated_practice_completion'] = dict(completed_at=(now-timedelta(days=1)).isoformat(), mode='Study', reference='video-retained-session')
    dlms.save_registry(registry)
    dlms.save_quiz_folders(['Uncategorized','Core Skills','New Horizons','Past Projects'])
    # A synthetic staged parser result, explicitly documented as fixture state.
    draft = dict(id='video_review', source_name='original-study-skills.pdf', page_count=1,
                 document_type='question_bank', detection={'recovery_mode': True}, recovery_mode=True,
                 quiz_title='Study Skills from PDF', exam_minutes=20,
                 summary={'detected':2,'complete':1,'review':0,'incomplete':1}, unassigned_text='', questions=[
        dict(number=1,question='Which activity practices recall?',choices=[{'label':'A','text':'Explain from memory'},{'label':'B','text':'Look at the answer'}],correct='A',declared_answer_text='Explain from memory',explanation='Recall requires retrieving the idea.',choice_feedback={},pages=[1],status='complete',issues=[]),
        dict(number=2,question='Which schedule spaces practice?',choices=[{'label':'A','text':'Several short sessions'},{'label':'B','text':'One long session'}],correct='',declared_answer_text='',explanation='',choice_feedback={},pages=[1],status='incomplete',issues=['A correct answer was not detected.']),
    ])
    Path(dlms.PDF_IMPORT_DRAFT_FOLDER).mkdir(parents=True, exist_ok=True)
    Path(dlms.PDF_IMPORT_DRAFT_FOLDER,'video_review.json').write_text(json.dumps(draft),encoding='utf-8')
    metadata = dict(fixture_version=FIXTURE_VERSION, evidence_anchor=now.isoformat(),
                    critical_html=published['network'][1], adaptive_html=published['adaptive'][1],
                    matching_html=published['matching'][1], hotspot_html=published['hotspot'][1],
                    source_ids=[published[s[0]][0] for s in SOURCES])
    Path(dlms.APP_DATA_DIR,'browser_fixture.json').write_text(json.dumps(metadata),encoding='utf-8')
    return metadata
