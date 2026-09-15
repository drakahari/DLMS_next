#!/usr/bin/env python3
"""Reproducibly capture the DLMS user-manual screenshot set with Firefox.

The tool runs DLMS against a disposable, deterministic data root.  It never
reads the operator's normal DLMS data and does not add screenshot-only behavior
to the application.  Run from the repository root:

    .venv/bin/python tools/capture_user_manual_screenshots.py

Use ``--only UM-03,UM-12`` for a focused refresh, or ``--list`` to inspect the
capture manifest without starting DLMS or Firefox.
"""

from __future__ import annotations

import argparse
import ast
import base64
import json
import os
import shutil
import signal
import socket
import struct
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
import zlib
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "docs" / "user-manual" / "images"
WIDTH = 1440
HEIGHT = 1000
THEME = "light"
FIXTURE_VERSION = "dlms-user-manual-3.2-v2"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@dataclass(frozen=True)
class CaptureSpec:
    screenshot_id: str
    title: str
    filename: str
    route: str
    ready: str
    classification: str = "Fully automatable"
    focus: str | None = None
    note: str = ""


CAPTURES = (
    CaptureSpec("UM-01", "Dashboard and Today’s Review", "UM-01-dashboard.png", "/", "document.getElementById('dailyReviewCount')?.textContent !== 'Loading…'"),
    CaptureSpec("UM-02", "Build Quiz hub", "UM-02-build-quiz-hub.png", "/upload", "document.querySelectorAll('.upload-method-card, .build-option-card, .upload-method').length >= 4"),
    CaptureSpec("UM-03", "Generated Practice Smart View", "UM-03-generated-practice-smart-view.png", "/library?view=visible&smart=generated-practice", "document.getElementById('librarySmartViewCount')?.textContent !== '…'", focus=".library-smart-active"),
    CaptureSpec("UM-04", "Mixed Quiz Builder", "UM-04-mixed-quiz-builder.png", "/quiz-composer", "document.querySelectorAll(\"input[name='question_ids']\").length >= 4", focus=".mixed-builder-plan"),
    CaptureSpec("UM-05", "Duplicate Question Review", "UM-05-duplicate-question-review.png", "/library/duplicates", "document.querySelector('.duplicate-question-summary')", focus=".duplicate-question-summary"),
    CaptureSpec("UM-06", "Portable Quiz Bundle review", "UM-06-portable-quiz-bundle-review.png", "/quiz-bundles", "document.querySelector(\"form[action='/quiz-bundles/import']\")", classification="Partially automatable", focus=".portable-bundle-workflows", note="The canonical asset captures the validated import review. The export-selection stage is automatable but would require a second image."),
    CaptureSpec("UM-07", "Study Mode feedback", "UM-07-study-mode-feedback.png", "@critical_quiz", "quizRecoveryReady === true && quiz.length >= 2", focus="#quizPanel"),
    CaptureSpec("UM-08", "Exam Mode in progress", "UM-08-exam-mode.png", "@recovery_quiz", "quizRecoveryReady === true && quiz.length === 4", focus="#quizPanel"),
    CaptureSpec("UM-09", "Interrupted quiz recovery", "UM-09-quiz-recovery.png", "@recovery_quiz", "quizRecoveryReady === true && quiz.length === 4", focus=".quiz-recovery-panel"),
    CaptureSpec("UM-10", "Which review should I use", "UM-10-review-options-guide.png", "/help/learning-intelligence#which-review", "document.querySelector('#which-review .help-table, .help-table')", focus="#which-review"),
    CaptureSpec("UM-11", "Review Schedule", "UM-11-review-schedule.png", "/review-schedule", "document.getElementById('nrsDue')?.textContent !== '—' && document.getElementById('rsDue')?.textContent !== '—'"),
    CaptureSpec("UM-12", "Learning Intelligence and mastery", "UM-12-learning-intelligence-mastery.png", "/learning-intelligence", "document.getElementById('liModelButton') && document.querySelector('#liRows tr')", focus="#liModel"),
    CaptureSpec("UM-13", "Learning Diagnostics", "UM-13-learning-diagnostics.png", "/learning-diagnostics", "document.getElementById('dqEvidence')?.textContent !== '—'"),
    CaptureSpec("UM-14", "History", "UM-14-history.png", "/history", "document.getElementById('historyTotalAttempts')?.textContent !== '—'", classification="Partially automatable", note="The canonical asset captures the populated History list. A separate attempt-detail image can be added after asset review if it adds teaching value."),
    CaptureSpec("UM-15", "PDF and Image Import", "UM-15-pdf-image-import.png", "/pdf-import", "document.querySelector(\"form[action='/pdf-import/analyze']\")"),
    CaptureSpec("UM-16", "Question Review and Repair", "UM-16-review-and-repair.png", "/pdf-import/review/manual_question_review", "document.querySelectorAll('.pdf-import-question-card').length === 3", focus=".pdf-import-summary-grid"),
    CaptureSpec("UM-17", "Screenshot OCR source selection", "UM-17-screenshot-ocr-selection.png", "/pdf-import", "document.querySelector(\"form[action='/pdf-import/screenshots']\")", focus=".pdf-ocr-import-panel", note="Browser automation selects a repository-safe synthetic screenshot without opening a native file dialog."),
    CaptureSpec("UM-18", "OCR matching Review and Repair", "UM-18-ocr-matching-review.png", "/external-ai/review/@ocr_matching_draft", "document.querySelector('.external-ai-matching-editor')", focus=".external-ai-diagnostics"),
    CaptureSpec("UM-19", "Image Study Editor", "UM-19-image-study-editor.png", "/admin/image-editor?pack=manual_demo&kind=hotspot&dataset=visuals", "document.getElementById('editorImage')?.complete", focus=".hotspot-editor-workspace"),
    CaptureSpec("UM-20", "External AI matching workflow", "UM-20-external-ai-matching.png", "/external-ai/quiz-builder", "document.getElementById('externalAiBuilderForm')", classification="Partially automatable", note="The canonical asset captures the provider-neutral matching builder. A validated Review & Repair result would be a second image."),
    CaptureSpec("UM-21", "AI Study Pack Builder", "UM-21-ai-study-pack-builder.png", "/study-packs/ai-builder", "document.querySelector('.study-pack-ai-form, form')", focus=".medical-ai-intro"),
    CaptureSpec("UM-22", "Study Packs catalog", "UM-22-study-packs-catalog.png", "/study-packs", "document.querySelector('.study-pack-section')", classification="Partially automatable", focus=".study-pack-toolbar", note="The canonical asset captures the learner catalog. Content Pack validation is a distinct management screen and would require a second image."),
    CaptureSpec("UM-23", "Law Case Review", "UM-23-law-case-review.png", "/law/cases/browser-law-negligence", "document.querySelector('.law-case-section')", focus=".law-case-detail-shell"),
    CaptureSpec("UM-24", "Custom Anki Deck", "UM-24-custom-anki-deck.png", "/anki/custom", "document.getElementById('customAnkiForm')", classification="Partially automatable", focus=".anki-tools-header", note="The canonical asset captures custom deck selection. Printable-card preview is a second state that can be added after asset review."),
    CaptureSpec("UM-25", "LAN server lifecycle", "UM-25-lan-server-lifecycle.png", "/settings/lifecycle", "document.querySelector('.settings-warning-panel') && document.querySelector('button[type=submit]')?.disabled", focus=".settings-page-shell", note="Captured from a real explicit LAN/server-mode DLMS process bound for the isolated run."),
    CaptureSpec("UM-26", "Validated backup restore", "UM-26-backup-restore-confirmation.png", "/settings/backup", "document.querySelector(\"form[action='/settings/backup/restore/stage']\")", focus=".settings-detail-shell", note="Automation uploads a synthetic DLMS backup and captures the real staged confirmation page."),
    CaptureSpec("UM-27", "Rebuild All Quiz Pages", "UM-27-rebuild-all-quiz-pages.png", "/admin/maintenance", "document.getElementById('rebuildAllBtn')", classification="Partially automatable", focus=".system-tools-action", note="The canonical asset captures the complete maintenance card. The browser-native confirmation is deliberately cancelled and is not present in the viewport image."),
)


