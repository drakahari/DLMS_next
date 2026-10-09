"""Explicit review intent. No response, completion, schedule or plan writes."""
import json
import uuid
import re
from collections import Counter
from pathlib import Path
from . import exam_plans as plans, study_sessions as study, learning
from .question_identity import is_generated_question, valid_question_uid
from .learning_scope import build_learning_scope
from ..persistence.review_mark_schema import validate_state

Conflict = plans.PlanConflict


def state(cur):
    return dict(cur.execute('SELECT * FROM review_mark_state WHERE id=1').fetchone())


def require_generation(cur, data):
    if data.get('generation') != state(cur)['generation']:
        raise Conflict('Data was restored or the quiz library was reset. Reload before changing marks.')


def begin_action(conn, data):
    """Reserve once; identical retries return the original acknowledgement."""
    plans.validate_request_id(data.get('request_id'))
    conn.execute('BEGIN IMMEDIATE')
    require_generation(conn.cursor(), data)
    old = conn.execute('SELECT * FROM review_mark_actions WHERE request_id=?', (data['request_id'],)).fetchone()
    if old:
        if old['input_hash'] != plans.digest(data):
            raise Conflict('This request was already used for a different selection. Reload before trying again.')
        return dict(old)
    if type(data.get('revision')) is not int or data.get('revision') != state(conn.cursor())['revision']:
        raise Conflict('Marks changed in another tab. Reload and check your selection.')
    conn.execute("INSERT INTO review_mark_actions(request_id,generation,input_hash,state) VALUES(?,?,?,'pending')", (data['request_id'],data['generation'],plans.digest(data)))
    return None


def acknowledge(conn, data, result):
    conn.execute("UPDATE review_mark_actions SET state='done',result_json=? WHERE request_id=?", (study.encode(result),data['request_id']))
    conn.commit()
    return result


def source(cur, row, *, allow_origin=False):
    if not is_generated_question(row):
        return row
    if '_direct_only' in row.keys() and row['_direct_only']:
        if allow_origin:
            return row
        raise Conflict('This generated hotspot cannot verify its original target revision. Its browser mark was not transferred.')
    rows = cur.execute('''SELECT q.*, z.generation_kind,z.source_file,z.title AS quiz_title FROM questions q
        JOIN quizzes z ON z.id=q.quiz_id WHERE q.question_uid=? AND q.is_generated_copy=0''', (row['source_question_uid'],)).fetchall()
    if not rows and valid_question_uid(row['canonical_question_uid']):
        rows = cur.execute('''SELECT q.*,z.generation_kind,z.source_file,z.title AS quiz_title FROM questions q
            JOIN quizzes z ON z.id=q.quiz_id WHERE q.question_uid=? AND q.is_generated_copy=0''',(row['canonical_question_uid'],)).fetchall()
    if len(rows) != 1 or study.question_revision(cur, rows[0]['id']) != study.question_revision(cur,row['id']):
        if allow_origin:
            return row
        raise Conflict('This generated question no longer matches a verified source. Open the current source to mark it; this copy was not substituted.')
    return rows[0]


def revision(cur, row):
    return row['_mark_revision'] if '_mark_revision' in row.keys() else study.question_revision(cur,row['id'])


def _assessment(item):
    kind=item.get('type','choice')
    content=dict(type=kind,question=item.get('question'),explanation=item.get('explanation') or '')
    if kind=='matching':
        content.update(pairs=[(p.get('left'),p.get('right')) for p in item.get('pairs',[])],round_size=item.get('round_size'),direction=item.get('direction') or 'term_to_definition')
    elif kind!='hotspot':
        content['choices']=[(c.get('label'),c.get('text'),bool(c.get('is_correct'))) for c in item.get('choices',[])]
    for key in ('image','target','hotspot','image_url','image_alt','image_edits','image_source','target_label'):
        if key in item: content[key]=item[key]
    return content


