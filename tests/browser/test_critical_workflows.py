"""Opt-in browser regressions for DLMS's highest-risk client/server seams."""

from __future__ import annotations

import base64
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


def test_fresh_profile_defaults_to_purple_gold_and_theme_selection_persists(browser_stack, tmp_path):
    browser = browser_stack.browser
    base_url = browser_stack.base_url
    portal_path = browser_stack.data_root / "config" / "portal.json"
    browser.set_viewport(1400, 1500)

    assert json.loads(portal_path.read_text(encoding="utf-8"))["theme"] == "purple-gold"

    browser.navigate(f"{base_url}/")
    browser.wait_for(
        "document.getElementById('dlmsQuickTheme') && "
        "!document.querySelector('.dashboard-theme-quick').hidden"
    )
    initial = browser.evaluate(
        "(() => { const root = getComputedStyle(document.documentElement);"
        "const select = document.getElementById('dlmsQuickTheme');"
        "return {selection:select.value,accent:root.getPropertyValue('--theme-accent').trim(),"
        "scheme:root.getPropertyValue('--theme-color-scheme').trim()}; })()"
    )
    assert initial == {"selection": "purple-gold", "accent": "#f2c230", "scheme": "dark"}

    screenshot = browser.command(
        "browsingContext.captureScreenshot",
        {"context": browser.context, "origin": "viewport"},
    )
    screenshot_path = tmp_path / "fresh-default-purple-gold.png"
    screenshot_path.write_bytes(base64.b64decode(screenshot["data"]))
    assert screenshot_path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")

    assert browser.evaluate(
        "(() => { const select = document.getElementById('dlmsQuickTheme');"
        "select.value = 'light'; select.dispatchEvent(new Event('change', {bubbles:true}));"
        "return true; })()"
    ) is True
    browser.wait_for(
        "document.getElementById('dlmsQuickTheme')?.value === 'light' && "
        "!document.getElementById('dlmsQuickTheme').disabled && "
        "!document.querySelector('.dashboard-theme-quick').hidden"
    )
    assert json.loads(portal_path.read_text(encoding="utf-8"))["theme"] == "light"

    browser.navigate(f"{base_url}/library")
    browser.wait_for(
        "document.getElementById('dlmsQuickTheme')?.value === 'light' && "
        "!document.querySelector('.dashboard-theme-quick').hidden"
    )
    assert browser.evaluate(
        "getComputedStyle(document.documentElement).getPropertyValue('--theme-color-scheme').trim()"
    ) == "light"

    assert browser.evaluate(
        "(() => { const select = document.getElementById('dlmsQuickTheme');"
        "select.value = 'purple-gold'; select.dispatchEvent(new Event('change', {bubbles:true}));"
        "return true; })()"
    ) is True
    browser.wait_for(
        "document.getElementById('dlmsQuickTheme')?.value === 'purple-gold' && "
        "!document.getElementById('dlmsQuickTheme').disabled && "
        "!document.querySelector('.dashboard-theme-quick').hidden"
    )


def test_dashboard_destructive_and_success_colors_resolve_across_themes(browser_stack):
    browser = browser_stack.browser
    browser.set_viewport(1400, 1000)
    expected = {
        "light": {
            "normal": "rgb(143, 36, 53)",
            "normal_background": "rgb(248, 231, 234)",
            "hover": "rgb(118, 27, 44)",
            "hover_background": "rgb(241, 210, 216)",
            "active": "rgb(104, 21, 35)",
            "active_background": "rgb(231, 188, 196)",
            "disabled": "rgb(118, 99, 106)",
            "disabled_background": "rgb(236, 231, 232)",
            "heading": "rgb(22, 120, 79)",
            "status": "rgb(16, 95, 61)",
            "status_background": "rgb(211, 234, 223)",
            "score": "rgb(18, 97, 63)",
            "score_background": "rgb(213, 234, 223)",
        },
        "dark": {
            "normal": "rgb(255, 98, 98)",
            "normal_background": "rgba(86, 15, 22, 0.32)",
            "hover": "rgb(255, 255, 255)",
            "hover_background": "rgba(172, 28, 39, 0.68)",
            "active": "rgb(255, 255, 255)",
            "active_background": "rgba(172, 28, 39, 0.68)",
            "disabled": "rgb(188, 160, 165)",
            "disabled_background": "rgba(64, 27, 34, 0.42)",
            "heading": "rgb(85, 228, 143)",
            "status": "rgb(78, 217, 138)",
            "status_background": "rgba(15, 98, 55, 0.22)",
            "score": "rgb(90, 240, 141)",
            "score_background": "rgba(18, 112, 56, 0.2)",
        },
        "purple-gold": {},
        "maroon-gold": {},
    }

    def set_theme(theme):
        browser.navigate(f"{browser_stack.base_url}/settings")
        browser.wait_for("window.dlmsCsrfToken")
        status = browser.evaluate(
            f"fetch('/api/theme', {{method:'POST', headers:{{'Content-Type':'application/json'}}, "
            f"body:JSON.stringify({{theme:{json.dumps(theme)}}})}}).then(response => response.status)"
        )
        assert status == 200
        browser.navigate(f"{browser_stack.base_url}/")
        browser.wait_for("document.querySelector('.dashboard-shutdown') !== null")
        assert browser.evaluate(
            "(() => {"
            "const source = document.querySelector('.dashboard-shutdown');"
            "const probe = source.cloneNode(true); probe.id = 'shutdownStyleProbe';"
            "probe.style.cssText = 'position:fixed;left:20px;top:20px;width:260px;z-index:9999';"
            "document.body.appendChild(probe);"
            "const states = document.createElement('div'); states.id = 'activityStyleProbe';"
            "states.innerHTML = "
            "'<span id=\"activityHeadingProbe\" class=\"dashboard-heading-icon\">⌁</span>' +"
            "'<div id=\"activityStatusProbe\" class=\"dashboard-activity-status\">✓</div>' +"
            "'<span id=\"activityScoreProbe\" class=\"dashboard-score score-good\">90%</span>';"
            "document.querySelector('.dashboard-activity-panel').appendChild(states);"
            "return true; })()"
        ) is True

    def snapshot():
        return browser.evaluate(
            "(() => {"
            "const probe = document.getElementById('shutdownStyleProbe');"
            "const button = getComputedStyle(probe);"
            "const heading = getComputedStyle(document.getElementById('activityHeadingProbe'));"
            "const status = getComputedStyle(document.getElementById('activityStatusProbe'));"
            "const score = getComputedStyle(document.getElementById('activityScoreProbe'));"
            "return {buttonColor:button.color,buttonBackground:button.backgroundImage,"
            "headingColor:heading.color,"
            "statusColor:status.color,statusBackground:status.backgroundColor,"
            "scoreColor:score.color,scoreBackground:score.backgroundColor}; })()"
        )

    for theme in ("light", "dark", "purple-gold", "maroon-gold"):
        set_theme(theme)
        palette = expected[theme] if theme in {"light", "dark"} else {
            **expected["dark"], **expected[theme],
        }

        normal = snapshot()
        assert normal["buttonColor"] == palette["normal"]
        assert palette["normal_background"] in normal["buttonBackground"]
        assert normal["headingColor"] == palette["heading"]
        assert normal["statusColor"] == palette["status"]
        assert normal["statusBackground"] == palette["status_background"]
        assert normal["scoreColor"] == palette["score"]
        assert normal["scoreBackground"] == palette["score_background"]

        coordinates = json.loads(browser.evaluate(
            "(() => { const rect = document.getElementById('shutdownStyleProbe').getBoundingClientRect();"
            "return JSON.stringify({x:rect.left + rect.width / 2,y:rect.top + rect.height / 2}); })()"
        ))
        pointer = {
            "type": "pointer", "id": "dashboard-state-mouse",
            "parameters": {"pointerType": "mouse"},
        }
        browser.command("input.performActions", {
            "context": browser.context,
            "actions": [{**pointer, "actions": [{
                "type": "pointerMove", "x": round(coordinates["x"]),
                "y": round(coordinates["y"]), "duration": 0, "origin": "viewport",
            }]}],
        })
        browser.wait_for(
            f"getComputedStyle(document.getElementById('shutdownStyleProbe')).color === "
            f"{json.dumps(palette['hover'])}"
        )
        hovered = snapshot()
        assert palette["hover_background"] in hovered["buttonBackground"]

        browser.command("input.performActions", {
            "context": browser.context,
            "actions": [{**pointer, "actions": [{"type": "pointerDown", "button": 0}]}],
        })
        browser.wait_for(
            f"getComputedStyle(document.getElementById('shutdownStyleProbe')).color === "
            f"{json.dumps(palette['active'])}"
        )
        pressed = snapshot()
        assert palette["active_background"] in pressed["buttonBackground"]
        browser.command("input.releaseActions", {"context": browser.context})

        assert browser.evaluate(
            "(() => { const probe = document.getElementById('shutdownStyleProbe');"
            "probe.disabled = true; return probe.disabled; })()"
        ) is True
        disabled = snapshot()
        assert disabled["buttonColor"] == palette["disabled"]
        assert palette["disabled_background"] in disabled["buttonBackground"]

    set_theme("purple-gold")


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