def _application_version() -> str:
    """Read APP_VERSION without importing the application or touching user data."""
    tree = ast.parse((ROOT / "app.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "APP_VERSION":
                    if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                        return node.value.value
    raise RuntimeError("Unable to locate the literal APP_VERSION assignment in app.py")


def _choice(number: int, prompt: str, concept: str, correct: int = 0) -> dict:
    labels = "ABCD"
    options = [
        "The documented primary option",
        "A related but incomplete option",
        "An unrelated option",
        "An option that reverses the rule",
    ]
    choices = [
        {"label": label, "text": text, "is_correct": index == correct}
        for index, (label, text) in enumerate(zip(labels, options))
    ]
    return {
        "number": number,
        "type": "choice",
        "question": prompt,
        "choices": choices,
        "correct": [labels[correct]],
        "explanation": "The primary option follows the documented rule used in this demonstration.",
        "concepts": [concept],
    }


def _write_demo_diagram(path: Path) -> None:
    """Write a neutral raster diagram without adding an image dependency."""
    width, height = 720, 420
    rows = []
    for y in range(height):
        row = bytearray()
        for x in range(width):
            color = (246, 249, 253)
            if 54 <= x <= 666 and 48 <= y <= 104:
                color = (180, 217, 246)
            elif 70 <= x <= 326 and 144 <= y <= 330:
                color = (210, 231, 249)
            elif 394 <= x <= 650 and 144 <= y <= 330:
                color = (213, 239, 226)
            if (x - 360) ** 2 + (y - 237) ** 2 <= 43 ** 2:
                color = (252, 220, 154)
            row.extend(color)
        rows.append(b"\x00" + bytes(row))

    def chunk(kind: bytes, data: bytes) -> bytes:
        payload = kind + data
        return struct.pack(">I", len(data)) + payload + struct.pack(">I", zlib.crc32(payload) & 0xFFFFFFFF)

    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"".join(rows), level=9))
        + chunk(b"IEND", b"")
    )


def _write_demo_pack(dlms) -> None:
    pack = Path(dlms.CONTENT_PACK_FOLDER) / "DLMS_Study_manual_demo"
    (pack / "data").mkdir(parents=True, exist_ok=True)
    (pack / "images").mkdir(exist_ok=True)
    _write_demo_diagram(pack / "images" / "diagram.png")
    source = {
        "organization": "DLMS Documentation Demo",
        "url": "https://example.invalid/dlms-demo",
        "license": "CC0",
        "attribution": "Synthetic documentation fixture",
    }
    image = {
        "id": "diagram",
        "file": "images/diagram.png",
        "alt": "Synthetic answer-choice diagram",
        "license": "CC0",
        "source": source,
        "concepts": ["Visual Navigation"],
        "hotspots": [{
            "id": "answer-area",
            "label": "Answer area",
            "shape": {"type": "polygon", "points": [[0.12, 0.25], [0.82, 0.25], [0.82, 0.72], [0.12, 0.72]]},
        }],
    }
    manifest = {
        "schema_version": 1,
        "id": "manual_demo",
        "name": "Learning Skills Demo",
        "version": "1.0.0",
        "description": "Synthetic study content prepared for the DLMS user manual.",
        "content_domain": "General",
        "datasets": [{"id": "terms", "title": "Study Terms", "type": "matching", "path": "data/terms.json"}],
        "image_datasets": [{"id": "visuals", "title": "Visual Study", "type": "hotspot", "path": "data/visuals.json"}],
        "quiz_datasets": [{"id": "mixed", "title": "Learning Skills", "type": "quiz", "path": "data/mixed.json"}],
    }
    terms = {
        "schema_version": 1, "id": "terms", "title": "Study Terms", "type": "matching", "source": source,
        "items": [{"term": "Retrieval practice", "definition": "Actively recalling information"}, {"term": "Spacing", "definition": "Revisiting material over time"}],
    }
    visuals = {"schema_version": 1, "id": "visuals", "title": "Visual Study", "type": "hotspot", "source": source, "images": [image]}
    mixed = {
        "schema_version": 1, "id": "mixed", "title": "Learning Skills", "source": source, "images": [image],
        "questions": [
            {"type": "choice", "question": "Which action is retrieval practice?", "concepts": ["Retrieval Practice"], "choices": [{"text": "Recalling without notes", "is_correct": True}, {"text": "Only rereading", "is_correct": False}]},
            {"type": "matching", "question": "Match each study method.", "concepts": ["Study Methods"], "pairs": [{"left": "Spacing", "right": "Review over time"}, {"left": "Interleaving", "right": "Mix related skills"}]},
            {"type": "hotspot", "question": "Select the answer area.", "image_id": "diagram", "hotspot_id": "answer-area"},
        ],
    }
    for relative, payload in (("manifest.json", manifest), ("data/terms.json", terms), ("data/visuals.json", visuals), ("data/mixed.json", mixed)):
        (pack / relative).write_text(json.dumps(payload, indent=2), encoding="utf-8")
    (pack / "PACK_VALIDATION.json").write_text(json.dumps({"schema_version": 1, "pack_id": "manual_demo", "overall_status": "PASS", "checks": []}, indent=2), encoding="utf-8")


