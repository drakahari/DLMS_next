"""Optional plans over authoritative learning evidence and factual Study history."""
import hashlib
import json
import math
import re
import uuid
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from . import learning, study_sessions as study
from .attempts import LEARNING_QUESTION_TYPES
from .learning_scope import build_learning_scope
from .question_identity import is_generated_question, canonical_learning_identity
from .quiz_mutations import quiz_folder_identity_key


class PlanConflict(ValueError):
    """Stale form, scope, restore token or publication request."""


DEFAULTS = dict(name='', exam_date='', calendar_timezone='', weekdays=[0, 2, 4],
                minutes=30, pace=2.0, pace_low=1.0, pace_high=4.0, reserve=25.0,
                folders=[], paused=False, visible=True)


def digest(value):
    return hashlib.sha256(study.encode(value).encode()).hexdigest()


def validate(data):
    if not isinstance(data, dict):
        raise ValueError('Plan configuration must be an object.')
    result = {key: data.get(key, default) for key, default in DEFAULTS.items()}
    if not isinstance(result['name'], str) or not 1 <= len(result['name'].strip()) <= 120:
        raise ValueError('Enter a certification name of 1–120 characters.')
    result['name'] = result['name'].strip()
    try:
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', result['exam_date']):
            raise ValueError()
        date.fromisoformat(result['exam_date'])
        ZoneInfo(result['calendar_timezone'])
    except (ValueError, TypeError, ZoneInfoNotFoundError):
        raise ValueError('Choose a real exam date and an IANA calendar timezone, such as America/Chicago.') from None
    for field, low, high in [('minutes', 1, 1440), ('pace_low', .1, 120), ('pace', .1, 120), ('pace_high', .1, 120), ('reserve', 0, 200)]:
        value = result[field]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
            raise ValueError(f'Invalid {field.replace("_", " ")} assumption.')
    if type(result['minutes']) is not int or not result['pace_low'] <= result['pace'] <= result['pace_high']:
        raise ValueError('Minutes must be a whole number; pace must be between the low and high estimates.')
    days = result['weekdays']
    if not isinstance(days, list) or not days or any(type(day) is not int or day not in range(7) for day in days) or len(days) != len(set(days)):
        raise ValueError('Choose at least one distinct study weekday.')
    folders = result['folders']
    if not isinstance(folders, list) or not folders or any(not isinstance(key, str) or not key.strip() or len(key) > 240 for key in folders):
        raise ValueError('Choose at least one exact folder.')
    result['folders'] = sorted(set(quiz_folder_identity_key(key) for key in folders))
    result['weekdays'] = sorted(days)
    if any(type(result[key]) is not bool for key in ('paused', 'visible')):
        raise ValueError('Pause and visibility values must be boolean.')
    return result


def state(cur):
    return dict(cur.execute('SELECT * FROM exam_plan_state WHERE id=1').fetchone())


def dashboard_selection(cur, *, saved=None, selected=None):
    """Bind the token to the selection actually displayed, without a migration."""
    if saved is None:
        saved = state(cur)
        selected = cur.execute('SELECT revision FROM exam_plans WHERE id=?', (saved['active_plan_id'],)).fetchone()
    return digest(dict(generation=saved['generation'], active=saved['active_plan_id'],
                       revision=selected['revision'] if selected else None))


def require_dashboard_selection(cur, expected):
    if expected != dashboard_selection(cur):
        raise PlanConflict('The dashboard plan changed in another tab. Reload and check which plan you would replace.')


def read_plan(row):
    if row is None:
        raise PlanConflict('This plan no longer exists. Return to Exam Plans.')
    result = dict(row)
    try:
        result['config'] = validate(json.loads(result.pop('config_json')))
        result['snapshot'] = json.loads(result.pop('scope_json'))
        if not isinstance(result['snapshot'], dict):
            raise ValueError()
    except (TypeError, ValueError):
        result['error'] = 'Saved plan configuration is unsupported. The original record is retained; restore a valid backup or delete only this plan.'
    return result


def get(cur, plan_id):
    return read_plan(cur.execute('SELECT * FROM exam_plans WHERE id=?', (plan_id,)).fetchone())


