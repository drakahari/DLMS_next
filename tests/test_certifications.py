"""Disposable credential data, atomic migrations, attachments and manual AI boundaries."""
import copy
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
import json
import sqlite3
import uuid
from pathlib import Path
from unittest import mock
from PIL import Image
from pypdf import PdfWriter
from tests import test_study_sessions as foundation
from dlms.services import certifications as cert, restore
from dlms.persistence import certification_schema
from tests.csrf_test_utils import csrf_headers

dlms=foundation.dlms


class CertificationTests(foundation.unittest.TestCase):
    setUp=foundation.StudySessionTests.setUp
    choice=staticmethod(foundation.StudySessionTests.choice)
    publish=foundation.StudySessionTests.publish
    fingerprint=foundation.StudySessionTests.fingerprint

    def request(self,action,data=None,**kw):
        with dlms.get_db() as c:state=cert.state(c.cursor())
        return dict(request_id=uuid.uuid4().hex,action=action,data=data or {},**state,**kw)

    def apply(self,payload,uploads=None):
        with dlms.get_db() as c:return cert.apply(c,payload,uploads)

    def create(self,name='Earned sample'):
        return self.apply(self.request('certification',dict(name=name,issuer='Example issuer',earned='2025-06-01')))['id']

    def cycle(self,cid):
        with dlms.get_db() as c:return cert.detail(c.cursor(),cid)['cycles'][0]

    @staticmethod
    def png():
        b=BytesIO();Image.new('RGB',(80,80),'white').save(b,'PNG');return b.getvalue()

    @staticmethod
    def pdf(encrypted=False):
        b=BytesIO();w=PdfWriter();w.add_blank_page(width=100,height=100)
        if encrypted:w.encrypt('secret')
        w.write(b);return b.getvalue()

    def test_dates_renewal_history_credit_distinctions_and_reset(self):
        cid=self.create();cycle=self.cycle(cid)
        tid=self.apply(self.request('training',dict(name='Workshop',completed='2026-09-01',hours=8)))['id']
        allocation=self.apply(self.request('allocation',dict(hours=6,submitted=5,accepted=3),cycle_id=cycle['id'],training_id=tid))
        with self.assertRaisesRegex(cert.Conflict,'already has'):
            self.apply(self.request('allocation',dict(hours=6,submitted=5,accepted=3),cycle_id=cycle['id'],training_id=tid))
        self.apply(self.request('training',dict(name='Workshop',completed='2026-09-01',hours=9),id=tid))
        with dlms.get_db() as c:
            self.assertEqual(cert.detail(c.cursor(),cid)['cycles'][0]['totals'],dict(hours=6,submitted=5,accepted=3))
        newer=self.apply(self.request('cycle',dict(start='2026-10-01',required=20,unit='CEUs'),certification_id=cid))
        with dlms.get_db() as c:
            detail=cert.detail(c.cursor(),cid)
            self.assertEqual(len(detail['cycles']),2)
            self.assertEqual(detail['cycles'][0]['totals'],dict(hours=0,submitted=0,accepted=0))
            before={table:[tuple(r) for r in c.execute('SELECT * FROM '+table)] for table in (*cert.TABLES,'certification_attachments')}
        restore.reset_learning_intelligence_core(dlms.DB_PATH)
        with dlms.get_db() as c:
            self.assertEqual(before,{table:[tuple(r) for r in c.execute('SELECT * FROM '+table)] for table in before})
        dlms.bootstrap_database(dlms.DB_PATH)
        self.assertEqual(self.cycle(cid)['data']['start'],'2026-10-01')
        self.assertEqual(cert.day('2026-03-08','Earned'),'2026-03-08')
        self.assertEqual(cert.day('2026-11-01','Earned'),'2026-11-01')

    def test_atomic_retries_concurrent_edits_and_restore_generation(self):
        d=self.request('certification',dict(name='One',issuer='Issuer',earned='2025-01-01'))
        first=self.apply(d);self.assertEqual(first,self.apply(d))
        changed=copy.deepcopy(d);changed['data']['name']='Changed'
        with self.assertRaises(cert.Conflict):self.apply(changed)
        two=self.request('certification',dict(name='Two',issuer='Issuer',earned='2025-01-01'))
        three={**two,'request_id':uuid.uuid4().hex,'data':{**two['data'],'name':'Three'}}
        def run(p):
            try:return self.apply(p)['ok']
            except cert.Conflict:return False
        with ThreadPoolExecutor(2) as pool:self.assertEqual(sorted(pool.map(run,[two,three])),[False,True])
        with dlms.get_db() as c:certification_schema.invalidate(c)
        with self.assertRaisesRegex(cert.Conflict,'predates a restore'):self.apply(d)
        with dlms.get_db() as c:self.assertEqual(len(cert.collection(c.cursor())),2)

    def test_upload_validation_missing_shared_evidence_and_delete_boundaries(self):
        for content in (b'',b'<svg onload="evil()"/>',b'<html>script</html>',self.pdf(True),b'%PDF-broken',b'x'*(cert.MAX_ATTACHMENT_BYTES+1)):
            with self.subTest(size=len(content)),self.assertRaises(ValueError):cert.validate_attachment(content)
        self.assertEqual(cert.validate_attachment(self.pdf()),'application/pdf')
        self.assertEqual(cert.validate_attachment(self.png())[0],'image/png')
        d=self.request('certification',dict(name='A',issuer='I',earned='2025-01-01'))
        cid=self.apply(d,{'badge':self.png()})['id']
        self.assertEqual(self.apply(d,{'badge':self.png()})['id'],cid)
        with dlms.get_db() as c:
            record=cert.get(c.cursor(),'certifications',cid);ref=record['data']['badge']
        other=self.apply(self.request('certification',{**record['data'],'name':'B'}))['id']
        no=self.client.get('/certifications/remove/certifications/'+cid)
        self.assertEqual(no.status_code,200)
        with self.assertRaises(ValueError):self.apply(self.request('delete',id=cid,table='certifications',confirm=False))
        self.apply(self.request('delete',id=cid,table='certifications',confirm=True))
        self.assertEqual(self.client.get('/certifications/attachments/'+ref).status_code,200)
        with dlms.get_db() as c:
            c.execute('DELETE FROM certification_attachments WHERE id=?',(ref,))
        self.assertEqual(self.client.get('/certifications/attachments/'+ref).status_code,404)
        self.assertEqual(self.client.get('/certifications/'+other).status_code,200)
        with dlms.get_db() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM quizzes').fetchone()[0],1)

    def test_prompt_excludes_notes_attachment_ids_and_unselected_information(self):
        cid=self.create();cycle=self.cycle(cid)
        tid=self.apply(self.request('training',dict(name='Training',completed='2026-01-01',provider='Provider',hours=5,notes='PRIVATE NOTES')),{'certificate':self.pdf()})['id']
        aid=self.apply(self.request('allocation',dict(hours=5,submitted=3,accepted=2,notes='PRIVATE ALLOCATION'),cycle_id=cycle['id'],training_id=tid))['id']
        with dlms.get_db() as c:
            prompt=cert.curated_prompt(c.cursor(),cid,cycle['id'],[aid],'Could this qualify?',include_certification=True,include_cycle=True)
            self.assertIn('Training',prompt);self.assertNotIn('PRIVATE',prompt);self.assertNotIn(tid,prompt);self.assertNotIn(aid,prompt)
            minimal=cert.curated_prompt(c.cursor(),cid,cycle['id'],[],'General guidance')
            self.assertNotIn('Earned sample',minimal);self.assertNotIn('selected_training',minimal)
            before=list(c.iterdump())
        self.assertEqual(self.client.post('/certifications/'+cid+'/ai',data=dict(cycle=cycle['id'],question='My question'),headers=self.headers).status_code,200)
        with dlms.get_db() as c:self.assertEqual(list(c.iterdump()),before)

    def test_invalid_forms_and_failed_write_preserve_existing_records(self):
        cid=self.create()
        for data in (dict(name='',issuer='I',earned='2025-01-01'),dict(name='A',issuer='I',earned='2026-02-30'),dict(name='A',issuer='I',earned='2025-1-1')):
            with self.assertRaises(ValueError):self.apply(self.request('certification',data,id=cid),{'badge':self.png()})
        with dlms.get_db() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM certification_attachments').fetchone()[0],0)
        payload=self.request('certification',dict(name='Changed',issuer='I',earned='2025-01-01'),id=cid)
        with mock.patch.object(cert,'normalize',side_effect=sqlite3.OperationalError('disk failure')):
            with self.assertRaises(sqlite3.Error):self.apply(payload,{'badge':self.png()})
        with dlms.get_db() as c:
            self.assertEqual(cert.get(c.cursor(),'certifications',cid)['data']['name'],'Earned sample')
            self.assertEqual(c.execute('SELECT COUNT(*) FROM certification_attachments').fetchone()[0],0)
        self.assertEqual(self.apply(payload)['id'],cid)
        self.assertEqual(self.client.post('/certifications/save',data=dict(kind='training',revision='bad')).status_code,400)

    def test_schema_seven_migration_failure_rerun_and_older_binary(self):
        path=Path(dlms.APP_DATA_DIR)/'schema6.db'
        with dlms.get_db() as source,sqlite3.connect(path) as target:source.backup(target)
        with sqlite3.connect(path) as c:
            for table in reversed(tuple(certification_schema.COLUMNS)):c.execute('DROP TABLE '+table)
            c.execute('UPDATE schema_meta SET version=6')
            old=list(c.iterdump())
        def fail(c):
            certification_schema.migrate(c);raise RuntimeError('interrupted migration')
        with mock.patch.dict(dlms.DLMS_SCHEMA_MIGRATIONS,{7:fail}):
            with self.assertRaisesRegex(RuntimeError,'interrupted'):dlms.bootstrap_database(str(path))
        with sqlite3.connect(path) as c:self.assertEqual(list(c.iterdump()),old)
        result=dlms.bootstrap_database(str(path));self.assertEqual(result['from_version'],6)
        self.assertEqual(dlms.bootstrap_database(str(path))['status'],'current')
        raw=path.read_bytes()
        with mock.patch.object(dlms,'DLMS_SCHEMA_VERSION',6):
            with self.assertRaisesRegex(RuntimeError,'newer'):dlms.bootstrap_database(str(path))
        self.assertEqual(path.read_bytes(),raw)

    def test_backup_evidence_roundtrip_and_unsafe_content_rejected(self):
        cid=self.apply(self.request('certification',dict(name='Badge',issuer='Issuer',earned='2025-01-01')),{'badge':self.png()})['id']
        cycle=self.cycle(cid)
        self.apply(self.request('cycle',{**cycle['data'],'required':20},id=cycle['id'],certification_id=cid),{'certificate':self.pdf()})
        backup=dlms._create_dlms_backup('certification-test')
        # Backup creation itself validates the staged database and attachments.
        import zipfile
        file=backup[0]
        with zipfile.ZipFile(file) as z:
            member=next(n for n in z.namelist() if n.endswith('/results.db'))
            restored=Path(dlms.APP_DATA_DIR)/'roundtrip.db';restored.write_bytes(z.read(member))
        with sqlite3.connect(restored) as c:
            cert.validate_restored(c)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM certification_attachments').fetchone()[0],2)
            c.execute("UPDATE certification_attachments SET content=?",(b'<svg/>',))
        with sqlite3.connect(restored) as c:
            with self.assertRaisesRegex(ValueError,'checksum'):cert.validate_restored(c)

    def test_dashboard_visibility_settings_reachability_and_no_query_when_hidden(self):
        cfg=dlms.load_portal_config();
        from dlms.persistence.portal import dashboard_card_defaults
        cfg['dashboard_card_visibility']={key:False for key in dashboard_card_defaults()}
        dlms._write_settings_portal_config(cfg)
        with mock.patch.object(dlms,'_certifications_dashboard',side_effect=AssertionError('hidden query')):
            page=self.client.get('/');self.assertEqual(page.status_code,200);self.assertNotIn(b'id="myCertifications"',page.data)
        self.assertEqual(self.client.get('/settings/layout').status_code,200)

    def test_staged_restore_old_and_new_backup_invalidates_stale_forms(self):
        import shutil
        cid=self.create(); cycle=self.cycle(cid)
        self.apply(self.request('cycle',{**cycle['data'],'required':20},id=cycle['id'],certification_id=cid),{'certificate':self.pdf()})
        old_request=self.request('certification',dict(name='Stale',issuer='I',earned='2025-01-01'))
        backup,manifest=dlms._create_dlms_backup('roundtrip')
        stage=Path(dlms.APP_DATA_DIR)/'staged-copy'
        report=dlms._validate_dlms_backup(backup)
        dlms._extract_validated_backup(backup,str(stage),report)
        dlms._validate_staged_backup_semantics(str(stage),manifest)
        dlms._prepare_staged_restore_database(str(stage))
        with sqlite3.connect(stage/'results.db') as c:
            c.row_factory=sqlite3.Row
            self.assertEqual(cert.detail(c.cursor(),cid)['cycles'][0]['data']['required'],20)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM certification_attachments').fetchone()[0],1)
            with self.assertRaisesRegex(cert.Conflict,'predates a restore'):cert.apply(c,old_request)
        # A pre-feature schema 6 backup is migrated only in the disposable stage.
        old_stage=Path(dlms.APP_DATA_DIR)/'old-staged-copy';shutil.copytree(stage,old_stage)
        with sqlite3.connect(old_stage/'results.db') as c:
            for table in reversed(tuple(certification_schema.COLUMNS)):c.execute('DROP TABLE '+table)
            c.execute('UPDATE schema_meta SET version=6')
        result=dlms._prepare_staged_restore_database(str(old_stage))
        self.assertEqual(result['bootstrap']['from_version'],6)
        with sqlite3.connect(old_stage/'results.db') as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM certifications').fetchone()[0],0)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM quizzes').fetchone()[0],1)

    def test_active_pdf_and_archive_paths_are_rejected(self):
        from pypdf.generic import DictionaryObject,NameObject,TextStringObject
        stream=BytesIO();writer=PdfWriter();writer.add_blank_page(width=100,height=100)
        writer._root_object[NameObject('/OpenAction')]=DictionaryObject({NameObject('/S'):NameObject('/JavaScript'),NameObject('/JS'):TextStringObject('alert(1)')})
        writer.write(stream)
        with self.assertRaises(ValueError):cert.validate_attachment(stream.getvalue())
        stream=BytesIO();writer=PdfWriter();writer.add_blank_page(width=100,height=100)
        writer.pages[0][NameObject('/A')]=DictionaryObject({NameObject('/S'):NameObject('/Launch'),NameObject('/F'):TextStringObject('evil.exe')})
        writer.write(stream)
        with self.assertRaises(ValueError):cert.validate_attachment(stream.getvalue())
        import zipfile
        unsafe=Path(dlms.APP_DATA_DIR)/'unsafe.zip'
        with zipfile.ZipFile(unsafe,'w') as z:z.writestr('dlms_data/../../escape.pdf',self.pdf())
        with self.assertRaises(ValueError):dlms._validate_dlms_backup(str(unsafe))

    def test_http_upload_filename_is_ignored_and_attachment_removal_is_scoped(self):
        cid=self.create();cycle=self.cycle(cid)
        request=self.request('cycle',{**cycle['data']},id=cycle['id'],certification_id=cid)
        f=dict(request_id=request['request_id'],generation=request['generation'],revision=request['revision'],kind='cycle',record_id=cycle['id'],certification_id=cid,
               **{'field_'+k:v for k,v in cycle['data'].items()})
        f['certificate']=(BytesIO(self.pdf()),'../../unsafe.html')
        response=self.client.post('/certifications/save',data=f,headers=self.headers)
        self.assertEqual(response.status_code,303)
        saved=self.cycle(cid)['data'];ref=saved['certificate']
        response=self.client.get('/certifications/attachments/'+ref)
        self.assertIn('attachment;',response.headers['Content-Disposition']);self.assertEqual(response.headers['Cache-Control'],'no-store')
        self.assertEqual(response.headers['X-Content-Type-Options'],'nosniff')
        self.assertNotIn('unsafe',response.headers['Content-Disposition'])
        self.apply(self.request('cycle',{**saved,'certificate':''},id=cycle['id'],certification_id=cid))
        self.assertEqual(self.client.get('/certifications/attachments/'+ref).status_code,404)
        self.assertEqual(self.client.get('/certifications/'+cid).status_code,200)

    def test_http_content_limits_origin_and_attachment_collision_preserve_records(self):
        cid=self.apply(self.request('certification',dict(name='Preserved',issuer='I',earned='2025-01-01')),{'badge':self.png()})['id']
        with dlms.get_db() as conn:
            record=cert.get(conn.cursor(),'certifications',cid)
            before=list(conn.iterdump())
        payload=self.request('certification',{**record['data'],'name':'Replacement'},id=cid)
        fields=dict(kind='certification',record_id=cid,request_id=payload['request_id'],generation=payload['generation'],revision=payload['revision'],
                    **{'field_'+k:v for k,v in payload['data'].items()})
        for content in (b'<html><script>bad()</script></html>',b'x'*(cert.MAX_ATTACHMENT_BYTES+1)):
            response=self.client.post('/certifications/save',data={**fields,'badge':(BytesIO(content),'image.png','image/png')},headers=self.headers)
            self.assertEqual(response.status_code,400)
        response=self.client.post('/certifications/save',data=fields,headers={**self.headers,'Origin':'https://unrelated.invalid','Sec-Fetch-Site':'cross-site'})
        self.assertEqual(response.status_code,403)
        self.assertEqual(self.client.post('/certifications/save',data=fields).status_code,400)
        response=self.client.post('/certifications/save',data=b'x'*(21*1024*1024+1),content_type='application/octet-stream',headers=self.headers)
        self.assertEqual(response.status_code,413)
        for path in ('../../results.db','%2Fetc%2Fpasswd','not-an-identifier'):
            self.assertIn(self.client.get('/certifications/attachments/'+path).status_code,(400,404))
        with mock.patch.object(cert.uuid,'uuid4',return_value=uuid.UUID(record['data']['badge'])):
            with self.assertRaises(sqlite3.IntegrityError):self.apply(payload,{'badge':self.png()})
        with dlms.get_db() as conn:self.assertEqual(list(conn.iterdump()),before)

    def test_prompt_default_restore_and_visibility_scopes_remain_independent(self):
        cfg=dlms.load_portal_config();cfg['ai_prompt_template']='Unrelated explanation';cfg['dashboard_card_visibility']['certifications']=False;cfg['study_area_visibility']['it']=False
        dlms._write_settings_portal_config(cfg)
        response=self.client.post('/settings/ai/save',data=dict(ai_provider='chatgpt',ai_helper_enabled='on',ai_prompt_template='Unrelated explanation',certification_ai_prompt_template='Custom {{certification_context}}'),headers=self.headers)
        self.assertEqual(response.status_code,302)
        self.assertEqual(dlms.load_portal_config()['certification_ai_prompt_template'],'Custom {{certification_context}}')
        self.assertEqual(dlms.load_portal_config()['ai_prompt_template'],'Unrelated explanation')
        self.assertFalse(dlms.load_portal_config()['dashboard_card_visibility']['certifications'])
        response=self.client.post('/certifications/display',data=dict(count='all'),headers=self.headers)
        self.assertEqual(response.status_code,303)
        cfg=dlms.load_portal_config();self.assertEqual(cfg['certification_display_count'],'all');self.assertFalse(cfg['study_area_visibility']['it'])
        self.assertFalse(cfg['dashboard_card_visibility']['certifications'])

    def test_non_expiring_and_foreign_cycle_scope_are_validated(self):
        cid=self.apply(self.request('certification',dict(name='Permanent',issuer='I',earned='2025-01-01',non_expiring='yes')))['id']
        cycle=self.cycle(cid)
        with self.assertRaisesRegex(ValueError,'non-expiring'):
            self.apply(self.request('cycle',{**cycle['data'],'expiration':'2028-01-01'},id=cycle['id'],certification_id=cid))
        second=self.create('Other')
        self.assertEqual(self.client.get('/certifications/'+second+'/cycles/'+cycle['id']+'/edit').status_code,404)
        self.assertEqual(self.client.get('/certifications/'+second+'/cycles/'+cycle['id']+'/allocate').status_code,404)

    def test_interrupted_schema_seven_migration_and_restart_keep_facts(self):
        import subprocess,sys,os
        path=Path(dlms.APP_DATA_DIR)/'interrupted6.db'
        with dlms.get_db() as source,sqlite3.connect(path) as target:source.backup(target)
        with sqlite3.connect(path) as c:
            for table in reversed(tuple(certification_schema.COLUMNS)):c.execute('DROP TABLE '+table)
            c.execute('UPDATE schema_meta SET version=6');before=list(c.iterdump())
        script="""import os,sys
from dlms.persistence import database as d,certification_schema as s
def crash(c):
 c.execute(s.STATEMENTS[0]);c.execute(s.STATEMENTS[1]);os._exit(73)
d.bootstrap_database(sys.argv[1],schema_version=7,legacy_schema_version=1,legacy_core_tables=d.DLMS_LEGACY_CORE_TABLES,migrations={7:crash},create_current_schema=None,database_table_names=d._database_table_names,read_schema_version=d._read_database_schema_version,validate_current_schema=d._validate_current_database_schema)
"""
        run=subprocess.run([sys.executable,'-c',script,str(path)],cwd=Path(dlms.__file__).parent,env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'},capture_output=True,text=True,timeout=15)
        self.assertEqual(run.returncode,73,run.stderr)
        with sqlite3.connect(path) as c:self.assertEqual(list(c.iterdump()),before)
        self.assertEqual(dlms.bootstrap_database(str(path))['version'],7)
        cid=self.create('Survives app restart')
        script="""import app,sys
from dlms.services import certifications
c=app.get_db()
try:
 assert certifications.get(c.cursor(),'certifications',sys.argv[1])['data']['name']=='Survives app restart'
 print('CERTIFICATION_RESTART_OK')
finally:c.close()
"""
        env={**os.environ,'QUIZAPP_DATA_DIR':dlms.APP_DATA_DIR,'PYTHONDONTWRITEBYTECODE':'1'}
        run=subprocess.run([sys.executable,'-c',script,cid],cwd=Path(dlms.__file__).parent,env=env,capture_output=True,text=True,timeout=15)
        self.assertEqual(run.returncode,0,run.stderr);self.assertIn('CERTIFICATION_RESTART_OK',run.stdout)

    def test_jpeg_webp_orientation_and_unsafe_appended_content_are_normalized(self):
        for format in ('JPEG','WEBP'):
            image=Image.new('RGB',(20,10),'white');b=BytesIO();image.save(b,format)
            mime,content=cert.validate_attachment(b.getvalue()+b'<script>unsafe()</script>')
            self.assertEqual(mime,'image/png');self.assertNotIn(b'<script>',content)
            with Image.open(BytesIO(content)) as restored:self.assertEqual(restored.size,(20,10))
        exif=Image.Exif();exif[274]=6
        b=BytesIO();Image.new('RGB',(20,10),'white').save(b,'JPEG',exif=exif)
        _,content=cert.validate_attachment(b.getvalue())
        with Image.open(BytesIO(content)) as restored:
            self.assertEqual(restored.size,(10,20));self.assertEqual(dict(restored.getexif()),{})
        b=BytesIO();w=PdfWriter();w.write(b)
        with self.assertRaises(ValueError):cert.validate_attachment(b.getvalue())

    def test_form_read_snapshot_cannot_pair_old_fields_with_new_revision(self):
        import re
        cid=self.create()
        with dlms.get_db() as c:
            c.execute('PRAGMA journal_mode=WAL')
            old=cert.state(c.cursor())
        original=cert.get; changed=False
        def interleave(cur,table,record_id):
            nonlocal changed
            value=original(cur,table,record_id)
            if not changed and table=='certifications':
                changed=True
                self.apply(self.request('certification',{**value['data'],'name':'Concurrent update'},id=cid))
            return value
        with mock.patch.object(cert,'get',side_effect=interleave):
            response=self.client.get('/certifications/'+cid+'/edit')
        self.assertEqual(response.status_code,200)
        self.assertIn(b'value="Earned sample"',response.data)
        self.assertEqual(int(re.search(rb'name="revision" value="(\d+)"',response.data)[1]),old['revision'])
        stale=dict(action='certification',data=dict(name='Old form',issuer='I',earned='2025-06-01'),id=cid,request_id=uuid.uuid4().hex,**old)
        with self.assertRaises(cert.Conflict):self.apply(stale)
        with dlms.get_db() as c:self.assertEqual(cert.get(c.cursor(),'certifications',cid)['data']['name'],'Concurrent update')

    def test_restore_lock_precedes_connection_and_rejects_waiting_stale_save(self):
        import threading
        from flask import Flask
        from dlms.routes import certifications as routes
        attempted=threading.Event(); lock=threading.RLock(); opened=[]
        class RestoreLock:
            def __enter__(self):
                attempted.set();lock.acquire();return self
            def __exit__(self,*args):lock.release()
        def connect():
            self.assertTrue(lock._is_owned())
            conn=dlms.get_db();opened.append(conn);return conn
        app=Flask(__name__)
        app.register_blueprint(routes.create_certification_blueprint(routes.CertificationDependencies(
            get_db=connect,load_config=dlms.load_portal_config,save_config=dlms._write_settings_portal_config,lock=RestoreLock())))
        payload=self.request('certification',dict(name='Waiting save',issuer='I',earned='2025-01-01'))
        form=dict(kind='certification',request_id=payload['request_id'],generation=payload['generation'],revision=payload['revision'],
                  **{'field_'+k:v for k,v in payload['data'].items()})
        def save():
            with app.test_client() as client:return client.post('/certifications/save',data=form)
        with mock.patch.object(routes,'render_template',return_value='Stale form'),ThreadPoolExecutor(1) as pool:
            lock.acquire()
            try:
                future=pool.submit(save)
                self.assertTrue(attempted.wait(5),'Save did not reach the restore lock')
                self.assertEqual(opened,[],'Connection opened before restore completed')
                # Restore rotates this generation before releasing the shared lock.
                with dlms.get_db() as conn:certification_schema.invalidate(conn)
            finally:lock.release()
            self.assertEqual(future.result(timeout=5).status_code,409)
        with dlms.get_db() as conn:self.assertEqual(cert.collection(conn.cursor()),[])
        for conn in opened:
            with self.assertRaises(sqlite3.ProgrammingError):conn.execute('SELECT 1')

    def test_import_relationships_do_not_trust_declared_constraints(self):
        for case in ('orphan-cycle','orphan-allocation','duplicate-allocation','conflicting-date'):
            with self.subTest(case=case),sqlite3.connect(':memory:') as conn:
                conn.row_factory=sqlite3.Row;certification_schema.migrate(conn)
                # Same columns, but an untrusted import omitted its constraints.
                conn.execute('DROP TABLE certification_allocations')
                conn.execute('DROP TABLE certification_cycles')
                conn.execute('CREATE TABLE certification_cycles(id TEXT PRIMARY KEY,certification_id TEXT,data_json TEXT)')
                conn.execute('CREATE TABLE certification_allocations(id TEXT PRIMARY KEY,cycle_id TEXT,training_id TEXT,data_json TEXT)')
                cid,cycle,tid=uuid.uuid4().hex,uuid.uuid4().hex,uuid.uuid4().hex
                conn.execute('INSERT INTO certifications VALUES(?,?)',(cid,json.dumps(cert.normalize('certification',dict(name='Earned',issuer='I',earned='2025-01-01')))))
                conn.execute('INSERT INTO certification_training VALUES(?,?)',(tid,json.dumps(cert.normalize('training',dict(name='Activity',completed='2025-01-01',hours=1)))))
                conn.execute('INSERT INTO certification_cycles VALUES(?,?,?)',(cycle,uuid.uuid4().hex if case=='orphan-cycle' else cid,
                    json.dumps(cert.normalize('cycle',dict(start='2024-01-01' if case=='conflicting-date' else '2025-01-01')))))
                conn.execute('INSERT INTO certification_allocations VALUES(?,?,?,?)',(uuid.uuid4().hex,cycle,uuid.uuid4().hex if case=='orphan-allocation' else tid,json.dumps(cert.normalize('allocation',{}))))
                if case=='duplicate-allocation':
                    conn.execute('INSERT INTO certification_allocations VALUES(?,?,?,?)',(uuid.uuid4().hex,cycle,tid,json.dumps(cert.normalize('allocation',{}))))
                before=list(conn.iterdump())
                with self.assertRaises(ValueError):cert.validate_restored(conn)
                self.assertEqual(before,list(conn.iterdump()),'Import validation must remain read-only')

    def test_import_valid_rows_cannot_hide_missing_deletion_or_uniqueness_rules(self):
        for defect in ('missing-cycle-parent', 'restrict-cycle-delete', 'missing-allocation-parent', 'missing-unique'):
            with self.subTest(defect=defect), sqlite3.connect(':memory:') as conn:
                conn.row_factory=sqlite3.Row
                certification_schema.migrate(conn)
                conn.execute('DROP TABLE certification_allocations')
                conn.execute('DROP TABLE certification_cycles')
                cycle_parent = '' if defect=='missing-cycle-parent' else 'REFERENCES certifications(id) ON DELETE '+('RESTRICT' if defect=='restrict-cycle-delete' else 'CASCADE')
                allocation_parent = '' if defect=='missing-allocation-parent' else 'REFERENCES certification_cycles(id) ON DELETE CASCADE'
                unique = '' if defect=='missing-unique' else ', UNIQUE(cycle_id,training_id)'
                conn.execute(f'CREATE TABLE certification_cycles(id TEXT PRIMARY KEY,certification_id TEXT {cycle_parent},data_json TEXT)')
                conn.execute(f'CREATE TABLE certification_allocations(id TEXT PRIMARY KEY,cycle_id TEXT {allocation_parent},training_id TEXT REFERENCES certification_training(id) ON DELETE CASCADE,data_json TEXT{unique})')
                # Valid existing records must not conceal unsafe future operations.
                cid,cycle=uuid.uuid4().hex,uuid.uuid4().hex
                conn.execute('INSERT INTO certifications VALUES(?,?)',(cid,json.dumps(cert.normalize('certification',dict(name='Earned',issuer='I',earned='2025-01-01')))))
                conn.execute('INSERT INTO certification_cycles VALUES(?,?,?)',(cycle,cid,json.dumps(cert.normalize('cycle',dict(start='2025-01-01')))))
                before=list(conn.iterdump())
                with self.assertRaisesRegex(ValueError,'constraint'):cert.validate_restored(conn)
                with self.assertRaisesRegex(ValueError,'constraint'):certification_schema.validate_state(conn)
                self.assertEqual(before,list(conn.iterdump()))

    def test_shared_training_allocations_are_explicit_and_survive_scoped_deletion(self):
        first,second=self.create('First'),self.create('Second')
        tid=self.apply(self.request('training',dict(name='Shared workshop',completed='2026-01-01',hours=8)),{'certificate':self.pdf()})['id']
        cycles=[self.cycle(cid) for cid in (first,second)]
        with dlms.get_db() as conn:
            learning_before={t:[tuple(r) for r in conn.execute('SELECT * FROM '+t)] for t in ('study_sessions','study_responses','learning_events')}
        for cycle in cycles:
            self.apply(self.request('allocation',dict(hours=6,submitted=5,accepted=2.5),cycle_id=cycle['id'],training_id=tid))
        self.apply(self.request('training',dict(name='Shared workshop',completed='2026-01-01',hours=10),id=tid))
        self.apply(self.request('delete',table='certifications',id=first,confirm=True))
        with dlms.get_db() as conn:
            self.assertEqual(cert.detail(conn.cursor(),second)['cycles'][0]['totals'],dict(hours=6,submitted=5,accepted=2.5))
            self.assertEqual(conn.execute('SELECT count(*) FROM certification_allocations').fetchone()[0],1)
            self.assertEqual(conn.execute('SELECT count(*) FROM certification_training').fetchone()[0],1)
            for table,rows in learning_before.items():self.assertEqual(rows,[tuple(r) for r in conn.execute('SELECT * FROM '+table)])

    def test_missing_form_parent_rejects_before_existing_record_update(self):
        cid=self.create();cycle=self.cycle(cid)
        tid=self.apply(self.request('training',dict(name='Activity',completed='2025-06-01',hours=2)))['id']
        aid=self.apply(self.request('allocation',dict(hours=1,submitted=5,accepted=1),cycle_id=cycle['id'],training_id=tid))['id']
        for kind,record_id,data in [('cycle',cycle['id'],{**cycle['data'],'required':17}),
                                    ('allocation',aid,dict(hours=1,submitted=5,accepted=2))]:
            with self.subTest(kind=kind):
                payload=self.request(kind,data,id=record_id,cycle_id=cycle['id'],training_id=tid)
                form=dict(kind=kind,record_id=record_id,request_id=payload['request_id'],generation=payload['generation'],revision=payload['revision'],
                          cycle_id=cycle['id'],training_id=tid,**{'field_'+key:value for key,value in data.items()})
                with dlms.get_db() as conn:before=list(conn.iterdump())
                response=self.client.post('/certifications/save',data=form,headers=self.headers)
                self.assertEqual(response.status_code,400)
                with dlms.get_db() as conn:self.assertEqual(before,list(conn.iterdump()))