def _seed_base_data(dlms) -> dict:
    """Create the small playable base fixture without importing the test package.

    Importing ``tests`` intentionally replaces ``QUIZAPP_DATA_DIR`` for test
    collection isolation, so the screenshot runner keeps this equivalent seed
    local and reuses only the browser protocol client from the test harness.
    """
    critical_id, critical_html = dlms._publish_quiz(
        "Browser Critical Workflow",
        [_choice(1, "Browser question one?", "Browser Basics", 0), _choice(2, "Browser question two?", "Browser Basics", 1)],
        filename_prefix="browser_critical", exam_minutes=5,
    )
    companion_id, companion_html = dlms._publish_quiz(
        "Browser Companion", [_choice(1, "Companion question?", "Browser Basics", 0)],
        filename_prefix="browser_companion", exam_minutes=5,
    )
    recovery_json = "browser_recovery_mixed.json"
    recovery_html = "browser_recovery_mixed.html"
    recovery_quiz = [
        _choice(1, "Recovery single-choice question?", "Recovery", 0),
        {
            "number": 2, "type": "choice", "question": "Recovery multi-answer question?",
            "choices": [
                {"label": "A", "text": "First", "is_correct": True},
                {"label": "B", "text": "Second", "is_correct": False},
                {"label": "C", "text": "Third", "is_correct": True},
            ],
            "correct": ["A", "C"], "explanation": "Select the first and third answers.", "concepts": ["Recovery"],
        },
        {
            "number": 3, "type": "matching", "question": "Recovery matching question?", "round_size": 2, "direction": "random",
            "pairs": [{"left": "Alpha", "right": "One"}, {"left": "Beta", "right": "Two"}, {"left": "Gamma", "right": "Three"}], "concepts": ["Recovery"],
        },
        {
            "number": 4, "type": "hotspot", "question": "Recovery hotspot question?", "image_url": "/static/favicon.ico",
            "image_alt": "Recovery test target", "target": {"type": "circle", "x": 0.5, "y": 0.5, "radius": 0.2}, "target_label": "Center", "concepts": ["Recovery"],
        },
    ]
    dlms._atomic_write_json(str(Path(dlms.DATA_FOLDER, recovery_json)), recovery_quiz, expected_type=list)
    dlms.build_quiz_html(recovery_html, recovery_json, str(Path(dlms.QUIZ_FOLDER, recovery_html)), "DLMS", "Browser Recovery Mixed Types", None, "browser-recovery-mixed", 5)

    registry = dlms.load_law_registry()
    law_file = "browser-law-negligence.json"
    dlms._atomic_write_json(
        str(Path(dlms.LAW_CASES_FOLDER, law_file)),
        {"id": "browser-law-negligence", "type": "law_case_review", "title": "Boundary Duty Documentation Review", "course": "Torts", "sections": {"rule_flashcards": "Q: What limits negligence duty?\nA: Foreseeability."}},
        expected_type=dict,
    )
    registry["cases"].append({"id": "browser-law-negligence", "title": "Boundary Duty Documentation Review", "course": "Torts", "file": law_file, "hidden": False})
    dlms.save_law_registry(registry)
    restore_path, _ = dlms._create_dlms_backup("manual-restore-fixture")
    metadata = {
        "critical_id": critical_id, "critical_html": critical_html,
        "companion_id": companion_id, "companion_html": companion_html,
        "recovery_html": recovery_html, "recovery_json": recovery_json,
        "restore_path": restore_path,
    }
    Path(dlms.APP_DATA_DIR, "browser_fixture.json").write_text(json.dumps(metadata), encoding="utf-8")
    return metadata