def list_plans(cur):
    return [read_plan(row) for row in cur.execute('SELECT * FROM exam_plans ORDER BY created_at,id')]


def require_version(cur, plan_id, revision, generation):
    if generation != state(cur)['generation']:
        raise PlanConflict('Data was restored or reset. Reload this page before changing a plan.')
    plan = get(cur, plan_id)
    if type(revision) is not int or revision != plan['revision']:
        raise PlanConflict('This plan changed in another tab. Reload and review its saved choices.')
    return plan


def save(conn, data, *, plan_id=None, revision=None, generation, active=False, known_folders=(), snapshot=None, expected_dashboard=None):
    config = validate(data)
    conn.execute('BEGIN IMMEDIATE')
    cur = conn.cursor()
    if generation != state(cur)['generation']:
        raise PlanConflict('Data was restored. Reload before saving.')
    old = require_version(cur, plan_id, revision, generation) if plan_id else None
    if active:
        require_dashboard_selection(cur, expected_dashboard)
        config['visible'] = True
    elif old:
        # Ordinary editing never changes visibility or the shared selection.
        config['visible'] = old.get('config', {}).get('visible', True)
    old_keys = set(old.get('config', {}).get('folders', [])) if old else set()
    if set(config['folders']) - set(known_folders) - old_keys:
        raise ValueError('A selected folder is no longer available. Review the folder choices.')
    now = study.utc_now()
    if old:
        conn.execute('UPDATE exam_plans SET config_json=?,revision=revision+1,updated_at=? WHERE id=?', (study.encode(config), now, plan_id))
    else:
        plan_id = uuid.uuid4().hex
        conn.execute('INSERT INTO exam_plans(id,config_json,scope_json,created_at,updated_at) VALUES(?,?,?,?,?)', (plan_id, study.encode(config), study.encode(snapshot or {}), now, now))
    if active:
        conn.execute('UPDATE exam_plan_state SET active_plan_id=? WHERE id=1', (plan_id,))
    conn.commit()
    return plan_id


def control(conn, plan_id, action, revision, generation, *, snapshot=None, expected_dashboard=None):
    conn.execute('BEGIN IMMEDIATE')
    plan = require_version(conn.cursor(), plan_id, revision, generation)
    if action == 'delete':
        conn.execute('DELETE FROM exam_plans WHERE id=?', (plan_id,))
    elif action == 'activate':
        require_dashboard_selection(conn.cursor(), expected_dashboard)
        config = plan['config']
        config['visible'] = True
        conn.execute('UPDATE exam_plans SET config_json=? WHERE id=?', (study.encode(config), plan_id))
        conn.execute('UPDATE exam_plan_state SET active_plan_id=? WHERE id=1', (plan_id,))
    elif action == 'acknowledge':
        conn.execute('UPDATE exam_plans SET scope_json=? WHERE id=?', (study.encode(snapshot), plan_id))
    elif action in {'pause', 'hide', 'visibility'} and 'config' in plan:
        config = plan['config']
        key = 'paused' if action == 'pause' else 'visible'
        if action == 'visibility' and not config['visible']:
            raise PlanConflict('Use this plan on your dashboard to show it. Reload the plan for the current controls.')
        config[key] = not config[key] if action == 'pause' else False
        conn.execute('UPDATE exam_plans SET config_json=? WHERE id=?', (study.encode(config), plan_id))
    else:
        raise ValueError('Unknown plan action.')
    if action != 'delete':
        conn.execute('UPDATE exam_plans SET revision=revision+1,updated_at=? WHERE id=?', (study.utc_now(), plan_id))
    conn.commit()


def calendar(config, now):
    today = now.astimezone(ZoneInfo(config['calendar_timezone'])).date()
    exam = date.fromisoformat(config['exam_date'])
    # O(7), including distant valid dates without allocating a daily calendar.
    span = max(0, (exam - today).days)
    weeks, remainder = divmod(span, 7)
    days = weeks * len(config['weekdays']) + sum((today.weekday()+n) % 7 in config['weekdays'] for n in range(remainder))
    return dict(today=today.isoformat(), days=days, study_today=today.weekday() in config['weekdays'] and today < exam,
                potential_minutes=days*config['minutes'], date_state='passed' if exam < today else 'today' if exam == today else 'future')


