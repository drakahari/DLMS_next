"""Schema 12: composition passes, independent of learning estimates."""

import json
import hashlib
from datetime import datetime
import re


STATEMENTS = (
    """CREATE TABLE IF NOT EXISTS study_mistake_state (
        id INTEGER PRIMARY KEY CHECK(id=1), generation TEXT NOT NULL)""",
    "INSERT OR IGNORE INTO study_mistake_state VALUES(1,lower(hex(randomblob(16))))",
    """CREATE TABLE IF NOT EXISTS study_mistake_passes (
        id TEXT PRIMARY KEY, scope_json TEXT NOT NULL, scope_hash TEXT NOT NULL,
        created_at TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS study_mistake_actions (
        request_id TEXT PRIMARY KEY, generation TEXT NOT NULL, input_hash TEXT NOT NULL,
        input_json TEXT NOT NULL, selection_json TEXT NOT NULL, pass_id TEXT,
        state TEXT NOT NULL, quiz_id INTEGER, html TEXT,
        FOREIGN KEY(pass_id) REFERENCES study_mistake_passes(id) ON DELETE CASCADE)""",
    """CREATE TABLE IF NOT EXISTS study_mistake_members (
        pass_id TEXT NOT NULL, question_id INTEGER NOT NULL, revision TEXT NOT NULL,
        position INTEGER NOT NULL, reserved_by TEXT, used_by TEXT,
        PRIMARY KEY(pass_id,question_id), UNIQUE(pass_id,position),
        FOREIGN KEY(pass_id) REFERENCES study_mistake_passes(id) ON DELETE CASCADE,
        FOREIGN KEY(reserved_by) REFERENCES study_mistake_actions(request_id),
        FOREIGN KEY(used_by) REFERENCES study_mistake_actions(request_id))""",
)
COLUMNS = {
    'study_mistake_state': {'id', 'generation'},
    'study_mistake_passes': {'id', 'scope_json', 'scope_hash', 'created_at'},
    'study_mistake_actions': {'request_id', 'generation', 'input_hash', 'input_json', 'selection_json', 'pass_id', 'state', 'quiz_id', 'html'},
    'study_mistake_members': {'pass_id', 'question_id', 'revision', 'position', 'reserved_by', 'used_by'},
}


def migrate(conn):
    for statement in STATEMENTS:
        conn.execute(statement)


def invalidate(conn):
    conn.execute("UPDATE study_mistake_state SET generation=lower(hex(randomblob(16))) WHERE id=1")


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def validate_scope(scope):
    if (not isinstance(scope, dict) or set(scope) != {'folders', 'quizzes'}
            or not isinstance(scope['folders'], list) or not isinstance(scope['quizzes'], list)
            or not 1 <= len(scope['folders']) + len(scope['quizzes']) <= 1000
            or any(not isinstance(v, str) or not v or len(v) > 200 for v in scope['folders'])
            or any(type(v) is not int or v <= 0 for v in scope['quizzes'])
            or scope['folders'] != sorted(set(scope['folders'])) or scope['quizzes'] != sorted(set(scope['quizzes']))):
        raise ValueError('Invalid Study mistakes pass scope.')


def validate_request(data):
    if (not isinstance(data, dict) or set(data) != {'request_id', 'generation', 'scope', 'fingerprint', 'mode', 'count', 'title', 'pass_id'}
            or not isinstance(data['request_id'], str) or not re.fullmatch('[a-zA-Z0-9_-]{16,100}', data['request_id'])
            or not isinstance(data['generation'], str) or not re.fullmatch('[0-9a-f]{32}', data['generation'])
            or not isinstance(data['fingerprint'], str) or not re.fullmatch('[0-9a-f]{64}', data['fingerprint'])
            or not isinstance(data['mode'], str) or data['mode'] not in {'random', 'without-repeats'} or type(data['count']) is not int or not 1 <= data['count'] <= 100
            or not isinstance(data['title'], str) or not data['title'].strip() or len(data['title']) > 200
            or (data['mode'] == 'random' and data['pass_id'] is not None)
            or (data['mode'] == 'without-repeats' and (not isinstance(data['pass_id'], str) or not re.fullmatch('[0-9a-f]{32}', data['pass_id'])))):
        raise ValueError('Name the quiz and choose 1–100 questions and a supported selection mode.')
    validate_scope(data['scope'])