def _seed_manual_data(dlms, metadata: dict) -> dict:
    """Add documentation-rich synthetic state after the browser fixture seed."""
    now = datetime.now(timezone.utc)
    published: dict[str, tuple[int, str]] = {}
    quiz_definitions = (
        ("network", "Network Foundations", "Networking", [
            "Which practice helps verify a network change?",
            "Which step should come before troubleshooting changes?",
            "Which result best confirms reachability?",
            "Which record helps make a change repeatable?",
        ]),
        ("security", "Security Essentials", "Access Control", [
            "Which principle limits unnecessary access?",
            "Which practice protects a recovery credential?",
            "Which action best verifies an identity?",
            "Which control reduces repeated password guessing?",
        ]),
        ("cloud", "Cloud Fundamentals", "Cloud Concepts", [
            "Which description fits an elastic resource?",
            "Which approach separates a service from one device?",
            "Which record helps explain resource use?",
            "Which design supports recovery from one failed component?",
        ]),
    )
    for key, title, concept, prompts in quiz_definitions:
        published[key] = dlms._publish_quiz(
            title,
            [_choice(index, prompt, concept, correct=index % 2) for index, prompt in enumerate(prompts, 1)],
            filename_prefix=f"manual_{key}", exam_minutes=20,
        )
    published["matching"] = dlms._publish_quiz(
        "Study Methods Matching",
        [{
            "number": 1, "type": "matching", "question": "Match each study method to its purpose.",
            "round_size": 3, "direction": "term_to_definition", "concepts": ["Study Methods"],
            "pairs": [
                {"left": "Retrieval practice", "right": "Recall without looking"},
                {"left": "Spacing", "right": "Review over time"},
                {"left": "Interleaving", "right": "Mix related skills"},
            ],
        }], filename_prefix="manual_matching", exam_minutes=10,
    )

    # Purpose-written exact and possible duplicate examples.
    duplicate_prompt = "Which step creates a reliable recovery point before a major change?"
    published["duplicate_a"] = dlms._publish_quiz("Backup Basics", [_choice(1, duplicate_prompt, "Data Safety")], filename_prefix="manual_duplicate_a")
    published["duplicate_b"] = dlms._publish_quiz("Maintenance Readiness", [_choice(1, duplicate_prompt, "Data Safety")], filename_prefix="manual_duplicate_b")
    published["duplicate_near"] = dlms._publish_quiz("Safe Changes", [_choice(1, "What creates a reliable recovery point before a significant change?", "Data Safety")], filename_prefix="manual_duplicate_near")

    source_questions = []
    conn = dlms.get_db()
    for key in ("network", "security", "cloud"):
        quiz_id = published[key][0]
        rows = conn.execute("SELECT id, question_number FROM questions WHERE quiz_id=? ORDER BY question_number", (quiz_id,)).fetchall()
        source_questions.extend((quiz_id, row[0], key, row[1]) for row in rows)

    # Six or more deterministic events per concept create meaningful mastery,
    # trends, due questions, and diagnostics without using real study history.
    for ordinal, (quiz_id, question_id, key, question_number) in enumerate(source_questions):
        results = [False, False, True, False, True, key == "cloud"]
        for event_index, was_correct in enumerate(results):
            occurred = now - timedelta(days=12 - event_index * 2 + ordinal % 3)
            attempt_id = f"manual-evidence-{key}-{question_number}-{event_index + 1}"
            response = {"selected": ["A" if was_correct else "B"], "question_type": "choice"}
            conn.execute(
                "INSERT INTO learning_events (event_type,quiz_id,question_id,attempt_id,mode,was_correct,response_json,occurred_at) VALUES ('exam_answer',?,?,?,?,?,?,?)",
                (quiz_id, question_id, attempt_id, "Exam", int(was_correct), json.dumps(response), occurred.isoformat()),
            )

    # Completed attempts for History, Analytics, low-score views, and Anki.
    for index, (key, score) in enumerate((("network", 3), ("security", 2), ("cloud", 4)), 1):
        quiz_id = published[key][0]
        attempt_id = f"manual-attempt-{index}"
        completed = now - timedelta(days=index)
        conn.execute(
            "INSERT INTO attempts (id,quiz_id,user_name,started_at,completed_at,score,total,percent,time_remaining,mode) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (attempt_id, quiz_id, "Demo Learner", (completed - timedelta(minutes=8)).isoformat(), completed.isoformat(), score, 4, score * 25, 540, "Exam"),
        )
        questions = conn.execute("SELECT id,question_number,question_text FROM questions WHERE quiz_id=? ORDER BY question_number", (quiz_id,)).fetchall()
        for q_index, row in enumerate(questions):
            correct = q_index < score
            conn.execute("INSERT INTO attempt_answers (attempt_id,question_id,selected_labels,was_correct) VALUES (?,?,?,?)", (attempt_id, row[0], "A" if correct else "B", int(correct)))
            if not correct:
                conn.execute(
                    "INSERT INTO missed_questions (attempt_id,question_id,correct_letters,question_text,choices_text,selected_letters,selected_text,correct_text,attempt_question_number,question_type) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (attempt_id, row[0], "A", row[2], "A. Primary\nB. Related", "B", "B. Related", "A. Primary", row[1], "choice"),
                )
    generated_source_payloads = []
    for number, source_index in enumerate((0, 4, 8), start=1):
        payload = dlms._question_payload_from_db(
            conn.cursor(), source_questions[source_index][1]
        )
        payload["number"] = number
        generated_source_payloads.append(payload)
    conn.commit()
    conn.close()

    # Current generated-session metadata drives the Generated Practice view.
    for key, title, kind in (
        ("adaptive", "Adaptive Study — What I Need Most", "adaptive_study"),
        ("smart", "Smart Review — Access Control", "smart_review"),
        ("due", "Due Questions — Current Review", "native_spaced_review"),
        ("retention", "Topic Retention — Network Foundations", "spaced_review"),
        ("concept", "Concept Review — Cloud Concepts", "concept_review"),
        ("mixed", "Mixed Quiz — Core Skills", "mixed_quiz"),
    ):
        published[key] = dlms._publish_quiz(
            title,
            generated_source_payloads,
            filename_prefix=f"manual_{key}",
            generation_kind=kind,
            exam_minutes=15,
        )

    registry = dlms.load_registry()
    folders = {
        published["network"][0]: "Core Skills",
        published["security"][0]: "Core Skills",
        published["cloud"][0]: "Cloud Study",
        published["matching"][0]: "Study Skills",
    }
    for entry in registry:
        generation_kind = entry.get("generation_kind")
        default_folder = (
            "Uncategorized"
            if generation_kind and generation_kind != "source" and generation_kind != "mixed_quiz"
            else "Generated Sessions"
            if generation_kind == "mixed_quiz"
            else "Practice Library"
        )
        entry["folder"] = folders.get(entry.get("id"), default_folder)
    dlms.save_registry(registry)
    dlms.save_quiz_folders(["Uncategorized", "Core Skills", "Cloud Study", "Study Skills", "Practice Library", "Generated Sessions", "Future Topics"])

    _write_demo_pack(dlms)

    # A compact Review & Repair draft with complete, review, and incomplete states.
    draft_root = Path(dlms.PDF_IMPORT_DRAFT_FOLDER)
    draft_root.mkdir(parents=True, exist_ok=True)
    question_draft = {
        "id": "manual_question_review", "source_name": "study-skills-demo.pdf", "page_count": 3,
        "document_type": "question_bank", "detection": {"recovery_mode": True}, "recovery_mode": True,
        "quiz_title": "Study Skills Question Bank", "exam_minutes": 30,
        "summary": {"detected": 3, "complete": 1, "review": 1, "incomplete": 1},
        "unassigned_text": "Appendix note: verify examples before publication.",
        "questions": [
            {"number": 1, "question": "Which method asks you to recall without looking?", "choices": [{"label": "A", "text": "Retrieval practice"}, {"label": "B", "text": "Passive rereading"}], "correct": "A", "declared_answer_text": "Retrieval practice", "explanation": "Retrieval practice requires active recall.", "choice_feedback": {}, "pages": [1], "status": "complete", "issues": []},
            {"number": 2, "question": "Which schedule spaces practice?", "choices": [{"label": "A", "text": "One long session"}, {"label": "B", "text": "Several shorter sessions"}], "correct": "B", "declared_answer_text": "Several shorter sessions", "explanation": "", "choice_feedback": {}, "pages": [2], "status": "review", "issues": ["Explanation was not detected; review the answer."]},
            {"number": 3, "question": "Complete this recovered question.", "choices": [{"label": "A", "text": "Recovered choice"}], "correct": "", "declared_answer_text": "", "explanation": "", "choice_feedback": {}, "pages": [3], "status": "incomplete", "issues": ["A correct answer was not detected."]},
        ],
    }
    (draft_root / "manual_question_review.json").write_text(json.dumps(question_draft, indent=2), encoding="utf-8")

    ocr_processing = {
        "quiz_title": "Study Methods from OCR", "matching_question": "Match each study term to its meaning.", "matching_direction": "term_to_definition",
        "ocr_batch": {"sources": [{"original_name": "study-terms-page-1.png"}, {"original_name": "study-terms-page-2.png"}]},
        "matching_results": [{
            "pairs": [
                {"left": "Retrieval practice", "right": "Recall without looking", "category": "Learning", "explanation": "", "ocr_metadata": {"source_name": "study-terms-page-1.png", "page_number": 1, "pattern": "em_dash", "confidence": 94}},
                {"left": "Spacing", "right": "Review over time", "category": "Learning", "explanation": "", "ocr_metadata": {"source_name": "study-terms-page-1.png", "page_number": 1, "pattern": "colon", "confidence": 91}},
                {"left": "Interleaving", "right": "Mix related skills", "category": "Learning", "explanation": "", "ocr_metadata": {"source_name": "study-terms-page-2.png", "page_number": 2, "pattern": "two_column", "confidence": 86}},
            ],
            "unassigned": [{"source_name": "study-terms-page-2.png", "page_number": 2, "text": "Compare this line with the original source."}],
            "diagnostics": [{"severity": "warning", "path": "Page 2", "message": "One readable line did not contain enough structure for a safe pairing."}],
        }],
    }
    ocr_draft_id, _ = dlms._stage_ocr_matching_review(ocr_processing)

    # Enrich the saved demo Law Case Review used by the real case-detail route.
    law_path = Path(dlms.LAW_CASES_FOLDER) / "browser-law-negligence.json"
    law = json.loads(law_path.read_text(encoding="utf-8"))
    law.update({
        "created_at": "2026-09-01T10:00:00", "source_import": "fictional-demo-packet.txt",
        "source_import_snapshot": "A fictional negligence dispute created for documentation.",
        "sections": {
            "case_brief": "Facts: A visitor encountered a clearly marked boundary.\nIssue: What duty applied?\nHolding: The documented duty governed the result.",
            "irac_drill": "Identify the issue, state the governing rule, apply the facts, and reach a supported conclusion.",
            "socratic_questions": "1. Which fact changes the duty analysis?\n2. What alternative rule could apply?",
            "rule_flashcards": "Q: What is the purpose of duty?\nA: It identifies a legally recognized obligation.",
        },
        "student_notes": "Demo note: compare the decisive fact with the stated rule.",
        "irac_student_response": {"issue": "Which duty applied?", "rule": "Use the documented duty rule.", "analysis": "The boundary notice affects the analysis.", "conclusion": "The facts support the stated result."},
        "socratic_student_answers": {"q1": "The notice changes reasonable expectations."},
    })
    law_path.write_text(json.dumps(law, indent=2), encoding="utf-8")

    # A portable bundle with an intentional title collision exercises preview.
    bundle_path = Path(dlms.APP_DATA_DIR) / "manual-portable-bundle.zip"
    bundle_manifest = {
        "format": "dlms-portable-quiz-bundle", "schema_version": 1,
        "created_at": "2026-09-14T10:00:00-05:00", "created_by": {"application": "DLMS", "version": dlms.APP_VERSION},
        "quizzes": [{
            "bundle_id": "manual-quiz-001", "title": "Network Foundations", "folder": "Imported Practice", "exam_minutes": 20, "logo": None, "assets": [],
            "questions": [{"number": 1, "type": "choice", "question": "Which imported practice option is correct?", "explanation": "A synthetic portable example.", "concepts": ["Portable Content"], "source": {}, "media": {}, "choices": [{"label": "A", "text": "The documented option", "is_correct": True}, {"label": "B", "text": "The alternate option", "is_correct": False}]}],
        }],
    }
    with zipfile.ZipFile(bundle_path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("dlms-quiz-bundle.json", json.dumps(bundle_manifest))

    portal = dlms.load_portal_config()
    portal["theme"] = THEME
    portal["title"] = "DLMS Documentation Demo"
    dlms._write_settings_portal_config(portal)

    metadata.update({
        "fixture_version": FIXTURE_VERSION,
        "critical_html": published["network"][1],
        "critical_id": published["network"][0],
        "recovery_html": metadata["recovery_html"],
        "ocr_matching_draft": ocr_draft_id,
        "bundle_path": str(bundle_path),
        "pdf_path": str(ROOT / "tests" / "fixtures" / "ocr" / "pdf" / "selectable-text.pdf"),
        "ocr_image_path": str(ROOT / "tests" / "fixtures" / "ocr" / "screenshot-explicit-abcd.png"),
    })
    Path(dlms.APP_DATA_DIR, "browser_fixture.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return metadata


def _serve(lan: bool) -> None:
    os.environ["DLMS_NO_BROWSER"] = "1"
    import app as dlms
    from werkzeug.serving import make_server

    print(f"DLMS manual screenshot data root: {dlms.APP_DATA_DIR}", flush=True)

    fixture = Path(dlms.APP_DATA_DIR) / "browser_fixture.json"
    if os.environ.get("DLMS_BROWSER_REUSE_DATA") != "1" or not fixture.is_file():
        metadata = _seed_base_data(dlms)
        _seed_manual_data(dlms, metadata)
    host_mode = "0.0.0.0" if lan else "127.0.0.1"
    dlms.start_browser_presence_monitor(host_mode)
    port = int(os.environ["DLMS_BROWSER_TEST_PORT"])
    server = make_server("127.0.0.1", port, dlms.app, threaded=True)
    print(f"DLMS manual screenshot server listening on {port}", flush=True)
    server.serve_forever()


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _terminate(process: subprocess.Popen | None, *, interrupt: bool = False) -> None:
    if process is None:
        return
    if os.name == "posix":
        try:
            # The DLMS runtime's supported stop signal is SIGINT. Firefox uses
            # normal termination after its BiDi session has been closed.
            os.killpg(process.pid, signal.SIGINT if interrupt else signal.SIGTERM)
        except ProcessLookupError:
            return
    elif process.poll() is None:
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
        process.wait(timeout=5)


def _wait_http(url: str, process: subprocess.Popen, log: Path) -> None:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    deadline = time.monotonic() + 18
    last_error = None
    while time.monotonic() < deadline and process.poll() is None:
        try:
            with opener.open(url, timeout=0.5) as response:
                if response.status == 200:
                    return
        except Exception as exc:
            last_error = exc
        time.sleep(0.08)
    output = log.read_text(encoding="utf-8", errors="replace") if log.exists() else ""
    raise RuntimeError(f"Screenshot server did not start: {last_error}\n{output[-4000:]}")


def _wait_fixture(path: Path, process: subprocess.Popen, log: Path) -> None:
    deadline = time.monotonic() + 18
    while time.monotonic() < deadline and process.poll() is None:
        if path.is_file():
            return
        time.sleep(0.08)
    output = log.read_text(encoding="utf-8", errors="replace") if log.exists() else ""
    raise RuntimeError(f"Screenshot fixture metadata was not created at {path}.\n{output[-4000:]}")


def _wait_firefox(port: int, process: subprocess.Popen, log: Path):
    from tests.browser._bidi import FirefoxBidi
    deadline = time.monotonic() + 18
    last_error = None
    while time.monotonic() < deadline and process.poll() is None:
        client = None
        try:
            client = FirefoxBidi.connect("127.0.0.1", port, timeout=0.6)
            client.start_session()
            return client
        except Exception as exc:
            last_error = exc
            if client:
                client.close()
        time.sleep(0.08)
    output = log.read_text(encoding="utf-8", errors="replace") if log.exists() else ""
    raise RuntimeError(f"Firefox did not start: {last_error}\n{output[-4000:]}")


def _start_server(work: Path, data_root: Path, *, lan: bool, reuse: bool):
    port = _free_port()
    log = work / ("server-lan.log" if lan else "server-local.log")
    env = os.environ.copy()
    env.update({
        "QUIZAPP_DATA_DIR": str(data_root), "DLMS_NO_BROWSER": "1",
        "DLMS_BROWSER_TEST_PORT": str(port), "PYTHONUNBUFFERED": "1",
        "MOZ_CRASHREPORTER_DISABLE": "1", "MOZ_DISABLE_AUTO_SAFE_MODE": "1",
    })
    env.pop("DLMS_BROWSER_REUSE_DATA", None)
    if reuse:
        env["DLMS_BROWSER_REUSE_DATA"] = "1"
    options = {"start_new_session": True} if os.name == "posix" else {}
    handle = log.open("w", encoding="utf-8")
    process = subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "--serve", *( ["--lan"] if lan else [] )],
        cwd=ROOT, env=env, stdout=handle, stderr=subprocess.STDOUT, **options,
    )
    process._dlms_log_handle = handle  # type: ignore[attr-defined]
    _wait_http(f"http://127.0.0.1:{port}/", process, log)
    _wait_fixture(data_root / "browser_fixture.json", process, log)
    return process, f"http://127.0.0.1:{port}", env


