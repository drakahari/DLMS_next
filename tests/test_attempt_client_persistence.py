"""DLMS-092 client-side attempt persistence contract regressions."""

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


def test_exam_responses_and_missed_details_share_runtime_ordinal_identity():
    submit = _function_block(SCRIPT.read_text(encoding="utf-8"), "submitQuiz")

    assert "async function submitQuiz" in submit
    assert submit.count("attemptQuestionNumber: i + 1") == 6
    assert "attemptQuestionNumber: q.number" not in submit


def test_exam_attempt_is_awaited_and_requires_server_success_acknowledgement():
    save = _function_block(
        SCRIPT.read_text(encoding="utf-8"), "savePendingExamAttempt"
    )

    assert 'persistDesktopOrWebAction("exam", pending.payload,' in save
    assert '"/record_attempt", fetch)' in save
    helper = _function_block(SCRIPT.read_text(encoding="utf-8"), "persistDesktopOrWebAction")
    assert 'return webFetch(webUrl' in helper
    assert 'return fetch("/_desktop/recovery/action"' in helper
    assert "!response.ok" in save
    assert "data.ok !== true" in save
    assert 'String(data.attempt_id || "") !== String(pending.attemptId)' in save
    assert save.index("!response.ok") < save.index("saveHistory(")


def test_review_action_is_only_rendered_for_a_durably_saved_attempt():
    render = _function_block(SCRIPT.read_text(encoding="utf-8"), "renderExamResult")

    assert 'const saved = state === "saved"' in render
    assert "const persistenceAction = saved" in render
    assert "Review This Attempt" in render
    assert "Retry Saving Attempt" in render
    assert "not confirmed as retained or saved" in render
    assert "retained for Desktop recovery" in render


def test_retry_reuses_pending_attempt_payload_and_id():
    source = SCRIPT.read_text(encoding="utf-8")
    submit = _function_block(source, "submitQuiz")
    save = _function_block(source, "savePendingExamAttempt")
    retry = _function_block(source, "retryExamAttemptSave")

    assert "pendingExamAttempt = {" in submit
    assert "payload: attemptPayload" in submit
    helper = _function_block(source, "persistDesktopOrWebAction")
    assert "body: JSON.stringify(payload)" in helper
    assert "body: JSON.stringify({kind, payload, fingerprint: quizContentFingerprint})" in helper
    assert "pendingExamAttempt = null" in save
    assert "void savePendingExamAttempt()" in retry
