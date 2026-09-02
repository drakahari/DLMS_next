"""DLMS-085 regressions for core keyboard-operable quiz choices."""

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (ROOT / "static" / "script.js").read_text(encoding="utf-8")
STYLE = (ROOT / "static" / "style.css").read_text(encoding="utf-8")


def _function_block(source: str, name: str) -> str:
    match = re.search(rf"(?m)^function {re.escape(name)}\(", source)
    if not match:
        raise AssertionError(f"Could not find JavaScript function {name}")
    next_function = re.search(r"(?m)^function [A-Za-z_$][\w$]*\(", source[match.end():])
    end = match.end() + next_function.start() if next_function else len(source)
    return source[match.start():end]


def test_choices_are_native_buttons_with_selection_semantics_and_mouse_activation():
    render = _function_block(SCRIPT, "renderQuestion")

    assert 'document.createElement("button")' in render
    assert 'choiceElement.type = "button"' in render
    assert 'choiceElement.setAttribute("aria-pressed", String(selected.includes(i)))' in render
    assert 'choiceElement.addEventListener("click", () => selectChoice(i));' in render
    assert 'choicesEl.setAttribute("role", "group")' in render
    assert "Select all correct answers" in render
    assert "Select one answer" in render


def test_native_choice_activation_has_one_handler_and_no_duplicate_keyboard_listener():
    render = _function_block(SCRIPT, "renderQuestion")

    # Native buttons synthesize one click for Enter/Space. Keeping exactly one
    # click listener preserves mouse/touch behavior and avoids double handling.
    assert render.count('choiceElement.addEventListener("click", () => selectChoice(i));') == 1
    assert "choiceElement.addEventListener(\"keydown\"" not in render
    assert "choiceElement.addEventListener(\"keypress\"" not in render


def test_choice_state_and_disabled_native_semantics_remain_exposed_to_assistive_technology():
    feedback = _function_block(SCRIPT, "applyStudyFeedback")

    assert 'btn.setAttribute("aria-pressed", String(selected.includes(Number(btn.dataset.index))))' in feedback
    assert '}. Correct.`)' in feedback
    assert '}. Incorrect.`)' in feedback
    # A disabled native button is unfocusable and does not dispatch activation;
    # no ARIA-only disabled state is used for answer controls.
    assert 'choiceElement.setAttribute("aria-disabled"' not in SCRIPT


def test_choice_buttons_receive_the_existing_theme_aware_keyboard_focus_indicator():
    focus_rule = re.search(
        r":where\(a\[href\], button, input, select, textarea, summary, \[tabindex\]\):focus-visible\s*\{([^}]*)\}",
        STYLE,
    )
    assert focus_rule is not None
    assert "outline: 3px solid var(--theme-accent-text" in focus_rule.group(1)
    assert "outline-offset: 3px" in focus_rule.group(1)

    choice_rules = re.findall(r"\.choice\s*\{([^}]*)\}", STYLE)
    assert any("font-family: inherit" in rule for rule in choice_rules)
    assert any("font-weight: inherit" in rule for rule in choice_rules)


def test_matching_keeps_its_existing_native_keyboard_path_and_hotspot_is_not_reframed_as_keyboard_equivalent():
    matching = _function_block(SCRIPT, "renderMatchingQuestion")
    hotspot = _function_block(SCRIPT, "renderHotspotQuestion")

    assert '<select class="matching-select"' in matching
    assert 'type="button" class="matching-answer-chip' in matching
    assert 'type="button" class="matching-drop-target' in matching
    assert 'onclick="selectHotspot(event)"' in hotspot
    assert "tabindex" not in hotspot
