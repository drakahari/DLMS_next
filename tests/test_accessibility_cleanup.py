"""DLMS-103 regressions for remaining cross-application accessibility gaps."""

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_SOURCE = (ROOT / "app.py").read_text(encoding="utf-8")
STYLE = (ROOT / "static" / "style.css").read_text(encoding="utf-8")
NAVIGATION = (ROOT / "static" / "nav-normalize.js").read_text(encoding="utf-8")


def _ui_sources():
    yield ROOT / "app.py", APP_SOURCE
    for path in sorted((ROOT / "static").glob("*.html")):
        yield path, path.read_text(encoding="utf-8")


def test_every_sidebar_menu_button_has_native_and_disclosure_semantics():
    menu_buttons = []
    for path, source in _ui_sources():
        for match in re.finditer(r"<button\b[^>]*dashboard-menu-button[^>]*>", source):
            menu_buttons.append((path.name, match.group(0)))

    assert len(menu_buttons) >= 70
    for filename, button in menu_buttons:
        assert 'type="button"' in button, filename
        assert 'aria-label="Toggle navigation"' in button, filename
        assert 'aria-controls="dashboardSidebar"' in button, filename
        assert 'aria-expanded="false"' in button, filename


def test_sidebar_disclosure_state_keyboard_entry_and_escape_focus_are_managed():
    assert "button.setAttribute('aria-expanded', String(open))" in NAVIGATION
    assert "if (event.detail === 0)" in NAVIGATION
    assert "sidebar.querySelector('a[href], button:not(:disabled), select')?.focus()" in NAVIGATION
    assert "event.key !== 'Escape'" in NAVIGATION
    assert "sidebar.classList.remove('open')" in NAVIGATION
    assert "menuButtons[0]?.focus()" in NAVIGATION


def test_search_controls_have_programmatic_names_not_only_placeholders():
    expected = {
        "app.py": ('id="librarySearch"', 'aria-label="Search quizzes"'),
        "learning-diagnostics.html": (
            'id="dqSearch"',
            'aria-label="Search questions or concepts"',
        ),
        "review-schedule.html": (
            'id="rsSearch"',
            'aria-label="Search scheduled topics"',
        ),
    }
    sources = {path.name: source for path, source in _ui_sources()}
    for filename, attributes in expected.items():
        element = re.search(
            rf"<input\b[^>]*{re.escape(attributes[0])}[^>]*>", sources[filename]
        )
        assert element is not None, filename
        assert attributes[1] in element.group(0), filename


def test_library_folder_collapse_and_icon_actions_have_accessible_semantics():
    assert 'class="folder-toggle-icon library-folder-toggle-button"' in APP_SOURCE
    assert 'aria-expanded="true"' in APP_SOURCE
    assert 'aria-controls="library-folder-body-{{ loop.index }}"' in APP_SOURCE
    assert 'icon.setAttribute("aria-expanded", String(!collapsed))' in APP_SOURCE
    assert 'aria-label="Rename {{ folder_name }}"' in APP_SOURCE
    assert 'aria-label="Delete {{ folder_name }} folder"' in APP_SOURCE
    assert "renameButton.focus()" in APP_SOURCE
    assert "newFolderButton.focus()" in APP_SOURCE
    assert "moveButton.focus()" in APP_SOURCE
    assert '<p class="library-folder-empty">No quizzes in this view.</p>' in APP_SOURCE
    assert "color: var(--theme-muted-text, #8297b4);" in STYLE


def test_help_screenshot_dialog_contains_tab_focus_and_restores_previous_focus():
    assert "if (event.key === 'Tab')" in NAVIGATION
    assert "event.preventDefault()" in NAVIGATION
    assert "closeButton.focus()" in NAVIGATION
    assert "previousFocus.focus()" in NAVIGATION


def test_reduced_motion_preference_disables_nonessential_animation_and_smooth_scroll():
    rule = re.search(
        r"@media\s*\(prefers-reduced-motion:\s*reduce\)\s*\{([\s\S]+)\}\s*$",
        STYLE,
    )
    assert rule is not None
    body = rule.group(1)
    assert "animation-duration: 0.01ms !important" in body
    assert "animation-iteration-count: 1 !important" in body
    assert "transition-duration: 0.01ms !important" in body
    assert "scroll-behavior: auto !important" in body