def next_study_date(config, start):
    """Calendar date only; never convert this value as a UTC instant."""
    exam = date.fromisoformat(config['exam_date'])
    for offset in range(7):
        day = start + timedelta(days=offset)
        if day >= exam:
            break
        if day.weekday() in config['weekdays']:
            return day.isoformat()
    return None


def work_state(report, *, schedules, eligible_ids, today_ids, now):
    """Explain the existing selection. This function never selects or schedules work."""
    config, cal, stats = report['plan']['config'], report['calendar'], report['stats']
    base = '/exam-plans/' + report['plan']['id'] if report['plan'].get('id') else '/exam-plans/new'
    edit = base + '/edit' if report['plan'].get('id') else base
    zone = ZoneInfo(config['calendar_timezone'])
    dates = []
    for item in schedules:
        stamp = learning._parse_learning_datetime(item['next_review'])
        if stamp and stamp > now and set(item['source_question_ids']) & eligible_ids:
            dates.append(stamp.astimezone(zone).date())
    review_date = min(dates) if dates else None
    tomorrow = date.fromisoformat(cal['today']) + timedelta(days=1)
    next_day = next_study_date(config, tomorrow)
    if stats['total'] == 0:
        code, label = 'no_material', 'Choose study material'
        reason = ('The selected folders are missing. Remap them explicitly.' if report['missing_folders'] else
                  'No source questions are in the selected folders. Choose folders containing regular quizzes.')
        action, url = 'Edit study material', edit
    elif stats['blocked'] == stats['total']:
        code, label = 'excluded', 'No study material is included'
        reason = f"No study material is included: {stats['blocked']} questions are excluded by Learning Scope. Exclusions have not been changed."
        action, url = 'Review Learning Scope', '/learning-scope'
    elif not eligible_ids:
        code, label = 'unavailable', 'Included material is unavailable'
        reason = f"{stats['unavailable']} included questions cannot be used. Check missing quiz files, required content packs or unsupported question types."
        action, url = 'Review study material', edit
    elif cal['date_state'] != 'future':
        code, label = 'exam_' + cal['date_state'], 'Exam is today' if cal['date_state'] == 'today' else 'Exam date has passed'
        reason = 'Pre-exam study time ends the day before the exam. Change the date only if your exam has changed; optional practice remains available.'
        action, url = 'Edit exam date', edit
    elif config['paused']:
        code, label = 'paused', 'Suggestions are paused'
        reason = 'Resume suggestions when you are ready. Showing this plan on the dashboard does not unpause it.'
        action, url = None, None
    elif not cal['days']:
        code, label = 'no_dates', 'No study dates remain before the exam'
        reason = 'Your selected weekdays leave no pre-exam study dates. Review availability; the exam date will not move automatically.'
        action, url = 'Edit study availability', edit
    elif not cal['study_today']:
        code, label = 'non_study_day', 'Today is not a selected study day'
        reason = 'Suggestions follow the weekdays in your saved plan calendar. Optional practice is available today.'
        action, url = None, None
    elif report['slots'] == 0:
        code, label = 'budget_too_small', 'One question exceeds the daily estimate'
        reason = 'The expected pace plus review allowance does not fit one question in your daily minutes. Review those assumptions or choose optional practice.'
        action, url = 'Edit pace and availability', edit
    elif report['remaining_slots'] == 0:
        code, label = 'allowance_used', 'Today’s estimated allowance is used'
        reason = f"{stats['today']} distinct questions answered today use the estimated allowance. Extra practice does not consume future days’ time."
        action, url = None, None
    elif report['selected']:
        code, label = 'ready', 'Ready to study'
        reason = 'Coverage needs come first, followed by ranked mistakes, due reviews and other practice within today’s allowance.'
        action, url = None, None
    elif review_date and not report['due'] and not (eligible_ids - today_ids):
        code, label = 'future_reviews', 'Today’s questions have saved answers; reviews come later'
        reason = 'All included, available questions have a saved response today. Remaining estimated work includes future reviews; those reviews are not due yet.'
        action, url = None, None
    else:
        code, label = 'reviewed_today', 'Today’s included questions have saved answers'
        reason = 'No additional distinct questions remain in today’s selection. This is reviewed coverage, not mastery. You can choose optional practice.'
        action, url = None, None
    warnings = []
    if stats['blocked'] and code != 'excluded':
        warnings.append(f"{stats['blocked']} questions are excluded by Learning Scope.")
    if stats['unavailable'] and code != 'unavailable':
        warnings.append(f"{stats['unavailable']} included questions are unavailable.")
    if config['paused'] and code != 'paused':
        warnings.append('Suggestions are also paused.')
    if cal['date_state'] != 'future' and not code.startswith('exam_'):
        warnings.append('No pre-exam study time remains: the exam is today.' if cal['date_state']=='today' else 'No pre-exam study time remains: the exam date has passed.')
    if code == 'reviewed_today' and report['due']:
        warnings.append(f"{len(report['due'])} questions remain due in the existing review schedule. A correction today does not automatically advance an interval.")
    return dict(code=code, label=label, reason=reason, action_label=action, action_url=url,
                next_study_date=next_day if eligible_ids and cal['date_state']=='future' else None,
                next_review_date=review_date.isoformat() if review_date else None,
                optional_practice=bool(eligible_ids), warnings=warnings)