def test_library_hidden_folder_lifecycle_search_and_order_in_real_browser(browser_stack):
    browser = browser_stack.browser
    base_url = browser_stack.base_url
    critical_html = browser_stack.metadata["critical_html"]
    folder_name = "Browser Hidden Folder"
    renamed_folder = "Browser Archived Folder"
    tail_folder = "Browser Tail Folder"

    def folder_lookup(name):
        return (
            "[...document.querySelectorAll('.library-folder')]"
            f".find(folder => folder.dataset.folderName === {json.dumps(name)})"
        )

    browser.navigate(f"{base_url}/library")
    browser.click(".library-add-folder > button")
    assert browser.evaluate(
        f"(() => {{ const input = document.querySelector('.add-folder-form [name=folder]'); "
        f"input.value = {json.dumps(folder_name)}; return input.value; }})()"
    ) == folder_name
    browser.click(".add-folder-form button[type=submit]")
    browser.wait_for(f"Boolean({folder_lookup(folder_name)})")

    browser.navigate(f"{base_url}/library?view=hidden")
    browser.wait_for(f"!({folder_lookup(folder_name)})")
    browser.navigate(f"{base_url}/library?view=all")
    browser.wait_for(f"({folder_lookup(folder_name)})?.dataset.folderHidden === 'false'")
    browser.navigate(f"{base_url}/library")
    browser.wait_for(f"Boolean({folder_lookup(folder_name)})")

    assert browser.evaluate(
        f"(() => {{ const folder = {folder_lookup(folder_name)}; "
        "folder.querySelector(\"form[action='/set_quiz_folder_hidden']\").requestSubmit(); "
        "return true; })()"
    ) is True
    browser.wait_for(f"!({folder_lookup(folder_name)})")

    browser.navigate(f"{base_url}/library?view=hidden")
    browser.wait_for(
        f"({folder_lookup(folder_name)})?.querySelector('.library-folder-hidden-badge')"
        "?.textContent.trim() === 'Hidden folder'"
    )
    browser.wait_for(
        f"({folder_lookup(folder_name)})?.querySelector('.library-folder-empty')"
        "?.textContent.trim() === 'No quizzes in this view.'"
    )
    browser.navigate(f"{base_url}/library?view=all")
    browser.wait_for(f"({folder_lookup(folder_name)})?.dataset.folderHidden === 'true'")

    browser.navigate(f"{base_url}/library")
    assert browser.evaluate(
        f"(() => {{ const card = [...document.querySelectorAll('.library-quiz-card')]"
        f".find(card => card.dataset.id === {json.dumps(critical_html)}); "
        "const form = card.querySelector('.move-quiz-form'); "
        f"form.querySelector('[name=folder]').value = {json.dumps(folder_name)}; "
        "form.requestSubmit(); return true; })()"
    ) is True
    browser.wait_for(
        f"getComputedStyle({folder_lookup(folder_name)}).display === 'none'"
    )

    assert browser.evaluate(
        "(() => { const search = document.getElementById('librarySearch'); "
        "search.value = 'Browser Critical Workflow'; "
        "search.dispatchEvent(new Event('input', {bubbles:true})); return true; })()"
    ) is True
    browser.wait_for(
        f"getComputedStyle({folder_lookup(folder_name)}).display !== 'none' && "
        f"({folder_lookup(folder_name)})?.classList.contains('library-search-revealed')"
    )
    browser.wait_for(
        f"({folder_lookup(folder_name)})?.querySelector('[data-id={json.dumps(critical_html)}]')"
        "?.querySelector('.library-folder-hidden-badge')?.textContent.trim() === 'Folder hidden'"
    )
    assert browser.evaluate(
        "(() => { const search = document.getElementById('librarySearch'); "
        "search.value = ''; search.dispatchEvent(new Event('input', {bubbles:true})); "
        "return true; })()"
    ) is True
    browser.wait_for(
        f"getComputedStyle({folder_lookup(folder_name)}).display === 'none'"
    )

    browser.navigate(f"{base_url}/library?view=hidden")
    assert browser.evaluate(
        f"(() => {{ const folder = {folder_lookup(folder_name)}; "
        f"const card = folder.querySelector('[data-id={json.dumps(critical_html)}]'); "
        "card.querySelector(\"form[action='/toggle_hidden']\").requestSubmit(); "
        "return true; })()"
    ) is True
    browser.wait_for(
        f"({folder_lookup(folder_name)})?.querySelector('[data-id={json.dumps(critical_html)}]')"
        "?.querySelector('.library-hidden-badge')?.textContent.trim() === 'Hidden'"
    )
    assert browser.evaluate(
        f"(() => {{ const folder = {folder_lookup(folder_name)}; "
        "const form = folder.querySelector(\"form[action='/set_quiz_folder_hidden']\"); "
        "form.requestSubmit(); return true; })()"
    ) is True
    browser.wait_for(
        f"({folder_lookup(folder_name)})?.dataset.folderHidden === 'false'"
    )

    browser.navigate(f"{base_url}/library")
    browser.wait_for(
        f"({folder_lookup(folder_name)})?.querySelector('.library-folder-empty')"
        "?.textContent.trim() === 'No quizzes in this view.'"
    )
    assert browser.evaluate(
        f"!({folder_lookup(folder_name)})?.querySelector('[data-id={json.dumps(critical_html)}]')"
    ) is True

    browser.navigate(f"{base_url}/library?view=hidden")
    assert browser.evaluate(
        f"(() => {{ const folder = {folder_lookup(folder_name)}; "
        "const form = folder.querySelector('.rename-folder-form'); "
        f"form.querySelector('[name=new_folder]').value = {json.dumps(renamed_folder)}; "
        "form.requestSubmit(); return true; })()"
    ) is True
    browser.wait_for(f"Boolean({folder_lookup(renamed_folder)})")

    browser.navigate(f"{base_url}/library")
    browser.click(".library-add-folder > button")
    assert browser.evaluate(
        f"(() => {{ const input = document.querySelector('.add-folder-form [name=folder]'); "
        f"input.value = {json.dumps(tail_folder)}; return input.value; }})()"
    ) == tail_folder
    browser.click(".add-folder-form button[type=submit]")
    browser.wait_for(f"Boolean({folder_lookup(tail_folder)})")
    assert browser.evaluate(
        f"(() => {{ const folder = {folder_lookup(renamed_folder)}; "
        "folder.querySelector(\"form[action='/set_quiz_folder_hidden']\").requestSubmit(); "
        "return true; })()"
    ) is True
    browser.wait_for(
        f"getComputedStyle({folder_lookup(renamed_folder)}).display === 'none'"
    )

    portal_path = browser_stack.data_root / "config" / "portal.json"
    before_order = json.loads(portal_path.read_text(encoding="utf-8"))["quiz_folders"]
    hidden_position = before_order.index(renamed_folder)
    assert browser.evaluate(
        f"(() => {{ const folder = {folder_lookup(tail_folder)}; "
        "folder.querySelector('[data-library-reorder=folder][data-library-reorder-direction=\"-1\"]').click(); "
        "return true; })()"
    ) is True
    browser.wait_for("document.getElementById('libraryReorderStatus').textContent.includes('moved up')")
    browser.navigate(f"{base_url}/library")
    after_order = json.loads(portal_path.read_text(encoding="utf-8"))["quiz_folders"]
    assert after_order.index(renamed_folder) == hidden_position
    assert after_order.index(tail_folder) < after_order.index(renamed_folder)

    browser.navigate(f"{base_url}/library?view=hidden")
    assert browser.evaluate(
        f"(() => {{ const folder = {folder_lookup(renamed_folder)}; window.confirm = () => true; "
        "folder.querySelector(\"form[action='/delete_quiz_folder']\").requestSubmit(); "
        "return true; })()"
    ) is True
    browser.wait_for(f"!({folder_lookup(renamed_folder)})")
    browser.wait_for(
        f"[...document.querySelectorAll('.library-quiz-card')]"
        f".find(card => card.dataset.id === {json.dumps(critical_html)})"
        "?.querySelector('.library-hidden-badge')?.textContent.trim() === 'Hidden'"
    )

    # Restore the shared browser fixture state for the remaining workflows.
    assert browser.evaluate(
        f"(() => {{ const card = [...document.querySelectorAll('.library-quiz-card')]"
        f".find(card => card.dataset.id === {json.dumps(critical_html)}); "
        "const move = card.querySelector('.move-quiz-form'); "
        "move.querySelector('[name=folder]').value = 'Browser Regression'; "
        "move.requestSubmit(); return true; })()"
    ) is True
    browser.wait_for(
        f"[...document.querySelectorAll('.library-quiz-card')]"
        f".some(card => card.dataset.id === {json.dumps(critical_html)})"
    )
    assert browser.evaluate(
        f"(() => {{ const card = [...document.querySelectorAll('.library-quiz-card')]"
        f".find(card => card.dataset.id === {json.dumps(critical_html)}); "
        "card.querySelector(\"form[action='/toggle_hidden']\").requestSubmit(); return true; })()"
    ) is True
    browser.wait_for(
        f"![...document.querySelectorAll('.library-quiz-card')]"
        f".some(card => card.dataset.id === {json.dumps(critical_html)})"
    )
    browser.navigate(f"{base_url}/library")
    browser.wait_for(
        f"[...document.querySelectorAll('.library-quiz-card')]"
        f".some(card => card.dataset.id === {json.dumps(critical_html)})"
    )
    assert browser.evaluate(
        f"(() => {{ const folder = {folder_lookup(tail_folder)}; window.confirm = () => true; "
        "folder.querySelector(\"form[action='/delete_quiz_folder']\").requestSubmit(); "
        "return true; })()"
    ) is True
    browser.wait_for(f"!({folder_lookup(tail_folder)})")


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


def test_paste_quiz_and_preview_readability_across_themes(browser_stack, tmp_path):
    browser = browser_stack.browser
    base_url = browser_stack.base_url
    browser.set_viewport(1400, 1500)

    portal_path = browser_stack.data_root / "config" / "portal.json"
    portal_config = json.loads(portal_path.read_text(encoding="utf-8"))
    portal_config["enable_regex_replace"] = True
    portal_path.write_text(json.dumps(portal_config, indent=2), encoding="utf-8")

    def capture(name):
        result = browser.command(
            "browsingContext.captureScreenshot",
            {"context": browser.context, "origin": "viewport"},
        )
        path = tmp_path / name
        path.write_bytes(base64.b64decode(result["data"]))
        assert path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")

    for theme in ("dark", "light", "purple-gold", "maroon-gold"):
        browser.navigate(f"{base_url}/settings")
        browser.wait_for("window.dlmsCsrfToken && document.getElementById('dlmsQuickTheme')")
        status = browser.evaluate(
            f"fetch('/api/theme', {{method:'POST', headers:{{'Content-Type':'application/json'}}, "
            f"body:JSON.stringify({{theme:{json.dumps(theme)}}})}}).then(response => response.status)"
        )
        assert status == 200

        browser.navigate(f"{base_url}/paste?theme={theme}")
        browser.wait_for(
            "document.querySelectorAll('.build-step-number').length === 3 && "
            "document.querySelectorAll('.build-preset-list > label').length === 3"
        )
        paste_styles = browser.evaluate(
            "(() => {"
            "const resolve = name => { const probe = document.createElement('span');"
            "probe.style.color = `var(${name})`; document.body.appendChild(probe);"
            "const value = getComputedStyle(probe).color; probe.remove(); return value; };"
            "const steps = [...document.querySelectorAll('.build-step-number')];"
            "const note = document.querySelector('.build-format-note');"
            "const noteStyle = getComputedStyle(note);"
            "const help = document.querySelector('.build-help-link');"
            "const presets = [...document.querySelectorAll('.build-preset-list > label')];"
            "return {stepCount:steps.length,"
            "stepColors:steps.map(step => getComputedStyle(step).color),"
            "stepBackground:getComputedStyle(steps[0]).backgroundColor,"
            "stepBackgroundImage:getComputedStyle(steps[0]).backgroundImage,"
            "primaryBackgroundImage:getComputedStyle(document.querySelector('.build-primary-button')).backgroundImage,"
            "noteColor:noteStyle.color,noteBackground:noteStyle.backgroundColor,"
            "noteHeading:getComputedStyle(note.querySelector('strong')).color,"
            "codeColors:[...note.querySelectorAll('code')].map(code => getComputedStyle(code).color),"
            "helpColor:getComputedStyle(help).color,helpBackground:getComputedStyle(help).backgroundColor,"
            "helpBackgroundImage:getComputedStyle(help).backgroundImage,"
            "helpBorder:getComputedStyle(help).borderTopColor,"
            "presetCount:presets.length,"
            "presetBackgrounds:presets.map(row => getComputedStyle(row).backgroundColor),"
            "presetBorders:presets.map(row => getComputedStyle(row).borderTopColor),"
            "presetLabels:presets.map(row => getComputedStyle(row.querySelector('strong')).color),"
            "presetDetails:presets.map(row => getComputedStyle(row.querySelector('small')).color),"
            "presetDetailOpacities:presets.map(row => getComputedStyle(row.querySelector('small')).opacity),"
            "inputBackground:getComputedStyle(document.querySelector('.build-source-textarea')).backgroundColor,"
            "pageText:resolve('--theme-page-text'),heading:resolve('--theme-heading'),"
            "accentText:resolve('--theme-accent-text'),muted:resolve('--theme-muted-text'),"
            "link:resolve('--theme-link')}; })()"
        )
        assert paste_styles["stepCount"] == 3
        assert all(color == paste_styles["accentText"] for color in paste_styles["stepColors"])
        assert paste_styles["stepBackgroundImage"] == "none"
        assert paste_styles["primaryBackgroundImage"] != "none"
        assert paste_styles["noteColor"] == paste_styles["pageText"]
        assert paste_styles["noteHeading"] == paste_styles["heading"]
        assert all(color == paste_styles["accentText"] for color in paste_styles["codeColors"])
        assert paste_styles["noteBackground"] != paste_styles["inputBackground"]
        assert paste_styles["helpColor"] == paste_styles["link"]
        assert paste_styles["helpBackgroundImage"] == "none"
        assert paste_styles["helpBackground"] != "rgba(0, 0, 0, 0)"
        assert paste_styles["helpBorder"] != "rgba(0, 0, 0, 0)"
        assert paste_styles["presetCount"] == 3
        assert len(set(paste_styles["presetBackgrounds"])) == 1
        assert all(color != "rgba(0, 0, 0, 0)" for color in paste_styles["presetBorders"])
        assert all(color == paste_styles["pageText"] for color in paste_styles["presetLabels"])
        assert all(color == paste_styles["muted"] for color in paste_styles["presetDetails"])
        assert all(opacity == "1" for opacity in paste_styles["presetDetailOpacities"])

        if theme == "light":
            capture("paste-questions-light.png")
            browser.evaluate(
                "document.querySelector('.build-advanced-block')"
                ".scrollIntoView({block:'center'}); true"
            )
            capture("paste-advanced-parsing-light.png")

        assert browser.evaluate(
            "(() => { const form = document.querySelector('.build-workspace');"
            "form.querySelector('[name=quiz_title]').value = 'Browser Theme Preview';"
            "form.querySelector('[name=quiz_text]').value = "
            + json.dumps(
                "Which value is correct?\nA. One\nB. Two\nSuggested Answer: B"
            )
            + "; form.requestSubmit(); return true; })()"
        ) is True
        browser.wait_for(
            "document.querySelector('.hero-title')?.textContent.includes('Preview Quiz Before Building')"
        )
        preview_styles = browser.evaluate(
            "(() => {"
            "const resolve = name => { const probe = document.createElement('span');"
            "probe.style.color = `var(${name})`; document.body.appendChild(probe);"
            "const value = getComputedStyle(probe).color; probe.remove(); return value; };"
            "const summary = document.querySelector('.paste-preview-summary');"
            "const hero = document.querySelector('.hero-title');"
            "const source = document.querySelector('#origBox');"
            "const helper = document.querySelector('.paste-preview-helper');"
            "const reason = document.querySelector('.paste-preview-confidence-reason');"
            "const detail = document.querySelector('.paste-preview-suggestion-detail');"
            "const recommendation = document.querySelector('.paste-preview-suggestion-recommendation');"
            "return {heroColor:getComputedStyle(hero).color,"
            "summaryColor:getComputedStyle(summary).color,"
            "summaryBackground:getComputedStyle(summary).backgroundColor,"
            "summaryHeading:getComputedStyle(summary.querySelector('h2')).color,"
            "sourceColor:getComputedStyle(source).color,sourceBackground:getComputedStyle(source).backgroundColor,"
            "helperColor:getComputedStyle(helper).color,helperOpacity:getComputedStyle(helper).opacity,"
            "reasonColor:getComputedStyle(reason).color,reasonOpacity:getComputedStyle(reason).opacity,"
            "detailColor:getComputedStyle(detail).color,detailOpacity:getComputedStyle(detail).opacity,"
            "recommendationColor:getComputedStyle(recommendation).color,"
            "recommendationOpacity:getComputedStyle(recommendation).opacity,"
            "pageText:resolve('--theme-page-text'),heading:resolve('--theme-heading'),"
            "accentText:resolve('--theme-accent-text'),muted:resolve('--theme-muted-text')}; })()"
        )
        assert preview_styles["heroColor"] == preview_styles["heading"]
        assert preview_styles["summaryColor"] == preview_styles["pageText"]
        assert preview_styles["summaryHeading"] == preview_styles["heading"]
        assert preview_styles["sourceColor"] == preview_styles["pageText"]
        assert preview_styles["sourceBackground"] != paste_styles["inputBackground"]
        assert preview_styles["summaryBackground"] != preview_styles["sourceBackground"]
        for role in ("helper", "reason", "detail", "recommendation"):
            assert preview_styles[f"{role}Color"] == preview_styles["muted"]
            assert preview_styles[f"{role}Opacity"] == "1"

        if theme == "light":
            browser.evaluate("window.scrollTo(0, 0); true")
            capture("paste-preview-light.png")
            browser.evaluate(
                "document.querySelector('.paste-preview-confidence')"
                ".scrollIntoView({block:'center'}); true"
            )
            capture("paste-preview-confidence-light.png")


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


