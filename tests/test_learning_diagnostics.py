import os, tempfile, unittest, uuid

_TEMP = tempfile.TemporaryDirectory(prefix='dlms-learning-diagnostics-tests-')
os.environ['QUIZAPP_DATA_DIR'] = _TEMP.name
from tests._isolation import ensure_test_data_isolation
ensure_test_data_isolation()
import app as dlms


class LearningDiagnosticsTests(unittest.TestCase):
    def _quiz(self, concept=None, question='Which option is correct?'):
        quiz_id = dlms.save_quiz_to_db(f'Diagnostics {uuid.uuid4()}', f'diagnostics-{uuid.uuid4()}.html', [{
            'number': 1,
            'question': question,
            'choices': [
                {'label':'A','text':'Correct answer','is_correct':True},
                {'label':'B','text':'Common distractor','is_correct':False},
                {'label':'C','text':'Unused distractor','is_correct':False},
            ],
            'concepts': [concept] if concept else [],
        }])
        conn=dlms.get_db(); cur=conn.cursor()
        qid=cur.execute('SELECT id FROM questions WHERE quiz_id=?',(quiz_id,)).fetchone()[0]
        conn.close()
        return quiz_id,qid

    def _event(self, quiz_id, qid, i, correct, selected):
        conn=dlms.get_db(); cur=conn.cursor()
        dlms._record_learning_event(cur,event_type='exam_answer',quiz_id=quiz_id,question_id=qid,
                                    attempt_id=f'diag-{i}-{uuid.uuid4()}',mode='Exam',was_correct=correct,
                                    response={'selected':selected,'question_type':'choice'})
        conn.commit(); conn.close()

    def test_confusion_pair_detects_repeated_wrong_to_correct(self):
        quiz_id,qid=self._quiz(f'Confusion-{uuid.uuid4()}')
        for i in range(3): self._event(quiz_id,qid,i,False,['B'])
        conn=dlms.get_db(); cur=conn.cursor(); payload=dlms._question_diagnostics_payload(cur); conn.close()
        pair=next((p for p in payload['confusions'] if p['selected_text']=='Common distractor' and p['correct_text']=='Correct answer'),None)
        self.assertIsNotNone(pair)
        self.assertEqual(pair['count'],3)

    def test_quality_flags_strong_and_unused_distractors(self):
        quiz_id,qid=self._quiz(f'Quality-{uuid.uuid4()}', question=f'Quality question {uuid.uuid4()}?')
        for i in range(8): self._event(quiz_id,qid,i,i>=3,['A'] if i>=3 else ['B'])
        conn=dlms.get_db(); cur=conn.cursor(); payload=dlms._question_diagnostics_payload(cur); conn.close()
        row=next(q for q in payload['questions'] if q['question_text'].startswith('Quality question'))
        self.assertEqual(row['status'],'review')
        self.assertIn('Strong distractor: B',row['signals'])
        self.assertIn('Unused distractor: C',row['signals'])

    def test_review_clones_group_with_identical_source_question(self):
        question=f'Grouped diagnostic question {uuid.uuid4()}?'
        quiz_id,qid=self._quiz(f'Group-{uuid.uuid4()}',question=question)
        clone=dlms.save_quiz_to_db('Smart Review — Diagnostics',f'smart_review_{uuid.uuid4()}.html',[{
            'number':1,'question':question,
            'choices':[{'label':'A','text':'Correct answer','is_correct':True},{'label':'B','text':'Common distractor','is_correct':False},{'label':'C','text':'Unused distractor','is_correct':False}],
        }])
        conn=dlms.get_db(); cqid=conn.execute('SELECT id FROM questions WHERE quiz_id=?',(clone,)).fetchone()[0]; conn.close()
        self._event(quiz_id,qid,1,True,['A']); self._event(clone,cqid,2,False,['B'])
        conn=dlms.get_db(); cur=conn.cursor(); payload=dlms._question_diagnostics_payload(cur); conn.close()
        matches=[q for q in payload['questions'] if q['question_text']==question]
        self.assertEqual(len(matches),1)
        self.assertEqual(matches[0]['evidence'],2)
        self.assertEqual(matches[0]['source_question_count'],1)

    def test_learning_diagnostics_api_shape(self):
        client=dlms.app.test_client(); response=client.get('/api/learning-diagnostics')
        self.assertEqual(response.status_code,200)
        payload=response.get_json()
        self.assertIn('summary',payload); self.assertIn('confusions',payload); self.assertIn('questions',payload); self.assertIn('model',payload)


if __name__=='__main__': unittest.main()
