"""Explicit order, preservation/readiness separation and stale answer contracts."""
import copy
import hashlib
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests._isolation import ensure_test_data_isolation
ensure_test_data_isolation()
import app as dlms
from tests import test_portable_quiz_bundles as fixtures
from tests.csrf_test_utils import csrf_headers
from dlms.persistence import choice_schema, database
from dlms.services import portable_quiz_bundles as bundles, quiz_readiness, study_sessions


class ChoicePreservationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.PortableQuizBundleTests('runTest')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.client = dlms.app.test_client()
        self.headers = csrf_headers(self.client)

    def quiz(self, labels=('A','C','D'), flags=(False,False,True), stem='  Exact question  '):
        q = self.fixture._choice(stem)
        q['choices'] = [{'label':label,'text':'  Option '+str(i)+'  ','is_correct':flag} for i,(label,flag) in enumerate(zip(labels,flags))]
        q['correct'] = [c['label'] for c in q['choices'] if c['is_correct']]
        return q

    def test_format_two_raw_order_flags_and_readiness_round_trip(self):
        for labels,flags,stem,ready in [
            (('D','A','C'),(True,False,False),'  Question  ',True),
            (('A','A','B'),(False,True,False),'Duplicate',False),
            (('A','C'),(False,True),'',False),
            (('A','C','D'),(False,False,False),'Unknown key',False),
            (('A','C','D'),(True,False,True),'Multi',True)]:
            with self.subTest(labels=labels,flags=flags,stem=stem):
                q=self.quiz(labels,flags,stem)
                qid=self.fixture._seed('Synthetic preserved',f'preserved-{len(dlms.load_registry())}.html',[q])
                data,_,manifest=self.fixture._export([qid])
                self.assertEqual(2,manifest['schema_version'])
                portable=manifest['quizzes'][0]['questions'][0]
                self.assertEqual(stem,portable['question'])
                self.assertEqual([{**c,'key':f'choice-{i:03d}'} for i,c in enumerate(q['choices'],1)],portable['choices'])
                before={r['id'] for r in dlms.load_registry()}
                self.fixture._import_bytes(data)
                imported=next(r['id'] for r in dlms.load_registry() if r['id'] not in before)
                with dlms.get_db() as c:
                    question=c.execute('SELECT id FROM questions WHERE quiz_id=?',(imported,)).fetchone()[0]
                    payload=dlms._question_payload_from_db(c.cursor(),question)
                    self.assertEqual(q['choices'],payload['choices'])
                    self.assertEqual(stem,payload['question'])
                    self.assertEqual(ready,quiz_readiness.quiz_readiness(c.cursor(),imported)['ready'])
                    self.assertEqual(list(range(len(labels))),[r[0] for r in c.execute('SELECT choice_order FROM choices WHERE question_id=? ORDER BY choice_order',(question,))])
                again=self.fixture._export([imported])[2]['quizzes'][0]['questions'][0]
                self.assertEqual(portable,again)

    def test_format_one_still_imports_and_format_two_keys_and_flags_are_strict(self):
        manifest=self.fixture._minimal_manifest()
        manifest['schema_version']=1
        for q in manifest['quizzes'][0]['questions']:
            for c in q.get('choices',[]):c.pop('key',None)
        self.assertEqual(1,bundles.validate_portable_quiz_bundle_manifest(manifest)['schema_version'])
        self.fixture._import_bytes(self.fixture._write_bundle(manifest).read_bytes())
        manifest['schema_version']=2
        for q in manifest['quizzes'][0]['questions']:
            for i,c in enumerate(q.get('choices',[]),1):c['key']=f'choice-{i:03d}'
        self.assertEqual(2,bundles.validate_portable_quiz_bundle_manifest(manifest)['schema_version'])
        for mutate in ('duplicate-key','nonboolean','extra-field'):
            bad=copy.deepcopy(manifest);choices=bad['quizzes'][0]['questions'][0]['choices']
            if mutate=='duplicate-key':choices[1]['key']=choices[0]['key']
            elif mutate=='nonboolean':choices[0]['is_correct']=1
            else:choices[0]['unexpected']='ignored?'
            with self.assertRaises(bundles.PortableQuizBundleError):bundles.validate_portable_quiz_bundle_manifest(bad)

    def test_raw_matching_limits_and_malformed_metadata_are_complete_blockers(self):
        manifest=self.fixture._minimal_manifest()
        matching=self.fixture._matching()
        self.assertEqual('matching',matching['type'])
        qid=self.fixture._seed('Malformed matching','matching-bad.html',[matching])
        with dlms.get_db() as c:
            qi=c.execute('SELECT id FROM questions WHERE quiz_id=?',(qid,)).fetchone()[0]
            c.execute("UPDATE matching_pairs SET verification_json='broken JSON' WHERE question_id=?",(qi,))
            c.commit()
        other=self.fixture._seed('Malformed media','media-bad.html',[self.quiz()])
        with dlms.get_db() as c:
            c.execute("UPDATE questions SET media_json='[]' WHERE quiz_id=?",(other,));c.commit()
            report=dlms._preflight_portable_quiz_export(c.cursor(),dlms.load_registry(),[qid,other])
        self.assertEqual(2,report['blocked_quizzes'])
        self.assertEqual([qid,other],[q['quiz_id'] for q in report['quizzes']])
        matching['pairs'][0]['left']=' '*4000+'a'
        with self.assertRaisesRegex(ValueError,'4,000'):
            bundles._validate_question(matching,quiz_number=1,question_number=1,asset_references={},version=2)

    def test_invalid_raw_source_numbers_block_preflight_and_direct_export(self):
        qid=self.fixture._seed('Invalid source number','source-number.html',[self.quiz()])
        for value in (2.5, True, 0, -1, '2'):
            with self.subTest(value=value):
                with dlms.get_db() as c:
                    c.execute('UPDATE questions SET media_json=? WHERE quiz_id=?',(json.dumps({'source_number':value}),qid));c.commit()
                    report=dlms._preflight_portable_quiz_export(c.cursor(),dlms.load_registry(),[qid])
                self.assertEqual(1,report['blocked_quizzes'])
                self.assertIn('positive integer',report['quizzes'][0]['blockers'][0]['reason'])
                with self.assertRaisesRegex(ValueError,'positive integer'):
                    self.fixture._export([qid])

    def test_warning_confirmation_is_bound_to_displayed_selection_and_issues(self):
        ready=self.fixture._seed('Ready','ready.html',[self.quiz()])
        warning=self.fixture._seed('Needs review','warning.html',[self.quiz(flags=(False,False,False))])
        with dlms.get_db() as c:
            old=dlms._preflight_portable_quiz_export(c.cursor(),dlms.load_registry(),[ready])
        response=self.client.post('/quiz-bundles/export',data={'quiz_ids':[ready,warning],'export_action':'preserve','warning_snapshot':old['signature']},headers=self.headers)
        self.assertEqual('text/html',response.mimetype);self.assertIn('No correct answer is marked',response.text)
        with dlms.get_db() as c:
            displayed=dlms._preflight_portable_quiz_export(c.cursor(),dlms.load_registry(),[ready,warning])
            c.execute("UPDATE questions SET question_text='' WHERE quiz_id=?",(warning,));c.commit()
        response=self.client.post('/quiz-bundles/export',data={'quiz_ids':[ready,warning],'export_action':'preserve','warning_snapshot':displayed['signature']},headers=self.headers)
        self.assertIn('Question text is empty',response.text);self.assertEqual(2,response.text.count(' checked'))

    def test_all_preflight_issues_grouped_and_selection_retained(self):
        empty=self.quiz(stem='');empty['number']=2
        a=self.fixture._seed('Two warnings','warn-a.html',[self.quiz(('A','A','B'),(False,True,False)),empty])
        b=self.fixture._seed('Missing answers','warn-b.html',[self.quiz(flags=(False,False,False))])
        q=self.quiz();q['image_url']='/quiz-assets/missing/picture.png'
        second=copy.deepcopy(q);second['number']=2
        c=self.fixture._seed('Missing images','block-c.html',[q,second])
        with dlms.get_db() as connection:
            report=dlms._preflight_portable_quiz_export(connection.cursor(),dlms.load_registry(),[a,b,c])
        self.assertEqual((2,1),(report['warning_quizzes'],report['blocked_quizzes']))
        self.assertEqual([a,b,c],[x['quiz_id'] for x in report['quizzes']])
        self.assertEqual([1,2],[x['position'] for x in report['quizzes'][0]['warnings']])
        self.assertEqual([1,2],[x['position'] for x in report['quizzes'][2]['blockers']])
        response=self.client.post('/quiz-bundles/export',data={'quiz_ids':[a,b,c]},headers=self.headers)
        self.assertEqual(400,response.status_code)
        html=response.get_data(as_text=True)
        for name in ('Two warnings','Missing answers','Missing images','No correct answer is marked','Question text is empty'):
            self.assertIn(name,html)
        self.assertEqual(3,html.count(' checked'))
        self.assertIn('2 quizzes with Needs review warnings',html)
        self.assertIn('1 blocked',html)
        self.assertIn('/edit_quiz/'+str(a),html)
        warning_only=self.client.post('/quiz-bundles/export',data={'quiz_ids':[a,b]},headers=self.headers)
        self.assertEqual(200,warning_only.status_code);self.assertIn('Selection check',warning_only.text)
        with dlms.get_db() as connection:
            signature=dlms._preflight_portable_quiz_export(connection.cursor(),dlms.load_registry(),[a,b])['signature']
        confirmed=self.client.post('/quiz-bundles/export',data={'quiz_ids':[a,b],'export_action':'preserve','warning_snapshot':signature},headers=self.headers)
        self.assertEqual('application/zip',confirmed.mimetype);confirmed.close()

    def test_nonpositional_study_and_exam_require_explicit_answer_encoding(self):
        q=self.quiz();qid,html=dlms._publish_quiz('Actual labels',[q])
        status=self.client.get(f'/api/study/quiz/{qid}').json
        self.assertTrue(status['readiness']['ready'])
        self.assertTrue(status['readiness']['actual_labels_required'])
        entry=next(x for x in dlms.load_registry() if x['id']==qid)
        _,name=dlms._quiz_artifact_names(entry)
        raw=(Path(dlms.DATA_FOLDER)/name).read_text()
        seed='\0'.join(['quiz-recovery-v1','1',str(qid),'/data/'+name,'90',raw])
        fingerprint='sha256:'+hashlib.sha256(seed.encode()).hexdigest()
        claim={'quizId':qid,'sessionId':'labels-session','owner':'labels-owner','generation':status['generation'],'fingerprint':fingerprint,'variants':{}}
        self.assertEqual(400,self.client.post('/api/study/session',json=claim,headers=self.headers).status_code)
        claim['answerEncoding']=quiz_readiness.ANSWER_ENCODING
        response=self.client.post('/api/study/session',json=claim,headers=self.headers)
        self.assertEqual(200,response.status_code,response.json)
        event={**claim,'contract':2,'assessmentRevision':response.json['session']['assessment_revision'],'eventId':'actual-d','sequence':1,'questionOrdinal':1,'questionType':'choice','wasCorrect':True,'selected':['D'],'kind':'response'}
        old=dict(event);old.pop('answerEncoding')
        self.assertEqual(400,self.client.post('/api/learning-events/study-response',json=old,headers=self.headers).status_code)
        self.assertEqual(200,self.client.post('/api/learning-events/study-response',json=event,headers=self.headers).status_code)
        self.assertEqual(200,self.client.post('/api/study/finish',json=event,headers=self.headers).status_code)
        attempt={'quizId':qid,'attemptId':'actual-d-exam','score':1,'total':1,'percent':100,'mode':'Exam','responseDetails':[{'attemptQuestionNumber':1,'questionType':'choice','wasCorrect':True,'selected':['D']}],'missedDetails':[]}
        self.assertEqual(400,self.client.post('/record_attempt',json=attempt,headers=self.headers).status_code)
        attempt['answerEncoding']=quiz_readiness.ANSWER_ENCODING
        self.assertEqual(200,self.client.post('/record_attempt',json=attempt,headers=self.headers).status_code)
        with dlms.get_db() as c:
            saved=c.execute("SELECT response_json FROM learning_events WHERE attempt_id=? AND event_type='exam_answer'",('actual-d-exam',)).fetchone()
            self.assertEqual(['D'],json.loads(saved[0])['selected'])
            self.assertEqual(1,c.execute('SELECT was_correct FROM study_responses WHERE session_id=?',('labels-session',)).fetchone()[0])

    def test_unready_content_blocks_direct_launch_study_exam_and_generated_publication(self):
        q=self.quiz(('A','A','B'),(False,True,False))
        qid,html=dlms._publish_quiz('Preserved duplicate',[q])
        response=self.client.get('/quizzes/'+html)
        self.assertEqual(409,response.status_code);self.assertIn('Review and edit',response.text)
        with dlms.get_db() as c:
            with self.assertRaisesRegex(ValueError,'needs review'):quiz_readiness.require_ready(c.cursor(),qid)
        for path,payload in [('/api/study/session',{'quizId':qid,'sessionId':'blocked','owner':'owner','generation':self.client.get(f'/api/study/quiz/{qid}').json['generation'],'fingerprint':'unused','variants':{}}),('/record_attempt',{'quizId':qid,'attemptId':'blocked'})]:
            self.assertEqual(400,self.client.post(path,json=payload,headers=self.headers).status_code)
        with self.assertRaisesRegex(ValueError,'needs review'):
            dlms._publish_quiz('No silent omission',[q],generation_kind='smart_review')
        with dlms.get_db() as c:
            self.assertEqual(0,c.execute('SELECT count(*) FROM study_responses').fetchone()[0])
            self.assertEqual(0,c.execute('SELECT count(*) FROM attempts').fetchone()[0])

    def test_supported_hotspot_surrogate_does_not_admit_incomplete_choice_rows(self):
        runtime = {'number': 1, 'type': 'hotspot', 'question': 'Locate the control',
                   'image_url': '/static/favicon.ico',
                   'target': {'type': 'circle', 'x': .5, 'y': .5, 'radius': .2}}
        canonical = {**runtime, 'type': 'choice',
                     'question': runtime['question'] + ' [Image hotspot]',
                     'choices': [{'label': 'A', 'text': 'Control', 'is_correct': True}]}
        ready, html = dlms._publish_quiz('Supported hotspot', [runtime], [canonical])
        incomplete, blocked_html = dlms._publish_quiz('Incomplete canonical row', [runtime])
        with dlms.get_db() as c:
            self.assertTrue(quiz_readiness.quiz_readiness(c.cursor(), ready)['ready'])
            issues = quiz_readiness.quiz_readiness(c.cursor(), incomplete)['issues']
            self.assertEqual(['A choice question needs between 1 and 26 choices.',
                              'No correct answer is marked.'], [i['reason'] for i in issues])
            self.assertEqual(0, c.execute('SELECT count(*) FROM choices WHERE question_id IN '
                                         '(SELECT id FROM questions WHERE quiz_id=?)',
                                         (incomplete,)).fetchone()[0])
        self.assertEqual(200, self.client.get('/quizzes/' + html).status_code)
        self.assertEqual(409, self.client.get('/quizzes/' + blocked_html).status_code)
        with dlms.get_db() as c:
            self.assertEqual(0, c.execute('SELECT count(*) FROM study_responses').fetchone()[0])
            self.assertEqual(0, c.execute('SELECT count(*) FROM attempts').fetchone()[0])


class ChoiceMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='dlms-choice-migration-');self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'results.db'
        sql=Path('init.sql').read_text().replace('    choice_order INTEGER,\n','').replace('VALUES (1, 11);','VALUES (1, 10);')
        sql=sql.replace('CREATE UNIQUE INDEX IF NOT EXISTS idx_choices_order ON choices(question_id, choice_order);','')
        with sqlite3.connect(self.path) as c:
            c.executescript(sql)
            c.execute("INSERT INTO quizzes(id,title,source_file) VALUES(1,'Migration sample','migration.html')")
            c.execute("INSERT INTO questions(id,quiz_id,question_number,question_text) VALUES(1,1,1,'Sample'),(2,1,2,'Sample'),(3,1,3,'Sample')")
            for qid,labels in [(1,['R','A','B','C','D']),(2,['A','B','D','C']),(3,['A','A','B'])]:
                for i,label in enumerate(labels):c.execute('INSERT INTO choices(question_id,label,text,is_correct) VALUES(?,?,?,?)',(qid,label,'Exact '+str(i),int(i==1)))
            self.before=[tuple(r) for r in c.execute('SELECT id,question_id,label,text,is_correct FROM choices ORDER BY id')]

    def test_migration_preserves_values_tie_order_and_repeated_startup(self):
        result=dlms.bootstrap_database(str(self.path),require_owned_root=False)
        self.assertEqual(10,result['from_version']);self.assertEqual(11,result['version'])
        with database.get_db(self.path) as c:
            self.assertEqual(self.before,[tuple(r) for r in c.execute('SELECT id,question_id,label,text,is_correct FROM choices ORDER BY id')])
            for qid,expected in [(1,['A','B','C','D','R']),(2,['A','B','C','D']),(3,['A','A','B'])]:
                rows=c.execute('SELECT id,label,choice_order FROM choices WHERE question_id=? ORDER BY choice_order,id',(qid,)).fetchall()
                self.assertEqual(expected,[r['label'] for r in rows]);self.assertEqual(list(range(len(rows))),[r['choice_order'] for r in rows])
                if qid==3:self.assertLess(rows[0]['id'],rows[1]['id'])
            before=list(c.iterdump());choice_schema.migrate(c);self.assertEqual(before,list(c.iterdump()))
        self.assertEqual('current',dlms.bootstrap_database(str(self.path),require_owned_root=False)['status'])

    def test_migration_keeps_assessment_and_mark_question_revisions(self):
        import types
        old=types.ModuleType('dlms.services.pre_migration_study');old.__package__='dlms.services'
        code=subprocess.check_output(['git','show','HEAD:dlms/services/study_sessions.py'],text=True)
        exec(compile(code,'pre_migration_study.py','exec'),old.__dict__)
        with database.get_db(self.path) as c:
            before=(old.assessment_revision(c.cursor(),1),[old.question_revision(c.cursor(),q) for q in (1,2,3)])
        dlms.bootstrap_database(str(self.path),require_owned_root=False)
        with database.get_db(self.path) as c:
            after=(study_sessions.assessment_revision(c.cursor(),1),[study_sessions.question_revision(c.cursor(),q) for q in (1,2,3)])
        self.assertEqual(before,after)

    def test_changed_order_index_cannot_masquerade_as_current_schema(self):
        dlms.bootstrap_database(str(self.path),require_owned_root=False)
        for definition in ('CREATE INDEX idx_choices_order ON choices(question_id,choice_order)',
                           'CREATE UNIQUE INDEX idx_choices_order ON choices(id)'):
            with sqlite3.connect(self.path) as c:
                c.execute('DROP INDEX idx_choices_order');c.execute(definition)
            with self.assertRaisesRegex(RuntimeError,'choice order index'):
                dlms.bootstrap_database(str(self.path),require_owned_root=False)
            with sqlite3.connect(self.path) as c:
                c.execute('DROP INDEX idx_choices_order')
                c.execute('CREATE UNIQUE INDEX idx_choices_order ON choices(question_id,choice_order)')

    def test_failed_and_interrupted_migration_leave_schema_ten_retryable(self):
        def fail(c):choice_schema.migrate(c);raise RuntimeError('interrupted migration')
        with mock.patch.dict(dlms.DLMS_SCHEMA_MIGRATIONS,{11:fail}):
            with self.assertRaisesRegex(RuntimeError,'interrupted'):dlms.bootstrap_database(str(self.path),require_owned_root=False)
        with sqlite3.connect(self.path) as c:
            self.assertEqual(10,c.execute('SELECT version FROM schema_meta').fetchone()[0])
            self.assertNotIn('choice_order',[r[1] for r in c.execute('pragma table_info(choices)')])
            self.assertEqual(self.before,c.execute('SELECT id,question_id,label,text,is_correct FROM choices ORDER BY id').fetchall())
        script="import sqlite3,os,sys;from dlms.persistence.choice_schema import migrate;c=sqlite3.connect(sys.argv[1]);c.execute('BEGIN IMMEDIATE');migrate(c);os._exit(37)"
        child=subprocess.run([sys.executable,'-c',script,str(self.path)],timeout=15)
        self.assertEqual(37,child.returncode)
        with sqlite3.connect(self.path) as c:self.assertEqual(10,c.execute('SELECT version FROM schema_meta').fetchone()[0])
        self.assertEqual('migrated',dlms.bootstrap_database(str(self.path),require_owned_root=False)['status'])

    def test_schema_ten_reader_refuses_upgraded_database_without_changes(self):
        dlms.bootstrap_database(str(self.path),require_owned_root=False)
        before=self.path.read_bytes()
        with self.assertRaises(database.UnsupportedDatabaseSchemaVersionError):
            database.bootstrap_database(str(self.path),schema_version=10,legacy_schema_version=1,
                legacy_core_tables=database.DLMS_LEGACY_CORE_TABLES,migrations={},create_current_schema=None,
                database_table_names=database._database_table_names,read_schema_version=database._read_database_schema_version,
                validate_current_schema=lambda c:None)
        self.assertEqual(before,self.path.read_bytes())