def valid_link(entry, *, data_folder, quiz_folder, artifact_names):
    try:
        html, data = artifact_names(entry)
        for root, name in ((quiz_folder, html), (data_folder, data)):
            path = Path(root) / name
            if path.is_symlink() or not path.is_file() or path.resolve().parent != Path(root).resolve():
                return None
        return '/quizzes/' + quote(html)
    except (ValueError, TypeError, KeyError):
        return None


def catalog(cur, config, registry, folders, *, data_folder, quiz_folder, artifact_names, media_available):
    entries = {str(item.get('id')): item for item in registry}
    selected = set(config['folders'])
    rows = cur.execute('''SELECT q.*,z.generation_kind,z.source_file,z.title AS quiz_title
                          FROM questions q JOIN quizzes z ON z.id=q.quiz_id ORDER BY q.id''').fetchall()
    members, quizzes, revisions = {}, {}, {}
    for row in rows:
        if is_generated_question(row):
            continue
        entry = entries.get(str(row['quiz_id']), {})
        folder = quiz_folder_identity_key(entry.get('folder'))
        if folder not in selected:
            continue
        qid = row['id']
        if row['quiz_id'] not in quizzes:
            quizzes[row['quiz_id']] = dict(id=row['quiz_id'], title=row['quiz_title'], folder=folder,
                url=valid_link(entry, data_folder=data_folder, quiz_folder=quiz_folder, artifact_names=artifact_names))
        revision = study.question_revision(cur, qid)
        revisions[qid] = revision
        members[str(qid)] = dict(uid=row['question_uid'], quiz_id=row['quiz_id'], title=row['quiz_title'],
                                folder=folder, revision=revision, available=bool(quizzes[row['quiz_id']]['url']) and (row['question_type'] or 'choice') in LEARNING_QUESTION_TYPES and media_available(row['media_json']))
    return rows, members, quizzes, revisions


