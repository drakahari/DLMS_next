"""Disposable factual-selection, fidelity and publication regressions."""
import json
import sqlite3
import threading
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

from tests._isolation import ensure_test_data_isolation
ensure_test_data_isolation()
import app as dlms
from tests import test_study_sessions as fixtures
from dlms.services import study_mistakes as sm, study_sessions as study, restore, learning
from dlms.persistence import study_mistake_schema as schema


class StudyMistakeTests(unittest.TestCase):
    setUp = fixtures.StudySessionTests.setUp
    choice = staticmethod(fixtures.StudySessionTests.choice)
    matching = staticmethod(fixtures.StudySessionTests.matching)
    publish = fixtures.StudySessionTests.publish
    fingerprint = fixtures.StudySessionTests.fingerprint
    payload = fixtures.StudySessionTests.payload
    save = fixtures.StudySessionTests.save
    finish = fixtures.StudySessionTests.finish

    def selection(self, quizzes=None, folders=None):
        return sm.scope(folders or [], quizzes if quizzes is not None else [self.quiz_id])

    def pool(self, scope=None):
        with dlms.get_db() as conn:
            return sm.pool(conn.cursor(), scope or self.selection(), dlms._study_mistake_options())

    def wrong(self):
        response = self.save(self.payload(1, correct=False))
        self.assertEqual(response.status_code, 200, response.json)

    def pass_data(self, scope=None):
        selection = scope or self.selection()
        with dlms.get_db() as conn:
            current = sm.pool(conn.cursor(), selection, dlms._study_mistake_options())
            report = sm.pass_report(conn.cursor(), selection, current)
            return dict(scope=selection, generation=sm.state(conn.cursor()), fingerprint=current['fingerprint'], expected_pass=report['id'] if report else None)

    def start(self, scope=None):
        response = self.client.post('/api/quiz-composer/study-mistakes/pass', json=self.pass_data(scope), headers=self.headers)
        self.assertEqual(response.status_code, 200, response.json)
        return response.json['pass_id']

    def create_data(self, pid=None, *, mode='without-repeats', count=1, scope=None):
        data = self.pass_data(scope)
        data.pop('expected_pass')
        return dict(**data, request_id=uuid.uuid4().hex, title='Saved mistakes mix', mode=mode, count=count, pass_id=pid)

    def create(self, data):
        return self.client.post('/api/quiz-composer/study-mistakes/create', json=data, headers=self.headers)

    def report(self, scope=None):
        with dlms.get_db() as conn:
            return sm.pass_report(conn.cursor(), scope or self.selection(), self.pool(scope))

    def claim_quiz(self, qid, *, sid=None, variants=None):
        sid = sid or uuid.uuid4().hex
        claim = dict(self.claim_data, quizId=qid, sessionId=sid, fingerprint=self.fingerprint(qid), variants=variants or {}, answerEncoding='choice-labels-v1')
        response = self.client.post('/api/study/session', json=claim, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.json)
        return dict(self.payload(1, correct=False), quizId=qid, sessionId=sid, eventId=uuid.uuid4().hex,
                    assessmentRevision=response.json['session']['assessment_revision'], answerEncoding='choice-labels-v1')

    def test_any_wrong_unfinished_corrected_and_later_success(self):
        self.wrong()
        self.save(self.payload(2))
        self.assertEqual(len(self.pool()['eligible']), 1)
        later = self.claim_quiz(self.quiz_id)
        self.assertEqual(self.save(dict(later, wasCorrect=True, selected=['A'])).status_code, 200)
        self.assertEqual(len(self.pool()['eligible']), 1)
        with dlms.get_db() as conn:
            self.assertIsNone(conn.execute("SELECT completed_at FROM study_sessions WHERE id='session-one'").fetchone()[0])

    def test_correct_then_wrong_is_not_first_outcome_projection(self):
        self.save(self.payload(1)); self.save(self.payload(2, correct=False))
        with dlms.get_db() as conn:
            self.assertEqual(learning._deduplicated_learning_answer_events(conn.cursor())[0]['was_correct'], 1)
        self.assertEqual(len(self.pool()['eligible']), 1)

    def test_assistance_and_replayed_answers_and_gaps(self):
        action = self.payload(1, correct=None, kind='ai_open'); action['selected'] = None
        self.assertEqual(self.save(action).status_code, 200)
        self.assertEqual(self.pool()['recorded'], 0)
        wrong = self.payload(3, correct=False)
        self.save(wrong); self.save(wrong)
        self.assertEqual(len(self.pool()['eligible']), 1)
        with dlms.get_db() as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM study_responses').fetchone()[0], 2)

    def test_unanswered_and_legacy_do_not_invent_revisions(self):
        self.save(self.payload(1, correct=False, selected=[]))
        self.assertEqual(self.pool()['recorded'], 0)
        with dlms.get_db() as conn:
            qid = conn.execute('SELECT id FROM questions WHERE quiz_id=?', (self.quiz_id,)).fetchone()[0]
            conn.execute("INSERT INTO study_legacy_responses(quiz_id,question_id,mode,was_correct,response_json) VALUES(?,?,'Study',0,?)", (self.quiz_id, qid, json.dumps({'selected': ['C']})))
        self.assertEqual(self.pool()['eligible'], [])
        self.assertIn('Legacy', self.pool()['unavailable'][0]['reason'])

    def test_incomplete_multi_and_matching_are_not_mistakes(self):
        for question, selected, variants in (
            (self.choice(multi=True), ['C'], {}),
            (self.matching(), {'0': 1}, {'0': {'sourcePairIndexes': [0, 1], 'direction': 'term_to_definition'}}),
        ):
            qid, _ = self.publish(kind=None, questions=[question])
            event = self.claim_quiz(qid, variants=variants)
            event.update(questionType=question['type'], selected=selected, wasCorrect=None)
            self.assertEqual(self.save(event).status_code, 200)
            self.assertEqual(self.pool(self.selection([qid]))['recorded'], 0)

    def test_source_edit_excludes_and_retains_fact(self):
        self.wrong()
        with dlms.get_db() as conn:
            conn.execute("UPDATE choices SET text='Changed' WHERE label='A'")
        self.assertEqual(self.pool()['eligible'], [])
        self.assertIn('changed', self.pool()['unavailable'][0]['reason'])
        with dlms.get_db() as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM study_responses').fetchone()[0], 1)

    def test_generated_lineage_not_prompt_collapse(self):
        second, _ = self.publish(title='Independent same prompt', kind=None)
        with dlms.get_db() as conn:
            source_q = conn.execute('SELECT id FROM questions WHERE quiz_id=?', (self.quiz_id,)).fetchone()[0]
            payload = learning._question_payload_from_db(conn.cursor(), source_q)
            payload['composition_sources'] = [{'quiz_id': self.quiz_id}]
        generated, _ = dlms._publish_quiz('Explicit mix', [payload], generation_kind='mixed_quiz', filename_prefix='mixed_quiz')
        self.save(self.claim_quiz(generated))
        scope = self.selection([self.quiz_id, second])
        self.assertEqual([source_q], [q['question_id'] for q in self.pool(scope)['eligible']])
        self.save(self.claim_quiz(second))
        self.assertEqual(len(self.pool(scope)['eligible']), 2)
        with dlms.get_db() as conn:
            conn.execute("UPDATE questions SET question_text='Edited original' WHERE id=?", (source_q,))
        self.assertEqual(len(self.pool(scope)['eligible']), 1)
        self.assertIn('Generated copy', self.pool(scope)['unavailable'][0]['reason'])

    def test_orphan_generated_cannot_supply_source(self):
        qid, _ = self.publish(title='Orphan')
        self.save(self.claim_quiz(qid))
        self.assertEqual(self.pool()['recorded'], 0)

    def test_union_overlap_hidden_and_excluded_manual_selection(self):
        self.wrong()
        registry = dlms.load_registry(); registry[0]['hidden'] = True; dlms.save_registry(registry)
        selection = self.selection([self.quiz_id], ['Uncategorized'])
        self.assertEqual(len(self.pool(selection)['eligible']), 1)
        with mock.patch.object(dlms, 'get_learning_excluded_folders', return_value=['Uncategorized'], create=True):
            self.assertEqual(len(self.pool(selection)['eligible']), 1)

    def test_single_source_single_question_fidelity_and_idempotency(self):
        self.wrong()
        with dlms.get_db() as conn:
            before = {t: [tuple(r) for r in conn.execute('SELECT * FROM ' + t)] for t in ('questions','choices','study_responses','learning_events')}
        pid = self.start(); data = self.create_data(pid)
        result = self.create(data)
        self.assertEqual(result.status_code, 200, result.json)
        self.assertEqual(self.create(data).json['url'], result.json['url'])
        self.assertEqual(self.report()['used'], 1)
        self.assertEqual(self.report()['remaining'], 0)
        self.assertEqual(self.create(dict(data, title='Changed inputs')).status_code, 409)
        with dlms.get_db() as conn:
            for table, original in before.items():
                after = [tuple(r) for r in conn.execute('SELECT * FROM ' + table)]
                self.assertEqual(after[:len(original)], original)
            created = conn.execute("SELECT id FROM quizzes WHERE generation_kind='mixed_quiz'").fetchone()[0]
            original = conn.execute('SELECT id FROM questions WHERE quiz_id=?', (self.quiz_id,)).fetchone()[0]
            copy = conn.execute('SELECT id FROM questions WHERE quiz_id=?', (created,)).fetchone()[0]
            a, b = learning._question_payload_from_db(conn.cursor(), original), learning._question_payload_from_db(conn.cursor(), copy)
            a.pop('_lineage'); b.pop('_lineage')
            self.assertEqual(a, b)
        # One-question Study really completes, rather than bypassing validation.
        event = self.claim_quiz(created)
        self.assertEqual(self.save(event).status_code, 200)
        finish = self.client.post('/api/study/finish', json=event, headers=self.headers)
        self.assertEqual(finish.status_code, 200, finish.json)
        self.assertIsNotNone(finish.json['session']['completed_at'])

    def test_random_leaves_pass_and_exhaustion_new_pass_explicit(self):
        self.wrong(); pid = self.start()
        random_data = self.create_data(mode='random')
        self.assertEqual(self.create(random_data).status_code, 200)
        self.assertEqual(self.create(random_data).status_code, 200)
        self.assertEqual(self.report()['remaining'], 1)
        self.assertEqual(self.create(self.create_data(pid)).status_code, 200)
        self.assertEqual(self.create(self.create_data(pid)).status_code, 409)
        self.assertEqual(self.report()['used'], 1)
        new = self.start()
        self.assertNotEqual(pid, new)
        self.assertEqual(self.report()['remaining'], 1)

    def test_shortage_does_not_consume_and_deleted_output_stays_used(self):
        self.wrong(); pid = self.start()
        self.assertEqual(self.create(self.create_data(pid, count=2)).status_code, 409)
        self.assertEqual(self.report()['remaining'], 1)
        result = self.create(self.create_data(pid)); self.assertEqual(result.status_code, 200)
        with dlms.get_db() as conn:
            conn.execute("DELETE FROM quizzes WHERE generation_kind='mixed_quiz'")
        self.assertEqual(self.report()['used'], 1)
        self.assertEqual(self.report()['remaining'], 0)

    def test_confirmed_rollback_then_same_retry_consumes_once(self):
        self.wrong(); pid = self.start(); data = self.create_data(pid)
        with mock.patch.object(dlms, 'build_quiz_html', side_effect=OSError('fixture disk failure')):
            self.assertEqual(self.create(data).status_code, 503)
        self.assertEqual(self.report()['reserved'], 0)
        self.assertEqual(self.report()['used'], 0)
        self.assertEqual(self.create(data).status_code, 200)
        self.assertEqual(self.report()['used'], 1)

    def test_crash_recovery_committed_and_registered_boundaries(self):
        class Crash(BaseException):
            pass
        for checkpoint, expected in [('db_committed', 0), ('registry_published', 1)]:
            with self.subTest(checkpoint=checkpoint):
                self.wrong(); pid = self.start(); data = self.create_data(pid)
                def crash(stage, journal):
                    if stage == checkpoint:
                        raise Crash()
                with mock.patch.object(dlms, '_quiz_publication_checkpoint', side_effect=crash):
                    with self.assertRaises(Crash): self.create(data)
                self.assertEqual(self.report()['reserved'], 1)
                self.assertEqual(self.create(data).status_code, 409)
                dlms.reconcile_quiz_publications()
                self.assertEqual(self.report()['used'], expected)
                self.assertEqual(self.report()['reserved'], 0)
                result = self.create(data)
                self.assertEqual(result.status_code, 200, result.json)
                self.assertEqual(self.report()['used'], 1)

    def test_reservation_before_crash_recovers_without_consumption(self):
        self.wrong(); pid = self.start(); data = self.create_data(pid)
        with dlms.get_db() as conn:
            sm.reserve(conn, data, dlms._study_mistake_options())
        dlms.reconcile_quiz_publications()
        self.assertEqual(self.report()['remaining'], 1)
        self.assertEqual(self.create(data).status_code, 200)

    def test_concurrent_requests_reserve_disjoint_members(self):
        self.wrong(); pid = self.start()
        requests = [self.create_data(pid) for _ in range(2)]
        def reserve(data):
            conn = dlms.get_db()
            try:
                return sm.reserve(conn, data, dlms._study_mistake_options())
            except sm.Conflict:
                return 'conflict'
            finally: conn.close()
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(reserve, requests))
        self.assertEqual(results.count('conflict'), 1)
        self.assertEqual(self.report()['reserved'], 1)
        self.assertEqual(self.report()['used'], 0)

    def test_evidence_deleted_between_selection_and_publication(self):
        self.wrong(); pid = self.start(); data = self.create_data(pid)
        with mock.patch.object(dlms, '_quiz_publication_checkpoint', side_effect=lambda stage, journal: restore.delete_study_history_core(dlms.DB_PATH) if stage=='journal_created' else None):
            self.assertEqual(self.create(data).status_code, 409)
        self.assertEqual(self.report()['used'], 0)
        self.assertEqual(self.pool()['eligible'], [])
        with dlms.get_db() as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM quizzes WHERE generation_kind='mixed_quiz'").fetchone()[0], 0)

    def test_learning_reset_preserves_pool_pass_but_not_estimates(self):
        self.wrong(); pid = self.start()
        restore.reset_learning_intelligence_core(dlms.DB_PATH)
        self.assertEqual(len(self.pool()['eligible']), 1)
        self.assertEqual(self.report()['id'], pid)
        with dlms.get_db() as conn:
            self.assertEqual(learning._deduplicated_learning_answer_events(conn.cursor()), [])
        self.assertEqual(self.create(self.create_data(pid)).status_code, 200)
        with dlms.get_db() as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM learning_events').fetchone()[0], 0)

    def test_epoch_invalidation_rejects_old_request_and_preserves_pass(self):
        self.wrong(); pid = self.start(); data = self.create_data(pid)
        with dlms.get_db() as conn: schema.invalidate(conn)
        self.assertEqual(self.create(data).status_code, 409)
        self.assertEqual(self.report()['id'], pid)
        self.assertEqual(self.report()['remaining'], 1)

    def test_schema11_migration_repeat_interruption_and_old_refusal(self):
        self.wrong()
        path = Path(dlms.APP_DATA_DIR) / 'old-copy.db'
        with dlms.get_db() as source, sqlite3.connect(path) as target: source.backup(target)
        with sqlite3.connect(path) as conn:
            for table in ('study_mistake_members','study_mistake_actions','study_mistake_passes','study_mistake_state'):
                conn.execute('DROP TABLE ' + table)
            conn.execute('UPDATE schema_meta SET version=11')
            before = {t: list(conn.execute('SELECT * FROM ' + t)) for t in ('quizzes','questions','choices','study_responses','learning_events')}
        original = schema.migrate
        def interrupted(conn):
            original(conn)
            raise RuntimeError('fixture migration interruption')
        with mock.patch.dict(dlms.DLMS_SCHEMA_MIGRATIONS, {12: interrupted}):
            with self.assertRaises(RuntimeError): dlms.bootstrap_database(str(path), require_owned_root=False)
        with sqlite3.connect(path) as conn:
            self.assertEqual(conn.execute('SELECT version FROM schema_meta').fetchone()[0], 11)
            self.assertEqual(conn.execute("SELECT count(*) FROM sqlite_master WHERE name='study_mistake_state'").fetchone()[0], 0)
        self.assertEqual(dlms.bootstrap_database(str(path), require_owned_root=False)['version'], 12)
        self.assertEqual(dlms.bootstrap_database(str(path), require_owned_root=False)['status'], 'current')
        with sqlite3.connect(path) as conn:
            for table, contents in before.items(): self.assertEqual(list(conn.execute('SELECT * FROM ' + table)), contents)
        # Same version-refusal path used by schema-11 source, not a moving Git baseline.
        with mock.patch.object(dlms, 'DLMS_SCHEMA_VERSION', 11):
            with self.assertRaises(dlms.UnsupportedDatabaseSchemaVersionError): dlms.bootstrap_database(str(path), require_owned_root=False)

    def test_full_backup_restores_pass_and_stales_old_request(self):
        self.wrong(); pid = self.start(); data = self.create_data(pid)
        archive, _ = dlms._create_dlms_backup('mistake-pass-fixture')
        staged = Path(dlms.APP_DATA_DIR) / 'restore-fixture'
        staged.mkdir()
        import zipfile
        with zipfile.ZipFile(archive) as z: z.extractall(staged)
        # Use the application's supported staged migration/validation procedure.
        root = next(staged.glob('*/results.db'), staged / 'results.db').parent
        result = dlms._prepare_staged_restore_database(str(root))
        with sqlite3.connect(result['path']) as conn:
            self.assertEqual(conn.execute('SELECT id FROM study_mistake_passes').fetchone()[0], pid)
            self.assertEqual(conn.execute('SELECT count(*) FROM study_mistake_members').fetchone()[0], 1)
            self.assertNotEqual(conn.execute('SELECT generation FROM study_mistake_state').fetchone()[0], data['generation'])

    def test_scope_change_preserves_previous_pass_and_new_mistakes_wait(self):
        self.wrong(); pid = self.start()
        qid, _ = self.publish(title='Later bank', kind=None)
        self.save(self.claim_quiz(qid))
        wider = self.selection([self.quiz_id, qid])
        new = self.start(wider)
        self.assertNotEqual(new, pid)
        self.assertEqual(self.report()['id'], pid)
        self.assertEqual(self.report(wider)['remaining'], 2)

    def test_missing_media_and_sources_cannot_be_substituted(self):
        self.wrong(); pid = self.start(); data = self.create_data(pid)
        with dlms.get_db() as conn:
            conn.execute("UPDATE questions SET media_json=? WHERE quiz_id=?", (json.dumps({'image_url':'/quiz-assets/missing/missing.png'}), self.quiz_id))
        self.assertEqual(self.create(data).status_code, 409)
        self.assertEqual(self.report()['used'], 0)
        with dlms.get_db() as conn: conn.execute('DELETE FROM quizzes WHERE id=?', (self.quiz_id,))
        self.assertEqual(self.pool()['eligible'], [])
        self.assertEqual(self.report()['unavailable'], 1)

    def test_same_named_images_preserve_separate_bytes_and_generated_lineage(self):
        from PIL import Image
        sources = []
        for bucket, color in [('one', 'red'), ('two', 'blue')]:
            path = Path(dlms.QUIZ_ASSET_FOLDER) / bucket / 'image.png'
            path.parent.mkdir(parents=True); Image.new('RGB', (20,20), color).save(path)
            question = dict(self.choice(), image_url=f'/quiz-assets/{bucket}/image.png')
            qid, _ = self.publish(title=bucket, questions=[question], kind=None)
            response = self.save(self.claim_quiz(qid)); self.assertEqual(response.status_code, 200)
            sources.append(qid)
        scope = self.selection(sources); pid = self.start(scope)
        result = self.create(self.create_data(pid, count=2, scope=scope))
        self.assertEqual(result.status_code, 200, result.json)
        with dlms.get_db() as conn:
            generated = conn.execute("SELECT id FROM quizzes WHERE generation_kind='mixed_quiz'").fetchone()[0]
            qs = conn.execute('SELECT id,source_question_uid FROM questions WHERE quiz_id=? ORDER BY question_number', (generated,)).fetchall()
            urls = []
            for row in qs:
                payload = learning._question_payload_from_db(conn.cursor(), row['id']); urls.append(payload['image_url'])
                source = conn.execute('SELECT id FROM questions WHERE question_uid=?', (row['source_question_uid'],)).fetchone()[0]
                self.assertEqual(sm.grading_content(payload, dlms._study_mistake_options()), sm.grading_content(learning._question_payload_from_db(conn.cursor(), source), dlms._study_mistake_options()))
            self.assertEqual(len(set(urls)), 2)

    def test_media_url_looking_text_is_not_rewritten_during_composition(self):
        from PIL import Image
        path = Path(dlms.QUIZ_ASSET_FOLDER) / 'literal' / 'image.png'
        path.parent.mkdir(parents=True)
        Image.new('RGB', (20, 20), 'green').save(path)
        literal = '/quiz-assets/literal/image.png'
        question = dict(self.choice(), question=literal, explanation=literal,
                        image_url=literal, image_alt=literal,
                        image_edits=[{'type': 'text', 'text': literal, 'x': .1, 'y': .1, 'size': 18}],
                        image_source={'url': literal})
        question['choices'][0]['text'] = literal
        qid, _ = self.publish(title='Literal path question', questions=[question], kind=None)
        self.assertEqual(self.save(self.claim_quiz(qid)).status_code, 200)
        selected = self.selection([qid])
        pid = self.start(selected)
        result = self.create(self.create_data(pid, scope=selected))
        self.assertEqual(result.status_code, 200, result.json)
        with dlms.get_db() as conn:
            source_id = conn.execute('SELECT id FROM questions WHERE quiz_id=?', (qid,)).fetchone()[0]
            copied_id = conn.execute("SELECT q.id FROM questions q JOIN quizzes z ON z.id=q.quiz_id WHERE z.generation_kind='mixed_quiz'").fetchone()[0]
            source = learning._question_payload_from_db(conn.cursor(), source_id)
            copied = learning._question_payload_from_db(conn.cursor(), copied_id)
            for key in ('question', 'explanation', 'choices', 'image_alt', 'image_edits', 'image_source'):
                self.assertEqual(copied[key], source[key], key)
            self.assertNotEqual(copied['image_url'], source['image_url'])
            self.assertEqual(sm.grading_content(copied, dlms._study_mistake_options()),
                             sm.grading_content(source, dlms._study_mistake_options()))
        # The supported direct media envelope also copies only its image URL;
        # arbitrary nested image_url fields are content, not inferred assets.
        envelope = {'question': literal, 'media': {'image_url': literal, 'image_alt': literal},
                    'image_source': {'image_url': literal}, 'pairs': [{'left': literal, 'right': literal}]}
        snapshot = dlms._snapshot_composition_asset_refs(envelope, 'envelope',
                                                       destination_root=str(path.parent / 'envelope'))
        self.assertNotEqual(snapshot['media']['image_url'], literal)
        for key in ('question', 'image_source', 'pairs'):
            self.assertEqual(snapshot[key], envelope[key], key)
        self.assertEqual(snapshot['media']['image_alt'], literal)

    def test_hundreds_of_questions_bounded_preview_and_successive_batches(self):
        questions = [dict(self.choice(), number=i+1, question=f'Sample question {i+1}') for i in range(230)]
        qid, _ = self.publish(title='Large pool', questions=questions, kind=None)
        event = self.claim_quiz(qid)
        with dlms.get_db() as conn:
            rows = conn.execute('SELECT id,question_number FROM questions WHERE quiz_id=? ORDER BY question_number', (qid,)).fetchall()
            for seq, row in enumerate(rows, 1):
                payload = dict(event, questionOrdinal=row['question_number'], sequence=seq, eventId=uuid.uuid4().hex)
                conn.execute('INSERT INTO study_responses VALUES(?,?,?,?,?,?,?,?,?)', (payload['eventId'], event['sessionId'], seq, row['id'], row['question_number'], 'response', 0, study.encode(payload), study.utc_now()))
        scope = self.selection([qid]); self.assertEqual(len(self.pool(scope)['eligible']), 230)
        html = self.client.get('/quiz-composer/study-mistakes?quizzes='+str(qid)).get_data(as_text=True)
        self.assertEqual(html.count('<li>Large pool'), 20)
        pid = self.start(scope)
        for count, remaining in [(100,130),(100,30),(30,0)]:
            result = self.create(self.create_data(pid, count=count, scope=scope))
            self.assertEqual(result.status_code, 200, result.json)
            self.assertEqual(self.report(scope)['remaining'], remaining)
        with dlms.get_db() as conn:
            consumed = [r[0] for r in conn.execute('SELECT source_question_uid FROM questions WHERE is_generated_copy=1')]
            self.assertEqual(len(consumed), 230); self.assertEqual(len(set(consumed)), 230)

    def test_restore_rejects_fabricated_consumption_and_scope_hash(self):
        self.wrong(); pid = self.start(); data = self.create_data(pid)
        self.assertEqual(self.create(data).status_code, 200)
        with dlms.get_db() as conn:
            schema.validate(conn)
            conn.execute("UPDATE study_mistake_passes SET scope_hash='wrong'")
            with self.assertRaises(ValueError): schema.validate(conn)
            conn.rollback()
            conn.execute("UPDATE study_mistake_actions SET input_json='{}'")
            with self.assertRaises(ValueError): schema.validate(conn)
            conn.rollback()
            conn.execute('UPDATE study_mistake_actions SET quiz_id=NULL,html=NULL')
            with self.assertRaises(ValueError): schema.validate(conn)
            conn.rollback()
            conn.execute('UPDATE study_mistake_members SET reserved_by=used_by,used_by=NULL')
            with self.assertRaises(ValueError): schema.validate(conn)
            conn.rollback()
            schema.validate(conn)

    def test_page_is_bounded_and_has_both_modes_and_no_text_collapse(self):
        self.wrong()
        response = self.client.get('/quiz-composer/study-mistakes?quizzes=' + str(self.quiz_id))
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('Without repeats', html); self.assertIn('Random', html)
        self.assertIn('1 eligible question in these sources', html); self.assertIn('Check Study mistakes', html)
        self.assertEqual(self.client.post('/api/quiz-composer/study-mistakes/create', json={}, headers=self.headers).status_code, 400)
        self.assertEqual(self.client.post('/api/quiz-composer/study-mistakes/create', json={}).status_code, 400)

    def test_generated_evidence_cannot_normalize_invalid_source_flags(self):
        with dlms.get_db() as conn:
            q = conn.execute('SELECT id FROM questions WHERE quiz_id=?',(self.quiz_id,)).fetchone()[0]
            payload = learning._question_payload_from_db(conn.cursor(), q)
            payload['composition_sources'] = [{'quiz_id': self.quiz_id}]
        generated, _ = dlms._publish_quiz('Copy before source corruption', [payload], generation_kind='mixed_quiz', filename_prefix='mixed_quiz')
        self.save(self.claim_quiz(generated))
        with dlms.get_db() as conn:
            conn.execute("UPDATE choices SET is_correct=2 WHERE question_id=? AND label='A'", (q,))
        current = self.pool()
        self.assertEqual(current['eligible'], [])
        self.assertEqual(len(current['unavailable']), 1)
        with dlms.get_db() as conn:
            self.assertEqual(conn.execute("SELECT is_correct FROM choices WHERE question_id=? AND label='A'",(q,)).fetchone()[0],2)

    def test_invalid_media_metadata_is_not_silently_repaired(self):
        self.wrong()
        with dlms.get_db() as conn:
            conn.execute("UPDATE questions SET media_json='[]' WHERE quiz_id=?",(self.quiz_id,))
        self.assertEqual(self.pool()['eligible'], [])

    def test_new_wrong_waits_for_next_snapshot_of_same_folder(self):
        self.wrong()
        registry = dlms.load_registry()
        registry[0]['folder'] = 'Shared folder';dlms.save_registry(registry)
        selected = self.selection([], ['Shared folder'])
        pid = self.start(selected)
        second, _ = self.publish(title='Newly studied source', kind=None)
        registry = dlms.load_registry()
        next(r for r in registry if r['id']==second)['folder'] = 'Shared folder';dlms.save_registry(registry)
        self.save(self.claim_quiz(second))
        report = self.report(selected)
        self.assertEqual((report['remaining'],report['new']),(1,1))
        response = self.create(self.create_data(pid,count=2,scope=selected))
        self.assertEqual(response.status_code,409)
        self.assertEqual(self.report(selected)['used'],0)
        self.start(selected)
        self.assertEqual(self.report(selected)['remaining'],2)

    def test_source_changed_at_publication_is_not_substituted(self):
        self.wrong();pid=self.start();data=self.create_data(pid)
        before = len(dlms.load_registry())
        def checkpoint(name, _journal):
            if name=='journal_created':
                with dlms.get_db() as conn:
                    conn.execute("UPDATE choices SET text='Explicit concurrent source change' WHERE label='A'")
        with mock.patch.object(dlms,'_quiz_publication_checkpoint',side_effect=checkpoint):
            result=self.create(data)
        self.assertEqual(result.status_code,409,result.json)
        self.assertEqual(len(dlms.load_registry()),before)
        self.assertEqual(self.report()['used'],0)

    def test_uncertain_journal_holds_reservation_and_original_request(self):
        self.wrong();pid=self.start();data=self.create_data(pid)
        with dlms.get_db() as conn:
            sm.reserve(conn,data,dlms._study_mistake_options())
            root=Path(dlms.DATA_FOLDER)/'uncertain-test';root.mkdir()
            (root/'publication_unresolved.json').write_text('{}')
            sm.recover(conn,dlms._study_mistake_options(),root)
            self.assertEqual(conn.execute('SELECT state FROM study_mistake_actions').fetchone()[0],'reserved')
        result=self.create(data)
        self.assertEqual(result.status_code,409)
        self.assertFalse(result.json['can_change_request'])
        self.assertEqual(self.report()['reserved'],1)

    def test_matching_multi_answer_and_non_alphabetic_gapped_order_fidelity(self):
        cases = [
            (self.matching(), {'0':1,'1':0}, {'0':{'sourcePairIndexes':[0,1],'direction':'term_to_definition'}}),
            (self.choice(multi=True), ['B','C'], {}),
            ({'number':1,'type':'choice','question':'Independent gap example','explanation':'Exact explanation',
              'choices':[{'label':'D','text':'Same visible wording','is_correct':True},
                         {'label':'A','text':'Distractor','is_correct':False},
                         {'label':'C','text':'Same visible wording','is_correct':False}]}, ['C'], {}),
        ]
        source_ids=[]
        for question, selected, variants in cases:
            qid,_=self.publish(title='Supported source '+question['type'],questions=[question],kind=None)
            event=self.claim_quiz(qid,variants=variants)
            event.update(questionType=question['type'],selected=selected,wasCorrect=False)
            result=self.save(event);self.assertEqual(result.status_code,200,result.json)
            source_ids.append(qid)
        selected=self.selection(source_ids);self.assertEqual(len(self.pool(selected)['eligible']),3)
        pid=self.start(selected)
        result=self.create(self.create_data(pid,count=3,scope=selected));self.assertEqual(result.status_code,200,result.json)
        with dlms.get_db() as conn:
            generated=conn.execute("SELECT id FROM quizzes WHERE generation_kind='mixed_quiz'").fetchone()[0]
            for row in conn.execute('SELECT id,source_question_uid FROM questions WHERE quiz_id=?',(generated,)).fetchall():
                original=conn.execute('SELECT id FROM questions WHERE question_uid=?',(row['source_question_uid'],)).fetchone()[0]
                copied=learning._question_payload_from_db(conn.cursor(),row['id'])
                source=learning._question_payload_from_db(conn.cursor(),original)
                for key in ('question','type','choices','pairs','round_size','direction','explanation'):
                    self.assertEqual(copied.get(key),source.get(key),key)

    def test_simultaneous_same_request_publishes_and_consumes_once(self):
        from tests.csrf_test_utils import csrf_headers
        self.wrong();pid=self.start();data=self.create_data(pid)
        def create(_):
            client=dlms.app.test_client()
            return client.post('/api/quiz-composer/study-mistakes/create',json=data,headers=csrf_headers(client))
        with ThreadPoolExecutor(max_workers=2) as executor:
            results=list(executor.map(create,range(2)))
        self.assertEqual([r.status_code for r in results],[200,200])
        self.assertEqual(results[0].json['url'],results[1].json['url'])
        self.assertEqual(sorted(r.json['replayed'] for r in results),[False,True])
        self.assertEqual(self.report()['used'],1)
        with dlms.get_db() as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM quizzes WHERE generation_kind='mixed_quiz'").fetchone()[0],1)

    def test_media_bytes_changed_before_publication_rejects_original_snapshot(self):
        from PIL import Image
        path=Path(dlms.QUIZ_ASSET_FOLDER)/'byte-change/image.png';path.parent.mkdir()
        Image.new('RGB',(20,20),'red').save(path)
        qid,_=self.publish(questions=[dict(self.choice(),image_url='/quiz-assets/byte-change/image.png')],kind=None)
        self.save(self.claim_quiz(qid));selected=self.selection([qid]);pid=self.start(selected);data=self.create_data(pid,scope=selected)
        def checkpoint(stage,_journal):
            if stage=='journal_created':Image.new('RGB',(20,20),'blue').save(path)
        with mock.patch.object(dlms,'_quiz_publication_checkpoint',side_effect=checkpoint):
            result=self.create(data)
        self.assertEqual(result.status_code,409,result.json)
        self.assertEqual(self.report(selected)['used'],0)

    def test_recovery_requires_owned_profile(self):
        self.wrong();pid=self.start();data=self.create_data(pid)
        with dlms.get_db() as conn:sm.reserve(conn,data,dlms._study_mistake_options())
        with mock.patch.object(dlms,'_read_data_root_marker',return_value=None):dlms.reconcile_quiz_publications()
        self.assertEqual(self.report()['reserved'],1)

    def test_consumed_and_random_ledger_roundtrip_and_schema11_backup(self):
        self.wrong();pid=self.start()
        self.assertEqual(self.create(self.create_data(pid)).status_code,200)
        self.assertEqual(self.create(self.create_data(mode='random')).status_code,200)
        with dlms.get_db() as conn:
            before={t:[tuple(r) for r in conn.execute('SELECT * FROM '+t+' ORDER BY rowid')] for t in
                    ('study_mistake_passes','study_mistake_members','study_mistake_actions')}
        archive,_=dlms._create_dlms_backup('consumed-ledger')
        root=Path(dlms.APP_DATA_DIR)/'staged-consumed';root.mkdir()
        import zipfile
        with zipfile.ZipFile(archive) as z:z.extractall(root)
        staged=root/'DLMS_DATA'
        prepared=dlms._prepare_staged_restore_database(str(staged))
        with sqlite3.connect(prepared['path']) as conn:
            for t,contents in before.items():self.assertEqual(list(conn.execute('SELECT * FROM '+t+' ORDER BY rowid')),contents)
            for table in ('study_mistake_members','study_mistake_actions','study_mistake_passes','study_mistake_state'):
                conn.execute('DROP TABLE '+table)
            conn.execute('UPDATE schema_meta SET version=11')
        # This old-profile staging fixture has no pass state. The supported
        # restore bootstrap upgrades it without inventing eligibility or usage.
        prepared=dlms._prepare_staged_restore_database(str(staged))
        with sqlite3.connect(prepared['path']) as conn:
            self.assertEqual(conn.execute('SELECT version FROM schema_meta').fetchone()[0],12)
            self.assertEqual(conn.execute('SELECT count(*) FROM study_mistake_passes').fetchone()[0],0)
            self.assertEqual(conn.execute('SELECT count(*) FROM study_responses').fetchone()[0],1)

    def test_checked_pool_labels_and_complete_pass_presentation(self):
        self.wrong(); pid=self.start()
        self.assertEqual(self.create(self.create_data(pid)).status_code,200)
        html=self.client.get('/quiz-composer/study-mistakes?quizzes='+str(self.quiz_id)).get_data(as_text=True)
        self.assertIn('1 eligible question in these sources',html)
        self.assertIn('0 remaining in this pass',html)
        self.assertIn('1 included in saved mixes',html)
        self.assertIn('Pass complete',html)
        self.assertIn('not the exact next batch',html)
        self.assertIn('Unavailable questions (0)',html)
        self.assertLess(html.index('id="mistakePreviewHeading"'),html.index('id="mistakeCreateForm"'))
        self.assertIn('aria-describedby="mistakeCreationReason"',html)
        self.assertEqual(self.report()['used'],1)

    def test_legacy_exclusion_table_groups_reasons_and_bounds_every_page(self):
        questions=[dict(self.choice(),number=n,question='Legacy exclusion '+str(n)) for n in range(1,26)]
        qid,_=self.publish(kind=None,questions=questions)
        with dlms.get_db() as c:
            for row in c.execute('SELECT id FROM questions WHERE quiz_id=?',(qid,)).fetchall():
                c.execute("INSERT INTO study_legacy_responses(quiz_id,question_id,mode,was_correct,response_json) VALUES(?,?,'Study',0,?)",(qid,row['id'],json.dumps({'selected':['C']})))
        base='/quiz-composer/study-mistakes?quizzes='+str(qid)
        first=self.client.get(base).get_data(as_text=True)
        second=self.client.get(base+'&unavailable_page=2').get_data(as_text=True)
        self.assertIn('Unavailable questions (25)',first)
        self.assertEqual(first.count('data-label="Quiz"'),20)
        self.assertEqual(second.count('data-label="Quiz"'),5)
        self.assertEqual(first.count('Legacy response has no verifiable content revision.'),1)
        self.assertEqual(first.count('Unverified legacy history'),20)
        self.assertIn('cannot recreate a missing historical revision',first)
        self.assertIn('More unavailable questions',first)
        self.assertIn('Previous unavailable questions',second)
        self.assertEqual(self.pool(self.selection([qid]))['eligible'],[])

    def test_reserved_pass_does_not_claim_completion(self):
        self.wrong();pid=self.start();data=self.create_data(pid)
        with dlms.get_db() as c:sm.reserve(c,data,dlms._study_mistake_options())
        html=self.client.get('/quiz-composer/study-mistakes?quizzes='+str(self.quiz_id)).get_data(as_text=True)
        self.assertIn('1 reserved',html)
        self.assertIn('id="mistakePassComplete" class="study-mistakes-notice" hidden',html)
        self.assertEqual(self.report()['used'],0)
