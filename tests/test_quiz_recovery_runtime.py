import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (ROOT / "static" / "script.js").read_text(encoding="utf-8")
RECOVERY = (ROOT / "static" / "quiz-recovery.js").read_text(encoding="utf-8")
LIBRARY_TEMPLATE = (ROOT / "templates" / "quiz" / "library.html").read_text(encoding="utf-8")
RESET_TEMPLATE = (ROOT / "templates" / "settings" / "reset-remove.html").read_text(encoding="utf-8")
RESTORE_COMPLETE_TEMPLATE = (ROOT / "templates" / "settings" / "restore-complete.html").read_text(encoding="utf-8")
RESTORE_CONFIRM_TEMPLATE = (ROOT / "templates" / "settings" / "restore-confirm.html").read_text(encoding="utf-8")
RESTORE_FAILED_TEMPLATE = (ROOT / "templates" / "settings" / "restore-failed.html").read_text(encoding="utf-8")


def test_recovery_is_a_dedicated_compatibility_loaded_runtime():
    assert 'script.src = "/static/quiz-recovery.js"' in SCRIPT
    assert "window.DLMSQuizRecovery" in RECOVERY
    assert "loadQuizRecoveryRuntime" in SCRIPT
    assert 'fetch(file, {cache: "no-store"})' in SCRIPT


def test_recovery_namespace_fingerprint_and_limits_are_versioned_and_bounded():
    assert 'STORAGE_PREFIX = "dlms.quiz-progress.v1:"' in RECOVERY
    assert 'RUNTIME_VERSION = "quiz-recovery-v1"' in RECOVERY
    assert "SHA-256" in RECOVERY
    assert "MAX_RECORD_BYTES = 512 * 1024" in RECOVERY
    assert "EXPIRY_MS = 30 * 24 * 60 * 60 * 1000" in RECOVERY
    assert "removeStored()" in RECOVERY
    assert "`${STORAGE_PREFIX}${encodeURIComponent(context.quizId)}`" in RECOVERY


def test_lifecycle_cleanup_is_scoped_and_best_effort():
    assert "function pruneStoredRecords" in RECOVERY
    assert "function listStoredRecords" in RECOVERY
    assert "function clearAllStoredRecords" in RECOVERY
    assert "function removeStoredQuiz" in RECOVERY
    assert "key.startsWith(STORAGE_PREFIX)" in RECOVERY
    assert "localStorage.clear(" not in RECOVERY
    assert "validateRecordEnvelope(record, now)" in RECOVERY
    assert "active.has(quizId)" in RECOVERY
    assert "pruneStoredRecords();" in RECOVERY
    assert "listStoredRecords," in RECOVERY
    assert "!current && savedRecord !== null && !allowTakeover" in RECOVERY


def test_fingerprint_tracks_playable_artifact_not_display_title():
    fingerprint_start = RECOVERY.index("async function quizFingerprint")
    fingerprint_end = RECOVERY.index("function questionDescriptors", fingerprint_start)
    fingerprint = RECOVERY[fingerprint_start:fingerprint_end]
    assert "rawQuizText" in fingerprint
    assert "quizId" in fingerprint
    assert "quizFile" in fingerprint
    assert "examMinutes" in fingerprint
    assert "quizTitle" not in fingerprint


def test_lifecycle_pages_clear_only_after_successful_destructive_operations():
    assert 'id="libraryQuizIdentityData"' in LIBRARY_TEMPLATE
    assert "pruneStoredRecords({activeQuizIds})" in LIBRARY_TEMPLATE
    assert '"/api/reset_quiz_library","/api/reset_all_data"' in RESET_TEMPLATE
    assert "quizRecoveryClearingResetEndpoints.has(btn.dataset.endpoint)" in RESET_TEMPLATE
    assert "window.DLMSQuizRecovery?.clearAllStoredRecords();" in RESET_TEMPLATE
    assert "window.DLMSQuizRecovery?.clearAllStoredRecords();" in RESTORE_COMPLETE_TEMPLATE
    assert "clearAllStoredRecords" not in RESTORE_CONFIRM_TEMPLATE
    assert "clearAllStoredRecords" not in RESTORE_FAILED_TEMPLATE


def test_recovery_record_does_not_embed_quiz_content_or_scoring_results():
    record_block = RECOVERY[
        RECOVERY.index("const record = {") : RECOVERY.index("if (!validateRecord(record", RECOVERY.index("const record = {"))
    ]
    for forbidden in (
        "rawQuizText",
        "questionText",
        "question_text",
        "correctAnswers",
        "correctText",
        "missedDetails",
        "score:",
        "percent:",
        "renderedHtml",
    ):
        assert forbidden not in record_block
    assert "pendingAttempt: snapshot.pendingAttempt" in record_block
    assert "responses: quiz.map" in SCRIPT


def test_restoration_is_explicit_and_does_not_issue_network_requests():
    restore_start = SCRIPT.index("function restoreQuizRecoveryState")
    restore_end = SCRIPT.index("/* =====================================================\n   START QUIZ", restore_start)
    restore_block = SCRIPT[restore_start:restore_end]
    assert "fetch(" not in restore_block
    assert "recordStudyLearningEvent" not in restore_block
    assert "savePendingExamAttempt" not in restore_block
    assert 'resume.textContent = record.session.phase === "submitting"' in RECOVERY
    assert 'reset.textContent = "Start Over"' in RECOVERY


def test_study_and_exam_identities_survive_recovery_without_automatic_retry():
    assert "learningSessionId" in RECOVERY
    assert "unacknowledgedStudyEvents" in RECOVERY
    assert 'state: "failed"' in SCRIPT
    assert "options.finishSubmission(claimed.pendingAttempt)" in RECOVERY
    assert "recoveredAttempt?.attemptId" in SCRIPT
    assert "recoveredAttempt?.completedAt" in SCRIPT
    assert "quizRecoveryController?.complete()" in SCRIPT
    assert "studyLearningEventSaves.set(record.eventId, record)" in SCRIPT


def test_all_playable_question_state_shapes_and_exact_matching_variant_are_covered():
    assert 'if (descriptor.type === "choice")' in RECOVERY
    assert 'descriptor.type === "hotspot"' in RECOVERY
    assert "sourcePairIndexes" in RECOVERY
    assert "optionOrder" in RECOVERY
    assert "matchingInteractionMode" in RECOVERY
    assert "matchingPendingRightIndex" not in re.search(
        r"const record = \{.*?if \(!validateRecord\(record", RECOVERY, re.S
    ).group(0)


def test_timer_is_checkpointed_without_wall_clock_subtraction():
    assert "timeRemaining % 5 === 0" in SCRIPT
    assert "remainingSeconds: Math.max(0, Math.floor(timeRemaining))" in SCRIPT
    assert "timeRemaining = record.timer.remainingSeconds" in SCRIPT
    assert "Date.now() -" not in SCRIPT[SCRIPT.index("function restoreQuizRecoveryState"):SCRIPT.index("function startQuiz")]


def test_recovery_does_not_couple_to_browser_presence_runtime():
    assert "heartbeat" not in RECOVERY.lower()
    assert "browser_presence" not in RECOVERY.lower()
    assert "browserPresence" not in SCRIPT
