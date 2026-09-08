"""DLMS-103 regressions for remaining cross-application accessibility gaps."""

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_SOURCE = (ROOT / "app.py").read_text(encoding="utf-8")
STYLE = (ROOT / "static" / "style.css").read_text(encoding="utf-8")
NAVIGATION = (ROOT / "static" / "nav-normalize.js").read_text(encoding="utf-8")
LIBRARY_SOURCE = (ROOT / "templates" / "quiz" / "library.html").read_text(encoding="utf-8")


def _template_source(relative_path):
    return (ROOT / "templates" / relative_path).read_text(encoding="utf-8")


def _ui_sources():
    yield ROOT / "app.py", APP_SOURCE
    for path in sorted((ROOT / "dlms" / "routes").rglob("*.py")):
        yield path, path.read_text(encoding="utf-8")
    for path in sorted((ROOT / "static").glob("*.html")):
        yield path, path.read_text(encoding="utf-8")
    for path in sorted((ROOT / "templates").rglob("*.html")):
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
        "library.html": ('id="librarySearch"', 'aria-label="Search quizzes"'),
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
    assert 'class="folder-toggle-icon library-folder-toggle-button"' in LIBRARY_SOURCE
    assert 'aria-expanded="true"' in LIBRARY_SOURCE
    assert 'aria-controls="library-folder-body-{{ loop.index }}"' in LIBRARY_SOURCE
    assert 'icon.setAttribute("aria-expanded", String(!collapsed))' in LIBRARY_SOURCE
    assert 'aria-label="Rename {{ folder_name }}"' in LIBRARY_SOURCE
    assert 'aria-label="Delete {{ folder_name }} folder"' in LIBRARY_SOURCE
    assert 'class="library-folder-hidden-badge">Hidden folder</span>' in LIBRARY_SOURCE
    assert 'aria-label="{{ \'Unhide\' if folder_is_hidden else \'Hide\' }} {{ folder_name }} folder"' in LIBRARY_SOURCE
    assert 'action="/set_quiz_folder_hidden"' in LIBRARY_SOURCE
    assert "renameButton.focus()" in LIBRARY_SOURCE
    assert "newFolderButton.focus()" in LIBRARY_SOURCE
    assert "moveButton.focus()" in LIBRARY_SOURCE
    assert '<p class="library-folder-empty">No quizzes in this view.</p>' in LIBRARY_SOURCE
    assert "color: var(--theme-muted-text, #8297b4);" in STYLE
    assert "color: var(--theme-accent-text, #78bfff);" in STYLE


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


def test_dataset_disclosures_reference_stable_regions_and_synchronize_state():
    study_packs = _template_source("study_packs/catalog.html")
    for kind in ("mixed", "matching", "image"):
        control = "dataset-{{ pack.id }}-" + kind + "-{{ loop.index }}"
        assert f'aria-controls="{control}"' in study_packs
        assert f'id="{control}"' in study_packs
    assert study_packs.count('aria-expanded="false"') >= 4
    assert "toggle.setAttribute('aria-expanded',String(open))" in study_packs

    it_matching = _template_source("it/matching.html")
    assert 'aria-controls="it-match-{{ loop.index }}"' in it_matching
    assert 'id="it-match-{{ loop.index }}"' in it_matching
    assert "toggle.setAttribute('aria-expanded',String(open))" in it_matching
    assert "setItDetails(true)" in it_matching
    assert "setItDetails(false)" in it_matching

    it_images = _template_source("it/images.html")
    assert 'aria-controls="it-image-{{ loop.index }}"' in it_images
    assert 'id="it-image-{{ loop.index }}"' in it_images
    assert "toggle.setAttribute('aria-expanded',String(open))" in it_images

    medical_matching = _template_source("medical/matching.html")
    assert 'aria-controls="matching-detail-{{ loop.index }}"' in medical_matching
    assert 'id="matching-detail-{{ loop.index }}"' in medical_matching
    assert 'toggle.setAttribute("aria-expanded", open ? "true" : "false")' in medical_matching

    medical_anatomy = _template_source("medical/anatomy.html")
    assert 'aria-controls="anatomy-detail-{{ loop.index }}"' in medical_anatomy
    assert 'id="anatomy-detail-{{ loop.index }}"' in medical_anatomy
    assert 'toggle.setAttribute("aria-expanded", open ? "true" : "false")' in medical_anatomy


