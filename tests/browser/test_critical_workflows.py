"""Opt-in browser regressions for DLMS's highest-risk client/server seams."""

from __future__ import annotations

import json
import os
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import pytest

from tests.browser._bidi import FirefoxBidi


ROOT = Path(__file__).resolve().parents[2]
RUN_BROWSER_TESTS = os.environ.get("DLMS_RUN_BROWSER_TESTS") == "1"

pytestmark = [
    pytest.mark.browser,
    pytest.mark.skipif(
        not RUN_BROWSER_TESTS,
        reason="set DLMS_RUN_BROWSER_TESTS=1 to run isolated Firefox regressions",
    ),
]


@dataclass
class BrowserStack:
    browser: FirefoxBidi
    base_url: str
    data_root: Path
    metadata: dict


def _free_loopback_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait_for_server(url, process, log_path, timeout=12.0):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    deadline = time.monotonic() + timeout
    last_error = None
    while time.monotonic() < deadline:
        if process.poll() is not None:
            break
        try:
            with opener.open(url, timeout=0.5) as response:
                if response.status == 200:
                    return
        except Exception as exc:
            last_error = exc
        time.sleep(0.05)
    log = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
    raise RuntimeError(f"DLMS test server did not start: {last_error}\n{log[-4000:]}")


def _connect_firefox(port, process, log_path, timeout=12.0):
    deadline = time.monotonic() + timeout
    last_error = None
    while time.monotonic() < deadline:
        if process.poll() is not None:
            break
        client = None
        try:
            client = FirefoxBidi.connect("127.0.0.1", port, timeout=0.5)
            client.start_session()
            return client
        except Exception as exc:
            last_error = exc
            if client is not None:
                client.close()
        time.sleep(0.05)
    log = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
    raise RuntimeError(f"Firefox WebDriver BiDi did not start: {last_error}\n{log[-4000:]}")


def _terminate_process_tree(process):
    if process is None:
        return
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
    elif process.poll() is None:
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
    else:
        return
    try:
        process.wait(timeout=5)
        return
    except subprocess.TimeoutExpired:
        pass
    if os.name == "posix":
        os.killpg(process.pid, signal.SIGKILL)
    else:
        process.kill()
    process.wait(timeout=5)


@pytest.fixture(scope="module")
def browser_stack(tmp_path_factory):
    firefox = shutil.which("firefox") or shutil.which("firefox-esr")
    if not firefox:
        pytest.skip("Firefox is not installed")

    work_root = tmp_path_factory.mktemp("dlms-browser")
    data_root = work_root / "data-root"
    profile = work_root / "firefox-profile"
    profile.mkdir()
    (profile / "user.js").write_text(
        '\n'.join([
            'user_pref("datareporting.healthreport.uploadEnabled", false);',
            'user_pref("toolkit.telemetry.enabled", false);',
            'user_pref("browser.crashReports.unsubmittedCheck.autoSubmit2", false);',
        ]),
        encoding="utf-8",
    )
    server_port = _free_loopback_port()
    browser_port = _free_loopback_port()
    base_url = f"http://127.0.0.1:{server_port}"
    server_log = work_root / "server.log"
    browser_log = work_root / "firefox.log"
    env = os.environ.copy()
    env.update({
        "QUIZAPP_DATA_DIR": str(data_root),
        "DLMS_NO_BROWSER": "1",
        "DLMS_BROWSER_TEST_PORT": str(server_port),
        "MOZ_CRASHREPORTER_DISABLE": "1",
        "MOZ_DISABLE_AUTO_SAFE_MODE": "1",
        "PYTHONUNBUFFERED": "1",
    })
    process_options = {"start_new_session": True} if os.name == "posix" else {}
    server_process = None
    browser_process = None
    browser = None

    try:
        with server_log.open("w", encoding="utf-8") as server_output, browser_log.open("w", encoding="utf-8") as browser_output:
            server_process = subprocess.Popen(
                [sys.executable, str(ROOT / "tests" / "browser" / "_server.py")],
                cwd=ROOT,
                env=env,
                stdout=server_output,
                stderr=subprocess.STDOUT,
                **process_options,
            )
            _wait_for_server(f"{base_url}/library", server_process, server_log)
            metadata = json.loads((data_root / "browser_fixture.json").read_text(encoding="utf-8"))

            browser_process = subprocess.Popen(
                [
                    firefox,
                    "--headless",
                    "--no-remote",
                    "--profile",
                    str(profile),
                    "--remote-debugging-port",
                    str(browser_port),
                    "about:blank",
                ],
                cwd=ROOT,
                env=env,
                stdout=browser_output,
                stderr=subprocess.STDOUT,
                **process_options,
            )
            browser = _connect_firefox(browser_port, browser_process, browser_log)
            yield BrowserStack(browser, base_url, data_root, metadata)
    finally:
        if browser is not None:
            browser.close()
        _terminate_process_tree(browser_process)
        _terminate_process_tree(server_process)
        shutil.rmtree(work_root, ignore_errors=True)


def _wait_for_database_value(path, query, expected, timeout=6.0):
    deadline = time.monotonic() + timeout
    last_value = None
    while time.monotonic() < deadline:
        try:
            with sqlite3.connect(path, timeout=0.5) as connection:
                row = connection.execute(query).fetchone()
                last_value = row[0] if row else None
            if last_value == expected:
                return
        except sqlite3.Error:
            pass
        time.sleep(0.05)
    raise AssertionError(f"Database value was {last_value!r}, expected {expected!r}: {query}")


def _database_value(path, query, parameters=()):
    with sqlite3.connect(path, timeout=0.5) as connection:
        row = connection.execute(query, parameters).fetchone()
    return row[0] if row else None


