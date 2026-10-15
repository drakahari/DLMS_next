"""Read-only history presentation over disposable factual records."""
import json
import re
import unittest
from unittest import mock
from urllib.parse import urlsplit,parse_qs
from html import unescape

from tests import test_study_sessions as foundation
from dlms.services import study_history as history

dlms = foundation.dlms


class StudyHistoryTests(unittest.TestCase):
    setUp = foundation.StudySessionTests.setUp
    choice = staticmethod(foundation.StudySessionTests.choice)
    publish = foundation.StudySessionTests.publish
    fingerprint = foundation.StudySessionTests.fingerprint
    payload = foundation.StudySessionTests.payload
    save = foundation.StudySessionTests.save

    def seed(self, count=61, legacy=63):
        self.save(self.payload(1,correct=False));self.save(self.payload(2))
        with dlms.get_db() as conn:
            row=dict(conn.execute('SELECT * FROM study_sessions').fetchone())
            responses=[dict(r) for r in conn.execute('SELECT * FROM study_responses')]
            conn.execute('DELETE FROM study_sessions')
            for n in range(count):
                session={**row,'id':f'history-{n:03}','purpose':'focused' if n%2 else 'regular','completed_at':row['last_activity_at'] if n%3==0 else None}
                conn.execute('INSERT INTO study_sessions('+','.join(session)+') VALUES('+','.join('?' for _ in session)+')',tuple(session.values()))
                for r in responses:
                    response={**r,'session_id':session['id'],'event_id':f'history-{n}-{r["sequence"]}'}
                    conn.execute('INSERT INTO study_responses('+','.join(response)+') VALUES('+','.join('?' for _ in response)+')',tuple(response.values()))
            for n in range(legacy):
                conn.execute('INSERT INTO study_legacy_responses(quiz_id,question_id,was_correct,occurred_at) VALUES(?,?,?,?)',(self.quiz_id,self.session['manifest'][0]['id'],n%2,'2026-03-08 06:59:00'))

    def link(self, html, label):
        match=re.search(r'href="([^"]+)"[^>]*>'+re.escape(label)+r'</a>',html)
        return unescape(match[1]) if match else None

    def test_large_history_independent_keyset_boundaries_and_no_eager_details(self):
        self.seed()
        with mock.patch.object(foundation.study,'public_session',side_effect=AssertionError('eager details')):
            url='/study-history';seen=[]
            while url:
                html=self.client.get(url).get_data(as_text=True)
                ids=re.findall(r'data-session-id="([^"]+)"',html)
                self.assertLessEqual(len(ids),20);seen.extend(ids)
                self.assertLessEqual(len(re.findall(r'data-legacy-id=',html)),25)
                url=self.link(html,'Older sessions')
        self.assertEqual(len(seen),61);self.assertEqual(len(set(seen)),61)
        self.assertEqual(seen,sorted(seen,reverse=True))
        first=self.client.get('/study-history').get_data(as_text=True)
        second_url=self.link(first,'Older sessions');second=self.client.get(second_url).get_data(as_text=True)
        previous=self.client.get(self.link(second,'Newer sessions')).get_data(as_text=True)
        self.assertEqual(re.findall(r'data-session-id="([^"]+)"',first),re.findall(r'data-session-id="([^"]+)"',previous))
        legacy_url=self.link(second,'Older legacy responses')
        self.assertEqual(parse_qs(urlsplit(legacy_url).query)['sessions_before'],parse_qs(urlsplit(second_url).query)['sessions_before'])
        url='/study-history';seen=[]
        while url:
            html=self.client.get(url).get_data(as_text=True);seen.extend(re.findall(r'data-legacy-id="(\d+)"',html));url=self.link(html,'Older legacy responses')
        self.assertEqual(len(seen),63);self.assertEqual(len(set(seen)),63)
        # Updates do not move old sessions, nor does deleting the boundary skip a neighbor.
        with dlms.get_db() as conn:
            conn.execute("UPDATE study_sessions SET last_activity_at='2099-01-01T00:00:00Z' WHERE id='history-000'")
            conn.execute("DELETE FROM study_sessions WHERE id='history-041'")
        ids=re.findall(r'data-session-id="([^"]+)"',self.client.get(second_url).get_data(as_text=True))
        self.assertEqual(ids[0],'history-040')

    def test_global_empty_later_empty_and_legacy_only_are_distinct(self):
        empty=self.client.get('/study-history').get_data(as_text=True)
        self.assertIn('No saved Study history yet',empty)
        self.seed(count=1)
        later=self.client.get('/study-history?page=2').get_data(as_text=True)
        self.assertIn('No Study sessions on this page',later)
        self.assertNotIn('No saved Study sessions yet',later)
        self.assertIn('Legacy saved responses (63)',later)
        with dlms.get_db() as conn:conn.execute('DELETE FROM study_sessions')
        legacy=self.client.get('/study-history').get_data(as_text=True)
        self.assertIn('No durable Study sessions recorded',legacy)
        self.assertNotIn('No saved Study history yet',legacy)
        for query in ('?page=oops','?sessions_before=-1','?legacy_after=9999999999999999999999999999999'):
            self.assertEqual(self.client.get('/study-history'+query).status_code,200)

    def test_gaps_corrections_identity_and_read_only_detail(self):
        self.seed(count=3,legacy=1)
        with dlms.get_db() as conn:
            conn.execute("DELETE FROM study_responses WHERE session_id='history-002' AND sequence=1")
            before=list(conn.iterdump())
        html=self.client.get('/study-history').get_data(as_text=True)
        self.assertIn('Earlier saves missing · first outcomes unverified',html)
        self.assertIn('Full quiz review',html);self.assertIn('Focused session',html)
        self.assertIn('Finished',html);self.assertIn('Unfinished',html)
        detail=self.client.get('/study-history/session/history-001?fragment=1').get_data(as_text=True)
        self.assertIn('first graded answer incorrect',detail)
        self.assertIn('A later correct answer was saved',detail)
        self.assertIn('history-001',detail)
        gap=self.client.get('/study-history/session/history-002?fragment=1').get_data(as_text=True)
        self.assertIn('First outcome unverified',gap)
        self.assertNotIn('first graded answer correct',gap)
        self.assertEqual(self.client.get('/study-history/session/missing').status_code,404)
        with dlms.get_db() as conn:self.assertEqual(before,list(conn.iterdump()))

    def test_question_details_are_paginated_and_escape_titles(self):
        self.seed(count=1,legacy=0)
        with dlms.get_db() as conn:
            row=dict(conn.execute('SELECT * FROM study_responses LIMIT 1').fetchone())
            conn.execute('DELETE FROM study_responses')
            for n in range(1,57):
                r={**row,'event_id':f'detail-{n}','sequence':n,'ordinal':n}
                conn.execute('INSERT INTO study_responses('+','.join(r)+') VALUES('+','.join('?' for _ in r)+')',tuple(r.values()))
            conn.execute("UPDATE quizzes SET title='<script>unsafe</script>'")
        html=self.client.get('/study-history').get_data(as_text=True)
        self.assertIn('&lt;script&gt;unsafe',html);self.assertNotIn('<script>unsafe',html)
        first=self.client.get('/study-history/session/history-000?fragment=1').get_data(as_text=True)
        self.assertEqual(len(re.findall(r'<li value=',first)),25)
        second=self.client.get(self.link(first,'Next question details')+'&fragment=1').get_data(as_text=True)
        self.assertIn('<li value="26">',second)
        self.assertEqual(len(re.findall(r'<li value=',second)),25)

    def test_recorded_finish_does_not_invent_missing_saved_coverage(self):
        self.seed(count=1,legacy=0)
        with dlms.get_db() as conn:conn.execute('DELETE FROM study_responses')
        page=self.client.get('/study-history').get_data(as_text=True)
        self.assertIn('0 / 1 reviewed',page)
        self.assertIn('Recorded finish has incomplete saved coverage',page)
        self.assertIn('Finish recorded; saves incomplete',page)
        detail=self.client.get('/study-history/session/history-000?fragment=1').get_data(as_text=True)
        self.assertIn('not repaired automatically',detail)

    def test_later_correction_is_visible_even_after_first_correct(self):
        self.save(self.payload(1));self.save(self.payload(2,correct=False));self.save(self.payload(3))
        detail=self.client.get('/study-history/session/session-one?fragment=1').get_data(as_text=True)
        self.assertIn('first graded answer correct',detail)
        self.assertIn('A later correct answer was saved after an incorrect answer',detail)
        self.assertIn('earlier incorrect responses remain recorded',detail)
        self.assertNotIn('the first mistake remains',detail)

    def test_thousand_session_history_keeps_initial_response_bounded(self):
        self.seed(count=1001,legacy=1503)
        with mock.patch.object(foundation.study,'public_session',side_effect=AssertionError('eager detail scan')):
            page=self.client.get('/study-history').get_data(as_text=True)
        self.assertEqual(len(re.findall('data-session-id=',page)),20)
        self.assertEqual(len(re.findall('data-legacy-id=',page)),25)
        self.assertIn('Showing 20 of 1001 sessions',page)
        self.assertIn('Legacy saved responses (1503)',page)