def _context_rows(cur, quiz_id, questions):
    rows=[dict(r) for r in cur.execute('''SELECT q.*,z.generation_kind,z.source_file,z.title AS quiz_title FROM questions q
        JOIN quizzes z ON z.id=q.quiz_id WHERE q.quiz_id=? ORDER BY question_number,q.id''',(quiz_id,))]
    if not isinstance(questions,list) or len(rows)!=len(questions):
        raise Conflict('The source changed. Reload or regenerate this quiz before transferring marks.')
    for row,item in zip(rows,questions):
        if not isinstance(item,dict):
            raise Conflict('The current question data is unavailable.')
        saved=learning._question_payload_from_db(cur,row['id'])
        compared=dict(item)
        direct=item.get('type')=='hotspot'
        if direct:
            # Existing storage retains hotspot media as a choice row. The current
            # verified playable assessment supplies target geometry for this mark
            # only; no Study revision, scoring or learning record is rewritten.
            compared['type']=saved['type']
            compared['choices']=[]
            if saved.get('choices'):
                # Image Study's canonical surrogate retains the explicit target
                # label. Verify that exact representation before comparing it;
                # do not turn arbitrary choice rows into hotspot sources.
                label=item.get('target_label')
                expected=[dict(label='A',text=label,is_correct=True)]
                if (not isinstance(label,str) or not label
                        or saved['choices']!=expected
                        or saved.get('question')!=str(item.get('question') or '')+' [Image hotspot]'):
                    raise Conflict('The source changed. Reload or regenerate this quiz before transferring marks.')
                compared['question']=saved['question']
                compared['choices']=expected
            for key in ('target','hotspot','target_label'):compared.pop(key,None)
        if _assessment(saved)!=_assessment(compared):
            raise Conflict('The source changed. Reload or regenerate this quiz before transferring marks.')
        base=study.question_revision(cur,row['id'])
        row['_mark_revision']=plans.digest(dict(database=base,hotspot=_assessment(item))) if direct else base
        row['_direct_only']=direct
    return rows


def quiz_context(cur, quiz_id, fingerprint, opts):
    questions=study.artifact(cur,quiz_id,fingerprint,registry=opts['registry'],data_folder=opts['data_folder'],artifact_names=opts['artifact_names'])
    return _context_rows(cur,quiz_id,questions)


def mark(conn, data, opts):
    old = begin_action(conn,data)
    if old:
        conn.commit()
        return json.loads(old['result_json'])
    cur=conn.cursor()
    if data.get('action') == 'mark':
        if type(data.get('quiz_id')) is not int or not 1 <= data['quiz_id'] <= 2**63-1 or type(data.get('marked')) is not bool or type(data.get('legacy',False)) is not bool:
            raise ValueError('Choose a quiz and whether to mark the question.')
        rows=quiz_context(cur,data['quiz_id'],data.get('fingerprint'),opts)
        if data.get('assessment_revision') != study.assessment_revision(cur,data['quiz_id']):
            raise Conflict('The question set changed. Reload before saving marks.')
        indexes=data.get('indexes')
        if not isinstance(indexes,list) or not indexes or any(type(i) is not int or not 0<=i<len(rows) for i in indexes) or len(indexes)!=len(set(indexes)):
            raise ValueError('Choose valid question positions; no marks were changed.')
        for index in indexes:
            row=source(cur,rows[index],allow_origin=data.get('legacy',False) is False); uid=row['question_uid']
            if not valid_question_uid(uid):
                uid=uuid.uuid4().hex
                # Identity only; do not rewrite legacy canonical learning evidence.
                cur.execute('UPDATE questions SET question_uid=? WHERE id=?',(uid,row['id']))
            mark_revision=revision(cur,row)
            cur.execute('''INSERT INTO review_marks(id,question_uid,question_revision,quiz_id,question_number,title,question_text,created_at,marked)
                VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(question_uid,question_revision) DO UPDATE SET marked=excluded.marked''',
                (uuid.uuid4().hex,uid,mark_revision,row['quiz_id'],row['question_number'],row['quiz_title'],row['question_text'],study.utc_now(),int(data['marked'])))
    elif data.get('action') == 'unmark':
        ids=data.get('ids')
        if not isinstance(ids,list) or not ids or any(not isinstance(i,str) for i in ids):
            raise ValueError('Select the marks to remove.')
        if any(not cur.execute('SELECT 1 FROM review_marks WHERE id=? AND marked=1',(mid,)).fetchone() for mid in ids):
            raise Conflict('A selected mark changed. Reload before unmarking; no other marks were changed.')
        for mid in set(ids):
            cur.execute('UPDATE review_marks SET marked=0 WHERE id=?',(mid,))
    else:
        raise ValueError('Unsupported mark action.')
    cur.execute('UPDATE review_mark_state SET revision=revision+1 WHERE id=1')
    return acknowledge(conn,data,dict(ok=True,**state(cur)))