def _start_firefox(work: Path, env: dict):
    firefox = shutil.which("firefox") or shutil.which("firefox-esr")
    if not firefox:
        raise RuntimeError("Firefox is required for user-manual screenshot capture.")
    port = _free_port()
    session = work / f"firefox-{port}"
    profile = session / "profile"
    profile.mkdir(parents=True)
    (profile / "user.js").write_text("\n".join([
        'user_pref("datareporting.healthreport.uploadEnabled", false);',
        'user_pref("toolkit.telemetry.enabled", false);',
        'user_pref("browser.crashReports.unsubmittedCheck.autoSubmit2", false);',
        'user_pref("layout.css.devPixelsPerPx", "1.0");',
    ]), encoding="utf-8")
    log = session / "firefox.log"
    handle = log.open("w", encoding="utf-8")
    options = {"start_new_session": True} if os.name == "posix" else {}
    process = subprocess.Popen(
        [firefox, "--headless", "--no-remote", "--profile", str(profile), "--remote-debugging-port", str(port), "about:blank"],
        cwd=ROOT, env=env, stdout=handle, stderr=subprocess.STDOUT, **options,
    )
    process._dlms_log_handle = handle  # type: ignore[attr-defined]
    return process, _wait_firefox(port, process, log)


def _stop_process(process, *, interrupt: bool = False) -> None:
    _terminate(process, interrupt=interrupt)
    handle = getattr(process, "_dlms_log_handle", None)
    if handle:
        handle.close()