def validate(conn):
    states = conn.execute('SELECT * FROM study_mistake_state').fetchall()
    if len(states) != 1 or states[0]['id'] != 1 or not isinstance(states[0]['generation'], str) or not re.fullmatch('[0-9a-f]{32}', states[0]['generation']):
        raise ValueError('Invalid Study mistakes state.')
    passes = {}
    for row in conn.execute('SELECT * FROM study_mistake_passes'):
        scope = json.loads(row['scope_json'])
        validate_scope(scope)
        if row['scope_hash'] != _hash(scope) or not isinstance(row['id'], str) or not re.fullmatch('[0-9a-f]{32}', row['id']):
            raise ValueError('Invalid Study mistakes scope identity.')
        if not isinstance(row['created_at'], str) or datetime.fromisoformat(row['created_at']).tzinfo is None:
            raise ValueError('Invalid Study mistakes pass timestamp.')
        passes[row['id']] = scope
    actions = {}
    for row in conn.execute('SELECT * FROM study_mistake_actions'):
        data, selection = json.loads(row['input_json']), json.loads(row['selection_json'])
        validate_request(data)
        if (row['state'] not in {'reserved', 'committed', 'published', 'retryable'}
                or row['input_hash'] != _hash(data) or row['request_id'] != data['request_id']
                or row['generation'] != data['generation'] or row['pass_id'] != data['pass_id']
                or not isinstance(selection, dict) or len(selection) != data['count']):
            raise ValueError('Invalid Study mistakes publication state.')
        if row['pass_id'] and passes.get(row['pass_id']) != data['scope']:
            raise ValueError('Study mistakes action does not match its pass.')
        if row['state'] in {'committed', 'published'}:
            if (type(row['quiz_id']) is not int or row['quiz_id'] <= 0 or not isinstance(row['html'], str)
                    or not re.fullmatch(r'[A-Za-z0-9_.-]{1,180}\.html', row['html'])):
                raise ValueError('Invalid Study mistakes publication destination.')
        elif row['quiz_id'] is not None or row['html'] is not None:
            raise ValueError('Unexpected Study mistakes publication destination.')
        for key, revision in selection.items():
            if not key.isdigit() or int(key) <= 0 or str(int(key)) != key or not isinstance(revision, str) or not re.fullmatch('[0-9a-f]{64}', revision):
                raise ValueError('Invalid Study mistakes source revision.')
        actions[row['request_id']] = (dict(row), selection)
    linked = {}
    for row in conn.execute('SELECT * FROM study_mistake_members'):
        if (row['pass_id'] not in passes or type(row['question_id']) is not int or row['question_id'] <= 0 or type(row['position']) is not int or row['position'] < 0
                or not isinstance(row['revision'], str) or not re.fullmatch('[0-9a-f]{64}', row['revision'])
                or (row['reserved_by'] and row['used_by'])):
            raise ValueError('Invalid Study mistakes pass member.')
        aid = row['reserved_by'] or row['used_by']
        if aid:
            action, selection = actions.get(aid, ({}, {}))
            if (action.get('pass_id') != row['pass_id'] or selection.get(str(row['question_id'])) != row['revision']
                    or (row['used_by'] and action.get('state') != 'published')
                    or (row['reserved_by'] and action.get('state') not in {'reserved','committed'})):
                raise ValueError('Invalid Study mistakes member reservation or consumption.')
            linked.setdefault(aid, set()).add(str(row['question_id']))
    for aid, (action, selection) in actions.items():
        expected = set(selection) if action['pass_id'] and action['state'] != 'retryable' else set()
        if linked.get(aid, set()) != expected:
            raise ValueError('Incomplete Study mistakes publication membership.')
