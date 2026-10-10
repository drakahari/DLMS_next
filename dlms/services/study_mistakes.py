"""Factual Study mistake selection and durable, retry-safe composition passes.

This service never writes learning events, responses, scores or schedules.
"""
import hashlib
import json
import secrets
import re
import sqlite3
import uuid
from pathlib import Path

from . import study_sessions as study, learning
from .question_identity import is_generated_question
from .quiz_readiness import question_issues

MAX_POOL = 10000
MAX_BATCH = 100
PREVIEW_SIZE = 20


class Conflict(ValueError):
    """A stale selection, exhausted pass or uncertain publication."""


def digest(value):
    return hashlib.sha256(study.encode(value).encode()).hexdigest()


def state(cur):
    return cur.execute('SELECT generation FROM study_mistake_state WHERE id=1').fetchone()[0]


def scope(folders, quizzes):
    if (not isinstance(folders, list) or not isinstance(quizzes, list)
            or len(folders) + len(quizzes) > 1000
            or any(not isinstance(v, str) or not v or len(v) > 200 for v in folders)
            or any(type(v) is not int or v <= 0 for v in quizzes)):
        raise ValueError('Choose valid folders or source quizzes.')
    return dict(folders=sorted(set(folders)), quizzes=sorted(set(quizzes)))


def source_options(cur, registry):
    originals = {r['id'] for r in cur.execute('SELECT id,generation_kind,source_file,title AS quiz_title FROM quizzes') if not is_generated_question(r)}
    quizzes = [dict(id=e['id'], title=e.get('title') or 'Untitled quiz', folder=e.get('folder') or 'Uncategorized')
               for e in registry if e.get('id') in originals]
    return dict(quizzes=quizzes, folders=sorted({q['folder'] for q in quizzes}, key=str.casefold))


def grading_content(payload, opts):
    """Exclude provenance/ordinals; compare actual grading content, not prompts."""
    keys = ('type', 'question', 'explanation', 'choices', 'pairs', 'round_size', 'direction',
            'image_alt', 'image_edits', 'target', 'target_label')
    content = {k: payload[k] for k in keys if k in payload}
    if payload.get('image_url'):
        path = opts['media_source'](payload['image_url'])
        if not path or not Path(path).is_file() or Path(path).stat().st_size > 20 * 1024 * 1024:
            raise ValueError('Required image is unavailable or exceeds the supported size.')
        content['image_sha256'] = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    return digest(content)