def catalog(cur, opts, quiz_id=None):
    """One registry/scope view; retain deleted/revised marks with honest reasons."""
    entries={e.get('id'):e for e in opts['registry']}
    scope=build_learning_scope(cur,opts['registry'],opts['excluded'])
    marks=cur.execute('SELECT * FROM review_marks WHERE marked=1 ORDER BY created_at,id').fetchall()
    rows={r['question_uid']:r for r in cur.execute('''SELECT q.*,z.title AS quiz_title,z.generation_kind,z.source_file
        FROM questions q JOIN quizzes z ON z.id=q.quiz_id WHERE q.question_uid IS NOT NULL''')}
    result=[]
    contexts={}
    def current(row):
        qid=row['quiz_id']
        if qid not in contexts:
            entry=entries.get(qid,{})
            if not plans.valid_link(entry,data_folder=opts['data_folder'],quiz_folder=opts['quiz_folder'],artifact_names=opts['artifact_names']):
                raise Conflict('Quiz files are unavailable. Restore the source files before using this mark.')
            try:
                _,name=opts['artifact_names'](entry)
                questions=json.loads((Path(opts['data_folder'])/name).read_text(encoding='utf-8'))
                contexts[qid]={r['id']:r for r in _context_rows(cur,qid,questions)}
            except (ValueError,OSError,TypeError,KeyError) as exc:
                contexts[qid]=str(exc)
        if isinstance(contexts[qid],str):raise Conflict(contexts[qid])
        return contexts[qid][row['id']]
    current_uids=None
    if quiz_id is not None:
        current_uids=set()
        for row in rows.values():
            if row['quiz_id']==quiz_id:
                try: current_uids.add(source(cur,current(row))['question_uid'])
                except Conflict: pass
    for mark in marks:
        m=dict(mark); row=rows.get(m['question_uid'])
        if quiz_id is not None and m['quiz_id']!=quiz_id and m['question_uid'] not in current_uids:
            continue
        m.update(question_id=None,url=None,folder='Unavailable',practice_reason='',anki_reason='',origin_only=bool(row is not None and is_generated_question(row)))
        reason=''
        if row is None or row['quiz_id']!=m['quiz_id']:
            reason='Source deleted or unavailable. The saved mark is retained.'
        else:
            try:
                row=current(row)
                if revision(cur,row)!=m['question_revision']:
                    reason='Question changed since marking. Open the source and mark the current question separately; the old version will not be substituted.'
            except Conflict as exc:reason=str(exc)
        if row is not None:
            entry=entries.get(row['quiz_id'],{})
            m.update(title=row['quiz_title'],question_number=row['question_number'],folder=entry.get('folder') or 'Uncategorized',url=plans.valid_link(entry,data_folder=opts['data_folder'],quiz_folder=opts['quiz_folder'],artifact_names=opts['artifact_names']))
        if not reason and not m['url']:
            reason='Quiz files are unavailable. Restore the source files before using this mark.'
        if reason:
            m['practice_reason']=m['anki_reason']=reason
        else:
            m['question_id']=row['id']
            kind=row['question_type'] or 'choice'
            if is_generated_question(row):
                m['practice_reason']='This marked copy has no verified matching source revision. Its mark is retained for direct quiz review; it cannot provide source-focused practice.'
            elif row.get('_direct_only') or kind not in {'choice','matching'} or json.loads(row['media_json'] or '{}'):
                m['practice_reason']='Marked practice currently supports text choice and matching questions. Use the source quiz for image or hotspot review; this mark is retained.'
            elif not opts['media_available'](row['media_json']):
                m['practice_reason']='Required images or content pack are unavailable.'
            elif scope and not scope.allows_source(row):
                m['practice_reason']='Excluded by Learning Scope. The mark and direct source access are retained.'
            if row.get('_direct_only') or kind!='choice' or json.loads(row['media_json'] or '{}'):
                m['anki_reason']='Anki export supports text choice questions only; matching and image cards are not converted.'
        result.append(m)
    return result


