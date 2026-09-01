"""Focused regressions for Study Mode answer feedback timing."""

from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "static" / "script.js"


def _function_block(source: str, name: str, next_name: str) -> str:
    start = source.index(f"function {name}(")
    end = source.index(f"function {next_name}(", start)
    return source[start:end]


def test_choice_wrong_attempt_allows_retry_without_explanation_reveal():
    source = SCRIPT.read_text(encoding="utf-8")
    feedback = _function_block(source, "applyStudyFeedback", "renderHotspotQuestion")

    assert '"✕ Not quite — try another answer."' in feedback
    assert "if (state.isCorrect)" in feedback
    assert feedback.index("if (state.isCorrect)") < feedback.index("q.explanation")
    assert "choice-study-explanation" in feedback
    assert "is-wrong" in feedback


def test_choice_correct_answer_records_completion_and_reveals_explanation():
    source = SCRIPT.read_text(encoding="utf-8")
    select_choice = _function_block(source, "selectChoice", "choiceStudyState")
    feedback = _function_block(source, "applyStudyFeedback", "renderHotspotQuestion")

    assert "recordStudyLearningEvent(q, state.isCorrect" in select_choice
    assert 'title="✓ Correct"' in feedback
    assert "choice-study-explanation" in feedback


def test_hotspot_wrong_attempt_hides_target_and_explanation_until_correct():
    source = SCRIPT.read_text(encoding="utf-8")
    hotspot = _function_block(source, "renderHotspotQuestion", "pointInHotspot")

    assert "Try another location on the image." in hotspot
    assert "if (isCorrect)" in hotspot
    assert hotspot.index("if (isCorrect)") < hotspot.index("q.explanation")
    assert "hotspot-correct-marker" not in hotspot


def test_matching_wrong_attempt_hides_correct_match_and_explanation():
    source = SCRIPT.read_text(encoding="utf-8")
    feedback = _function_block(source, "matchingFeedbackHtml", "commitMatchingAnswer")

    assert "Try a different match." in feedback
    assert "if (isCorrect)" in feedback
    assert feedback.index("if (isCorrect)") < feedback.index("pair.explanation")
    assert "Correct match:" not in feedback


def test_exam_mode_keeps_study_feedback_suppressed():
    source = SCRIPT.read_text(encoding="utf-8")
    hotspot = _function_block(source, "renderHotspotQuestion", "pointInHotspot")
    matching = _function_block(source, "matchingFeedbackHtml", "commitMatchingAnswer")

    assert "if (!examMode && hasAnswer)" in hotspot
    assert 'if (examMode || chosen === "") return "";' in matching