def pool(cur, selected_scope, opts):
    """Every qualifying saved wrong response, with conservative revision checks."""
    options = source_options(cur, opts['registry'])
    entries = {q['id']: q for q in options['quizzes']}
    selected_ids = {q['id'] for q in entries.values()
                    if q['id'] in selected_scope['quizzes'] or q['folder'] in selected_scope['folders']}
    if not selected_ids:
        return dict(eligible=[], unavailable=[], recorded=0, fingerprint=digest([]))
    rows = {r['id']: r for r in cur.execute('SELECT q.*,z.generation_kind,z.source_file,z.title AS quiz_title FROM questions q JOIN quizzes z ON z.id=q.quiz_id')}
    by_uid = {r['question_uid']: r for r in rows.values() if r['question_uid'] and not is_generated_question(r)}
    revisions, payloads, assessments = {}, {}, {}
    available, unavailable, matched = {}, {}, set()

    def revision(qid):
        if qid not in revisions:
            revisions[qid] = digest({'question_revision': study.question_revision(cur, qid),
                                     'grading_content': grading_content(payload(qid), opts)})
        return revisions[qid]

    def payload(qid):
        if qid not in payloads:
            # The shared payload reader is a presentation reader: it normalizes
            # booleans and falls back on malformed media. Composition must not
            # turn an unsafe source into a silently repaired generated copy.
            media = json.loads(rows[qid]['media_json'] or '{}')
            if not isinstance(media, dict):
                raise ValueError('Question media metadata is invalid.')
            if rows[qid]['question_type'] == 'choice':
                flags = cur.execute('SELECT is_correct FROM choices WHERE question_id=?', (qid,)).fetchall()
                if any(type(r[0]) is not int or r[0] not in (0, 1) for r in flags):
                    raise ValueError('A stored correct-answer flag is invalid.')
            payloads[qid] = learning._question_payload_from_db(cur, qid)
        return payloads[qid]

    def assessment(qid):
        if qid not in assessments:
            assessments[qid] = study.assessment_revision(cur, qid)
        return assessments[qid]

    def consider(record, legacy=False):
        row = rows.get(record['question_id'])
        if row is None:
            return
        source = row
        generated = is_generated_question(row)
        if generated:
            source = by_uid.get(row['source_question_uid'])
            if source is None:
                # Never attach an orphaned copy by its prompt or title.
                return
        if source['quiz_id'] not in selected_ids:
            return
        qid = source['id']
        matched.add(qid)
        label = dict(question_id=qid, quiz_id=source['quiz_id'], title=entries[source['quiz_id']]['title'],
                     number=source['question_number'], question=source['question_text'])
        reason = ''
        try:
            saved = json.loads(record['response_json'] if legacy else record['payload_json'])
            if not isinstance(saved, dict) or not saved.get('selected'):
                if qid not in available and qid not in unavailable:
                    matched.discard(qid)
                return  # Unanswered is not a mistake, even if a legacy boolean says false.
            if legacy:
                reason = 'Legacy response has no verifiable content revision.'
            elif record['assessment_revision'] != assessment(row['quiz_id']):
                reason = 'Quiz changed since this answer; its content revision cannot be verified.'
            else:
                item = json.loads(record['manifest_json'])[record['ordinal'] - 1]
                if item['id'] != row['id']:
                    reason = 'Saved question identity cannot be verified.'
                elif saved.get('questionType') == 'matching':
                    variant = item.get('variant') or {}
                    if len(saved['selected']) != len(variant.get('sourcePairIndexes', [])):
                        return
                elif saved.get('questionType') == 'choice':
                    correct_count = sum(bool(c['is_correct']) for c in payload(row['id']).get('choices', []))
                    if correct_count > 1 and len(saved['selected']) != correct_count:
                        return
                elif saved.get('questionType') != 'hotspot':
                    reason = 'Saved question type cannot be verified.'
                if not reason and generated and grading_content(payload(row['id']), opts) != grading_content(payload(qid), opts):
                    reason = 'Generated copy no longer matches its original source content.'
                source_payload = payload(qid)
                if not reason and (source_payload.get('type') not in {'choice', 'matching'} or str(source_payload.get('question') or '').endswith('[Image hotspot]')):
                    reason = 'Hotspot questions are not supported by Mixed Quiz composition; open the source quiz.'
                if not reason:
                    reasons = question_issues(source_payload)
                    reason = reasons[0] if reasons else ''
                    grading_content(source_payload, opts)  # Validate required media before offering it.
            if reason:
                unavailable.setdefault(qid, {**label, 'reason': reason})
            else:
                available[qid] = {**label, 'revision': revision(qid)}
        except (ValueError, TypeError, KeyError, IndexError, OSError):
            unavailable.setdefault(qid, {**label, 'reason': 'Saved evidence or source media cannot be verified.'})

    for record in cur.connection.execute('''SELECT r.*,s.assessment_revision,s.manifest_json FROM study_responses r
        JOIN study_sessions s ON s.id=r.session_id WHERE r.kind='response' AND r.was_correct=0 ORDER BY r.saved_at,r.event_id'''):
        consider(record)
    for record in cur.connection.execute("SELECT * FROM study_legacy_responses WHERE mode='Study' AND was_correct=0 ORDER BY id"):
        consider(record, True)
    for qid in available:
        unavailable.pop(qid, None)
    if len(matched) > MAX_POOL:
        raise ValueError('This selection exceeds 10,000 recorded source questions. Choose fewer folders or quizzes; nothing was truncated.')
    eligible = sorted(available.values(), key=lambda q: (q['quiz_id'], q['number'], q['question_id']))
    return dict(eligible=eligible, unavailable=list(unavailable.values()), recorded=len(available) + len(unavailable),
                fingerprint=digest([[q['question_id'], q['revision']] for q in eligible]))


