import os, tempfile, unittest, uuid
from unittest import mock

_TEMP = tempfile.TemporaryDirectory(prefix="dlms-learning-actions-tests-")
os.environ["QUIZAPP_DATA_DIR"] = _TEMP.name
from tests._isolation import ensure_test_data_isolation
ensure_test_data_isolation()
import app as dlms


class LearningActionsTests(unittest.TestCase):
    def _weak_quiz(self, concept):
        quiz_id = dlms.save_quiz_to_db(f"Review {uuid.uuid4()}", f"review-{uuid.uuid4()}.txt", [{
            "number": 1,
            "question": "Which answer is correct?",
            "choices": [
                {"label": "A", "text": "Correct", "is_correct": True},
                {"label": "B", "text": "Wrong", "is_correct": False},
            ],
            "explanation": "Test explanation",
            "concepts": [concept],
        }])
        conn = dlms.get_db(); cur = conn.cursor()
        qid = cur.execute("SELECT id FROM questions WHERE quiz_id=?", (quiz_id,)).fetchone()[0]
        for i, result in enumerate([False, False, True, False, False]):
            dlms._record_learning_event(cur, event_type="exam_answer", quiz_id=quiz_id, question_id=qid, attempt_id=f"review-{i}", mode="Exam", was_correct=result)
        conn.commit(); conn.close()
        return quiz_id, qid

    def test_smart_review_candidates_use_weak_topics(self):
        concept = f"SmartReview-{uuid.uuid4()}"
        _, qid = self._weak_quiz(concept)
        conn = dlms.get_db(); cur = conn.cursor()
        candidates, weak = dlms._smart_review_candidates(cur)
        conn.close()
        self.assertTrue(any(t["name"] == concept for t in weak))
        self.assertTrue(any(
            any(topic.get("name") == concept for topic in c.get("topics", []))
            for c in candidates
        ))

    def test_question_payload_preserves_concepts_and_choices(self):
        concept = f"Payload-{uuid.uuid4()}"
        _, qid = self._weak_quiz(concept)
        conn = dlms.get_db(); cur = conn.cursor()
        item = dlms._question_payload_from_db(cur, qid)
        conn.close()
        self.assertIn(concept, item["concepts"])
        self.assertEqual(item["correct"], ["A"])
        self.assertEqual(len(item["choices"]), 2)

    def test_learning_profile_surfaces_weakness_and_recommendation(self):
        concept = f"ProfileWeak-{uuid.uuid4()}"
        self._weak_quiz(concept)
        conn = dlms.get_db(); cur = conn.cursor()
        profile = dlms._learning_profile_payload(cur)
        conn.close()
        self.assertGreaterEqual(profile["status_counts"]["weak"], 1)
        self.assertTrue(any(t["name"] == concept for t in profile["weakest_topics"]))
        self.assertEqual(profile["recommendation"]["kind"], "review_weak")

    def test_learning_profile_api_shape(self):
        client = dlms.app.test_client()
        response = client.get("/api/learning-profile")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertIn("summary", payload)
        self.assertIn("status_counts", payload)
        self.assertIn("activity", payload)
        self.assertIn("recommendation", payload)

    def test_app_learning_composition_uses_patchable_helper_names(self):
        topic = {"concept_id": 7, "name": "Patched", "evidence": 3}
        retention = {"review_state": "due", "retained_mastery": 42.0}
        marker = object()
        with mock.patch.object(
            dlms, "_learning_intelligence_topics", return_value=[topic.copy()]
        ) as topics_helper, mock.patch.object(
            dlms, "_retention_schedule_for_topic", return_value=retention
        ) as retention_helper:
            result = dlms._learning_topics_with_retention(marker, now="frozen-now")

        self.assertEqual(result, [{**topic, **retention}])
        topics_helper.assert_called_once_with(marker, now="frozen-now")
        retention_helper.assert_called_once_with(
            {**topic, **retention}, now="frozen-now"
        )

    def test_concept_normalization_preserves_order_case_and_limits(self):
        concepts = dlms._normalize_concept_names(
            "  Civil   Procedure ; Evidence\nCIVIL PROCEDURE, Crimé "
        )
        self.assertEqual(concepts, ["Civil Procedure", "Evidence", "Crimé"])

    def test_smart_review_generation_hands_prepared_quiz_to_app_publisher(self):
        weak = [{
            "concept_id": 1, "name": "Contracts", "mastery": 35.0,
            "accuracy": 20.0, "evidence": 5,
        }]
        candidate = {"question_id": 17, "topics": weak}
        question = {
            "number": 99, "type": "choice", "question": "Offer?",
            "choices": [{"label": "A", "text": "Yes", "is_correct": True}],
            "correct": ["A"], "concepts": ["Contracts"],
        }
        with dlms.app.test_request_context(
            "/smart-review/generate", method="POST", data={"question_count": "5"}
        ), mock.patch.object(
            dlms, "_smart_review_candidates", return_value=([candidate], weak)
        ), mock.patch.object(
            dlms, "_smart_review_select_candidates", return_value=[candidate]
        ), mock.patch.object(
            dlms, "_question_payload_from_db", return_value=question.copy()
        ), mock.patch.object(
            dlms, "_publish_quiz", return_value=(23, "smart-review.html")
        ) as publisher:
            response = dlms.app.view_functions[
                "learning.smart_review_generate"
            ]()

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.location, "/quizzes/smart-review.html")
        publisher.assert_called_once_with(
            "Smart Review — Contracts",
            [{**question, "number": 1}],
            filename_prefix="smart_review",
            exam_minutes=90,
            snapshot_existing_assets=True,
        )

    def test_smart_review_publication_failure_still_propagates(self):
        weak = [{
            "concept_id": 1, "name": "Contracts", "mastery": 35.0,
            "accuracy": 20.0, "evidence": 5,
        }]
        candidate = {"question_id": 17, "topics": weak}
        question = {
            "number": 1, "type": "choice", "question": "Offer?",
            "choices": [{"label": "A", "text": "Yes", "is_correct": True}],
            "correct": ["A"], "concepts": ["Contracts"],
        }
        with dlms.app.test_request_context(
            "/smart-review/generate", method="POST", data={"question_count": "5"}
        ), mock.patch.object(
            dlms, "_smart_review_candidates", return_value=([candidate], weak)
        ), mock.patch.object(
            dlms, "_smart_review_select_candidates", return_value=[candidate]
        ), mock.patch.object(
            dlms, "_question_payload_from_db", return_value=question
        ), mock.patch.object(
            dlms, "_publish_quiz", side_effect=RuntimeError("publication failed")
        ):
            with self.assertRaisesRegex(RuntimeError, "publication failed"):
                dlms.app.view_functions[
                    "learning.smart_review_generate"
                ]()


