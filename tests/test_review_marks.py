"""Disposable marks, source identity, independent actions and additive storage."""
import json
import sqlite3
import uuid
import unittest
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from unittest import mock
from tests import test_study_sessions as foundation
dlms = foundation.dlms
from dlms.services import review_marks as marks, study_sessions as study, restore, exam_plans as plans
from dlms.persistence import review_mark_schema
from tests.csrf_test_utils import csrf_headers


class ReviewMarkTests(unittest.TestCase):
    setUp = foundation.StudySessionTests.setUp
    choice = staticmethod(foundation.StudySessionTests.choice)
    matching = staticmethod(foundation.StudySessionTests.matching)
    publish = foundation.StudySessionTests.publish
    fingerprint = foundation.StudySessionTests.fingerprint
    payload = foundation.StudySessionTests.payload
    save = foundation.StudySessionTests.save
    finish = foundation.StudySessionTests.finish
    facts = foundation.StudySessionTests.facts
    evidence = foundation.StudySessionTests.evidence
    def context(self, quiz_id=None):
        quiz_id=quiz_id or self.quiz_id
        response=self.client.post('/api/review-marks/context',json=dict(quiz_id=quiz_id,fingerprint=self.fingerprint(quiz_id)),headers=self.headers)
        self.assertEqual(response.status_code,200,response.json)
        return response.json

    def mark_data(self, quiz_id=None, **changes):
        quiz_id=quiz_id or self.quiz_id; context=self.context(quiz_id)
        return dict(action='mark',request_id=uuid.uuid4().hex,quiz_id=quiz_id,fingerprint=self.fingerprint(quiz_id),
                    generation=context['generation'],revision=context['revision'],assessment_revision=context['assessment_revision'],indexes=[0],marked=True,**changes)

    def mark(self,quiz_id=None):
        response=self.client.post('/api/review-marks/save',json=self.mark_data(quiz_id),headers=self.headers)
        self.assertEqual(response.status_code,200,response.json)
        return response.json

    def rows(self, quiz=None):
        with dlms.get_db() as conn:return marks.catalog(conn.cursor(),dlms._exam_plan_options(conn.cursor()),quiz)

    def action_data(self,ids=None):
        c=self.context()
        return dict(request_id=uuid.uuid4().hex,generation=c['generation'],revision=c['revision'],ids=ids or [m['id'] for m in self.rows()])

    def test_mark_retry_conflict_no_learning_or_completion(self):
        d=self.mark_data(); first=self.client.post('/api/review-marks/save',json=d,headers=self.headers)
        self.assertEqual(first.json,self.client.post('/api/review-marks/save',json=d,headers=self.headers).json)
        self.assertEqual(self.client.post('/api/review-marks/save',json={**d,'marked':False},headers=self.headers).status_code,409)
        self.assertEqual(len(self.rows()),1); self.assertEqual(self.evidence(),[])
        self.assertIsNone(self.facts())  # Opening/marking alone is not study progress.
        self.client.get('/marked-questions');self.assertEqual(len(self.rows()),1)
        # Explicit unmark remains safe after a lost acknowledgement.
        remove={**self.action_data(),'action':'unmark'}
        self.assertEqual(self.client.post('/api/review-marks/save',json=remove,headers=self.headers).status_code,200)
        self.assertEqual(self.client.post('/api/review-marks/save',json=d,headers=self.headers).json,first.json)
        self.assertEqual(self.rows(),[])

    def test_practice_and_anki_independent_and_lineage(self):
        self.mark(); d=self.action_data()
        result=self.client.post('/api/review-marks/generate',json=d,headers=self.headers)
        self.assertEqual(result.status_code,200,result.json)
        again=self.client.post('/api/review-marks/generate',json=d,headers=self.headers)
        self.assertEqual(result.json['url'],again.json['url']);self.assertTrue(again.json['replayed'])
        with dlms.get_db() as conn:
            source=conn.execute('SELECT question_uid FROM questions WHERE quiz_id=?',(self.quiz_id,)).fetchone()[0]
            q=conn.execute('SELECT q.*,z.generation_kind FROM questions q JOIN quizzes z ON z.id=q.quiz_id WHERE z.generation_kind=?',('marked_practice',)).fetchone()
            self.assertEqual(q['source_question_uid'],source); generated=q['quiz_id']
            self.assertEqual(study.question_revision(conn.cursor(),q['id']),self.rows()[0]['question_revision'])
        self.mark(generated);self.assertEqual(len(self.rows()),1)
        self.assertEqual(len(self.rows(generated)),1)
        response=self.client.post('/api/review-marks/anki',json=self.action_data(),headers=self.headers)
        self.assertEqual(response.status_code,200);self.assertTrue(response.data.startswith(b'PK'))
        response.close();self.assertEqual(len(self.rows()),1);self.assertEqual(self.evidence(),[])
        claim={**self.claim_data,'quizId':generated,'fingerprint':self.fingerprint(generated),'sessionId':'marked-session'}
        saved=self.client.post('/api/study/session',json=claim,headers=self.headers)
        self.assertEqual(saved.json['session']['purpose'],'focused')

    def test_excluded_unsupported_changed_deleted_and_renamed(self):
        self.mark(); registry=dlms.load_registry();registry[0]['title']='Renamed';registry[0]['folder']='Later';dlms.save_registry(registry)
        with dlms.get_db() as conn:conn.execute("UPDATE quizzes SET title='Renamed' WHERE id=?",(self.quiz_id,))
        self.assertEqual(self.rows()[0]['title'],'Renamed');self.assertEqual(self.rows()[0]['folder'],'Later')
        with mock.patch.object(dlms,'get_excluded_learning_folders',return_value=['Later']):
            self.assertIn('Learning Scope',self.rows()[0]['practice_reason']);self.assertEqual(self.rows()[0]['anki_reason'],'')
            self.assertEqual(self.client.post('/api/review-marks/generate',json=self.action_data(),headers=self.headers).status_code,409)
        matching,_=self.publish(title='Matching',questions=[self.matching()],kind=None);self.mark(matching)
        self.assertIn('text choice',self.rows(matching)[0]['anki_reason']);self.assertEqual(self.rows(matching)[0]['practice_reason'],'')
        with dlms.get_db() as conn:conn.execute("UPDATE questions SET question_text='Edited' WHERE quiz_id=?",(self.quiz_id,))
        self.assertIn('changed',self.rows(self.quiz_id)[0]['practice_reason'])
        with dlms.get_db() as conn:conn.execute('DELETE FROM quizzes WHERE id=?',(self.quiz_id,))
        self.assertIn('deleted',self.rows(self.quiz_id)[0]['practice_reason'])

    def test_concurrent_and_failed_adoption_preserve_legacy(self):
        d=self.mark_data();d['fingerprint']='sha256:'+'0'*64
        self.assertEqual(self.client.post('/api/review-marks/save',json=d,headers=self.headers).status_code,409)
        self.assertEqual(self.rows(),[])
        d=self.mark_data()
        def save():
            client=dlms.app.test_client();return client.post('/api/review-marks/save',json=d,headers=csrf_headers(client)).status_code
        with ThreadPoolExecutor(2) as pool:self.assertEqual(list(pool.map(lambda _:save(),range(2))),[200,200])
        self.assertEqual(len(self.rows()),1)
        stale={**d,'request_id':uuid.uuid4().hex,'marked':False}
        self.assertEqual(self.client.post('/api/review-marks/save',json=stale,headers=self.headers).status_code,409)

    def test_reset_backup_restore_generation_and_migration(self):
        self.save(self.payload(1,correct=False))
        self.mark();d=self.action_data();oldrows=self.rows()
        restore.reset_learning_intelligence_core(dlms.DB_PATH)
        self.assertEqual(self.rows(),oldrows)
        copy=Path(dlms.DB_PATH).with_name('backup.db')
        with dlms.get_db() as conn,sqlite3.connect(copy) as backup:conn.backup(backup)
        dlms.bootstrap_database(str(copy))
        with sqlite3.connect(copy) as conn:
            conn.row_factory=sqlite3.Row;marks.validate_restored_marks(conn)
            self.assertEqual(conn.execute('SELECT count(*) FROM review_marks WHERE marked=1').fetchone()[0],1)
        with dlms.get_db() as conn:review_mark_schema.invalidate(conn)
        self.assertEqual(self.client.post('/api/review-marks/generate',json=d,headers=self.headers).status_code,409)
        with dlms.get_db() as conn:
            conn.execute('DROP TABLE review_mark_actions');conn.execute('DROP TABLE review_marks');conn.execute('DROP TABLE review_mark_state');conn.execute('UPDATE schema_meta SET version=5')
        dlms.bootstrap_database(dlms.DB_PATH)
        self.assertEqual(self.rows(),[])
        self.assertIsNotNone(self.facts())

    def test_changed_answers_cannot_adopt_old_page(self):
        d=self.mark_data()
        with dlms.get_db() as conn:
            conn.execute("UPDATE choices SET is_correct=0 WHERE label='A'")
            conn.execute("UPDATE choices SET is_correct=1 WHERE label='C'")
        self.assertEqual(self.client.post('/api/review-marks/save',json=d,headers=self.headers).status_code,409)
        self.assertEqual(self.rows(),[])
        self.assertEqual(self.client.post('/api/review-marks/context',json=dict(quiz_id=self.quiz_id,fingerprint=self.fingerprint(self.quiz_id)),headers=self.headers).status_code,409)

    def test_write_failure_and_publication_rollback_retry(self):
        d=self.mark_data()
        with dlms.get_db() as conn:conn.execute("CREATE TRIGGER fail_mark BEFORE INSERT ON review_marks BEGIN SELECT RAISE(ABORT,'simulated write failure'); END")
        self.assertEqual(self.client.post('/api/review-marks/save',json=d,headers=self.headers).status_code,503)
        self.assertEqual(self.rows(),[])
        with dlms.get_db() as conn:conn.execute('DROP TRIGGER fail_mark')
        self.assertEqual(self.client.post('/api/review-marks/save',json=d,headers=self.headers).status_code,200)
        request=self.action_data()
        with mock.patch.object(dlms,'build_quiz_html',side_effect=OSError('simulated publication failure')):
            response=self.client.post('/api/review-marks/generate',json=request,headers=self.headers)
            self.assertEqual(response.status_code,503,response.json)
        result=self.client.post('/api/review-marks/generate',json=request,headers=self.headers)
        self.assertEqual(result.status_code,200,result.json)
        self.assertEqual(len(self.rows()),1)

    def test_simultaneous_generation_lost_ack_changed_request_and_pending(self):
        self.mark();d=self.action_data()
        def generate():
            client=dlms.app.test_client();response=client.post('/api/review-marks/generate',json=d,headers=csrf_headers(client));return response.status_code,response.json
        with ThreadPoolExecutor(2) as pool:results=list(pool.map(lambda _:generate(),range(2)))
        self.assertEqual([r[0] for r in results],[200,200]);self.assertEqual(results[0][1]['url'],results[1][1]['url'])
        self.assertEqual(self.client.post('/api/review-marks/generate',json={**d,'ids':[]},headers=self.headers).status_code,409)
        d=self.action_data()
        with mock.patch.object(dlms,'_publish_quiz',side_effect=OSError('uncertain interruption')):
            self.assertEqual(self.client.post('/api/review-marks/generate',json=d,headers=self.headers).status_code,503)
        response=self.client.post('/api/review-marks/generate',json=d,headers=self.headers)
        self.assertEqual(response.status_code,409);self.assertTrue(response.json['uncertain'])
        with dlms.get_db() as conn:self.assertEqual(conn.execute("SELECT count(*) FROM quizzes WHERE generation_kind='marked_practice'").fetchone()[0],1)

    def test_anki_package_contains_exact_supported_selection_and_no_unmark(self):
        import io,zipfile
        second,_=self.publish(title='Other source',questions=[{**self.choice(multi=True),'question':'Choose both expected answers.'}],kind=None)
        self.mark();self.mark(second)
        rows=self.rows();chosen=next(m for m in rows if m['quiz_id']==second)
        response=self.client.post('/api/review-marks/anki',json=self.action_data([chosen['id']]),headers=self.headers)
        self.assertEqual(response.status_code,200)
        with zipfile.ZipFile(io.BytesIO(response.data)) as package:
            path=Path(dlms.DB_PATH).with_name('exported-anki.db');path.write_bytes(package.read('collection.anki2'))
        with sqlite3.connect(path) as conn:
            notes=conn.execute('SELECT flds FROM notes').fetchall()
            self.assertEqual(len(notes),1)
            self.assertIn('Choose both expected answers.',notes[0][0]);self.assertIn('A. Alpha<br>B. Beta',notes[0][0])
        response.close();self.assertEqual(len(self.rows()),2)

    def test_large_selection_pages_and_exact_generation_no_truncation(self):
        questions=[{**self.choice(),'number':i+1,'question':f'Unique source item {i}'} for i in range(57)]
        source,_=self.publish(title='Many marked questions',questions=questions,kind=None)
        d=self.mark_data(source);d['indexes']=list(range(57))
        self.assertEqual(self.client.post('/api/review-marks/save',json=d,headers=self.headers).status_code,200)
        import re
        found=[]
        for page,expected in ((1,25),(2,25),(3,7)):
            text=self.client.get(f'/marked-questions?quiz={source}&page={page}').text
            ids=re.findall(r'data-mark-id="([a-f0-9]+)"',text)
            self.assertEqual(len(ids),expected);found.extend(ids)
        self.assertEqual(len(set(found)),57)
        generated=self.client.post('/api/review-marks/generate',json=self.action_data(found),headers=self.headers)
        self.assertEqual(generated.status_code,200,generated.json)
        with dlms.get_db() as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM questions q JOIN quizzes z ON z.id=q.quiz_id WHERE z.generation_kind='marked_practice'").fetchone()[0],57)

    def test_study_deletion_retains_marks_migration_failure_is_atomic(self):
        self.mark();restore.delete_study_history_core(dlms.DB_PATH);self.assertEqual(len(self.rows()),1)
        with dlms.get_db() as conn:
            conn.execute('DROP TABLE review_mark_actions');conn.execute('DROP TABLE review_marks');conn.execute('DROP TABLE review_mark_state');conn.execute('UPDATE schema_meta SET version=5')
        original=review_mark_schema.STATEMENTS
        with mock.patch.object(review_mark_schema,'STATEMENTS',(original[0],'invalid migration statement')):
            with self.assertRaises(sqlite3.Error):dlms.bootstrap_database(dlms.DB_PATH)
        with dlms.get_db() as conn:
            self.assertEqual(conn.execute('SELECT version FROM schema_meta').fetchone()[0],5)
            self.assertIsNone(conn.execute("SELECT name FROM sqlite_master WHERE name='review_mark_state'").fetchone())
            self.assertIsNotNone(conn.execute('SELECT id FROM quizzes WHERE id=?',(self.quiz_id,)).fetchone())
        dlms.bootstrap_database(dlms.DB_PATH);self.assertEqual(self.rows(),[])

    def test_duplicate_content_missing_files_and_unsupported_media(self):
        self.mark()
        duplicate,_=self.publish(title='Separate identical source',questions=[self.choice()],kind=None);self.mark(duplicate)
        request=self.action_data()
        response=self.client.post('/api/review-marks/generate',json=request,headers=self.headers)
        self.assertEqual(response.status_code,409);self.assertIn('identical questions',response.json['error'])
        with dlms.get_db() as conn:
            qid=conn.execute('SELECT id FROM questions WHERE quiz_id=?',(duplicate,)).fetchone()[0]
            conn.execute("UPDATE questions SET media_json=? WHERE id=?",(json.dumps({'image_url':'/quiz-assets/missing.png'}),qid))
            revision=study.question_revision(conn.cursor(),qid)
            conn.execute('UPDATE review_marks SET question_revision=? WHERE quiz_id=?',(revision,duplicate))
        m=self.rows(duplicate)[0]
        self.assertIn('source changed',m['practice_reason']);self.assertIn('source changed',m['anki_reason'])
        image,_=self.publish(title='Image question',questions=[{**self.choice(),'image_url':'/static/favicon.ico'}],kind=None)
        self.mark(image);m=self.rows(image)[0]
        self.assertIn('image or hotspot',m['practice_reason']);self.assertIn('text choice',m['anki_reason'])
        Path(dlms.QUIZ_FOLDER,self.html).unlink()
        self.assertIn('files are unavailable',self.rows(self.quiz_id)[0]['practice_reason'])

    def test_new_process_reads_marks_and_restored_validation_rejects_corruption(self):
        import subprocess,sys,os
        self.mark()
        check=subprocess.run([sys.executable,'-c',"import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); print(c.execute('SELECT count(*) FROM review_marks WHERE marked=1').fetchone()[0])",dlms.DB_PATH],capture_output=True,text=True,check=True)
        self.assertEqual(check.stdout.strip(),'1')
        with dlms.get_db() as conn:
            conn.execute("UPDATE review_marks SET question_revision='invalid'")
            with self.assertRaises(ValueError):marks.validate_restored_marks(conn)
            conn.rollback()
        self.assertEqual(len(self.rows()),1)

    def test_portable_backup_restore_and_old_backup_preserve_boundaries(self):
        self.mark();self.save(self.payload(1,correct=False));self.save(self.payload(2));self.finish(2)
        restore.reset_learning_intelligence_core(dlms.DB_PATH)
        generation=self.context()['generation']
        archive,_=dlms._create_dlms_backup('marks-test')
        staged=Path(dlms.APP_DATA_DIR)/'marks-restore'
        dlms._extract_validated_backup(archive,staged,dlms._validate_dlms_backup(archive))
        dlms._prepare_staged_restore_database(str(staged))
        with sqlite3.connect(staged/'results.db') as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM review_marks WHERE marked=1').fetchone()[0],1)
            self.assertNotEqual(conn.execute('SELECT generation FROM review_mark_state').fetchone()[0],generation)
            self.assertEqual(conn.execute('SELECT count(*) FROM learning_events').fetchone()[0],0)
            self.assertEqual(conn.execute('SELECT count(*) FROM study_responses').fetchone()[0],2)
            self.assertIsNotNone(conn.execute('SELECT completed_at FROM study_sessions').fetchone()[0])
        # A real older portable backup has no marks, but retains factual Study data.
        with dlms.get_db() as conn:
            for table in ('review_mark_actions','review_marks','review_mark_state'):conn.execute('DROP TABLE '+table)
            conn.execute('UPDATE schema_meta SET version=5')
        old,_=dlms._create_dlms_backup('old-marks-test');oldstaged=Path(dlms.APP_DATA_DIR)/'old-marks-restore'
        dlms._extract_validated_backup(old,oldstaged,dlms._validate_dlms_backup(old))
        dlms._prepare_staged_restore_database(str(oldstaged))
        with sqlite3.connect(oldstaged/'results.db') as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM review_marks').fetchone()[0],0)
            self.assertEqual(conn.execute('SELECT count(*) FROM study_responses').fetchone()[0],2)
            self.assertEqual(conn.execute('SELECT count(*) FROM learning_events').fetchone()[0],0)

    def test_orphan_generated_mark_retains_exact_copy_but_legacy_adoption_rejects(self):
        orphan,_=self.publish(title='Older generated quiz',questions=[self.choice()],kind='native_spaced_review')
        legacy=self.mark_data(orphan);legacy['legacy']=True
        self.assertEqual(self.client.post('/api/review-marks/save',json=legacy,headers=self.headers).status_code,409)
        self.assertEqual(self.rows(),[])
        self.mark(orphan)
        row=self.rows(orphan)[0]
        self.assertEqual(row['quiz_id'],orphan)
        self.assertIn('no verified matching source revision',row['practice_reason'])
        self.assertEqual(row['anki_reason'],'')
        self.assertEqual(self.context(orphan)['indexes'],[0])
        d=self.action_data([row['id']])
        self.assertEqual(self.client.post('/api/review-marks/generate',json=d,headers=self.headers).status_code,409)
        response=self.client.post('/api/review-marks/anki',json=d,headers=self.headers)
        self.assertEqual(response.status_code,200);response.close()
        self.assertEqual(len(self.rows()),1);self.assertEqual(self.evidence(),[])

    def test_schema_six_missing_or_invalid_state_is_not_ready(self):
        self.mark()
        for mutation in ('DELETE FROM review_mark_state', "UPDATE review_mark_state SET generation='invalid'", 'UPDATE review_mark_state SET revision=-1'):
            with self.subTest(mutation=mutation):
                copy=Path(dlms.APP_DATA_DIR)/'invalid-state.db'
                with dlms.get_db() as source,sqlite3.connect(copy) as target: source.backup(target)
                with sqlite3.connect(copy) as conn:conn.execute(mutation)
                before=copy.read_bytes()
                with self.assertRaisesRegex(RuntimeError,'state is incomplete or invalid'):
                    dlms.bootstrap_database(str(copy))
                self.assertEqual(copy.read_bytes(),before)
                with sqlite3.connect(copy) as conn:self.assertEqual(conn.execute('SELECT count(*) FROM review_marks').fetchone()[0],1)
                copy.unlink()

    def test_schema_six_crash_and_validation_failure_preserve_all_old_rows(self):
        import subprocess,sys,os
        self.save(self.payload(1,correct=False));self.save(self.payload(2));self.finish(2)
        restore.reset_learning_intelligence_core(dlms.DB_PATH)
        with dlms.get_db() as conn:
            for table in ('review_mark_actions','review_marks','review_mark_state'):conn.execute('DROP TABLE '+table)
            conn.execute('UPDATE schema_meta SET version=5')
        def contents():
            with dlms.get_db() as conn:
                names=[r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
                return {name:sorted([tuple(row) for row in conn.execute('SELECT * FROM "'+name+'"')],key=repr) for name in names if name!='schema_meta'}
        before=contents()
        script="""import os,sys
from dlms.persistence import database as d,review_mark_schema as m
def crash(c):
 c.execute(m.STATEMENTS[0]);c.execute(m.STATEMENTS[1]);os._exit(73)
d.bootstrap_database(sys.argv[1],schema_version=6,legacy_schema_version=1,legacy_core_tables=d.DLMS_LEGACY_CORE_TABLES,migrations={6:crash},create_current_schema=None,database_table_names=d._database_table_names,read_schema_version=d._read_database_schema_version,validate_current_schema=d._validate_current_database_schema)
"""
        run=subprocess.run([sys.executable,'-c',script,dlms.DB_PATH],cwd=Path(dlms.__file__).parent,env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'},capture_output=True,text=True,timeout=15)
        self.assertEqual(run.returncode,73,run.stderr);self.assertEqual(contents(),before)
        with dlms.get_db() as conn:self.assertEqual(conn.execute('SELECT version FROM schema_meta').fetchone()[0],5)
        with mock.patch.object(dlms,'_validate_current_database_schema',side_effect=RuntimeError('validation interrupted')):
            with self.assertRaisesRegex(RuntimeError,'validation interrupted'):dlms.bootstrap_database(dlms.DB_PATH)
        self.assertEqual(contents(),before)
        dlms.bootstrap_database(dlms.DB_PATH)
        after=contents()
        # Schema 10 rotates only certification form state to reject old deadline writers.
        self.assertEqual({name:after[name] for name in before if name!='certification_state'},
                         {name:rows for name,rows in before.items() if name!='certification_state'})
        old_state,new_state=before['certification_state'][0],after['certification_state'][0]
        self.assertEqual(new_state[0],old_state[0]);self.assertNotEqual(new_state[1],old_state[1])
        self.assertEqual(new_state[2],old_state[2]+1)
        self.assertEqual(after['review_marks'],[]);self.assertEqual(after['learning_events'],[])
        # The previous build's version guard rejects the current schema before any write.
        raw=Path(dlms.DB_PATH).read_bytes()
        with mock.patch.object(dlms,'DLMS_SCHEMA_VERSION',5):
            with self.assertRaisesRegex(RuntimeError,'newer than this DLMS build'):dlms.bootstrap_database(dlms.DB_PATH)
        self.assertEqual(Path(dlms.DB_PATH).read_bytes(),raw)

    def test_concurrent_unmark_selects_exact_rows_and_legacy_retry_cannot_remark(self):
        self.mark()
        second,_=self.publish(title='Other marked quiz',questions=[{**self.choice(),'question':'Other question'}],kind=None)
        transfer=self.mark_data(second,legacy=True)
        self.assertEqual(self.client.post('/api/review-marks/save',json=transfer,headers=self.headers).status_code,200)
        rows=self.rows();first=next(m['id'] for m in rows if m['quiz_id']==self.quiz_id);other=next(m['id'] for m in rows if m['quiz_id']==second)
        one={**self.action_data([first]),'action':'unmark'};two={**self.action_data([other]),'action':'unmark'}
        def send(d):
            client=dlms.app.test_client();return client.post('/api/review-marks/save',json=d,headers=csrf_headers(client)).status_code
        with ThreadPoolExecutor(2) as pool:outcomes=list(pool.map(send,[one,two]))
        self.assertEqual(sorted(outcomes),[200,409]);self.assertEqual(len(self.rows()),1)
        winning=one if outcomes[0]==200 else two
        self.assertEqual(send(winning),200);self.assertEqual(len(self.rows()),1)
        remaining={**self.action_data([self.rows()[0]['id']]),'action':'unmark'}
        self.assertEqual(send(remaining),200)
        self.assertEqual(send(transfer),200)  # Lost legacy acknowledgement, not a new mark.
        self.assertEqual(self.rows(),[])

    def test_selection_preview_exact_types_reasons_and_stale_scope(self):
        self.mark()
        match,_=self.publish(title='Matching',questions=[self.matching()],kind=None);self.mark(match)
        hotspot=dict(number=1,type='hotspot',question='Locate the target',image_url='/static/favicon.ico',image_alt='Test target',target=dict(type='circle',x=.5,y=.5,radius=.2),target_label='Center')
        hot,_=self.publish(title='Hotspot',questions=[hotspot],kind=None);self.mark(hot)
        d=self.action_data()
        before=self.rows()
        response=self.client.post('/api/review-marks/preview',json=d,headers=self.headers)
        self.assertEqual(response.status_code,200,response.json)
        self.assertEqual(response.json['total'],3)
        self.assertEqual((response.json['practice']['included'],response.json['practice']['excluded']),(2,1))
        self.assertEqual((response.json['anki']['included'],response.json['anki']['excluded']),(1,2))
        self.assertEqual(sum(r['count'] for r in response.json['anki']['reasons']),2)
        self.assertEqual(self.rows(),before);self.assertEqual(self.evidence(),[])
        self.assertTrue(self.rows(hot)[0]['url'])
        for action in ('generate','anki'):
            self.assertEqual(self.client.post('/api/review-marks/'+action,json=d,headers=self.headers).status_code,409)
        choice=next(m['id'] for m in before if m['quiz_id']==self.quiz_id);d=self.action_data([choice])
        with mock.patch.object(dlms,'get_excluded_learning_folders',return_value=['Uncategorized']):
            response=self.client.post('/api/review-marks/preview',json=d,headers=self.headers)
            self.assertEqual(response.json['practice']['excluded'],1)
            self.assertIn('Learning Scope',response.json['practice']['reasons'][0]['reason'])
            self.assertEqual(self.client.post('/api/review-marks/generate',json=d,headers=self.headers).status_code,409)
        with dlms.get_db() as conn:conn.execute("UPDATE questions SET question_text='Revised source' WHERE quiz_id=?",(self.quiz_id,))
        response=self.client.post('/api/review-marks/preview',json=d,headers=self.headers)
        self.assertEqual(response.json['anki']['excluded'],1)
        self.assertIn('changed',response.json['anki']['reasons'][0]['reason'])
        self.assertEqual(self.client.post('/api/review-marks/anki',json=d,headers=self.headers).status_code,409)

    def test_canonical_hotspot_marks_verify_target_label_and_source_projection(self):
        hotspot=dict(number=1,type='hotspot',question='Select the target',image_url='/static/favicon.ico',
                     target=dict(type='circle',x=.5,y=.5,radius=.2),target_label='Center')
        canonical=dict(number=1,type='choice',question='Select the target [Image hotspot]',
                       image_url='/static/favicon.ico',choices=[dict(label='A',text='Center',is_correct=True)])
        qid,_=dlms._publish_quiz('Canonical hotspot',[hotspot],[canonical],filename_prefix='canonical_hotspot')
        self.mark(qid)
        before=self.rows(qid)
        self.assertEqual(len(before),1)
        self.assertTrue(before[0]['url'])
        self.assertIn('image or hotspot',before[0]['practice_reason'])
        self.assertIn('text choice',before[0]['anki_reason'])
        with dlms.get_db() as conn:
            conn.execute("UPDATE choices SET text='Different target' WHERE question_id IN (SELECT id FROM questions WHERE quiz_id=?)",(qid,))
        rejected=self.client.post('/api/review-marks/context',json=dict(quiz_id=qid,fingerprint=self.fingerprint(qid)),headers=self.headers)
        self.assertEqual(rejected.status_code,409)
        self.assertIn('source changed',rejected.json['error'])
        self.assertEqual(len(self.rows(qid)),1)
        self.assertEqual(self.evidence(),[])

    def test_hotspot_target_revision_and_legacy_fingerprint_are_not_substituted(self):
        hotspot=dict(number=1,type='hotspot',question='Select the target',image_url='/static/favicon.ico',target=dict(type='circle',x=.5,y=.5,radius=.2))
        qid,_=self.publish(title='Direct hotspot review',questions=[hotspot],kind=None)
        old=self.mark_data(qid,legacy=True)
        self.assertEqual(self.client.post('/api/review-marks/save',json=old,headers=self.headers).status_code,200)
        original=self.rows(qid)[0]
        entry=next(e for e in dlms.load_registry() if e['id']==qid)
        _,name=dlms._quiz_artifact_names(entry);path=Path(dlms.DATA_FOLDER,name)
        questions=json.loads(path.read_text());questions[0]['target']['x']=.2;path.write_text(json.dumps(questions))
        self.assertIn('changed',self.rows(qid)[0]['practice_reason'])
        stale={**old,'request_id':uuid.uuid4().hex,'revision':self.context(qid)['revision']}
        self.assertEqual(self.client.post('/api/review-marks/save',json=stale,headers=self.headers).status_code,409)
        self.assertEqual(self.context(qid)['indexes'],[])
        self.mark(qid)
        rows=self.rows(qid);self.assertEqual(len(rows),2)
        self.assertEqual(len({m['question_revision'] for m in rows}),2)
        self.assertIn(original['id'],[m['id'] for m in rows]);self.assertEqual(self.evidence(),[])