def test_law_fields_and_reveal_controls_have_programmatic_names():
    law_import = _template_source("law/import.html")
    assert 'for="lawRawPacketInput"' in law_import
    assert 'id="lawRawPacketInput" name="raw_packet"' in law_import

    import_detail = _template_source("law/import-detail.html")
    assert '<label for="lawSavedRawPacket">Raw Packet Text</label>' in import_detail
    assert 'id="lawSavedRawPacket" class="law-raw-packet"' in import_detail

    law_create = _template_source("law/create.html")
    assert 'id="lawGeneratedPromptHeading"' in law_create
    assert 'aria-labelledby="lawGeneratedPromptHeading"' in law_create

    case_detail = _template_source("law/case-detail.html")
    for field_id in (
        "lawCaseTitle",
        "lawCaseCourse",
        "lawIracIssue",
        "lawIracRule",
        "lawIracAnalysis",
        "lawIracConclusion",
    ):
        assert f'for="{field_id}"' in case_detail
        assert f'id="{field_id}"' in case_detail
    assert 'for="lawSocraticAnswer{{ loop.index }}"' in case_detail
    assert 'id="lawSocraticAnswer{{ loop.index }}"' in case_detail
    assert 'id="lawStudentNotesHeading"' in case_detail
    assert 'aria-labelledby="lawStudentNotesHeading"' in case_detail
    assert 'aria-expanded="false" aria-controls="iracDrillBox"' in case_detail
    assert 'aria-expanded="false" aria-controls="socraticAnswerKey"' in case_detail
    assert 'id="iracDrillBox"' in case_detail
    assert 'id="socraticAnswerKey"' in case_detail
    assert 'setAttribute("aria-expanded", String(open))' in case_detail


def test_post_action_feedback_uses_status_or_alert_without_announcing_static_guidance():
    law_import = _template_source("law/import.html")
    assert 'class="law-notice success" role="status" aria-live="polite"' in law_import
    assert "{% if save_message_category == 'error' %}role=\"alert\"" in law_import
    assert "{% else %}role=\"status\" aria-live=\"polite\"{% endif %}" in law_import
    assert '<div class="law-notice warning">' in law_import

    import_detail = _template_source("law/import-detail.html")
    assert 'class="law-message success" role="status" aria-live="polite"' in import_detail
    assert '<div class="law-message success"><strong>Parser preview:' in import_detail

    for relative_path in (
        "law/case-detail.html",
        "law/cases.html",
        "law/imports.html",
        "settings/ai.html",
        "settings/appearance.html",
        "settings/navigation.html",
        "settings/parsing.html",
    ):
        source = _template_source(relative_path)
        assert 'role="status" aria-live="polite"' in source, relative_path

    content_review = _template_source("content_packs/import-review.html")
    assert "{% if report.valid %}role=\"status\" aria-live=\"polite\"{% else %}role=\"alert\"{% endif %}" in content_review
    assert '<div class="pack-validation-messages warnings">' in content_review

    content_catalog = _template_source("content_packs/index.html")
    assert "{% if category == 'error' %}role=\"alert\"{% else %}role=\"status\" aria-live=\"polite\"{% endif %}" in content_catalog

    backup = _template_source("settings/backup.html")
    assert 'class="settings-critical-panel" role="alert"' in backup
    assert 'class="settings-warning-panel" role="status" aria-live="polite"' in backup
    assert '<div class="settings-warning-panel"><strong>Restore is deliberately cautious.' in backup

    for relative_path in (
        "settings/backup-failed.html",
        "settings/restore-failed.html",
        "settings/restore-validation-failed.html",
    ):
        assert 'class="settings-critical-panel" role="alert"' in _template_source(relative_path)

    reset_remove = _template_source("settings/reset-remove.html")
    assert reset_remove.count('role="status" aria-live="polite"') == 2
    assert 'target.setAttribute("role",isError?"alert":"status")' in reset_remove
    assert 'target.setAttribute("aria-live",isError?"assertive":"polite")' in reset_remove