def coverage(cur, members, revisions, now):
    """One factual scan; revisions cached by quiz. Facts never become learning events."""
    history, reviewed, before, full, focused, partial, assisted = set(), set(), set(), set(), set(), set(), set()
    first_mistake, corrected = set(), set()
    quiz_revisions, contiguous = {}, {}
    sessions = {row['id']: row for row in cur.execute('SELECT * FROM study_sessions')}
    responses = {}
    for row in cur.execute('SELECT * FROM study_responses ORDER BY session_id,sequence'):
        responses.setdefault(row['session_id'], []).append(row)
    for sid, session in sessions.items():
        records = responses.get(sid, [])
        sequence = 0
        for record in records:
            if record['sequence'] != sequence + 1:
                break
            sequence = record['sequence']
        contiguous[sid] = sequence
        if not records or len(records) != records[-1]['sequence']:
            continue
        try:
            manifest = json.loads(session['manifest_json'])
            mapping = {item['id']: item for item in manifest}
        except (ValueError, TypeError, KeyError):
            continue
        qz = session['quiz_id']
        if qz not in quiz_revisions:
            quiz_revisions[qz] = study.assessment_revision(cur, qz)
        unchanged = quiz_revisions[qz] == session['assessment_revision']
        latest, first, corrections, actions = {}, {}, set(), set()
        complete_ids = {record['question_id'] for record in records if record['kind'] == 'response' and record['was_correct'] is not None}
        finished = bool(session['completed_at']) and {item['id'] for item in manifest} <= complete_ids
        for record in records:
            item = mapping.get(record['question_id'], {})
            source = item.get('source_id') or record['question_id']
            if str(source) not in members:
                continue
            if record['kind'] != 'response':
                actions.add(source)
                continue
            if source in latest:
                actions.add(source)  # Prior observable answer feedback, not keyboard use.
            latest[source] = record
            if record['was_correct'] is not None:
                first.setdefault(source, record['was_correct'])
                if not first[source] and record['was_correct']:
                    corrections.add(source)
                history.add(source)
                stamp = learning._parse_learning_datetime(record['saved_at'])
                if unchanged and stamp and stamp < now and (not item.get('source_id') or item.get('source_revision') == revisions.get(source)):
                    before.add(source)
            else:
                actions.add(source)
        for source, record in latest.items():
            if record['was_correct'] is None:
                continue
            item = mapping[record['question_id']]
            if not unchanged or (item.get('source_id') and item.get('source_revision') != revisions.get(source)):
                continue
            reviewed.add(source)
            if first.get(source) == 0:
                first_mistake.add(source)
            if source in corrections:
                corrected.add(source)
            stamp = learning._parse_learning_datetime(record['saved_at'])
            if stamp and stamp < now:
                before.add(source)
            if source in actions:
                assisted.add(source)
            if finished:
                (full if session['purpose'] == 'regular' else focused).add((qz, session['assessment_revision']) if session['purpose'] == 'regular' else sid)
            else:
                partial.add(sid)
    return dict(historical=len(history), reviewed=len(reviewed), full=len(full), focused=len(focused), partial=len(partial), assisted=len(assisted),
                first_mistake=len(first_mistake), corrected=len(corrected)), reviewed, before, contiguous


def recorded_answer_sources(cur, members):
    """Historical answer presence for labels only; never feeds learning estimates.

    Exact rows or explicit generated lineage only. No identical-text inference,
    completion backfill or replay of facts excluded by a learning reset.
    """
    by_uid = {item['uid']: int(qid) for qid,item in members.items() if item['uid']}
    result = set()
    for row in cur.execute("""SELECT q.id,q.is_generated_copy,q.source_question_uid
        FROM questions q JOIN (
          SELECT question_id FROM study_responses WHERE kind='response'
          UNION SELECT question_id FROM study_legacy_responses
          UNION SELECT question_id FROM attempt_answers
        ) f ON f.question_id=q.id"""):
        if not row['is_generated_copy'] and str(row['id']) in members:
            result.add(row['id'])
        elif row['is_generated_copy'] and row['source_question_uid'] in by_uid:
            result.add(by_uid[row['source_question_uid']])
    return result


def selected_breakdown(selected, *, needs, recorded, missed, due):
    """Exclusive labels after selection; coverage, then mistakes, due, other."""
    groups = [('new', 'No recorded answer'), ('refresh', 'Coverage / fresh evidence'),
              ('mistakes', 'Mistakes'), ('due', 'Due reviews'), ('other', 'Other practice')]
    counts = dict.fromkeys((key for key,_ in groups), 0)
    for qid in {c['question_id'] for c in selected}:
        key = ('refresh' if qid in recorded else 'new') if qid in needs else 'mistakes' if qid in missed else 'due' if qid in due else 'other'
        counts[key] += 1
    return [dict(key=key, label=label, count=counts[key]) for key,label in groups if counts[key]]


