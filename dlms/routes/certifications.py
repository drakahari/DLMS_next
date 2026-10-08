"""Earned certification workspace and safe, manually selected AI context."""
from dataclasses import dataclass
from contextlib import contextmanager
from io import BytesIO
import json
import sqlite3
import uuid
from typing import Callable
from flask import Blueprint, abort, redirect, render_template, request, send_file
from dlms.services import certifications as service
from dlms.prompts import DEFAULT_CERTIFICATION_PROMPT


@dataclass(frozen=True)
class CertificationDependencies:
    get_db: Callable
    load_config: Callable
    save_config: Callable
    lock: object


def create_certification_blueprint(deps):
    bp=Blueprint('certifications',__name__)

    @contextmanager
    def database(*, write=False):
        # Restore swaps the database under this same lock. Acquire it before
        # opening a connection so no request can commit to the replaced file.
        with deps.lock:
            conn=deps.get_db()
            try:
                # Record fields and their revision must come from one snapshot.
                if not write:conn.execute('BEGIN')
                yield conn
            finally:conn.close()

    def page(conn, mode, **values):
        cur=conn.cursor()
        return render_template('certifications/workspace.html',page=mode,state=service.state(cur),
            request_id=values.pop('request_id',uuid.uuid4().hex),records=service.collection(cur),**values)

    @bp.get('/certifications')
    def index():
        with database() as conn:return page(conn,'list')

    @bp.get('/certifications/new')
    @bp.get('/certifications/<cert_id>/edit')
    def certification_form(cert_id=None):
        with database() as conn:
            data=service.get(conn.cursor(),'certifications',cert_id)['data'] if cert_id else {}
            return page(conn,'form',kind='certification',record_id=cert_id,fields=data,parent={})

    @bp.get('/certifications/<cert_id>')
    def detail(cert_id):
        with database() as conn:return page(conn,'detail',**service.detail(conn.cursor(),cert_id))

    @bp.get('/certifications/<cert_id>/cycles/new')
    @bp.get('/certifications/<cert_id>/cycles/<cycle_id>/edit')
    def cycle_form(cert_id,cycle_id=None):
        with database() as conn:
            cert=service.get(conn.cursor(),'certifications',cert_id)
            cycle=service.get(conn.cursor(),'certification_cycles',cycle_id) if cycle_id else None
            if cycle and cycle['certification_id']!=cert_id:abort(404)
            return page(conn,'form',kind='cycle',record_id=cycle_id,fields=cycle['data'] if cycle else {},parent=dict(certification_id=cert_id),certification=cert)

    @bp.get('/certifications/training')
    def training():
        with database() as conn:return page(conn,'training',training=service.records(conn.cursor(),'certification_training'))

    @bp.get('/certifications/training/new')
    @bp.get('/certifications/training/<training_id>/edit')
    def training_form(training_id=None):
        with database() as conn:
            data=service.get(conn.cursor(),'certification_training',training_id)['data'] if training_id else {}
            return page(conn,'form',kind='training',record_id=training_id,fields=data,parent={})

    @bp.get('/certifications/<cert_id>/cycles/<cycle_id>/allocate')
    @bp.get('/certifications/<cert_id>/allocations/<allocation_id>/edit')
    def allocation_form(cert_id,cycle_id=None,allocation_id=None):
        with database() as conn:
            cur=conn.cursor(); row=service.get(cur,'certification_allocations',allocation_id) if allocation_id else None
            cycle_id=row['cycle_id'] if row else cycle_id
            cycle=service.get(cur,'certification_cycles',cycle_id)
            if cycle['certification_id']!=cert_id:abort(404)
            return page(conn,'form',kind='allocation',record_id=allocation_id,fields=row['data'] if row else {},
                        training=service.records(cur,'certification_training'),parent=dict(certification_id=cert_id,cycle_id=cycle_id,training_id=row['training_id'] if row else ''))

    @bp.post('/certifications/save')
    def save():
        form=request.form
        try:
            payload=dict(request_id=form.get('request_id'),generation=form.get('generation'),revision=int(form.get('revision','-1')),
                         action=form.get('kind'),id=form.get('record_id') or None,data={k[6:]:v for k,v in form.items() if k.startswith('field_')})
            for key in ('certification_id','cycle_id','training_id'):
                if form.get(key):payload[key]=form[key]
            if payload['action'] in ('cycle','allocation'):
                # Navigation requires this context after the commit. Reject a
                # malformed form before any write, including existing records.
                service.identifier(payload.get('certification_id'))
            for key in ('badge','certificate'):
                if form.get('remove_'+key)=='yes':payload['data'][key]=''
            uploads={k:f.stream.read(service.MAX_ATTACHMENT_BYTES+1) for k,f in request.files.items() if f.filename}
            with database(write=True) as conn:result=service.apply(conn,payload,uploads)
            kind=payload['action']
            url='/certifications/training' if kind=='training' else '/certifications/'+(result['id'] if kind=='certification' else payload['certification_id'])
            return redirect(url+'?saved=1',code=303)
        except (ValueError,sqlite3.Error,OSError) as exc:
            with database() as conn:
                message=str(exc) if isinstance(exc,ValueError) else 'The save failed. No changes were applied. Retry with the same form; reselect any upload.'
                return page(conn,'form',kind=form.get('kind'),record_id=form.get('record_id'),fields={k[6:]:v for k,v in form.items() if k.startswith('field_')},
                    parent={k:form.get(k,'') for k in ('certification_id','cycle_id','training_id')},
                    training=service.records(conn.cursor(),'certification_training'),error=message,request_id=form.get('request_id'),retained_state=dict(generation=form.get('generation'),revision=form.get('revision'))),409 if isinstance(exc,service.Conflict) else 400 if isinstance(exc,ValueError) else 503

    @bp.get('/certifications/remove/<table>/<record_id>')
    def confirm_delete(table,record_id):
        with database() as conn:return page(conn,'delete',record=service.get(conn.cursor(),table,record_id),table=table)

    @bp.post('/certifications/remove')
    def remove():
        f=request.form
        with database(write=True) as conn:
            try:
                service.apply(conn,dict(request_id=f.get('request_id'),generation=f.get('generation'),revision=int(f.get('revision','-1')),
                    action='delete',table=f.get('table'),id=f.get('record_id'),confirm=f.get('confirm')=='yes'))
            except (ValueError,sqlite3.Error) as exc:
                return page(conn,'error',error=str(exc) if isinstance(exc,ValueError) else 'Removal failed. Records were preserved.'),409
        return redirect('/certifications',code=303)

    @bp.get('/certifications/attachments/<attachment_id>')
    def attachment(attachment_id):
        service.identifier(attachment_id)
        with database() as conn:
            row=conn.execute('SELECT * FROM certification_attachments WHERE id=?',(attachment_id,)).fetchone()
        if not row:return 'This attachment is missing. The certification and training records remain available.',404
        # Images can appear as badges; PDFs are download-only, never embedded.
        extension={'image/png':'.png','image/jpeg':'.jpg','image/webp':'.webp','application/pdf':'.pdf'}.get(row['mime'])
        if not extension:abort(415)
        response=send_file(BytesIO(row['content']),mimetype=row['mime'],as_attachment=row['mime']=='application/pdf',download_name='certification-evidence'+extension)
        response.headers['Cache-Control']='no-store'
        response.headers['Content-Security-Policy']="default-src 'none'; sandbox"
        return response

    @bp.post('/certifications/display')
    def display():
        count=request.form.get('count')
        if count not in ('3','6','all'):return 'Choose 3, 6 or All.',400
        with deps.lock:
            cfg=deps.load_config();cfg['certification_display_count']=count;deps.save_config(cfg)
        return redirect('/#myCertifications',code=303)

    @bp.route('/certifications/<cert_id>/ai',methods=['GET','POST'])
    def assistant(cert_id):
        with database() as conn:
            detail=service.detail(conn.cursor(),cert_id); cfg=deps.load_config(); prompt='';error=''
            cycle_id=request.values.get('cycle') or (detail['cycles'][0]['id'] if detail['cycles'] else '')
            cycle=next((c for c in detail['cycles'] if c['id']==cycle_id),None)
            if not cycle:abort(404)
            if request.method=='POST':
                try:
                    prompt=service.curated_prompt(conn.cursor(),cert_id,cycle_id,request.form.getlist('training'),request.form.get('question',''),
                        cfg.get('certification_ai_prompt_template'),include_certification='include_certification' in request.form,include_cycle='include_cycle' in request.form)
                except ValueError as exc:error=str(exc)
            # Matches the existing Law/Study Pack provider launcher, with no prompt in URL.
            url={'chatgpt':'https://chatgpt.com/','claude':'https://claude.ai/','gemini':'https://gemini.google.com/','local':cfg.get('ai_custom_url','')}.get(cfg.get('ai_provider','chatgpt'),'')
            return page(conn,'ai',**detail,cycle=cycle,prompt=prompt,error=error,ai_url=url if cfg.get('ai_helper_enabled',True) else '',question=request.form.get('question',''))

    @bp.errorhandler(ValueError)
    def invalid(exc):
        with database() as conn:return page(conn,'error',error=str(exc)),400

    @bp.errorhandler(sqlite3.Error)
    @bp.errorhandler(OSError)
    def unavailable(exc):
        return 'Certifications are temporarily unavailable. Existing records were not changed. Return to /certifications to retry.',503
    return bp