if __name__ == "__main__":
    unittest.main()


class SmartReviewDiversityRegressionTests(unittest.TestCase):
    def _make_quiz(self, title, source_file, questions):
        return dlms.save_quiz_to_db(title, source_file, questions)

    def _make_concept_weak(self, concept, quiz_id, question_id):
        conn = dlms.get_db(); cur = conn.cursor()
        for i, result in enumerate([False, False, False, True, False]):
            dlms._record_learning_event(
                cur,
                event_type="exam_answer",
                quiz_id=quiz_id,
                question_id=question_id,
                attempt_id=f"weak-{concept}-{i}-{uuid.uuid4()}",
                mode="Exam",
                was_correct=result,
            )
        conn.commit(); conn.close()

    def test_smart_review_excludes_prior_smart_review_clones(self):
        concept = f"NoClone-{uuid.uuid4()}"
        source_quiz = self._make_quiz("Original Source", f"original-{uuid.uuid4()}.html", [{
            "number": 1,
            "question": "Unique source question for clone regression?",
            "choices": [{"label":"A","text":"Yes","is_correct":True},{"label":"B","text":"No","is_correct":False}],
            "concepts": [concept],
        }])
        conn = dlms.get_db(); cur = conn.cursor()
        source_qid = cur.execute("SELECT id FROM questions WHERE quiz_id=?", (source_quiz,)).fetchone()[0]
        conn.close()
        self._make_concept_weak(concept, source_quiz, source_qid)

        self._make_quiz("Smart Review — Old", f"smart_review_{uuid.uuid4()}.html", [{
            "number": 1,
            "question": "Unique source question for clone regression?",
            "choices": [{"label":"A","text":"Yes","is_correct":True},{"label":"B","text":"No","is_correct":False}],
            "concepts": [concept],
        }])

        conn = dlms.get_db(); cur = conn.cursor()
        candidates, weak = dlms._smart_review_candidates(cur)
        conn.close()
        matching = [c for c in candidates if "clone regression" in c["question_text"]]
        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0]["question_id"], source_qid)

    def test_smart_review_selection_rotates_across_weak_concepts(self):
        c1 = f"DiversityA-{uuid.uuid4()}"
        c2 = f"DiversityB-{uuid.uuid4()}"
        q1 = self._make_quiz("Diversity Source A", f"div-a-{uuid.uuid4()}.html", [{
            "number": 1, "question": "Diversity question A?",
            "choices": [{"label":"A","text":"Yes","is_correct":True},{"label":"B","text":"No","is_correct":False}],
            "concepts": [c1],
        }])
        q2 = self._make_quiz("Diversity Source B", f"div-b-{uuid.uuid4()}.html", [{
            "number": 1, "question": "Diversity question B?",
            "choices": [{"label":"A","text":"Yes","is_correct":True},{"label":"B","text":"No","is_correct":False}],
            "concepts": [c2],
        }])
        conn = dlms.get_db(); cur = conn.cursor()
        qid1 = cur.execute("SELECT id FROM questions WHERE quiz_id=?", (q1,)).fetchone()[0]
        qid2 = cur.execute("SELECT id FROM questions WHERE quiz_id=?", (q2,)).fetchone()[0]
        conn.close()
        self._make_concept_weak(c1, q1, qid1)
        self._make_concept_weak(c2, q2, qid2)

        conn = dlms.get_db(); cur = conn.cursor()
        candidates, weak = dlms._smart_review_candidates(cur)
        selected = dlms._smart_review_select_candidates(candidates, weak, 10)
        conn.close()
        texts = {c["question_text"] for c in selected}
        self.assertIn("Diversity question A?", texts)
        self.assertIn("Diversity question B?", texts)
        self.assertEqual(len([c for c in selected if c["question_text"] in texts]), len({c["question_text"] for c in selected}))