def selection_review(cur,data,opts):
    """Use the same live eligibility for preview and action; never drop a selection."""
    require_generation(cur,data)
    if type(data.get('revision')) is not int or data.get('revision')!=state(cur)['revision']:
        raise Conflict('Marks changed. Reload and review the selection.')
    ids=data.get('ids')
    if not isinstance(ids,list) or any(not isinstance(v,str) for v in ids) or len(set(ids))!=len(ids):
        raise ValueError('Choose marked questions once each.')
    by_id={m['id']:m for m in catalog(cur,opts)}
    if any(mid not in by_id for mid in ids):
        raise Conflict('A selected mark is no longer available. Reload the list.')
    selected=[by_id[mid] for mid in ids]
    assessments={}
    for action in ('practice','anki'):
        reasons={}
        revisions=Counter(m['question_revision'] for m in selected if not m['practice_reason'])
        duplicates={revision for revision,count in revisions.items() if count>1} if action=='practice' else set()
        for mark in selected:
            reason=mark[action+'_reason']
            if not reason and mark['question_revision'] in duplicates:
                reason='Selected marks include identical questions from different sources. Choose one source for each question.'
            if reason:
                reasons[reason]=reasons.get(reason,0)+1
        excluded=sum(reasons.values())
        assessments[action]=dict(included=len(selected)-excluded,excluded=excluded,reasons=[dict(reason=reason,count=count) for reason,count in reasons.items()])
    return selected,dict(total=len(selected),**assessments)


def selection(cur,data,opts,action):
    selected,review=selection_review(cur,data,opts)
    if not selected:
        raise ValueError('Choose marked questions once each.')
    if review[action]['excluded']:
        raise Conflict(' '.join(item['reason'] for item in review[action]['reasons'])+' Nothing was skipped or unmarked.')
    return selected


def validate_restored_marks(conn):
    try:
        validate_state(conn)
    except RuntimeError as exc:
        raise ValueError('Backup contains invalid marked-question state.') from exc
    for row in conn.execute('SELECT * FROM review_marks'):
        if not valid_question_uid(row['question_uid']) or not valid_question_uid(row['id']) or row['marked'] not in (0,1) or not isinstance(row['question_revision'],str) or not re.fullmatch(r'[0-9a-f]{64}',row['question_revision']) or type(row['quiz_id']) is not int or row['quiz_id']<1 or type(row['question_number']) is not int or any(not isinstance(row[key],str) for key in ('title','question_text','created_at')):
            raise ValueError('Backup contains invalid marked questions; original data is retained.')
    for row in conn.execute('SELECT * FROM review_mark_actions'):
        plans.validate_request_id(row['request_id'])
        if row['state'] not in {'pending','published','retryable','done'} or not isinstance(row['generation'],str) or not isinstance(row['input_hash'],str) or not re.fullmatch(r'[0-9a-f]{64}',row['input_hash']):
            raise ValueError('Backup contains invalid marked-question requests.')
        if row['state']=='done' and not isinstance(json.loads(row['result_json'] or 'null'),dict):
            raise ValueError('Backup contains invalid mark acknowledgements.')
