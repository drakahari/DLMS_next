"""Disposable factual-completion and persisted-library-order checks."""

import unittest
from pathlib import Path

from tests import test_study_sessions as contract
from tests.test_study_sessions import dlms


class QuizSequenceTests(unittest.TestCase):
    setUp = contract.StudySessionTests.setUp
    choice = staticmethod(contract.StudySessionTests.choice)
    publish = contract.StudySessionTests.publish
    fingerprint = contract.StudySessionTests.fingerprint
    payload = contract.StudySessionTests.payload
    save = contract.StudySessionTests.save
    finish = contract.StudySessionTests.finish

    def sequence(self):
        response = self.client.get('/api/dashboard/quiz-activity')
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        return response.json['quiz_sequence']

    def complete(self):
        self.assertEqual(self.save(self.payload(1, correct=False)).status_code, 200)
        self.assertEqual(self.finish(1).status_code, 200)

    def test_opening_and_coverage_alone_do_not_advance_or_create_credit(self):
        next_id, html = self.publish('Next regular', kind=None)
        self.assertEqual(self.sequence()['state'], 'empty')
        self.client.get('/quizzes/' + self.html)
        self.assertEqual(self.sequence()['state'], 'empty')
        self.save(self.payload(1, correct=False))
        self.assertEqual(self.sequence()['state'], 'unfinished')
        self.complete()
        with dlms.get_db() as conn:
            before = list(conn.iterdump())
        seq = self.sequence()
        self.assertEqual(seq['next']['quiz_id'], next_id)
        self.assertEqual(seq['next']['folder'], 'Uncategorized')
        self.assertEqual(seq['next']['review_status'], 'No tracked Study review recorded')
        self.client.get(seq['next']['quiz_url'])
        with dlms.get_db() as conn:
            self.assertEqual(list(conn.iterdump()), before)
        self.assertEqual(self.sequence()['anchor']['quiz_id'], self.quiz_id)

    def test_persisted_library_order_includes_reviewed_and_skips_focused_practice(self):
        generated, _ = self.publish('Exam Plan — CISM', kind='adaptive_study')
        later, later_html = self.publish('Z first', kind=None)
        earlier, earlier_html = self.publish('A second', kind=None)
        self.complete()
        self.assertEqual(self.sequence()['next']['quiz_id'], later)
        response = self.client.post('/save_quiz_order_in_folder', headers=self.headers,
            json={'folder': 'Uncategorized', 'order': [self.html, earlier_html, later_html]})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.sequence()['next']['quiz_id'], earlier)
        # A different app client sees the same saved order, independent of browser sort.
        other = dlms.app.test_client()
        self.assertEqual(other.get('/api/dashboard/quiz-activity').json['quiz_sequence']['next']['quiz_id'], earlier)
        # A later generated response remains focused and cannot replace the anchor.
        claimed = self.client.post('/api/study/session', headers=self.headers, json={
            'quizId': generated, 'sessionId': 'generated', 'owner': 'generated-owner',
            'generation': self.generation, 'fingerprint': self.fingerprint(generated), 'variants': {}}).json['session']
        payload = {**self.payload(1), 'quizId': generated, 'sessionId': 'generated',
                   'owner': 'generated-owner', 'assessmentRevision': claimed['assessment_revision'], 'eventId': 'generated-answer'}
        self.assertEqual(self.save(payload).status_code, 200)
        self.assertEqual(self.sequence()['anchor']['quiz_id'], self.quiz_id)
        # Actually finish the next regular quiz, then finish a fresh anchor
        # review so it is once again the most recent regular durable work.
        claim = {**self.claim_data, 'quizId': earlier, 'sessionId': 'next-review',
                 'fingerprint': self.fingerprint(earlier)}
        tracked = self.client.post('/api/study/session', headers=self.headers, json=claim).json['session']
        answer = {**self.payload(1, correct=False), 'quizId': earlier, 'sessionId': 'next-review',
                  'assessmentRevision': tracked['assessment_revision'], 'eventId': 'next-answer'}
        self.assertEqual(self.save(answer).status_code, 200)
        self.assertEqual(self.client.post('/api/study/finish', headers=self.headers, json=answer).status_code, 200)
        claim = {**self.claim_data, 'sessionId': 'anchor-again'}
        tracked = self.client.post('/api/study/session', headers=self.headers, json=claim).json['session']
        answer = {**self.payload(1, correct=False), 'sessionId': 'anchor-again',
                  'assessmentRevision': tracked['assessment_revision'], 'eventId': 'anchor-again-answer'}
        self.assertEqual(self.save(answer).status_code, 200)
        self.assertEqual(self.client.post('/api/study/finish', headers=self.headers, json=answer).status_code, 200)
        target = self.sequence()['next']
        self.assertEqual(target['quiz_id'], earlier)
        self.assertEqual(target['review_status'], 'Tracked review finished for current content')
        with dlms.get_db() as conn:
            conn.execute("UPDATE questions SET question_text='Substantively revised' WHERE quiz_id=?", (earlier,))
        self.assertEqual(self.sequence()['next']['review_status'], 'Content changed since its saved review')

    def test_changed_content_and_gapped_completion_never_advance(self):
        self.publish('Next', kind=None)
        self.complete()
        with dlms.get_db() as conn:
            conn.execute('UPDATE questions SET question_text=? WHERE quiz_id=?', ('Edited', self.quiz_id))
        self.assertEqual(self.sequence()['state'], 'changed')

    def test_missing_saves_and_artifact_changes_are_explicit(self):
        self.publish('Next', kind=None)
        self.save(self.payload(2))
        with dlms.get_db() as conn:
            conn.execute("UPDATE study_sessions SET completed_at='2026-01-01T00:00:00Z' WHERE id='session-one'")
        self.assertEqual(self.sequence()['state'], 'incomplete_saves')
        self.save(self.payload(1))
        entry = next(e for e in dlms.load_registry() if e['id'] == self.quiz_id)
        _, name = dlms._quiz_artifact_names(entry)
        p = Path(dlms.DATA_FOLDER) / name
        p.write_text(p.read_text() + '\n')
        self.assertEqual(self.sequence()['state'], 'changed')

    def test_live_folder_moves_renames_and_end_never_cross_folders(self):
        next_id, _ = self.publish('Next', kind=None)
        outside, _ = self.publish('Other folder', kind=None)
        registry = dlms.load_registry()
        for e in registry:
            e['folder'] = 'Other' if e['id'] == outside else 'CISM'
        dlms.save_registry(registry)
        self.complete()
        self.assertEqual(self.sequence()['folder'], 'CISM')
        self.assertEqual(self.sequence()['next']['quiz_id'], next_id)
        for e in registry:
            if e['folder'] == 'CISM': e['folder'] = 'Renamed CISM'
        dlms.save_registry(registry)
        self.assertEqual(self.sequence()['folder'], 'Renamed CISM')
        for e in registry:
            if e['id'] == self.quiz_id: e['folder'] = 'Moved anchor'
        dlms.save_registry(registry)
        self.assertEqual(self.sequence()['state'], 'end')
        self.assertIsNone(self.sequence()['next'])
        dlms.save_registry([e for e in registry if e['id'] != self.quiz_id])
        self.assertEqual(self.sequence()['state'], 'unavailable')

    def test_hidden_excluded_and_missing_next_are_not_silently_skipped(self):
        next_id, html = self.publish('Next', kind=None)
        self.publish('After next', kind=None)
        self.complete()
        registry = dlms.load_registry()
        next(e for e in registry if e['id'] == next_id)['hidden'] = True
        dlms.save_registry(registry)
        self.assertEqual(self.sequence()['state'], 'next_hidden')
        next(e for e in registry if e['id'] == next_id)['hidden'] = False
        dlms.save_registry(registry)
        config = dlms.load_portal_config()
        config['excluded_learning_folders'] = ['Uncategorized']
        dlms._write_settings_portal_config(config)
        self.assertEqual(self.sequence()['state'], 'excluded')
        config['excluded_learning_folders'] = []
        dlms._write_settings_portal_config(config)
        (Path(dlms.QUIZ_FOLDER) / html).unlink()
        self.assertEqual(self.sequence()['state'], 'next_unavailable')
        self.assertEqual(self.sequence()['next']['quiz_id'], next_id)

    def test_latest_unfinished_session_does_not_use_earlier_completion(self):
        self.publish('Next', kind=None)
        self.complete()
        claim = {**self.claim_data, 'sessionId': 'new-review'}
        new = self.client.post('/api/study/session', headers=self.headers, json=claim).json['session']
        self.assertEqual(self.sequence()['state'], 'next')  # merely opening does not replace evidence
        payload = {**self.payload(1), 'sessionId': 'new-review', 'eventId': 'new-review-answer',
                   'assessmentRevision': new['assessment_revision']}
        self.assertEqual(self.save(payload).status_code, 200)
        self.assertEqual(self.sequence()['state'], 'unfinished')
        self.assertEqual(self.sequence()['anchor']['session_id'], 'new-review')

    def test_empty_quiz_and_deleted_next_stop_without_skipping(self):
        next_id, _ = self.publish('Next', kind=None)
        self.publish('Later', kind=None)
        self.complete()
        with dlms.get_db() as conn:
            conn.execute('PRAGMA foreign_keys=ON')
            conn.execute('DELETE FROM questions WHERE quiz_id=?', (next_id,))
        self.assertEqual(self.sequence()['state'], 'next_unavailable')
        self.assertEqual(self.sequence()['next']['availability'], 'Quiz has no current questions')
        with dlms.get_db() as conn:
            conn.execute('PRAGMA foreign_keys=ON')
            conn.execute('DELETE FROM quizzes WHERE id=?', (next_id,))
        self.assertEqual(self.sequence()['state'], 'next_unavailable')
        self.assertEqual(self.sequence()['next']['quiz_id'], next_id)

    def test_missing_generation_metadata_stops_instead_of_guessing_from_title(self):
        generated, _ = self.publish('Exam Plan — CISM', kind='adaptive_study')
        regular, _ = self.publish('Next regular', kind=None)
        self.complete()
        with dlms.get_db() as conn:
            conn.execute('PRAGMA foreign_keys=ON')
            conn.execute('DELETE FROM quizzes WHERE id=?', (generated,))
        # Publishing keeps authoritative generation_kind in the DB. If that
        # record is gone, this title alone cannot establish focused lineage.
        self.assertEqual(self.sequence()['state'], 'next_unavailable')
        self.assertEqual(self.sequence()['next']['quiz_id'], generated)
        self.assertNotEqual(self.sequence()['next']['quiz_id'], regular)

    def test_legacy_answers_never_invent_an_anchor_or_completion(self):
        self.publish('Next', kind=None)
        with dlms.get_db() as conn:
            question = conn.execute('SELECT id FROM questions WHERE quiz_id=?', (self.quiz_id,)).fetchone()[0]
            conn.execute("INSERT INTO study_legacy_responses(quiz_id,question_id,session_id,mode,was_correct,occurred_at) VALUES (?,?,'old','Study',1,'2020-01-01 12:00:00')", (self.quiz_id, question))
        self.assertEqual(self.sequence()['state'], 'empty')

    def test_hidden_folder_and_artifact_missing_anchor_are_explained(self):
        self.publish('Next', kind=None)
        registry = dlms.load_registry()
        for entry in registry: entry['folder'] = 'CISM'
        dlms.save_registry(registry)
        self.complete()
        config = dlms.load_portal_config()
        config.update(quiz_folders=['CISM'], hidden_quiz_folders=['CISM'])
        dlms._write_settings_portal_config(config)
        self.assertEqual(self.sequence()['state'], 'hidden')
        config['hidden_quiz_folders'] = []
        dlms._write_settings_portal_config(config)
        (Path(dlms.QUIZ_FOLDER) / self.html).unlink()
        self.assertEqual(self.sequence()['state'], 'unavailable')