def test_library_reorder_control_persists_after_refresh(browser_stack):
    browser = browser_stack.browser
    browser.navigate(f"{browser_stack.base_url}/library")
    browser.wait_for("document.querySelectorAll('.library-quiz-card').length === 2")

    browser.activate()
    browser.set_viewport(800, 700)
    assert browser.evaluate(
        "(() => { const sidebar = document.getElementById('dashboardSidebar'); "
        "const menu = document.getElementById('menuButton'); "
        "sidebar.classList.add('open'); menu.setAttribute('aria-expanded', 'true'); "
        "sidebar.querySelector('a[href]').focus(); "
        "return document.activeElement.closest('#dashboardSidebar') === sidebar; })()"
    ) is True
    browser.press_key("\ue00c")
    browser.wait_for("!document.getElementById('dashboardSidebar').classList.contains('open')")
    assert browser.evaluate(
        "document.getElementById('menuButton').getAttribute('aria-expanded') === 'false' && "
        "document.activeElement === document.getElementById('menuButton')"
    ) is True

    order_expression = (
        "[...document.querySelectorAll('.library-quiz-card')]"
        ".map(card => card.dataset.title).join('|')"
    )
    initial_order = browser.evaluate(order_expression)
    expected_order = "|".join(reversed(initial_order.split("|")))
    down_button = (
        "[data-library-reorder='quiz'][data-library-reorder-direction='1']:not(:disabled)"
    )
    assert browser.evaluate(
        f"(() => {{ const button = document.querySelector({json.dumps(down_button)}); "
        "return button?.tagName === 'BUTTON' && button.type === 'button' && "
        "button.getAttribute('aria-label')?.includes('down within'); })()"
    ) is True
    browser.click(down_button)
    browser.wait_for("document.getElementById('libraryReorderStatus').textContent.includes('moved down')")
    assert browser.evaluate(order_expression) == expected_order

    browser.navigate(f"{browser_stack.base_url}/library")
    assert browser.wait_for(f"{order_expression} === {json.dumps(expected_order)}") is True


def test_library_empty_folder_lifecycle_persists_in_real_browser(browser_stack):
    browser = browser_stack.browser
    folder_name = "Browser Empty Folder"
    folder_lookup = (
        "[...document.querySelectorAll('.library-folder')]"
        f".find(folder => folder.dataset.folderName === {json.dumps(folder_name)})"
    )
    critical_html = browser_stack.metadata["critical_html"]

    browser.navigate(f"{browser_stack.base_url}/library")
    browser.click(".library-add-folder > button")
    assert browser.evaluate(
        f"(() => {{ const input = document.querySelector('.add-folder-form [name=folder]'); "
        f"input.value = {json.dumps(folder_name)}; return input.value; }})()"
    ) == folder_name
    browser.click(".add-folder-form button[type=submit]")
    browser.wait_for(
        f"({folder_lookup})?.querySelector('.library-folder-empty')?.textContent.trim() === "
        "'No quizzes in this view.'"
    )

    browser.navigate(f"{browser_stack.base_url}/library")
    browser.wait_for(f"Boolean({folder_lookup})")

    assert browser.evaluate(
        "(() => { const search = document.getElementById('librarySearch'); "
        "search.value = 'no browser quiz matches this'; "
        "search.dispatchEvent(new Event('input', {bubbles:true})); return true; })()"
    ) is True
    browser.wait_for(f"({folder_lookup})?.classList.contains('library-search-empty')")
    assert browser.evaluate(
        "(() => { const search = document.getElementById('librarySearch'); "
        "search.value = ''; search.dispatchEvent(new Event('input', {bubbles:true})); "
        "return true; })()"
    ) is True
    browser.wait_for(f"!({folder_lookup})?.classList.contains('library-search-empty')")

    assert browser.evaluate(
        f"(() => {{ const card = [...document.querySelectorAll('.library-quiz-card')]"
        f".find(card => card.dataset.id === {json.dumps(critical_html)}); "
        "const form = card.querySelector('.move-quiz-form'); "
        f"form.querySelector('[name=folder]').value = {json.dumps(folder_name)}; "
        "form.requestSubmit(); return true; })()"
    ) is True
    browser.wait_for(f"({folder_lookup})?.querySelectorAll('.library-quiz-card').length === 1")

    assert browser.evaluate(
        f"(() => {{ const folder = {folder_lookup}; "
        "const form = folder.querySelector('.move-quiz-form'); "
        "form.querySelector('[name=folder]').value = 'Browser Regression'; "
        "form.requestSubmit(); return true; })()"
    ) is True
    browser.wait_for(
        f"({folder_lookup})?.querySelector('.library-folder-empty')?.textContent.trim() === "
        "'No quizzes in this view.'"
    )

    assert browser.evaluate(
        f"(() => {{ const folder = {folder_lookup}; window.confirm = () => true; "
        "folder.querySelector(\"form[action='/delete_quiz_folder']\").requestSubmit(); "
        "return true; })()"
    ) is True
    browser.wait_for(f"!({folder_lookup})")


def test_navigation_visibility_persists_through_settings_and_page_reload(browser_stack):
    browser = browser_stack.browser
    keys = ("it", "law", "medical", "other")
    key_list = json.dumps(keys)

    browser.navigate(f"{browser_stack.base_url}/settings/navigation")
    browser.wait_for("document.querySelectorAll('[name^=study_area_]').length === 4")
    assert browser.evaluate(
        "[...document.querySelectorAll('.settings-toggle-row')].every(row => "
        "row.tagName === 'LABEL' && row.querySelector('input[type=checkbox]')) && "
        "document.querySelector('.settings-primary-button').type === 'submit'"
    ) is True
    assert browser.evaluate(
        "(() => { document.querySelectorAll('[name^=study_area_]').forEach(input => {"
        "input.checked = false; }); return true; })()"
    ) is True
    browser.click(".settings-primary-button")
    browser.wait_for(
        "location.pathname === '/settings/navigation' && "
        "new URLSearchParams(location.search).get('saved') === '1'"
    )
    assert browser.evaluate(
        "[...document.querySelectorAll('[name^=study_area_]')].every(input => !input.checked)"
    ) is True
    browser.wait_for(
        f"{key_list}.every(key => document.querySelector(`[data-nav-key=${{key}}]`)?.hidden)"
    )
    assert browser.evaluate(
        f"{key_list}.every(key => "
        "getComputedStyle(document.querySelector(`[data-nav-key=${key}]`)).display === 'none')"
    ) is True

    browser.navigate(f"{browser_stack.base_url}/library")
    browser.wait_for("document.querySelector('.dashboard-nav-normalized') !== null")
    browser.wait_for(
        f"{key_list}.every(key => document.querySelector(`[data-nav-key=${{key}}]`)?.hidden)"
    )
    assert browser.evaluate(
        f"{key_list}.every(key => "
        "getComputedStyle(document.querySelector(`[data-nav-key=${key}]`)).display === 'none') && "
        "getComputedStyle(document.querySelector('[data-nav-key=study]')).display !== 'none' && "
        "getComputedStyle(document.querySelector('[data-nav-key=settings]')).display !== 'none'"
    ) is True

    browser.navigate(f"{browser_stack.base_url}/library?navigation-reload=1")
    browser.wait_for(
        f"{key_list}.every(key => document.querySelector(`[data-nav-key=${{key}}]`)?.hidden)"
    )
    assert browser.evaluate(
        f"{key_list}.every(key => "
        "getComputedStyle(document.querySelector(`[data-nav-key=${key}]`)).display === 'none')"
    ) is True

    browser.navigate(f"{browser_stack.base_url}/settings/navigation")
    browser.wait_for("document.querySelector('[name=study_area_law]') !== null")
    browser.evaluate("document.querySelector('[name=study_area_law]').checked = true; true")
    browser.click(".settings-primary-button")
    browser.wait_for(
        "location.pathname === '/settings/navigation' && "
        "document.querySelector('[name=study_area_law]').checked"
    )
    browser.navigate(f"{browser_stack.base_url}/library?navigation-reenabled=1")
    browser.wait_for("document.querySelector('[data-nav-key=law]')?.hidden === false")
    assert browser.evaluate(
        "getComputedStyle(document.querySelector('[data-nav-key=law]')).display !== 'none' && "
        "['it','medical','other'].every(key => "
        "getComputedStyle(document.querySelector(`[data-nav-key=${key}]`)).display === 'none')"
    ) is True

    browser.navigate(f"{browser_stack.base_url}/settings/navigation")
    browser.wait_for("document.querySelectorAll('[name^=study_area_]').length === 4")
    browser.evaluate(
        "document.querySelectorAll('[name^=study_area_]').forEach(input => { input.checked = true; }); true"
    )
    browser.click(".settings-primary-button")
    browser.wait_for(
        "location.pathname === '/settings/navigation' && "
        "[...document.querySelectorAll('[name^=study_area_]')].every(input => input.checked)"
    )