def test_ai_settings_reset_buttons_restore_defaults_and_focus_fields(browser_stack):
    browser = browser_stack.browser
    browser.navigate(f"{browser_stack.base_url}/settings/ai")
    browser.wait_for("document.getElementById('resetLawPromptBtn') !== null")

    initial_defaults = browser.evaluate(
        "(() => ({"
        "study:document.getElementById('studyPackAIPromptTemplate').value,"
        "medical:document.getElementById('medicalStudyPackAddendum').value,"
        "law:document.getElementById('lawAIPromptTemplate').value"
        "}))()"
    )
    reset_results = browser.evaluate(
        "(() => {"
        "const contracts=["
        "['resetAIPromptBtn','aiPromptTemplate'],"
        "['resetStudyPackPromptBtn','studyPackAIPromptTemplate'],"
        "['resetMedicalStudyPackPromptBtn','medicalStudyPackAddendum'],"
        "['resetLawPromptBtn','lawAIPromptTemplate']];"
        "const results={};"
        "for (const [buttonId,fieldId] of contracts) {"
        "const field=document.getElementById(fieldId); field.value='DLMS reset sentinel';"
        "document.getElementById(buttonId).click();"
        "results[fieldId]={value:field.value,focused:document.activeElement===field};"
        "} return results; })()"
    )

    assert reset_results["aiPromptTemplate"] == {
        "value": (
            "You are a technical tutor helping a student learn from mistakes.\n\n"
            "For each question:\n"
            "1. Explain why the correct answer is correct\n"
            "2. Explain why the selected answer is incorrect\n"
            "3. Give a short memory tip\n"
            "4. Keep explanations concise but clear\n"
            "5. Return your answer in clearly separated sections per question.\n\n"
            "---\n\n{{questions}}"
        ),
        "focused": True,
    }
    for field_id, default_name in (
        ("studyPackAIPromptTemplate", "study"),
        ("medicalStudyPackAddendum", "medical"),
        ("lawAIPromptTemplate", "law"),
    ):
        assert reset_results[field_id] == {
            "value": initial_defaults[default_name],
            "focused": True,
        }


def test_reset_remove_destructive_controls_requests_and_failure_recovery(browser_stack):
    browser = browser_stack.browser
    base_url = browser_stack.base_url
    browser.navigate(f"{base_url}/settings/reset-remove")
    browser.wait_for(
        "window.dlmsCsrfToken && "
        "document.querySelector('[data-nav-key=settings][aria-current=page]')"
    )

    accessibility = browser.evaluate(
        "(() => ({"
        "menuControls:document.querySelector('[data-settings-menu]').getAttribute('aria-controls'),"
        "menuExpanded:document.querySelector('[data-settings-menu]').getAttribute('aria-expanded'),"
        "clearLive:document.getElementById('clearDBStatus').getAttribute('aria-live'),"
        "resetLive:document.getElementById('resetStatus').getAttribute('aria-live'),"
        "removeLabel:document.querySelector('label[for=removeDlmsConfirmation]')?.textContent.trim(),"
        "clearType:document.getElementById('clearDBBtn').type,"
        "removeType:document.getElementById('removeAllDlmsDataBtn').type,"
        "removeDisabled:document.getElementById('removeAllDlmsDataBtn').disabled"
        "}))()"
    )
    assert accessibility == {
        "menuControls": "dashboardSidebar",
        "menuExpanded": "false",
        "clearLive": "polite",
        "resetLive": "polite",
        "removeLabel": "Type REMOVE DLMS DATA to enable permanent removal",
        "clearType": "button",
        "removeType": "button",
        "removeDisabled": True,
    }

    phrase_states = browser.evaluate(
        "(() => { const input=document.getElementById('removeDlmsConfirmation');"
        "const button=document.getElementById('removeAllDlmsDataBtn'); const states=[];"
        "for (const value of ['remove dlms data','REMOVE DLMS DATA',' REMOVE DLMS DATA ']) {"
        "input.value=value; input.dispatchEvent(new Event('input',{bubbles:true}));"
        "states.push(button.disabled); } return states; })()"
    )
    assert phrase_states == [True, False, False]

    assert browser.evaluate(
        "(() => { window.__resetCalls=[]; window.__resetConfirms=[];"
        "window.confirm=message=>{window.__resetConfirms.push(message);return true};"
        "window.fetch=(input,init={})=>{window.__resetCalls.push({url:String(input),method:init.method});"
        "return new Promise(resolve=>{window.__resolveResetFetch=resolve})}; return true; })()"
    ) is True
    browser.click("#clearDBBtn")
    browser.wait_for(
        "document.getElementById('clearDBBtn').disabled && "
        "document.getElementById('clearDBStatus').textContent === 'Clearing saved history...'"
    )
    browser.evaluate(
        "window.__resolveResetFetch(new Response(JSON.stringify({status:'ok'}),"
        "{status:200,headers:{'Content-Type':'application/json'}})); true"
    )
    browser.wait_for(
        "!document.getElementById('clearDBBtn').disabled && "
        "document.getElementById('clearDBStatus').textContent.includes('history cleared')"
    )
    clear_contract = browser.evaluate(
        "({calls:window.__resetCalls,confirms:window.__resetConfirms,"
        "status:document.getElementById('clearDBStatus').textContent})"
    )
    assert clear_contract == {
        "calls": [{"url": "/api/clear_db_history", "method": "POST"}],
        "confirms": [
            "Clear all saved quiz attempts and missed-question history?\n\n"
            "Your quizzes will remain available.\n\n"
            "Create a backup first if you may need this history later."
        ],
        "status": "✅ Saved attempt and missed-question history cleared.",
    }

    assert browser.evaluate(
        "(() => { sessionStorage.removeItem('dlms-reset-alert'); window.__resetCalls=[];"
        "window.confirm=()=>true;"
        "window.alert=message=>sessionStorage.setItem('dlms-reset-alert',message);"
        "window.fetch=(input,init={})=>{window.__resetCalls.push({url:String(input),method:init.method});"
        "return new Promise(resolve=>{window.__resolveResetFetch=resolve})}; return true; })()"
    ) is True
    browser.click(".resetAction[data-endpoint='/api/reset_quiz_library']")
    browser.wait_for(
        "Array.from(document.querySelectorAll('.resetAction')).every(button=>button.disabled) && "
        "document.getElementById('resetStatus').textContent === "
        "'Creating safety backup and resetting Quiz Library & Results...'"
    )
    browser.evaluate(
        "window.__resolveResetFetch(new Response(JSON.stringify({status:'ok',backup:'browser-safety.zip'}),"
        "{status:200,headers:{'Content-Type':'application/json'}})); true"
    )
    browser.wait_for(
        "document.readyState === 'complete' && "
        "sessionStorage.getItem('dlms-reset-alert') !== null && "
        "typeof window.__resolveResetFetch === 'undefined'"
    )
    assert browser.evaluate("sessionStorage.getItem('dlms-reset-alert')") == (
        "Quiz Library & Results reset completed.\n\n"
        "Safety backup: browser-safety.zip"
    )
    assert browser.evaluate("location.pathname") == "/settings/reset-remove"

    browser.wait_for("window.dlmsCsrfToken && document.getElementById('resetStatus')")
    protected_fetch_setup = (
        "(() => { const protectedFetch=window.fetch.bind(window); window.__resetCalls=[];"
        "window.__resetConfirms=[]; window.confirm=message=>{window.__resetConfirms.push(message);return true};"
        "window.fetch=(input,init={})=>{const headers=Object.fromEntries(new Headers(init.headers||{}));"
        "window.__resetCalls.push({url:String(input),method:init.method||'GET',headers,body:init.body||null});"
        "return protectedFetch(input,init)}; return true; })()"
    )
    marker = browser_stack.data_root / ".dlms-data-root"
    disabled_marker = browser_stack.data_root / ".dlms-data-root.browser-disabled"
    backup_count = len(list((browser_stack.data_root / "backups").glob("*.zip")))
    marker.rename(disabled_marker)
    try:
        assert browser.evaluate(protected_fetch_setup) is True
        browser.click(".resetAction[data-endpoint='/api/reset_all_data']")
        browser.wait_for(
            "document.getElementById('resetStatus').textContent.startsWith('❌ Reset failed:') && "
            "Array.from(document.querySelectorAll('.resetAction')).every(button=>!button.disabled)"
        )
        reset_failure = browser.evaluate(
            "({calls:window.__resetCalls,confirms:window.__resetConfirms,"
            "status:document.getElementById('resetStatus').textContent})"
        )
        assert reset_failure["calls"] == [
            {"url": "/api/reset_all_data", "method": "POST", "headers": {}, "body": None}
        ]
        assert reset_failure["confirms"] == [
            "⚠ DLMS to Fresh State ⚠\n\n"
            "DLMS will create a safety backup first, then perform this reset.\n\n"
            "Continue?"
        ]
        assert "not verified" in reset_failure["status"]
        assert len(list((browser_stack.data_root / "backups").glob("*.zip"))) == backup_count

        cancel_result = browser.evaluate(
            "(() => { const input=document.getElementById('removeDlmsConfirmation');"
            "input.value='REMOVE DLMS DATA';input.dispatchEvent(new Event('input',{bubbles:true}));"
            "window.__resetCalls=[];window.__resetConfirms=[];"
            "window.confirm=message=>{window.__resetConfirms.push(message);return false};"
            "document.getElementById('removeAllDlmsDataBtn').click();"
            "return {calls:window.__resetCalls,confirms:window.__resetConfirms,"
            "disabled:document.getElementById('removeAllDlmsDataBtn').disabled}; })()"
        )
        removal_confirmation = (
            "☠ PERMANENT DLMS DATA REMOVAL ☠\n\n"
            "This will delete the entire DLMS application-data directory INCLUDING ALL BACKUPS, then shut DLMS down.\n\n"
            "The executable/source installation will remain.\n\n"
            "This cannot be undone unless you copied a backup somewhere outside DLMS.\n\n"
            "Continue?"
        )
        assert cancel_result == {
            "calls": [],
            "confirms": [removal_confirmation],
            "disabled": False,
        }

        assert browser.evaluate(
            "(() => {window.__resetCalls=[];window.__resetConfirms=[];"
            "window.confirm=message=>{window.__resetConfirms.push(message);return true};return true})()"
        ) is True
        browser.click("#removeAllDlmsDataBtn")
        browser.wait_for(
            "document.getElementById('resetStatus').textContent.startsWith('❌ Permanent removal failed:') && "
            "!document.getElementById('removeAllDlmsDataBtn').disabled && "
            "!document.getElementById('removeDlmsConfirmation').disabled"
        )
        removal_failure = browser.evaluate(
            "({calls:window.__resetCalls,confirms:window.__resetConfirms,"
            "status:document.getElementById('resetStatus').textContent})"
        )
        assert removal_failure["calls"] == [{
            "url": "/api/remove_all_dlms_data",
            "method": "POST",
            "headers": {"content-type": "application/json"},
            "body": '{"confirmation":"REMOVE DLMS DATA"}',
        }]
        assert removal_failure["confirms"] == [removal_confirmation]
        assert "not verified" in removal_failure["status"]
        assert browser_stack.data_root.is_dir()
        assert disabled_marker.is_file()
    finally:
        if disabled_marker.exists():
            disabled_marker.rename(marker)