def summary(cur, plan, *, registry, folders, excluded, data_folder, quiz_folder, artifact_names, media_available=lambda value: True, dashboard_panel_visible=True, now=None):
    if plan.get('error'):
        raise ValueError(plan['error'])
    now = now or datetime.now(timezone.utc)
    config = plan['config']
    cal = calendar(config, now)
    zone = ZoneInfo(config['calendar_timezone'])
    midnight = datetime.combine(date.fromisoformat(cal['today']), time(), zone).astimezone(timezone.utc)
    rows, members, quizzes, revisions = catalog(cur, config, registry, folders, data_folder=data_folder, quiz_folder=quiz_folder, artifact_names=artifact_names, media_available=media_available)
    for member in members.values():
        member['excluded'] = member['folder'] in set(excluded)
    all_keys = {quiz_folder_identity_key(entry.get('folder')) for entry in registry} | {'uncategorized'}
    omitted = all_keys - set(config['folders']) | set(excluded)
    scope = build_learning_scope(cur, registry, omitted)
    events = learning._deduplicated_learning_answer_events(cur)
    topics = lambda c, now=None, answer_events=None: learning._learning_topics_with_retention(c, now=now, answer_events=answer_events,
        learning_intelligence_topics=lambda c, **kw: learning._learning_intelligence_topics(c, scope=scope, **kw))
    candidates = learning._adaptive_study_candidates(cur, now=now, scope=scope, answer_events=events, learning_topics_with_retention=topics)
    # Legacy text grouping is useful to the existing ranker, but is not proof
    # that two curriculum rows are the same question. Keep their plan slots distinct.
    row_by_id = {row['id']: row for row in rows}
    expanded = []
    for candidate in candidates:
        source_ids = candidate['source_question_ids']
        for qid in source_ids:
            if str(qid) not in members:
                continue
            source = row_by_id[qid]
            expanded.append({**candidate, 'question_id': qid, 'quiz_id': source['quiz_id'],
                             'question_number': source['question_number'], 'source_question_ids': [qid],
                             'legacy_grouped': len(source_ids) > 1})
    candidates = expanded
    schedules = learning._native_spaced_repetition_schedule(cur, now=now, scope=scope, answer_events=events)['questions']
    stats, reviewed, covered_before, contiguous = coverage(cur, members, revisions, midnight)
    question_keys = {row['id']: canonical_learning_identity(row) for row in rows}
    evidence_by_key = {}
    for event in events:
        key = question_keys.get(event['question_id'])
        evidence_by_key.setdefault(key, []).append(event)
    valid_sessions = {(e['session_id'], e['question_id']) for e in events if e.get('study_contract') == 2}
    work_by_key = {}
    for row in cur.execute("SELECT question_id,session_id,response_json,occurred_at FROM learning_events WHERE event_type='study_answer' AND was_correct IS NOT NULL"):
        if (row['session_id'], row['question_id']) not in valid_sessions:
            continue
        try:
            payload = json.loads(row['response_json'])
            if type(payload.get('sequence')) is not int or payload['sequence'] > contiguous.get(row['session_id'], 0):
                continue
        except (ValueError, TypeError):
            continue
        stamp = learning._parse_learning_datetime(row['occurred_at'])
        if stamp and midnight <= stamp <= now:
            key = question_keys.get(row['question_id'])
            work_by_key[('row', row['question_id']) if key and key[0] == 'legacy' else key] = True
    today, first_today, needs, missed, due, due_before_exam, independent = set(), set(), set(), set(), set(), set(), set()
    followup = set()
    eligible, unavailable = [], []
    for candidate in candidates:
        qid = candidate['question_id']
        evidence = evidence_by_key.get(question_keys[qid], [])
        if question_keys[qid][0] == 'legacy':
            evidence = [event for event in evidence if event['question_id'] == qid]
        timed = [(event, learning._parse_learning_datetime(event['occurred_at'])) for event in evidence]
        work_key = ('row', qid) if question_keys[qid][0] == 'legacy' else question_keys[qid]
        if work_by_key.get(work_key) or any(stamp and midnight <= stamp <= now for _, stamp in timed):
            today.add(qid)
            if not any(stamp and stamp < midnight for _, stamp in timed) or qid not in covered_before:
                first_today.add(qid)
        if not evidence or qid not in reviewed:
            needs.add(qid)
        if any(event.get('independent_success') for event in evidence):
            independent.add(qid)
        # A later session can fulfill follow-up without erasing the ranking's initial difficulty.
        if candidate['score_components'].get('recent_miss'):
            missed.add(qid)
        if evidence and not evidence[-1]['was_correct']:
            followup.add(qid)
        (eligible if members[str(qid)]['available'] else unavailable).append(candidate)
    exam_start = datetime.combine(date.fromisoformat(config['exam_date']), time(), zone)
    for scheduled in schedules:
        source_ids = set(scheduled['source_question_ids'])
        if scheduled['is_due']:
            due.update(source_ids)
        stamp = learning._parse_learning_datetime(scheduled['next_review'])
        if stamp and stamp < exam_start:
            due_before_exam.update(source_ids)
    ids = {c['question_id'] for c in eligible}
    needs &= ids
    slots = math.floor(config['minutes'] / (config['pace'] * (1 + config['reserve']/100)))
    remaining_slots = max(0, slots-len(today & ids))
    target = max(0, math.ceil((len(needs-today)+len(first_today & ids))/cal['days'])-len(first_today & ids)) if cal['days'] else 0
    automatic = cal['study_today'] and not config['paused']
    first_count = min(target, remaining_slots, 50) if automatic else 0
    selected = learning._adaptive_study_select_candidates([c for c in eligible if c['question_id'] in needs-today], first_count) if first_count else []
    remaining = min(50, remaining_slots)-len(selected) if automatic else 0
    for pool in (missed | due, ids):
        chosen = {c['question_id'] for c in selected}
        available = [c for c in eligible if c['question_id'] in pool-today-chosen]
        if remaining > 0 and available:
            extra = learning._adaptive_study_select_candidates(available, remaining, previous=selected)
            selected.extend(extra)
            remaining -= len(extra)
    outstanding = (needs | followup | due_before_exam | due) & ids
    factor = 1 + config['reserve']/100
    workload = len(outstanding)*config['pace']*factor
    # Optional extra practice exhausts today's allowance, never future dates.
    # Responses estimate use of a planning budget; they are not time telemetry.
    today_budget_used = min(config['minutes'], len(today & ids)*config['pace']*factor) if cal['study_today'] else 0
    capacity = max(0, cal['potential_minutes'] - today_budget_used)
    old = plan.get('snapshot', {})
    changes = dict(added=sorted(set(members)-set(old)), removed=sorted(set(old)-set(members)),
                   changed=sorted(key for key in set(members)&set(old) if members[key] != old[key]))
    known = {folder['key'] for folder in folders}
    blocked = sum(member['folder'] in set(excluded) for member in members.values())
    for quiz in quizzes.values():
        quiz['excluded'] = quiz['folder'] in set(excluded)
    fit = ('Even the low estimate exceeds capacity.' if len(outstanding)*config['pace_low']*factor > capacity else
           'The estimate range crosses available capacity; fit is uncertain.' if len(outstanding)*config['pace_high']*factor > capacity else
           'Known work fits the current estimate range; future work can add to it.')
    included_ids = {int(key) for key,member in members.items() if not member['excluded']}
    stats.update(total=len(members), included=len(included_ids), included_reviewed=len(reviewed & included_ids), eligible=len(eligible), blocked=blocked, unavailable=len(included_ids-ids), independent=len(independent), fresh=len(needs & reviewed), today=len(today & ids))
    fingerprint = digest(dict(members=members, excluded=sorted(excluded), generation=state(cur)['generation'], revision=plan['revision']))
    result = dict(plan=plan, calendar=cal, stats=stats, changes=changes, missing_folders=sorted(set(config['folders'])-known),
                snapshot=members, fingerprint=fingerprint, generation=state(cur)['generation'], quizzes=list(quizzes.values()),
                candidates=eligible, missed=sorted(missed & ids), due=sorted(due & ids), selected=selected,
                target=target, slots=slots, remaining_slots=remaining_slots if automatic else 0,
                fit=fit, outstanding=len(outstanding), workload=round(workload,1), low=round(len(outstanding)*config['pace_low']*factor,1),
                high=round(len(outstanding)*config['pace_high']*factor,1), capacity=round(capacity,1), shortfall=round(max(0,workload-capacity),1),
                coverage_shortfall=max(0,len(needs)*config['pace']*factor-capacity), estimated_batch=round(len(selected)*config['pace']*factor,1))
    result['breakdown'] = selected_breakdown(selected, needs=needs, recorded=recorded_answer_sources(cur, members) if selected else set(), missed=missed, due=due)
    result['shortfall_rounded'] = (max(5, round(result['shortfall']/5)*5) if result['shortfall'] >= 5 else math.ceil(result['shortfall']))
    result['estimate_available'] = bool(ids)
    if not ids:
        result['fit'] = 'A useful workload estimate needs included, available study material.'
    result['dashboard_panel_visible'] = dashboard_panel_visible
    result['work_state'] = work_state(result, schedules=schedules, eligible_ids=ids, today_ids=today, now=now)
    return result