def test_custom_anki_quiz_filter_bulk_and_accordion_state(browser_stack):
    browser = browser_stack.browser
    browser.navigate(f"{browser_stack.base_url}/anki/custom")
    browser.wait_for("document.querySelectorAll('.anki-custom-quiz-group').length === 2")

    group = (
        "title => [...document.querySelectorAll('.anki-custom-quiz-group')]"
        ".find(item => item.querySelector('.anki-custom-quiz-title')"
        ".textContent.includes(title))"
    )
    assert browser.evaluate(
        "[...document.querySelectorAll('.anki-custom-quiz-group')]"
        ".every(item => !item.open)"
    ) is True

    browser.click("#ankiExpandAllQuizzes")
    browser.wait_for(
        "[...document.querySelectorAll('.anki-custom-quiz-group')]"
        ".every(item => item.open)"
    )
    browser.click("#ankiCollapseAllQuizzes")
    browser.wait_for(
        "[...document.querySelectorAll('.anki-custom-quiz-group')]"
        ".every(item => !item.open)"
    )

    assert browser.evaluate(
        f"(() => {{ const item = ({group})('Browser Critical Workflow');"
        "item.open = true; const control = item.querySelector('[data-anki-quiz-select-all]');"
        "control.focus(); const accessible = control.tagName === 'BUTTON' && "
        "control.type === 'button' && document.activeElement === control;"
        "control.click(); return accessible; })()"
    ) is True
    browser.wait_for(
        f"({group})('Browser Critical Workflow')"
        ".querySelectorAll('[name=quiz_cards]:checked').length === 2"
    )
    assert browser.evaluate(
        f"(() => {{ const critical = ({group})('Browser Critical Workflow');"
        f"const companion = ({group})('Browser Companion'); return {{"
        "criticalSelected: critical.querySelectorAll('[name=quiz_cards]:checked').length,"
        "companionSelected: companion.querySelectorAll('[name=quiz_cards]:checked').length,"
        "criticalCount: critical.querySelector('[data-anki-quiz-selection-count]').textContent.trim(),"
        "globalCount: document.getElementById('ankiSelectedCount').textContent.trim()}; })()"
    ) == {
        "criticalSelected": 2,
        "companionSelected": 0,
        "criticalCount": "2 of 2 selected",
        "globalCount": "2 cards selected",
    }
    assert browser.evaluate(
        f"(() => {{ const item = ({group})('Browser Critical Workflow');"
        "item.querySelector('summary').click();"
        "return !item.open && item.querySelectorAll('[name=quiz_cards]:checked').length === 2; })()"
    ) is True

    assert browser.evaluate(
        "(() => { const filter = document.getElementById('ankiQuizFilter');"
        "filter.value = 'Companion'; filter.dispatchEvent(new Event('input', {bubbles:true}));"
        "return true; })()"
    ) is True
    filtered = browser.evaluate(
        f"(() => {{ const critical = ({group})('Browser Critical Workflow');"
        f"const companion = ({group})('Browser Companion'); return {{"
        "criticalHidden: critical.hidden,"
        "criticalSelected: critical.querySelectorAll('[name=quiz_cards]:checked').length,"
        "companionHidden: companion.hidden, companionOpen: companion.open,"
        "status: document.getElementById('ankiQuizFilterStatus').textContent.trim()}; })()"
    )
    assert filtered == {
        "criticalHidden": True,
        "criticalSelected": 2,
        "companionHidden": False,
        "companionOpen": False,
        "status": "1 of 2 quizzes shown",
    }

    browser.click("#ankiExpandAllQuizzes")
    assert browser.evaluate(
        f"(() => {{ const critical = ({group})('Browser Critical Workflow');"
        f"const companion = ({group})('Browser Companion');"
        "return !critical.open && companion.open; })()"
    ) is True
    assert browser.evaluate(
        "(() => { const filter = document.getElementById('ankiQuizFilter');"
        "filter.value = ''; filter.dispatchEvent(new Event('input', {bubbles:true})); return true; })()"
    ) is True
    assert browser.evaluate(
        f"(() => {{ const critical = ({group})('Browser Critical Workflow');"
        f"const companion = ({group})('Browser Companion'); return {{"
        "criticalHidden: critical.hidden, criticalOpen: critical.open,"
        "criticalSelected: critical.querySelectorAll('[name=quiz_cards]:checked').length,"
        "companionOpen: companion.open}; })()"
    ) == {
        "criticalHidden": False,
        "criticalOpen": False,
        "criticalSelected": 2,
        "companionOpen": True,
    }

    assert browser.evaluate(
        f"(() => {{ const companion = ({group})('Browser Companion');"
        "companion.querySelector('[name=quiz_cards]').click();"
        f"const critical = ({group})('Browser Critical Workflow');"
        "critical.querySelector('[data-anki-quiz-clear]').click(); return true; })()"
    ) is True
    assert browser.evaluate(
        f"(() => {{ const critical = ({group})('Browser Critical Workflow');"
        f"const companion = ({group})('Browser Companion'); return {{"
        "criticalSelected: critical.querySelectorAll('[name=quiz_cards]:checked').length,"
        "companionSelected: companion.querySelectorAll('[name=quiz_cards]:checked').length,"
        "criticalCount: critical.querySelector('[data-anki-quiz-selection-count]').textContent.trim(),"
        "companionCount: companion.querySelector('[data-anki-quiz-selection-count]').textContent.trim(),"
        "globalCount: document.getElementById('ankiSelectedCount').textContent.trim()}; })()"
    ) == {
        "criticalSelected": 0,
        "companionSelected": 1,
        "criticalCount": "0 of 2 selected",
        "companionCount": "1 of 1 selected",
        "globalCount": "1 card selected",
    }