def test_system_tools_rebuild_workflow_states_csrf_and_text_rendering(browser_stack):
    browser = browser_stack.browser
    browser.navigate(f"{browser_stack.base_url}/admin/maintenance")
    browser.wait_for(
        "window.dlmsCsrfToken && "
        "document.querySelector('[data-nav-key=settings][aria-current=page]')"
    )

    accessibility = browser.evaluate(
        "(() => ({"
        "menuLabel:document.querySelector('[data-settings-menu]').getAttribute('aria-label'),"
        "menuControls:document.querySelector('[data-settings-menu]').getAttribute('aria-controls'),"
        "menuExpanded:document.querySelector('[data-settings-menu]').getAttribute('aria-expanded'),"
        "buttonType:document.getElementById('rebuildAllBtn').type,"
        "statusLive:document.getElementById('rebuildStatus').getAttribute('aria-live'),"
        "imageEditorHref:document.querySelector('.system-tools-secondary-action').getAttribute('href')"
        "}))()"
    )
    assert accessibility == {
        "menuLabel": "Toggle navigation",
        "menuControls": "dashboardSidebar",
        "menuExpanded": "false",
        "buttonType": "button",
        "statusLive": "polite",
        "imageEditorHref": "/admin/image-editor",
    }

    confirmation = (
        "Rebuild all quiz pages using the current DLMS template?\n\n"
        "Quiz questions, answers, IDs, and history will not be changed."
    )
    cancelled = browser.evaluate(
        "(() => {window.__maintenanceCalls=[];window.__maintenanceConfirms=[];"
        "window.confirm=message=>{window.__maintenanceConfirms.push(message);return false};"
        "const originalFetch=window.fetch.bind(window);"
        "window.fetch=(input,init={})=>{window.__maintenanceCalls.push({url:String(input),method:init.method});"
        "return originalFetch(input,init)};document.getElementById('rebuildAllBtn').click();"
        "return {calls:window.__maintenanceCalls,confirms:window.__maintenanceConfirms,"
        "disabled:document.getElementById('rebuildAllBtn').disabled,"
        "status:document.getElementById('rebuildStatus').textContent};})()"
    )
    assert cancelled == {
        "calls": [],
        "confirms": [confirmation],
        "disabled": False,
        "status": "",
    }

    assert browser.evaluate(
        "(() => {window.__maintenanceCalls=[];window.__maintenanceConfirms=[];"
        "window.confirm=message=>{window.__maintenanceConfirms.push(message);return true};"
        "window.fetch=(input,init={})=>{window.__maintenanceCalls.push({url:String(input),method:init.method});"
        "return new Promise(resolve=>{window.__resolveMaintenanceFetch=resolve})};return true;})()"
    ) is True
    browser.click("#rebuildAllBtn")
    browser.wait_for(
        "document.getElementById('rebuildAllBtn').disabled && "
        "document.getElementById('rebuildStatus').textContent === 'Rebuilding quiz pages...'"
    )
    browser.evaluate(
        "window.__resolveMaintenanceFetch(new Response(JSON.stringify({"
        "status:'complete',rebuilt:'<img id=maintenanceInjected>',failed:['<svg>']}),"
        "{status:200,headers:{'Content-Type':'application/json'}}));true"
    )
    browser.wait_for(
        "!document.getElementById('rebuildAllBtn').disabled && "
        "document.getElementById('rebuildStatus').textContent.startsWith('Complete:')"
    )
    safe_status = browser.evaluate(
        "(() => {const status=document.getElementById('rebuildStatus');return {"
        "text:status.textContent,html:status.innerHTML,"
        "injected:document.getElementById('maintenanceInjected')!==null,"
        "calls:window.__maintenanceCalls,confirms:window.__maintenanceConfirms};})()"
    )
    assert safe_status == {
        "text": "Complete: <img id=maintenanceInjected> rebuilt, 1 failed.",
        "html": "Complete: &lt;img id=maintenanceInjected&gt; rebuilt, 1 failed.",
        "injected": False,
        "calls": [{"url": "/admin/rebuild_all_quiz_html", "method": "POST"}],
        "confirms": [confirmation],
    }

    assert browser.evaluate(
        "(() => {window.confirm=()=>true;window.fetch=()=>new Promise(resolve=>{"
        "window.__resolveMaintenanceFetch=resolve});return true;})()"
    ) is True
    browser.click("#rebuildAllBtn")
    browser.wait_for(
        "document.getElementById('rebuildAllBtn').disabled && "
        "document.getElementById('rebuildStatus').textContent === 'Rebuilding quiz pages...'"
    )
    browser.evaluate(
        "window.__resolveMaintenanceFetch(new Response(JSON.stringify({error:'forced failure'}),"
        "{status:503,headers:{'Content-Type':'application/json'}}));true"
    )
    browser.wait_for(
        "!document.getElementById('rebuildAllBtn').disabled && "
        "document.getElementById('rebuildStatus').textContent === "
        "'Rebuild failed. Check the server log.'"
    )

    browser.navigate(f"{browser_stack.base_url}/admin/maintenance?live=1")
    browser.wait_for("window.dlmsCsrfToken && document.getElementById('rebuildAllBtn')")
    expected_rebuilt = sum(
        entry.get("id") is not None
        for entry in json.loads(
            (browser_stack.data_root / "config" / "quizzes.json").read_text(
                encoding="utf-8"
            )
        )
    )
    assert browser.evaluate(
        "(() => {const protectedFetch=window.fetch.bind(window);window.__maintenanceCalls=[];"
        "window.confirm=()=>true;window.fetch=(input,init={})=>{"
        "window.__maintenanceCalls.push({url:String(input),method:init.method});"
        "return protectedFetch(input,init)};return true;})()"
    ) is True
    browser.click("#rebuildAllBtn")
    browser.wait_for(
        "!document.getElementById('rebuildAllBtn').disabled && "
        "document.getElementById('rebuildStatus').textContent.startsWith('Complete:')",
        timeout=12.0,
    )
    assert browser.evaluate("document.getElementById('rebuildStatus').textContent") == (
        f"Complete: {expected_rebuilt} rebuilt, 0 failed."
    )
    assert browser.evaluate("window.__maintenanceCalls") == [
        {"url": "/admin/rebuild_all_quiz_html", "method": "POST"}
    ]


def test_content_pack_catalog_detail_dialog_navigation_and_escaping(browser_stack):
    browser = browser_stack.browser
    base_url = browser_stack.base_url
    browser.navigate(f"{base_url}/content-packs")
    browser.wait_for(
        "window.dlmsCsrfToken && "
        "document.querySelector('[data-nav-key=content][aria-current=page]') && "
        "document.querySelector(\"form[action='/content-packs/import'] input[name=csrf_token]\")"
    )
    empty = browser.evaluate(
        "(() => ({"
        "heading:document.querySelector('.pack-empty-card h2')?.textContent,"
        "count:document.querySelector('.pack-count-pill').textContent.trim(),"
        "menuLabel:document.getElementById('menuButton').getAttribute('aria-label'),"
        "menuControls:document.getElementById('menuButton').getAttribute('aria-controls'),"
        "dialogHidden:document.getElementById('deletePackDialog').hidden,"
        "dialogRole:document.querySelector('.content-pack-delete-dialog').getAttribute('role'),"
        "dialogModal:document.querySelector('.content-pack-delete-dialog').getAttribute('aria-modal'),"
        "importCsrf:document.querySelector(\"form[action='/content-packs/import'] input[name=csrf_token]\")?.value.length>0,"
        "deleteCsrf:document.querySelector(\"form[action='/content-packs/delete'] input[name=csrf_token]\")?.value.length>0"
        "}))()"
    )
    assert empty == {
        "heading": "No content packs installed",
        "count": "0 installed folders",
        "menuLabel": "Toggle navigation",
        "menuControls": "dashboardSidebar",
        "dialogHidden": True,
        "dialogRole": "dialog",
        "dialogModal": "true",
        "importCsrf": True,
        "deleteCsrf": True,
    }

    folder = "DLMS_Study_browser_catalog"
    pack_name = "Browser <Pack> & Safe"
    description = 'Browser </script><img id="packInjected"> description & safe'
    pack_root = browser_stack.data_root / "content_packs" / folder
    data_root = pack_root / "data"
    data_root.mkdir(parents=True)
    (pack_root / "manifest.json").write_text(
        json.dumps({
            "schema_version": 1,
            "id": "browser_catalog",
            "name": pack_name,
            "version": "1.0 <safe>",
            "description": description,
            "content_domain": "Other & Browser",
            "datasets": [{
                "id": "terms",
                "title": "Browser terms",
                "type": "matching",
                "path": "data/terms.json",
            }],
            "image_datasets": [],
            "quiz_datasets": [],
        }),
        encoding="utf-8",
    )
    (data_root / "terms.json").write_text(
        json.dumps({
            "schema_version": 1,
            "id": "terms",
            "title": "Browser terms",
            "source": {"organization": "DLMS Browser Test", "license": "CC0"},
            "terms": [
                {"term": "Catalog", "definition": "A listed collection."},
                {"term": "Detail", "definition": "Pack metadata."},
            ],
        }),
        encoding="utf-8",
    )

    browser.navigate(f"{base_url}/content-packs?browser-pack=1")
    browser.wait_for(
        "document.querySelector('.content-pack-table tbody') && "
        "document.querySelector('.content-pack-name strong')?.textContent.includes('Browser <Pack>')"
    )
    catalog = browser.evaluate(
        "(() => {const row=document.querySelector('.content-pack-table tbody tr');"
        "const details=row.querySelector(\"a[href*='/content-packs/details/']\");"
        "const exportLink=row.querySelector(\"a[href*='/content-packs/export/']\");"
        "return {name:row.querySelector('.content-pack-name strong').textContent,"
        "folder:row.querySelector('.content-pack-name small').textContent,"
        "count:document.querySelector('.pack-count-pill').textContent.trim(),"
        "status:row.querySelector('.content-pack-status').textContent,"
        "matching:row.querySelector('.content-pack-counts').textContent.trim(),"
        "details:details?.getAttribute('href'),exportHref:exportLink?.getAttribute('href'),"
        "injected:document.getElementById('packInjected')!==null};})()"
    )
    assert catalog == {
        "name": pack_name,
        "folder": folder,
        "count": "1 installed folder",
        "status": "Valid",
        "matching": "1 matching",
        "details": f"/content-packs/details/{folder}",
        "exportHref": f"/content-packs/export/{folder}",
        "injected": False,
    }

    browser.click(".content-pack-action.danger")
    browser.wait_for("!document.getElementById('deletePackDialog').hidden")
    opened = browser.evaluate(
        "(() => {const dialog=document.getElementById('deletePackDialog');"
        "const checkbox=dialog.querySelector('input[name=confirm_delete]');checkbox.checked=true;"
        "return {message:document.getElementById('deletePackMessage').textContent,"
        "folder:document.getElementById('deletePackFolder').value,"
        "injected:document.getElementById('packInjected')!==null,checked:checkbox.checked};})()"
    )
    assert opened == {
        "message": f"Delete “{pack_name}” from installed Content Packs?",
        "folder": folder,
        "injected": False,
        "checked": True,
    }
    browser.click("#deletePackDialog button[type=button]")
    assert browser.evaluate(
        "document.getElementById('deletePackDialog').hidden && "
        "!document.querySelector('#deletePackDialog input[name=confirm_delete]').checked"
    ) is True

    browser.navigate(f"{base_url}/content-packs/details/{folder}")
    browser.wait_for(
        "document.querySelector('[data-nav-key=content][aria-current=page]') && "
        "document.querySelector('.pack-detail-hero h2')?.textContent.includes('Browser <Pack>')"
    )
    detail = browser.evaluate(
        "(() => ({"
        "heading:document.querySelector('.pack-detail-hero h2').textContent,"
        "description:document.querySelector('.pack-detail-hero p').textContent,"
        "status:document.querySelector('.content-pack-status').textContent,"
        "datasets:document.querySelector('.pack-detail-stat-grid strong').textContent,"
        "folder:Array.from(document.querySelectorAll('.pack-detail-meta div')).find(el=>el.querySelector('strong')?.textContent==='Folder')?.querySelector('span').textContent,"
        "backHref:document.querySelector('.pack-detail-actions a').getAttribute('href'),"
        "exportHref:document.querySelector(\".pack-detail-actions a[href*='/export/']\")?.getAttribute('href'),"
        "injected:document.getElementById('packInjected')!==null"
        "}))()"
    )
    assert detail == {
        "heading": pack_name,
        "description": description,
        "status": "Valid",
        "datasets": "1",
        "folder": folder,
        "backHref": "/content-packs",
        "exportHref": f"/content-packs/export/{folder}",
        "injected": False,
    }


