"""Current no-op maintenance preserves byte-bound Study identity, not old states."""
from contextlib import closing
import copy
import json
from pathlib import Path
from unittest import mock
import unittest

from tests import test_study_sessions as foundation
from tests import test_generated_practice_lifecycle as lifecycle
from tests.csrf_test_utils import csrf_headers
from dlms.rendering.quiz_artifacts import equivalent_quiz_json_bytes

dlms = foundation.dlms


class RebuildCurrentIdentityTests(unittest.TestCase):
    def setUp(self):
        lifecycle.GeneratedPracticeLifecycleTests.setUp(self)
        # The reused low-level fixture creates every non-DB path as a folder;
        # provide an actual portal file for these maintenance journeys.
        portal = Path(dlms.PORTAL_CONFIG)
        portal.rmdir()
        portal.write_text('{}')
    publish = foundation.StudySessionTests.publish
    fingerprint = foundation.StudySessionTests.fingerprint
    choice = staticmethod(foundation.StudySessionTests.choice)

    def create(self, questions=None):
        if questions is None:
            question = self.choice()
            # Match the actual authoring path's complete playable answer key;
            # the lower-level lifecycle fixture omits this runtime field.
            question['correct'] = ['A']
            questions = [question]
        qid, html = self.publish(questions=questions, kind=None)
        entry = next(e for e in dlms.load_registry() if e['id'] == qid)
        path = Path(dlms.DATA_FOLDER, dlms._quiz_artifact_names(entry)[1])
        return qid, entry, path

    def records(self):
        with closing(dlms.get_db()) as conn:
            return list(conn.iterdump())

    def test_current_study_survives_two_rebuilds_and_new_http_client(self):
        qid, entry, path = self.create()
        # Actual ordinary authoring omits these defaults. Keep CRLF/formatting
        # too: comparing parsed equality alone would still break fingerprints.
        payload = json.loads(path.read_bytes())
        for q in payload:
            for key in ('type', 'explanation', 'concepts'):
                q.pop(key, None)
        path.write_bytes(json.dumps(payload, indent=2).replace('\n', '\r\n').encode())
        before = path.read_bytes()
        claim = dict(quizId=qid, sessionId='current-study', owner='current-owner',
                     generation=self.client.get(f'/api/study/quiz/{qid}').json['generation'],
                     fingerprint=self.fingerprint(qid), variants={})
        started = self.client.post('/api/study/session', json=claim, headers=self.headers)
        self.assertEqual(started.status_code, 200, started.json)
        event = dict(contract=2, quizId=qid, sessionId=claim['sessionId'], owner=claim['owner'],
                     generation=claim['generation'], assessmentRevision=started.json['session']['assessment_revision'],
                     eventId='current-answer', sequence=1, questionOrdinal=1,
                     questionType='choice', wasCorrect=True, selected=['A'], kind='response')
        self.assertEqual(self.client.post('/api/learning-events/study-response', json=event, headers=self.headers).status_code, 200)
        records = self.records()
        registry = copy.deepcopy(dlms.load_registry())
        for _ in range(2):
            self.assertEqual(dlms._rebuild_registered_quiz_artifacts()['failed'], [])
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(self.records(), records)
            self.assertEqual(dlms.load_registry(), registry)
        reopened = dlms.app.test_client()
        headers = csrf_headers(reopened)
        resumed = reopened.post('/api/study/session', json=claim, headers=headers)
        self.assertEqual(resumed.status_code, 200, resumed.json)
        self.assertEqual(resumed.json['session']['id'], claim['sessionId'])
        self.assertEqual(resumed.json['session']['reviewed'], 1)
        self.assertEqual(resumed.json['session']['answers']['0']['selected'], ['A'])
        for _ in range(2):
            self.assertEqual(reopened.post('/api/study/finish', json=event, headers=headers).status_code, 200)
        with closing(dlms.get_db()) as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM study_responses').fetchone()[0], 1)
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM study_sessions WHERE completed_at IS NOT NULL').fetchone()[0], 1)
        # A genuine canonical edit still regenerates and refuses the old hash.
        with closing(dlms.get_db()) as conn, conn:
            conn.execute('UPDATE questions SET question_text=? WHERE quiz_id=?', ('Real edit', qid))
        self.assertEqual(dlms._rebuild_registered_quiz_artifacts()['failed'], [])
        self.assertNotEqual(path.read_bytes(), before)
        refused = reopened.post('/api/study/session', json=claim, headers=headers)
        self.assertEqual(refused.status_code, 409, refused.json)

    def test_matching_defaults_full_metadata_order_and_real_key_changes(self):
        q = lifecycle.GeneratedPracticeLifecycleTests.matching()
        qid, entry, path = self.create([q])
        before = path.read_bytes()
        self.assertEqual(dlms._rebuild_registered_quiz_artifacts()['failed'], [])
        self.assertEqual(path.read_bytes(), before)
        with closing(dlms.get_db()) as conn, conn:
            conn.execute('UPDATE matching_pairs SET right_text=? WHERE id=(SELECT MIN(id) FROM matching_pairs)', ('Changed answer',))
        self.assertEqual(dlms._rebuild_registered_quiz_artifacts()['failed'], [])
        self.assertNotEqual(path.read_bytes(), before)
        self.assertEqual(json.loads(path.read_bytes())[0]['pairs'][0]['right'], 'Changed answer')

    def test_missing_or_broken_ordinary_derived_file_can_rebuild_from_complete_db(self):
        qid, entry, path = self.create()
        for invalid in (None, b'{invalid'):
            if invalid is None:
                path.unlink()
            else:
                path.write_bytes(invalid)
            self.assertEqual(dlms._rebuild_registered_quiz_artifacts()['failed'], [])
            self.assertEqual(json.loads(path.read_bytes())[0]['question'], self.choice()['question'])

    def test_unknown_full_content_is_refused_without_writes_and_other_item_succeeds(self):
        qid, entry, path = self.create()
        other, _, _ = self.create()
        payload = json.loads(path.read_bytes())
        payload[0]['unpersisted_instruction'] = 'Do not silently delete this'
        path.write_text(json.dumps(payload))
        before, html, records = path.read_bytes(), Path(dlms.QUIZ_FOLDER, entry['html']).read_bytes(), self.records()
        result = dlms._rebuild_registered_quiz_artifacts()
        self.assertEqual(result['failed'], [qid])
        self.assertEqual(result['rebuilt'], 1)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(Path(dlms.QUIZ_FOLDER, entry['html']).read_bytes(), html)
        self.assertEqual(self.records(), records)
        self.assertIn('complete content', result['failure_details'][0]['message'])

    def test_flat_derived_stubs_regenerate_only_with_complete_canonical_answers(self):
        quizzes = []
        for kind in ('choice', 'matching'):
            questions = [lifecycle.GeneratedPracticeLifecycleTests.matching()] if kind == 'matching' else None
            qid, entry, path = self.create(questions)
            html = Path(dlms.QUIZ_FOLDER, entry['html'])
            quizzes.append((kind, qid, path, html))
            for stub in ([{'stale': True}], [{'number': 1, 'previous': True}], [{}]):
                path.write_text(json.dumps(stub))
                html.write_text('stale derived HTML')
                records = self.records()
                result = dlms._rebuild_registered_quiz_artifacts()
                self.assertEqual(result['failed'], [], result)
                payload = json.loads(path.read_bytes())
                self.assertEqual(payload[0]['type'], kind)
                self.assertEqual(self.records(), records)
                self.assertIn(f'window.QUIZ_ID = {qid};', html.read_text())
                if kind == 'choice':
                    self.assertEqual(payload[0]['correct'], ['A'])
                else:
                    self.assertEqual([(p['left'], p['right']) for p in payload[0]['pairs']],
                                     [('Alpha', 'First'), ('Beta', 'Second')])
        # A stub must never authorize fabrication from incomplete DB rows.
        refused = []
        for kind, qid, path, html in quizzes:
            path.write_text('[{"stale":true}]')
            before, previous_html = path.read_bytes(), html.read_bytes()
            table = 'choices' if kind == 'choice' else 'matching_pairs'
            with closing(dlms.get_db()) as conn, conn:
                conn.execute('DELETE FROM '+table+' WHERE question_id IN (SELECT id FROM questions WHERE quiz_id=?)', (qid,))
            records = self.records()
            refused.append(qid)
            self.assertEqual(dlms._rebuild_registered_quiz_artifacts()['failed'], refused)
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(html.read_bytes(), previous_html)
            self.assertEqual(self.records(), records)

    def test_stub_detection_keeps_mixed_nested_and_spatial_authority_refusal(self):
        qid, entry, path = self.create()
        full = json.loads(path.read_bytes())[0]
        unknown = {**full, 'unpersisted_instruction':'Keep this content'}
        cases = [
            [{'stale': True}, unknown], [unknown, {'stale': True}],
            [None, unknown], [unknown, None],
            [{'previous': {'question':'Unmapped nested content'}}],
            [{'type':'hotspot', 'stale':True}],
            [{'target':{'type':'circle','x':.5,'y':.5,'radius':.1}}],
            [{'question':'Represented question', 'unpersisted_instruction':'Keep'}],
        ]
        html = Path(dlms.QUIZ_FOLDER, entry['html'])
        for payload in cases:
            path.write_text(json.dumps(payload))
            before, previous_html, records = path.read_bytes(), html.read_bytes(), self.records()
            result = dlms._rebuild_registered_quiz_artifacts()
            self.assertEqual(result['failed'], [qid], payload)
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(html.read_bytes(), previous_html)
            self.assertEqual(self.records(), records)

    def test_unknown_nested_content_and_reserved_media_cannot_be_silently_dropped(self):
        qid, entry, path = self.create()
        original = json.loads(path.read_bytes())
        for area in ('choice', 'pair', 'source'):
            payload = copy.deepcopy(original)
            if area == 'choice':
                payload[0]['choices'][0]['unpersisted_feedback'] = 'Do not drop'
            elif area == 'pair':
                payload[0] = {'number':1, 'type':'matching', 'question':'Match',
                              'pairs':[{'left':'A','right':'B','source':{'license':'Do not drop'}}]}
            else:
                payload[0]['source'] = {'unpersisted_license_detail':'Do not drop'}
            path.write_text(json.dumps(payload))
            before = path.read_bytes()
            result = dlms._rebuild_registered_quiz_artifacts()
            self.assertEqual(result['failed'], [qid])
            self.assertEqual(path.read_bytes(), before)
        path.write_text(json.dumps(original))
        with closing(dlms.get_db()) as conn, conn:
            conn.execute('UPDATE questions SET media_json=? WHERE quiz_id=?', (json.dumps({'correct':['C']}), qid))
        before, records = path.read_bytes(), self.records()
        result = dlms._rebuild_registered_quiz_artifacts()
        self.assertEqual(result['failed'], [qid])
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(self.records(), records)

    def test_current_media_bytes_preserved_and_missing_or_invalid_image_refused(self):
        from PIL import Image
        image = Path(dlms.QUIZ_ASSET_FOLDER, 'current', 'current.png')
        image.parent.mkdir()
        Image.new('RGB', (4,4), 'blue').save(image)
        q = self.choice(); q['correct']=['A']; q['image_url']='/quiz-assets/current/current.png'
        q['image_alt']='Current synthetic asset'
        qid, entry, path = self.create([q])
        before, records = path.read_bytes(), self.records()
        asset = image.read_bytes()
        self.assertEqual(dlms._rebuild_registered_quiz_artifacts()['failed'], [])
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(image.read_bytes(), asset)
        for invalid in (None, b'not an image'):
            if invalid is None: image.unlink()
            else: image.write_bytes(invalid)
            self.assertEqual(dlms._rebuild_registered_quiz_artifacts()['failed'], [qid])
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(self.records(), records)

    def test_corrupt_canonical_media_or_pair_metadata_is_refused_before_publication(self):
        qid, entry, path = self.create()
        html = Path(dlms.QUIZ_FOLDER, entry['html'])
        before, previous_html = path.read_bytes(), html.read_bytes()
        for invalid in ('{broken', '["not-an-object"]'):
            with closing(dlms.get_db()) as conn, conn:
                conn.execute('UPDATE questions SET media_json=? WHERE quiz_id=?', (invalid, qid))
            records = self.records()
            result = dlms._rebuild_registered_quiz_artifacts()
            self.assertEqual(result['failed'], [qid])
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(html.read_bytes(), previous_html)
            self.assertEqual(self.records(), records)
        with closing(dlms.get_db()) as conn, conn:
            conn.execute('UPDATE questions SET media_json=? WHERE quiz_id=?', ('{}', qid))
        matching, match_entry, match_path = self.create([lifecycle.GeneratedPracticeLifecycleTests.matching()])
        match_before = match_path.read_bytes()
        with closing(dlms.get_db()) as conn, conn:
            conn.execute('UPDATE matching_pairs SET verification_json=?', ('{broken',))
        records = self.records()
        result = dlms._rebuild_registered_quiz_artifacts()
        self.assertEqual(result['failed'], [matching])
        self.assertEqual(match_path.read_bytes(), match_before)
        self.assertEqual(self.records(), records)

    def test_failed_publication_restores_exact_pair_and_records(self):
        qid, entry, path = self.create()
        before, html, records = path.read_bytes(), Path(dlms.QUIZ_FOLDER, entry['html']).read_bytes(), self.records()
        # Existing service fault seam; promotion/partial rollback itself is also
        # covered by the unchanged hotspot/publication contracts.
        with mock.patch.object(dlms, '_promote_quiz_mutation_artifacts', side_effect=OSError('synthetic failure')):
            result = dlms._rebuild_registered_quiz_artifacts()
        self.assertEqual(result['failed'], [qid])
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(Path(dlms.QUIZ_FOLDER, entry['html']).read_bytes(), html)
        self.assertEqual(self.records(), records)

    def test_missing_canonical_answers_or_pairs_never_overwrite_playable_content(self):
        for kind in ('choice', 'matching'):
            questions = [lifecycle.GeneratedPracticeLifecycleTests.matching()] if kind == 'matching' else None
            qid, entry, path = self.create(questions)
            html = Path(dlms.QUIZ_FOLDER, entry['html'])
            before, previous_html = path.read_bytes(), html.read_bytes()
            table = 'choices' if kind == 'choice' else 'matching_pairs'
            with closing(dlms.get_db()) as conn, conn:
                conn.execute('DELETE FROM '+table+' WHERE question_id IN (SELECT id FROM questions WHERE quiz_id=?)', (qid,))
            records = self.records()
            result = dlms._rebuild_registered_quiz_artifacts()
            self.assertIn(qid, result['failed'])
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(html.read_bytes(), previous_html)
            self.assertEqual(self.records(), records)

    def test_full_comparison_does_not_ignore_media_answers_or_types(self):
        qid, entry, path = self.create()
        with closing(dlms.get_db()) as conn:
            canonical = dlms._quiz_json_payload_from_db(conn.cursor(), qid)
        raw = path.read_bytes()
        self.assertEqual(equivalent_quiz_json_bytes(path, canonical), raw)
        for change in ('question', 'correct', 'image_url', 'source', 'explanation', 'concepts'):
            altered = copy.deepcopy(canonical)
            altered[0][change] = {'question':'Changed', 'correct':['C'], 'image_url':'/quiz_assets/different.png',
                                  'source':{'license':'Different'}, 'explanation':'Different', 'concepts':['Different']}[change]
            self.assertIsNone(equivalent_quiz_json_bytes(path, altered), change)
        path.unlink(); path.symlink_to(Path(dlms.QUIZ_FOLDER, entry['html']))
        with self.assertRaisesRegex(ValueError, 'not a regular file'):
            equivalent_quiz_json_bytes(path, canonical)