def test_anki_submenu_consolidates_custom_and_printable_navigation(browser_stack):
    browser = browser_stack.browser
    browser.navigate(f"{browser_stack.base_url}/anki/custom#printableCards")
    browser.wait_for(
        "document.querySelector('.dashboard-nav-normalized .dashboard-nav-submenu') !== null && "
        "document.getElementById('printableCards') !== null"
    )

    submenu = browser.evaluate(
        "(() => { const group = document.querySelector('[data-nav-key=anki]').closest('.dashboard-nav-group');"
        "const links = [...group.querySelectorAll('.dashboard-nav-subitem')];"
        "const label = link => link.lastElementChild.textContent.trim(); return {"
        "labels:links.map(label),"
        "hrefs:links.map(link => new URL(link.href).pathname + new URL(link.href).hash),"
        "active:links.filter(link => link.classList.contains('active')).map(label),"
        "current:links.filter(link => link.getAttribute('aria-current') === 'page').map(label),"
        "hash:location.hash, targetPresent:Boolean(document.getElementById('printableCards')),"
        "targetVisible:(() => { const rect=document.getElementById('printableCards').getBoundingClientRect();"
        "return rect.top < innerHeight && rect.bottom > 0; })()}; })()"
    )
    assert submenu == {
        "labels": ["Custom Deck & Printable Cards", "Law Study Anki"],
        "hrefs": ["/anki/custom", "/anki/law"],
        "active": ["Custom Deck & Printable Cards"],
        "current": ["Custom Deck & Printable Cards"],
        "hash": "#printableCards",
        "targetPresent": True,
        "targetVisible": True,
    }

    browser.navigate(f"{browser_stack.base_url}/anki/law")
    browser.wait_for(
        "document.querySelector('.dashboard-nav-normalized .dashboard-nav-subitem.active') !== null"
    )
    assert browser.evaluate(
        "document.querySelector('.dashboard-nav-normalized .dashboard-nav-subitem.active').lastElementChild.textContent.trim()"
    ) == "Law Study Anki"


def test_custom_anki_non_quiz_bulk_selection_and_law_filter_state(browser_stack):
    browser = browser_stack.browser
    browser.navigate(f"{browser_stack.base_url}/anki/custom")
    browser.wait_for(
        "document.querySelectorAll('#ankiPerformanceGroup [name=missed_cards]').length === 2 && "
        "document.querySelectorAll('.anki-custom-law-group').length === 2"
    )
    law_group = (
        "title => [...document.querySelectorAll('.anki-custom-law-group')]"
        ".find(item => item.querySelector('.anki-custom-law-title').textContent.includes(title))"
    )

    assert browser.evaluate(
        "(() => { const performance = document.getElementById('ankiPerformanceGroup');"
        "const control = performance.querySelector('[data-anki-group-select-all]');"
        "control.focus(); const accessible = control.tagName === 'BUTTON' && "
        "control.type === 'button' && document.activeElement === control;"
        "control.click(); return accessible; })()"
    ) is True
    assert browser.evaluate(
        "(() => { const performance = document.getElementById('ankiPerformanceGroup'); return {"
        "missed: performance.querySelectorAll('[name=missed_cards]:checked').length,"
        "quiz: document.querySelectorAll('[name=quiz_cards]:checked').length,"
        "law: document.querySelectorAll('[name=law_cards]:checked').length,"
        "count: document.getElementById('ankiPerformanceSelectionCount').textContent.trim(),"
        "globalCount: document.getElementById('ankiSelectedCount').textContent.trim()}; })()"
    ) == {
        "missed": 2,
        "quiz": 0,
        "law": 0,
        "count": "2 of 2 selected",
        "globalCount": "2 cards selected",
    }
    assert browser.evaluate(
        "(() => { const performance = document.getElementById('ankiPerformanceGroup');"
        "performance.querySelector('summary').click(); return !performance.open && "
        "performance.querySelectorAll('[name=missed_cards]:checked').length === 2; })()"
    ) is True

    browser.evaluate(
        "(() => { const filter = document.getElementById('ankiLawFilter');"
        "filter.value = 'Palsgraf'; filter.dispatchEvent(new Event('input', {bubbles:true}));"
        "return true; })()"
    )
    assert browser.evaluate(
        f"(() => {{ const palsgraf = ({law_group})('Palsgraf');"
        f"const hadley = ({law_group})('Hadley'); return {{"
        "palsgrafHidden: palsgraf.hidden, palsgrafOpen: palsgraf.open,"
        "hadleyHidden: hadley.hidden, hadleyOpen: hadley.open,"
        "status: document.getElementById('ankiLawFilterStatus').textContent.trim()}; })()"
    ) == {
        "palsgrafHidden": False,
        "palsgrafOpen": False,
        "hadleyHidden": True,
        "hadleyOpen": False,
        "status": "1 of 2 cases shown",
    }
    browser.click("#ankiExpandAllLawCases")
    assert browser.evaluate(
        f"({law_group})('Palsgraf').open && !({law_group})('Hadley').open"
    ) is True
    assert browser.evaluate(
        f"(() => {{ const group = ({law_group})('Palsgraf');"
        "group.querySelector('[data-anki-group-select-all]').click();"
        "return group.querySelectorAll('[name=law_cards]:checked').length; })()"
    ) == 2

    browser.evaluate(
        "(() => { const filter = document.getElementById('ankiLawFilter');"
        "filter.value = ''; filter.dispatchEvent(new Event('input', {bubbles:true})); return true; })()"
    )
    assert browser.evaluate(
        f"(() => {{ const hadley = ({law_group})('Hadley'); hadley.open = true;"
        "hadley.querySelector('[data-anki-group-select-all]').click();"
        f"const palsgraf = ({law_group})('Palsgraf');"
        "palsgraf.querySelector('[data-anki-group-clear]').click(); return {"
        "palsgraf: palsgraf.querySelectorAll('[name=law_cards]:checked').length,"
        "hadley: hadley.querySelectorAll('[name=law_cards]:checked').length,"
        "missed: document.querySelectorAll('[name=missed_cards]:checked').length,"
        "quiz: document.querySelectorAll('[name=quiz_cards]:checked').length,"
        "palsgrafCount: palsgraf.querySelector('[data-anki-group-selection-count]').textContent.trim(),"
        "hadleyCount: hadley.querySelector('[data-anki-group-selection-count]').textContent.trim(),"
        "globalCount: document.getElementById('ankiSelectedCount').textContent.trim()}; })()"
    ) == {
        "palsgraf": 0,
        "hadley": 1,
        "missed": 2,
        "quiz": 0,
        "palsgrafCount": "0 of 2 selected",
        "hadleyCount": "1 of 1 selected",
        "globalCount": "3 cards selected",
    }

    browser.evaluate(
        "document.querySelector('#ankiPerformanceGroup [data-anki-group-clear]').click(); true"
    )
    browser.click("#ankiCollapseAllLawCases")
    assert browser.evaluate(
        f"(() => {{ const hadley = ({law_group})('Hadley'); return !hadley.open && "
        "hadley.querySelectorAll('[name=law_cards]:checked').length === 1 && "
        "document.querySelectorAll('[name=missed_cards]:checked').length === 0 && "
        "document.getElementById('ankiPerformanceSelectionCount').textContent.trim() === "
        "'0 of 2 selected' && "
        "document.getElementById('ankiSelectedCount').textContent.trim() === '1 card selected'; })()"
    ) is True


