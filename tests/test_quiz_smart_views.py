import json
from datetime import datetime, timezone
from pathlib import Path

from dlms.persistence.pdf_banks import _ocr_generated_quiz_ids
from dlms.services.quiz_smart_views import (
    LOW_SCORE_PERCENT,
    RECENTLY_ADDED_DAYS,
    build_quiz_smart_views,
    normalize_smart_view,
)
from tests.current_schema import bootstrap_current_schema_database
from tests._isolation import ensure_test_data_isolation

ensure_test_data_isolation()
import app as dlms


def _seed_quiz(database, quiz_id, title, source_file, question_id):
    database.seed_quiz(
        title,
        source_file,
        [{
            "id": question_id,
            "number": 1,
            "question": f"Neutral prompt {quiz_id}?",
            "choices": [
                {"label": "A", "text": "One", "is_correct": True},
                {"label": "B", "text": "Two", "is_correct": False},
            ],
        }],
        quiz_id=quiz_id,
    )


def test_smart_views_use_canonical_data_and_latest_attempt(tmp_path):
    database = bootstrap_current_schema_database(
        tmp_path / "results.db", bootstrap_database=dlms.bootstrap_database
    )
    registry = []
    for quiz_id, source_file, question_id in (
        (1, "due.html", 101),
        (2, "recent.html", 201),
        (3, "low.html", 301),
        (4, "healthy.html", 401),
        (5, "ocr_matching_terms.html", 501),
        (6, "bank_generated.html", 601),
        (7, "plain_pdf_bank.html", 701),
        (8, "ocrXmatching_near_miss.html", 801),
    ):
        _seed_quiz(database, quiz_id, f"Quiz {quiz_id}", source_file, question_id)
        registry.append({
            "id": quiz_id,
            "title": f"Quiz {quiz_id}",
            "html": source_file,
            "folder": "Course",
        })

    connection = database.connect()
    original_registry = json.loads(json.dumps(registry))
    try:
        cursor = connection.cursor()
        cursor.execute("UPDATE quizzes SET created_at = '2026-07-01 12:00:00'")
        cursor.execute(
            "UPDATE quizzes SET created_at = '2026-09-01 12:00:00' WHERE id IN (2, 3)"
        )
        cursor.executemany(
            """
            INSERT INTO attempts (
                id, quiz_id, started_at, completed_at, score, total, percent, mode
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                ("low-old", 3, "2026-08-01", "2026-08-01", 9, 10, 90, "Exam"),
                ("low-latest", 3, "2026-09-02", "2026-09-02", 7, 10, 70, "Exam"),
                ("healthy-old", 4, "2026-08-01", "2026-08-01", 4, 10, 40, "Exam"),
                ("healthy-latest", 4, "2026-09-02", "2026-09-02", 8, 10, 80, "Exam"),
            ],
        )
        connection.commit()

        def schedule(_cursor, now=None):
            assert now == datetime(2026, 9, 13, 12, tzinfo=timezone.utc)
            return {
                "questions": [
                    {
                        "question_id": 101,
                        "source_question_ids": [101],
                        "schedule_state": "overdue",
                        "next_review": "2026-09-10T12:00:00+00:00",
                    },
                    {
                        "question_id": 201,
                        "source_question_ids": [201],
                        "schedule_state": "upcoming",
                    },
                ]
            }

        result = build_quiz_smart_views(
            cursor,
            registry,
            native_schedule=schedule,
            bank_ocr_quiz_ids={6},
            now=datetime(2026, 9, 13, 12, tzinfo=timezone.utc),
        )
    finally:
        connection.close()

    assert set(result["matches"]["needs-review"]) == {1}
    assert result["matches"]["needs-review"][1]["badge"] == "Overdue"
    assert set(result["matches"]["recently-added"]) == {2, 3}
    assert set(result["matches"]["low-score"]) == {3}
    assert result["matches"]["low-score"][3]["percent"] == 70.0
    assert set(result["matches"]["ocr-imported"]) == {5, 6}
    assert 7 not in result["matches"]["ocr-imported"]
    assert 8 not in result["matches"]["ocr-imported"]
    assert result["matches"]["unfinished"] == {}
    assert result["matches"]["generated-practice"] == {}
    assert result["generation"] == {}
    assert result["provenance"] == {}
    assert registry == original_registry
    assert [view["key"] for view in result["views"]] == [
        "needs-review", "recently-added", "low-score", "unfinished",
        "ocr-imported", "generated-practice",
    ]
    assert RECENTLY_ADDED_DAYS == 30
    assert LOW_SCORE_PERCENT == 75.0


def test_needs_review_maps_canonical_shared_source_questions_to_each_quiz(tmp_path):
    database = bootstrap_current_schema_database(
        tmp_path / "results.db", bootstrap_database=dlms.bootstrap_database
    )
    _seed_quiz(database, 1, "First", "first.html", 101)
    _seed_quiz(database, 2, "Second", "second.html", 201)
    registry = [
        {"id": 2, "title": "Second", "html": "second.html"},
        {"id": 1, "title": "First", "html": "first.html"},
    ]
    connection = database.connect()
    try:
        result = build_quiz_smart_views(
            connection.cursor(),
            registry,
            native_schedule=lambda _cursor, now=None: {"questions": [{
                "question_id": 101,
                "source_question_ids": [101, 201],
                "schedule_state": "due",
                "next_review": "2026-09-13T12:00:00+00:00",
            }]},
            now=datetime(2026, 9, 13, 12, tzinfo=timezone.utc),
        )
    finally:
        connection.close()

    assert set(result["matches"]["needs-review"]) == {1, 2}
    assert result["matches"]["needs-review"][1]["due"] == 1
    assert result["matches"]["needs-review"][2]["due"] == 1


def test_ocr_bank_provenance_accepts_only_explicit_ocr_sources(tmp_path):
    (tmp_path / "ocr.json").write_text(json.dumps({
        "source_kind": "user-provided-screenshot-ocr",
        "generated_quizzes": [{"quiz_id": 7}, {"quiz_id": 8}],
    }), encoding="utf-8")
    (tmp_path / "digital.json").write_text(json.dumps({
        "source_kind": "user-provided-pdf",
        "generated_quizzes": [{"quiz_id": 9}],
    }), encoding="utf-8")
    (tmp_path / "near-miss.json").write_text(json.dumps({
        "source_kind": "user-provided-pdf-ocr-preflight",
        "generated_quizzes": [{"quiz_id": 10}],
    }), encoding="utf-8")
    (tmp_path / "malformed.json").write_text("{", encoding="utf-8")

    messages = []
    assert _ocr_generated_quiz_ids(tmp_path, print_message=messages.append) == {7, 8}
    assert len(messages) == 1
    assert "malformed.json" in messages[0]

    missing_folder = tmp_path / "not-created-by-derived-view"
    assert _ocr_generated_quiz_ids(missing_folder) == set()
    assert not missing_folder.exists()


def test_smart_view_keys_are_strict_and_case_normalized():
    assert normalize_smart_view(" Needs-Review ") == "needs-review"
    assert normalize_smart_view("unfinished") == "unfinished"
    assert normalize_smart_view("low score") is None
    assert normalize_smart_view("recently-added-extra") is None
    assert normalize_smart_view("GENERATED-PRACTICE") == "generated-practice"
    assert normalize_smart_view(None) is None


def test_repeated_generated_sessions_are_grouped_without_mixing_curated_quizzes(
    tmp_path,
):
    database = bootstrap_current_schema_database(
        tmp_path / "results.db", bootstrap_database=dlms.bootstrap_database
    )
    registry = []
    generation_updates = []
    generation_kinds = (
        "adaptive_study",
        "smart_review",
        "native_spaced_review",
        "spaced_review",
        "concept_review",
        "mixed_quiz",
    )
    quiz_id = 1
    for repetition in range(4):
        for kind in generation_kinds:
            title = (
                f"Curated mix {repetition + 1}"
                if kind == "mixed_quiz"
                else f"Saved practice {quiz_id}"
            )
            source_file = f"neutral-{quiz_id}.html"
            _seed_quiz(
                database,
                quiz_id,
                title,
                source_file,
                1000 + quiz_id,
            )
            generation_updates.append((kind, quiz_id))
            registry.append({
                "id": quiz_id,
                "title": title,
                "html": source_file,
                "folder": "Uncategorized",
            })
            quiz_id += 1

    connection = database.connect()
    try:
        connection.executemany(
            "UPDATE quizzes SET generation_kind = ? WHERE id = ?",
            generation_updates,
        )
        connection.commit()
        result = build_quiz_smart_views(
            connection.cursor(),
            registry,
            native_schedule=lambda _cursor, now=None: {"questions": []},
            now=datetime(2026, 9, 13, 12, tzinfo=timezone.utc),
        )
    finally:
        connection.close()

    assert len(registry) == 24
    assert len(result["generation"]) == 24
    assert len(result["matches"]["generated-practice"]) == 20
    assert result["views"][-1]["count"] == 20
    assert {
        item["label"] for item in result["generation"].values()
        if item["category"] == "practice"
    } == {
        "Adaptive Study practice",
        "Smart Review practice",
        "Due Questions practice",
        "Topic Retention practice",
        "Concept Review practice",
    }
    mixed = {
        quiz_id: item
        for quiz_id, item in result["generation"].items()
        if item["category"] == "mixed"
    }
    assert len(mixed) == 4
    assert all(item["label"] == "Mixed Quiz" for item in mixed.values())
    assert set(mixed).isdisjoint(result["matches"]["generated-practice"])


def test_generated_view_prefers_metadata_and_keeps_legacy_fallback(tmp_path):
    database = bootstrap_current_schema_database(
        tmp_path / "results.db", bootstrap_database=dlms.bootstrap_database
    )
    cases = (
        (1, "Smart Review — Ordinary", "smart_review_ordinary.html", "source"),
        (2, "Renamed personal session", "renamed-session.html", "adaptive_study"),
        (3, "Concept Review — Legacy", "legacy-session.html", None),
    )
    registry = []
    for quiz_id, title, source_file, _kind in cases:
        _seed_quiz(database, quiz_id, title, source_file, 2000 + quiz_id)
        registry.append({
            "id": quiz_id,
            "title": title,
            "html": source_file,
            "folder": "Uncategorized",
        })

    connection = database.connect()
    try:
        connection.executemany(
            "UPDATE quizzes SET generation_kind = ? WHERE id = ?",
            [(kind, quiz_id) for quiz_id, _title, _source, kind in cases],
        )
        connection.commit()
        result = build_quiz_smart_views(
            connection.cursor(),
            registry,
            native_schedule=lambda _cursor, now=None: {"questions": []},
            now=datetime(2026, 9, 13, 12, tzinfo=timezone.utc),
        )
    finally:
        connection.close()

    assert set(result["matches"]["generated-practice"]) == {2, 3}
    assert 1 not in result["generation"]
    assert result["generation"][2]["label"] == "Adaptive Study practice"
    assert result["generation"][3]["label"] == "Concept Review practice"


def test_generated_practice_provenance_uses_lineage_and_live_source_quizzes(
    tmp_path,
):
    database = bootstrap_current_schema_database(
        tmp_path / "results.db", bootstrap_database=dlms.bootstrap_database
    )
    for quiz_id, title, question_id in (
        (1, "Shared Title", 101),
        (2, "Shared Title", 201),
        (3, "Original Name", 301),
        (10, "Generated Across Sources", 1001),
        (11, "Generated From One Source", 1101),
        (12, "Legacy Generated", 1201),
        (13, "Curated Mix", 1301),
    ):
        _seed_quiz(database, quiz_id, title, f"quiz-{quiz_id}.html", question_id)

    registry = [
        {
            "id": quiz_id,
            "title": title,
            "html": f"quiz-{quiz_id}.html",
            "folder": "Uncategorized",
        }
        for quiz_id, title in (
            (1, "Shared Title"),
            (2, "Shared Title"),
            (3, "Original Name"),
            (10, "Generated Across Sources"),
            (11, "Generated From One Source"),
            (12, "Legacy Generated"),
            (13, "Curated Mix"),
        )
    ]
    connection = database.connect()
    try:
        cursor = connection.cursor()
        cursor.executemany(
            "UPDATE questions SET question_uid = ?, canonical_question_uid = ? WHERE id = ?",
            [
                ("a" * 32, "a" * 32, 101),
                ("b" * 32, "b" * 32, 201),
                ("c" * 32, "c" * 32, 301),
            ],
        )
        cursor.executemany(
            "UPDATE quizzes SET generation_kind = ? WHERE id = ?",
            [
                ("source", 1), ("source", 2), ("source", 3),
                ("adaptive_study", 10), ("smart_review", 11),
                ("concept_review", 12), ("mixed_quiz", 13),
            ],
        )
        cursor.execute(
            "UPDATE questions SET source_question_uid = ?, is_generated_copy = 1 WHERE id = 1001",
            ("a" * 32,),
        )
        cursor.execute(
            "UPDATE questions SET source_question_uid = ?, is_generated_copy = 1 WHERE id = 1101",
            ("c" * 32,),
        )
        for question_id, number, source_uid in (
            (1002, 2, "b" * 32),
            (1003, 3, "c" * 32),
            (1004, 4, "d" * 32),
            (1005, 5, None),
        ):
            cursor.execute(
                """
                INSERT INTO questions (
                    id, quiz_id, question_number, question_text,
                    question_type, source_question_uid, is_generated_copy
                ) VALUES (?, 10, ?, ?, 'choice', ?, 1)
                """,
                (question_id, number, "Neutral prompt 1?", source_uid),
            )
        connection.commit()

        traced = []
        connection.set_trace_callback(traced.append)
        first = build_quiz_smart_views(
            cursor,
            registry,
            native_schedule=lambda _cursor, now=None: {"questions": []},
        )
        connection.set_trace_callback(None)

        multiple = first["provenance"][10]
        assert [source["quiz_id"] for source in multiple["sources"]] == [1, 2, 3]
        assert [source["display_title"] for source in multiple["sources"]] == [
            "Shared Title (Quiz #1)",
            "Shared Title (Quiz #2)",
            "Original Name",
        ]
        assert multiple["unavailable_count"] == 2
        assert first["provenance"][11]["sources"][0]["display_title"] == "Original Name"
        assert first["provenance"][12] == {
            "sources": [], "unavailable_count": 1, "search_text": ""
        }
        assert 13 not in first["provenance"]
        assert len([
            statement for statement in traced
            if "FROM questions AS generated" in statement
        ]) == 1

        cursor.execute("UPDATE quizzes SET title = 'Renamed Source' WHERE id = 3")
        connection.commit()
        renamed = build_quiz_smart_views(
            cursor,
            registry,
            native_schedule=lambda _cursor, now=None: {"questions": []},
        )
        assert renamed["provenance"][11]["sources"][0]["display_title"] == "Renamed Source"

        cursor.execute("DELETE FROM quizzes WHERE id = 3")
        connection.commit()
        deleted = build_quiz_smart_views(
            cursor,
            registry,
            native_schedule=lambda _cursor, now=None: {"questions": []},
        )
        assert deleted["provenance"][11] == {
            "sources": [], "unavailable_count": 1, "search_text": ""
        }
        assert deleted["provenance"][10]["unavailable_count"] == 3
        # Question 1005 deliberately has matching text but no lineage. It
        # remains unavailable rather than being guessed from content.
        assert deleted["provenance"][10]["unavailable_count"] > 0
    finally:
        connection.close()


def test_smart_view_styles_use_semantic_themes_and_content_breakpoints():
    css = (Path(__file__).resolve().parents[1] / "static" / "style.css").read_text(
        encoding="utf-8"
    )
    start = css.index(".library-page .library-smart-views {")
    end = css.index(".library-page .library-hero > div,", start)
    component = css[start:end]
    for token in (
        "--theme-page-text",
        "--theme-muted-text",
        "--semantic-secondary-control-text",
        "--semantic-secondary-control-surface",
        "--semantic-secondary-control-border",
        "--semantic-info-text",
        "--semantic-info-surface",
        "--semantic-info-border",
        "--theme-accent",
    ):
        assert token in component
    assert ".library-page .library-smart-view-link:focus" in component
    assert ".library-page .library-smart-view-link:hover" in component
    assert ".library-page .library-smart-view-link.active" in component
    assert "outline: 2px solid var(--theme-accent" in component
    assert "@container (max-width: 760px)" in css
    assert "@container (max-width: 430px)" in css

    generated_start = css.index(".library-page .library-generation-badge {")
    generated_end = css.index(".library-page .library-hidden-badge {", generated_start)
    generated_component = css[generated_start:generated_end]
    for token in (
        "--semantic-info-text",
        "--semantic-info-surface",
        "--semantic-info-border",
        "--semantic-secondary-control-text",
        "--semantic-secondary-control-surface",
        "--semantic-secondary-control-border",
    ):
        assert token in generated_component
    assert "grid-template-columns: repeat(6, minmax(120px, 1fr))" in css
    for selector in (
        ".library-page .library-folder-system {",
        ".library-page .library-system-group-badge {",
        ".library-page .library-source-provenance {",
        ".library-page .library-source-provenance summary:focus-visible {",
    ):
        assert selector in css
