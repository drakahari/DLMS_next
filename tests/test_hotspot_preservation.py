"""Real pack-generator regressions; no historical quiz repair or migration."""
from contextlib import closing
import copy
import json
import os
from pathlib import Path
import unittest
from unittest import mock
import zipfile

from tests import test_study_sessions as foundation

dlms = foundation.dlms
PACK_ID = 'workflow_audit_it_20261018'
FIXTURE = Path(__file__).parent / 'fixtures/hotspot-preservation/synthetic-pack.zip'


class HotspotPreservationTests(unittest.TestCase):
    setUp = foundation.StudySessionTests.setUp
    publish = foundation.StudySessionTests.publish
    fingerprint = foundation.StudySessionTests.fingerprint
    choice = staticmethod(foundation.StudySessionTests.choice)

    def pack_quiz(self):
        root = Path(dlms.APP_DATA_DIR)
        for name in ('CONTENT_PACK_FOLDER', 'CONTENT_PACK_STAGING_FOLDER'):
            path = root / name.lower()
            path.mkdir(exist_ok=True)
            patch = mock.patch.object(dlms, name, str(path))
            patch.start(); self.addCleanup(patch.stop)
        with zipfile.ZipFile(FIXTURE) as archive:
            archive.extractall(dlms.CONTENT_PACK_FOLDER)  # trusted, committed synthetic fixture
        response = self.client.post('/study-packs/image/generate', data={
            'pack_id': PACK_ID, 'dataset_id': 'lab_targets',
        }, headers=self.headers)
        self.assertEqual(response.status_code, 302)
        entry = next(e for e in dlms.load_registry() if response.location.endswith(e['html']))
        path = Path(dlms.DATA_FOLDER, dlms._quiz_artifact_names(entry)[1])
        payload = json.loads(path.read_bytes())
        self.assertEqual({q['target']['type'] for q in payload}, {'circle', 'polygon'})
        return entry, path, payload

    def database(self):
        with closing(dlms.get_db()) as conn:
            return '\n'.join(conn.iterdump())

    def mark(self, qid, indexes=(0, 1)):
        fingerprint = self.fingerprint(qid)
        context = self.client.post('/api/review-marks/context', json={
            'quiz_id': qid, 'fingerprint': fingerprint,
        }, headers=self.headers)
        self.assertEqual(context.status_code, 200, context.json)
        import uuid
        data = dict(action='mark', request_id=uuid.uuid4().hex, quiz_id=qid,
                    fingerprint=fingerprint, generation=context.json['generation'],
                    revision=context.json['revision'],
                    assessment_revision=context.json['assessment_revision'],
                    indexes=list(indexes), marked=True)
        result = self.client.post('/api/review-marks/save', json=data, headers=self.headers)
        self.assertEqual(result.status_code, 200, result.json)
        self.assertEqual(result.json, self.client.post('/api/review-marks/save', json=data, headers=self.headers).json)
        return data

    def test_actual_image_pack_marks_and_rebuild_preserve_exact_runtime_and_database(self):
        entry, path, payload = self.pack_quiz()
        self.mark(entry['id'])
        before, records = path.read_bytes(), self.database()
        registry = copy.deepcopy(dlms.load_registry())
        result = dlms._rebuild_registered_quiz_artifacts()
        self.assertEqual(result['failed'], [], result)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(self.database(), records)
        self.assertEqual(dlms.load_registry(), registry)
        self.assertEqual(self.client.get('/quizzes/' + entry['html']).status_code, 200)
        self.assertEqual(json.loads(path.read_bytes()), payload)

    def test_actual_pack_rebuild_without_marking_preserves_spatial_assessment(self):
        entry, path, payload = self.pack_quiz()
        before = path.read_bytes()
        result = dlms._rebuild_registered_quiz_artifacts()
        self.assertEqual(result['failed'], [], result)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(json.loads(path.read_bytes()), payload)

    def save_hotspot_history(self, qid, payload):
        claim = dict(quizId=qid, sessionId='hotspot-history', owner='hotspot-owner',
                     generation=self.generation, fingerprint=self.fingerprint(qid), variants={})
        response = self.client.post('/api/study/session', json=claim, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.json)
        session = response.json['session']
        details = []
        for ordinal, question in enumerate(payload, 1):
            point = {'x': .25 if question['target']['type'] == 'circle' else .75, 'y': .5}
            event = dict(contract=2, quizId=qid, sessionId=claim['sessionId'], owner=claim['owner'],
                         generation=self.generation, assessmentRevision=session['assessment_revision'],
                         eventId=f'hotspot-event-{ordinal}', sequence=ordinal, questionOrdinal=ordinal,
                         questionType='hotspot', selected=point, wasCorrect=True, kind='response')
            result = self.client.post('/api/learning-events/study-response', json=event, headers=self.headers)
            self.assertEqual(result.status_code, 200, result.json)
            details.append(dict(attemptQuestionNumber=ordinal, questionType='hotspot', selected=point, wasCorrect=True))
        attempt = dict(quizId=qid, attemptId='hotspot-exam', score=2, total=2, percent=100,
                       mode='Exam', startedAt='2026-10-18T10:00:00+00:00',
                       completedAt='2026-10-18T10:01:00+00:00', timeRemaining=60,
                       sessionId='hotspot-exam-session', responseDetails=details, missedDetails=[])
        saved = self.client.post('/record_attempt', json=attempt, headers=self.headers)
        self.assertEqual(saved.status_code, 200, saved.json)
        return claim, event

    def test_saved_study_exam_mark_identity_grading_and_resume_survive_rebuild(self):
        entry, path, payload = self.pack_quiz()
        claim, event = self.save_hotspot_history(entry['id'], payload)
        self.mark(entry['id'])
        raw, records = path.read_bytes(), self.database()
        for _ in range(2):
            self.assertEqual(dlms._rebuild_registered_quiz_artifacts()['failed'], [])
            self.assertEqual(path.read_bytes(), raw)
            self.assertEqual(self.database(), records)
        # A new HTTP client/SQLite connection reopens the original session;
        # separate-process/browser reopen is covered by the packaged exercise.
        client = dlms.app.test_client()
        from tests.csrf_test_utils import csrf_headers
        resumed = client.post('/api/study/session', json=claim, headers=csrf_headers(client))
        self.assertEqual(resumed.status_code, 200, resumed.json)
        self.assertEqual(resumed.json['session']['id'], claim['sessionId'])
        self.assertEqual(resumed.json['session']['reviewed'], 2)
        self.assertEqual(client.post('/api/learning-events/study-response', json=event,
                                    headers=csrf_headers(client)).status_code, 200)
        from dlms.services.study_sessions import hotspot_result
        for question in payload:
            target = question['target']
            self.assertTrue(hotspot_result({'x': .25 if target['type']=='circle' else .75, 'y': .5}, target))
            self.assertFalse(hotspot_result({'x': .01, 'y': .01}, target))

    def test_absent_corrupt_degraded_or_invalid_authority_is_refused_per_item(self):
        entry, path, payload = self.pack_quiz()
        html = Path(dlms.QUIZ_FOLDER, entry['html'])
        original, previous_html, records = path.read_bytes(), html.read_bytes(), self.database()
        invalid_target = copy.deepcopy(payload)
        invalid_target[0]['target'] = {'type':'circle', 'x':2, 'y':.5, 'radius':.1}
        degraded = copy.deepcopy(payload)
        degraded[0] = {'type':'choice', 'question':payload[0]['question']+' [Image hotspot]',
                       'choices':[dict(label='A', text=payload[0]['target_label'], is_correct=True)]}
        changed_media = copy.deepcopy(payload)
        changed_media[0]['image_alt'] = 'not the saved source'
        string_coordinates = copy.deepcopy(payload)
        circle = next(q for q in string_coordinates if q['target']['type']=='circle')
        circle['target']['x'] = str(circle['target']['x'])
        for data in (None, b'{broken', b'{}', json.dumps(invalid_target).encode(),
                     json.dumps(degraded).encode(), json.dumps(changed_media).encode(),
                     json.dumps(string_coordinates).encode()):
            with self.subTest(data=data):
                if data is None:
                    path.unlink()
                else:
                    path.write_bytes(data)
                result = dlms._rebuild_registered_quiz_artifacts()
                self.assertEqual(result['rebuilt'], 1)  # unrelated ordinary quiz
                self.assertEqual(result['failed'], [entry['id']])
                self.assertIn('hotspot', result['failure_details'][0]['message'])
                self.assertEqual(path.read_bytes() if path.exists() else None, data)
                self.assertEqual(html.read_bytes(), previous_html)
                self.assertEqual(self.database(), records)
                path.write_bytes(original)

    def test_missing_image_and_symlink_runtime_are_refused_without_replacement(self):
        entry, path, payload = self.pack_quiz()
        original = path.read_bytes()
        image = Path(dlms._portable_quiz_media_source(payload[0]['image_url']))
        old_image = image.read_bytes()
        image.unlink()
        self.assertEqual(dlms._rebuild_registered_quiz_artifacts()['failed'], [entry['id']])
        self.assertEqual(path.read_bytes(), original)
        image.write_bytes(b'not a raster')
        self.assertEqual(dlms._rebuild_registered_quiz_artifacts()['failed'], [entry['id']])
        self.assertEqual(path.read_bytes(), original)
        image.write_bytes(old_image)
        other = path.with_suffix('.retained')
        path.rename(other)
        path.symlink_to(other)
        self.assertEqual(dlms._rebuild_registered_quiz_artifacts()['failed'], [entry['id']])
        self.assertTrue(path.is_symlink())
        self.assertEqual(other.read_bytes(), original)

    def test_staging_and_second_promotion_failure_keep_previous_pair_and_history(self):
        entry, path, payload = self.pack_quiz()
        self.save_hotspot_history(entry['id'], payload)
        html = Path(dlms.QUIZ_FOLDER, entry['html'])
        raw, previous_html, records = path.read_bytes(), html.read_bytes(), self.database()
        with mock.patch('dlms.services.hotspot_artifacts.write_preserved_hotspot_json', side_effect=OSError('bounded write fault')):
            self.assertEqual(dlms._rebuild_registered_quiz_artifacts()['failed'], [entry['id']])
        real_replace = os.replace
        def fail_html(source, destination):
            if Path(destination) == html and not Path(source).name.startswith('previous_'):
                raise OSError('bounded promotion fault')
            return real_replace(source, destination)
        with mock.patch.object(dlms.os, 'replace', side_effect=fail_html):
            self.assertEqual(dlms._rebuild_registered_quiz_artifacts()['failed'], [entry['id']])
        self.assertEqual(path.read_bytes(), raw)
        self.assertEqual(html.read_bytes(), previous_html)
        self.assertEqual(self.database(), records)

    def test_changed_target_and_changed_surrogate_reject_stale_mark_requests(self):
        entry, path, payload = self.pack_quiz()
        old = self.mark(entry['id'])
        changed = copy.deepcopy(payload)
        changed[0]['target']['type'] = 'polygon'
        changed[0]['target'] = {'type':'polygon', 'points':[[.1,.1],[.3,.1],[.3,.3]]}
        path.write_text(json.dumps(changed))
        import uuid
        rejected = self.client.post('/api/review-marks/save', json={**old, 'request_id':uuid.uuid4().hex}, headers=self.headers)
        self.assertEqual(rejected.status_code, 409)
        with closing(dlms.get_db()) as conn, conn:
            conn.execute("UPDATE choices SET text='Changed target' WHERE question_id IN (SELECT id FROM questions WHERE quiz_id=?)", (entry['id'],))
        response = self.client.post('/api/review-marks/context', json={
            'quiz_id':entry['id'], 'fingerprint':self.fingerprint(entry['id'])}, headers=self.headers)
        self.assertEqual(response.status_code, 409)

    def test_image_builder_projection_and_ordinary_multi_answer_control(self):
        entry, path, payload = self.pack_quiz()
        data = dlms.load_content_pack_image_dataset(PACK_ID, 'lab_targets')
        data['questions'] = [dict(type='hotspot', question='Builder target',
                                  image_id='lab_diagram', hotspot_id='blue_circle',
                                  concepts=['synthetic diagram'], explanation='Builder explanation')]
        with dlms.app.test_request_context():
            runtime, saved = dlms._quiz_dataset_runtime(PACK_ID, data)
        qid, _ = dlms._publish_quiz('Image builder control', runtime, saved, filename_prefix='builder_control')
        self.mark(qid, (0,))
        multi_id, _ = self.publish(title='Multi-answer control', questions=[self.choice(multi=True)], kind=None)
        self.mark(multi_id, (0,))
        builder_entry = next(e for e in dlms.load_registry() if e['id']==qid)
        builder_path = Path(dlms.DATA_FOLDER, dlms._quiz_artifact_names(builder_entry)[1])
        raw, records = builder_path.read_bytes(), self.database()
        self.assertEqual(dlms._rebuild_registered_quiz_artifacts()['failed'], [])
        self.assertEqual(builder_path.read_bytes(), raw)
        self.assertEqual(self.database(), records)


if __name__ == '__main__':
    unittest.main()