def test_custom_anki_performance_accordion_state_persists(browser_stack):
    browser = browser_stack.browser
    storage_key = "dlms.anki.custom.performanceHistory.openState.v1"

    try:
        browser.navigate(f"{browser_stack.base_url}/anki/custom")
        browser.evaluate(f"localStorage.removeItem({json.dumps(storage_key)}); true")
        browser.navigate(f"{browser_stack.base_url}/anki/custom?first-visit=1")
        browser.wait_for("document.getElementById('ankiPerformanceGroup') !== null")

        assert browser.evaluate(
            "(() => { const group = document.getElementById('ankiPerformanceGroup');"
            "const summary = group.querySelector('summary'); summary.focus(); return {"
            "open:group.open, nativeDetails:group.tagName === 'DETAILS',"
            "nativeSummary:summary.tagName === 'SUMMARY', focused:document.activeElement === summary}; })()"
        ) == {
            "open": True,
            "nativeDetails": True,
            "nativeSummary": True,
            "focused": True,
        }

        browser.evaluate(
            "(() => { const performance = document.getElementById('ankiPerformanceGroup');"
            "const quiz = document.querySelector('.anki-custom-quiz-group');"
            "const law = document.querySelector('.anki-custom-law-group');"
            "performance.querySelector('[name=missed_cards]').click();"
            "quiz.open = true; law.open = true; performance.querySelector('summary').click();"
            "return true; })()"
        )
        browser.wait_for("document.getElementById('ankiPerformanceGroup').open === false")
        state_after_collapse = browser.evaluate(
            "(() => { const performance = document.getElementById('ankiPerformanceGroup');"
            "const quiz = document.querySelector('.anki-custom-quiz-group');"
            "const law = document.querySelector('.anki-custom-law-group'); return {"
            "open:performance.open, missed:performance.querySelectorAll('[name=missed_cards]:checked').length,"
            "quizOpen:quiz.open, lawOpen:law.open}; })()"
        )
        assert state_after_collapse == {
            "open": False,
            "missed": 1,
            "quizOpen": True,
            "lawOpen": True,
        }
        browser.wait_for(
            f"localStorage.getItem({json.dumps(storage_key)}) === 'false'"
        )

        browser.navigate(f"{browser_stack.base_url}/anki/custom?collapsed-reload=1")
        browser.wait_for("document.getElementById('ankiPerformanceGroup') !== null")
        assert browser.evaluate(
            "(() => ({open:document.getElementById('ankiPerformanceGroup').open,"
            "selected:document.querySelectorAll('[name=missed_cards]:checked').length}))()"
        ) == {"open": False, "selected": 0}

        browser.evaluate(
            "document.querySelector('#ankiPerformanceGroup summary').click(); true"
        )
        browser.wait_for(
            f"localStorage.getItem({json.dumps(storage_key)}) === 'true'"
        )
        browser.navigate(f"{browser_stack.base_url}/anki/custom?expanded-reload=1")
        browser.wait_for("document.getElementById('ankiPerformanceGroup')?.open === true")

        browser.navigate(f"{browser_stack.base_url}/anki")
        browser.navigate(f"{browser_stack.base_url}/anki/custom?return-visit=1")
        browser.wait_for("document.getElementById('ankiPerformanceGroup')?.open === true")

        browser.evaluate(
            f"localStorage.setItem({json.dumps(storage_key)}, '{{malformed'); true"
        )
        browser.navigate(f"{browser_stack.base_url}/anki/custom?malformed-state=1")
        browser.wait_for("document.getElementById('ankiPerformanceGroup') !== null")
        assert browser.evaluate(
            "document.getElementById('ankiPerformanceGroup').open"
        ) is True

        browser.evaluate(
            f"localStorage.setItem({json.dumps(storage_key)}, JSON.stringify({{open:false}})); true"
        )
        browser.navigate(f"{browser_stack.base_url}/anki/custom?stale-state=1")
        browser.wait_for("document.getElementById('ankiPerformanceGroup') !== null")
        assert browser.evaluate(
            "document.getElementById('ankiPerformanceGroup').open"
        ) is True
    finally:
        browser.evaluate(f"localStorage.removeItem({json.dumps(storage_key)}); true")


def test_study_feedback_exam_save_and_history_navigation(browser_stack):
    browser = browser_stack.browser
    attempts_before = _database_value(
        browser_stack.data_root / "results.db",
        "SELECT COUNT(*) FROM attempts",
    )
    quiz_url = f"{browser_stack.base_url}/quizzes/{browser_stack.metadata['critical_html']}"
    browser.navigate(quiz_url)
    browser.wait_for("typeof quiz !== 'undefined' && quiz.length === 2")

    browser.click(".study-mode-btn")
    browser.wait_for("document.querySelectorAll('#choices .choice').length === 2")
    browser.click("#choices .choice[data-index='1']")
    browser.wait_for("document.querySelector('#choices .wrong-choice') !== null")
    assert "Not quite" in browser.evaluate("document.querySelector('.choice-study-explanation').textContent")
    _wait_for_database_value(
        browser_stack.data_root / "results.db",
        "SELECT COUNT(*) FROM learning_events WHERE event_type = 'study_answer'",
        1,
    )

    browser.navigate(quiz_url)
    browser.wait_for("typeof quiz !== 'undefined' && quiz.length === 2")
    browser.click(".exam-mode-btn")
    browser.wait_for("document.querySelectorAll('#choices .choice').length === 2")
    browser.click("#choices .choice[data-index='0']")
    browser.click("#nextBtn")
    browser.wait_for("document.getElementById('qText').textContent.includes('two')")
    browser.click("#choices .choice[data-index='1']")
    browser.evaluate("window.confirm = () => true; true")
    browser.click("#submitBtn")
    browser.wait_for("document.getElementById('result').textContent.includes('saved successfully')")
    assert "Score: 2 / 2 (100%)" in browser.evaluate("document.getElementById('result').textContent")
    _wait_for_database_value(
        browser_stack.data_root / "results.db",
        "SELECT COUNT(*) FROM attempts",
        attempts_before + 1,
    )

    browser.click("#result button[onclick*='/history']")
    browser.wait_for("location.pathname === '/history'")
    browser.wait_for("document.body.textContent.includes('Browser Critical Workflow')")