def pass_report(cur, selected_scope, current):
    row = cur.execute('SELECT * FROM study_mistake_passes WHERE scope_hash=? ORDER BY created_at DESC,id DESC LIMIT 1', (digest(selected_scope),)).fetchone()
    if row is None:
        return None
    live = {q['question_id']: q['revision'] for q in current['eligible']}
    members = [dict(r) for r in cur.execute('SELECT * FROM study_mistake_members WHERE pass_id=? ORDER BY position', (row['id'],))]
    remaining = [m for m in members if not m['used_by'] and not m['reserved_by'] and live.get(m['question_id']) == m['revision']]
    return dict(id=row['id'], total=len(members), used=sum(bool(m['used_by']) for m in members),
                reserved=sum(bool(m['reserved_by']) for m in members), remaining=len(remaining),
                unavailable=sum(not m['used_by'] and live.get(m['question_id']) != m['revision'] for m in members),
                new=sum(revision != {m['question_id']: m['revision'] for m in members}.get(qid) for qid, revision in live.items()), members=remaining)


def require_epoch(cur, generation):
    if generation != state(cur):
        raise Conflict('Data was restored or reset. Reload before creating a mix; this old request cannot change it.')


def start_pass(conn, selected_scope, opts, *, generation, fingerprint, expected_pass):
    conn.execute('BEGIN IMMEDIATE')
    cur = conn.cursor()
    require_epoch(cur, generation)
    current = pool(cur, selected_scope, opts)
    if fingerprint != current['fingerprint']:
        raise Conflict('Study evidence or sources changed. Reload and review the counts.')
    old = pass_report(cur, selected_scope, current)
    if (old['id'] if old else None) != expected_pass:
        raise Conflict('This selection already has a newer pass. Reload to continue it.')
    if not current['eligible']:
        raise Conflict('No verified Study mistakes are available for this selection.')
    if old and old['reserved']:
        raise Conflict('A quiz is still being published for this pass. Resolve that request before starting another pass.')
    pid = uuid.uuid4().hex
    cur.execute('INSERT INTO study_mistake_passes VALUES(?,?,?,?)', (pid, study.encode(selected_scope), digest(selected_scope), study.utc_now()))
    questions = list(current['eligible'])
    secrets.SystemRandom().shuffle(questions)
    cur.executemany('INSERT INTO study_mistake_members(pass_id,question_id,revision,position) VALUES(?,?,?,?)',
                    [(pid, q['question_id'], q['revision'], i) for i, q in enumerate(questions)])
    conn.commit()
    return pid


def reserve(conn, data, opts):
    """Reserve in SQLite; caller retains the registry lock through publication."""
    from ..persistence.study_mistake_schema import validate_request
    validate_request(data)
    selected_scope = scope(**data['scope'])
    conn.execute('BEGIN IMMEDIATE')
    cur = conn.cursor()
    require_epoch(cur, data['generation'])
    old = cur.execute('SELECT * FROM study_mistake_actions WHERE request_id=?', (data['request_id'],)).fetchone()
    if old and old['input_hash'] != digest(data):
        raise Conflict('This request ID was already used with different inputs. Reload before creating different work.')
    if old and old['state'] != 'retryable':
        conn.commit()
        return dict(old), None
    current = pool(cur, selected_scope, opts)
    if data['fingerprint'] != current['fingerprint']:
        raise Conflict('Study evidence or sources changed. Reload and check the updated counts; nothing was consumed.')
    available = {q['question_id']: q for q in current['eligible']}
    report = pass_report(cur, selected_scope, current)
    if data['mode'] == 'without-repeats':
        if not report or report['id'] != data['pass_id']:
            raise Conflict('Start or select the current pass before creating this mix.')
        ids = [m['question_id'] for m in report['members']]
    else:
        if data['pass_id'] is not None:
            raise ValueError('Random selection must not change a Without repeats pass.')
        ids = list(available)
        secrets.SystemRandom().shuffle(ids)
    if old:
        selected = json.loads(old['selection_json'])
        ids = [int(k) for k in selected]
        if any(qid not in available or available[qid]['revision'] != selected[str(qid)] for qid in ids):
            raise Conflict('The original selection is no longer eligible. Reload; it will not be substituted.')
    else:
        if len(ids) < data['count']:
            quantity = 'question remains' if len(ids) == 1 else 'questions remain'
            raise Conflict(f"Only {len(ids)} {quantity} available. Choose that smaller count explicitly, or start a new pass; no quiz was created.")
        ids = ids[:data['count']]
        selected = {str(qid): available[qid]['revision'] for qid in ids}
    if old:
        cur.execute("UPDATE study_mistake_actions SET state='reserved',quiz_id=NULL,html=NULL WHERE request_id=?", (data['request_id'],))
    else:
        cur.execute('INSERT INTO study_mistake_actions VALUES(?,?,?,?,?,?,?,NULL,NULL)',
                    (data['request_id'], data['generation'], digest(data), study.encode(data), study.encode(selected), data['pass_id'], 'reserved'))
    if data['mode'] == 'without-repeats':
        for qid in ids:
            changed = cur.execute('UPDATE study_mistake_members SET reserved_by=? WHERE pass_id=? AND question_id=? AND reserved_by IS NULL AND used_by IS NULL',
                                  (data['request_id'], data['pass_id'], qid)).rowcount
            if changed != 1:
                raise Conflict('Another request reserved this question. Reload; no additional questions were consumed.')
    conn.commit()
    return None, ids