def test_content_pack_import_review_install_cancel_csrf_and_escaping(browser_stack):
    browser = browser_stack.browser
    base_url = browser_stack.base_url

    def stage_pack(token, folder, pack_id):
        stage_root = browser_stack.data_root / "content_pack_staging" / token
        pack_root = stage_root / "extracted" / folder
        data_root = pack_root / "data"
        data_root.mkdir(parents=True)
        pack_name = 'Browser </script><img id="reviewInjected"> & Safe'
        uploaded_name = 'Browser <Archive> & "Review".zip'
        (pack_root / "manifest.json").write_text(
            json.dumps({
                "schema_version": 1,
                "id": pack_id,
                "name": pack_name,
                "version": "1.0",
                "description": "Browser review description.",
                "content_domain": "Other",
                "datasets": [{
                    "id": "terms",
                    "title": "Browser terms",
                    "type": "matching",
                    "path": "data/terms.json",
                }],
                "image_datasets": [],
                "quiz_datasets": [],
            }),
            encoding="utf-8",
        )
        (data_root / "terms.json").write_text(
            json.dumps({
                "schema_version": 1,
                "id": "terms",
                "title": "Browser terms",
                "source": {"organization": "DLMS Browser Test", "license": "CC0"},
                "terms": [
                    {"term": "Review", "definition": "Inspect before install."},
                    {"term": "Confirm", "definition": "Authorize installation."},
                ],
            }),
            encoding="utf-8",
        )
        (stage_root / "stage.json").write_text(
            json.dumps({
                "token": token,
                "root_name": f"extracted/{folder}",
                "extract_root": "extracted",
                "uploaded_name": uploaded_name,
                "file_count": 2,
                "uncompressed_bytes": 1048576,
                "report": {},
                "created_at": "2026-09-06T12:00:00",
            }),
            encoding="utf-8",
        )
        return stage_root, pack_name, uploaded_name

    install_token = "1234567890abcdef1234567890abcdef"
    install_folder = "DLMS_Study_browser_review_install"
    stage_root, pack_name, uploaded_name = stage_pack(
        install_token, install_folder, "browser_review_install"
    )
    review_url = f"{base_url}/content-packs/import/{install_token}"
    browser.navigate(review_url)
    browser.wait_for(
        "window.dlmsCsrfToken && "
        "document.querySelector('[data-nav-key=content][aria-current=page]') && "
        "document.querySelector(\"#packReviewInstallForm input[name=csrf_token]\") && "
        "document.querySelector(\".pack-review-cancel-form input[name=csrf_token]\")"
    )
    review = browser.evaluate(
        "(() => {const install=document.getElementById('packReviewInstallForm');"
        "const cancel=document.querySelector('.pack-review-cancel-form');"
        "const confirm=install.querySelector('input[name=confirm_install]');"
        "return {heading:document.querySelector('.pack-review-summary h2').textContent,"
        "metadata:document.querySelector('.pack-review-summary p').textContent,"
        "status:document.querySelector('.content-pack-status').textContent,"
        "installMethod:install.method,installAction:install.getAttribute('action'),"
        "cancelMethod:cancel.method,cancelAction:cancel.getAttribute('action'),"
        "confirmValue:confirm.value,confirmRequired:confirm.required,"
        "installCsrf:install.querySelector('input[name=csrf_token]').value.length>0,"
        "cancelCsrf:cancel.querySelector('input[name=csrf_token]').value.length>0,"
        "menuLabel:document.getElementById('menuButton').getAttribute('aria-label'),"
        "menuControls:document.getElementById('menuButton').getAttribute('aria-controls'),"
        "injected:document.getElementById('reviewInjected')!==null};})()"
    )
    assert review == {
        "heading": pack_name,
        "metadata": f"{uploaded_name} · 2 files · 1.0 MB expanded",
        "status": "Valid",
        "installMethod": "post",
        "installAction": f"/content-packs/import/{install_token}/install",
        "cancelMethod": "post",
        "cancelAction": f"/content-packs/import/{install_token}/cancel",
        "confirmValue": "yes",
        "confirmRequired": True,
        "installCsrf": True,
        "cancelCsrf": True,
        "menuLabel": "Toggle navigation",
        "menuControls": "dashboardSidebar",
        "injected": False,
    }

    browser.evaluate(
        "document.querySelector('#packReviewInstallForm input[name=confirm_install]').checked=true"
    )
    browser.click("button[form=packReviewInstallForm]")
    browser.wait_for(
        "location.pathname==='/content-packs' && "
        "Array.from(document.querySelectorAll('.content-pack-name strong'))"
        ".some(el=>el.textContent.includes('Browser </script>'))"
    )
    assert not stage_root.exists()
    assert (
        browser_stack.data_root / "content_packs" / install_folder
    ).is_dir()
    assert browser.evaluate(
        "document.querySelector('.content-pack-flashes .flash.success').textContent"
    ) == f"Installed Study Pack '{pack_name}' successfully."
    assert browser.evaluate("document.getElementById('reviewInjected')===null") is True

    cancel_token = "abcdef1234567890abcdef1234567890"
    cancel_stage, _, _ = stage_pack(
        cancel_token,
        "DLMS_Study_browser_review_cancel",
        "browser_review_cancel",
    )
    browser.navigate(f"{base_url}/content-packs/import/{cancel_token}")
    browser.wait_for(
        "window.dlmsCsrfToken && "
        "document.querySelector(\".pack-review-cancel-form input[name=csrf_token]\")"
    )
    browser.click(".pack-review-cancel-form button")
    browser.wait_for(
        "location.pathname==='/content-packs' && "
        "document.querySelector('.content-pack-flashes .flash.success')"
    )
    assert not cancel_stage.exists()
    assert browser.evaluate(
        "document.querySelector('.content-pack-flashes .flash.success').textContent"
    ) == "Study Pack import cancelled; staging files were removed."