def _set_theme(browser, base_url: str) -> None:
    browser.navigate(base_url + "/settings")
    browser.wait_for("typeof window.dlmsCsrfToken === 'string' && window.dlmsCsrfToken.length > 0")
    status = browser.evaluate(
        "fetch('/api/theme',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({theme:'light'})}).then(r=>r.status)"
    )
    if status != 200:
        raise RuntimeError(f"Could not set screenshot theme: HTTP {status}")


def _resolve_route(spec: CaptureSpec, metadata: dict) -> str:
    if spec.route == "@critical_quiz":
        return f"/quizzes/{metadata['critical_html']}"
    if spec.route == "@recovery_quiz":
        return f"/quizzes/{metadata['recovery_html']}"
    route = spec.route
    for key, value in metadata.items():
        route = route.replace(f"@{key}", str(value))
    return route


def _stable_page(browser) -> None:
    browser.wait_for_page_ready()
    browser.evaluate(
        "(() => {const id='dlms-manual-capture-style';let s=document.getElementById(id);"
        "if(!s){s=document.createElement('style');s.id=id;s.textContent='*,*::before,*::after{animation:none!important;transition:none!important;caret-color:transparent!important}html{scroll-behavior:auto!important}';document.head.appendChild(s);}"
        "document.querySelectorAll('[autofocus]').forEach(n=>n.removeAttribute('autofocus'));document.activeElement?.blur?.();return true;})()"
    )
    browser.evaluate("document.fonts?.ready.then(()=>true) || true")