def validate_request_id(token):
    if not isinstance(token, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{16,100}', token):
        raise ValueError('Invalid practice request ID. Reload the plan.')


def reserve_action(conn, plan_id, data, *, retry=False):
    """Unique durable reservation. A pending/uncertain operation is never duplicated."""
    token = data.get('request_id')
    validate_request_id(token)
    conn.execute('BEGIN IMMEDIATE')
    require_version(conn.cursor(), plan_id, data.get('revision'), data.get('generation'))
    hashed = digest({'plan_id': plan_id, **data})
    old = conn.execute('SELECT * FROM exam_plan_actions WHERE request_id=?', (token,)).fetchone()
    if old:
        if old['input_hash'] != hashed:
            raise PlanConflict('This request ID was already used with different inputs. Reload before starting different work.')
        if retry and old['state'] == 'retryable' and old['quiz_id'] is None:
            conn.execute("UPDATE exam_plan_actions SET state='pending' WHERE request_id=?", (token,))
            conn.commit()
            return None
        conn.commit()
        return dict(old)
    conn.execute('INSERT INTO exam_plan_actions(request_id,plan_id,generation,input_hash,state) VALUES(?,?,?,?,?)', (token, plan_id, data['generation'], hashed, 'pending'))
    conn.commit()
    return None


def publication_callback(request_id, generation, *, plan_id, revision, sources):
    def record(conn, quiz_id, html):
        if state(conn.cursor())['generation'] != generation:
            raise PlanConflict('Data was restored during publication. Reload the plan.')
        require_version(conn.cursor(), plan_id, revision, generation)
        if any(study.question_revision(conn.cursor(), qid) != expected for qid, expected in sources.items()):
            raise PlanConflict('Source questions changed during publication. Reload before trying again.')
        changed = conn.execute("UPDATE exam_plan_actions SET quiz_id=?,html=?,state='published' WHERE request_id=? AND generation=? AND state='pending'", (quiz_id, html, request_id, generation)).rowcount
        if changed != 1:
            raise PlanConflict('Publication request changed. Reload the plan.')
    return record


def validate_restored_plans(conn):
    """Reject malformed imported configuration before replacing live data."""
    for row in conn.execute('SELECT * FROM exam_plans'):
        plan = read_plan(row)
        if plan.get('error') or type(plan['revision']) is not int or plan['revision'] < 1:
            raise ValueError('Backup contains an unsupported Exam Plan configuration.')
        for key, member in plan['snapshot'].items():
            if not isinstance(key, str) or not key.isdigit() or not isinstance(member, dict) or not isinstance(member.get('title'), str) or not isinstance(member.get('folder'), str) or not isinstance(member.get('revision'), str):
                raise ValueError('Backup contains malformed Exam Plan scope metadata.')
    saved = conn.execute('SELECT * FROM exam_plan_state').fetchall()
    if len(saved) != 1 or saved[0]['id'] != 1 or not isinstance(saved[0]['generation'], str):
        raise ValueError('Backup contains invalid Exam Plan state.')
    if saved[0]['active_plan_id'] and not conn.execute('SELECT 1 FROM exam_plans WHERE id=?', (saved[0]['active_plan_id'],)).fetchone():
        raise ValueError('Backup contains a missing active Exam Plan.')
