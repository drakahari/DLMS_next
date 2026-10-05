"""Read-only, bounded presentation queries for factual Study history."""
import json

from . import study_sessions as study

SESSION_PAGE_SIZE = 20
LEGACY_PAGE_SIZE = 25
DETAIL_PAGE_SIZE = 25


def positive(value, default=0):
    try:
        return min(max(int(value), 0), 2**63 - 1)
    except (ValueError, TypeError):
        return default


def page_rows(cur, *, legacy=False, before=0, after=0, old_page=1):
    # Immutable insertion order keeps an older session's new answers from moving
    # it across page boundaries. Keyset links also tolerate inserts/deletions.
    table, key = ('study_legacy_responses', 'id') if legacy else ('study_sessions', 'rowid')
    size = LEGACY_PAGE_SIZE if legacy else SESSION_PAGE_SIZE
    where = '1=1' if legacy else 'r.last_activity_at IS NOT NULL'
    total = cur.execute(f'SELECT count(*) FROM {table} r WHERE {where}').fetchone()[0]
    params = []
    boundary = ''
    if before:
        boundary = f' AND r.{key} < ?'; params.append(before)
    elif after:
        boundary = f' AND r.{key} > ?'; params.append(after)
    order = 'ASC' if after and not before else 'DESC'
    # Old page links remain valid entry points; new navigation uses stable keys.
    offset = min(max(old_page-1, 0), 1000000) * size if not (before or after) else 0
    rows = [dict(row) for row in cur.execute(f'''SELECT r.*, r.{key} AS history_key, q.title
        FROM {table} r LEFT JOIN quizzes q ON q.id=r.quiz_id WHERE {where}{boundary}
        ORDER BY r.{key} {order} LIMIT ? OFFSET ?''', (*params, size, offset))]
    if order == 'ASC':
        rows.reverse()
    newer = older = None
    if rows:
        if cur.execute(f'SELECT 1 FROM {table} r WHERE {where} AND r.{key}>? LIMIT 1', (rows[0]['history_key'],)).fetchone():
            newer = rows[0]['history_key']
        if cur.execute(f'SELECT 1 FROM {table} r WHERE {where} AND r.{key}<? LIMIT 1', (rows[-1]['history_key'],)).fetchone():
            older = rows[-1]['history_key']
    return dict(rows=rows, total=total, newer=newer, older=older, size=size)


def session_summaries(cur, rows):
    for row in rows:
        count, sequence = cur.execute('SELECT count(*),coalesce(max(sequence),0) FROM study_responses WHERE session_id=?', (row['id'],)).fetchone()
        row['sequence_complete'] = count == sequence
        row['saved_count'] = count
        row['total'] = len(json.loads(row['manifest_json']))
        row['reviewed'] = cur.execute('''SELECT count(*) FROM study_responses r
            WHERE session_id=? AND kind='response' AND was_correct IS NOT NULL
            AND NOT EXISTS (SELECT 1 FROM study_responses newer WHERE newer.session_id=r.session_id
                AND newer.ordinal=r.ordinal AND newer.kind='response' AND newer.sequence>r.sequence)''', (row['id'],)).fetchone()[0]
        row['coverage_incomplete'] = bool(row['completed_at'] and row['reviewed'] < row['total'])
    return rows


def session_detail(cur, session_id, page=1):
    row = cur.execute('SELECT s.*,q.title FROM study_sessions s LEFT JOIN quizzes q ON q.id=s.quiz_id WHERE s.id=?', (session_id,)).fetchone()
    if row is None:
        return None
    # Only the explicitly expanded session is read. Reuse authoritative ordering
    # and gap semantics; never fill missing responses or infer legacy completion.
    session = study.public_session(cur, row)
    observations = sorted(session['observations'].items(), key=lambda pair: int(pair[0]))
    page = max(1, positive(page, 1))
    start = (page-1)*DETAIL_PAGE_SIZE
    shown = observations[start:start+DETAIL_PAGE_SIZE]
    corrected = {str(r['ordinal']-1) for r in cur.execute("""SELECT DISTINCT r.ordinal FROM study_responses r
        WHERE r.session_id=? AND r.kind='response' AND r.was_correct=1
        AND EXISTS (SELECT 1 FROM study_responses earlier WHERE earlier.session_id=r.session_id
            AND earlier.ordinal=r.ordinal AND earlier.kind='response' AND earlier.was_correct=0
            AND earlier.sequence<r.sequence)""", (session_id,))}
    session['coverage_incomplete'] = session_summaries(cur, [dict(row)])[0]['coverage_incomplete']
    return dict(session=session, observations=shown, corrected=corrected, detail_page=page,
                detail_total=len(observations), detail_more=start+DETAIL_PAGE_SIZE<len(observations))