def test_medical_read_only_views_empty_populated_controls_csrf_and_escaping(browser_stack):
    browser = browser_stack.browser
    base_url = browser_stack.base_url

    browser.navigate(f"{base_url}/medical")
    browser.wait_for(
        "document.querySelector('[data-nav-key=medical][aria-current=page]') && "
        "document.querySelector('.medical-empty-state-panel')"
    )
    empty = browser.evaluate(
        "(() => ({heading:document.querySelector('.medical-header h1').textContent,"
        "emptyHeading:document.querySelector('.medical-empty-state-panel h2').textContent,"
        "builderHref:document.querySelector(\"a[href^='/study-packs/ai-builder?domain=Medical']\").getAttribute('href'),"
        "packsHref:document.querySelector(\".medical-section-launch-card[href='/content-packs']\").getAttribute('href'),"
        "menuLabel:document.getElementById('menuButton').getAttribute('aria-label'),"
        "menuControls:document.getElementById('menuButton').getAttribute('aria-controls')}))()"
    )
    assert empty == {
        "heading": "Medical Study",
        "emptyHeading": "No Medical Study Packs Installed",
        "builderHref": "/study-packs/ai-builder?domain=Medical&from=medical",
        "packsHref": "/content-packs",
        "menuLabel": "Toggle navigation",
        "menuControls": "dashboardSidebar",
    }

    folder = "DLMS_Study_browser_medical_views"
    pack_root = browser_stack.data_root / "content_packs" / folder
    data_root = pack_root / "data"
    assets_root = pack_root / "assets"
    data_root.mkdir(parents=True)
    assets_root.mkdir()
    pack_name = 'Medical </script><img id="medicalPackInjected"> & Safe'
    matching_title = 'Terms </script><svg id="medicalMatchingInjected"> & Safe'
    matching_description = 'Matching <b id="medicalDescriptionInjected"> details & safe'
    anatomy_title = 'Anatomy </script><svg id="medicalAnatomyInjected"> & Safe'
    anatomy_description = 'Anatomy <b id="medicalAnatomyDescriptionInjected"> details & safe'
    framework_name = 'Framework <img id="medicalFrameworkInjected"> & Safe'
    (pack_root / "manifest.json").write_text(
        json.dumps({
            "schema_version": 1,
            "id": "browser_medical_views",
            "name": pack_name,
            "version": "1.0 <safe>",
            "description": "Browser Medical views.",
            "content_domain": "Medical",
            "datasets": [{
                "id": "terms",
                "title": matching_title,
                "description": matching_description,
                "type": "matching",
                "path": "data/terms.json",
            }],
            "image_datasets": [{
                "id": "anatomy",
                "title": anatomy_title,
                "description": anatomy_description,
                "type": "image",
                "path": "data/anatomy.json",
            }],
            "quiz_datasets": [],
            "image_framework": {
                "name": framework_name,
                "description": "Circle and polygon hotspot schema.",
                "schema_version": 1,
                "status": "ready",
            },
        }),
        encoding="utf-8",
    )
    (data_root / "terms.json").write_text(
        json.dumps({
            "schema_version": 1,
            "id": "terms",
            "title": matching_title,
            "category": "Clinical & Core",
            "source": {"organization": "DLMS Browser", "license": "CC0"},
            "terms": [
                {"term": "Anterior", "definition": "Toward the front."},
                {"term": "Posterior", "definition": "Toward the back."},
                {"term": "Medial", "definition": "Toward the midline."},
            ],
        }),
        encoding="utf-8",
    )
    (data_root / "anatomy.json").write_text(
        json.dumps({
            "schema_version": 1,
            "id": "anatomy",
            "title": anatomy_title,
            "category": "Anatomy & Images",
            "source": {"organization": "DLMS Browser", "license": "CC0"},
            "images": [{
                "id": "body",
                "file": "assets/body.png",
                "alt_text": "Browser anatomy image",
                "source": {"organization": "DLMS Browser", "license": "CC0"},
                "hotspots": [
                    {
                        "id": "one",
                        "label": "Structure One",
                        "prompt": "Identify structure one.",
                        "shape": {"type": "circle", "cx": 0.5, "cy": 0.5, "r": 0.1},
                    },
                    {
                        "id": "two",
                        "label": "Structure Two",
                        "prompt": "Identify structure two.",
                        "shape": {"type": "circle", "cx": 0.7, "cy": 0.7, "r": 0.1},
                    },
                ],
            }],
        }),
        encoding="utf-8",
    )
    (assets_root / "body.png").write_bytes(
        base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
        )
    )

    browser.navigate(f"{base_url}/medical?populated=1")
    browser.wait_for(
        "document.querySelector('.medical-header h1')?.textContent.includes('Medical </script>')"
    )
    home = browser.evaluate(
        "(() => {const cards=Array.from(document.querySelectorAll('.medical-summary-grid .dashboard-stat-card'));"
        "return {heading:document.querySelector('.medical-header h1').textContent,"
        "banks:cards[1].querySelector('strong').textContent,"
        "terms:cards[1].querySelector('small').textContent,"
        "imageSets:cards[2].querySelector('strong').textContent,"
        "structures:cards[2].querySelector('small').textContent,"
        "matchingHref:document.querySelector(\".medical-section-launch-card[href='/medical/matching']\").getAttribute('href'),"
        "anatomyHref:document.querySelector(\".medical-section-launch-card[href='/medical/anatomy']\").getAttribute('href'),"
        "injected:document.getElementById('medicalPackInjected')!==null};})()"
    )
    assert home == {
        "heading": pack_name,
        "banks": "1",
        "terms": "3 terminology terms",
        "imageSets": "1",
        "structures": "2 visual structures",
        "matchingHref": "/medical/matching",
        "anatomyHref": "/medical/anatomy",
        "injected": False,
    }

    browser.navigate(f"{base_url}/medical/matching")
    browser.wait_for(
        "window.dlmsCsrfToken && "
        "document.querySelector(\"form[action='/medical/generate'] input[name=csrf_token]\")"
    )
    matching = browser.evaluate(
        "(() => {const form=document.querySelector(\"form[action='/medical/generate']\");"
        "const toggle=document.querySelector('.medical-dataset-toggle');"
        "return {title:toggle.textContent.trim().replace(/^›\\s*/,''),"
        "description:document.querySelector('.medical-dataset-detail-content p').textContent,"
        "method:form.method,action:form.getAttribute('action'),"
        "packId:form.querySelector('input[name=pack_id]').value,"
        "datasetId:form.querySelector('input[name=dataset_id]').value,"
        "roundMin:form.querySelector('input[name=round_size]').min,"
        "roundMax:form.querySelector('input[name=round_size]').max,"
        "roundValue:form.querySelector('input[name=round_size]').value,"
        "direction:form.querySelector('select[name=direction]').value,"
        "csrf:form.querySelector('input[name=csrf_token]').value.length>0,"
        "expanded:toggle.getAttribute('aria-expanded'),"
        "detailHidden:document.getElementById(toggle.dataset.medicalDetail).hidden,"
        "navCurrent:document.querySelector('[data-nav-key=medical]').getAttribute('aria-current'),"
        "injected:!!document.getElementById('medicalMatchingInjected')||!!document.getElementById('medicalDescriptionInjected')};})()"
    )
    assert matching == {
        "title": matching_title,
        "description": matching_description,
        "method": "post",
        "action": "/medical/generate",
        "packId": "browser_medical_views",
        "datasetId": "terms",
        "roundMin": "2",
        "roundMax": "3",
        "roundValue": "3",
        "direction": "random",
        "csrf": True,
        "expanded": "false",
        "detailHidden": True,
        "navCurrent": "page",
        "injected": False,
    }
    browser.click("[data-medical-expand=matching]")
    assert browser.evaluate(
        "document.querySelector('.medical-dataset-toggle').getAttribute('aria-expanded')==='true' && "
        "!document.querySelector('.medical-dataset-detail-row').hidden"
    ) is True
    browser.click("[data-medical-collapse=matching]")
    assert browser.evaluate(
        "document.querySelector('.medical-dataset-toggle').getAttribute('aria-expanded')==='false' && "
        "document.querySelector('.medical-dataset-detail-row').hidden"
    ) is True

    browser.navigate(f"{base_url}/medical/anatomy")
    browser.wait_for(
        "window.dlmsCsrfToken && "
        "document.querySelector(\"form[action='/medical/anatomy/generate'] input[name=csrf_token]\")"
    )
    anatomy = browser.evaluate(
        "(() => {const form=document.querySelector(\"form[action='/medical/anatomy/generate']\");"
        "const toggle=document.querySelector('.medical-dataset-toggle');"
        "return {framework:document.querySelector('.medical-image-framework-card h2').textContent,"
        "title:toggle.textContent.trim().replace(/^›\\s*/,''),"
        "description:document.querySelector('.medical-dataset-detail-content p').textContent,"
        "method:form.method,action:form.getAttribute('action'),"
        "packId:form.querySelector('input[name=pack_id]').value,"
        "datasetId:form.querySelector('input[name=dataset_id]').value,"
        "csrf:form.querySelector('input[name=csrf_token]').value.length>0,"
        "expanded:toggle.getAttribute('aria-expanded'),"
        "detailHidden:document.getElementById(toggle.dataset.medicalDetail).hidden,"
        "navCurrent:document.querySelector('[data-nav-key=medical]').getAttribute('aria-current'),"
        "injected:!!document.getElementById('medicalAnatomyInjected')||"
        "!!document.getElementById('medicalAnatomyDescriptionInjected')||"
        "!!document.getElementById('medicalFrameworkInjected')};})()"
    )
    assert anatomy == {
        "framework": framework_name,
        "title": anatomy_title,
        "description": anatomy_description,
        "method": "post",
        "action": "/medical/anatomy/generate",
        "packId": "browser_medical_views",
        "datasetId": "anatomy",
        "csrf": True,
        "expanded": "false",
        "detailHidden": True,
        "navCurrent": "page",
        "injected": False,
    }
    browser.click("[data-medical-expand=anatomy]")
    assert browser.evaluate(
        "document.querySelector('.medical-dataset-toggle').getAttribute('aria-expanded')==='true' && "
        "!document.querySelector('.medical-dataset-detail-row').hidden"
    ) is True
    browser.click("[data-medical-collapse=anatomy]")
    assert browser.evaluate(
        "document.querySelector('.medical-dataset-toggle').getAttribute('aria-expanded')==='false' && "
        "document.querySelector('.medical-dataset-detail-row').hidden"
    ) is True


def test_it_read_only_views_empty_populated_controls_csrf_and_escaping(browser_stack):
    browser = browser_stack.browser
    base_url = browser_stack.base_url

    browser.navigate(f"{base_url}/it")
    browser.wait_for(
        "document.querySelector('[data-nav-key=it][aria-current=page]') && "
        "document.querySelector('.medical-summary-grid')"
    )
    empty = browser.evaluate(
        "(() => {const cards=Array.from(document.querySelectorAll('.medical-summary-grid .dashboard-stat-card'));"
        "return {heading:document.querySelector('.medical-header h1').textContent,"
        "packs:cards[0].querySelector('strong').textContent,"
        "banks:cards[1].querySelector('strong').textContent,"
        "images:cards[2].querySelector('strong').textContent,"
        "builderHref:document.querySelector(\"a[href^='/study-packs/ai-builder?domain=IT']\").getAttribute('href'),"
        "packsHref:document.querySelector(\".medical-section-launch-card[href='/content-packs']\").getAttribute('href'),"
        "menuLabel:document.getElementById('menuButton').getAttribute('aria-label'),"
        "menuControls:document.getElementById('menuButton').getAttribute('aria-controls')}})()"
    )
    assert empty == {
        "heading": "DLMS IT Study",
        "packs": "0",
        "banks": "0",
        "images": "0",
        "builderHref": "/study-packs/ai-builder?domain=IT%20/%20Cybersecurity&from=it",
        "packsHref": "/content-packs",
        "menuLabel": "Toggle navigation",
        "menuControls": "dashboardSidebar",
    }

    folder = "DLMS_Study_browser_it_views"
    pack_root = browser_stack.data_root / "content_packs" / folder
    data_root = pack_root / "data"
    assets_root = pack_root / "assets"
    data_root.mkdir(parents=True)
    assets_root.mkdir()
    pack_name = 'IT </script><img id="itPackInjected"> & Safe'
    matching_title = 'Concepts </script><svg id="itMatchingInjected"> & Safe'
    matching_description = 'Matching <b id="itMatchingDescriptionInjected"> details & safe'
    image_title = 'Diagrams </script><svg id="itImageInjected"> & Safe'
    image_description = 'Images <b id="itImageDescriptionInjected"> details & safe'
    quiz_title = 'Questions </script><svg id="itQuizInjected"> & Safe'
    (pack_root / "manifest.json").write_text(
        json.dumps({
            "schema_version": 1,
            "id": "browser_it_views",
            "name": pack_name,
            "version": "1.0 <safe>",
            "description": "Browser IT views.",
            "content_domain": "IT / Cybersecurity",
            "datasets": [{
                "id": "concepts",
                "title": matching_title,
                "description": matching_description,
                "type": "matching",
                "path": "data/concepts.json",
            }],
            "image_datasets": [{
                "id": "diagrams",
                "title": image_title,
                "description": image_description,
                "type": "image",
                "path": "data/diagrams.json",
            }],
            "quiz_datasets": [{
                "id": "questions",
                "title": quiz_title,
                "description": "Mixed browser questions.",
                "type": "quiz",
                "path": "data/questions.json",
            }],
        }),
        encoding="utf-8",
    )
    (data_root / "concepts.json").write_text(
        json.dumps({
            "schema_version": 1,
            "id": "concepts",
            "title": matching_title,
            "category": 'Protocols <category> & "safe"',
            "source": {"organization": "DLMS Browser", "license": "CC0"},
            "terms": [
                {"term": "Layer", "definition": "A level in a model."},
                {"term": "Frame", "definition": "A data-link unit."},
                {"term": "Packet", "definition": "A network-layer unit."},
            ],
        }),
        encoding="utf-8",
    )
    (data_root / "diagrams.json").write_text(
        json.dumps({
            "schema_version": 1,
            "id": "diagrams",
            "title": image_title,
            "category": 'Network <category> & "safe"',
            "source": {"organization": "DLMS Browser", "license": "CC0"},
            "images": [{
                "id": "network",
                "file": "assets/network.png",
                "alt_text": "Browser network image",
                "source": {"organization": "DLMS Browser", "license": "CC0"},
                "hotspots": [
                    {
                        "id": "router",
                        "label": "Router",
                        "prompt": "Identify the router.",
                        "shape": {"type": "circle", "cx": 0.5, "cy": 0.5, "r": 0.1},
                    },
                    {
                        "id": "switch",
                        "label": "Switch",
                        "prompt": "Identify the switch.",
                        "shape": {"type": "circle", "cx": 0.7, "cy": 0.7, "r": 0.1},
                    },
                ],
            }],
        }),
        encoding="utf-8",
    )
    (data_root / "questions.json").write_text(
        json.dumps({
            "schema_version": 1,
            "id": "questions",
            "title": quiz_title,
            "source": {"organization": "DLMS Browser", "license": "CC0"},
            "questions": [
                {
                    "type": "choice",
                    "question": "Which device routes packets?",
                    "choices": [
                        {"text": "Router", "is_correct": True},
                        {"text": "Keyboard", "is_correct": False},
                    ],
                }
            ],
        }),
        encoding="utf-8",
    )
    (assets_root / "network.png").write_bytes(
        base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
        )
    )

    browser.navigate(f"{base_url}/it?populated=1")
    browser.wait_for(
        "document.querySelector('.dashboard-sidebar-version')?.textContent.includes('IT </script>')"
    )
    home = browser.evaluate(
        "(() => {const cards=Array.from(document.querySelectorAll('.medical-summary-grid .dashboard-stat-card'));"
        "return {packs:cards[0].querySelector('strong').textContent,"
        "banks:cards[1].querySelector('strong').textContent,"
        "terms:cards[1].querySelector('small').textContent,"
        "imageSets:cards[2].querySelector('strong').textContent,"
        "targets:cards[2].querySelector('small').textContent,"
        "questionHeading:document.querySelector('.medical-ai-builder-teaser h2').textContent,"
        "questionCopy:document.querySelector('.medical-ai-builder-teaser p').textContent,"
        "matchingHref:document.querySelector(\".medical-section-launch-card[href='/it/matching']\").getAttribute('href'),"
        "imagesHref:document.querySelector(\".medical-section-launch-card[href='/it/images']\").getAttribute('href'),"
        "navCurrent:document.querySelector('[data-nav-key=it]').getAttribute('aria-current'),"
        "injected:!!document.getElementById('itPackInjected')||!!document.getElementById('itQuizInjected')};})()"
    )
    assert home == {
        "packs": "1",
        "banks": "1",
        "terms": "3 concepts",
        "imageSets": "1",
        "targets": "2 targets across 1 images",
        "questionHeading": "1 Question Set",
        "questionCopy": "1 mixed questions are available through the main Study Packs workspace.",
        "matchingHref": "/it/matching",
        "imagesHref": "/it/images",
        "navCurrent": "page",
        "injected": False,
    }

    browser.navigate(f"{base_url}/it/matching")
    browser.wait_for(
        "window.dlmsCsrfToken && "
        "document.querySelector(\"form[action='/study-packs/generate'] input[name=csrf_token]\")"
    )
    matching = browser.evaluate(
        "(() => {const form=document.querySelector(\"form[action='/study-packs/generate']\");"
        "const toggle=document.querySelector('.study-dataset-title-button');"
        "const round=document.querySelector(\"input[name='round_size']\");"
        "const direction=document.querySelector(\"select[name='direction']\");"
        "const submit=document.querySelector('.study-table-primary');"
        "return {title:toggle.textContent,description:document.querySelector('.medical-dataset-detail-content p').textContent,"
        "method:form.method,action:form.getAttribute('action'),"
        "packId:document.querySelector(\"input[name='pack_id']\").value,"
        "datasetId:document.querySelector(\"input[name='dataset_id']\").value,"
        "roundMin:round.min,roundMax:round.max,roundValue:round.value,roundForm:round.getAttribute('form'),"
        "direction:direction.value,directionForm:direction.getAttribute('form'),"
        "submitForm:submit.getAttribute('form'),csrf:form.querySelector('input[name=csrf_token]').value.length>0,"
        "expanded:toggle.getAttribute('aria-expanded'),detailHidden:document.querySelector('.study-dataset-detail-row').hidden,"
        "navCurrent:document.querySelector('[data-nav-key=it]').getAttribute('aria-current'),"
        "injected:!!document.getElementById('itMatchingInjected')||!!document.getElementById('itMatchingDescriptionInjected')};})()"
    )
    assert matching == {
        "title": matching_title,
        "description": matching_description,
        "method": "post",
        "action": "/study-packs/generate",
        "packId": "browser_it_views",
        "datasetId": "concepts",
        "roundMin": "2",
        "roundMax": "3",
        "roundValue": "3",
        "roundForm": "it-match-form-1",
        "direction": "random",
        "directionForm": "it-match-form-1",
        "submitForm": "it-match-form-1",
        "csrf": True,
        "expanded": None,
        "detailHidden": True,
        "navCurrent": "page",
        "injected": False,
    }
    browser.click(".study-dataset-title-button")
    browser.wait_for("!document.querySelector('.study-dataset-detail-row').hidden")
    browser.evaluate(
        "Array.from(document.querySelectorAll('.medical-compact-panel-actions button'))"
        ".find(button=>button.textContent==='Collapse All').click()"
    )
    browser.wait_for("document.querySelector('.study-dataset-detail-row').hidden")
    browser.evaluate(
        "Array.from(document.querySelectorAll('.medical-compact-panel-actions button'))"
        ".find(button=>button.textContent==='Expand All').click()"
    )
    browser.wait_for("!document.querySelector('.study-dataset-detail-row').hidden")

    browser.navigate(f"{base_url}/it/images")
    browser.wait_for(
        "window.dlmsCsrfToken && "
        "document.querySelector(\"form[action='/study-packs/image/generate'] input[name=csrf_token]\")"
    )
    images = browser.evaluate(
        "(() => {const form=document.querySelector(\"form[action='/study-packs/image/generate']\");"
        "const toggle=document.querySelector('.study-dataset-title-button');"
        "return {title:toggle.textContent,description:document.querySelector('.medical-dataset-detail-content p').textContent,"
        "method:form.method,action:form.getAttribute('action'),"
        "packId:form.querySelector(\"input[name='pack_id']\").value,"
        "datasetId:form.querySelector(\"input[name='dataset_id']\").value,"
        "csrf:form.querySelector('input[name=csrf_token]').value.length>0,"
        "expanded:toggle.getAttribute('aria-expanded'),detailHidden:document.querySelector('.study-dataset-detail-row').hidden,"
        "navCurrent:document.querySelector('[data-nav-key=it]').getAttribute('aria-current'),"
        "injected:!!document.getElementById('itImageInjected')||!!document.getElementById('itImageDescriptionInjected')};})()"
    )
    assert images == {
        "title": image_title,
        "description": image_description,
        "method": "post",
        "action": "/study-packs/image/generate",
        "packId": "browser_it_views",
        "datasetId": "diagrams",
        "csrf": True,
        "expanded": None,
        "detailHidden": True,
        "navCurrent": "page",
        "injected": False,
    }
    browser.click(".study-dataset-title-button")
    browser.wait_for("!document.querySelector('.study-dataset-detail-row').hidden")


