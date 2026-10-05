"""Isolated Exam Plan persistence, calendar, evidence, scope and retry contracts."""
import copy
import json
import sqlite3
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock
from tests import test_study_sessions as foundation
from dlms.services import exam_plans as plans, restore
from dlms.persistence import exam_plan_schema
from tests.csrf_test_utils import csrf_headers

dlms = foundation.dlms


class ExamPlanTests(unittest.TestCase):
    choice = staticmethod(foundation.StudySessionTests.choice)
    matching = staticmethod(foundation.StudySessionTests.matching)
    publish = foundation.StudySessionTests.publish
    fingerprint = foundation.StudySessionTests.fingerprint
    payload = foundation.StudySessionTests.payload
    save = foundation.StudySessionTests.save
    finish = foundation.StudySessionTests.finish
    setUp = foundation.StudySessionTests.setUp

    def config(self, **changes):
        return {**copy.deepcopy(plans.DEFAULTS), 'name': 'CISM', 'exam_date': '2026-10-30',
                'calendar_timezone': 'America/Chicago', 'folders': ['uncategorized'], **changes}

    def create(self, **changes):
        with dlms.get_db() as conn:
            opts = dlms._exam_plan_options(conn.cursor())
            config = self.config(**changes)
            preview = plans.summary(conn.cursor(), dict(config=config, revision=0, snapshot={}), **opts)
            return plans.save(conn, config, generation=plans.state(conn.cursor())['generation'],
                              known_folders=['uncategorized'], snapshot=preview['snapshot'], active=True,
                              expected_dashboard=plans.dashboard_selection(conn.cursor()))

    def report(self, pid, now=None):
        with dlms.get_db() as conn:
            return plans.summary(conn.cursor(), plans.get(conn.cursor(), pid), **dlms._exam_plan_options(conn.cursor()), now=now)

    def request_data(self, pid, **changes):
        r = self.report(pid)
        return dict(request_id='request-plan-00000001', revision=r['plan']['revision'], generation=r['generation'], fingerprint=r['fingerprint'], mode='focused', count=1, **changes)

    def test_calendar_dst_travel_and_zero_capacity(self):
        config = self.config()
        now = datetime(2026, 10, 16, 18, tzinfo=timezone.utc)
        result = plans.calendar(config, now)
        self.assertEqual(result['days'], 6)
        self.assertEqual(result['potential_minutes'], 180)
        self.assertEqual(plans.calendar(config, now.astimezone(plans.ZoneInfo('Asia/Tokyo'))), result)
        for day in ('2026-03-08', '2026-11-01'):
            c = self.config(exam_date=day, weekdays=list(range(7)))
            stamp = datetime.fromisoformat(day).replace(tzinfo=plans.ZoneInfo('America/Chicago'))
            self.assertEqual(plans.calendar(c, stamp)['days'], 0)
        self.assertEqual(plans.calendar(self.config(exam_date='2020-01-01'), now)['date_state'], 'passed')
        self.assertEqual(plans.calendar(self.config(exam_date='2026-10-17', weekdays=[1]), now)['days'], 0)

    def test_validation_persistence_conflicts_and_failed_write(self):
        pid = self.create()
        with dlms.get_db() as conn:
            original = plans.get(conn.cursor(), pid)
            generation = plans.state(conn.cursor())['generation']
            for change in ({'minutes': True}, {'pace': float('nan')}, {'weekdays': []}, {'calendar_timezone': '../UTC'}, {'exam_date':'2026-02-30'}, {'folders': []}, {'pace_low': 5}):
                with self.subTest(change=change), self.assertRaises(ValueError):
                    plans.validate(self.config(**change))
            with self.assertRaises(plans.PlanConflict):
                plans.save(conn, self.config(name='stale'), plan_id=pid, revision=0, generation=generation, known_folders=['uncategorized'])
            conn.rollback()
            conn.execute("CREATE TRIGGER fail_plan BEFORE UPDATE ON exam_plans BEGIN SELECT RAISE(ABORT,'test failure'); END")
            conn.commit()
            with self.assertRaises(sqlite3.DatabaseError):
                plans.save(conn, self.config(name='unsaved'), plan_id=pid, revision=1, generation=generation, known_folders=['uncategorized'])
            conn.rollback()
            self.assertEqual(plans.get(conn.cursor(), pid), original)

    def test_reset_preserves_coverage_but_requires_fresh_evidence(self):
        self.save(self.payload(1, correct=False)); self.save(self.payload(2)); self.finish(2)
        pid = self.create()
        r = self.report(pid)
        self.assertEqual(r['stats']['reviewed'], 1)
        self.assertEqual(r['stats']['full'], 1)
        self.assertEqual(len(r['missed']), 1)
        restore.reset_learning_intelligence_core(dlms.DB_PATH)
        r = self.report(pid)
        self.assertEqual(r['stats']['reviewed'], 1)
        self.assertEqual(r['stats']['historical'], 1)
        self.assertEqual(r['stats']['fresh'], 1)
        self.assertEqual(r['missed'], [])
        self.assertEqual(r['stats']['today'], 0)
        # Restart/read and portable database copy cannot replay historical facts.
        copy_path = Path(dlms.DB_PATH).with_name('restored.db')
        with dlms.get_db() as conn, sqlite3.connect(copy_path) as backup:
            conn.backup(backup)
        dlms.bootstrap_database(str(copy_path))
        with sqlite3.connect(copy_path) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM learning_events').fetchone()[0], 0)
            self.assertEqual(conn.execute('SELECT count(*) FROM exam_plans').fetchone()[0], 1)

    def test_edit_and_scope_changes_are_visible(self):
        self.save(self.payload(1)); self.finish(1)
        pid = self.create()
        with dlms.get_db() as conn:
            conn.execute("UPDATE questions SET question_text='Materially edited' WHERE quiz_id=?", (self.quiz_id,))
        r = self.report(pid)
        self.assertEqual(r['stats']['reviewed'], 0)
        self.assertEqual(r['stats']['historical'], 1)
        self.assertTrue(r['changes']['changed'])
        registry = dlms.load_registry(); registry[0]['folder'] = 'Renamed'; dlms.save_registry(registry)
        r = self.report(pid)
        self.assertEqual(r['stats']['total'], 0)
        self.assertTrue(r['changes']['removed'])

    def test_exclusion_missing_artifact_and_csrf(self):
        pid = self.create()
        with dlms.get_db() as conn:
            opts = dlms._exam_plan_options(conn.cursor()); opts['excluded'] = ['uncategorized']
            r = plans.summary(conn.cursor(), plans.get(conn.cursor(), pid), **opts)
            self.assertEqual(r['stats']['total'], 1)
            self.assertEqual(r['stats']['blocked'], 1)
            self.assertEqual(r['candidates'], [])
        (Path(dlms.QUIZ_FOLDER)/self.html).unlink()
        self.assertEqual(self.report(pid)['stats']['unavailable'], 1)
        self.assertEqual(self.client.post('/api/exam-plans/preview', json=self.config()).status_code, 400)

    def test_generation_lost_ack_reuse_and_restore(self):
        pid = self.create()
        data = self.request_data(pid)
        url = f'/api/exam-plans/{pid}/generate'
        first = self.client.post(url, json=data, headers=self.headers)
        self.assertEqual(first.status_code, 200, first.json)
        again = self.client.post(url, json=data, headers=self.headers)
        self.assertEqual(again.json['url'], first.json['url'])
        self.assertTrue(again.json['replayed'])
        self.assertEqual(self.client.post(url, json={**data, 'count':2}, headers=self.headers).status_code, 409)
        with dlms.get_db() as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM quizzes WHERE generation_kind='adaptive_study'").fetchone()[0], 1)
            generated = conn.execute('SELECT * FROM questions WHERE quiz_id != ?', (self.quiz_id,)).fetchone()
            source = conn.execute('SELECT question_uid FROM questions WHERE quiz_id=?', (self.quiz_id,)).fetchone()[0]
            self.assertEqual(generated['source_question_uid'], source)
            exam_plan_schema.invalidate(conn)
        self.assertEqual(self.client.post(url, json=data, headers=self.headers).status_code, 409)

    def test_simultaneous_requests_publish_once(self):
        pid = self.create(); data = self.request_data(pid)
        barrier = threading.Barrier(2)
        def send():
            client = dlms.app.test_client(); headers = csrf_headers(client)
            barrier.wait(timeout=5)
            response = client.post(f'/api/exam-plans/{pid}/generate', json=data, headers=headers)
            return response.status_code, response.json
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: send(), range(2)))
        self.assertEqual([r[0] for r in results], [200,200], results)
        self.assertEqual(results[0][1]['url'], results[1][1]['url'])

    def test_pages_and_scoped_controls(self):
        pid = self.create()
        for route in ('/exam-plans', '/exam-plans/new', f'/exam-plans/{pid}', f'/exam-plans/{pid}/edit'):
            response = self.client.get(route)
            self.assertEqual(response.status_code, 200, route)
        with dlms.get_db() as conn:
            generation = plans.state(conn.cursor())['generation']
            plans.control(conn, pid, 'pause', 1, generation)
            self.assertTrue(plans.get(conn.cursor(), pid)['config']['paused'])
            plans.control(conn, pid, 'delete', 2, generation)
            self.assertEqual(conn.execute('SELECT count(*) FROM quizzes').fetchone()[0], 1)
            self.assertIsNone(plans.state(conn.cursor())['active_plan_id'])

    def test_old_database_additive_migration(self):
        with dlms.get_db() as conn:
            for table in ('exam_plan_actions','exam_plan_state','exam_plans'):
                conn.execute('DROP TABLE '+table)
            conn.execute('UPDATE schema_meta SET version=4')
        dlms.bootstrap_database(dlms.DB_PATH)
        with dlms.get_db() as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM quizzes').fetchone()[0],1)
            self.assertEqual(conn.execute('SELECT count(*) FROM exam_plans').fetchone()[0],0)
            self.assertEqual(conn.execute('SELECT count(*) FROM study_sessions').fetchone()[0],1)

    def study_questions(self, qid, *, count, wrong=(), stamp='2026-10-16T15:00:00+00:00', prefix='quota'):
        info = self.client.get(f'/api/study/quiz/{qid}').json
        claim = dict(quizId=qid, sessionId=prefix, owner=prefix+'-owner', generation=info['generation'], fingerprint=self.fingerprint(qid), variants={})
        with mock.patch('dlms.services.study_sessions.utc_now', return_value=stamp):
            session = self.client.post('/api/study/session', json=claim, headers=self.headers).json['session']
            sequence = 0
            for ordinal in range(1,count+1):
                for correct in ([False,True] if ordinal in wrong else [True]):
                    sequence += 1
                    payload = dict(contract=2, **claim, assessmentRevision=session['assessment_revision'], eventId=f'{prefix}-{sequence}', sequence=sequence,
                                   questionOrdinal=ordinal, questionType='choice', wasCorrect=correct, selected=['A' if correct else 'C'], kind='response')
                    response = self.save(payload)
                    self.assertEqual(response.status_code,200,response.json)
        with dlms.get_db() as conn:
            conn.execute('UPDATE learning_events SET occurred_at=? WHERE session_id=?', (stamp,prefix))
        return sequence

    def test_budget_coverage_priority_today_credit_and_unique_overlap(self):
        questions = [{**self.choice(), 'number': i+1, 'question':f'Coverage {i+1}'} for i in range(79)]
        qid, _ = self.publish(title='Coverage bank',questions=questions,kind=None)
        pid = self.create()
        now = datetime(2026,10,16,18,tzinfo=timezone.utc)
        initial = self.report(pid, now)
        self.assertEqual(initial['stats']['total'],80)
        self.assertEqual(initial['target'],14)
        self.assertEqual(initial['slots'],12)
        self.assertEqual(len(initial['selected']),12)
        self.study_questions(qid,count=5,wrong=(1,))
        after = self.report(pid, now)
        self.assertEqual(after['stats']['today'],5)
        self.assertEqual(after['remaining_slots'],7)
        self.assertEqual(after['target'],9)
        self.assertEqual(len(after['selected']),7)
        self.assertEqual([c['question_id'] for c in after['selected']], [c['question_id'] for c in self.report(pid,now)['selected']])
        self.assertEqual(len({c['question_id'] for c in after['selected']}),7)
        self.assertEqual(after['stats']['reviewed'],5)
        self.assertEqual(after['stats']['full'],0)
        self.assertGreater(after['shortfall'],0)

    def test_oversubscribed_first_mistakes_rank_and_generated_lineage(self):
        questions = [{**self.choice(), 'number':i+1, 'question':f'Equivalent item {i+1}'} for i in range(8)]
        qid,_ = self.publish(title='Oversubscribed bank',questions=questions,kind=None)
        self.study_questions(qid,count=8,wrong=(1,2,3,4),stamp='2026-10-15T15:00:00+00:00',prefix='ranking')
        pid = self.create()
        r = self.report(pid,datetime(2026,10,16,18,tzinfo=timezone.utc))
        candidates = [c for c in r['candidates'] if c['quiz_id']==qid]
        chosen = plans.learning._adaptive_study_select_candidates(candidates,3)
        self.assertEqual(len(chosen),3)
        self.assertTrue(all(c['question_number']<=4 for c in chosen))
        self.assertTrue(all(c['recent_accuracy']==0 for c in chosen))
        self.assertEqual(len({c['question_id'] for c in chosen}),3)
        # Repeated corrected mistakes in one quiz still share diversity penalties.
        first = next(c for c in candidates if c['question_number']==1)
        correct = next(c for c in candidates if c['question_number']==8)
        many = [{**first,'question_id':100+n} for n in range(10)] + [{**correct,'question_id':200,'quiz_id':999}]
        chosen = plans.learning._adaptive_study_select_candidates(many,10)
        self.assertEqual(chosen[-1]['question_id'],200)
        data = self.request_data(pid); data.update(mode='missed',count=3)
        response = self.client.post(f'/api/exam-plans/{pid}/generate',json=data,headers=self.headers)
        self.assertEqual(response.status_code,200,response.json)
        with dlms.get_db() as conn:
            ids = {row[0] for row in conn.execute('SELECT source_question_uid FROM questions WHERE is_generated_copy=1')}
            mistakes = {row[0] for row in conn.execute('SELECT question_uid FROM questions WHERE quiz_id=? AND question_number<=4',(qid,))}
            self.assertEqual(len(ids),3); self.assertTrue(ids <= mistakes)

    def test_scope_preview_race_and_deleted_generated_replay(self):
        pid=self.create(); data=self.request_data(pid)
        with dlms.get_db() as conn:
            conn.execute("UPDATE questions SET explanation='Changed revision' WHERE quiz_id=?",(self.quiz_id,))
        url=f'/api/exam-plans/{pid}/generate'
        self.assertEqual(self.client.post(url,json=data,headers=self.headers).status_code,409)
        data=self.request_data(pid)
        self.assertEqual(self.client.post(url,json=data,headers=self.headers).status_code,200)
        with dlms.get_db() as conn:
            conn.execute("DELETE FROM quizzes WHERE generation_kind='adaptive_study'")
        self.assertEqual(self.client.post(url,json=data,headers=self.headers).status_code,409)
        with dlms.get_db() as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM quizzes WHERE generation_kind='adaptive_study'").fetchone()[0],0)

    def test_timezone_package_without_system_database_and_date_only_evidence(self):
        import zoneinfo
        # no_cache exercises the package fallback under an empty search path.
        zoneinfo.reset_tzpath(())
        try:
            self.assertEqual(zoneinfo.ZoneInfo.no_cache('America/Chicago').key,'America/Chicago')
        finally:
            zoneinfo.reset_tzpath()
        pid=self.create(); self.save(self.payload(1))
        with dlms.get_db() as conn:
            conn.execute("UPDATE learning_events SET occurred_at='2026-10-16'")
        self.assertEqual(self.report(pid,datetime(2026,10,16,18,tzinfo=timezone.utc))['stats']['today'],0)

    def test_portable_restore_rotates_tokens_and_preserves_post_reset_boundary(self):
        import shutil
        pid=self.create(); self.save(self.payload(1)); self.finish(1)
        restore.reset_learning_intelligence_core(dlms.DB_PATH)
        stage=Path(dlms.APP_DATA_DIR)/'plan-restore-fixture'
        stage.mkdir()
        for name in ('config','data'):
            shutil.copytree(Path(dlms.APP_DATA_DIR)/name,stage/name)
        with dlms.get_db() as source, sqlite3.connect(stage/'results.db') as target:
            source.backup(target)
        with dlms.get_db() as conn:
            old=plans.state(conn.cursor())['generation']
        dlms._prepare_staged_restore_database(str(stage))
        with sqlite3.connect(stage/'results.db') as conn:
            conn.row_factory=sqlite3.Row
            self.assertNotEqual(plans.state(conn.cursor())['generation'],old)
            self.assertEqual(plans.get(conn.cursor(),pid)['config']['name'],'CISM')
            self.assertEqual(conn.execute('SELECT count(*) FROM learning_events').fetchone()[0],0)
            self.assertEqual(conn.execute('SELECT count(*) FROM study_sessions WHERE completed_at IS NOT NULL').fetchone()[0],1)
        # Simulate a real older backup: no new tables, unchanged Study facts.
        with sqlite3.connect(stage/'results.db') as conn:
            for table in ('exam_plan_actions','exam_plan_state','exam_plans'):
                conn.execute('DROP TABLE '+table)
            conn.execute('UPDATE schema_meta SET version=4')
        dlms._prepare_staged_restore_database(str(stage))
        with sqlite3.connect(stage/'results.db') as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM exam_plans').fetchone()[0],0)
            self.assertEqual(conn.execute('SELECT count(*) FROM study_sessions WHERE completed_at IS NOT NULL').fetchone()[0],1)

    def test_invalid_stored_plan_not_rewritten_and_restore_rejects_it(self):
        pid=self.create()
        with dlms.get_db() as conn:
            conn.execute('UPDATE exam_plans SET config_json=? WHERE id=?', ('{"name":"retained"}',pid))
        self.assertEqual(self.client.get('/exam-plans').status_code,200)
        self.assertIn(b'unsupported',self.client.get('/exam-plans/'+pid).data)
        with dlms.get_db() as conn:
            self.assertEqual(conn.execute('SELECT config_json FROM exam_plans').fetchone()[0],'{"name":"retained"}')
            with self.assertRaises(ValueError):
                plans.validate_restored_plans(conn)

    def test_failed_publication_and_pending_retries_never_duplicate(self):
        pid=self.create(); data=self.request_data(pid); url=f'/api/exam-plans/{pid}/generate'
        with mock.patch.object(dlms,'_write_staged_quiz_json',side_effect=OSError('fixture failure')):
            self.assertEqual(self.client.post(url,json=data,headers=self.headers).status_code,503)
        with dlms.get_db() as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM quizzes').fetchone()[0],1)
            self.assertEqual(conn.execute('SELECT state FROM exam_plan_actions').fetchone()[0],'retryable')
        # A fully rolled-back operation can safely retry the same ID.
        response=self.client.post(url,json=data,headers=self.headers)
        self.assertEqual(response.status_code,200,response.json)

    def test_plans_survive_history_deletion_but_not_full_reset(self):
        pid=self.create(); self.save(self.payload(1)); self.finish(1)
        restore.delete_study_history_core(dlms.DB_PATH)
        self.assertEqual(self.report(pid)['stats']['reviewed'],0)
        self.assertEqual(self.report(pid)['plan']['config']['name'],'CISM')
        dlms._full_data_reset_core()
        with dlms.get_db() as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM exam_plans').fetchone()[0],0)

    def test_multiple_plans_active_pointer_and_pause_hide_are_independent(self):
        first=self.create(); second=self.create(name='Second certification')
        with dlms.get_db() as conn:
            generation=plans.state(conn.cursor())['generation']
            self.assertEqual(plans.state(conn.cursor())['active_plan_id'],second)
            plans.control(conn,first,'activate',1,generation,expected_dashboard=plans.dashboard_selection(conn.cursor()))
            plans.control(conn,first,'visibility',2,generation)
            plans.control(conn,first,'pause',3,generation)
            self.assertEqual(plans.state(conn.cursor())['active_plan_id'],first)
            self.assertTrue(plans.get(conn.cursor(),second)['config']['visible'])
            self.assertFalse(plans.get(conn.cursor(),second)['config']['paused'])
            config=plans.get(conn.cursor(),first)['config']
            plans.save(conn,config,plan_id=first,revision=4,generation=generation,active=False,known_folders=['uncategorized'])
            self.assertEqual(plans.state(conn.cursor())['active_plan_id'],first)

    def test_unavailable_pack_and_unsupported_question_are_not_published(self):
        pid=self.create()
        with dlms.get_db() as conn:
            conn.execute('UPDATE questions SET media_json=? WHERE quiz_id=?',(json.dumps({'image_url':'/content-packs/never-installed/assets/image.png'}),self.quiz_id))
        with mock.patch.object(dlms,'get_content_pack',return_value=None):
            r=self.report(pid)
            self.assertEqual(r['stats']['unavailable'],1)
            self.assertEqual(r['selected'],[])
        with dlms.get_db() as conn:
            conn.execute("UPDATE questions SET media_json='{}',question_type='unsupported' WHERE quiz_id=?",(self.quiz_id,))
        self.assertEqual(self.report(pid)['stats']['unavailable'],1)

    def test_complete_answer_after_midnight_in_same_session_earns_daily_credit(self):
        self.study_questions(self.quiz_id,count=1,stamp='2026-10-15T15:00:00+00:00',prefix='overnight')
        with dlms.get_db() as conn:
            session=dict(conn.execute("SELECT * FROM study_sessions WHERE id='overnight'").fetchone())
        payload=dict(contract=2,quizId=self.quiz_id,sessionId='overnight',owner='overnight-owner',generation=session['generation'],assessmentRevision=session['assessment_revision'],
                     sequence=2,eventId='overnight-new-response',questionOrdinal=1,questionType='choice',wasCorrect=True,selected=['A'],kind='response')
        self.assertEqual(self.save(payload).status_code,200)
        with dlms.get_db() as conn:
            conn.execute("UPDATE learning_events SET occurred_at='2026-10-16T15:00:00+00:00' WHERE attempt_id='overnight-new-response'")
        pid=self.create()
        r=self.report(pid,datetime(2026,10,16,18,tzinfo=timezone.utc))
        self.assertEqual(r['stats']['today'],1)
        self.assertEqual(r['remaining_slots'],11)
        self.assertEqual(r['target'],0)

    def test_identical_text_does_not_collapse_curriculum_or_invent_coverage(self):
        second,_=self.publish(title='Independent identical source',questions=[self.choice()],kind=None)
        pid=self.create()
        self.assertEqual(self.report(pid)['stats']['total'],2)
        self.assertEqual(len(self.report(pid)['candidates']),2)
        # Legacy ranking can group text, but plans must still account for each row.
        with dlms.get_db() as conn:
            conn.execute('UPDATE questions SET question_uid=NULL,canonical_question_uid=NULL')
        r=self.report(pid)
        self.assertEqual(r['stats']['total'],2)
        self.assertEqual(len(r['candidates']),2)
        self.assertEqual(r['outstanding'],2)
        self.assertEqual(r['stats']['reviewed'],0)

    def test_database_reservation_serializes_without_process_local_lock(self):
        pid=self.create(); data=self.request_data(pid)
        barrier=threading.Barrier(2)
        def reserve():
            conn=dlms.get_db()
            try:
                barrier.wait(timeout=5)
                return plans.reserve_action(conn,pid,data)
            finally:
                conn.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _:reserve(),range(2)))
        self.assertEqual(sum(result is None for result in results),1)
        self.assertEqual(next(result['state'] for result in results if result),'pending')
        with dlms.get_db() as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM exam_plan_actions').fetchone()[0],1)

    def test_past_exam_does_not_remove_current_overdue_work(self):
        self.study_questions(self.quiz_id,count=1,stamp='2026-10-14T15:00:00+00:00',prefix='past-date')
        pid=self.create(exam_date='2026-10-14')
        r=self.report(pid,datetime(2026,10,16,18,tzinfo=timezone.utc))
        self.assertEqual(r['calendar']['days'],0)
        self.assertEqual(len(r['due']),1)
        self.assertEqual(r['outstanding'],1)
        self.assertGreater(r['shortfall'],0)
        self.assertEqual(r['selected'],[])

    def finish_session(self, quiz_id, session_id, sequence):
        with dlms.get_db() as conn:
            session = dict(conn.execute('SELECT * FROM study_sessions WHERE id=?', (session_id,)).fetchone())
        response = self.client.post('/api/study/finish', json=dict(
            quizId=quiz_id, sessionId=session_id, owner=session_id+'-owner',
            generation=session['generation'], assessmentRevision=session['assessment_revision'],
            sequence=sequence), headers=self.headers)
        self.assertEqual(response.status_code, 200, response.json)
        return response.json['session']

    def test_fifty_question_corrections_completion_and_focused_lineage(self):
        questions = [{**self.choice(), 'number': n, 'question': f'CISM review {n}'} for n in range(1,51)]
        qid, _ = self.publish(title='CISM whole review', questions=questions, kind=None)
        pid = self.create()
        sequence = self.study_questions(qid, count=50, wrong=range(1,26), prefix='fifty')
        self.assertEqual(sequence, 75)
        before = self.report(pid)
        self.assertEqual(before['stats']['reviewed'], 50)
        self.assertEqual(before['stats']['full'], 0)
        self.assertEqual(before['stats']['first_mistake'], 25)
        self.assertEqual(before['stats']['corrected'], 25)
        self.assertEqual(before['stats']['independent'], 25)
        finished = self.finish_session(qid, 'fifty', sequence)
        self.assertEqual(finished['reviewed'], 50)
        self.assertEqual(self.finish_session(qid, 'fifty', sequence)['completed_at'], finished['completed_at'])
        after = self.report(pid)
        self.assertEqual(after['stats']['full'], 1)
        self.assertEqual(len(after['missed']), 25)
        data = self.request_data(pid); data.update(mode='missed', count=10)
        response = self.client.post(f'/api/exam-plans/{pid}/generate', json=data, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.json)
        with dlms.get_db() as conn:
            generated = conn.execute('SELECT quiz_id FROM exam_plan_actions').fetchone()[0]
            source_ids = {r[0] for r in conn.execute('SELECT source_question_uid FROM questions WHERE quiz_id=?', (generated,))}
            missed_ids = {r[0] for r in conn.execute('SELECT question_uid FROM questions WHERE quiz_id=? AND question_number<=25', (qid,))}
            self.assertEqual(len(source_ids), 10)
            self.assertTrue(source_ids <= missed_ids)
        self.study_questions(generated, count=10, prefix='focused-fifty')
        self.finish_session(generated, 'focused-fifty', 10)
        after = self.report(pid)
        self.assertEqual(after['stats']['reviewed'], 50)
        self.assertEqual(after['stats']['full'], 1)
        self.assertEqual(after['stats']['focused'], 1)
        self.assertEqual(len(after['missed']), 25)
        with dlms.get_db() as conn:
            continuity = dlms._study_service.regular_continuity(conn.cursor(), dlms.load_registry(),
                data_folder=dlms.DATA_FOLDER, quiz_folder=dlms.QUIZ_FOLDER, artifact_names=dlms._quiz_artifact_names)
            self.assertEqual(continuity['quiz_id'], qid)
            self.assertEqual(continuity['completed_at'], finished['completed_at'])

    def test_deadline_comparison_overlap_and_generation_has_no_credit(self):
        questions = [{**self.choice(), 'number': n, 'question': f'Deadline {n}'} for n in range(1,80)]
        qid, _ = self.publish(title='Deadline bank', questions=questions, kind=None)
        now = datetime(2026,10,16,18,tzinfo=timezone.utc)
        far = self.create(); near = self.create(exam_date='2026-10-20')
        distant, imminent = self.report(far,now), self.report(near,now)
        self.assertEqual((distant['calendar']['days'], distant['target'], distant['shortfall']), (6,14,20))
        self.assertEqual((imminent['calendar']['days'], imminent['target'], imminent['shortfall']), (2,40,140))
        self.assertEqual(len(distant['selected']), 12)
        self.assertEqual(len(imminent['selected']), 12)
        self.study_questions(qid,count=5,wrong=(1,),prefix='deadline-today')
        after = self.report(near,now)
        self.assertEqual((after['target'],after['remaining_slots']), (35,7))
        self.assertEqual(after['stats']['today'],5)
        data = self.request_data(near)
        self.assertEqual(self.client.post(f'/api/exam-plans/{near}/generate', json=data, headers=self.headers).status_code,200)
        repeated = self.report(near,now)
        self.assertEqual((repeated['target'],repeated['remaining_slots'],repeated['stats']['today']), (35,7,5))
        # Yesterday's mistakes are also overdue; each source occupies only one slot.
        self.study_questions(qid,count=10,wrong=range(1,11),stamp='2026-10-14T15:00:00+00:00',prefix='deadline-overdue')
        overlap = self.report(far,now)
        self.assertTrue(set(overlap['missed']) & set(overlap['due']))
        self.assertEqual(len(overlap['selected']),len({c['question_id'] for c in overlap['selected']}))

    def test_suggested_publication_preserves_coverage_lane_when_count_shrinks(self):
        questions = [{**self.choice(), 'number': n, 'question': f'Priority {n}'} for n in range(1,21)]
        qid, _ = self.publish(title='Prior mistakes',questions=questions,kind=None)
        self.study_questions(qid,count=20,wrong=range(1,21),stamp='2026-10-14T15:00:00+00:00',prefix='priority')
        pid = self.create()
        report = self.report(pid,datetime(2026,10,16,18,tzinfo=timezone.utc))
        self.assertEqual(report['target'],1)
        self.assertEqual(report['selected'][0]['quiz_id'],self.quiz_id)
        data = self.request_data(pid); data.update(mode='suggested',count=1,fingerprint=report['fingerprint'])
        with mock.patch.object(plans,'summary',return_value=report):
            response = self.client.post(f'/api/exam-plans/{pid}/generate',json=data,headers=self.headers)
        self.assertEqual(response.status_code,200,response.json)
        with dlms.get_db() as conn:
            source = conn.execute('SELECT source_question_uid FROM questions WHERE is_generated_copy=1').fetchone()[0]
            expected = conn.execute('SELECT question_uid FROM questions WHERE quiz_id=?',(self.quiz_id,)).fetchone()[0]
            self.assertEqual(source,expected)

    def test_interrupted_publication_reconciliation_and_explicit_new_work(self):
        class Interrupted(BaseException):
            pass
        for stage in ('db_committed', 'registry_published'):
            with self.subTest(stage=stage):
                pid = self.create(name=stage)
                data = self.request_data(pid); data['request_id'] = 'interrupted-plan-'+stage
                url = f'/api/exam-plans/{pid}/generate'
                def interrupt(current, _journal):
                    if current == stage:
                        raise Interrupted()
                with mock.patch.object(dlms,'_quiz_publication_checkpoint',side_effect=interrupt):
                    with self.assertRaises(Interrupted):
                        self.client.post(url,json=data,headers=self.headers)
                # No blind duplicate is created while publication is uncertain.
                before = len(dlms.load_registry())
                pending = self.client.post(url,json=data,headers=self.headers)
                self.assertEqual(pending.status_code, 200 if stage=='registry_published' else 409)
                self.assertEqual(len(dlms.load_registry()),before)
                dlms.reconcile_quiz_publications()  # Disposable app's normal startup recovery only.
                recovered = self.client.post(url,json=data,headers=self.headers)
                if stage == 'registry_published':
                    self.assertEqual(recovered.status_code,200,recovered.json)
                    self.assertTrue(recovered.json['replayed'])
                else:
                    self.assertEqual(recovered.status_code,409,recovered.json)
                    self.assertIn('explicitly start new work',recovered.json['error'])
                    with dlms.get_db() as conn:
                        record = conn.execute('SELECT * FROM exam_plan_actions WHERE request_id=?',(data['request_id'],)).fetchone()
                        self.assertIsNone(record['quiz_id'])
                    # Only an explicit new operation after verified recovery publishes.
                    data['request_id'] += '-new'
                    self.assertEqual(self.client.post(url,json=data,headers=self.headers).status_code,200)

    def test_schema_five_failure_is_atomic_and_retry_preserves_study(self):
        self.save(self.payload(1,correct=False)); self.finish(1)
        with dlms.get_db() as conn:
            for table in ('exam_plan_actions','exam_plan_state','exam_plans'):
                conn.execute('DROP TABLE '+table)
            conn.execute('UPDATE schema_meta SET version=4')
        def failed_migration(conn):
            exam_plan_schema.migrate(conn)
            conn.execute("UPDATE quizzes SET title='Must roll back'")
            raise RuntimeError('Injected schema-five failure')
        with mock.patch.dict(dlms.DLMS_SCHEMA_MIGRATIONS,{5:failed_migration}):
            with self.assertRaisesRegex(RuntimeError,'schema-five failure'):
                dlms.bootstrap_database(dlms.DB_PATH)
        with sqlite3.connect(dlms.DB_PATH) as conn:
            self.assertEqual(conn.execute('SELECT version FROM schema_meta').fetchone()[0],4)
            self.assertIsNone(conn.execute("SELECT name FROM sqlite_master WHERE name='exam_plans'").fetchone())
            self.assertNotEqual(conn.execute('SELECT title FROM quizzes').fetchone()[0],'Must roll back')
            self.assertEqual(conn.execute('SELECT count(*) FROM study_sessions WHERE completed_at IS NOT NULL').fetchone()[0],1)
        dlms.bootstrap_database(dlms.DB_PATH)
        with dlms.get_db() as conn:
            self.assertEqual(conn.execute('SELECT version FROM schema_meta').fetchone()[0],5)
            self.assertEqual(conn.execute('SELECT count(*) FROM study_responses').fetchone()[0],1)

    def test_plan_midnight_credit_and_dst_calendar_days(self):
        pid = self.create(exam_date='2026-11-04',weekdays=list(range(7)))
        self.study_questions(self.quiz_id,count=1,stamp='2026-11-01T04:59:00Z',prefix='before-midnight')
        before = self.report(pid,datetime(2026,11,1,4,59,30,tzinfo=timezone.utc))
        midnight = self.report(pid,datetime(2026,11,1,5,tzinfo=timezone.utc))
        self.assertEqual((before['calendar']['today'],before['stats']['today']),('2026-10-31',1))
        self.assertEqual((midnight['calendar']['today'],midnight['stats']['today']),('2026-11-01',0))
        self.study_questions(self.quiz_id,count=1,stamp='2026-11-01T06:30:00Z',prefix='fall-first-hour')
        self.study_questions(self.quiz_id,count=1,stamp='2026-11-01T07:30:00Z',prefix='fall-second-hour')
        repeated = self.report(pid,datetime(2026,11,1,8,tzinfo=timezone.utc))
        self.assertEqual((repeated['calendar']['days'],repeated['stats']['today']), (3,1))
        self.assertEqual(repeated['remaining_slots'],11)
        for exam, now, days in (
            ('2026-03-10','2026-03-08T06:00:00+00:00',2),
            ('2026-11-03','2026-11-01T05:00:00+00:00',2),
        ):
            with self.subTest(exam=exam):
                result = plans.calendar(self.config(exam_date=exam,weekdays=list(range(7))),datetime.fromisoformat(now))
                self.assertEqual((result['days'],result['potential_minutes']), (days,days*30))

    def test_malformed_generation_inputs_do_not_reserve_or_publish(self):
        pid = self.create(); data = self.request_data(pid)
        for change in ({'mode':[]}, {'request_id':{}}, {'request_id':'short'}, {'count':True}):
            with self.subTest(change=change):
                response = self.client.post(f'/api/exam-plans/{pid}/generate',json={**data,**change},headers=self.headers)
                self.assertEqual(response.status_code,400,response.json)
        with dlms.get_db() as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM exam_plan_actions').fetchone()[0],0)
            self.assertEqual(conn.execute('SELECT count(*) FROM quizzes').fetchone()[0],1)

    def test_optional_extra_work_cannot_consume_future_calendar_capacity(self):
        questions = [{**self.choice(),'number':n,'question':f'Extra study {n}'} for n in range(1,51)]
        qid, _ = self.publish(title='Long regular review',questions=questions,kind=None)
        pid = self.create()
        self.study_questions(qid,count=50,prefix='extra-work')
        result = self.report(pid,datetime(2026,10,16,18,tzinfo=timezone.utc))
        self.assertEqual(result['stats']['today'],50)
        self.assertEqual(result['remaining_slots'],0)
        self.assertEqual(result['selected'],[])
        # Six 30-minute dates included today. Extra practice does not borrow
        # from the five future dates or pretend to measure actual duration.
        self.assertEqual(result['capacity'],150)

    def test_flat_folder_remap_exclusion_and_source_deletion(self):
        registry = dlms.load_registry(); registry[0]['folder']='CISM'; dlms.save_registry(registry)
        with dlms.get_db() as conn:
            config = self.config(folders=['cism'])
            opts = dlms._exam_plan_options(conn.cursor())
            snapshot = plans.summary(conn.cursor(),dict(config=config,revision=0,snapshot={}),**opts)['snapshot']
            pid = plans.save(conn,config,generation=plans.state(conn.cursor())['generation'],known_folders=['cism'],snapshot=snapshot)
        before = self.request_data(pid)
        registry[0]['folder']='CISM renamed'; dlms.save_registry(registry)
        report = self.report(pid)
        self.assertEqual(report['missing_folders'],['cism'])
        self.assertEqual(report['stats']['total'],0)
        self.assertEqual(self.client.post(f'/api/exam-plans/{pid}/generate',json=before,headers=self.headers).status_code,409)
        with dlms.get_db() as conn:
            plans.save(conn,self.config(folders=['cism renamed']),plan_id=pid,revision=1,generation=report['generation'],known_folders=['cism renamed'])
        remapped = self.report(pid)
        self.assertEqual(remapped['stats']['total'],1)
        self.assertTrue(remapped['changes']['changed'])
        with dlms.get_db() as conn:
            opts = dlms._exam_plan_options(conn.cursor()); opts['excluded']=['cism renamed']
            excluded = plans.summary(conn.cursor(),plans.get(conn.cursor(),pid),**opts)
            self.assertNotEqual(excluded['fingerprint'],remapped['fingerprint'])
            self.assertEqual((excluded['stats']['blocked'],excluded['stats']['eligible']),(1,0))
            conn.execute('DELETE FROM quizzes WHERE id=?',(self.quiz_id,))
        dlms.save_registry([])
        deleted = self.report(pid)
        self.assertEqual(deleted['stats']['total'],0)
        self.assertTrue(deleted['changes']['removed'])

    def form_values(self, pid=None, **changes):
        with dlms.get_db() as conn:
            plan = plans.get(conn.cursor(),pid) if pid else None
            config = dict(plan['config']) if plan else self.config()
            data = {**config, 'generation':plans.state(conn.cursor())['generation'],
                    'revision':plan['revision'] if plan else 0,'dashboard_token':plans.dashboard_selection(conn.cursor())}
        data.pop('visible',None)
        if data.pop('paused'): data['paused']='on'
        data.update(changes)
        return data

    def test_dashboard_choice_is_positive_atomic_and_preserves_pause(self):
        first = self.create(); second = self.create(name='Second',paused=True)
        with dlms.get_db() as conn:
            generation=plans.state(conn.cursor())['generation']
            plans.control(conn,second,'hide',1,generation)
        ordinary=self.form_values(second,name='Second edited')
        self.assertEqual(self.client.post(f'/exam-plans/{second}/edit',data=ordinary,headers=self.headers).status_code,302)
        with dlms.get_db() as conn:
            self.assertEqual(plans.state(conn.cursor())['active_plan_id'],second)
            self.assertFalse(plans.get(conn.cursor(),second)['config']['visible'])
            self.assertTrue(plans.get(conn.cursor(),second)['config']['paused'])
        stale=self.form_values(first,use_dashboard='on')
        show=self.form_values(second,use_dashboard='on')
        self.assertEqual(self.client.post(f'/exam-plans/{second}/edit',data=show,headers=self.headers).status_code,302)
        self.assertEqual(self.client.post(f'/exam-plans/{first}/edit',data=stale,headers=self.headers).status_code,409)
        with dlms.get_db() as conn:
            self.assertEqual(plans.state(conn.cursor())['active_plan_id'],second)
            self.assertTrue(plans.get(conn.cursor(),second)['config']['visible'])
            self.assertTrue(plans.get(conn.cursor(),second)['config']['paused'])
        # An unchecked new plan does not replace it; nor does editing another plan.
        self.assertEqual(self.client.post('/exam-plans/new',data=self.form_values(name='Unselected'),headers=self.headers).status_code,302)
        self.assertEqual(self.client.post(f'/exam-plans/{first}/edit',data=self.form_values(first,name='First edited'),headers=self.headers).status_code,302)
        dlms.bootstrap_database(dlms.DB_PATH)
        with dlms.get_db() as conn:
            self.assertEqual(plans.state(conn.cursor())['active_plan_id'],second)
            self.assertEqual(conn.execute('SELECT count(*) FROM exam_plans').fetchone()[0],3)
        html=self.client.get('/exam-plans/'+second).get_data(as_text=True)
        self.assertIn('On dashboard',html)
        self.assertNotIn('value="activate"',html)
        self.assertNotIn('name="visible"',self.client.get('/exam-plans/'+second+'/edit').get_data(as_text=True))

    def test_concurrent_dashboard_switches_and_aba_conflict(self):
        first=self.create(); second=self.create(name='Second'); third=self.create(name='Third')
        with dlms.get_db() as conn:
            token=plans.dashboard_selection(conn.cursor()); generation=plans.state(conn.cursor())['generation']
        barrier=threading.Barrier(2)
        def choose(pid):
            client=dlms.app.test_client(); headers=csrf_headers(client); barrier.wait(timeout=5)
            return client.post(f'/exam-plans/{pid}/action',data=dict(action='activate',revision=1,generation=generation,dashboard_token=token),headers=headers).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            result=list(pool.map(choose,(first,second)))
        self.assertEqual(sorted(result),[302,409])
        with dlms.get_db() as conn:
            active=plans.state(conn.cursor())['active_plan_id']
            original=plans.dashboard_selection(conn.cursor())
            revision=plans.get(conn.cursor(),active)['revision']
            plans.control(conn,third,'activate',1,generation,expected_dashboard=original)
            plans.control(conn,active,'activate',revision,generation,expected_dashboard=plans.dashboard_selection(conn.cursor()))
            with self.assertRaises(plans.PlanConflict):
                plans.control(conn,third,'activate',2,generation,expected_dashboard=original)
            conn.rollback()
            self.assertEqual(plans.state(conn.cursor())['active_plan_id'],active)

    def test_four_future_reviews_are_workload_not_an_exhausted_allowance(self):
        other,_=self.publish(title='Three more',questions=[{**self.choice(),'number':n,'question':f'Future {n}'} for n in range(1,4)],kind=None)
        self.study_questions(self.quiz_id,count=1,prefix='future-one')
        self.study_questions(other,count=3,prefix='future-three')
        pid=self.create()
        result=self.report(pid,datetime(2026,10,16,18,tzinfo=timezone.utc))
        self.assertEqual((result['outstanding'],result['workload'],result['remaining_slots']),(4,10,8))
        self.assertEqual(result['selected'],[])
        self.assertEqual(result['work_state']['code'],'future_reviews')
        self.assertEqual(result['work_state']['next_review_date'],'2026-10-17')
        self.assertEqual(result['work_state']['next_study_date'],'2026-10-19')

    def test_next_study_date_does_not_wait_for_a_later_review_interval(self):
        self.study_questions(self.quiz_id,count=1,stamp='2026-10-14T15:00:00+00:00',prefix='interval-first')
        self.study_questions(self.quiz_id,count=1,prefix='interval-second')
        pid=self.create(weekdays=list(range(7)))
        result=self.report(pid,datetime(2026,10,16,18,tzinfo=timezone.utc))
        self.assertEqual(result['work_state']['code'],'future_reviews')
        self.assertEqual(result['work_state']['next_review_date'],'2026-10-19')
        self.assertEqual(result['work_state']['next_study_date'],'2026-10-17')

    def test_work_state_precedence_empty_excluded_unavailable_and_calendar(self):
        extra=[{**self.choice(),'number':n,'question':f'Excluded {n}'} for n in range(1,139)]
        self.publish(title='Excluded bank',questions=extra,kind=None)
        pid=self.create()
        now=datetime(2026,10,16,18,tzinfo=timezone.utc)
        with dlms.get_db() as conn:
            opts=dlms._exam_plan_options(conn.cursor()); plan=plans.get(conn.cursor(),pid)
            all_excluded=plans.summary(conn.cursor(),plan,**{**opts,'excluded':['uncategorized']},now=now)
            self.assertEqual(all_excluded['work_state']['code'],'excluded')
            self.assertIn('139 questions',all_excluded['work_state']['reason'])
            self.assertFalse(all_excluded['estimate_available'])
            self.assertNotIn('Known work fits',all_excluded['fit'])
            cases=[({'folders':['gone']},'no_material'),({'exam_date':'2026-10-16','paused':True},'exam_today'),
                   ({'exam_date':'2026-10-15'},'exam_passed'),({'paused':True},'paused'),
                   ({'weekdays':[1]},'non_study_day'),({'weekdays':[1],'exam_date':'2026-10-17'},'no_dates'),
                   ({'minutes':1},'budget_too_small'),({},'ready')]
            for changes,code in cases:
                with self.subTest(code=code):
                    changed={**plan,'config':{**plan['config'],**changes}}
                    result=plans.summary(conn.cursor(),changed,**opts,now=now)
                    self.assertEqual(result['work_state']['code'],code)
            unavailable=plans.summary(conn.cursor(),plan,**{**opts,'media_available':lambda value:False},now=now)
            self.assertEqual(unavailable['work_state']['code'],'unavailable')
            self.assertFalse(unavailable['work_state']['optional_practice'])
        with mock.patch.object(dlms,'get_excluded_learning_folders',return_value=['uncategorized']):
            html=self.client.get('/exam-plans/'+pid).get_data(as_text=True)
            self.assertIn('139 questions are excluded',html)
            self.assertNotIn('Known work fits',html)
            self.assertNotIn('data-practice="suggested"',html)
            self.assertNotIn('id="other-practice"',html)

    def test_panel_notice_and_failed_selection_preserve_settings(self):
        pid=self.create()
        cfg=dlms.load_portal_config(); cfg['dashboard_card_visibility']['daily_review']=False
        dlms._write_settings_portal_config(cfg)
        html=self.client.get('/exam-plans/'+pid).get_data(as_text=True)
        self.assertIn('/settings/layout#dashboard-panels',html)
        self.assertNotIn('value="acknowledge"',html)
        values=self.form_values(name='Must not switch',use_dashboard='on')
        with dlms.get_db() as conn:
            conn.execute("CREATE TRIGGER fail_dashboard BEFORE UPDATE ON exam_plan_state BEGIN SELECT RAISE(ABORT,'fixture failure'); END")
        response=self.client.post('/exam-plans/new',data=values,headers=self.headers)
        self.assertEqual(response.status_code,503)
        with dlms.get_db() as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM exam_plans').fetchone()[0],1)
            self.assertEqual(plans.state(conn.cursor())['active_plan_id'],pid)
        self.assertEqual(dlms.load_portal_config(),cfg)

    def test_dashboard_token_describes_the_displayed_selection(self):
        first=self.create()
        with dlms.get_db() as conn:
            shown_state=plans.state(conn.cursor())
            shown_plan=plans.get(conn.cursor(),first)
            original=plans.dashboard_selection(conn.cursor())
        second=self.create(name='Replacement')
        with dlms.get_db() as conn:
            rendered=plans.dashboard_selection(conn.cursor(),saved=shown_state,selected=shown_plan)
            self.assertEqual(rendered,original)
            self.assertNotEqual(rendered,plans.dashboard_selection(conn.cursor()))
            with self.assertRaises(plans.PlanConflict):
                plans.control(conn,first,'activate',1,shown_state['generation'],expected_dashboard=rendered)
            conn.rollback()
            self.assertEqual(plans.state(conn.cursor())['active_plan_id'],second)

    def test_selected_breakdown_is_exclusive_and_does_not_rank(self):
        selected=[{'question_id':n} for n in range(1,7)]
        before=copy.deepcopy(selected)
        result=plans.selected_breakdown(selected,needs={1,2},recorded={2,3,4,5,6},missed={2,3,4},due={1,3,4,5})
        self.assertEqual({r['key']:r['count'] for r in result},{'new':1,'refresh':1,'mistakes':2,'due':1,'other':1})
        self.assertEqual(sum(r['count'] for r in result),len(selected))
        self.assertEqual(selected,before)

    def test_included_coverage_keeps_unavailable_and_separates_excluded(self):
        available,_=self.publish(title='Included bank',questions=[{**self.choice(),'number':n,'question':f'Included {n}'} for n in range(1,4)],kind=None)
        blocked,_=self.publish(title='Excluded bank',questions=[{**self.choice(),'number':n,'question':f'Excluded {n}'} for n in range(1,140)],kind=None)
        registry=dlms.load_registry()
        for entry in registry:
            if entry['id']==blocked:entry['folder']='Excluded'
        dlms.save_registry(registry)
        self.study_questions(self.quiz_id,count=1,prefix='coverage-one')
        self.study_questions(available,count=3,prefix='coverage-three')
        pid=self.create()
        with dlms.get_db() as conn:
            plan=plans.get(conn.cursor(),pid);plan['config']['folders']=['uncategorized','excluded']
            opts=dlms._exam_plan_options(conn.cursor())
            result=plans.summary(conn.cursor(),plan,**{**opts,'excluded':['excluded']},now=datetime(2026,10,17,18,tzinfo=timezone.utc))
            self.assertEqual((result['stats']['total'],result['stats']['included'],result['stats']['included_reviewed'],result['stats']['blocked']),(143,4,4,139))
            missing=plans.summary(conn.cursor(),plan,**{**opts,'excluded':['excluded'],'media_available':lambda value:False},now=datetime(2026,10,17,18,tzinfo=timezone.utc))
            self.assertEqual((missing['stats']['included'],missing['stats']['included_reviewed'],missing['stats']['unavailable']),(4,4,4))
            self.assertEqual(missing['selected'],[])

    def test_reset_breakdown_uses_facts_only_for_labels_and_keeps_selection(self):
        now=datetime(2026,10,19,18,tzinfo=timezone.utc)
        self.publish(title='New material',kind=None)
        self.study_questions(self.quiz_id,count=1,wrong=(1,),prefix='known-mistake')
        pid=self.create()
        before=self.report(pid,now)
        self.assertEqual(sum(r['count'] for r in before['breakdown']),len(before['selected']))
        restore.reset_learning_intelligence_core(dlms.DB_PATH)
        report=self.report(pid,now)
        self.assertEqual({r['key']:r['count'] for r in report['breakdown']},{'new':1,'refresh':1})
        self.assertEqual(report['stats']['included_reviewed'],1)
        self.assertEqual(report['missed'],[]);self.assertEqual(report['due'],[])
        # Presentation annotations cannot change candidate ranking, budget or scheduling.
        with mock.patch.object(plans,'selected_breakdown',return_value=[]):
            without=self.report(pid,now)
        for key in ('selected','target','remaining_slots','capacity','workload','shortfall','stats','fingerprint'):
            self.assertEqual(report[key],without[key],key)

    def test_shortfall_headline_rounding_and_zero(self):
        self.publish(title='Risk bank',questions=[{**self.choice(),'number':n,'question':f'Risk {n}'} for n in range(1,99)],kind=None)
        pid=self.create(exam_date='2026-10-17',weekdays=list(range(7)))
        result=self.report(pid,datetime(2026,10,16,18,tzinfo=timezone.utc))
        self.assertEqual(result['shortfall'],217.5)
        self.assertEqual(result['shortfall_rounded'],220)
        self.assertTrue(result['selected'])
        other=self.create(minutes=1440,weekdays=list(range(7)))
        self.assertEqual(self.report(other,datetime(2026,10,16,18,tzinfo=timezone.utc))['shortfall_rounded'],0)

    def test_breakdown_historical_lineage_does_not_merge_identical_sources(self):
        pid=self.create()
        published=self.client.post(f'/api/exam-plans/{pid}/generate',json=self.request_data(pid),headers=self.headers)
        self.assertEqual(published.status_code,200)
        with dlms.get_db() as conn:
            generated=conn.execute('SELECT id FROM quizzes WHERE generation_kind=\'adaptive_study\'').fetchone()[0]
        other,_=self.publish(title='Independent identical wording',kind=None)
        self.study_questions(generated,count=1,wrong=(1,),prefix='lineage-label')
        restore.reset_learning_intelligence_core(dlms.DB_PATH)
        report=self.report(pid,datetime(2026,10,19,18,tzinfo=timezone.utc))
        self.assertEqual({item['key']:item['count'] for item in report['breakdown']},{'new':1,'refresh':1})
        self.assertEqual(report['missed'],[])
        with dlms.get_db() as conn:
            recorded=plans.recorded_answer_sources(conn.cursor(),report['snapshot'])
            source=conn.execute('SELECT id FROM questions WHERE quiz_id=?',(self.quiz_id,)).fetchone()[0]
            independent=conn.execute('SELECT id FROM questions WHERE quiz_id=?',(other,)).fetchone()[0]
        self.assertIn(source,recorded);self.assertNotIn(independent,recorded)