def test_quiz_edit_persists_to_editor_and_generated_quiz(browser_stack):
    browser = browser_stack.browser
    quiz_id = browser_stack.metadata["critical_id"]
    edited_title = "Browser Edited Workflow"
    edited_question = "Browser edited question one?"

    browser.navigate(f"{browser_stack.base_url}/edit_quiz/{quiz_id}")
    browser.wait_for("document.querySelectorAll('.question-text').length === 2")
    assert browser.evaluate(
        f"(() => {{ document.querySelector('[name=quiz_title]').value = {json.dumps(edited_title)}; "
        f"document.querySelector('.question-text').value = {json.dumps(edited_question)}; "
        "return true; })()"
    ) is True
    browser.click("#edit-quiz-form .build-primary-button")
    browser.wait_for(
        f"location.pathname === '/edit_quiz/{quiz_id}' && "
        f"document.querySelector('[name=quiz_title]').value === {json.dumps(edited_title)}"
    )
    assert browser.evaluate("document.querySelector('.question-text').value") == edited_question

    browser.navigate(
        f"{browser_stack.base_url}/quizzes/{browser_stack.metadata['critical_html']}?edited=1"
    )
    browser.wait_for("typeof quiz !== 'undefined' && quiz.length === 2")
    assert browser.evaluate("document.title.includes('Browser Edited Workflow')") is True
    assert browser.evaluate("quiz[0].question") == edited_question


def test_study_and_exam_quiz_shell_follow_each_theme(browser_stack):
    browser = browser_stack.browser
    quiz_url = f"{browser_stack.base_url}/quizzes/{browser_stack.metadata['critical_html']}"

    for theme in ("dark", "light", "purple-gold", "maroon-gold"):
        browser.navigate(f"{browser_stack.base_url}/settings")
        browser.wait_for("window.dlmsCsrfToken")
        status = browser.evaluate(
            f"fetch('/api/theme', {{method:'POST', headers:{{'Content-Type':'application/json'}}, "
            f"body:JSON.stringify({{theme:{json.dumps(theme)}}})}}).then(response => response.status)"
        )
        assert status == 200

        for mode_selector in (".study-mode-btn", ".exam-mode-btn"):
            browser.navigate(f"{quiz_url}?theme={theme}&mode={mode_selector[1:]}")
            browser.wait_for("typeof quiz !== 'undefined' && quiz.length === 2")
            pre_quiz = browser.evaluate(
                "(() => {"
                "const bounds = selector => { const rect = document.querySelector(selector).getBoundingClientRect();"
                "return {left:rect.left,right:rect.right}; };"
                "const probe = document.createElement('span');"
                "probe.style.color = 'light-dark(var(--theme-panel-1), var(--theme-heading))';"
                "document.body.appendChild(probe); const shellText = getComputedStyle(probe).color;"
                "probe.remove();"
                "return {hero:bounds('#quizWrapper > .container > .hero-title'),"
                "modeCard:bounds('#modeSelect'), mode:bounds('.mode-banner'),"
                "returns:bounds('.quiz-return-buttons'),"
                "heroColor:getComputedStyle(document.querySelector('#quizWrapper > .container > .hero-title')).color,"
                "shellText}; })()"
            )
            assert abs(pre_quiz["modeCard"]["left"] - pre_quiz["hero"]["left"]) < 1
            assert abs(pre_quiz["modeCard"]["right"] - pre_quiz["hero"]["right"]) < 1
            assert abs(pre_quiz["modeCard"]["left"] - pre_quiz["returns"]["left"]) < 1
            assert abs(pre_quiz["modeCard"]["right"] - pre_quiz["returns"]["right"]) < 1
            assert pre_quiz["mode"]["left"] >= pre_quiz["modeCard"]["left"]
            assert pre_quiz["mode"]["right"] <= pre_quiz["modeCard"]["right"]
            assert pre_quiz["heroColor"] == pre_quiz["shellText"]

            browser.click(mode_selector)
            browser.wait_for("!document.getElementById('quiz').classList.contains('hidden')")
            shell = browser.evaluate(
                "(() => {"
                "const resolve = name => { const probe = document.createElement('span');"
                "probe.style.color = `var(${name})`; document.body.appendChild(probe);"
                "const result = getComputedStyle(probe).color; probe.remove(); return result; };"
                "const header = getComputedStyle(document.querySelector('.active-quiz-logo-banner'));"
                "const question = getComputedStyle(document.querySelector('.quiz-question-card'));"
                "const returns = getComputedStyle(document.querySelector('.quiz-return-buttons'));"
                "const link = document.getElementById('returnPortalBtn');"
                "const linkStyle = getComputedStyle(link);"
                "const titleStyle = getComputedStyle(document.querySelector('.active-quiz-title'));"
                "const shellProbe = document.createElement('span');"
                "shellProbe.style.color = 'light-dark(var(--theme-panel-1), var(--theme-heading))';"
                "document.body.appendChild(shellProbe); const shellText = getComputedStyle(shellProbe).color;"
                "shellProbe.remove();"
                "return {header:header.backgroundImage, question:question.backgroundImage,"
                "returns:returns.backgroundImage, linkBackground:linkStyle.backgroundColor,"
                "linkColor:linkStyle.color, titleColor:titleStyle.color, shellText,"
                "pageText:resolve('--theme-page-text')}; })()"
            )
            assert shell["header"] != "none"
            assert shell["header"] != shell["question"]
            assert shell["returns"] != "none"
            assert shell["returns"] != shell["question"]
            assert shell["linkBackground"] != "rgba(0, 0, 0, 0)"
            assert shell["linkColor"] == shell["pageText"]
            assert shell["titleColor"] == shell["shellText"]


