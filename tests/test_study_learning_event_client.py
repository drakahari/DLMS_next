"""DLMS-095 Study learning-event acknowledgement and retry client contracts."""

import re
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "static" / "script.js"


def _function_block(source: str, name: str) -> str:
    match = re.search(rf"(?m)^(?:async )?function {re.escape(name)}\(", source)
    if not match:
        raise AssertionError(f"Could not find JavaScript function {name}")
    next_function = re.search(
        r"(?m)^(?:async )?function [A-Za-z_$][\w$]*\(", source[match.end():]
    )
    end = match.end() + next_function.start() if next_function else len(source)
    return source[match.start():end]


def test_study_save_requires_the_matching_server_acknowledgement():
    source = SCRIPT.read_text(encoding="utf-8")
    save = _function_block(source, "saveStudyLearningEvent")

    assert "async function saveStudyLearningEvent" in save
    assert 'await fetch("/api/learning-events/study-response"' in save
    assert "!response.ok" in save
    assert "data.ok !== true" in save
    assert 'String(data.event_id || "") !== record.eventId' in save
    assert "await response.json()" in save


def test_network_http_and_malformed_acknowledgement_failures_show_one_retry_status():
    source = SCRIPT.read_text(encoding="utf-8")
    ensure_status = _function_block(source, "ensureStudyLearningEventStatus")
    update_status = _function_block(source, "updateStudyLearningEventStatus")
    save = _function_block(source, "saveStudyLearningEvent")

    assert 'getElementById("studyLearningEventStatus")' in ensure_status
    assert 'status.setAttribute("role", "status")' in ensure_status
    assert 'status.setAttribute("aria-live", "polite")' in ensure_status
    assert 'message.textContent = retrying && !failed.length' in update_status
    assert '"Learning progress was not saved."' in update_status
    assert 'retry.textContent = "Retry"' in ensure_status
    assert 'record.state = "failed"' in save
    assert "return false" in save
    assert "nextBtn" not in save


def test_retry_reuses_failed_event_identity_and_success_clears_the_warning_state():
    source = SCRIPT.read_text(encoding="utf-8")
    retry = _function_block(source, "retryStudyLearningEventSaves")
    save = _function_block(source, "saveStudyLearningEvent")
    record = _function_block(source, "recordStudyLearningEvent")

    assert "failed.map(record => saveStudyLearningEvent(record, true))" in retry
    assert "body: JSON.stringify(record.payload)" in save
    assert "studyLearningEventSaves.delete(record.questionKey)" in save
    assert "updateStudyLearningEventStatus()" in save
    assert "eventId: eventId" in record
    assert "await saveStudyLearningEvent(record)" in record


def test_choice_matching_and_hotspot_answer_handlers_save_without_blocking_progression():
    source = SCRIPT.read_text(encoding="utf-8")
    choice = _function_block(source, "selectChoice")
    matching = _function_block(source, "commitMatchingAnswer")
    hotspot = _function_block(source, "selectHotspot")

    assert "void recordStudyLearningEvent" in choice
    assert "void recordStudyLearningEvent" in matching
    assert "void recordStudyLearningEvent" in hotspot
    assert "renderQuestion()" in choice
    assert "renderQuestion()" in matching
    assert "renderQuestion()" in hotspot


def test_starting_a_new_quiz_session_drops_only_the_in_memory_retry_state():
    source = SCRIPT.read_text(encoding="utf-8")
    start = _function_block(source, "startQuiz")

    assert "learningSessionId = createLearningSessionId()" in start
    assert "studyLearningEventSaves.clear()" in start
    assert "updateStudyLearningEventStatus()" in start


def test_question_navigation_preserves_failed_retry_state():
    source = SCRIPT.read_text(encoding="utf-8")
    next_question = _function_block(source, "next")
    previous_question = _function_block(source, "prev")

    assert "renderQuestion()" in next_question
    assert "renderQuestion()" in previous_question
    assert "studyLearningEventSaves.clear()" not in next_question
    assert "studyLearningEventSaves.clear()" not in previous_question