def test_study_packs_catalog_populated_controls_csrf_state_and_escaping(browser_stack):
    browser = browser_stack.browser
    base_url = browser_stack.base_url

    folder = "DLMS_Study_browser_study_packs_catalog"
    pack_root = browser_stack.data_root / "content_packs" / folder
    data_root = pack_root / "data"
    assets_root = pack_root / "assets"
    data_root.mkdir(parents=True)
    assets_root.mkdir()
    pack_name = 'Catalog </script><img id="studyPackInjected"> & Safe'
    pack_description = 'Pack <b id="studyPackDescriptionInjected"> details & safe'
    matching_title = 'Terms </script><svg id="studyMatchingInjected"> & Safe'
    matching_description = 'Term <b id="studyMatchingDescriptionInjected"> details'
    image_title = 'Images </script><svg id="studyImageInjected"> & Safe'
    image_description = 'Image <b id="studyImageDescriptionInjected"> details'
    quiz_title = 'Questions </script><svg id="studyQuizInjected"> & Safe'
    quiz_description = 'Question <b id="studyQuizDescriptionInjected"> details'
    (pack_root / "manifest.json").write_text(
        json.dumps({
            "schema_version": 1,
            "id": "browser_catalog",
            "name": pack_name,
            "version": "3.0 <safe>",
            "description": pack_description,
            "content_domain": "Science & Engineering",
            "datasets": [{
                "id": "terms",
                "title": matching_title,
                "description": matching_description,
                "type": "matching",
                "path": "data/terms.json",
            }],
            "image_datasets": [{
                "id": "images",
                "title": image_title,
                "description": image_description,
                "type": "image",
                "path": "data/images.json",
            }],
            "quiz_datasets": [{
                "id": "questions",
                "title": quiz_title,
                "description": quiz_description,
                "type": "quiz",
                "path": "data/questions.json",
            }],
        }),
        encoding="utf-8",
    )
    (data_root / "terms.json").write_text(
        json.dumps({
            "schema_version": 1,
            "id": "terms",
            "title": matching_title,
            "category": 'Foundations <category> & "safe"',
            "source": {"organization": "DLMS Browser", "license": "CC0"},
            "terms": [
                {"term": "Mass", "definition": "Quantity of matter."},
                {"term": "Force", "definition": "Mass times acceleration."},
                {"term": "Energy", "definition": "Capacity to do work."},
            ],
        }),
        encoding="utf-8",
    )
    (data_root / "images.json").write_text(
        json.dumps({
            "schema_version": 1,
            "id": "images",
            "title": image_title,
            "category": 'Diagrams <category> & "safe"',
            "source": {"organization": "DLMS Browser", "license": "CC0"},
            "images": [{
                "id": "diagram",
                "file": "assets/diagram.png",
                "alt_text": "Browser science diagram",
                "source": {"organization": "DLMS Browser", "license": "CC0"},
                "hotspots": [
                    {
                        "id": "one",
                        "label": "Point One",
                        "prompt": "Identify point one.",
                        "shape": {"type": "circle", "cx": 0.4, "cy": 0.4, "r": 0.1},
                    },
                    {
                        "id": "two",
                        "label": "Point Two",
                        "prompt": "Identify point two.",
                        "shape": {"type": "circle", "cx": 0.6, "cy": 0.6, "r": 0.1},
                    },
                ],
            }],
        }),
        encoding="utf-8",
    )
    (data_root / "questions.json").write_text(
        json.dumps({
            "schema_version": 1,
            "id": "questions",
            "title": quiz_title,
            "category": 'Review <category> & "safe"',
            "source": {"organization": "DLMS Browser", "license": "CC0"},
            "questions": [{
                "type": "choice",
                "question": "Which quantity is measured in joules?",
                "choices": [
                    {"text": "Energy", "is_correct": True},
                    {"text": "Mass", "is_correct": False},
                ],
            }],
        }),
        encoding="utf-8",
    )
    (assets_root / "diagram.png").write_bytes(
        base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
        )
    )

    browser.navigate(f"{base_url}/study-packs")
    browser.evaluate("localStorage.removeItem('dlms.studyPacks.openState.v1')")
    browser.navigate(f"{base_url}/study-packs?installed=browser_catalog")
    browser.wait_for(
        "window.dlmsCsrfToken && "
        "document.querySelector(\"[data-pack-id='browser_catalog'] form[action='/study-packs/generate'] input[name=csrf_token]\") && "
        "document.querySelector(\"[data-pack-id='browser_catalog'] form[action='/study-packs/image/generate'] input[name=csrf_token]\") && "
        "document.querySelector(\"[data-pack-id='browser_catalog'] form[action='/study-packs/quiz/generate'] input[name=csrf_token]\")"
    )
    catalog = browser.evaluate(
        "(() => {const pack=document.querySelector(\"[data-pack-id='browser_catalog']\");"
        "const forms=Array.from(pack.querySelectorAll('form'));"
        "const counts=Array.from(pack.querySelectorAll('.study-pack-summary-meta span')).map(el=>el.textContent.trim());"
        "return {name:pack.querySelector('h2').textContent,description:pack.querySelector('.study-pack-summary-main p').textContent,"
        "eyebrow:pack.querySelector('.medical-eyebrow').textContent,counts,open:pack.open,"
        "installedId:pack.id,installedClass:pack.classList.contains('is-newly-installed'),"
        "noticeLabel:document.querySelector('.study-pack-installed-notice').getAttribute('aria-label'),"
        "noticeId:document.querySelector('.study-pack-installed-notice strong').textContent,"
        "noticeHref:document.querySelector('.study-pack-installed-notice a').getAttribute('href'),"
        "actions:forms.map(form=>form.getAttribute('action')).sort(),"
        "methods:forms.map(form=>form.method),"
        "packIds:forms.map(form=>form.querySelector(\"input[name='pack_id']\").value),"
        "datasetIds:forms.map(form=>form.querySelector(\"input[name='dataset_id']\").value).sort(),"
        "csrf:forms.every(form=>form.querySelector(\"input[name='csrf_token']\")?.value.length>0),"
        "round:pack.querySelector(\"input[name='round_size']\").value,"
        "roundForm:pack.querySelector(\"input[name='round_size']\").getAttribute('form'),"
        "direction:pack.querySelector(\"select[name='direction']\").value,"
        "navCurrent:document.querySelector('[data-nav-key=study]').getAttribute('aria-current'),"
        "menuLabel:document.getElementById('menuButton').getAttribute('aria-label'),"
        "injected:!!document.getElementById('studyPackInjected')||!!document.getElementById('studyPackDescriptionInjected')||"
        "!!document.getElementById('studyMatchingInjected')||!!document.getElementById('studyMatchingDescriptionInjected')||"
        "!!document.getElementById('studyImageInjected')||!!document.getElementById('studyImageDescriptionInjected')||"
        "!!document.getElementById('studyQuizInjected')||!!document.getElementById('studyQuizDescriptionInjected')};})()"
    )
    assert catalog == {
        "name": pack_name,
        "description": pack_description,
        "eyebrow": "SCIENCE & ENGINEERING · 3.0 <safe>",
        "counts": ["3 datasets", "1 matching", "1 image", "1 mixed"],
        "open": True,
        "installedId": "installed-study-pack",
        "installedClass": True,
        "noticeLabel": "Newly installed Study Pack",
        "noticeId": "browser_catalog",
        "noticeHref": "#installed-study-pack",
        "actions": [
            "/study-packs/generate",
            "/study-packs/image/generate",
            "/study-packs/quiz/generate",
        ],
        "methods": ["post", "post", "post"],
        "packIds": ["browser_catalog", "browser_catalog", "browser_catalog"],
        "datasetIds": ["images", "questions", "terms"],
        "csrf": True,
        "round": "3",
        "roundForm": "matchForm-browser_catalog-1",
        "direction": "random",
        "navCurrent": "page",
        "menuLabel": "Toggle navigation",
        "injected": False,
    }

    browser.click("#collapseAllPacks")
    browser.wait_for("!document.querySelector(\"[data-pack-id='browser_catalog']\").open")
    assert browser.evaluate(
        "JSON.parse(localStorage.getItem('dlms.studyPacks.openState.v1')).browser_catalog"
    ) is False
    browser.click("#expandAllPacks")
    browser.wait_for("document.querySelector(\"[data-pack-id='browser_catalog']\").open")
    matching_toggle = (
        "[data-pack-id='browser_catalog'] "
        "form[action='/study-packs/generate']"
    )
    browser.evaluate(
        f"document.querySelector({json.dumps(matching_toggle)})"
        ".closest('tr').querySelector('.study-dataset-title-button').click()"
    )
    browser.wait_for(
        "!document.getElementById('dataset-browser_catalog-matching-1').hidden"
    )

    browser.navigate(f"{base_url}/study-packs?domain_group=other")
    browser.wait_for("document.querySelector('[data-nav-key=other][aria-current=page]')")
    other = browser.evaluate(
        "(() => ({heading:document.querySelector('.dashboard-header h1').textContent,"
        "builderHref:document.querySelector('.study-pack-launch').getAttribute('href'),"
        "catalogPresent:!!document.querySelector(\"[data-pack-id='browser_catalog']\"),"
        "itPresent:!!document.querySelector(\"[data-pack-id='browser_it_views']\"),"
        "medicalPresent:!!document.querySelector(\"[data-pack-id='browser_medical_views']\")}))()"
    )
    assert other == {
        "heading": "Other Studies",
        "builderHref": "/study-packs/ai-builder?domain=Other&from=other",
        "catalogPresent": True,
        "itPresent": False,
        "medicalPresent": False,
    }


