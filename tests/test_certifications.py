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
        newer=self.apply(self.request('cycle',dict(start='2026-10-01',expiration='2029-10-01',required=20,unit='CEUs'),certification_id=cid))
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
        with self.assertRaisesRegex(ValueError,'Does not expire'):
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
        self.assertEqual(dlms.bootstrap_database(str(path))['version'],dlms.DLMS_SCHEMA_VERSION)
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

    def test_unified_current_details_two_attachments_and_separate_early_renewal(self):
        payload=self.request('certification',dict(name='Credential',issuer='Issuer',earned='2020-01-01',expiration='2027-06-01'),edit_current=True)
        saved=self.apply(payload,{'badge':self.png(),'certificate':self.pdf()})
        self.assertEqual(self.apply(payload,{'badge':self.png(),'certificate':self.pdf()}),saved)
        cid=saved['id'];first=self.cycle(cid)
        self.assertEqual(first['data']['start'],'','Unknown effective start must not be invented from earned date')
        with dlms.get_db() as conn:badge=cert.get(conn.cursor(),'certifications',cid)['data']['badge']
        document=first['data']['certificate'];self.assertNotEqual(badge,document)
        edit=self.request('certification',dict(name='Credential',issuer='Issuer',earned='2020-01-01',badge=badge,**{**first['data'],'expiration':'2027-07-01'}),id=cid,cycle_id=first['id'],edit_current=True)
        self.apply(edit,{'badge':self.png()})
        current=self.cycle(cid);self.assertEqual(current['id'],first['id']);self.assertEqual(current['data']['certificate'],document)
        renewal=self.apply(self.request('cycle',dict(start='2027-05-01',renewed='2027-04-01',expiration='2030-07-01'),certification_id=cid))
        with dlms.get_db() as conn:
            periods=cert.detail(conn.cursor(),cid)['cycles']
            self.assertEqual(len(periods),2);self.assertEqual(periods[0]['id'],renewal['id'])
            self.assertEqual(periods[0]['data']['certificate'],'');self.assertEqual(periods[1]['data']['certificate'],document)
            self.assertEqual(periods[0]['totals'],dict(hours=0,submitted=0,accepted=0))
        html=self.client.get('/certifications/'+cid).get_data(as_text=True)
        self.assertIn('Add certificate',html);self.assertIn('/certifications/attachments/'+document,html)
        self.assertNotIn('/certifications/attachments/'+badge,html)
        with self.assertRaises(cert.Conflict):self.apply({**edit,'request_id':uuid.uuid4().hex})
        with self.assertRaisesRegex(ValueError,'conflicts with period'):
            self.apply(self.request('cycle',dict(expiration='2027-07-01'),certification_id=cid))

    def test_http_unified_errors_preserve_fields_and_documents(self):
        request=self.request('certification')
        form=dict(kind='certification',edit_current='yes',request_id=request['request_id'],generation=request['generation'],revision=request['revision'],field_name='Entered title',field_issuer='Issuer',field_earned='2025-01-01',field_expiration='2024-01-01')
        failed=self.client.post('/certifications/save',data={**form,'badge':(BytesIO(self.png()),'badge.png'),'certificate':(BytesIO(self.pdf()),'official.pdf')},headers=self.headers)
        self.assertEqual(failed.status_code,400);self.assertIn('Entered title',failed.get_data(as_text=True))
        with dlms.get_db() as conn:self.assertEqual(conn.execute('SELECT count(*) FROM certification_attachments').fetchone()[0],0)
        form['field_expiration']='2028-01-01'
        response=self.client.post('/certifications/save',data={**form,'badge':(BytesIO(self.png()),'badge.png'),'certificate':(BytesIO(self.pdf()),'official.pdf')},headers=self.headers)
        self.assertEqual(response.status_code,303)
        with dlms.get_db() as conn:
            row=cert.collection(conn.cursor())[0];period=cert.detail(conn.cursor(),row['id'])['cycles'][0]
            self.assertEqual(conn.execute('SELECT count(*) FROM certification_attachments').fetchone()[0],2)
        edit=self.client.get('/certifications/'+row['id']+'/edit').get_data(as_text=True)
        self.assertIn('value="2028-01-01"',edit)
        self.assertIn('/certifications/attachments/'+period['data']['certificate'],edit)
        self.assertEqual(self.client.get('/certifications/attachments/'+period['data']['certificate']).mimetype,'application/pdf')

    def test_non_expiring_after_renewal_keeps_history_and_explicit_image_adoption(self):
        cid=self.apply(self.request('certification',dict(name='A',issuer='I',earned='2020-01-01',expiration='2025-01-01')),{'badge':self.png()})['id']
        first=self.cycle(cid)
        self.apply(self.request('cycle',dict(expiration='2028-01-01'),certification_id=cid));current=self.cycle(cid)
        with dlms.get_db() as conn:data=cert.get(conn.cursor(),'certifications',cid)['data']
        self.apply(self.request('certification',{**data,**current['data'],'non_expiring':'yes','expiration':''},id=cid,cycle_id=current['id'],edit_current=True,use_badge_certificate=True))
        with dlms.get_db() as conn:
            periods=cert.detail(conn.cursor(),cid)['cycles']
            self.assertEqual(periods[0]['data']['certificate'],data['badge'])
            self.assertEqual(periods[1]['data']['expiration'],'2025-01-01')
            cert.validate_restored(conn)
        self.assertEqual(first['id'],periods[1]['id'])

    def test_schema_eight_preserves_periods_and_rejects_failed_order_migration(self):
        path=Path(dlms.APP_DATA_DIR)/'v7-copy.db'
        cid=self.create();first=self.cycle(cid)
        self.apply(self.request('cycle',dict(start='2026-01-01',expiration='2029-01-01'),certification_id=cid))
        with dlms.get_db() as source,sqlite3.connect(path) as conn:source.backup(conn)
        with sqlite3.connect(path) as conn:
            conn.execute('DROP INDEX certification_period_order')
            conn.execute('ALTER TABLE certification_cycles DROP COLUMN period_order')
            conn.execute('UPDATE schema_meta SET version=7')
            before=list(conn.iterdump())
        def fail(conn):certification_schema.migrate_periods(conn);raise RuntimeError('interrupted period migration')
        with mock.patch.dict(dlms.DLMS_SCHEMA_MIGRATIONS,{8:fail}):
            with self.assertRaisesRegex(RuntimeError,'interrupted'):dlms.bootstrap_database(str(path))
        with sqlite3.connect(path) as conn:self.assertEqual(list(conn.iterdump()),before)
        self.assertEqual(dlms.bootstrap_database(str(path))['from_version'],7)
        with sqlite3.connect(path) as conn:
            conn.row_factory=sqlite3.Row
            rows=cert.detail(conn.cursor(),cid)['cycles']
            self.assertEqual([r['period_order'] for r in rows],[2,1]);self.assertEqual(rows[1]['id'],first['id'])
            certification_schema.migrate_periods(conn);cert.validate_restored(conn)
        raw=path.read_bytes()
        with mock.patch.object(dlms,'DLMS_SCHEMA_VERSION',7):
            with self.assertRaisesRegex(RuntimeError,'newer'):dlms.bootstrap_database(str(path))
        self.assertEqual(path.read_bytes(),raw)

    def test_feature_visibility_preserves_data_counts_and_independent_preferences(self):
        cid=self.create();cfg=dlms.load_portal_config();cfg['certification_display_count']='all';dlms._atomic_write_json(dlms.PORTAL_CONFIG,cfg)
        with dlms.get_db() as conn:before=list(conn.iterdump())
        choices={**{'dashboard_card_'+k:'on' for k,v in cfg['dashboard_card_visibility'].items() if v},**{'study_area_'+k:'on' for k,v in cfg['study_area_visibility'].items() if v},'certifications_visibility_present':'yes'}
        self.assertEqual(self.client.post('/settings/layout/save',data=choices,headers=self.headers).status_code,302)
        with mock.patch.object(dlms,'_certifications_dashboard',side_effect=AssertionError('hidden query')):
            html=self.client.get('/').get_data(as_text=True);self.assertNotIn('id="myCertifications"',html)
        cfg2=dlms.load_portal_config();self.assertFalse(cfg2['show_certifications']);self.assertEqual(cfg2['certification_display_count'],'all')
        self.assertEqual(cfg2['dashboard_card_visibility'],cfg['dashboard_card_visibility'])
        self.client.post('/settings/layout/save',data={'action':'dashboard_defaults'},headers=self.headers)
        self.assertFalse(dlms.load_portal_config()['show_certifications'])
        self.client.post('/settings/layout/save',data={**choices,'show_certifications':'on'},headers=self.headers)
        self.assertTrue(dlms.load_portal_config()['show_certifications'])
        self.assertIn('id="myCertifications"',self.client.get('/').get_data(as_text=True))
        with dlms.get_db() as conn:self.assertEqual(list(conn.iterdump()),before)
    def test_custom_issuer_shared_library_unknown_rules_and_portfolio_privacy(self):
        a=self.apply(self.request('certification',dict(name='River stewardship',issuer='Independent Watershed Guild',earned='2025-06-01',version='Field standard 9',notes='PRIVATE ID 12345')))['id']
        b=self.create('Second earned credential');one=self.cycle(a);two=self.cycle(b)
        activity=self.apply(self.request('training',dict(name='Stream survey',provider='Community college',completed='2026-06-10',hours=8,course_url='https://example.org/course',topics='Water sampling',notes='PRIVATE MEDICAL NOTE')),{'certificate':self.pdf()})['id']
        with dlms.get_db() as c:
            self.assertIsNone(cert.detail(c.cursor(),a)['cycles'][0]['progress']['remaining'])
            prompt=cert.portfolio_prompt(c.cursor(),[a,b],[activity],'Which rules apply?')
        for secret in ('PRIVATE',a,b,activity,one['id'],'certificate.pdf'):self.assertNotIn(secret,prompt)
        for expected in ('Independent Watershed Guild','Field standard 9','Unknown','Stream survey','Water sampling','https://example.org/course'):self.assertIn(expected,prompt)
        for period in (one,two):
            self.apply(self.request('allocation',dict(hours=6,proposed=5,reviewed='yes',submitted=4,accepted=2,rationale='Issuer allows field training',source='https://example.org/rules'),cycle_id=period['id'],training_id=activity))
        with self.assertRaisesRegex(cert.Conflict,'already has'):
            self.apply(self.request('allocation',dict(hours=1),cycle_id=one['id'],training_id=activity))
        self.apply(self.request('training',dict(name='Stream survey',completed='2026-06-10',hours=10),id=activity))
        with dlms.get_db() as c:
            self.assertEqual(sum(r['data']['hours'] for r in cert.records(c.cursor(),'certification_training')),10)
            self.assertEqual(self.cycle(a)['totals']['accepted'],2)
            cert.validate_restored(c)
        self.assertIn('Total requirement unknown',self.client.get('/certifications/'+a).get_data(as_text=True))
        self.assertEqual(self.client.get('/certifications/matches').status_code,200)

    def test_annual_reporting_boundaries_caps_and_minimum_versus_pacing(self):
        rules=dict(requirement_known=True,annual_kind='minimum',annual_amount=20,year_basis='anniversary',year_anchor='2025-07-01',reporting_start='2025-07-01',reporting_end='2028-06-30',categories=[dict(name='Field work',minimum=10,cap=15)])
        cid=self.apply(self.request('certification',dict(name='Custom standard',issuer='Open Field Institute',earned='2025-06-01',required=40,tracking=rules)))['id'];cycle=self.cycle(cid)
        for when,credit in [('2026-06-30',10),('2026-07-01',8)]:
            tid=self.apply(self.request('training',dict(name=when,completed=when,hours=10)))['id']
            self.apply(self.request('allocation',dict(hours=10,submitted=credit,accepted=credit,category='Field work'),cycle_id=cycle['id'],training_id=tid))
        p=self.cycle(cid)['progress'];self.assertEqual([y['accepted'] for y in p['annual']],[10,8,0]);self.assertEqual(p['accepted'],15);self.assertEqual(p['remaining'],25);self.assertEqual(p['categories'][0]['over_cap'],3)
        tid=self.apply(self.request('training',dict(name='Outside',completed='2025-06-30',hours=2)))['id']
        with self.assertRaisesRegex(ValueError,'outside'):
            self.apply(self.request('allocation',dict(hours=1,submitted=1),cycle_id=cycle['id'],training_id=tid))
        with self.assertRaisesRegex(ValueError,'Explain'):
            self.apply(self.request('allocation',dict(hours=1,submitted=1,reporting_date='2025-07-01'),cycle_id=cycle['id'],training_id=tid))
        self.apply(self.request('allocation',dict(hours=1,submitted=1,reporting_date='2025-07-01',rationale='Explicit initial-year exception checked with issuer'),cycle_id=cycle['id'],training_id=tid))
        from dlms.services.certification_presets import values
        self.assertEqual(values('cism-2026')['tracking']['annual_kind'],'minimum')
        self.assertEqual(values('cissp-v7')['tracking']['annual_kind'],'pacing')
        self.assertEqual(values('lpic-membership')['required'],60)
        self.assertEqual(values('lpic-membership')['tracking']['annual_kind'],'unknown')
        self.assertEqual(values('lpic-exams')['required'],'')
        self.assertFalse(values('peoplecert-custom')['tracking']['requirement_known'])
        # Date-only boundaries include leap day without shifting timezone.
        from dlms.services.certification_tracking import progress
        fake={**self.cycle(cid),'data':{**cycle['data'],'tracking':{**rules,'reporting_start':'2028-02-28','reporting_end':'2029-03-01','year_anchor':'2028-02-29'}},'allocations':[]}
        years=progress(fake)['annual'];self.assertEqual(years[0]['end'],'2028-02-28');self.assertEqual(years[1]['start'],'2028-02-29');self.assertEqual(years[1]['end'],'2029-02-27')

    def test_directional_relationship_expired_history_and_confirmed_renewal(self):
        a=self.create('Higher credential');b=self.apply(self.request('certification',dict(name='Earlier achievement',issuer='Custom Guild',earned='2025-06-01',expiration='2026-06-01')))['id']
        rel=dict(target=b,trigger='earning',rule='https://example.org/renewal',checked='2026-10-07',conditions='Only version 2 after issuer confirmation')
        payload=self.request('relationship',rel,id=a);first=self.apply(payload);self.assertEqual(first,self.apply(payload))
        with dlms.get_db() as c:
            self.assertEqual(cert.get(c.cursor(),'certifications',b)['data'].get('relationships',[]),[])
            self.assertIn('earned achievement retained',next(r for r in cert.collection(c.cursor()) if r['id']==b)['status'])
        original=self.cycle(b)
        renewal=self.request('cycle',dict(expiration='2029-06-01',renewed='2026-05-01'),certification_id=b,renewal_from=a,renewal_trigger='earning')
        with self.assertRaisesRegex(ValueError,'Confirm'):self.apply(renewal)
        renewal['confirm_relationship']=True;out=self.apply(renewal);self.assertEqual(out,self.apply(renewal))
        self.assertEqual(self.cycle(b)['totals']['accepted'],0)
        self.assertEqual(self.cycle(b)['data']['renewal_source']['name'],'Higher credential')
        self.apply(self.request('relationship',rel,id=a,remove_relationship=True,confirm=True))
        with dlms.get_db() as c:
            self.assertEqual(len(cert.detail(c.cursor(),b)['cycles']),2)
            self.assertEqual(cert.get(c.cursor(),'certification_cycles',original['id'])['data']['expiration'],'2026-06-01')
            cert.validate_restored(c)
        with self.assertRaisesRegex(cert.Conflict,'unavailable'):
            self.apply(self.request('cycle',dict(expiration='2032-06-01'),certification_id=b,renewal_from=a,renewal_trigger='earning',confirm_relationship=True))

    def test_new_metadata_backup_and_settings_roundtrip(self):
        from zipfile import ZipFile
        cid=self.apply(self.request('certification',dict(name='Custom',issuer='Arbitrary issuer',earned='2025-06-01',tracking=dict(requirement_known=False,annual_kind='unknown'))),{'badge':self.png(),'certificate':self.pdf()})['id']
        self.apply(self.request('training',dict(name='Public course',completed='2026-01-01',hours=2,topics='A public description',course_url='https://example.org')))
        cfg=dlms.load_portal_config();cfg.update(show_certifications=False,certification_display_count='11',certification_sort='expiration',portfolio_ai_prompt_template='CUSTOM {{portfolio_context}}',certification_ai_prompt_template='INDEPENDENT {{certification_context}}');dlms._atomic_write_json(dlms.PORTAL_CONFIG,cfg)
        backup,manifest=dlms._create_dlms_backup('portfolio-roundtrip')
        stage=Path(dlms.APP_DATA_DIR)/'portfolio-stage';stage.mkdir()
        report=dlms._validate_dlms_backup(backup);dlms._extract_validated_backup(backup,str(stage),report);dlms._validate_staged_backup_semantics(str(stage),manifest);dlms._prepare_staged_restore_database(str(stage))
        db=next(stage.rglob('results.db'))
        with sqlite3.connect(db) as c:
            c.row_factory=sqlite3.Row;cert.validate_restored(c)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM certification_attachments').fetchone()[0],2)
            self.assertFalse(cert.detail(c.cursor(),cid)['cycles'][0]['progress']['known'])
        configs=[p for p in stage.rglob('*.json') if 'portfolio_ai_prompt_template' in p.read_text()]
        self.assertTrue(configs)
        saved=next(json.loads(p.read_text()) for p in configs if 'show_certifications' in json.loads(p.read_text()))
        self.assertEqual(saved['certification_display_count'],'11');self.assertEqual(saved['certification_sort'],'expiration')
        self.assertFalse(saved['show_certifications']);self.assertEqual(saved['certification_ai_prompt_template'],'INDEPENDENT {{certification_context}}')
    def test_visibility_and_independent_prompts_survive_real_restart(self):
        import os,subprocess,sys
        cid=self.create();cfg=dlms.load_portal_config();cfg.update(certification_display_count='11',certification_sort='name',portfolio_ai_prompt_template='PORTFOLIO {{portfolio_context}}',certification_ai_prompt_template='SINGLE {{certification_context}}')
        with dlms.get_db() as c:before={t:list(c.execute('SELECT * FROM '+t)) for t in cert.TABLES}
        for enabled in (False,True):
            cfg['show_certifications']=enabled;dlms._atomic_write_json(dlms.PORTAL_CONFIG,cfg)
            code="import app,json; c=app.load_portal_config(); print('CHECK:'+json.dumps({k:c[k] for k in ('show_certifications','certification_display_count','certification_sort','portfolio_ai_prompt_template','certification_ai_prompt_template')}))"
            result=subprocess.run([sys.executable,'-c',code],cwd=Path(dlms.__file__).parent,env={**os.environ,'QUIZAPP_DATA_DIR':dlms.APP_DATA_DIR,'PYTHONDONTWRITEBYTECODE':'1'},capture_output=True,text=True,timeout=30)
            self.assertEqual(result.returncode,0,result.stderr)
            actual=json.loads(next(line[6:] for line in result.stdout.splitlines() if line.startswith('CHECK:')))
            self.assertIs(actual['show_certifications'],enabled);self.assertEqual(actual['certification_display_count'],'11');self.assertEqual(actual['certification_sort'],'name')
            self.assertEqual(actual['portfolio_ai_prompt_template'],cfg['portfolio_ai_prompt_template']);self.assertEqual(actual['certification_ai_prompt_template'],cfg['certification_ai_prompt_template'])
        with dlms.get_db() as c:self.assertEqual({t:list(c.execute('SELECT * FROM '+t)) for t in cert.TABLES},before)
        for bad in (None,'false',0,[],{}):
            cfg['show_certifications']=bad;dlms._atomic_write_json(dlms.PORTAL_CONFIG,cfg)
            raw=Path(dlms.PORTAL_CONFIG).read_bytes();self.assertIs(dlms.load_portal_config()['show_certifications'],True)
            self.assertEqual(Path(dlms.PORTAL_CONFIG).read_bytes(),raw)

    def test_unknown_categories_cannot_hide_caps_or_invent_verified_progress(self):
        from dlms.services.certification_tracking import progress
        cid=self.create();cycle=self.cycle(cid)
        row=dict(data=dict(hours=2,submitted=2,accepted=2,category='Typo'),training=dict(data=dict(completed='2026-01-01')))
        cycle['allocations']=[row];cycle['data']['tracking']=dict(requirement_known=True,year_basis='calendar',annual_kind='minimum',annual_amount=1,reporting_start='2026-01-01',reporting_end='2026-12-31',categories=[dict(name='Course',minimum=1,cap=1)])
        p=progress(cycle);self.assertEqual(p['accepted'],0);self.assertEqual(p['unclassified'],[row]);self.assertEqual(p['annual'][0]['accepted'],2)
        for fields in ({'annual_kind':'minimum'}, {'year_basis':'anniversary'}, {'categories':[dict(name='A',minimum=2,cap=1)]}):
            with self.subTest(fields=fields),self.assertRaises(ValueError):cert.normalize('cycle',dict(tracking=fields))
        # Import validation preserves the period-order uniqueness safety boundary.
        with dlms.get_db() as c:
            c.execute('DROP INDEX certification_period_order')
            with self.assertRaisesRegex(ValueError,'uniqueness'):cert.validate_restored(c)

    def test_unknown_earned_date_is_not_invented_and_known_dates_still_validate(self):
        cid=self.apply(self.request('certification',dict(name='Earned long ago',issuer='Any custom organization',non_expiring='yes')))['id']
        with dlms.get_db() as c:
            self.assertEqual(cert.get(c.cursor(),'certifications',cid)['data']['earned'],'')
            self.assertEqual(cert.detail(c.cursor(),cid)['cycles'][0]['data']['start'],'')
            cert.validate_restored(c)
        self.assertIn('not recorded',self.client.get('/certifications/'+cid).get_data(as_text=True))

    def test_unknown_annual_amount_and_singular_library_copy(self):
        cid=self.apply(self.request('certification',dict(name='Custom',issuer='Any issuer',tracking={})))['id']
        form=self.client.get('/certifications/'+cid+'/cycles/'+self.cycle(cid)['id']+'/requirements').get_data(as_text=True)
        self.assertRegex(form,r'name="track_annual_amount"[^>]*value=""')
        self.apply(self.request('training',dict(name='One activity',completed='2026-01-01',hours=1)))
        self.assertIn('1 saved course.',self.client.get('/certifications/training').get_data(as_text=True))

    def test_reporting_calendar_extremes_remain_viewable_and_restorable(self):
        for year in ('0001', '9999'):
            with self.subTest(year=year):
                start, end = year+'-01-01', year+'-12-31'
                cid = self.apply(self.request('certification', dict(
                    name='Calendar boundary '+year, issuer='Custom issuer',
                    tracking=dict(year_basis='calendar', reporting_start=start,
                                  reporting_end=end))))['id']
                response = self.client.get('/certifications/'+cid)
                self.assertEqual(response.status_code, 200)
                annual = self.cycle(cid)['progress']['annual']
                self.assertEqual([(row['start'], row['end']) for row in annual], [(start, end)])
                from dlms.services.certification_tracking import progress
                cycle = self.cycle(cid)
                cycle['data']['tracking'].update(year_basis='anniversary', year_anchor='2000-07-01')
                annual = progress(cycle)['annual']
                self.assertEqual([(row['start'], row['end']) for row in annual],
                                 [(start, year+'-06-30'), (year+'-07-01', end)])
                with dlms.get_db() as conn:
                    cert.validate_restored(conn)

    def test_fractional_credit_progress_has_exact_two_decimal_arithmetic(self):
        cid = self.apply(self.request('certification', dict(
            name='Fractional credits', issuer='Custom issuer', required='.40',
            tracking=dict(requirement_known=True, year_basis='calendar',
                reporting_start='2026-01-01', reporting_end='2026-12-31',
                annual_kind='minimum', annual_amount='.50',
                categories=[dict(name='Course', minimum='.30', cap='.30')]))))['id']
        cycle = self.cycle(cid)
        for credit in ('.10', '.30'):
            tid = self.apply(self.request('training', dict(
                name='Partial course '+credit, completed='2026-06-01', hours=1)))['id']
            self.apply(self.request('allocation', dict(hours=1, submitted=1,
                accepted=credit, category='Course'), cycle_id=cycle['id'], training_id=tid))
            p = self.cycle(cid)['progress']
            if credit == '.10':
                self.assertEqual(p['remaining'], .30)
                self.assertEqual(p['categories'][0]['remaining'], .20)
        self.assertEqual(p['accepted'], .30)
        self.assertEqual(p['remaining'], .10)
        self.assertEqual(p['categories'][0]['over_cap'], .10)
        self.assertEqual(p['annual'][0]['remaining'], .10)
        self.assertEqual(self.cycle(cid)['totals']['accepted'], .40)

    def test_exact_minutes_bulk_estimates_and_backup(self):
        from dlms.services import certification_time
        payload=self.request('training',dict(name='9 h 22 min course',provider='Any provider',completed='2026-10-01',duration_minutes=562,notes='PRIVATE'))
        activity=self.apply(payload)['id']
        with dlms.get_db() as c:
            row=cert.get(c.cursor(),'certification_training',activity)['data']
            self.assertEqual(certification_time.label(row),'9 h 22 min')
            self.assertEqual(row['duration_minutes'],562)
        a=self.apply(self.request('certification',dict(name='Hours goal',issuer='Custom',required=20,unit='hours',tracking=dict(requirement_known=True),expiration='2028-01-01')))['id']
        b=self.apply(self.request('certification',dict(name='Unknown conversion',issuer='Custom',unit='PDU',expiration='2028-01-01')))['id']
        periods=[self.cycle(a),self.cycle(b)]
        page=self.client.get('/certifications/training/'+activity+'/renewals').get_data(as_text=True)
        self.assertIn('9 h 22 min',page);self.assertIn('value="9.37"',page)
        batch=self.request('use_training',training_id=activity,entries=[dict(certification_id=a,cycle_id=periods[0]['id'],proposed='9.37'),dict(certification_id=b,cycle_id=periods[1]['id'],proposed=None)])
        saved=self.apply(batch);self.assertEqual(saved,self.apply(batch))
        self.assertEqual(self.cycle(a)['planning']['accepted'],9.37)
        self.assertEqual(self.cycle(a)['totals']['accepted'],0)
        self.assertEqual(self.cycle(a)['duration_label'],'9 h 22 min')
        self.assertEqual(self.cycle(b)['planning']['unknown'],1)
        with dlms.get_db() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM certification_allocations').fetchone()[0],2)
            prompt=cert.portfolio_prompt(c.cursor(),[a,b],[activity],'Compare')
            self.assertIn('9 h 22 min',prompt);self.assertIn('562',prompt);self.assertNotIn('PRIVATE',prompt)
            cert.validate_restored(c)
        backup,manifest=dlms._create_dlms_backup('exact-minutes')
        stage=Path(dlms.APP_DATA_DIR)/'minute-stage';stage.mkdir()
        checked=dlms._validate_dlms_backup(backup);dlms._extract_validated_backup(backup,str(stage),checked)
        dlms._validate_staged_backup_semantics(str(stage),manifest);dlms._prepare_staged_restore_database(str(stage))
        with sqlite3.connect(stage/'results.db') as c:
            c.row_factory=sqlite3.Row
            self.assertEqual(cert.get(c.cursor(),'certification_training',activity)['data']['duration_minutes'],562)
            self.assertEqual(cert.detail(c.cursor(),a)['cycles'][0]['duration_label'],'9 h 22 min')

    def test_bulk_failure_stale_retry_and_existing_acceptance_are_atomic(self):
        a=self.create('A');b=self.create('B');pa=self.cycle(a);pb=self.cycle(b)
        tid=self.apply(self.request('training',dict(name='Course',completed='2026-01-01',duration_minutes=562)))['id']
        bad=self.request('use_training',training_id=tid,entries=[dict(certification_id=a,cycle_id=pa['id'],proposed=5),dict(certification_id=b,cycle_id=pb['id'],proposed='bad')])
        with dlms.get_db() as c:before=list(c.iterdump())
        with self.assertRaises(ValueError):self.apply(bad)
        with dlms.get_db() as c:self.assertEqual(list(c.iterdump()),before)
        good={**bad,'entries':[dict(certification_id=a,cycle_id=pa['id'],proposed=5),dict(certification_id=b,cycle_id=pb['id'],proposed=4)]}
        result=self.apply(good);self.assertEqual(result,self.apply(good))
        with self.assertRaises(cert.Conflict):self.apply({**good,'entries':[good['entries'][0]]})
        allocation=self.cycle(a)['allocations'][0]
        self.apply(self.request('allocation',{**allocation['data'],'submitted':4,'accepted':2},id=allocation['id'],cycle_id=pa['id'],training_id=tid))
        self.apply(self.request('use_training',training_id=tid,entries=[dict(certification_id=a,cycle_id=pa['id'],proposed=3)]))
        current=self.cycle(a)
        self.assertEqual(len(current['allocations']),1);self.assertEqual(current['totals']['accepted'],2)
        self.assertEqual(current['planning']['accepted'],3) # not 3+4+2
        stale=self.request('use_training',training_id=tid,entries=[dict(certification_id=b,cycle_id=pb['id'],proposed=8)])
        self.apply(self.request('cycle',dict(expiration='2029-01-01'),certification_id=b))
        with self.assertRaises(cert.Conflict):self.apply(stale)

    def test_duration_forms_validate_and_preserve_legacy_decimals(self):
        tid=self.apply(self.request('training',dict(name='Old',completed='2026-01-01',hours=9.37)))['id']
        with dlms.get_db() as c:original=cert.get(c.cursor(),'certification_training',tid)['data']
        edit=self.client.get('/certifications/training/'+tid+'/edit').get_data(as_text=True)
        self.assertIn('value="22.2"',edit)
        req=self.request('training')
        form=dict(kind='training',record_id=tid,request_id=req['request_id'],generation=req['generation'],revision=req['revision'],field_name='Old',field_completed='2026-01-01',duration_hours='9',duration_minutes='22.2')
        self.assertEqual(self.client.post('/certifications/save',data=form,headers=self.headers).status_code,303)
        with dlms.get_db() as c:self.assertEqual(cert.get(c.cursor(),'certification_training',tid)['data'],original)
        for hours,minutes in [('9','60'),('1.5','2'),('-1','0'),('9','-1'),('nan','0')]:
            with self.subTest(hours=hours,minutes=minutes):
                req=self.request('training');f={**form,'record_id':'','request_id':req['request_id'],'revision':req['revision'],'duration_hours':hours,'duration_minutes':minutes}
                failed=self.client.post('/certifications/save',data=f,headers=self.headers)
                self.assertEqual(failed.status_code,400);self.assertIn('value="Old"',failed.get_data(as_text=True))
        req=self.request('training');f={**form,'request_id':req['request_id'],'revision':req['revision'],'duration_minutes':'22'}
        self.assertEqual(self.client.post('/certifications/save',data=f,headers=self.headers).status_code,303)
        with dlms.get_db() as c:self.assertEqual(cert.get(c.cursor(),'certification_training',tid)['data']['duration_minutes'],562)

    def test_schema_nine_guard_does_not_convert_legacy_values(self):
        tid=self.apply(self.request('training',dict(name='Legacy',completed='2026-01-01',hours=9.37)))['id']
        path=Path(dlms.APP_DATA_DIR)/'schema8.db'
        with dlms.get_db() as source,sqlite3.connect(path) as target:source.backup(target)
        with sqlite3.connect(path) as c:
            c.execute('UPDATE schema_meta SET version=8');before=list(c.iterdump())
        def fail(c):certification_schema.migrate_minutes(c);raise RuntimeError('guard migration interruption')
        with mock.patch.dict(dlms.DLMS_SCHEMA_MIGRATIONS,{9:fail}):
            with self.assertRaisesRegex(RuntimeError,'interruption'):dlms.bootstrap_database(str(path))
        with sqlite3.connect(path) as c:self.assertEqual(list(c.iterdump()),before)
        self.assertEqual(dlms.bootstrap_database(str(path))['version'],dlms.DLMS_SCHEMA_VERSION)
        with sqlite3.connect(path) as c:
            c.row_factory=sqlite3.Row
            self.assertEqual(cert.get(c.cursor(),'certification_training',tid)['data']['hours'],9.37)
            self.assertNotIn('duration_minutes',cert.get(c.cursor(),'certification_training',tid)['data'])
        raw=path.read_bytes()
        with mock.patch.object(dlms,'DLMS_SCHEMA_VERSION',8):
            with self.assertRaisesRegex(RuntimeError,'newer'):dlms.bootstrap_database(str(path))
        self.assertEqual(path.read_bytes(),raw)

    def test_custom_display_counts_sort_and_ai_defaults(self):
        a=self.apply(self.request('certification',dict(name='Z',issuer='I',expiration='2028-01-01')))['id']
        b=self.apply(self.request('certification',dict(name='A',issuer='I',expiration='2027-01-01')))['id']
        unknown=self.create('Unknown status')
        page=self.client.get('/certifications/matches').get_data(as_text=True)
        for cid in (a,b):self.assertIn('value="'+cid+'" checked',page)
        self.assertIn('value="'+unknown+'" >',page)
        for count in ('1','7','1000','all'):
            self.assertEqual(self.client.post('/certifications/display',data={'count':count,'sort':'name'},headers=self.headers).status_code,303)
            self.assertEqual(dlms.load_portal_config()['certification_display_count'],count)
            rows=dlms._certifications_dashboard()['rows'];self.assertEqual(rows[0]['id'],b)
        before=Path(dlms.PORTAL_CONFIG).read_bytes()
        for count in ('0','-1','1.5','NaN',''):
            self.assertEqual(self.client.post('/certifications/display',data={'count':count},headers=self.headers).status_code,400)
            self.assertEqual(Path(dlms.PORTAL_CONFIG).read_bytes(),before)

    def test_bulk_concurrent_replays_and_restored_generation(self):
        cid=self.create();period=self.cycle(cid)
        tid=self.apply(self.request('training',dict(name='One exact course',completed='2026-01-01',duration_minutes=562)))['id']
        request=self.request('use_training',training_id=tid,entries=[dict(certification_id=cid,cycle_id=period['id'],proposed=5)])
        with ThreadPoolExecutor(2) as pool:
            results=list(pool.map(self.apply,[request,copy.deepcopy(request)]))
        self.assertEqual(results[0],results[1])
        self.assertEqual(len(self.cycle(cid)['allocations']),1)
        self.assertEqual(self.cycle(cid)['planning']['accepted'],5)
        with dlms.get_db() as c:certification_schema.invalidate(c)
        with self.assertRaisesRegex(cert.Conflict,'predates a restore'):self.apply(request)
        self.assertEqual(len(self.cycle(cid)['allocations']),1)

    def test_estimated_progress_respects_dates_caps_and_distinct_stages(self):
        from dlms.services.certification_tracking import planning_progress
        cid=self.apply(self.request('certification',dict(name='Planning',issuer='Any',required=20,
            tracking=dict(requirement_known=True,reporting_start='2026-07-01',reporting_end='2028-06-30',
            year_basis='anniversary',year_anchor='2026-07-01',annual_kind='pacing',annual_amount=10,
            categories=[dict(name='Courses',cap=8)]))))['id']
        period=self.cycle(cid)
        for day,category,proposed,submitted,accepted in [('2026-06-30','Courses',9,0,0),('2026-07-01','Courses',6,5,2),('2027-06-30','Courses',6,0,0),('2027-07-01','',3,0,0)]:
            tid=self.apply(self.request('training',dict(name=day,completed=day,hours=9)))['id']
            self.apply(self.request('allocation',dict(hours=9,category=category,proposed=proposed,submitted=submitted,accepted=accepted),cycle_id=period['id'],training_id=tid))
        cycle=self.cycle(cid);original=copy.deepcopy(cycle)
        result=planning_progress(cycle)
        self.assertEqual(result['accepted'],11) # 8 capped + 3 unclassified, not sum of workflow stages
        self.assertEqual(result['remaining'],9);self.assertEqual(len(result['excluded']),1)
        self.assertEqual([y['accepted'] for y in result['annual']],[12,3])
        self.assertEqual(cycle,original);self.assertEqual(cycle['totals']['accepted'],2)

    def test_layout_display_validation_and_scoped_defaults(self):
        cfg=dlms.load_portal_config();cfg.update(certification_display_count='7',certification_sort='name',show_certifications=False)
        dlms._atomic_write_json(dlms.PORTAL_CONFIG,cfg);before=Path(dlms.PORTAL_CONFIG).read_bytes()
        for mode,count in [('custom','0'),('custom','2.5'),('invalid','3')]:
            response=self.client.post('/settings/layout/save',data=dict(action='save',certification_count_mode=mode,certification_display_count=count),headers=self.headers)
            self.assertEqual(response.status_code,400);self.assertEqual(Path(dlms.PORTAL_CONFIG).read_bytes(),before)
        for action in ('dashboard_defaults','sidebar_defaults'):
            self.assertEqual(self.client.post('/settings/layout/save',data=dict(action=action),headers=self.headers).status_code,302)
            saved=dlms.load_portal_config();self.assertEqual(saved['certification_display_count'],'7');self.assertEqual(saved['certification_sort'],'name');self.assertFalse(saved['show_certifications'])
        self.assertEqual(self.client.post('/settings/layout/save',data=dict(action='save',certification_count_mode='custom',certification_display_count='19',certification_sort='expiration'),headers=self.headers).status_code,302)
        self.assertEqual(dlms.load_portal_config()['certification_display_count'],'19')

    def test_reviewed_prompt_uses_selected_provider_without_prompt_in_url(self):
        cid=self.create();cfg=dlms.load_portal_config()
        from html.parser import HTMLParser
        class Links(HTMLParser):
            def __init__(self):super().__init__();self.urls=[]
            def handle_starttag(self,tag,attrs):
                attrs=dict(attrs)
                if attrs.get('id')=='certProviderLink':self.urls.append(attrs['href'])
        for provider,url in [('chatgpt','https://chatgpt.com/'),('claude','https://claude.ai/'),('gemini','https://gemini.google.com/'),('local','http://192.0.2.1:8080/')]:
            with self.subTest(provider=provider):
                cfg.update(ai_provider=provider,ai_custom_url=url,ai_helper_enabled=True);dlms._atomic_write_json(dlms.PORTAL_CONFIG,cfg)
                response=self.client.post('/certifications/matches',data=dict(credentials=cid,question='Exact reviewed selection'),headers=self.headers)
                self.assertEqual(response.status_code,200);html=response.get_data(as_text=True)
                links=Links();links.feed(html);self.assertEqual(links.urls,[url])
                self.assertIn('Copy &amp; open AI',html);self.assertIn('Selected provider: '+{'chatgpt':'ChatGPT','claude':'Claude','gemini':'Gemini','local':'your configured AI'}[provider],html);self.assertIn('Exact reviewed selection',html)
        cfg['ai_helper_enabled']=False;dlms._atomic_write_json(dlms.PORTAL_CONFIG,cfg)
        html=self.client.post('/certifications/matches',data=dict(credentials=cid,question='Copy only'),headers=self.headers).get_data(as_text=True)
        self.assertNotIn('data-cert-launch',html);self.assertIn('data-cert-copy',html)

    def test_focused_edit_scopes_preserve_period_policy_credit_and_retry_identity(self):
        rules=dict(requirement_known=False,annual_kind='minimum',annual_amount=20,
                   version='Recorded policy version',verification='user_checked',route='Custom route',
                   reporting_start='2025-06-01',reporting_end='2028-06-01',year_basis='anniversary',year_anchor='2025-06-01',
                   categories=[dict(name='Technical',minimum=5,cap=40)],conditions='User-recorded condition')
        cid=self.apply(self.request('certification',dict(name='CySA+',issuer='Custom fixture issuer',earned='2025-06-01',
            expiration='2028-06-01',start='2025-06-01',planning_deadline='2028-05-01',requirements='Keep policy notes',tracking=rules)),
            {'badge':self.png(),'certificate':self.pdf()})['id']
        period=self.cycle(cid)
        tid=self.apply(self.request('training',dict(name='Reviewed course',completed='2026-10-01',duration_minutes=562,hours=9.37)))['id']
        aid=self.apply(self.request('allocation',dict(hours=9,submitted=9,accepted=9),cycle_id=period['id'],training_id=tid))['id']
        with dlms.get_db() as c:allocation=cert.get(c.cursor(),'certification_allocations',aid)
        identity=self.request('certification',dict(name='CySA+ updated',expiration='2028-07-01',required=999,policy='https://evil.invalid'),
                              id=cid,cycle_id=period['id'],edit_current=True,edit_scope='identity')
        self.apply(identity);self.assertEqual(self.apply(identity)['id'],cid)
        after=self.cycle(cid)
        self.assertEqual(after['id'],period['id'])
        self.assertEqual(after['data'],{**period['data'],'expiration':'2028-07-01'})
        goal=self.request('cycle',dict(required=30,unit='credits',planning_deadline='2028-04-01',annual_goal=21,expiration='2040-01-01',policy='https://evil.invalid'),
                          id=period['id'],certification_id=cid,edit_scope='goal')
        self.apply(goal);self.assertEqual(self.apply(goal)['id'],period['id'])
        now=self.cycle(cid)['data'];expected={**after['data'],'required':30.0,'planning_deadline':'2028-04-01',
                                          'tracking':{**after['data']['tracking'],'requirement_known':True}}
        self.assertEqual(now,expected)
        with dlms.get_db() as c:
            self.assertEqual(cert.get(c.cursor(),'certification_allocations',aid),allocation)
            self.assertEqual(cert.get(c.cursor(),'certification_training',tid)['data']['duration_minutes'],562)
            cert.validate_restored(c)
        # A new operation makes the old form stale, but its lost acknowledgement
        # still replays exactly; changed content under the same ID is rejected.
        self.apply(self.request('training',dict(name='Other',completed='2026-10-01',hours=1)))
        self.assertEqual(self.apply(goal)['id'],period['id'])
        with self.assertRaises(cert.Conflict):self.apply({**goal,'data':{**goal['data'],'required':50}})
        with self.assertRaises(cert.Conflict):self.apply({**goal,'request_id':uuid.uuid4().hex})
        reopened=self.client.get('/certifications/'+cid+'/edit').get_data(as_text=True)
        self.assertIn('Replace badge',reopened);self.assertIn('Replace certificate',reopened)
        self.assertNotIn('name="field_required"',reopened)
        self.assertEqual(self.cycle(cid)['data'],now)

    def test_goal_form_validation_cancel_and_requirements_patch_preserve_dates(self):
        cid=self.create();period=self.cycle(cid)
        goal_url='/certifications/'+cid+'/cycles/'+period['id']+'/goal'
        self.assertEqual(self.client.get(goal_url).status_code,200)
        self.assertEqual(self.cycle(cid)['data'],period['data'])
        req=self.request('cycle',dict(required='bad',unit='credits',planning_deadline='2028-01-01'),id=period['id'],certification_id=cid,edit_scope='goal')
        form={k:v for k,v in req.items() if k not in ('action','id','data')}
        form.update(kind='cycle',record_id=period['id'],**{'field_'+k:v for k,v in req['data'].items()})
        failed=self.client.post('/certifications/save',data=form,headers=self.headers)
        self.assertEqual(failed.status_code,400)
        self.assertIn('value="2028-01-01"',failed.get_data(as_text=True))
        self.assertIn('value="goal"',failed.get_data(as_text=True))
        self.assertEqual(self.cycle(cid)['data'],period['data'])
        form['field_required']='40'
        self.assertEqual(self.client.post('/certifications/save',data=form,headers=self.headers).status_code,303)
        self.assertEqual(self.client.post('/certifications/save',data=form,headers=self.headers).status_code,303)
        saved=self.cycle(cid)['data']
        self.apply(self.request('cycle',dict(policy='https://example.org/rules',tracking=dict(requirement_known=True,annual_kind='pacing',annual_amount=10),expiration='2099-01-01'),id=period['id'],certification_id=cid,edit_scope='requirements'))
        after=self.cycle(cid)['data']
        self.assertEqual(after['expiration'],saved['expiration']);self.assertEqual(after['planning_deadline'],saved['planning_deadline'])
        self.assertEqual(after['required'],40)
        self.assertEqual(after['policy'],'https://example.org/rules')
        with dlms.get_db() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM certification_cycles WHERE certification_id=?',(cid,)).fetchone()[0],1)

    def test_focused_goal_backup_roundtrip_preserves_legacy_associated_time_and_documents(self):
        cid=self.apply(self.request('certification',dict(name='CySA+ fixture',issuer='Disposable issuer',expiration='2029-10-01')),
            {'badge':self.png(),'certificate':self.pdf()})['id'];period=self.cycle(cid)
        tid=self.apply(self.request('training',dict(name='Course',completed='2026-10-01',duration_minutes=562)),{'certificate':self.pdf()})['id']
        aid=self.apply(self.request('allocation',dict(hours=9,submitted=9,accepted=9),cycle_id=period['id'],training_id=tid))['id']
        self.apply(self.request('cycle',dict(required=40,unit='credits',planning_deadline='2029-09-01'),id=period['id'],certification_id=cid,edit_scope='goal'))
        with dlms.get_db() as c:
            before={t:[tuple(r) for r in c.execute('SELECT * FROM '+t+' ORDER BY id')] for t in (*cert.TABLES,'certification_attachments')}
        backup,manifest=dlms._create_dlms_backup('scoped-goal')
        stage=Path(dlms.APP_DATA_DIR)/'goal-stage';stage.mkdir()
        checked=dlms._validate_dlms_backup(backup);dlms._extract_validated_backup(backup,str(stage),checked)
        dlms._validate_staged_backup_semantics(str(stage),manifest);dlms._prepare_staged_restore_database(str(stage))
        with sqlite3.connect(stage/'results.db') as c:
            c.row_factory=sqlite3.Row;cert.validate_restored(c)
            self.assertEqual(before,{t:[tuple(r) for r in c.execute('SELECT * FROM '+t+' ORDER BY id')] for t in before})
            self.assertEqual(cert.get(c.cursor(),'certification_training',tid)['data']['duration_minutes'],562)
            self.assertEqual(cert.get(c.cursor(),'certification_allocations',aid)['data']['hours'],9)
            self.assertEqual(cert.detail(c.cursor(),cid)['cycles'][0]['totals']['accepted'],9)

    def test_goal_error_retains_mandatory_annual_context_and_submitted_values(self):
        cid=self.apply(self.request('certification',dict(name='Custom',issuer='Any',tracking=dict(annual_kind='minimum',annual_amount=20))))['id']
        period=self.cycle(cid)
        req=self.request('cycle',id=period['id'])
        form=dict(kind='cycle',edit_scope='goal',record_id=period['id'],certification_id=cid,request_id=req['request_id'],generation=req['generation'],revision=req['revision'],field_required='30',field_unit='credits',field_planning_deadline='2028-99-99',field_annual_goal='21')
        failed=self.client.post('/certifications/save',data=form,headers=self.headers)
        self.assertEqual(failed.status_code,400)
        html=failed.get_data(as_text=True)
        self.assertIn('recorded mandatory annual minimum',html)
        self.assertIn('class="cert-task-context"><strong>Custom</strong>',html)
        self.assertNotIn('name="field_annual_goal"',html)
        self.assertIn('minimum is 20 credits',html)
        self.assertRegex(html,r'name="field_required"[^>]*value="30"')
        self.assertEqual(self.cycle(cid)['data'],period['data'])

    def test_optional_annual_planning_goal_is_pacing_and_can_be_cleared(self):
        cid=self.create();period=self.cycle(cid)
        self.apply(self.request('cycle',dict(required=40,unit='credits',annual_goal=10),id=period['id'],certification_id=cid,edit_scope='goal'))
        data=self.cycle(cid)['data']
        self.assertEqual(data['tracking']['annual_kind'],'pacing')
        self.assertEqual(data['tracking']['annual_amount'],10)
        self.assertEqual(data['tracking']['year_basis'],'unknown')
        self.assertEqual(data['expiration'],period['data']['expiration'])
        self.apply(self.request('cycle',dict(annual_goal=''),id=period['id'],certification_id=cid,edit_scope='goal'))
        cleared=self.cycle(cid)['data']
        self.assertEqual(cleared['required'],40)
        self.assertTrue(cleared['tracking']['requirement_known'])
        self.assertEqual(cleared['tracking']['annual_kind'],'unknown')
        self.assertEqual(cleared['tracking']['annual_amount'],0)

    def test_ai_settings_single_save_retains_all_editors_on_validation_and_io_failure(self):
        from html import unescape
        import re
        original=Path(dlms.PORTAL_CONFIG).read_bytes()
        data=dict(ai_helper_enabled='on',ai_provider='local',ai_custom_url='javascript:bad',
                  ai_prompt_template='STUDY {{questions}}',law_ai_prompt_template='LAW',
                  study_pack_ai_prompt_template='PACK',medical_study_pack_ai_addendum='MEDICAL',
                  certification_ai_prompt_template='  CERT {{certification_context}}  ',
                  portfolio_ai_prompt_template='  PORT {{portfolio_context}}  ')
        def post():return self.client.post('/settings/ai/save',data=data,headers=self.headers)
        response=post();self.assertEqual(response.status_code,400)
        html=response.get_data(as_text=True)
        for key in ('ai_prompt_template','law_ai_prompt_template','study_pack_ai_prompt_template','medical_study_pack_ai_addendum','certification_ai_prompt_template','portfolio_ai_prompt_template'):
            self.assertEqual(unescape(re.search(r'<textarea[^>]*name="'+key+r'"[^>]*>(.*?)</textarea>',html,re.S).group(1)),data[key])
        self.assertEqual(Path(dlms.PORTAL_CONFIG).read_bytes(),original)
        data['ai_custom_url']='https://example.org/assistant'
        with mock.patch.object(dlms,'_write_settings_portal_config',side_effect=OSError('disposable failure')):
            failed=post();self.assertEqual(failed.status_code,503)
            self.assertIn(b'Your edits are retained',failed.data)
        self.assertEqual(Path(dlms.PORTAL_CONFIG).read_bytes(),original)
        data['portfolio_ai_prompt_template']='x'*20001
        self.assertEqual(post().status_code,400)
        self.assertEqual(Path(dlms.PORTAL_CONFIG).read_bytes(),original)
        data['portfolio_ai_prompt_template']='PORT {{portfolio_context}}'
        self.assertEqual(post().status_code,302)
        saved=dlms.load_portal_config()
        for key in data:
            if key!='ai_helper_enabled':self.assertEqual(saved[key],data[key].strip())
        for key,value in json.loads(original).items():
            if not key.startswith(('ai_','law_ai_','study_pack_ai_','medical_study_pack_ai_','certification_ai_','portfolio_ai_')):self.assertEqual(saved[key],value)
        backup,manifest=dlms._create_dlms_backup('ai-settings-form-roundtrip')
        stage=Path(dlms.APP_DATA_DIR)/'ai-settings-stage';stage.mkdir()
        report=dlms._validate_dlms_backup(backup)
        dlms._extract_validated_backup(backup,str(stage),report)
        dlms._validate_staged_backup_semantics(str(stage),manifest)
        restored=next(json.loads(p.read_text()) for p in stage.rglob('portal.json'))
        for key in data:
            self.assertEqual(restored[key],saved[key])
        page=self.client.get('/settings/ai').get_data(as_text=True)
        self.assertEqual(page.count('type="submit"'),1)
        self.assertLess(page.index('id="certificationPromptSettings"'),page.index('class="settings-form-actions ai-settings-actions"'))

    def test_optional_annual_pacing_does_not_invent_reporting_year(self):
        cid=self.create();cycle=self.cycle(cid)
        self.apply(self.request('cycle',dict(required=20,unit='hours',annual_goal=10),id=cycle['id'],certification_id=cid,edit_scope='goal'))
        tid=self.apply(self.request('training',dict(name='Planning example',completed='2026-10-01',duration_minutes=562,hours=9.37)))['id']
        self.apply(self.request('allocation',dict(hours=0,duration_minutes=562,proposed=9.37,submitted=0,accepted=0),cycle_id=cycle['id'],training_id=tid))
        with dlms.get_db() as c:
            item=cert.detail(c.cursor(),cid)['cycles'][0]
            self.assertEqual(item['data']['tracking']['annual_kind'],'pacing')
            self.assertEqual(item['data']['tracking']['year_basis'],'unknown')
            self.assertEqual(item['planning']['annual'],[])
            self.assertEqual(item['planning']['accepted'],9.37)
            self.assertEqual(item['totals']['accepted'],0)

    def test_independent_deadlines_edit_clear_labels_and_credit_invariants(self):
        cid=self.apply(self.request('certification',dict(name='Date fixture',issuer='Any issuer',earned='2025-01-01',
            start='2025-02-01',expiration='2028-11-01',planning_deadline='2028-03-12',renewal_deadline='2028-10-01',required=40)))['id']
        cycle=self.cycle(cid);pid=cycle['id']
        tid=self.apply(self.request('training',dict(name='Exact time',completed='2026-10-01',duration_minutes=562)))['id']
        aid=self.apply(self.request('allocation',dict(hours=9,proposed=10,submitted=9,accepted=9),cycle_id=pid,training_id=tid))['id']
        before=self.cycle(cid)
        def save(scope,values):
            req=self.request('cycle',values,id=pid,certification_id=cid,edit_scope=scope)
            self.apply(req);self.assertEqual(self.apply(req)['id'],pid)
            return self.cycle(cid)
        summary=self.client.get('/certifications/'+cid).get_data(as_text=True)
        self.assertIn('Planning deadline: <strong>2028-03-12</strong>',summary)
        self.assertIn('· Expires 2028-11-01</summary>',summary)
        self.assertIn('<dt>Renewal deadline (user recorded)</dt><dd>2028-10-01</dd>',summary)
        with dlms.get_db() as c:
            prompts=[cert.curated_prompt(c.cursor(),cid,pid,[],'Dates?',include_cycle=True),cert.portfolio_prompt(c.cursor(),[cid],[],'Dates?')]
        for prompt in prompts:
            for value in ('Planning deadline','Renewal deadline (user recorded; not issuer verified)','Expires','2028-03-12','2028-10-01','2028-11-01'):self.assertIn(value,prompt)
        # Scope filters reject any attempted cross-editor overwrite by ignoring it.
        now=save('goal',dict(planning_deadline='',renewal_deadline='2040-01-01',expiration='2041-01-01'))
        self.assertEqual(now['data'],{**before['data'],'planning_deadline':''})
        self.assertIn('Renewal deadline (user recorded): <strong>2028-10-01</strong>',self.client.get('/certifications/'+cid).get_data(as_text=True))
        now=save('requirements',dict(renewal_deadline='',planning_deadline='2040-01-01'))
        self.assertEqual(now['data'],{**before['data'],'planning_deadline':'','renewal_deadline':''})
        self.assertIn('Expires: <strong>2028-11-01</strong>',self.client.get('/certifications/'+cid).get_data(as_text=True))
        # Equal dates remain independent; a personal target may precede effective coverage.
        save('goal',dict(planning_deadline='2025-01-15'))
        now=save('requirements',dict(renewal_deadline='2028-11-01'))
        now=save('goal',dict(planning_deadline='2028-11-01'))
        self.assertEqual(len({now['data'][k] for k in ('expiration','planning_deadline','renewal_deadline')}),1)
        certdata=now['data'];req=self.request('certification',dict(expiration='',non_expiring='yes'),id=cid,cycle_id=pid,edit_current=True,edit_scope='identity');self.apply(req)
        self.assertEqual(self.cycle(cid)['data'],{**certdata,'expiration':''})
        with dlms.get_db() as c:
            self.assertEqual(cert.get(c.cursor(),'certification_training',tid)['data']['duration_minutes'],562)
        for key in ('planning','progress','totals','allocations'):self.assertEqual(self.cycle(cid)[key],before[key])
        save('goal',dict(planning_deadline=''));save('requirements',dict(renewal_deadline=''))
        self.assertIn('Planning deadline: <strong>not recorded</strong>',self.client.get('/certifications/'+cid).get_data(as_text=True))
        for invalid in ('2028-02-30','2028-03-12T00:00:00Z',None,22):
            with self.subTest(invalid=invalid),self.assertRaises(ValueError):save('goal',dict(planning_deadline=invalid))
        for day in ('2028-03-12','2028-11-05','2028-02-29'):
            self.assertEqual(save('goal',dict(planning_deadline=day))['data']['planning_deadline'],day)

    def legacy_date_copy(self, value='2028-09-01'):
        cid=self.apply(self.request('certification',dict(name='Legacy date',issuer='Custom',earned='2025-01-01',expiration='2029-01-01')))['id']
        pid=self.cycle(cid)['id'];path=Path(dlms.APP_DATA_DIR)/('legacy-'+uuid.uuid4().hex+'.db')
        with dlms.get_db() as source,sqlite3.connect(path) as target:source.backup(target)
        with sqlite3.connect(path) as c:
            for name in certification_schema.DATE_TRIGGERS:c.execute('DROP TRIGGER '+name)
            data=json.loads(c.execute('SELECT data_json FROM certification_cycles WHERE id=?',(pid,)).fetchone()[0])
            for key in ('planning_deadline','renewal_deadline'):data.pop(key)
            data['renewal']=value
            c.execute('UPDATE certification_cycles SET data_json=? WHERE id=?',(json.dumps(data),pid));c.execute('UPDATE schema_meta SET version=9')
        return path,cid,pid

    def test_schema_ten_deadline_migration_failure_interruption_old_writer_and_rollback(self):
        import subprocess,sys,os,shutil
        path,cid,pid=self.legacy_date_copy()
        backup=path.with_suffix('.pre-upgrade.db');shutil.copyfile(path,backup)
        with sqlite3.connect(path) as c:before=list(c.iterdump())
        def fail(c):certification_schema.migrate_deadlines(c);raise RuntimeError('interrupted date migration')
        with mock.patch.dict(dlms.DLMS_SCHEMA_MIGRATIONS,{10:fail}),self.assertRaisesRegex(RuntimeError,'interrupted'):
            dlms.bootstrap_database(str(path))
        with sqlite3.connect(path) as c:self.assertEqual(list(c.iterdump()),before)
        script="""import os,sys
from dlms.persistence import database as d,certification_schema as s
def crash(c):s.migrate_deadlines(c);os._exit(73)
d.bootstrap_database(sys.argv[1],schema_version=10,legacy_schema_version=1,legacy_core_tables=d.DLMS_LEGACY_CORE_TABLES,migrations={10:crash},create_current_schema=None,database_table_names=d._database_table_names,read_schema_version=d._read_database_schema_version,validate_current_schema=d._validate_current_database_schema)
"""
        run=subprocess.run([sys.executable,'-c',script,str(path)],cwd=Path(dlms.__file__).parent,env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'},capture_output=True,text=True,timeout=15)
        self.assertEqual(run.returncode,73,run.stderr)
        with sqlite3.connect(path) as c:self.assertEqual(list(c.iterdump()),before)
        self.assertEqual(dlms.bootstrap_database(str(path))['version'],10)
        with sqlite3.connect(path) as c:
            c.row_factory=sqlite3.Row;item=cert.get(c.cursor(),'certification_cycles',pid)['data'];state=cert.state(c.cursor());snapshot=list(c.iterdump())
            self.assertEqual(item['legacy_deadline'],dict(value='2028-09-01',source='cycle.data.renewal',source_schema=9,classification='unresolved'))
            self.assertEqual((item['planning_deadline'],item['renewal_deadline']),('',''))
            certification_schema.migrate_deadlines(c);self.assertEqual(list(c.iterdump()),snapshot)
            with self.assertRaisesRegex(sqlite3.IntegrityError,'Outdated'):c.execute('UPDATE certification_cycles SET data_json=? WHERE id=?',(json.dumps({**item,'renewal':'2030-01-01'}),pid))
            c.rollback()
            with self.assertRaisesRegex(cert.Conflict,'old shared'):cert.apply(c,dict(action='cycle',id=pid,certification_id=cid,data={'renewal':'2030-01-01'},request_id=uuid.uuid4().hex,**state))
        # Exercise the compatibility limit without requiring repository history in CI.
        # The actual schema-9 source bootstrap was also checked in retained review evidence.
        from dlms.persistence import database as db
        def old_bootstrap(target):
            return db.bootstrap_database(str(target),schema_version=9,legacy_schema_version=1,
                legacy_core_tables=db.DLMS_LEGACY_CORE_TABLES,migrations={},create_current_schema=None,
                database_table_names=db._database_table_names,read_schema_version=db._read_database_schema_version,
                validate_current_schema=certification_schema.validate_state)
        raw=path.read_bytes()
        with self.assertRaisesRegex(RuntimeError,'newer'):old_bootstrap(path)
        self.assertEqual(path.read_bytes(),raw)
        restored=path.with_suffix('.rollback.db');shutil.copyfile(backup,restored)
        self.assertEqual(old_bootstrap(restored)['version'],9)
        with sqlite3.connect(restored) as c:self.assertEqual(list(c.iterdump()),before)

    def test_legacy_date_classification_is_explicit_retry_safe_and_preserved(self):
        path,cid,pid=self.legacy_date_copy();dlms.bootstrap_database(str(path))
        with sqlite3.connect(path) as c:
            c.row_factory=sqlite3.Row
            def request(data,scope='requirements'):
                return dict(action='cycle',id=pid,certification_id=cid,edit_scope=scope,data=data,request_id=uuid.uuid4().hex,**cert.state(c.cursor()))
            initial=cert.get(c.cursor(),'certification_cycles',pid)['data']
            cert.apply(c,request(dict(required=20),'goal'))
            self.assertEqual(cert.get(c.cursor(),'certification_cycles',pid)['data']['legacy_deadline'],initial['legacy_deadline'])
            cert.apply(c,request(dict(planning_deadline='2028-06-01'),'goal'))
            with self.assertRaisesRegex(ValueError,'different date'):cert.apply(c,request(dict(classify_legacy_deadline='planning_deadline')))
            req=request(dict(classify_legacy_deadline='renewal_deadline'));out=cert.apply(c,req);self.assertEqual(cert.apply(c,req),out)
            result=cert.get(c.cursor(),'certification_cycles',pid)['data']
            self.assertEqual(result['planning_deadline'],'2028-06-01');self.assertEqual(result['renewal_deadline'],'2028-09-01')
            self.assertEqual(result['legacy_deadline'],{**initial['legacy_deadline'],'classification':'renewal_deadline'})
            cert.apply(c,request(dict(planning_deadline=''),'goal'))
            self.assertEqual(cert.get(c.cursor(),'certification_cycles',pid)['data']['legacy_deadline'],result['legacy_deadline'])
            stale=request(dict(renewal_deadline='2028-11-01'));other=request(dict(renewal_deadline='2028-12-01'))
            cert.apply(c,other)
            with self.assertRaises(cert.Conflict):cert.apply(c,stale)
            cert.validate_restored(c)

    def test_deadline_legacy_backup_validation_and_roundtrip(self):
        path,cid,pid=self.legacy_date_copy()
        with sqlite3.connect(path) as c:
            before=list(c.iterdump());cert.validate_restored(c);self.assertEqual(list(c.iterdump()),before)
        # Build a real legacy backup archive; validate it read-only, then migrate only staging.
        with sqlite3.connect(path) as source,dlms.get_db() as target:source.backup(target)
        old_backup,old_manifest=dlms._create_dlms_backup('schema-nine-deadlines')
        old_stage=Path(dlms.APP_DATA_DIR)/'old-deadlines-stage'
        checked=dlms._validate_dlms_backup(old_backup);dlms._extract_validated_backup(old_backup,str(old_stage),checked)
        dlms._validate_staged_backup_semantics(str(old_stage),old_manifest)
        dlms._prepare_staged_restore_database(str(old_stage))
        with sqlite3.connect(old_stage/'results.db') as c:
            c.row_factory=sqlite3.Row
            restored=cert.get(c.cursor(),'certification_cycles',pid)['data']
            self.assertEqual(restored['legacy_deadline']['value'],'2028-09-01')
            self.assertEqual((restored['planning_deadline'],restored['renewal_deadline']),('',''))
        dlms.bootstrap_database(str(path))
        with sqlite3.connect(path) as source,dlms.get_db() as target:source.backup(target)
        period=self.cycle(cid)
        self.apply(self.request('cycle',dict(planning_deadline='2028-06-01',renewal_deadline='2028-10-01'),id=pid,certification_id=cid))
        before=self.cycle(cid)['data']
        backup,manifest=dlms._create_dlms_backup('distinct-deadlines');stage=Path(dlms.APP_DATA_DIR)/'deadlines-stage'
        checked=dlms._validate_dlms_backup(backup);dlms._extract_validated_backup(backup,str(stage),checked)
        dlms._validate_staged_backup_semantics(str(stage),manifest);dlms._prepare_staged_restore_database(str(stage))
        with sqlite3.connect(stage/'results.db') as c:
            c.row_factory=sqlite3.Row;cert.validate_restored(c)
            self.assertEqual(cert.get(c.cursor(),'certification_cycles',pid)['data'],before)
        # A forged schema-9 export carrying new fields is rejected, not reinterpreted.
        with sqlite3.connect(stage/'results.db') as c:
            c.execute('UPDATE schema_meta SET version=9')
            with self.assertRaisesRegex(ValueError,'conflicting deadline'):cert.validate_restored(c)

    def test_date_guards_malformed_legacy_and_historical_periods(self):
        path,cid,pid=self.legacy_date_copy('not-a-date')
        with sqlite3.connect(path) as c:before=list(c.iterdump())
        with self.assertRaises(ValueError):dlms.bootstrap_database(str(path))
        with sqlite3.connect(path) as c:self.assertEqual(list(c.iterdump()),before)
        cid=self.apply(self.request('certification',dict(name='History',issuer='Custom',earned='2025-01-01',expiration='2028-01-01',planning_deadline='2027-08-01',renewal_deadline='2027-12-01')))['id']
        old=self.cycle(cid)
        newer=self.apply(self.request('cycle',dict(expiration='2031-01-01',renewal_deadline='2030-12-01'),certification_id=cid))['id']
        self.assertEqual(self.cycle(cid)['data']['planning_deadline'],'')
        self.apply(self.request('cycle',dict(planning_deadline='2027-09-01'),id=old['id'],certification_id=cid,edit_scope='goal'))
        with dlms.get_db() as c:
            historical=cert.get(c.cursor(),'certification_cycles',old['id'])
            self.assertEqual(historical['data'],{**old['data'],'planning_deadline':'2027-09-01'})
            self.assertEqual(cert.get(c.cursor(),'certification_cycles',newer)['data']['renewal_deadline'],'2030-12-01')
            before=list(c.iterdump())
            with self.assertRaisesRegex(sqlite3.IntegrityError,'Outdated'):
                c.execute('INSERT INTO certification_cycles VALUES(?,?,?,?)',(uuid.uuid4().hex,cid,json.dumps({'renewal':'2034-01-01'}),3))
            c.rollback();self.assertEqual(list(c.iterdump()),before)
            # A forged guard with the right name is still rejected on restore.
            c.execute('DROP TRIGGER certification_dates_update')
            c.execute('CREATE TRIGGER certification_dates_update BEFORE UPDATE ON certification_cycles BEGIN SELECT 1; END')
            with self.assertRaisesRegex(ValueError,'protections are incompatible'):cert.validate_restored(c)

    def test_partial_period_date_correction_preserves_omitted_evidence_and_credit(self):
        cid=self.apply(self.request('certification',dict(name='Partial date correction',issuer='Custom',earned='2025-01-01',start='2025-01-01',expiration='2029-11-01',planning_deadline='2029-08-01',renewal_deadline='2029-10-01',required=40,requirements='Keep recorded requirements',policy='https://example.org/policy')),
                       {'badge':self.png(),'certificate':self.pdf()})['id']
        period=self.cycle(cid);pid=period['id']
        tid=self.apply(self.request('training',dict(name='Recorded course',completed='2026-10-01',duration_minutes=562)))['id']
        self.apply(self.request('allocation',dict(hours=9,proposed=10,submitted=9,accepted=9),cycle_id=pid,training_id=tid))
        before=self.cycle(cid)
        with dlms.get_db() as c:
            preserved={t:[tuple(r) for r in c.execute('SELECT * FROM '+t+' ORDER BY id')] for t in ('certifications','certification_training','certification_allocations','certification_attachments')}
        req=self.request('cycle',dict(renewal_deadline='2029-10-15'),id=pid,certification_id=cid)
        result=self.apply(req);self.assertEqual(self.apply(req),result)
        self.assertEqual(self.cycle(cid)['data'],{**before['data'],'renewal_deadline':'2029-10-15'})
        expected=self.cycle(cid)['data']
        for key in ('planning_deadline','renewal_deadline','expiration'):
            self.apply(self.request('cycle',{key:''},id=pid,certification_id=cid));expected={**expected,key:''}
            self.assertEqual(self.cycle(cid)['data'],expected)
        # An interrupted transaction cannot partially save a date or orphan its evidence.
        req=self.request('cycle',dict(expiration='2029-12-01'),id=pid,certification_id=cid)
        with dlms.get_db() as c:c.execute("CREATE TRIGGER fail_review_receipt BEFORE INSERT ON certification_actions BEGIN SELECT RAISE(ABORT,'review interruption'); END")
        with self.assertRaisesRegex(sqlite3.IntegrityError,'review interruption'):self.apply(req)
        self.assertEqual(self.cycle(cid)['data'],expected)
        with dlms.get_db() as c:c.execute('DROP TRIGGER fail_review_receipt')
        self.apply(req);self.assertEqual(self.apply(req)['id'],pid)
        for key in ('planning','progress','totals','allocations'):self.assertEqual(self.cycle(cid)[key],before[key])
        with dlms.get_db() as c:
            self.assertEqual({t:[tuple(r) for r in c.execute('SELECT * FROM '+t+' ORDER BY id')] for t in preserved},preserved)
        stale=self.request('cycle',dict(renewal_deadline='2030-01-01'),id=pid,certification_id=cid)
        current=self.request('cycle',dict(planning_deadline='2029-07-01'),id=pid,certification_id=cid)
        self.apply(current)
        with self.assertRaises(cert.Conflict):self.apply(stale)
        self.assertEqual(self.cycle(cid)['data']['renewal_deadline'],'')

    def test_legacy_classification_form_errors_preserve_provenance_selection_and_guards(self):
        path,cid,pid=self.legacy_date_copy();dlms.bootstrap_database(str(path))
        with sqlite3.connect(path) as source,dlms.get_db() as target:source.backup(target)
        before=self.cycle(cid)['data']
        for scope in ('requirements',''):
            for choice in ('planning_deadline','renewal_deadline'):
                with self.subTest(scope=scope,choice=choice):
                    req=self.request('cycle')
                    form=dict(kind='cycle',record_id=pid,certification_id=cid,edit_scope=scope,request_id=req['request_id'],generation=req['generation'],revision=req['revision'],field_required='invalid',field_unit='credits',field_classify_legacy_deadline=choice)
                    response=self.client.post('/certifications/save',data=form,headers=self.headers)
                    self.assertEqual(response.status_code,400);html=response.get_data(as_text=True)
                    self.assertIn('id="legacyDeadline"',html);self.assertIn('2028-09-01',html)
                    self.assertIn('value="'+choice+'" selected',html)
                    for key in ('request_id','generation','revision'):self.assertIn('name="'+key+'" value="'+str(req[key])+'"',html)
                    self.assertEqual(self.cycle(cid)['data'],before)