def test_anki_summary_cards_across_themes_and_widths(browser_stack):
    browser = browser_stack.browser
    browser.navigate(f"{browser_stack.base_url}/anki/custom")
    browser.wait_for("document.querySelectorAll('[name=law_cards]').length === 3")
    custom_law_count = browser.evaluate(
        "document.querySelectorAll('[name=law_cards]').length"
    )

    for theme in ("dark", "light", "purple-gold", "maroon-gold"):
        browser.navigate(f"{browser_stack.base_url}/settings")
        browser.wait_for("window.dlmsCsrfToken")
        status = browser.evaluate(
            f"fetch('/api/theme', {{method:'POST', headers:{{'Content-Type':'application/json'}}, "
            f"body:JSON.stringify({{theme:{json.dumps(theme)}}})}}).then(response => response.status)"
        )
        assert status == 200

        for width in (1280, 640):
            browser.set_viewport(width, 900)
            browser.navigate(f"{browser_stack.base_url}/anki?theme={theme}&width={width}")
            browser.wait_for("document.querySelector('.anki-missed-summary-card') !== null")
            summary = browser.evaluate(
                "(() => {"
                "const card = document.querySelector('.anki-missed-summary-card');"
                "const cards = [...document.querySelectorAll('.anki-tools-summary .anki-summary-card')];"
                "const items = [...card.querySelectorAll('.anki-missed-summary-metrics li')];"
                "const resolve = name => { const probe = document.createElement('span');"
                "probe.style.color = `var(${name})`; document.body.appendChild(probe);"
                "const result = getComputedStyle(probe).color; probe.remove(); return result; };"
                "return {text:card.textContent.replace(/\\s+/g,' ').trim(),"
                "itemCount:items.length, associated:items.every(item => "
                "Boolean(item.querySelector('strong') && item.querySelector('span'))),"
                "overflow:card.scrollWidth > card.clientWidth,"
                "cardHeight:card.getBoundingClientRect().height,"
                "summaryHeights:cards.map(item => item.getBoundingClientRect().height),"
                "cardOverflows:cards.map(item => item.scrollWidth > item.clientWidth),"
                "primaryDisplays:cards.map(item => getComputedStyle(item.querySelector('.anki-summary-primary')).display),"
                "labels:cards.map(item => item.querySelector('.anki-summary-primary span').textContent.trim()),"
                "lawCount:cards[2].querySelector('strong').textContent.trim(),"
                "labelTransforms:cards.map(item => getComputedStyle(item.querySelector('.anki-summary-primary')).textTransform),"
                "supportSingleLines:cards.filter(item => item.querySelector('.anki-summary-support')).every(item => {"
                "const range=document.createRange(); range.selectNodeContents(item.querySelector('.anki-summary-support'));"
                "return range.getClientRects().length === 1; }),"
                "metricDisplay:getComputedStyle(card.querySelector('.anki-missed-summary-metrics')).display,"
                "metricRows:items.map(item => getComputedStyle(item).gridTemplateColumns),"
                "totalColor:getComputedStyle(card.querySelector('.anki-missed-summary-total strong')).color,"
                "metricColors:items.map(item => getComputedStyle(item.querySelector('strong')).color),"
                "heading:resolve('--theme-heading')}; })()"
            )
            assert "Questions Ever Missed:" in summary["text"]
            assert "not yet revisited" in summary["text"]
            assert "revisited later" in summary["text"]
            assert "missed more than once" in summary["text"]
            assert "Repeat count overlaps revisit status." in summary["text"]
            assert summary["itemCount"] == 3
            assert summary["labels"] == ["Quizzes", "Questions Ever Missed:", "Law Flashcards"]
            assert summary["lawCount"] == str(custom_law_count) == "3"
            assert summary["associated"] is True
            assert summary["overflow"] is False
            assert not any(summary["cardOverflows"])
            assert all(display == "grid" for display in summary["primaryDisplays"])
            assert all(transform == "uppercase" for transform in summary["labelTransforms"])
            assert summary["supportSingleLines"] is True
            assert summary["cardHeight"] < 190
            if width == 1280:
                assert max(summary["summaryHeights"]) - min(summary["summaryHeights"]) < 1
            assert summary["metricDisplay"] == "grid"
            assert all(row != "none" for row in summary["metricRows"])
            assert summary["totalColor"] == summary["heading"]
            assert all(color == summary["heading"] for color in summary["metricColors"])


def test_study_learning_save_failure_is_visible_and_retry_persists(browser_stack):
    browser = browser_stack.browser
    database = browser_stack.data_root / "results.db"
    before = _database_value(
        database,
        "SELECT COUNT(*) FROM learning_events WHERE event_type = 'study_answer'",
    )
    quiz_url = f"{browser_stack.base_url}/quizzes/{browser_stack.metadata['critical_html']}"
    browser.navigate(quiz_url)
    browser.wait_for("typeof quiz !== 'undefined' && quiz.length === 2")
    assert browser.evaluate(
        "(() => { const originalFetch = window.fetch.bind(window); let failStudySave = true; "
        "window.fetch = (...args) => { const target = String(args[0]); "
        "if (failStudySave && target.includes('/api/learning-events/study-response')) { "
        "failStudySave = false; return Promise.resolve(new Response("
        "JSON.stringify({error: 'forced browser regression failure'}), "
        "{status: 503, headers: {'Content-Type': 'application/json'}})); } "
        "return originalFetch(...args); }; return true; })()"
    ) is True

    browser.click(".study-mode-btn")
    browser.wait_for("document.querySelectorAll('#choices .choice').length === 2")
    browser.click("#choices .choice[data-index='0']")
    browser.wait_for(
        "!document.getElementById('studyLearningEventStatus').hidden && "
        "document.querySelector('.study-learning-save-message').textContent.includes('not saved')"
    )
    assert _database_value(
        database,
        "SELECT COUNT(*) FROM learning_events WHERE event_type = 'study_answer'",
    ) == before

    browser.click(".study-learning-save-retry")
    browser.wait_for("document.getElementById('studyLearningEventStatus').hidden")
    _wait_for_database_value(
        database,
        "SELECT COUNT(*) FROM learning_events WHERE event_type = 'study_answer'",
        before + 1,
    )