def release(conn, request_id):
    """Only called after publisher-confirmed rollback or startup journal recovery."""
    with conn:
        conn.execute('UPDATE study_mistake_members SET reserved_by=NULL WHERE reserved_by=?', (request_id,))
        conn.execute("UPDATE study_mistake_actions SET state='retryable',quiz_id=NULL,html=NULL WHERE request_id=? AND state!='published'", (request_id,))


def publication_callback(data, opts):
    def record(conn, quiz_id, html):
        cur = conn.cursor()
        require_epoch(cur, data['generation'])
        action = cur.execute('SELECT * FROM study_mistake_actions WHERE request_id=?', (data['request_id'],)).fetchone()
        if not action or action['state'] != 'reserved' or action['input_hash'] != digest(data):
            raise Conflict('Publication reservation changed. Reload before trying again.')
        live = {str(q['question_id']): q['revision'] for q in pool(cur, data['scope'], opts)['eligible']}
        if any(live.get(k) != rev for k, rev in json.loads(action['selection_json']).items()):
            raise Conflict('Study evidence or source content changed before publication; no substitute quiz was created.')
        cur.execute("UPDATE study_mistake_actions SET state='committed',quiz_id=?,html=? WHERE request_id=?", (quiz_id, html, data['request_id']))
    return record


def finalize(conn, request_id):
    with conn:
        conn.execute('UPDATE study_mistake_members SET used_by=reserved_by,reserved_by=NULL WHERE reserved_by=?', (request_id,))
        conn.execute("UPDATE study_mistake_actions SET state='published' WHERE request_id=? AND state='committed'", (request_id,))


def destination(action, opts):
    entry = next((e for e in opts['registry'] if e.get('id') == action['quiz_id'] and e.get('html') == action['html']), None)
    if not entry:
        return None
    from .exam_plans import valid_link
    return valid_link(entry, data_folder=opts['data_folder'], quiz_folder=opts['quiz_folder'], artifact_names=opts['artifact_names'])


def recover(conn, opts, staging_root):
    """Called after ordinary publication recovery, never on a live request.

    Unresolved/unsafe journals hold all uncertain reservations. A complete quiz
    finalizes once; proven missing publication releases the original selection.
    """
    unresolved = list(Path(staging_root).glob('publication_*.json*')) if Path(staging_root).exists() else []
    for row in list(conn.execute("SELECT * FROM study_mistake_actions WHERE state IN ('reserved','committed')")):
        action = dict(row)
        if unresolved:
            continue
        if action['state'] == 'committed' and destination(action, opts):
            finalize(conn, action['request_id'])
        elif action['quiz_id'] is None or not conn.execute('SELECT 1 FROM quizzes WHERE id=?', (action['quiz_id'],)).fetchone():
            release(conn, action['request_id'])