def _prepare(browser, base_url: str, spec: CaptureSpec, metadata: dict) -> None:
    sid = spec.screenshot_id
    if sid == "UM-01":
        browser.wait_for("document.getElementById('dailyReviewCount')?.textContent !== 'Loading…'", timeout=12)
    elif sid == "UM-04":
        browser.evaluate("(() => {document.getElementById('mixedQuizTitle').value='Core Skills Mixed Practice';const boxes=[...document.querySelectorAll(\"input[name='question_ids']\")];const sources=new Set();for(const box of boxes){const card=box.closest('.mixed-builder-question');const source=card?.dataset.quizId||card?.querySelector('[data-quiz-id]')?.dataset.quizId||box.dataset.quizId;if(sources.size<2||sources.has(source)){box.click();sources.add(source);}if([...document.querySelectorAll(\"input[name='question_ids']:checked\")].length>=4&&sources.size>=2)break;}return true;})()")
    elif sid == "UM-06":
        browser.set_files("input[name='bundle_zip']", [metadata["bundle_path"]])
        browser.click("form[action='/quiz-bundles/import'] button[type='submit']")
        browser.wait_for("location.pathname.startsWith('/quiz-bundles/import/') && document.querySelector('.portable-bundle-confirm-panel')", timeout=12)
    elif sid == "UM-07":
        browser.click(".study-mode-btn")
        browser.wait_for("document.querySelectorAll('#choices .choice').length >= 2")
        browser.click("#choices .choice[data-index='0']")
        browser.wait_for("document.querySelector('#choices .wrong-choice')")
    elif sid == "UM-08":
        browser.click(".exam-mode-btn")
        browser.wait_for("document.querySelectorAll('#choices .choice').length >= 2")
        browser.click("#choices .choice[data-index='1']")
        browser.click("#nextBtn")
        browser.wait_for("document.getElementById('qText').textContent.includes('multi-answer')")
        browser.click("#choices .choice[data-index='0']")
        browser.click("#choices .choice[data-index='2']")
    elif sid == "UM-09":
        if not browser.evaluate("Boolean(document.querySelector('.quiz-recovery-panel'))"):
            browser.click(".exam-mode-btn")
            browser.wait_for("document.querySelectorAll('#choices .choice').length >= 2")
            browser.click("#choices .choice[data-index='1']")
            browser.navigate(base_url + _resolve_route(spec, metadata))
        browser.wait_for("document.querySelector('.quiz-recovery-panel')")
    elif sid == "UM-12":
        browser.click("#liModelButton")
        browser.wait_for("!document.getElementById('liModel').hidden")
    elif sid == "UM-15":
        browser.set_files("input[name='pdf_file']", [metadata["pdf_path"]])
        browser.evaluate("(() => {const rights=document.querySelector('[name=rights_ok]');if(rights&&!rights.checked)rights.click();const title=document.querySelector('[name=quiz_title]');if(title)title.value='Study Skills from PDF';return true;})()")
    elif sid == "UM-16":
        browser.click("#pdfSelectAllVisible")
    elif sid == "UM-17":
        browser.set_files("form[action='/pdf-import/screenshots'] input[type=file]", [metadata["ocr_image_path"]])
        browser.evaluate("(() => {const form=document.querySelector(\"form[action='/pdf-import/screenshots']\");const rights=form?.querySelector('[name=rights_ok]');if(rights&&!rights.checked)rights.click();return true;})()")
    elif sid == "UM-19":
        browser.wait_for("document.getElementById('editorImage')?.naturalWidth > 0", timeout=12)
        browser.click("#editorStage")
        for key in ("\ue014", "\ue014", "\ue015", "\ue007", "\ue014", "\ue015", "\ue007", "\ue012", "\ue015", "\ue007"):
            browser.press_key(key)
    elif sid == "UM-20":
        browser.evaluate("(() => {const type=document.querySelector('[name=content_type]');if(type){type.value='matching';type.dispatchEvent(new Event('change',{bubbles:true}));}const topic=document.querySelector('[name=topic]');if(topic)topic.value='Study methods and learning strategies';return true;})()")
    elif sid == "UM-21":
        browser.evaluate("(() => {const topic=document.querySelector('[name=topic]');if(topic)topic.value='Learning Skills';document.querySelectorAll('input[type=checkbox]').forEach((box,index)=>{if(index<3&&!box.checked)box.click();});return true;})()")
    elif sid == "UM-24":
        browser.evaluate("(() => {const name=document.querySelector('[name=deck_name]');if(name)name.value='Learning Skills Review';[...document.querySelectorAll('input[type=checkbox]')].slice(0,4).forEach(box=>{if(!box.checked)box.click();});return true;})()")
    elif sid == "UM-26":
        browser.set_files("input[name='backup_file']", [metadata["restore_path"]])
        browser.click("form[action='/settings/backup/restore/stage'] button[type='submit']")
        browser.wait_for("location.pathname.includes('/settings/backup/restore') && document.querySelector(\"form[action*='/confirm/']\")", timeout=15)
    elif sid == "UM-27":
        browser.evaluate("window.confirm = () => false; true")
        browser.click("#rebuildAllBtn")