def test_restore_confirmation_and_success_replace_live_quiz_state(browser_stack):
    browser = browser_stack.browser
    quiz_id = browser_stack.metadata["critical_id"]
    original_title = "Browser Critical Workflow"
    changed_title = "Browser Restore Mutation"
    original_question = "Browser question one?"
    changed_question = "Browser restore mutation question?"
    database = browser_stack.data_root / "results.db"

    browser.navigate(f"{browser_stack.base_url}/edit_quiz/{quiz_id}")
    browser.wait_for("document.querySelector('[name=quiz_title]') !== null")
    browser.evaluate(
        f"(() => {{ document.querySelector('[name=quiz_title]').value = {json.dumps(changed_title)}; "
        f"document.querySelector('.question-text').value = {json.dumps(changed_question)}; "
        "return true; })()"
    )
    browser.click("#edit-quiz-form .build-primary-button")
    _wait_for_database_value(
        database,
        "SELECT title FROM quizzes WHERE id = %d" % quiz_id,
        changed_title,
    )
    assert _database_value(
        database,
        "SELECT question_text FROM questions WHERE quiz_id = ? ORDER BY question_number LIMIT 1",
        (quiz_id,),
    ) == changed_question

    browser.navigate(f"{browser_stack.base_url}/settings/backup")
    browser.wait_for("document.getElementById('backupFile') !== null")
    browser.set_files("#backupFile", [browser_stack.metadata["restore_path"]])
    browser.click("form[action='/settings/backup/restore/stage'] button[type='submit']")
    browser.wait_for("document.querySelector('h1')?.textContent.includes('Review backup before restore')")
    assert _database_value(
        database,
        "SELECT title FROM quizzes WHERE id = ?",
        (quiz_id,),
    ) == changed_title
    assert _database_value(
        database,
        "SELECT question_text FROM questions WHERE quiz_id = ? ORDER BY question_number LIMIT 1",
        (quiz_id,),
    ) == changed_question
    assert browser.evaluate(
        "document.body.textContent.includes('2 quizzes') && "
        "document.body.textContent.includes('Nothing has been restored yet')"
    ) is True

    browser.click("form[action*='/restore/confirm/'] button[type='submit']")
    browser.wait_for("document.querySelector('h1')?.textContent.includes('Restore complete')", timeout=12.0)
    _wait_for_database_value(
        database,
        "SELECT title FROM quizzes WHERE id = %d" % quiz_id,
        original_title,
    )
    assert _database_value(
        database,
        "SELECT question_text FROM questions WHERE quiz_id = ? ORDER BY question_number LIMIT 1",
        (quiz_id,),
    ) == original_question
    browser.navigate(
        f"{browser_stack.base_url}/quizzes/{browser_stack.metadata['critical_html']}?restored=1"
    )
    browser.wait_for("typeof quiz !== 'undefined' && quiz.length === 2")
    assert browser.evaluate("document.title") == original_title
    assert browser.evaluate("quiz[0].question") == original_question


def test_settings_hub_interaction_states_follow_each_theme(browser_stack):
    browser = browser_stack.browser
    selector = ".settings-hub-card[href='/settings/ai']"
    encoded_selector = json.dumps(selector)

    def move_pointer(x, y, button_down=False):
        actions = [{
            "type": "pointerMove", "x": round(x), "y": round(y),
            "duration": 0, "origin": "viewport",
        }]
        if button_down:
            actions.append({"type": "pointerDown", "button": 0})
        browser.command("input.performActions", {
            "context": browser.context,
            "actions": [{
                "type": "pointer", "id": "settings-hover-mouse",
                "parameters": {"pointerType": "mouse"}, "actions": actions,
            }],
        })

    def snapshot():
        return browser.evaluate(
            "(() => {"
            f"const card = document.querySelector({encoded_selector});"
            "const resolve = name => { const probe = document.createElement('span');"
            "probe.style.color = `var(${name})`; document.body.appendChild(probe);"
            "const result = getComputedStyle(probe).color; probe.remove(); return result; };"
            "const style = getComputedStyle(card);"
            "return {"
            "background: style.backgroundImage, color: style.color,"
            "heading: getComputedStyle(card.querySelector('h2')).color,"
            "description: getComputedStyle(card.querySelector('p')).color,"
            "kicker: getComputedStyle(card.querySelector('.settings-card-kicker')).color,"
            "icon: getComputedStyle(card.querySelector('.settings-hub-icon')).color,"
            "arrow: getComputedStyle(card.querySelector('.settings-hub-arrow')).color,"
            "transform: style.transform,"
            "pageText: resolve('--theme-page-text'), muted: resolve('--theme-muted-text'),"
            "headingToken: resolve('--theme-heading'), accentText: resolve('--theme-accent-text'),"
            "}; })()"
        )

    for theme in ("dark", "light", "purple-gold", "maroon-gold"):
        browser.navigate(f"{browser_stack.base_url}/settings")
        browser.wait_for("window.dlmsCsrfToken && document.getElementById('dlmsQuickTheme')")
        status = browser.evaluate(
            f"fetch('/api/theme', {{method:'POST', headers:{{'Content-Type':'application/json'}}, "
            f"body:JSON.stringify({{theme:{json.dumps(theme)}}})}}).then(response => response.status)"
        )
        assert status == 200
        browser.navigate(f"{browser_stack.base_url}/settings?theme={theme}")
        browser.wait_for(f"document.querySelector({encoded_selector}) !== null")
        browser.set_viewport(1280, 900)
        hero = browser.evaluate(
            "(() => { const header = document.querySelector('.settings-page-header');"
            "const accent = getComputedStyle(header, '::after');"
            "return { background: accent.backgroundImage, pointerEvents: accent.pointerEvents,"
            "contentZIndex: getComputedStyle(header.querySelector(':scope > *')).zIndex }; })()"
        )
        assert hero["background"] != "none"
        assert hero["pointerEvents"] == "none"
        assert hero["contentZIndex"] == "1"
        move_pointer(1, 1)
        normal = snapshot()

        coordinates = json.loads(browser.evaluate(
            f"(() => {{ const rect = document.querySelector({encoded_selector}).getBoundingClientRect();"
            "return JSON.stringify({x:rect.left+rect.width/2,y:rect.top+rect.height/2}); })()"
        ))
        move_pointer(coordinates["x"], coordinates["y"])
        browser.wait_for(f"document.querySelector({encoded_selector}).matches(':hover')")
        hovered = snapshot()
        assert hovered["background"] != normal["background"]
        assert "rgb(8, 25, 54)" not in hovered["background"]
        assert hovered["color"] == hovered["pageText"]
        assert hovered["heading"] == hovered["headingToken"]
        assert hovered["description"] == hovered["muted"]
        assert hovered["kicker"] == hovered["accentText"]
        assert hovered["icon"] == normal["icon"]
        assert hovered["arrow"] == hovered["accentText"]
        assert hovered["transform"] != "none"

        move_pointer(coordinates["x"], coordinates["y"], button_down=True)
        browser.wait_for(f"document.querySelector({encoded_selector}).matches(':active')")
        pressed = snapshot()
        try:
            assert pressed["background"] != hovered["background"]
            assert pressed["color"] == pressed["pageText"]
            assert pressed["description"] == pressed["muted"]
            assert pressed["icon"] == normal["icon"]
        finally:
            browser.command("input.releaseActions", {"context": browser.context})