def test_law_landing_counts_links_navigation_controls_and_metadata_boundaries(browser_stack):
    browser = browser_stack.browser
    base_url = browser_stack.base_url
    registry_path = browser_stack.data_root / "config" / "law.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    hostile = 'Law </script><img id="lawLandingInjected"> & Safe'
    registry["cases"].append({
        "id": "law-landing-hostile",
        "title": hostile,
        "course": '<b id="lawLandingCourseInjected">Torts</b>',
        "file": "law-landing-hostile.json",
        "status": "draft-hostile-status",
    })
    registry["folders"].append('<svg id="lawLandingFolderInjected">Evidence</svg>')
    registry_path.write_text(json.dumps(registry), encoding="utf-8")

    browser.set_viewport(760, 1100)
    browser.navigate(f"{base_url}/law")
    browser.wait_for(
        "document.querySelector('[data-nav-key=law][aria-current=page]') && "
        "document.querySelector('.law-hub-summary')"
    )
    landing = browser.evaluate(
        "(() => {const stats=Array.from(document.querySelectorAll('.law-hub-stat'));"
        "const cards=Array.from(document.querySelectorAll('.law-hub-card'));"
        "const menu=document.getElementById('menuButton');const shutdown=document.getElementById('shutdownBtn');"
        "return {heading:document.querySelector('.law-hub-header h1').textContent,"
        "cases:stats[0].querySelector('strong').textContent,courses:stats[1].querySelector('strong').textContent,"
        "workflow:stats[2].querySelector('strong').textContent,summaryLabel:document.querySelector('.law-hub-summary').getAttribute('aria-label'),"
        "toolsLabel:document.querySelector('.law-hub-grid').getAttribute('aria-label'),"
        "links:cards.map(card=>card.getAttribute('href')),"
        "headings:cards.map(card=>card.querySelector('h2').textContent),"
        "primaryNav:document.querySelector('nav.dashboard-nav').getAttribute('aria-label'),"
        "systemNav:document.querySelector('nav.dashboard-nav-system').getAttribute('aria-label'),"
        "navCurrent:document.querySelector('[data-nav-key=law]').getAttribute('aria-current'),"
        "menuLabel:menu.getAttribute('aria-label'),menuControls:menu.getAttribute('aria-controls'),"
        "menuExpanded:menu.getAttribute('aria-expanded'),shutdownType:shutdown.type,shutdownText:shutdown.textContent.trim(),"
        "injected:!!document.getElementById('lawLandingInjected')||!!document.getElementById('lawLandingCourseInjected')||"
        "!!document.getElementById('lawLandingFolderInjected'),"
        "metadataVisible:document.body.textContent.includes('draft-hostile-status')||"
        "document.body.textContent.includes('law-landing-hostile.json')||"
        f"document.body.textContent.includes({json.dumps(hostile)})}};}})()"
    )
    assert landing == {
        "heading": "Casework & Review",
        "cases": str(len(registry["cases"])),
        "courses": str(len(registry["folders"])),
        "workflow": "AI Ready",
        "summaryLabel": "Law Study summary",
        "toolsLabel": "Law Study tools",
        "links": ["/law/create", "/law/import", "/law/cases", "/law/imports"],
        "headings": [
            "Create Case Review",
            "Import Case Packet",
            "My Case Reviews",
            "Saved Imports",
        ],
        "primaryNav": "Primary navigation",
        "systemNav": "System navigation",
        "navCurrent": "page",
        "menuLabel": "Toggle navigation",
        "menuControls": "dashboardSidebar",
        "menuExpanded": "false",
        "shutdownType": "button",
        "shutdownText": "⏻Shutdown DLMS",
        "injected": False,
        "metadataVisible": False,
    }

    browser.click("#menuButton")
    browser.wait_for("document.getElementById('dashboardSidebar').classList.contains('open')")
    assert browser.evaluate(
        "document.getElementById('menuButton').getAttribute('aria-expanded')"
    ) == "true"
    browser.click(".law-hub-header h1")
    browser.wait_for("!document.getElementById('dashboardSidebar').classList.contains('open')")
    assert browser.evaluate(
        "document.getElementById('menuButton').getAttribute('aria-expanded')"
    ) == "false"

    shutdown = browser.evaluate(
        "(() => {window.__lawShutdownConfirm='';window.__lawShutdownRequest=null;"
        "window.confirm=message=>{window.__lawShutdownConfirm=message;return true};"
        "window.fetch=(url,options)=>{window.__lawShutdownRequest={url,method:options.method};"
        "return new Promise(()=>{})};document.getElementById('shutdownBtn').click();"
        "return {confirm:window.__lawShutdownConfirm,request:window.__lawShutdownRequest};})()"
    )
    assert shutdown == {
        "confirm": (
            "SHUTDOWN DLMS\n\nThis will stop the application.\n\n"
            "You will need to restart it manually.\n\nContinue?"
        ),
        "request": {"url": "/api/shutdown", "method": "POST"},
    }


def test_law_catalogs_render_records_banners_actions_and_runtime_csrf(browser_stack):
    browser = browser_stack.browser
    base_url = browser_stack.base_url
    data_root = browser_stack.data_root

    import_name = 'browser & <import-id> "quoted" \'single\'.txt'
    (data_root / "law" / "imports" / import_name).write_text(
        "Browser catalog packet", encoding="utf-8"
    )

    registry_path = data_root / "config" / "law.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    case_id = 'browser & <case-id> "quoted" \'single\''
    case_title = 'Catalog & <img id="lawCatalogInjected"> "Case"'
    registry["cases"].append({
        "id": case_id,
        "title": case_title,
        "course": '<b id="lawCourseCatalogInjected">Procedure</b>',
        "created_at": "2099-09-07T12:00:00",
        "source_import": '<svg id="lawSourceCatalogInjected">source.txt</svg>',
        "status": "catalog-hidden-status",
        "description": "catalog-hidden-description",
        "file": "catalog-hidden-path.json",
    })
    registry_path.write_text(json.dumps(registry), encoding="utf-8")

    browser.set_viewport(760, 1100)
    browser.navigate(f"{base_url}/law/imports?deleted=1")
    browser.wait_for(
        "document.querySelector('[data-nav-key=law][aria-current=page]') && "
        "document.querySelector('input[name=csrf_token]')"
    )
    imports = browser.evaluate(
        "(() => {const rows=Array.from(document.querySelectorAll('.law-record-row'));"
        f"const row=rows.find(item=>item.querySelector('h3').textContent==={json.dumps(import_name)});"
        "const form=row.querySelector('form');const open=row.querySelector('.law-open-action');"
        "return {heading:document.querySelector('h1').textContent,count:document.querySelector('.law-count-pill').textContent,"
        "banner:document.querySelector('.law-notice').textContent,filename:row.querySelector('h3').textContent,"
        "open:open.getAttribute('onclick'),method:form.method,action:form.getAttribute('action'),"
        "confirm:form.getAttribute('onsubmit'),csrf:!!form.querySelector('input[name=csrf_token][type=hidden]'),"
        "deleteLabel:form.querySelector('button').getAttribute('aria-label'),"
        "current:document.querySelector('[data-nav-key=law]').getAttribute('aria-current'),"
        "menuExpanded:document.getElementById('menuButton').getAttribute('aria-expanded'),"
        "injected:!!document.getElementById('import-id')};})()"
    )
    assert imports == {
        "heading": "Saved Law Imports",
        "count": "1 saved",
        "banner": "Saved import deleted.Structured case reviews were not changed.",
        "filename": import_name,
        "open": f"location.href='/law/imports/{import_name}'",
        "method": "post",
        "action": f"/law/imports/{import_name}/delete",
        "confirm": (
            "return confirm('Delete this saved raw import? This will not delete any "
            "structured case reviews already created from it.');"
        ),
        "csrf": True,
        "deleteLabel": "Delete import",
        "current": "page",
        "menuExpanded": "false",
        "injected": False,
    }

    browser.navigate(f"{base_url}/law/cases?deleted=1")
    browser.wait_for(
        "document.querySelector('[data-nav-key=law][aria-current=page]') && "
        "document.querySelector('input[name=csrf_token]')"
    )
    cases = browser.evaluate(
        "(() => {const rows=Array.from(document.querySelectorAll('.law-record-row'));"
        f"const row=rows.find(item=>item.querySelector('h3').textContent==={json.dumps(case_title)});"
        "const form=row.querySelector('form');return {heading:document.querySelector('h1').textContent,"
        "count:document.querySelector('.law-count-pill').textContent,banner:document.querySelector('.law-notice').textContent,"
        "firstTitle:rows[0].querySelector('h3').textContent,title:row.querySelector('h3').textContent,"
        "course:row.querySelector('.law-record-meta span').textContent,source:row.querySelector('.law-record-source').textContent,"
        "open:row.querySelector('.law-open-action').getAttribute('onclick'),method:form.method,"
        "action:form.getAttribute('action'),confirm:form.getAttribute('onsubmit'),"
        "csrf:!!form.querySelector('input[name=csrf_token][type=hidden]'),"
        "deleteLabel:form.querySelector('button').getAttribute('aria-label'),"
        "injected:!!document.getElementById('lawCatalogInjected')||"
        "!!document.getElementById('lawCourseCatalogInjected')||"
        "!!document.getElementById('lawSourceCatalogInjected'),"
        "hidden:document.body.textContent.includes('catalog-hidden-status')||"
        "document.body.textContent.includes('catalog-hidden-description')||"
        "document.body.textContent.includes('catalog-hidden-path.json')};})()"
    )
    assert cases == {
        "heading": "My Case Reviews",
        "count": f"{len(registry['cases'])} saved",
        "banner": "Case review deleted.The original raw import was not changed.",
        "firstTitle": case_title,
        "title": case_title,
        "course": '<b id="lawCourseCatalogInjected">Procedure</b>',
        "source": 'Source: <svg id="lawSourceCatalogInjected">source.txt</svg>',
        "open": f"location.href='/law/cases/{case_id}'",
        "method": "post",
        "action": f"/law/cases/{case_id}/delete",
        "confirm": (
            "return confirm('Delete this Law Case Review? This will remove the saved "
            "case review JSON file, but it will not delete the original raw import.');"
        ),
        "csrf": True,
        "deleteLabel": "Delete case review",
        "injected": False,
        "hidden": False,
    }

    browser.click("#menuButton")
    browser.wait_for("document.getElementById('dashboardSidebar').classList.contains('open')")
    assert browser.evaluate(
        "document.getElementById('menuButton').getAttribute('aria-expanded')"
    ) == "true"
    browser.click(".law-subpage-header h1")
    browser.wait_for("!document.getElementById('dashboardSidebar').classList.contains('open')")