def _capture_png(browser, path: Path) -> None:
    result = browser.command("browsingContext.captureScreenshot", {"context": browser.context, "origin": "viewport"}, timeout=18)
    data = base64.b64decode(result["data"])
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise RuntimeError(f"Firefox did not return a PNG for {path.name}")
    path.write_bytes(data)


def _png_dimensions(path: Path) -> tuple[int, int]:
    data = path.read_bytes()[:24]
    if len(data) != 24 or not data.startswith(b"\x89PNG\r\n\x1a\n") or data[12:16] != b"IHDR":
        raise ValueError(f"Not a valid PNG: {path}")
    return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")


def _capture_group(browser, base_url: str, specs, metadata: dict, output: Path) -> list[dict]:
    records = []
    for spec in specs:
        route = _resolve_route(spec, metadata)
        browser.set_viewport(WIDTH, HEIGHT)
        browser.navigate(base_url + route)
        browser.wait_for(spec.ready, timeout=15)
        _prepare(browser, base_url, spec, metadata)
        _stable_page(browser)
        if spec.focus and spec.screenshot_id not in {"UM-09", "UM-12"}:
            browser.evaluate(f"document.querySelector({json.dumps(spec.focus)})?.scrollIntoView({{block:'start',inline:'nearest'}});true")
        path = output / spec.filename
        _capture_png(browser, path)
        width, height = _png_dimensions(path)
        records.append({
            **asdict(spec), "status": "Captured", "theme": THEME,
            "viewport": f"{WIDTH}×{HEIGHT}", "dimensions": f"{width}×{height}",
            "fixture_version": FIXTURE_VERSION, "capture_route": route,
        })
        print(f"Captured {spec.screenshot_id}: {path.relative_to(ROOT)}")
    return records


def _run_capture(selected: set[str], output: Path) -> list[dict]:
    output.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="dlms-manual-capture-"))
    data_root = work / "data"
    server = firefox_process = None
    browser = None
    records = []
    try:
        local_specs = [spec for spec in CAPTURES if spec.screenshot_id in selected and spec.screenshot_id != "UM-25"]
        if local_specs:
            server, base_url, env = _start_server(work, data_root, lan=False, reuse=False)
            metadata = json.loads((data_root / "browser_fixture.json").read_text(encoding="utf-8"))
            firefox_process, browser = _start_firefox(work, env)
            browser.set_viewport(WIDTH, HEIGHT)
            _set_theme(browser, base_url)
            # Prime one genuine browser-local interrupted checkpoint for UM-01
            # and leave the Exam checkpoint from UM-08 available for UM-09.
            critical_url = f"{base_url}/quizzes/{metadata['critical_html']}"
            browser.navigate(critical_url)
            browser.wait_for("quizRecoveryReady === true")
            browser.click(".study-mode-btn")
            browser.click("#choices .choice[data-index='0']")
            browser.navigate(base_url + "/")
            records.extend(_capture_group(browser, base_url, local_specs, metadata, output))
            browser.close()
            browser = None
            _stop_process(firefox_process)
            firefox_process = None
            _stop_process(server, interrupt=True)
            server = None

        if "UM-25" in selected:
            reuse = (data_root / "browser_fixture.json").is_file()
            server, base_url, env = _start_server(work, data_root, lan=True, reuse=reuse)
            metadata = json.loads((data_root / "browser_fixture.json").read_text(encoding="utf-8"))
            firefox_process, browser = _start_firefox(work, env)
            browser.set_viewport(WIDTH, HEIGHT)
            _set_theme(browser, base_url)
            spec = next(item for item in CAPTURES if item.screenshot_id == "UM-25")
            records.extend(_capture_group(browser, base_url, [spec], metadata, output))
        return sorted(records, key=lambda item: item["screenshot_id"])
    finally:
        if browser:
            browser.close()
        if firefox_process:
            _stop_process(firefox_process)
        if server:
            _stop_process(server, interrupt=True)
        shutil.rmtree(work, ignore_errors=True)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--only", help="Comma-separated UM IDs to refresh")
    parser.add_argument("--list", action="store_true", help="List the capture contract without starting Firefox")
    parser.add_argument("--serve", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--lan", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.serve:
        _serve(args.lan)
        return 0
    known = {item.screenshot_id for item in CAPTURES}
    selected = known if not args.only else {value.strip().upper() for value in args.only.split(",") if value.strip()}
    unknown = selected - known
    if unknown:
        parser.error("unknown screenshot ID(s): " + ", ".join(sorted(unknown)))
    if args.list:
        print(json.dumps([asdict(item) for item in CAPTURES if item.screenshot_id in selected], indent=2, ensure_ascii=False))
        return 0
    output = args.output.resolve()
    manual_root = (ROOT / "docs" / "user-manual").resolve()
    if manual_root not in output.parents and output != manual_root:
        parser.error("output must remain under docs/user-manual")
    records = _run_capture(selected, output)
    manifest_path = output / "capture-metadata.json"
    if selected != known and manifest_path.is_file():
        try:
            previous = json.loads(manifest_path.read_text(encoding="utf-8"))
            previous_records = {
                record.get("screenshot_id"): record
                for record in previous.get("captures", [])
                if isinstance(record, dict) and record.get("screenshot_id") in known
            }
        except (OSError, ValueError):
            previous_records = {}
        previous_records.update({record["screenshot_id"]: record for record in records})
        records = [
            previous_records[item.screenshot_id]
            for item in CAPTURES
            if item.screenshot_id in previous_records
        ]
    manifest_path.write_text(json.dumps({
        "application": "DLMS", "version": _application_version(), "generated_at": datetime.now(timezone.utc).isoformat(),
        "browser": "Firefox (headless WebDriver BiDi)", "theme": THEME,
        "viewport": {"width": WIDTH, "height": HEIGHT, "device_scale": 1},
        "fixture_version": FIXTURE_VERSION, "captures": records,
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {len(records)} capture record(s) and {manifest_path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
