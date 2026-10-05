"""Marked-question pages and existing Anki/generated-practice integrations."""
import json
import sqlite3
import uuid
from dataclasses import dataclass
from typing import Callable
from flask import Blueprint, jsonify, render_template, request
from dlms.services import review_marks as marks, study_sessions as study, learning, exam_plans as plans
from dlms.services.generated_practice_lifecycle import completion_metadata


@dataclass(frozen=True)
class ReviewMarkDependencies:
    get_db: Callable
    options: Callable
    publish: Callable
    registry_lock: object
    export: Callable
    send_package: Callable


def create_review_mark_blueprint(deps):
    bp=Blueprint('review_marks',__name__)

    def data():
        value=request.get_json()
        if not isinstance(value,dict):
            raise ValueError('A marked-question request is required.')
        return value

    @bp.get('/marked-questions')
    def page():
        conn=deps.get_db()
        try:
            quiz_id=request.args.get('quiz',type=int)
            rows=marks.catalog(conn.cursor(),deps.options(conn.cursor()),quiz_id)
            page=max(1,request.args.get('page',1,type=int)); pages=max(1,(len(rows)+24)//25); page=min(page,pages)
            return render_template('learning/marked_questions.html',marks=rows[(page-1)*25:page*25],total=len(rows),page=page,pages=pages,
                quiz_id=quiz_id,state=marks.state(conn.cursor()),request_id=uuid.uuid4().hex)
        finally: conn.close()

    @bp.post('/api/review-marks/context')
    def context():
        d=data(); conn=deps.get_db()
        try:
            if type(d.get('quiz_id')) is not int or not 1 <= d['quiz_id'] <= 2**63-1: raise ValueError('A quiz is required.')
            cur=conn.cursor(); opts=deps.options(cur)
            rows=marks.quiz_context(cur,d['quiz_id'],d.get('fingerprint'),opts)
            current={(m['question_uid'],m['question_revision']) for m in marks.catalog(cur,opts)}
            marked=[]; unavailable={}
            for i,row in enumerate(rows):
                try:
                    row=marks.source(cur,row,allow_origin=True)
                    if marks.is_generated_question(row): unavailable[str(i)]='This copy is marked separately when no matching source revision can be verified. Use its quiz for direct review.'
                    if (row['question_uid'],marks.revision(cur,row)) in current: marked.append(i)
                except marks.Conflict as exc: unavailable[str(i)]=str(exc)
            return jsonify(ok=True,**marks.state(cur),assessment_revision=study.assessment_revision(cur,d['quiz_id']),indexes=marked,unavailable=unavailable)
        finally: conn.close()

    @bp.post('/api/review-marks/save')
    def save():
        conn=deps.get_db()
        try:
            with deps.registry_lock:
                return jsonify(marks.mark(conn,data(),deps.options(conn.cursor())))
        finally: conn.close()

    @bp.post('/api/review-marks/preview')
    def preview():
        conn=deps.get_db()
        try:
            with deps.registry_lock:
                conn.execute('BEGIN')
                _,review=marks.selection_review(conn.cursor(),data(),deps.options(conn.cursor()))
                return jsonify(ok=True,**review)
        finally: conn.close()

    @bp.post('/api/review-marks/anki')
    def anki():
        conn=deps.get_db()
        try:
            d=data()
            with deps.registry_lock:
                conn.execute('BEGIN IMMEDIATE')
                selected=marks.selection(conn.cursor(),d,deps.options(conn.cursor()),'anki')
                rows=[]
                for mark in selected:
                    q=learning._question_payload_from_db(conn.cursor(),mark['question_id'])
                    choices=q['choices']
                    rows.append(dict(front=q['question']+'\n\n'+'\n'.join(c['label']+'. '+c['text'] for c in choices),
                                     back='\n'.join(c['label']+'. '+c['text'] for c in choices if c['is_correct'])))
                conn.rollback()
            path=deps.export('DLMS — Marked questions',rows)
            return deps.send_package(path,'dlms_marked_questions.apkg')
        finally: conn.close()

    @bp.post('/api/review-marks/generate')
    def generate():
        d=data(); conn=deps.get_db()
        try:
            with deps.registry_lock:
                old=marks.begin_action(conn,d)
                opts=deps.options(conn.cursor())
                if old and old['state']=='published':
                    entry=next((e for e in opts['registry'] if e.get('id')==old['quiz_id'] and e.get('html')==old['html']),{})
                    url=plans.valid_link(entry,data_folder=opts['data_folder'],quiz_folder=opts['quiz_folder'],artifact_names=opts['artifact_names'])
                    if url:
                        conn.commit()
                        return jsonify(ok=True,url=url,title=entry.get('title'),location='Quiz Library → Completed Practice' if completion_metadata(entry,'marked_practice') else 'Quiz Library → Generated Practice',replayed=True)
                if old and old['state']!='retryable':
                    return jsonify(error='This request is still running or its quiz is unavailable. Retry this same request. If DLMS was interrupted, let its next normal startup recover, then check Generated Practice before explicitly starting new work. No second quiz was created.', uncertain=True),409
                selected=marks.selection(conn.cursor(),d,opts,'practice')
                payload=[learning._question_payload_from_db(conn.cursor(),m['question_id']) for m in selected]
                for i,q in enumerate(payload,1): q['number']=i
                if old: conn.execute("UPDATE review_mark_actions SET state='pending' WHERE request_id=?",(d['request_id'],))
                conn.commit()
                def record(db,quiz_id,html):
                    marks.selection(db.cursor(),d,deps.options(db.cursor()),'practice')
                    db.execute("UPDATE review_mark_actions SET state='published',quiz_id=?,html=? WHERE request_id=? AND generation=? AND state='pending'",(quiz_id,html,d['request_id'],d['generation']))
                def rollback():
                    with deps.get_db() as db:
                        db.execute("UPDATE review_mark_actions SET state='retryable' WHERE request_id=? AND generation=? AND quiz_id IS NULL",(d['request_id'],d['generation']))
                title='Marked practice — '+(selected[0]['title'] if len({m['quiz_id'] for m in selected})==1 else 'Selected quizzes')
                _,html=deps.publish(title,payload,filename_prefix='marked_practice',generation_kind='marked_practice',snapshot_existing_assets=True,
                                    publication_record=record,publication_rollback=rollback)
                return jsonify(ok=True,url='/quizzes/'+html,title=title,location='Quiz Library → Generated Practice',replayed=False)
        finally: conn.close()

    @bp.errorhandler(ValueError)
    def invalid(exc):
        return jsonify(error=str(exc)),409 if isinstance(exc,(marks.Conflict,study.StudyConflict)) else 400

    @bp.errorhandler(sqlite3.Error)
    @bp.errorhandler(OSError)
    def storage_error(exc):
        return jsonify(error='Could not save this request. Your marks are retained. Retry the same request; do not clear browser storage.'),503
    return bp
