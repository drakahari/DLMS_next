"""Opt-in browser regressions for DLMS's highest-risk client/server seams."""

from __future__ import annotations

import base64
import hashlib
import http.cookiejar
import json
import os
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pytest

from dlms.rendering.quiz_artifacts import build_quiz_html
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


def test_storage_health_themes_and_narrow_layout(browser_stack):
    browser = browser_stack.browser
    base = browser_stack.base_url
    browser.navigate(base + "/settings/backup")
    for theme in ("light", "dark", "purple-gold", "maroon-gold"):
        _set_theme(browser, theme)
        browser.navigate(base + "/settings/backup?storage=1")
        browser.wait_for("document.querySelector('#storage-health').textContent.includes('Database size')")
        for width in (1440, 420):
            browser.set_viewport(width, 1000)
            browser.wait_for_page_ready()
            assert browser.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
            assert browser.evaluate("document.querySelector('#storage-health').textContent.includes('Available disk space')")
            browser.evaluate("document.querySelector('#storage-health a').focus(); true")
            assert browser.evaluate("document.activeElement.getAttribute('href')") == "/settings/backup?storage=1#storage-health"
            contrast = _theme_contrast_snapshot(browser, {"body": "#storage-health p", "heading": "#storageHeading"})
            assert contrast["body"]["contrast"] >= 4.5
            assert contrast["heading"]["contrast"] >= 3
            geometry = browser.evaluate("(() => {const chart=document.querySelector('.storage-donut').getBoundingClientRect();const list=document.querySelector('.storage-usage-list').getBoundingClientRect();return {chartWidth:chart.width,left:chart.left,right:chart.right,chartTop:chart.top,listTop:list.top,listLeft:list.left};})()")
            assert 150 <= geometry["chartWidth"] <= 240
            assert geometry["left"] >= 0 and geometry["right"] <= width
            if width == 420:
                assert geometry["listTop"] > geometry["chartTop"] + geometry["chartWidth"]
            else:
                assert geometry["listLeft"] > geometry["right"]
            assert browser.evaluate("[...document.querySelectorAll('.storage-slice')].every(s=>[...document.querySelectorAll('.storage-usage-list li')].some(li=>li.dataset.category===s.dataset.category&&li.dataset.bytes===s.dataset.bytes))")
            extra_contrast = _theme_contrast_snapshot(browser, {"total": ".storage-donut-total strong", "legend": ".storage-usage-list li", "note": "#storageChartNote"})
            assert all(item["contrast"] >= 4.5 for item in extra_contrast.values()), (theme, width, extra_contrast)


@dataclass
class BrowserStack:
    browser: FirefoxBidi
    base_url: str
    data_root: Path
    metadata: dict


@dataclass
class BrowserServer:
    firefox: str
    base_url: str
    data_root: Path
    metadata: dict
    work_root: Path
    env: dict
    process_options: dict


def _set_theme(browser, theme):
    browser.wait_for(
        "typeof window.dlmsCsrfToken === 'string' && "
        "window.dlmsCsrfToken.length > 0"
    )
    status = browser.evaluate(
        f"fetch('/api/theme', {{method:'POST', headers:{{'Content-Type':'application/json'}}, "
        f"body:JSON.stringify({{theme:{json.dumps(theme)}}})}}).then(response => response.status)"
    )
    assert status == 200


def _theme_contrast_snapshot(browser, selectors):
    """Measure rendered text contrast against each element's effective background."""
    return browser.evaluate(
        "(() => {"
        "const selectors=" + json.dumps(selectors) + ";"
        "const parseColor=value=>{"
        "const rgb=value.match(/^rgba?\\(([^)]+)\\)$/);"
        "if(rgb){const parts=rgb[1].split(/[, ]+/).filter(Boolean).map(Number);"
        "return [parts[0]/255,parts[1]/255,parts[2]/255,parts.length>3?parts[3]:1];}"
        "const srgb=value.match(/^color\\(srgb ([^/ )]+) ([^/ )]+) ([^/ )]+)(?: \\/ ([^)]+))?\\)$/);"
        "if(srgb)return [+srgb[1],+srgb[2],+srgb[3],srgb[4]===undefined?1:+srgb[4]];"
        "throw new Error('Unsupported computed color: '+value);};"
        "const resolveColor=value=>{const sample=document.createElement('span');"
        "sample.style.color=value;document.body.appendChild(sample);"
        "const result=getComputedStyle(sample).color;sample.remove();return parseColor(result);};"
        "const composite=(foreground,background)=>foreground.slice(0,3).map((value,index)=>"
        "value*foreground[3]+background[index]*(1-foreground[3]));"
        "const luminance=rgb=>rgb.map(value=>value<=.04045?value/12.92:"
        "Math.pow((value+.055)/1.055,2.4)).reduce((sum,value,index)=>"
        "sum+value*[.2126,.7152,.0722][index],0);"
        "const contrast=(foreground,background)=>{const a=luminance(foreground),b=luminance(background);"
        "return (Math.max(a,b)+.05)/(Math.min(a,b)+.05);};"
        "const root=getComputedStyle(document.documentElement);"
        "const base=resolveColor(root.getPropertyValue('--theme-body-base')).slice(0,3);"
        "const effectiveBackground=node=>{const layers=[];"
        "for(let item=node;item;item=item.parentElement){layers.push(parseColor(getComputedStyle(item).backgroundColor));}"
        "return layers.reverse().reduce((background,layer)=>composite(layer,background),base);};"
        "const measure=(name,selector)=>{const node=document.querySelector(selector);"
        "if(!node)throw new Error('Missing contrast target '+name+': '+selector);"
        "const style=getComputedStyle(node),background=effectiveBackground(node);"
        "const color=parseColor(style.color),foreground=composite(color,background);"
        "return [name,{contrast:contrast(foreground,background),color:style.color,"
        "background:style.backgroundColor,borderColor:style.borderColor,"
        "borderStyle:style.borderStyle,outlineStyle:style.outlineStyle,"
        "opacity:style.opacity,cursor:style.cursor,text:node.textContent.trim()}];};"
        "return Object.fromEntries(Object.entries(selectors).map(([name,selector])=>measure(name,selector)));"
        "})()"
    )


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


@pytest.fixture
def browser_server(tmp_path_factory):
    firefox = shutil.which("firefox") or shutil.which("firefox-esr")
    if not firefox:
        pytest.skip("Firefox is not installed")

    work_root = tmp_path_factory.mktemp("dlms-browser")
    data_root = work_root / "data-root"
    server_port = _free_loopback_port()
    base_url = f"http://127.0.0.1:{server_port}"
    server_log = work_root / "server.log"
    ocr_test_root = work_root / "ocr-runtime"
    ocr_tessdata = ocr_test_root / "tessdata"
    ocr_tessdata.mkdir(parents=True)
    (ocr_tessdata / "eng.traineddata").write_bytes(b"browser fixture language data")
    (ocr_tessdata / "configs").mkdir()
    (ocr_tessdata / "configs" / "tsv").write_text(
        "tessedit_create_tsv 1\n", encoding="utf-8"
    )
    ocr_executable = ocr_test_root / "tesseract"
    ocr_executable.write_text(
        "#!" + sys.executable + "\n"
        "import sys\n"
        "if '--version' in sys.argv:\n"
        " print('tesseract 5.5.3')\n"
        " raise SystemExit(0)\n"
        "lines=['Which controls apply? Select all that apply','A. First option','B. Second option','C. Third option','D. Fourth option','Correct answers: B and D','Explanation: The second and fourth options apply.']\n"
        "print('level\\tpage_num\\tblock_num\\tpar_num\\tline_num\\tword_num\\tleft\\ttop\\twidth\\theight\\tconf\\ttext')\n"
        "top=30\n"
        "for line_no,line in enumerate(lines,1):\n"
        " left=70\n"
        " for word_no,word in enumerate(line.split(),1):\n"
        "  width=max(15,len(word)*9)\n"
        "  print(f'5\\t1\\t1\\t1\\t{line_no}\\t{word_no}\\t{left}\\t{top}\\t{width}\\t24\\t94.0\\t{word}')\n"
        "  left+=width+8\n"
        " top+=48\n",
        encoding="utf-8",
    )
    ocr_executable.chmod(0o755)
    env = os.environ.copy()
    env.update({
        "QUIZAPP_DATA_DIR": str(data_root),
        "DLMS_NO_BROWSER": "1",
        "DLMS_BROWSER_TEST_PORT": str(server_port),
        "MOZ_CRASHREPORTER_DISABLE": "1",
        "MOZ_DISABLE_AUTO_SAFE_MODE": "1",
        "PYTHONUNBUFFERED": "1",
        "DLMS_TESSERACT_EXECUTABLE": str(ocr_executable),
        "DLMS_TESSDATA_PREFIX": str(ocr_tessdata),
    })
    process_options = {"start_new_session": True} if os.name == "posix" else {}
    server_process = None

    try:
        with server_log.open("w", encoding="utf-8") as server_output:
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
            yield BrowserServer(
                firefox=firefox,
                base_url=base_url,
                data_root=data_root,
                metadata=metadata,
                work_root=work_root,
                env=env,
                process_options=process_options,
            )
    finally:
        _terminate_process_tree(server_process)
        shutil.rmtree(work_root, ignore_errors=True)


@pytest.fixture
def browser_stack(browser_server):
    browser_port = _free_loopback_port()
    session_root = browser_server.work_root / f"firefox-session-{browser_port}"
    profile = session_root / "profile"
    profile.mkdir(parents=True)
    (profile / "user.js").write_text(
        '\n'.join([
            'user_pref("datareporting.healthreport.uploadEnabled", false);',
            'user_pref("toolkit.telemetry.enabled", false);',
            'user_pref("browser.crashReports.unsubmittedCheck.autoSubmit2", false);',
        ]),
        encoding="utf-8",
    )
    browser_log = session_root / "firefox.log"
    browser_process = None
    browser = None

    try:
        with browser_log.open("w", encoding="utf-8") as browser_output:
            browser_process = subprocess.Popen(
                [
                    browser_server.firefox,
                    "--headless",
                    "--no-remote",
                    "--profile",
                    str(profile),
                    "--remote-debugging-port",
                    str(browser_port),
                    "about:blank",
                ],
                cwd=ROOT,
                env=browser_server.env,
                stdout=browser_output,
                stderr=subprocess.STDOUT,
                **browser_server.process_options,
            )
            browser = _connect_firefox(browser_port, browser_process, browser_log)
            yield BrowserStack(
                browser,
                browser_server.base_url,
                browser_server.data_root,
                browser_server.metadata,
            )
    finally:
        if browser is not None:
            browser.close()
        _terminate_process_tree(browser_process)
        shutil.rmtree(session_root, ignore_errors=True)


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


def _close_context_after_pagehide(browser, closing_context, observer_context):
    """Close one tab only after its synchronous pagehide handlers have run."""
    marker_key = f"dlms.browser-test.pagehide:{time.monotonic_ns()}"
    encoded_key = json.dumps(marker_key)
    browser.context = closing_context
    browser.evaluate(
        "window.addEventListener('pagehide', () => "
        f"localStorage.setItem({encoded_key}, 'complete'), {{once:true}}); true"
    )
    try:
        browser.command("browsingContext.close", {"context": closing_context})
    finally:
        browser.context = observer_context
    browser.wait_for(f"localStorage.getItem({encoded_key}) === 'complete'")
    browser.evaluate(f"localStorage.removeItem({encoded_key}); true")


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
            "scores": {
                "good": ("rgb(22, 120, 79)", "rgba(34, 155, 98, 0.1)"),
                "warn": ("rgb(138, 99, 0)", "rgba(204, 155, 33, 0.12)"),
                "bad": ("rgb(185, 61, 82)", "rgba(198, 63, 82, 0.1)"),
            },
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
            "scores": {
                "good": ("rgb(134, 232, 187)", "rgba(27, 114, 81, 0.18)"),
                "warn": ("rgb(237, 214, 129)", "rgba(112, 87, 20, 0.18)"),
                "bad": ("rgb(255, 157, 163)", "rgba(123, 41, 48, 0.2)"),
            },
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
        browser.wait_for("document.querySelector('.dashboard-activity-row .dashboard-score') !== null")
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
            "'<span id=\"activityScoreGoodProbe\" class=\"dashboard-score score-good\">100%</span>' +"
            "'<span id=\"activityScoreWarnProbe\" class=\"dashboard-score score-warn\">75%</span>' +"
            "'<span id=\"activityScoreBadProbe\" class=\"dashboard-score score-bad\">40%</span>' +"
            "'<span id=\"historyScoreGoodProbe\" class=\"history-score-badge good\">100%</span>' +"
            "'<span id=\"historyScoreWarnProbe\" class=\"history-score-badge warn\">75%</span>' +"
            "'<span id=\"historyScoreBadProbe\" class=\"history-score-badge bad\">40%</span>';"
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
            "const styles = id => { const value = getComputedStyle(document.getElementById(id));"
            "return {color:value.color,background:value.backgroundColor}; };"
            "const recent = document.querySelector('.dashboard-activity-row .dashboard-score');"
            "const recentStyle = getComputedStyle(recent);"
            "return {buttonColor:button.color,buttonBackground:button.backgroundImage,"
            "headingColor:heading.color,"
            "statusColor:status.color,statusBackground:status.backgroundColor,"
            "dashboardScores:{good:styles('activityScoreGoodProbe'),warn:styles('activityScoreWarnProbe'),"
            "bad:styles('activityScoreBadProbe')},"
            "historyScores:{good:styles('historyScoreGoodProbe'),warn:styles('historyScoreWarnProbe'),"
            "bad:styles('historyScoreBadProbe')},"
            "recentScore:{text:recent.textContent.trim(),className:recent.className,"
            "color:recentStyle.color,background:recentStyle.backgroundColor}}; })()"
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
        for state, (color, background) in palette["scores"].items():
            assert normal["dashboardScores"][state] == {"color": color, "background": background}
            assert normal["historyScores"][state] == normal["dashboardScores"][state]
        assert normal["recentScore"]["text"] == "0%"
        assert "score-bad" in normal["recentScore"]["className"]
        assert normal["recentScore"]["color"] == palette["scores"]["bad"][0]
        assert normal["recentScore"]["background"] == palette["scores"]["bad"][1]

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


def test_library_touch_navigation_and_scroll_gestures_across_themes(browser_stack):
    """Exercise Sortable's real event listeners, without emulating mobile OS physics."""
    browser = browser_stack.browser
    for theme in ("light", "dark", "purple-gold", "maroon-gold"):
        browser.navigate(f"{browser_stack.base_url}/library")
        _set_theme(browser, theme)
        for width in (1280, 420):
            browser.set_viewport(width, 850)
            browser.navigate(f"{browser_stack.base_url}/library")
            browser.wait_for("document.querySelectorAll('.library-quiz-card').length === 2")
            result = browser.evaluate("""(() => {
                const before = [...document.querySelectorAll('.quiz-card')].map(e=>e.dataset.id);
                let prevented = false, chosen = false;
                for (const selector of ['.library-quiz-title-row h3', '.library-folder-header',
                                        '.library-primary-action.compact']) {
                    const target = document.querySelector(selector);
                    for (const pointerType of ['touch', 'pen']) {
                        for (const type of ['pointerdown', 'pointermove', 'pointerup']) {
                            const event = new PointerEvent(type, {bubbles:true, cancelable:true,
                                pointerType, button:0, clientX:100, clientY:type==='pointermove'?300:100});
                            target.dispatchEvent(event);
                            prevented ||= event.defaultPrevented;
                            chosen ||= Boolean(Sortable.dragged || Sortable.active);
                        }
                    }
                    // Legacy touchstart path (used by browsers without Pointer Events).
                    const start = new Event('touchstart', {bubbles:true, cancelable:true});
                    Object.defineProperty(start, 'touches', {value:[{target, clientX:100, clientY:100}]});
                    target.dispatchEvent(start);
                    prevented ||= start.defaultPrevented;
                    chosen ||= Boolean(Sortable.dragged || Sortable.active);
                    const move = new Event('touchmove', {bubbles:true, cancelable:true});
                    Object.defineProperty(move, 'touches', {value:[{target, clientX:100, clientY:300}]});
                    target.dispatchEvent(move);
                    prevented ||= move.defaultPrevented;
                    chosen ||= Boolean(Sortable.dragged || Sortable.active);
                    target.dispatchEvent(new Event('touchend', {bubbles:true}));
                }
                const after = [...document.querySelectorAll('.quiz-card')].map(e=>e.dataset.id);
                return {prevented, chosen, unchanged:JSON.stringify(before)===JSON.stringify(after),
                    overflow:document.documentElement.scrollWidth>innerWidth,
                    href:document.querySelector('.library-primary-action.compact').getAttribute('href')};
            })()""")
            assert result["prevented"] is False
            assert result["chosen"] is False
            assert result["unchanged"] is True
            assert result["overflow"] is False
            # Native link activation remains intact after touch/scroll input.
            browser.click(".library-primary-action.compact")
            browser.wait_for(f"location.pathname === {json.dumps(result['href'])}")


def test_library_mouse_drag_reordering(browser_stack):
    browser = browser_stack.browser
    browser.set_viewport(1280, 1000)
    browser.navigate(f"{browser_stack.base_url}/library")
    browser.wait_for("document.querySelectorAll('.library-quiz-card').length === 2")
    order = "[...document.querySelectorAll('.library-quiz-card')].map(e=>e.dataset.id)"
    initial = browser.evaluate(order)
    browser.evaluate("""(() => {
        const save = saveLibraryQuizOrder;
        window.dragOrderSaved = false;
        saveLibraryQuizOrder = async body => {
            await save(body);
            window.dragOrderSaved = true;
        };
    })()""")
    points = browser.evaluate("""(() => {
        const cards = [...document.querySelectorAll('.library-quiz-card')];
        cards[0].scrollIntoView({block:'center'});
        const a=cards[0].querySelector('h3').getBoundingClientRect();
        const b=cards[1].getBoundingClientRect();
        return {x:Math.round(a.x+15), y:Math.round(a.y+10),
                end:Math.round(b.bottom-10)};
    })()""")
    browser.command("input.performActions", {
        "context": browser.context,
        "actions": [{"type":"pointer", "id":"mouse", "parameters":{"pointerType":"mouse"},
                     "actions":[
                         {"type":"pointerMove", "x":points["x"], "y":points["y"]},
                         {"type":"pointerDown", "button":0},
                         {"type":"pointerMove", "x":points["x"]+15, "y":points["y"]+15, "duration":200},
                         {"type":"pointerMove", "x":points["x"], "y":points["end"], "duration":600},
                         {"type":"pause", "duration":300},
                         {"type":"pointerUp", "button":0}]}]})
    browser.command("input.releaseActions", {"context":browser.context})
    # Firefox BiDi moves the native drag but does not consistently emit its
    # terminal dragend on pointerUp. Complete that OS event if still active.
    browser.evaluate("""(() => {
        if (Sortable.dragged) Sortable.dragged.dispatchEvent(
            new DragEvent('dragend', {bubbles:true, cancelable:true}));
    })()""")
    reversed_order = list(reversed(initial))
    browser.wait_for(f"JSON.stringify({order}) === {json.dumps(json.dumps(reversed_order, separators=(',', ':')))}")
    browser.wait_for("window.dragOrderSaved === true")
    browser.navigate(f"{browser_stack.base_url}/library")
    assert browser.evaluate(order) == reversed_order



def test_library_keyboard_focus_and_nonpointer_reordering(browser_stack):
    browser = browser_stack.browser
    browser.navigate(f"{browser_stack.base_url}/library")
    order = "[...document.querySelectorAll('.library-quiz-card')].map(e=>e.dataset.id)"
    initial = browser.evaluate(order)
    browser.activate()
    browser.evaluate("document.querySelector('.library-quiz-card a[href^=\"/export/quiz/\"]').focus(); true")
    browser.press_key("\ue004")
    assert browser.evaluate(
        "document.activeElement.dataset.libraryReorder === 'quiz' && "
        "document.activeElement.dataset.libraryReorderDirection === '1'"
    ) is True
    # Headless Firefox BiDi delivers Return key events without native button
    # activation here. Exercise the non-pointer click separately from Tab focus.
    browser.evaluate("document.activeElement.click(); true")
    browser.wait_for("document.getElementById('libraryReorderStatus').textContent.includes('moved down')")
    browser.navigate(f"{browser_stack.base_url}/library")
    assert browser.evaluate(order) == list(reversed(initial))


def test_library_smart_views_use_browser_recovery_and_remain_theme_responsive(
    browser_stack,
):
    browser = browser_stack.browser
    base_url = browser_stack.base_url
    critical_id = str(browser_stack.metadata["critical_id"])
    companion_id = str(browser_stack.metadata["companion_id"])
    critical_html = browser_stack.metadata["critical_html"]
    database_path = browser_stack.data_root / "results.db"
    generated_rows = (
        (
            "Renamed browser practice",
            "renamed-browser-practice.html",
            "adaptive_study",
        ),
        (
            "Browser curated collection",
            "browser-curated-collection.html",
            "mixed_quiz",
        ),
    )
    generated_ids = []
    with sqlite3.connect(database_path) as connection:
        sources = connection.execute(
            """
            SELECT q.question_uid, q.canonical_question_uid
            FROM questions q JOIN quizzes z ON z.id = q.quiz_id
            WHERE z.id IN (?, ?) ORDER BY z.id, q.question_number
            """,
            (int(critical_id), int(companion_id)),
        ).fetchall()
        for title, source_file, generation_kind in generated_rows:
            cursor = connection.execute(
                """
                INSERT INTO quizzes (title, source_file, generation_kind)
                VALUES (?, ?, ?)
                """,
                (title, source_file, generation_kind),
            )
            generated_ids.append(cursor.lastrowid)
        connection.executemany(
            """
            INSERT INTO questions (
                quiz_id, question_number, question_text, question_type,
                question_uid, canonical_question_uid, source_question_uid,
                is_generated_copy
            ) VALUES (?, ?, ?, 'choice', ?, ?, ?, 1)
            """,
            [
                (
                    generated_ids[0],
                    number,
                    f"Which source supports generated-practice item {number}?",
                    "f" * 31 + str(number),
                    source[1],
                    source[0],
                )
                for number, source in enumerate(sources, start=1)
            ],
        )

    registry_path = browser_stack.data_root / "config" / "quizzes.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    for quiz_id, (title, source_file, _generation_kind) in zip(
        generated_ids, generated_rows
    ):
        registry.append({
            "id": quiz_id,
            "title": title,
            "html": source_file,
            "folder": (
                "Uncategorized"
                if _generation_kind == "adaptive_study"
                else "Generated Sessions"
            ),
            "exam_minutes": 90,
        })
    registry_path.write_text(json.dumps(registry, indent=4), encoding="utf-8")

    browser.navigate(f"{base_url}/quizzes/{critical_html}")
    browser.wait_for("quizRecoveryReady === true")
    browser.click(".study-mode-btn")
    browser.click("#choices .choice[data-index='0']")
    recovery_key = browser.evaluate("quizRecoveryController.storageKey")

    browser.navigate(f"{base_url}/library?view=visible&smart=unfinished")
    browser.wait_for(
        "document.body.classList.contains('library-smart-view-ready') && "
        "document.getElementById('librarySmartViewCount').textContent === '1'"
    )
    state = browser.evaluate(
        "(() => {const cards=[...document.querySelectorAll('.library-quiz-card')];"
        "const visible=cards.filter(card=>getComputedStyle(card).display!=='none');"
        "const active=document.querySelector('.library-smart-view-link.active');"
        "return {visibleIds:visible.map(card=>card.dataset.quizId),"
        "active:active?.textContent.trim(),current:active?.getAttribute('aria-current'),"
        "badge:visible[0]?.querySelector('.library-smart-match-badge')?.textContent.trim(),"
        "reason:visible[0]?.querySelector('.library-smart-match-reason')?.textContent.trim(),"
        "reorder:document.querySelectorAll('.library-reorder-controls').length};})()"
    )
    assert state == {
        "visibleIds": [critical_id],
        "active": "Unfinished\n                    1",
        "current": "page",
        "badge": "In progress",
        "reason": "Study session saved in this browser · ready to resume",
        "reorder": 0,
    }

    browser.evaluate(
        "(() => {const input=document.getElementById('librarySearch');"
        "input.value='no such quiz';input.dispatchEvent(new Event('input',{bubbles:true}));"
        "return true;})()"
    )
    browser.wait_for(
        "[...document.querySelectorAll('.library-folder')]"
        ".every(folder=>getComputedStyle(folder).display==='none')"
    )
    browser.evaluate(
        "(() => {const input=document.getElementById('librarySearch');"
        "input.value='';input.dispatchEvent(new Event('input',{bubbles:true}));return true;})()"
    )

    for theme in ("light", "dark", "purple-gold", "maroon-gold"):
        _set_theme(browser, theme)
        browser.navigate(f"{base_url}/library?view=visible&smart=unfinished")
        browser.wait_for(
            "document.body.classList.contains('library-smart-view-ready') && "
            "document.getElementById('librarySmartViewCount').textContent === '1'"
        )
        snapshot = _theme_contrast_snapshot(browser, {
            "smart heading": ".library-smart-views h2",
            "smart helper": ".library-smart-views-heading p",
            "inactive view": ".library-smart-view-link:not(.active)",
            "active view": ".library-smart-view-link.active",
            "active detail": ".library-smart-active > div span",
            "match badge": ".library-smart-match-badge",
            "match reason": ".library-smart-match-reason",
            "reset action": ".library-smart-reset",
        })
        for role, values in snapshot.items():
            assert values["contrast"] >= 4.5, (theme, role, values)

        browser.navigate(
            f"{base_url}/library?view=visible&smart=generated-practice"
        )
        browser.wait_for(
            "document.getElementById('librarySmartViewCount').textContent === '1'"
        )
        generated_state = browser.evaluate(
            "(() => {const cards=[...document.querySelectorAll('.library-quiz-card')];"
            "return {ids:cards.map(card=>card.dataset.quizId),"
            "kinds:cards.map(card=>card.dataset.generationKind),"
            "badge:cards[0]?.querySelector('.library-generation-badge')?.textContent.trim(),"
            "sourceSummary:cards[0]?.querySelector('.library-source-provenance summary')?.textContent.trim(),"
            "sourceTitles:[...cards[0]?.querySelectorAll('.library-source-provenance li')||[]]"
            ".map(item=>item.textContent.trim()),"
            "reason:cards[0]?.querySelector('.library-smart-match-reason')?.textContent.trim(),"
            "mixed:Boolean(document.querySelector('[data-generation-category=\"mixed\"]'))};})()"
        )
        assert generated_state == {
            "ids": [str(generated_ids[0])],
            "kinds": ["adaptive_study"],
            "badge": "Adaptive Study practice",
            "sourceSummary": "Sources: 2 quizzes",
            "sourceTitles": ["Browser Critical Workflow", "Browser Companion"],
            "reason": "Saved practice built from source questions · safe to revisit or hide",
            "mixed": False,
        }
        generated_contrast = _theme_contrast_snapshot(browser, {
            "generated practice badge": ".library-generation-badge",
            "generated practice source": ".library-source-provenance summary",
            "generated practice reason": ".library-smart-match-reason",
        })
        for role, values in generated_contrast.items():
            assert values["contrast"] >= 4.5, (theme, role, values)

        browser.navigate(f"{base_url}/library?view=visible")
        browser.wait_for(
            "document.querySelector('.library-generation-badge-mixed')"
        )
        normal_contrast = _theme_contrast_snapshot(browser, {
            "mixed quiz badge": ".library-generation-badge-mixed",
            "automatic group badge": ".library-system-group-badge",
            "source disclosure": ".library-source-provenance summary",
        })
        for role, values in normal_contrast.items():
            assert values["contrast"] >= 4.5, (theme, role, values)

    assert browser.evaluate(
        "(() => {const summary=document.querySelector('.library-source-provenance summary');"
        "return summary?.tagName==='SUMMARY' && summary.tabIndex===0 && "
        "summary.closest('details')?.open===false;})()"
    ) is True
    browser.click(".library-source-provenance summary")
    browser.wait_for(
        "document.querySelector('.library-source-provenance details').open === true"
    )

    for width, expected_columns in ((1280, 6), (700, 2), (420, 1)):
        browser.set_viewport(width, 900)
        layout = browser.evaluate(
            "(() => {const links=[...document.querySelectorAll('.library-smart-view-link')];"
            "const tops=new Set(links.map(link=>Math.round(link.getBoundingClientRect().top)));"
            "const panel=document.querySelector('.library-smart-views').getBoundingClientRect();"
            "const main=document.querySelector('.dashboard-main').getBoundingClientRect();"
            "const folders=[...document.querySelectorAll('.library-folder')]"
            ".filter(folder=>getComputedStyle(folder).display!=='none');"
            "const footer=document.querySelector('.library-footer-actions').getBoundingClientRect();"
            "return {columns:Math.round(links.length/tops.size),"
            "overflow:document.documentElement.scrollWidth-document.documentElement.clientWidth,"
            "inside:panel.left>=main.left-1&&panel.right<=main.right+1,"
            "footerGap:Math.round(footer.top-folders.at(-1).getBoundingClientRect().bottom),"
            "minWidth:Math.min(...links.map(link=>link.getBoundingClientRect().width))};})()"
        )
        assert layout["columns"] == expected_columns, (width, layout)
        assert layout["overflow"] <= 1, (width, layout)
        assert layout["inside"] is True, (width, layout)
        assert layout["footerGap"] == 18, (width, layout)
        assert layout["minWidth"] >= (250 if expected_columns == 1 else 120), (
            width, layout
        )

    browser.navigate(f"{base_url}/library?view=visible")
    browser.wait_for("document.querySelectorAll('.library-quiz-card').length === 4")
    assert browser.evaluate("document.body.dataset.librarySmartView") == ""
    presentation = browser.evaluate(
        "(() => {const practice=document.querySelector('[data-generation-kind=\"adaptive_study\"]');"
        "const group=practice.closest('.library-folder');return {"
        "practice:practice.querySelector('.library-generation-badge').textContent.trim(),"
        "virtual:group.dataset.generatedPracticeGroup,"
        "groupLabel:group.dataset.folderLabel,"
        "reorder:group.querySelectorAll('.library-reorder-controls').length,"
        "mixed:document.querySelector('[data-generation-kind=\"mixed_quiz\"]')"
        ".querySelector('.library-generation-badge').textContent.trim()};})()"
    )
    assert presentation == {
        "practice": "Adaptive Study practice",
        "virtual": "true",
        "groupLabel": "Generated Practice",
        "reorder": 0,
        "mixed": "Mixed Quiz",
    }
    browser.click("[data-generated-practice-group='true'] .library-folder-toggle-button")
    browser.wait_for(
        "document.querySelector('[data-generated-practice-group=\"true\"]')"
        ".classList.contains('collapsed')"
    )
    browser.evaluate(
        "(() => {const input=document.getElementById('librarySearch');"
        "input.value='renamed browser practice';"
        "input.dispatchEvent(new Event('input',{bubbles:true}));return true;})()"
    )
    browser.wait_for(
        "[...document.querySelectorAll('.library-quiz-card')]"
        ".filter(card=>getComputedStyle(card).display!=='none').length === 1"
    )
    assert browser.evaluate(
        "!document.querySelector('[data-generated-practice-group=\"true\"]')"
        ".classList.contains('collapsed')"
    ) is True
    assert browser.evaluate(
        "[...document.querySelectorAll('.library-quiz-card')]"
        ".find(card=>getComputedStyle(card).display!=='none').dataset.generationKind"
    ) == "adaptive_study"

    browser.evaluate(f"localStorage.removeItem({json.dumps(recovery_key)});true")
    browser.navigate(f"{base_url}/library?view=visible&smart=unfinished")
    browser.wait_for(
        "document.body.classList.contains('library-smart-view-ready') && "
        "document.getElementById('librarySmartEmptyState').hidden === false"
    )


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


def test_library_folder_client_state_reconciles_rename_delete_and_legacy_promotion(browser_stack):
    browser = browser_stack.browser
    base_url = browser_stack.base_url
    storage_key = "dlmsCollapsedLibraryFolders"
    original_folder = "Browser Client State"
    renamed_folder = "Browser Renamed State"
    recased_folder = "bROWSER rENAMED sTATE"
    unrelated_folder = "Browser Unrelated State"

    def folder_lookup(name):
        return (
            "[...document.querySelectorAll('.library-folder')]"
            f".find(folder => folder.dataset.folderName === {json.dumps(name)})"
        )

    def add_folder(name):
        browser.click(".library-add-folder > button")
        assert browser.evaluate(
            "(() => { const input = document.querySelector('.add-folder-form [name=folder]'); "
            f"input.value = {json.dumps(name)}; return input.value; }})()"
        ) == name
        browser.click(".add-folder-form button[type=submit]")
        browser.wait_for(f"Boolean({folder_lookup(name)})")

    def collapsed_state():
        return json.loads(browser.evaluate(
            f"localStorage.getItem({json.dumps(storage_key)}) || '[]'"
        ))

    browser.navigate(f"{base_url}/library")
    browser.evaluate(f"localStorage.removeItem({json.dumps(storage_key)}); true")
    add_folder(original_folder)
    add_folder(unrelated_folder)

    assert browser.evaluate(
        f"(() => {{ {folder_lookup(original_folder)}"
        ".querySelector('.library-folder-toggle-button').click(); return true; })()"
    ) is True
    assert browser.evaluate(
        f"(() => {{ {folder_lookup(unrelated_folder)}"
        ".querySelector('.library-folder-toggle-button').click(); return true; })()"
    ) is True
    browser.wait_for(
        f"{folder_lookup(original_folder)}.classList.contains('collapsed') && "
        f"{folder_lookup(unrelated_folder)}.classList.contains('collapsed')"
    )

    browser.navigate(f"{base_url}/library?client-state-reload=1")
    browser.wait_for(
        f"{folder_lookup(original_folder)}.classList.contains('collapsed') && "
        f"{folder_lookup(unrelated_folder)}.classList.contains('collapsed')"
    )

    assert browser.evaluate(
        f"(() => {{ const form = {folder_lookup(original_folder)}"
        ".querySelector('.rename-folder-form'); "
        f"form.querySelector('[name=new_folder]').value = {json.dumps(renamed_folder)}; "
        "form.requestSubmit(); return true; })()"
    ) is True
    browser.wait_for(f"Boolean({folder_lookup(renamed_folder)})")
    browser.wait_for(f"{folder_lookup(renamed_folder)}.classList.contains('collapsed')")
    state_after_rename = collapsed_state()
    assert renamed_folder in state_after_rename
    assert original_folder not in state_after_rename
    assert unrelated_folder in state_after_rename

    assert browser.evaluate(
        f"(() => {{ const form = {folder_lookup(renamed_folder)}"
        ".querySelector('.rename-folder-form'); "
        f"form.querySelector('[name=new_folder]').value = {json.dumps(recased_folder)}; "
        "form.requestSubmit(); return true; })()"
    ) is True
    browser.wait_for(f"Boolean({folder_lookup(recased_folder)})")
    browser.wait_for(f"{folder_lookup(recased_folder)}.classList.contains('collapsed')")
    state_after_recasing = collapsed_state()
    assert recased_folder in state_after_recasing
    assert sum(
        1 for name in state_after_recasing
        if name.strip().lower() == recased_folder.strip().lower()
    ) == 1

    browser.evaluate(
        f"localStorage.setItem({json.dumps(storage_key)}, "
        f"JSON.stringify([{json.dumps(recased_folder.lower())}, "
        f"{json.dumps(recased_folder.upper())}, {json.dumps(unrelated_folder.lower())}, "
        "'Missing Folder', '  uncategorized  '])); true"
    )
    browser.navigate(f"{base_url}/library?client-state-normalize=1")
    browser.wait_for(f"{folder_lookup(recased_folder)}.classList.contains('collapsed')")
    normalized_state = collapsed_state()
    assert normalized_state == [recased_folder, unrelated_folder, "Uncategorized"]

    # Browser Regression is temporarily assignment-only. Client reconciliation
    # must retain its state and promotion must not introduce another identity.
    portal_path = browser_stack.data_root / "config" / "portal.json"
    portal = json.loads(portal_path.read_text(encoding="utf-8"))
    portal["quiz_folders"] = [
        name for name in portal.get("quiz_folders", [])
        if name.strip().lower() != "browser regression"
    ]
    portal_path.write_text(json.dumps(portal, indent=2), encoding="utf-8")
    browser.evaluate(
        f"localStorage.setItem({json.dumps(storage_key)}, "
        "JSON.stringify(['browser regression', 'BROWSER REGRESSION', "
        f"{json.dumps(recased_folder)}, {json.dumps(unrelated_folder)}, "
        "'uncategorized'])); true"
    )
    browser.navigate(f"{base_url}/library?assignment-only=1")
    browser.wait_for(
        f"{folder_lookup('Browser Regression')}.classList.contains('collapsed')"
    )
    assignment_only_state = collapsed_state()
    assert assignment_only_state.count("Browser Regression") == 1

    browser.click(".library-add-folder > button")
    assert browser.evaluate(
        "(() => { window.__dlmsClientStateMutationPending = true; "
        "const input = document.querySelector('.add-folder-form [name=folder]'); "
        "input.value = 'BROWSER REGRESSION'; return input.value; })()"
    ) == "BROWSER REGRESSION"
    browser.click(".add-folder-form button[type=submit]")
    browser.wait_for(
        "window.__dlmsClientStateMutationPending !== true && "
        f"{folder_lookup('Browser Regression')}.classList.contains('collapsed')"
    )
    promoted_state = collapsed_state()
    assert promoted_state.count("Browser Regression") == 1

    assert browser.evaluate(
        f"(() => {{ const folder = {folder_lookup(recased_folder)}; "
        "window.__dlmsClientStateMutationPending = true; "
        "window.confirm = () => true; "
        "folder.querySelector('.delete-folder-form').requestSubmit(); return true; })()"
    ) is True
    browser.wait_for(
        "window.__dlmsClientStateMutationPending !== true && "
        f"!({folder_lookup(recased_folder)})"
    )
    browser.wait_for(
        f"JSON.parse(localStorage.getItem({json.dumps(storage_key)}) || '[]')"
        f".every(name => name.trim().toLowerCase() !== "
        f"{json.dumps(recased_folder.strip().lower())})"
    )
    state_after_delete = collapsed_state()
    assert all(
        name.strip().lower() != recased_folder.strip().lower()
        for name in state_after_delete
    )
    assert unrelated_folder in state_after_delete
    assert "Browser Regression" in state_after_delete

    assert browser.evaluate(
        f"(() => {{ const folder = {folder_lookup(unrelated_folder)}; "
        "window.__dlmsClientStateMutationPending = true; "
        "window.confirm = () => true; "
        "folder.querySelector('.delete-folder-form').requestSubmit(); return true; })()"
    ) is True
    browser.wait_for(
        "window.__dlmsClientStateMutationPending !== true && "
        f"!({folder_lookup(unrelated_folder)})"
    )
    browser.wait_for(
        f"JSON.parse(localStorage.getItem({json.dumps(storage_key)}) || '[]')"
        f".every(name => name.trim().toLowerCase() !== "
        f"{json.dumps(unrelated_folder.strip().lower())})"
    )
    final_state = collapsed_state()
    assert unrelated_folder not in final_state
    assert "Browser Regression" in final_state
    assert "Uncategorized" in final_state


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
    exam_recovery_key = browser.evaluate("quizRecoveryController.storageKey")
    browser.wait_for("document.querySelectorAll('#choices .choice').length === 2")
    browser.click("#choices .choice[data-index='0']")
    browser.click("#nextBtn")
    browser.wait_for("document.getElementById('qText').textContent.includes('two')")
    browser.click("#choices .choice[data-index='1']")
    browser.evaluate("window.confirm = () => true; true")
    browser.click("#submitBtn")
    browser.wait_for("document.getElementById('result').textContent.includes('saved successfully')")
    browser.wait_for(
        f"localStorage.getItem({json.dumps(exam_recovery_key)}) === null"
    )
    assert "Score: 2 / 2 (100%)" in browser.evaluate("document.getElementById('result').textContent")
    _wait_for_database_value(
        browser_stack.data_root / "results.db",
        "SELECT COUNT(*) FROM attempts",
        attempts_before + 1,
    )

    browser.click("#result button[onclick*='/history']")
    browser.wait_for("location.pathname === '/history'")
    browser.wait_for("document.body.textContent.includes('Browser Critical Workflow')")


def test_quiz_recovery_restores_all_question_types_and_pauses_closed_exam_time(browser_stack):
    browser = browser_stack.browser
    quiz_url = f"{browser_stack.base_url}/quizzes/{browser_stack.metadata['recovery_html']}"
    browser.navigate(quiz_url)
    browser.wait_for("quizRecoveryReady === true && quiz.length === 4")
    identity = "\0".join(["quiz-recovery-v1", "1", "7", "/data/example.json", "5", "abc"])
    expected_fingerprint = "sha256:" + hashlib.sha256(identity.encode("utf-8")).hexdigest()
    assert browser.evaluate(
        "(async () => { const prototype=Object.getPrototypeOf(window.crypto);"
        "const descriptor=Object.getOwnPropertyDescriptor(prototype, 'subtle');"
        "Object.defineProperty(prototype, 'subtle', {configurable:true,get:()=>undefined});"
        "try { return await DLMSQuizRecovery.quizFingerprint({rawQuizText:'abc',quizId:7,"
        "quizFile:'/data/example.json',quizTitle:'Example',examMinutes:5}); }"
        "finally { Object.defineProperty(prototype, 'subtle', descriptor); } })()"
    ) == expected_fingerprint
    browser.click(".exam-mode-btn")
    browser.click("#choices .choice[data-index='1']")
    browser.click("#nextBtn")
    browser.click("#choices .choice[data-index='0']")
    browser.click("#choices .choice[data-index='2']")
    browser.click("#nextBtn")
    assert browser.evaluate("setMatchingInteractionMode('select'); true") is True
    browser.wait_for("document.querySelector('.matching-select') !== null")
    assert browser.evaluate(
        "(() => { const select = document.querySelector('.matching-select');"
        "select.value = String(matchingOptionOrders.q2[0]);"
        "select.dispatchEvent(new Event('change', {bubbles:true})); return true; })()"
    ) is True
    browser.click("#nextBtn")
    browser.wait_for("document.querySelector('.hotspot-image-wrap') !== null")
    browser.click(".hotspot-image-wrap")
    browser.wait_for("document.querySelector('.hotspot-click-marker') !== null")

    storage_key = browser.evaluate("quizRecoveryController.storageKey")
    before = browser.evaluate(f"JSON.parse(localStorage.getItem({json.dumps(storage_key)}))")
    assert before["session"]["mode"] == "Exam"
    assert before["view"]["questionIndex"] == 3
    assert before["answers"]["0"]["selected"] == [1]
    assert before["answers"]["1"]["selected"] == [0, 2]
    assert before["answers"]["2"]["selected"]
    hotspot = before["answers"]["3"]["selected"]
    assert 0 <= hotspot["x"] <= 1
    assert 0 <= hotspot["y"] <= 1
    assert before["matchingVariants"]["2"]["optionOrder"] is not None
    serialized = json.dumps(before)
    assert "Recovery single-choice question?" not in serialized
    assert '"correct"' not in serialized
    assert '"score"' not in serialized

    browser.navigate(quiz_url)
    browser.wait_for("document.querySelector('.quiz-recovery-resume') !== null")
    assert "Question 4 of 4" in browser.evaluate("document.querySelector('.quiz-recovery-panel p').textContent")
    saved_remaining = browser.evaluate(
        f"JSON.parse(localStorage.getItem({json.dumps(storage_key)})).timer.remainingSeconds"
    )
    time.sleep(1.1)
    assert browser.evaluate(
        f"JSON.parse(localStorage.getItem({json.dumps(storage_key)})).timer.remainingSeconds"
    ) == saved_remaining
    browser.click(".quiz-recovery-resume")
    browser.wait_for("index === 3 && document.querySelector('.hotspot-click-marker') !== null")
    browser.evaluate("prev(); true")
    browser.wait_for("index === 2 && document.querySelector('.matching-select') !== null")
    restored = browser.evaluate(
        "({mode:matchingInteractionMode, answer:userAnswers.q2,"
        "variant:quiz[2]._matching_variant, order:matchingOptionOrders.q2})"
    )
    assert restored["mode"] == "select"
    assert restored["answer"] == before["answers"]["2"]["selected"]
    assert restored["variant"]["sourcePairIndexes"] == before["matchingVariants"]["2"]["sourcePairIndexes"]
    assert restored["variant"]["direction"] == before["matchingVariants"]["2"]["direction"]
    assert restored["order"] == before["matchingVariants"]["2"]["optionOrder"]
    browser.evaluate("prev(); true")
    browser.wait_for("index === 1")
    assert browser.evaluate("userAnswers.q1") == [0, 2]
    assert browser.evaluate(
        "[...document.querySelectorAll('#choices .choice')].filter(button => button.getAttribute('aria-pressed') === 'true').map(button => Number(button.dataset.index))"
    ) == [0, 2]
    browser.evaluate("pauseExam(); true")
    browser.wait_for("paused === true && document.getElementById('pauseOverlay').classList.contains('show')")
    browser.navigate(quiz_url)
    browser.wait_for("document.querySelector('.quiz-recovery-resume') !== null")
    browser.click(".quiz-recovery-resume")
    browser.wait_for("paused === true && document.getElementById('pauseOverlay').classList.contains('show')")
    browser.evaluate("resumeExam(); true")
    browser.wait_for("paused === false && !document.getElementById('pauseOverlay').classList.contains('show')")


def test_quiz_recovery_preserves_failed_study_event_identity_until_explicit_retry(browser_stack):
    browser = browser_stack.browser
    quiz_id = browser_stack.metadata["critical_id"]
    quiz_url = f"{browser_stack.base_url}/quizzes/{browser_stack.metadata['critical_html']}"
    before_count = _database_value(
        browser_stack.data_root / "results.db",
        "SELECT COUNT(*) FROM learning_events WHERE quiz_id = ? AND event_type = 'study_answer'",
        (quiz_id,),
    )
    browser.navigate(quiz_url)
    browser.wait_for("quizRecoveryReady === true")
    assert browser.evaluate(
        "window.__recoveryFetch = window.fetch.bind(window);"
        "window.fetch = (...args) => String(args[0]).includes('/api/learning-events/study-response')"
        " ? Promise.reject(new Error('simulated lost acknowledgement')) : window.__recoveryFetch(...args); true"
    ) is True
    browser.click(".study-mode-btn")
    browser.click("#studyAnkiBtn")
    browser.click("#choices .choice[data-index='0']")
    browser.wait_for("document.querySelector('.study-learning-save-retry:not([hidden])') !== null")
    storage_key = browser.evaluate("quizRecoveryController.storageKey")
    saved = browser.evaluate(f"JSON.parse(localStorage.getItem({json.dumps(storage_key)}))")
    event = saved["unacknowledgedStudyEvents"][0]
    session_id = saved["learningSessionId"]
    assert _database_value(
        browser_stack.data_root / "results.db",
        "SELECT COUNT(*) FROM learning_events WHERE quiz_id = ? AND event_type = 'study_answer'",
        (quiz_id,),
    ) == before_count

    browser.navigate(quiz_url)
    browser.wait_for("document.querySelector('.quiz-recovery-resume') !== null")
    browser.click(".quiz-recovery-resume")
    browser.wait_for("document.querySelector('.study-learning-save-retry:not([hidden])') !== null")
    browser.wait_for("document.querySelector('#choices .correct-choice') !== null")
    assert browser.evaluate("studyAnkiSelections.has(0)") is True
    assert browser.evaluate("learningSessionId") == session_id
    assert _database_value(
        browser_stack.data_root / "results.db",
        "SELECT COUNT(*) FROM learning_events WHERE quiz_id = ? AND event_type = 'study_answer'",
        (quiz_id,),
    ) == before_count
    browser.click(".study-learning-save-retry")
    _wait_for_database_value(
        browser_stack.data_root / "results.db",
        f"SELECT COUNT(*) FROM learning_events WHERE quiz_id = {int(quiz_id)} AND event_type = 'study_answer'",
        before_count + 1,
    )
    assert _database_value(
        browser_stack.data_root / "results.db",
        "SELECT COUNT(*) FROM learning_events WHERE attempt_id = ?",
        (event["eventId"],),
    ) == 1
    browser.wait_for(
        f"JSON.parse(localStorage.getItem({json.dumps(storage_key)})).unacknowledgedStudyEvents.length === 0"
    )


def test_study_recovery_clears_only_after_every_answer_is_saved(browser_stack):
    browser = browser_stack.browser
    quiz_id = browser_stack.metadata["critical_id"]
    quiz_url = f"{browser_stack.base_url}/quizzes/{browser_stack.metadata['critical_html']}"
    browser.navigate(quiz_url)
    browser.wait_for("quizRecoveryReady === true && quiz.length === 2")
    browser.click(".study-mode-btn")
    recovery_key = browser.evaluate("quizRecoveryController.storageKey")

    browser.click("#choices .choice[data-index='0']")
    browser.wait_for("studyLearningEventSaves.size === 0")
    browser.click("#nextBtn")
    browser.wait_for("index === 1")
    assert browser.evaluate("document.getElementById('finishReviewBtn') === null") is True
    assert browser.evaluate(
        f"localStorage.getItem({json.dumps(recovery_key)}) !== null"
    ) is True

    before = _database_value(
        browser_stack.data_root / "results.db",
        "SELECT COUNT(*) FROM learning_events WHERE quiz_id = ? AND event_type = 'study_answer'",
        (quiz_id,),
    )
    browser.click("#choices .choice[data-index='1']")
    _wait_for_database_value(
        browser_stack.data_root / "results.db",
        f"SELECT COUNT(*) FROM learning_events WHERE quiz_id = {int(quiz_id)} AND event_type = 'study_answer'",
        before + 1,
    )
    browser.wait_for(
        f"localStorage.getItem({json.dumps(recovery_key)}) === null && "
        "quizRecoveryController.ownsState === false"
    )

    browser.navigate(f"{browser_stack.base_url}/")
    browser.wait_for("document.getElementById('dailyReviewCount').textContent !== 'Loading…'")
    assert browser.evaluate(
        "[...document.querySelectorAll('.daily-review-unfinished')]"
        ".every(item => !item.textContent.includes('Browser Critical Workflow'))"
    ) is True


def test_adaptive_study_completion_survives_late_partial_multiselect_save(browser_stack):
    browser = browser_stack.browser
    quiz_id = browser_stack.metadata["critical_id"]
    quiz_url = f"{browser_stack.base_url}/quizzes/{browser_stack.metadata['critical_html']}"
    registry_path = browser_stack.data_root / "config" / "quizzes.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    entry = next(item for item in registry if item["id"] == quiz_id)
    entry["folder"] = "Uncategorized"
    registry_path.write_text(json.dumps(registry), encoding="utf-8")
    json_path = browser_stack.data_root / "data" / Path(entry["html"]).with_suffix(".json").name
    questions = json.loads(json_path.read_text(encoding="utf-8"))
    questions[1]["choices"][0]["is_correct"] = True
    questions[1]["correct"] = ["A", "B"]
    json_path.write_text(json.dumps(questions), encoding="utf-8")
    with sqlite3.connect(browser_stack.data_root / "results.db") as connection:
        connection.execute(
            "UPDATE quizzes SET generation_kind = 'adaptive_study' WHERE id = ?", (quiz_id,),
        )
        connection.execute(
            "UPDATE choices SET is_correct = 1 WHERE question_id = "
            "(SELECT id FROM questions WHERE quiz_id = ? AND question_number = 2) AND label = 'A'",
            (quiz_id,),
        )

    browser.navigate(quiz_url)
    browser.wait_for("quizRecoveryReady === true && generatedPracticeStatus?.is_transient === true")
    browser.click(".study-mode-btn")
    recovery_key = browser.evaluate("quizRecoveryController.storageKey")
    browser.click("#choices .choice[data-index='0']")
    browser.wait_for("studyLearningEventSaves.size === 0")
    browser.click("#nextBtn")
    browser.wait_for("index === 1")
    browser.click("#choices .choice[data-index='0']")
    browser.wait_for("studyLearningEventSaves.size === 0")
    assert browser.evaluate(f"localStorage.getItem({json.dumps(recovery_key)}) !== null") is True
    assert browser.evaluate("generatedPracticeStatus.completed") is False
    browser.click("#finishReviewBtn")
    browser.wait_for(
        "document.querySelector('.study-learning-save-message')?.textContent.includes('Question 2 needs a complete answer')"
    )
    assert browser.evaluate(f"localStorage.getItem({json.dumps(recovery_key)}) !== null") is True
    browser.evaluate(
        "(() => { const original = window.fetch.bind(window);"
        "window.fetch = (...args) => {"
        "if (String(args[0]).includes('/api/learning-events/study-response')"
        " && JSON.parse(args[1].body).questionOrdinal === 2"
        " && JSON.parse(args[1].body).selected.length === 0) {"
        "return new Promise(resolve => { window.releasePartialStudySave = () => resolve(original(...args)); });"
        "} return original(...args); }; return true; })()"
    )
    browser.click("#choices .choice[data-index='0']")
    browser.wait_for("typeof window.releasePartialStudySave === 'function'")
    assert browser.evaluate(f"localStorage.getItem({json.dumps(recovery_key)}) !== null") is True
    browser.click("#choices .choice[data-index='0']")
    browser.click("#choices .choice[data-index='1']")
    browser.wait_for(
        "studyLearningEventSaves.size === 1 && "
        "[...studyLearningEventSaves.values()][0].payload.selected.length === 0"
    )
    assert browser.evaluate(f"localStorage.getItem({json.dumps(recovery_key)}) !== null") is True
    assert browser.evaluate("generatedPracticeStatus.completed") is False
    browser.evaluate("window.releasePartialStudySave(); true")
    browser.wait_for("studyLearningEventSaves.size === 0")
    assert browser.evaluate("generatedPracticeStatus.completed") is False
    assert browser.evaluate(f"localStorage.getItem({json.dumps(recovery_key)}) !== null") is True
    browser.navigate(f"{browser_stack.base_url}/library")
    browser.wait_for("document.querySelector('[data-generated-practice-group=true]') !== null")
    assert "Browser Critical Workflow" in browser.evaluate(
        "document.querySelector('[data-generated-practice-group=true]').textContent"
    )
    browser.navigate(f"{browser_stack.base_url}/")
    browser.wait_for(
        "document.querySelector('.daily-review-unfinished')?.textContent.includes('Browser Critical Workflow')"
    )
    browser.navigate(quiz_url)
    browser.wait_for("document.querySelector('.quiz-recovery-resume') !== null")
    browser.click(".quiz-recovery-resume")
    browser.wait_for("index === 1 && document.getElementById('finishReviewBtn')?.style.display !== 'none'")
    assert browser.evaluate(f"localStorage.getItem({json.dumps(recovery_key)}) !== null") is True
    browser.click("#finishReviewBtn")
    browser.wait_for(f"generatedPracticeStatus.completed === true && localStorage.getItem({json.dumps(recovery_key)}) === null")
    assert browser.evaluate(
        "document.querySelector('.study-learning-save-message').textContent.includes('Review completed')"
    ) is True
    browser.navigate(f"{browser_stack.base_url}/")
    browser.wait_for("document.getElementById('dailyReviewCount').textContent !== 'Loading…'")
    assert browser.evaluate(
        "[...document.querySelectorAll('.daily-review-unfinished')]"
        ".every(item => !item.textContent.includes('Browser Critical Workflow'))"
    ) is True


def test_generated_finish_review_waits_for_save_and_requires_earlier_answers(browser_stack):
    browser = browser_stack.browser
    quiz_id = browser_stack.metadata["critical_id"]
    quiz_url = f"{browser_stack.base_url}/quizzes/{browser_stack.metadata['critical_html']}"
    with sqlite3.connect(browser_stack.data_root / "results.db") as connection:
        connection.execute(
            "UPDATE quizzes SET generation_kind = 'adaptive_study' WHERE id = ?", (quiz_id,),
        )
    browser.navigate(quiz_url)
    browser.wait_for("quizRecoveryReady === true && generatedPracticeStatus?.is_transient === true")
    browser.click(".study-mode-btn")
    recovery_key = browser.evaluate("quizRecoveryController.storageKey")
    browser.click("#nextBtn")
    browser.wait_for("index === 1 && document.getElementById('finishReviewBtn') !== null")
    browser.set_viewport(420, 900)
    assert browser.evaluate(
        "(() => { const button=document.getElementById('finishReviewBtn');"
        "button.focus(); return document.activeElement===button && button.tagName==='BUTTON'"
        "&& button.type==='button' && document.documentElement.scrollWidth<=innerWidth; })()"
    ) is True
    browser.evaluate(
        "(() => { const original = window.fetch.bind(window);"
        "window.fetch = (...args) => {"
        "if (String(args[0]).includes('/api/learning-events/study-response')) {"
        "window.fetch = original;"
        "return new Promise(resolve => { window.releaseFinalStudySave = () => resolve(original(...args)); });"
        "} return original(...args); }; return true; })()"
    )
    browser.click("#choices .choice[data-index='1']")
    browser.click("#finishReviewBtn")
    browser.wait_for(
        "studyCompletionInProgress === true && "
        "document.querySelector('.study-learning-save-message')?.textContent.includes('Waiting for learning progress')"
    )
    assert browser.evaluate(
        f"document.getElementById('finishReviewBtn').disabled && localStorage.getItem({json.dumps(recovery_key)}) !== null"
    ) is True
    browser.evaluate("window.releaseFinalStudySave(); true")
    browser.wait_for(
        "studyCompletionInProgress === false && "
        "document.querySelector('.study-learning-save-message')?.textContent.includes('Question 1 needs a complete answer')"
    )
    assert browser.evaluate("generatedPracticeStatus.completed") is False
    assert browser.evaluate(f"localStorage.getItem({json.dumps(recovery_key)}) !== null") is True
    browser.click("#prevBtn")
    browser.click("#choices .choice[data-index='0']")
    browser.wait_for("studyLearningEventSaves.size === 0")
    browser.click("#nextBtn")
    browser.click("#finishReviewBtn")
    browser.wait_for(
        f"generatedPracticeStatus.completed === true && localStorage.getItem({json.dumps(recovery_key)}) === null"
    )


def test_generated_finish_review_retries_failed_browser_checkpoint_clear(browser_stack):
    browser = browser_stack.browser
    quiz_id = browser_stack.metadata["critical_id"]
    with sqlite3.connect(browser_stack.data_root / "results.db") as connection:
        connection.execute(
            "UPDATE quizzes SET generation_kind = 'smart_review' WHERE id = ?", (quiz_id,),
        )
    quiz_url = f"{browser_stack.base_url}/quizzes/{browser_stack.metadata['critical_html']}"
    browser.navigate(quiz_url)
    browser.wait_for("quizRecoveryReady === true && generatedPracticeStatus?.is_transient === true")
    browser.click(".study-mode-btn")
    recovery_key = browser.evaluate("quizRecoveryController.storageKey")
    browser.click("#choices .choice[data-index='0']")
    browser.wait_for("studyLearningEventSaves.size === 0")
    browser.click("#nextBtn")
    browser.click("#choices .choice[data-index='1']")
    browser.wait_for("studyLearningEventSaves.size === 0")
    browser.evaluate(
        "(() => {const original=Storage.prototype.removeItem;let fail=true;"
        f"const recoveryKey={json.dumps(recovery_key)};"
        "Storage.prototype.removeItem=function(key){"
        "if(fail&&key===recoveryKey){fail=false;throw new Error('blocked storage');}"
        "return original.call(this,key);};return true;})()"
    )
    browser.click("#finishReviewBtn")
    browser.wait_for(
        "studyCompletionFailed === true && "
        "document.querySelector('.study-learning-save-message')?.textContent.includes('could not clear its resume point')"
    )
    assert browser.evaluate(
        f"quizRecoveryController.ownsState && localStorage.getItem({json.dumps(recovery_key)}) !== null"
    ) is True
    browser.click("#finishReviewBtn")
    browser.wait_for(
        f"studyCompletionFailed === false && localStorage.getItem({json.dumps(recovery_key)}) === null"
    )


def test_generated_practice_study_completion_retry_library_and_retake(browser_stack):
    browser = browser_stack.browser
    quiz_id = browser_stack.metadata["critical_id"]
    quiz_url = f"{browser_stack.base_url}/quizzes/{browser_stack.metadata['critical_html']}"
    with sqlite3.connect(browser_stack.data_root / "results.db") as connection:
        connection.execute(
            "UPDATE quizzes SET generation_kind = 'native_spaced_review' WHERE id = ?",
            (quiz_id,),
        )
    registry_path = browser_stack.data_root / "config" / "quizzes.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    next(item for item in registry if item["id"] == quiz_id)["folder"] = "Uncategorized"
    registry_path.write_text(json.dumps(registry), encoding="utf-8")

    browser.navigate(f"{browser_stack.base_url}/library")
    browser.wait_for("document.querySelector('[data-generated-practice-group=true]') !== null")
    assert "Browser Critical Workflow" in browser.evaluate(
        "document.querySelector('[data-generated-practice-group=true]').textContent"
    )

    browser.navigate(quiz_url)
    browser.wait_for("quizRecoveryReady === true && generatedPracticeStatus?.is_transient === true")
    assert browser.evaluate(
        "(() => { const original = window.fetch.bind(window); let failCompletion = true, failStudy = true;"
        "window.fetch = (...args) => { const target = String(args[0]);"
        "if (failStudy && target.includes('/api/learning-events/study-response')"
        " && JSON.parse(args[1].body).questionOrdinal === 2) {"
        "failStudy = false; return Promise.resolve(new Response(JSON.stringify({error:'forced Study save failure'}),"
        "{status:503,headers:{'Content-Type':'application/json'}})); }"
        "if (failCompletion && target.includes('/api/generated-practice/complete')) {"
        "failCompletion = false; return Promise.resolve(new Response(JSON.stringify({error:'forced completion failure'}),"
        "{status:503,headers:{'Content-Type':'application/json'}})); } return original(...args); }; return true; })()"
    ) is True
    browser.click(".study-mode-btn")
    recovery_key = browser.evaluate("quizRecoveryController.storageKey")
    browser.click("#choices .choice[data-index='0']")
    browser.wait_for("studyLearningEventSaves.size === 0")
    browser.click("#nextBtn")
    browser.click("#choices .choice[data-index='1']")
    browser.wait_for("document.querySelector('.study-learning-save-message')?.textContent === 'Learning progress was not saved.'")
    browser.click("#finishReviewBtn")
    browser.wait_for("document.querySelector('.study-learning-save-message')?.textContent.includes('Retry the failed Study save')")
    assert browser.evaluate(f"localStorage.getItem({json.dumps(recovery_key)}) !== null") is True
    with registry_path.open(encoding="utf-8") as handle:
        assert "generated_practice_completion" not in next(item for item in json.load(handle) if item["id"] == quiz_id)
    browser.click(".study-learning-save-retry")
    browser.wait_for("studyLearningEventSaves.size === 0")
    assert browser.evaluate("generatedPracticeStatus.completed") is False
    browser.click("#finishReviewBtn")
    browser.wait_for("studyCompletionFailed === true")
    assert browser.evaluate(f"localStorage.getItem({json.dumps(recovery_key)}) !== null") is True
    assert browser.evaluate("document.querySelector('.study-learning-save-message').textContent") == (
        "forced completion failure"
    )
    browser.click("#finishReviewBtn")
    browser.wait_for(
        f"generatedPracticeStatus.completed === true && localStorage.getItem({json.dumps(recovery_key)}) === null"
    )
    with (browser_stack.data_root / "config" / "quizzes.json").open(encoding="utf-8") as handle:
        registry = json.load(handle)
    assert next(item for item in registry if item["id"] == quiz_id)["generated_practice_completion"]["mode"] == "Study"

    browser.navigate(f"{browser_stack.base_url}/library")
    browser.wait_for("document.querySelector('.library-folder-completed-practice') !== null")
    assert browser.evaluate(
        "document.querySelector('[data-generated-practice-group=true]') === null && "
        "document.querySelector('.library-folder-completed-practice .library-quiz-card') !== null"
    ) is True
    browser.evaluate(
        "(() => { const input=document.getElementById('librarySearch');"
        "input.value='Browser Critical Workflow'; input.dispatchEvent(new Event('input',{bubbles:true})); return true; })()"
    )
    browser.wait_for(
        "document.querySelector('.library-folder-completed-practice .library-folder-toggle-button').getAttribute('aria-expanded') === 'true'"
    )
    browser.evaluate(
        "(() => { const input=document.getElementById('librarySearch');"
        "input.value=''; input.dispatchEvent(new Event('input',{bubbles:true})); return true; })()"
    )
    browser.wait_for(
        "document.querySelector('.library-folder-completed-practice .library-folder-toggle-button').getAttribute('aria-expanded') === 'false'"
    )
    for theme in ("light", "dark", "purple-gold", "maroon-gold"):
        _set_theme(browser, theme)
        browser.navigate(f"{browser_stack.base_url}/library")
        browser.wait_for("document.querySelector('.library-folder-completed-practice') !== null")
        contrast = _theme_contrast_snapshot(browser, {
            "completed status": ".library-completed-badge",
            "completed section": ".library-folder-completed-practice h2",
        })
        assert all(item["contrast"] >= 4.5 for item in contrast.values()), (theme, contrast)
        for width in (1440, 1024, 760, 420):
            browser.set_viewport(width, 1000)
            assert browser.evaluate(
                "document.documentElement.scrollWidth <= window.innerWidth + 1 && "
                "document.querySelector('.library-folder-completed-practice button').getAttribute('aria-expanded') === 'false'"
            ) is True, (theme, width)
    assert browser.evaluate(
        "(() => { const button=document.querySelector('.library-folder-completed-practice .library-folder-toggle-button');"
        "button.focus(); return document.activeElement===button && button.tagName==='BUTTON' && button.type==='button'; })()"
    ) is True
    browser.click(".library-folder-completed-practice .library-folder-toggle-button")
    assert browser.evaluate(
        "document.querySelector('.library-folder-completed-practice .library-folder-toggle-button').getAttribute('aria-expanded')"
    ) == "true"
    browser.navigate(quiz_url)
    browser.wait_for("quizRecoveryReady === true")
    browser.click(".study-mode-btn")
    browser.click("#choices .choice[data-index='0']")
    browser.wait_for("studyLearningEventSaves.size === 0")
    assert browser.evaluate("quizRecoveryController.ownsState") is True
    browser.click("#nextBtn")
    browser.click("#choices .choice[data-index='1']")
    browser.wait_for("studyLearningEventSaves.size === 0")
    assert browser.evaluate("quizRecoveryController.ownsState") is True
    browser.navigate(f"{browser_stack.base_url}/")
    browser.wait_for("document.getElementById('dailyReviewCount').textContent !== 'Loading…'")
    browser.wait_for(
        "document.querySelector('.daily-review-unfinished')?.textContent.includes('Browser Critical Workflow')"
    )
    assert "This browser" in browser.evaluate(
        "document.querySelector('.daily-review-unfinished').textContent"
    )
    browser.navigate(quiz_url)
    browser.wait_for("document.querySelector('.quiz-recovery-resume') !== null")
    browser.click(".quiz-recovery-resume")
    browser.wait_for("index === 1 && generatedPracticeStatus.completed === true")
    assert browser.evaluate(f"localStorage.getItem({json.dumps(recovery_key)}) !== null") is True
    browser.click("#finishReviewBtn")
    browser.wait_for(f"localStorage.getItem({json.dumps(recovery_key)}) === null")


def test_generated_practice_exam_completion_requires_saved_attempt(browser_stack):
    browser = browser_stack.browser
    quiz_id = browser_stack.metadata["critical_id"]
    attempts_before = _database_value(
        browser_stack.data_root / "results.db",
        "SELECT COUNT(*) FROM attempts WHERE quiz_id = ? AND mode = 'Exam'",
        (quiz_id,),
    )
    with sqlite3.connect(browser_stack.data_root / "results.db") as connection:
        connection.execute(
            "UPDATE quizzes SET generation_kind = 'smart_review' WHERE id = ?",
            (quiz_id,),
        )
    quiz_url = f"{browser_stack.base_url}/quizzes/{browser_stack.metadata['critical_html']}"
    browser.navigate(quiz_url)
    browser.wait_for("quizRecoveryReady === true && generatedPracticeStatus?.is_transient === true")
    browser.click(".exam-mode-btn")
    browser.click("#choices .choice[data-index='0']")
    browser.click("#nextBtn")
    browser.click("#choices .choice[data-index='1']")
    assert browser.evaluate("document.getElementById('finishReviewBtn') === null") is True
    browser.evaluate(
        "(() => { const original=window.fetch.bind(window); let fail=true;"
        "window.fetch=(...args)=>{if(fail&&String(args[0]).includes('/record_attempt')){"
        "fail=false;return Promise.resolve(new Response(JSON.stringify({error:'forced attempt failure'}),"
        "{status:503,headers:{'Content-Type':'application/json'}}));}return original(...args);};"
        "window.confirm=()=>true;return true;})()"
    )
    browser.click("#submitBtn")
    browser.wait_for("document.getElementById('result').textContent.includes('was not saved')")
    registry_path = browser_stack.data_root / "config" / "quizzes.json"
    with registry_path.open(encoding="utf-8") as handle:
        assert "generated_practice_completion" not in next(item for item in json.load(handle) if item["id"] == quiz_id)
    browser.click("#result button[onclick='retryExamAttemptSave()']")
    browser.wait_for("generatedPracticeStatus.completed === true")
    with registry_path.open(encoding="utf-8") as handle:
        marker = next(item for item in json.load(handle) if item["id"] == quiz_id)["generated_practice_completion"]
    assert marker["mode"] == "Exam"
    assert _database_value(
        browser_stack.data_root / "results.db",
        "SELECT COUNT(*) FROM attempts WHERE quiz_id = ? AND mode = 'Exam'",
        (quiz_id,),
    ) == attempts_before + 1


def test_final_study_answer_save_failure_keeps_recovery(browser_stack):
    browser = browser_stack.browser
    quiz_url = f"{browser_stack.base_url}/quizzes/{browser_stack.metadata['critical_html']}"
    browser.navigate(quiz_url)
    browser.wait_for("quizRecoveryReady === true && quiz.length === 2")
    browser.click(".study-mode-btn")
    recovery_key = browser.evaluate("quizRecoveryController.storageKey")
    browser.click("#choices .choice[data-index='0']")
    browser.wait_for("studyLearningEventSaves.size === 0")
    browser.click("#nextBtn")
    browser.wait_for("index === 1")
    assert browser.evaluate(
        "window.__recoveryFetch = window.fetch.bind(window);"
        "window.fetch = (...args) => String(args[0]).includes('/api/learning-events/study-response')"
        " ? Promise.reject(new Error('simulated final-answer failure')) : window.__recoveryFetch(...args); true"
    ) is True
    browser.click("#choices .choice[data-index='1']")
    browser.wait_for("document.querySelector('.study-learning-save-retry:not([hidden])') !== null")
    saved = browser.evaluate(
        f"JSON.parse(localStorage.getItem({json.dumps(recovery_key)}))"
    )
    assert saved["view"]["questionIndex"] == 1
    assert len(saved["unacknowledgedStudyEvents"]) == 1

    browser.navigate(f"{browser_stack.base_url}/")
    browser.wait_for(
        "document.querySelector('.daily-review-unfinished')?.textContent.includes('Browser Critical Workflow')"
    )
    recovery_copy = browser.evaluate(
        "document.querySelector('.daily-review-unfinished').textContent"
    )
    assert "This browser" in recovery_copy


def test_quiz_recovery_resends_one_exact_exam_attempt_after_lost_acknowledgement(browser_stack):
    browser = browser_stack.browser
    quiz_id = browser_stack.metadata["critical_id"]
    quiz_url = f"{browser_stack.base_url}/quizzes/{browser_stack.metadata['critical_html']}"
    attempts_before = _database_value(
        browser_stack.data_root / "results.db", "SELECT COUNT(*) FROM attempts WHERE quiz_id = ?", (quiz_id,)
    )
    missed_before = _database_value(
        browser_stack.data_root / "results.db",
        "SELECT COUNT(*) FROM missed_questions WHERE attempt_id IN (SELECT id FROM attempts WHERE quiz_id = ?)",
        (quiz_id,),
    )
    browser.navigate(quiz_url)
    browser.wait_for("quizRecoveryReady === true")
    assert browser.evaluate(
        "window.__recoveryFetch = window.fetch.bind(window);"
        "window.fetch = async (...args) => { const response = await window.__recoveryFetch(...args);"
        "if (String(args[0]).includes('/record_attempt')) throw new Error('simulated lost acknowledgement');"
        "return response; }; true"
    ) is True
    browser.click(".exam-mode-btn")
    browser.click("#choices .choice[data-index='1']")
    browser.click("#nextBtn")
    browser.click("#choices .choice[data-index='1']")
    browser.evaluate("window.confirm = () => true; true")
    browser.click("#submitBtn")
    browser.wait_for("document.getElementById('result').textContent.includes('was not saved')")
    storage_key = browser.evaluate("quizRecoveryController.storageKey")
    pending = browser.evaluate(f"JSON.parse(localStorage.getItem({json.dumps(storage_key)})).pendingAttempt")
    original_payload = browser.evaluate("pendingExamAttempt.payload")
    attempt_id = pending["attemptId"]
    _wait_for_database_value(
        browser_stack.data_root / "results.db",
        f"SELECT COUNT(*) FROM attempts WHERE quiz_id = {int(quiz_id)}",
        attempts_before + 1,
    )

    browser.navigate(quiz_url)
    browser.wait_for("document.querySelector('.quiz-recovery-resume')?.textContent.includes('Finish Saving')")
    assert browser.evaluate(
        "window.__recoveryFetch = window.fetch.bind(window);"
        "window.fetch = (...args) => {"
        "if (String(args[0]).includes('/record_attempt')) window.__recoveryRetryPayload = args[1].body;"
        "return window.__recoveryFetch(...args).then(async response=>{"
        "if(String(args[0]).includes('/record_attempt'))"
        "window.__recoveryRetryResponse=await response.clone().json();return response}); }; true"
    ) is True
    browser.click(".quiz-recovery-resume")
    browser.wait_for("document.getElementById('result').textContent.includes('saved successfully')")
    assert browser.evaluate("JSON.parse(window.__recoveryRetryPayload)") == original_payload
    assert browser.evaluate("window.__recoveryRetryResponse.already_recorded") is True
    assert _database_value(
        browser_stack.data_root / "results.db", "SELECT COUNT(*) FROM attempts WHERE id = ?", (attempt_id,)
    ) == 1
    assert _database_value(
        browser_stack.data_root / "results.db",
        "SELECT COUNT(*) FROM learning_events WHERE attempt_id = ? AND event_type = 'exam_answer'",
        (attempt_id,),
    ) == 2
    assert _database_value(
        browser_stack.data_root / "results.db", "SELECT COUNT(*) FROM attempts WHERE quiz_id = ?", (quiz_id,)
    ) == attempts_before + 1
    assert _database_value(
        browser_stack.data_root / "results.db",
        "SELECT COUNT(*) FROM missed_questions WHERE attempt_id IN (SELECT id FROM attempts WHERE quiz_id = ?)",
        (quiz_id,),
    ) == missed_before + 1
    assert browser.evaluate(f"localStorage.getItem({json.dumps(storage_key)})") is None


def test_quiz_recovery_rejects_bad_state_and_enforces_single_writer(browser_stack):
    browser = browser_stack.browser
    quiz_url = f"{browser_stack.base_url}/quizzes/{browser_stack.metadata['critical_html']}"
    browser.navigate(quiz_url)
    browser.wait_for("quizRecoveryReady === true")
    browser.click(".exam-mode-btn")
    browser.click("#choices .choice[data-index='0']")
    storage_key = browser.evaluate("quizRecoveryController.storageKey")
    first_context = browser.context
    created = browser.command("browsingContext.create", {"type": "tab"})
    second_context = created["context"]
    try:
        browser.context = second_context
        browser.navigate(quiz_url)
        browser.wait_for("document.querySelector('.quiz-recovery-resume') !== null")
        assert browser.evaluate("quizRecoveryController.ownsState") is False
        browser.click(".quiz-recovery-resume")
        browser.wait_for("quizRecoveryController.ownsState === true")
        browser.context = first_context
        browser.wait_for("quizRecoveryController.ownsState === false")
        assert "another tab" in browser.evaluate("document.getElementById('quizRecoveryNotice').textContent")
    finally:
        _close_context_after_pagehide(browser, second_context, first_context)

    assert browser.evaluate(
        f"(() => {{ const saved=JSON.parse(localStorage.getItem({json.dumps(storage_key)}));"
        "saved.schemaVersion=999; localStorage.setItem("
        f"{json.dumps(storage_key)}, JSON.stringify(saved)); return true; }})()"
    ) is True
    browser.navigate(quiz_url)
    browser.wait_for("quizRecoveryReady === true")
    assert browser.evaluate("document.querySelector('.quiz-recovery-panel')") is None
    assert browser.evaluate(f"localStorage.getItem({json.dumps(storage_key)})") is None

    assert browser.evaluate(
        f"localStorage.setItem({json.dumps(storage_key)}, '{{malformed'); true"
    ) is True
    browser.navigate(quiz_url)
    browser.wait_for("quizRecoveryReady === true")
    assert browser.evaluate(f"localStorage.getItem({json.dumps(storage_key)})") is None

    assert browser.evaluate(
        f"localStorage.setItem({json.dumps(storage_key)}, 'x'.repeat(524289)); true"
    ) is True
    browser.navigate(quiz_url)
    browser.wait_for("quizRecoveryReady === true")
    assert browser.evaluate(f"localStorage.getItem({json.dumps(storage_key)})") is None

    browser.click(".exam-mode-btn")
    browser.click("#choices .choice[data-index='0']")
    browser.navigate(f"{browser_stack.base_url}/library")
    assert browser.evaluate(
        f"(() => {{ const saved=JSON.parse(localStorage.getItem({json.dumps(storage_key)}));"
        "saved.quiz.fingerprint='sha256:' + '0'.repeat(64); localStorage.setItem("
        f"{json.dumps(storage_key)}, JSON.stringify(saved)); return true; }})()"
    ) is True
    browser.navigate(quiz_url)
    browser.wait_for("quizRecoveryReady === true")
    assert browser.evaluate("document.querySelector('.quiz-recovery-panel')") is None
    assert browser.evaluate(f"localStorage.getItem({json.dumps(storage_key)})") is None

    browser.click(".exam-mode-btn")
    browser.navigate(f"{browser_stack.base_url}/library")
    assert browser.evaluate(
        f"(() => {{ const saved=JSON.parse(localStorage.getItem({json.dumps(storage_key)}));"
        "saved.view.questionIndex=99; localStorage.setItem("
        f"{json.dumps(storage_key)}, JSON.stringify(saved)); return true; }})()"
    ) is True
    browser.navigate(quiz_url)
    browser.wait_for("quizRecoveryReady === true")
    assert browser.evaluate(f"localStorage.getItem({json.dumps(storage_key)})") is None

    browser.click(".exam-mode-btn")
    browser.navigate(f"{browser_stack.base_url}/library")
    assert browser.evaluate(
        f"(() => {{ const saved=JSON.parse(localStorage.getItem({json.dumps(storage_key)}));"
        "saved.session.createdAt=1; saved.session.updatedAt=2;"
        "saved.session.expiresAt=2 + (30 * 24 * 60 * 60 * 1000); localStorage.setItem("
        f"{json.dumps(storage_key)}, JSON.stringify(saved)); return true; }})()"
    ) is True
    browser.navigate(quiz_url)
    browser.wait_for("quizRecoveryReady === true")
    assert browser.evaluate(f"localStorage.getItem({json.dumps(storage_key)})") is None

    browser.click(".study-mode-btn")
    browser.click("#choices .choice[data-index='0']")
    browser.navigate(quiz_url)
    browser.wait_for("document.querySelector('.quiz-recovery-start-over') !== null")
    browser.click(".quiz-recovery-start-over")
    assert browser.evaluate(f"localStorage.getItem({json.dumps(storage_key)})") is None
    assert browser.evaluate(
        "!document.getElementById('modeSelect').classList.contains('hidden') && "
        "document.getElementById('quiz').classList.contains('hidden')"
    ) is True

    assert browser.evaluate(
        "(() => { const original = Storage.prototype.setItem;"
        "Storage.prototype.setItem = function(){ throw new DOMException('full', 'QuotaExceededError'); };"
        "window.__restoreRecoveryStorage = () => { Storage.prototype.setItem = original; }; return true; })()"
    ) is True
    browser.click(".study-mode-btn")
    browser.click("#choices .choice[data-index='0']")
    assert browser.evaluate("index === 0 && userAnswers.q0[0] === 0") is True
    assert "recovery is unavailable" in browser.evaluate("document.getElementById('quizRecoveryNotice').textContent")
    browser.evaluate("window.__restoreRecoveryStorage(); true")


def test_quiz_recovery_survives_firefox_close_and_reopen_with_same_profile(browser_server):
    profile = browser_server.work_root / "firefox-recovery-reopen-profile"
    profile.mkdir()
    quiz_url = f"{browser_server.base_url}/quizzes/{browser_server.metadata['critical_html']}"

    def launch(label):
        port = _free_loopback_port()
        log_path = browser_server.work_root / f"firefox-recovery-reopen-{label}.log"
        output = log_path.open("w", encoding="utf-8")
        process = subprocess.Popen(
            [browser_server.firefox, "--headless", "--no-remote", "--profile", str(profile),
             "--remote-debugging-port", str(port), "about:blank"],
            cwd=ROOT,
            env=browser_server.env,
            stdout=output,
            stderr=subprocess.STDOUT,
            **browser_server.process_options,
        )
        try:
            return process, output, _connect_firefox(port, process, log_path)
        except Exception:
            _terminate_process_tree(process)
            output.close()
            raise

    def close(process, output, browser):
        try:
            browser.command("browser.close", {}, timeout=3.0)
        except Exception:
            browser.close()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _terminate_process_tree(process)
        output.close()

    first_process = first_output = first_browser = None
    second_process = second_output = second_browser = None
    try:
        first_process, first_output, first_browser = launch("first")
        first_browser.navigate(quiz_url)
        first_browser.wait_for("quizRecoveryReady === true")
        first_browser.click(".exam-mode-btn")
        first_browser.click("#choices .choice[data-index='1']")
        first_browser.click("#nextBtn")
        first_browser.wait_for("index === 1")
        first_browser.navigate(f"{browser_server.base_url}/library")
        time.sleep(0.5)
        close(first_process, first_output, first_browser)
        first_process = first_output = first_browser = None

        second_process, second_output, second_browser = launch("second")
        second_browser.navigate(quiz_url)
        second_browser.wait_for("document.querySelector('.quiz-recovery-resume') !== null")
        assert "Question 2 of 2" in second_browser.evaluate(
            "document.querySelector('.quiz-recovery-panel p').textContent"
        )
        second_browser.click(".quiz-recovery-resume")
        second_browser.wait_for("index === 1 && userAnswers.q0[0] === 1")
    finally:
        if first_browser is not None:
            close(first_process, first_output, first_browser)
        if second_browser is not None:
            close(second_process, second_output, second_browser)


def test_quiz_recovery_survives_presence_shutdown_and_server_restart(tmp_path):
    firefox = shutil.which("firefox") or shutil.which("firefox-esr")
    if not firefox:
        pytest.skip("Firefox is not installed")
    data_root = tmp_path / "recovery-presence-data"
    profile = tmp_path / "recovery-presence-profile"
    profile.mkdir()
    server_port = _free_loopback_port()
    base_url = f"http://127.0.0.1:{server_port}"
    process_options = {"start_new_session": True} if os.name == "posix" else {}
    env = os.environ.copy()
    env.update({
        "QUIZAPP_DATA_DIR": str(data_root),
        "DLMS_NO_BROWSER": "1",
        "DLMS_BROWSER_TEST_PORT": str(server_port),
        "DLMS_BROWSER_REUSE_DATA": "1",
        "DLMS_BROWSER_PRESENCE_TEST_GRACE_SECONDS": "2",
        "DLMS_BROWSER_PRESENCE_TEST_TOKEN_TTL_SECONDS": "0.5",
        "DLMS_BROWSER_PRESENCE_TEST_POLL_SECONDS": "0.05",
        "MOZ_CRASHREPORTER_DISABLE": "1",
        "MOZ_DISABLE_AUTO_SAFE_MODE": "1",
        "PYTHONUNBUFFERED": "1",
    })
    server_process = browser_process = browser = None
    server_output = browser_output = None

    def start_server(label):
        log_path = tmp_path / f"recovery-presence-server-{label}.log"
        output = log_path.open("w", encoding="utf-8")
        process = subprocess.Popen(
            [sys.executable, str(ROOT / "tests" / "browser" / "_server.py")],
            cwd=ROOT, env=env, stdout=output, stderr=subprocess.STDOUT,
            **process_options,
        )
        _wait_for_server(f"{base_url}/library", process, log_path)
        return process, output

    def start_browser(label):
        port = _free_loopback_port()
        log_path = tmp_path / f"recovery-presence-firefox-{label}.log"
        output = log_path.open("w", encoding="utf-8")
        process = subprocess.Popen(
            [firefox, "--headless", "--no-remote", "--profile", str(profile),
             "--remote-debugging-port", str(port), "about:blank"],
            cwd=ROOT, env=env, stdout=output, stderr=subprocess.STDOUT,
            **process_options,
        )
        return process, output, _connect_firefox(port, process, log_path)

    def close_browser():
        nonlocal browser, browser_process, browser_output
        if browser is not None:
            try:
                browser.command("browser.close", {}, timeout=3.0)
            except Exception:
                browser.close()
            browser = None
        if browser_process is not None:
            try:
                browser_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                _terminate_process_tree(browser_process)
        browser_process = None
        if browser_output is not None:
            browser_output.close()
            browser_output = None

    try:
        server_process, server_output = start_server("first")
        metadata = json.loads((data_root / "browser_fixture.json").read_text(encoding="utf-8"))
        quiz_url = f"{base_url}/quizzes/{metadata['critical_html']}"
        browser_process, browser_output, browser = start_browser("first")
        browser.navigate(quiz_url)
        browser.wait_for("quizRecoveryReady === true && window.dlmsBrowserPresence?.enabled === true")
        browser.click(".study-mode-btn")
        browser.click("#choices .choice[data-index='0']")
        recovery_key = browser.evaluate("quizRecoveryController.storageKey")
        browser.navigate(f"{base_url}/library")
        browser.wait_for(f"localStorage.getItem({json.dumps(recovery_key)}) !== null")
        close_browser()

        deadline = time.monotonic() + 6
        while server_process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        assert server_process.poll() is not None
        server_output.close()
        server_output = None

        server_process, server_output = start_server("second")
        browser_process, browser_output, browser = start_browser("second")
        browser.navigate(quiz_url)
        browser.wait_for("document.querySelector('.quiz-recovery-resume') !== null")
        assert browser.evaluate(f"localStorage.getItem({json.dumps(recovery_key)}) !== null") is True
    finally:
        close_browser()
        _terminate_process_tree(server_process)
        if server_output is not None:
            server_output.close()


def test_quiz_recovery_library_prunes_only_expired_malformed_and_orphaned_records(browser_stack):
    browser = browser_stack.browser
    quiz_url = f"{browser_stack.base_url}/quizzes/{browser_stack.metadata['critical_html']}"
    browser.navigate(quiz_url)
    browser.wait_for("quizRecoveryReady === true")
    browser.click(".study-mode-btn")
    browser.click("#choices .choice[data-index='0']")
    current_key = browser.evaluate("quizRecoveryController.storageKey")
    browser.navigate(f"{browser_stack.base_url}/")
    browser.wait_for("window.dlmsCsrfToken !== undefined")
    seeded = browser.evaluate(
        f"(() => {{ const prefix=window.DLMSQuizRecovery?.STORAGE_PREFIX || 'dlms.quiz-progress.v1:';"
        f"const current=JSON.parse(localStorage.getItem({json.dumps(current_key)}));"
        "const put=(id,value)=>localStorage.setItem(prefix+encodeURIComponent(id),JSON.stringify(value));"
        "const orphan=structuredClone(current);orphan.quiz.id='orphan-118';put('orphan-118',orphan);"
        "const expired=structuredClone(current);expired.quiz.id='expired-118';"
        "expired.session.createdAt=1;expired.session.updatedAt=2;"
        "expired.session.expiresAt=2+(30*24*60*60*1000);put('expired-118',expired);"
        "const future=structuredClone(current);future.quiz.id='future-118';future.schemaVersion=999;put('future-118',future);"
        "localStorage.setItem(prefix+'malformed-118','{bad');"
        "localStorage.setItem('dlmsCollapsedLibraryFolders','[\"Browser Regression\"]');"
        "localStorage.setItem('unrelated.segment118','preserve');"
        "return {prefix,currentKey:" + json.dumps(current_key) + "}; })()"
    )
    browser.navigate(f"{browser_stack.base_url}/library")
    browser.wait_for(
        "window.DLMSQuizRecovery && "
        "localStorage.getItem('dlms.quiz-progress.v1:orphan-118') === null && "
        "localStorage.getItem('dlms.quiz-progress.v1:expired-118') === null && "
        "localStorage.getItem('dlms.quiz-progress.v1:future-118') === null && "
        "localStorage.getItem('dlms.quiz-progress.v1:malformed-118') === null"
    )
    assert browser.evaluate(f"localStorage.getItem({json.dumps(current_key)}) !== null") is True
    assert browser.evaluate("localStorage.getItem('unrelated.segment118')") == "preserve"
    assert browser.evaluate("localStorage.getItem('dlmsCollapsedLibraryFolders')") == '["Browser Regression"]'
    assert seeded["prefix"] == "dlms.quiz-progress.v1:"


def test_quiz_recovery_fingerprint_invalidation_tracks_playable_content_not_title(browser_stack):
    browser = browser_stack.browser
    browser.navigate(f"{browser_stack.base_url}/")
    browser.wait_for("window.dlmsCsrfToken !== undefined")
    browser.evaluate(
        "new Promise((resolve,reject)=>{const script=document.createElement('script');"
        "script.src='/static/quiz-recovery.js';script.onload=resolve;script.onerror=reject;"
        "document.head.appendChild(script)})"
    )
    fingerprints = browser.evaluate(
        "(async()=>{const make=(raw,minutes=5,title='One')=>DLMSQuizRecovery.quizFingerprint({"
        "rawQuizText:raw,quizId:'fingerprint-118',quizFile:'/data/fingerprint.json',"
        "quizTitle:title,examMinutes:minutes});"
        "const base='[{\"type\":\"choice\",\"choices\":[\"A\",\"B\"]}]';"
        "return {base:await make(base),identical:await make(base),title:await make(base,5,'Two'),"
        "question:await make('[{\"type\":\"choice\",\"choices\":[\"A\",\"C\"]}]'),"
        "reorder:await make('[{\"n\":2},{\"n\":1}]'),"
        "matching:await make('[{\"type\":\"matching\",\"pairs\":[[\"A\",\"B\"]]}]'),"
        "hotspot:await make('[{\"type\":\"hotspot\",\"x\":0.7,\"y\":0.2}]'),"
        "timer:await make(base,6)};})()"
    )
    assert fingerprints["base"] == fingerprints["identical"] == fingerprints["title"]
    assert len({fingerprints[name] for name in ("base", "question", "reorder", "matching", "hotspot", "timer")}) == 6

    quiz_url = f"{browser_stack.base_url}/quizzes/{browser_stack.metadata['recovery_html']}"
    artifact = browser_stack.data_root / "data" / browser_stack.metadata["recovery_json"]
    original_bytes = artifact.read_bytes()
    try:
        browser.navigate(quiz_url)
        browser.wait_for("quizRecoveryReady === true")
        browser.click(".study-mode-btn")
        browser.click("#choices .choice[data-index='0']")
        storage_key = browser.evaluate("quizRecoveryController.storageKey")
        browser.navigate(f"{browser_stack.base_url}/")
        changed = json.loads(original_bytes.decode("utf-8"))
        changed[0]["question"] = "Materially changed recovery question"
        artifact.write_text(json.dumps(changed), encoding="utf-8")
        browser.navigate(quiz_url)
        browser.wait_for("quizRecoveryReady === true")
        assert browser.evaluate("document.querySelector('.quiz-recovery-panel')") is None
        assert browser.evaluate(f"localStorage.getItem({json.dumps(storage_key)})") is None
    finally:
        artifact.write_bytes(original_bytes)


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


def test_quiz_header_uses_site_heading_and_branded_title_across_modes_themes_and_widths(browser_stack):
    browser = browser_stack.browser
    quiz_folder = browser_stack.data_root / "quizzes"
    logo_folder = browser_stack.data_root / "static" / "logos"
    logo_folder.mkdir(parents=True, exist_ok=True)
    (logo_folder / "header-test.png").write_bytes(base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
    ))
    title = "Smart Review — " + "LongUnbrokenTopicName" * 6 + " practice"
    html_name = "browser_header_branded.html"
    build_quiz_html(
        html_name, browser_stack.metadata["recovery_json"], str(quiz_folder / html_name),
        "Mike's Training & Practice Center", title, "header-test.png",
        browser_stack.metadata["critical_id"], 5,
        normalize_exam_minutes=lambda value: int(value),
    )
    quiz_url = f"{browser_stack.base_url}/quizzes/{html_name}"

    for theme in ("light", "dark", "purple-gold", "maroon-gold"):
        browser.navigate(f"{browser_stack.base_url}/settings")
        _set_theme(browser, theme)
        for mode_selector in (".study-mode-btn", ".exam-mode-btn"):
            browser.set_viewport(1440, 1000)
            browser.navigate(quiz_url)
            browser.wait_for("quizRecoveryReady === true && quiz.length === 4")
            browser.click(mode_selector)
            browser.wait_for("!document.getElementById('quiz').classList.contains('hidden')")
            for width in (1440, 1024, 760, 420):
                browser.set_viewport(width, 1000)
                layout = browser.evaluate(
                    "(() => {const hero=document.querySelector('.hero-title');"
                    "const banner=document.querySelector('.active-quiz-logo-banner');"
                    "const title=document.querySelector('.active-quiz-title');"
                    "const logos=[...banner.querySelectorAll('.active-logo-slot img')];"
                    "const bounds=node=>{const r=node.getBoundingClientRect();"
                    "return {left:r.left,right:r.right,top:r.top,bottom:r.bottom};};"
                    "return {hero:hero.textContent.trim(),heroChildren:hero.children.length,"
                    "heroBounds:bounds(hero),bannerBounds:bounds(banner),"
                    "title:title.textContent.trim(),titleTag:title.tagName,titleBounds:bounds(title),"
                    "logos:logos.map(img=>({loaded:img.complete&&img.naturalWidth>0,bounds:bounds(img)})),"
                    "progress:!!document.querySelector('.quiz-progress-card'),"
                    "studyBadge:getComputedStyle(document.getElementById('studyModeBadge')||document.body).display,"
                    "timer:getComputedStyle(document.getElementById('timer')).display,"
                    "question:document.getElementById('qText').textContent.trim(),"
                    "overflow:document.documentElement.scrollWidth>innerWidth};})()"
                )
                assert layout["hero"] == "Mike's Training & Practice Center"
                assert layout["heroChildren"] == 0
                if width == 1440:
                    assert layout["heroBounds"]["bottom"] - layout["heroBounds"]["top"] < 100
                assert layout["title"] == title
                assert layout["titleTag"] == "H2"
                assert len(layout["logos"]) == 2
                assert all(logo["loaded"] for logo in layout["logos"])
                assert layout["bannerBounds"]["top"] >= layout["heroBounds"]["bottom"]
                assert layout["titleBounds"]["left"] >= layout["bannerBounds"]["left"]
                assert layout["titleBounds"]["right"] <= layout["bannerBounds"]["right"]
                assert layout["titleBounds"]["bottom"] <= layout["bannerBounds"]["bottom"]
                if width > 600:
                    assert layout["logos"][0]["bounds"]["right"] <= layout["titleBounds"]["left"]
                    assert layout["titleBounds"]["right"] <= layout["logos"][1]["bounds"]["left"]
                else:
                    assert layout["logos"][0]["bounds"]["bottom"] <= layout["titleBounds"]["top"]
                    assert layout["titleBounds"]["bottom"] <= layout["logos"][1]["bounds"]["top"]
                assert all(logo["bounds"]["right"] <= layout["bannerBounds"]["right"]
                           for logo in layout["logos"])
                assert layout["progress"] and layout["question"]
                assert not layout["overflow"]
                if mode_selector == ".study-mode-btn":
                    assert layout["studyBadge"] != "none"
                    assert layout["timer"] == "none"
                else:
                    assert layout["timer"] != "none"

    no_logo_name = "browser_header_generated_no_logo.html"
    no_logo_title = "Spaced Review — Due Questions"
    build_quiz_html(
        no_logo_name, browser_stack.metadata["recovery_json"],
        str(quiz_folder / no_logo_name), "DLMS", no_logo_title, None,
        browser_stack.metadata["critical_id"], 5,
        normalize_exam_minutes=lambda value: int(value),
    )
    for mode_selector in (".study-mode-btn", ".exam-mode-btn"):
        browser.set_viewport(420, 1000)
        browser.navigate(f"{browser_stack.base_url}/quizzes/{no_logo_name}")
        browser.wait_for("quizRecoveryReady === true && quiz.length === 4")
        browser.click(mode_selector)
        browser.wait_for("!document.getElementById('quiz').classList.contains('hidden')")
        assert browser.evaluate(
            "(() => {const banner=document.querySelector('.active-quiz-logo-banner');"
            "return document.querySelector('.hero-title').textContent.trim()==='DLMS'"
            "&& banner.querySelector('.active-quiz-title').textContent.trim()==="
            + json.dumps(no_logo_title) + ";})()"
        )
        assert browser.evaluate(
            "document.querySelectorAll('.active-quiz-logo-banner img').length"
        ) == 0
        assert browser.evaluate("document.documentElement.scrollWidth <= innerWidth")

    # Previously published HTML is served from disk; its old subtitle is removed on load.
    legacy_name = "browser_header_legacy.html"
    legacy = (quiz_folder / html_name).read_text(encoding="utf-8")
    legacy = legacy.replace(
        '<h1 class="hero-title">Mike\'s Training &amp; Practice Center</h1>',
        '<h1 class="hero-title">Mike\'s Training &amp; Practice Center<br>'
        f'<span style="font-size:20px;opacity:.85">{title}</span></h1>',
    )
    (quiz_folder / legacy_name).write_text(legacy, encoding="utf-8")
    browser.navigate(f"{browser_stack.base_url}/quizzes/{legacy_name}")
    browser.wait_for("quizRecoveryReady === true && quiz.length === 4")
    assert browser.evaluate("document.querySelector('.hero-title').textContent.trim()") == (
        "Mike's Training & Practice Center"
    )
    assert browser.evaluate("document.querySelector('.hero-title').children.length") == 0


def test_study_session_panel_is_study_only_and_contained_across_themes(browser_stack):
    browser = browser_stack.browser
    base_url = browser_stack.base_url
    quiz_url = f"{base_url}/quizzes/{browser_stack.metadata['recovery_html']}"

    for theme in ("light", "dark", "purple-gold", "maroon-gold"):
        browser.navigate(base_url + "/settings")
        _set_theme(browser, theme)
        browser.navigate(quiz_url)
        browser.wait_for("quizRecoveryReady === true && quiz.length === 4")
        if browser.evaluate("Boolean(document.querySelector('.quiz-recovery-start-over'))"):
            browser.click(".quiz-recovery-start-over")
        browser.click(".study-mode-btn")
        browser.wait_for("document.getElementById('studySessionIntro') !== null")

        contrast = _theme_contrast_snapshot(browser, {
            "eyebrow": ".study-session-eyebrow",
            "heading": ".study-session-intro h3",
            "detail": ".study-session-intro p",
            "badge": ".study-mode-badge",
        })
        assert all(item["contrast"] >= 4.5 for item in contrast.values()), (theme, contrast)

        for width in (1440, 1024, 760, 420):
            browser.set_viewport(width, 900)
            layout = browser.evaluate(
                "(() => {const bar=document.querySelector('.top-bar');"
                "const intro=document.getElementById('studySessionIntro');"
                "const badge=document.getElementById('studyModeBadge');"
                "const progress=document.querySelector('.quiz-progress-card');"
                "const a=intro.getBoundingClientRect(),b=badge.getBoundingClientRect(),t=bar.getBoundingClientRect();"
                "return {visible:!intro.hidden&&!badge.hidden,"
                "wording:intro.textContent.includes('Untimed practice with feedback as you answer.'),"
                "singleTagline:bar.textContent.split('Learn at your own pace').length===2,"
                "studyControlsHidden:['submitBtn','timer','pauseBtn'].every(id=>getComputedStyle(document.getElementById(id)).display==='none'),"
                "progressAfter:progress.previousElementSibling===bar&&progress.getBoundingClientRect().top>=t.bottom,"
                "contained:a.left>=t.left&&a.right<=t.right&&b.left>=t.left&&b.right<=t.right,"
                "badgeCompact:b.width<t.width*.7,"
                "separate:a.right<=b.left+1||a.bottom<=b.top+1,"
                "overflow:document.documentElement.scrollWidth>innerWidth};})()"
            )
            assert layout == {
                "visible": True, "wording": True, "singleTagline": True,
                "studyControlsHidden": True,
                "progressAfter": True, "contained": True, "badgeCompact": True,
                "separate": True,
                "overflow": False,
            }, (theme, width, layout)

        if theme == "light":
            for expected in ("choice", "matching", "hotspot"):
                browser.evaluate("next(); true")
                assert browser.evaluate("quiz[index].type") == expected
                assert browser.evaluate(
                    "!document.getElementById('studySessionIntro').hidden && "
                    "!document.getElementById('studyModeBadge').hidden"
                ) is True

    # The same published quiz renderer is used by Adaptive and Concept Review.
    quiz_folder = browser_stack.data_root / "quizzes"
    for filename, title in (
        ("study_panel_adaptive.html", "Adaptive Study — What I Need Most"),
        ("study_panel_concept.html", "Concept Review — " + "VeryLongSharedTopic" * 6),
    ):
        build_quiz_html(
            filename, browser_stack.metadata["recovery_json"],
            str(quiz_folder / filename), "DLMS", title, None,
            browser_stack.metadata["critical_id"], 5,
            normalize_exam_minutes=lambda value: int(value),
        )
        browser.set_viewport(420, 900)
        browser.navigate(f"{base_url}/quizzes/{filename}")
        browser.wait_for("quizRecoveryReady === true && quiz.length === 4")
        if browser.evaluate("Boolean(document.querySelector('.quiz-recovery-start-over'))"):
            browser.click(".quiz-recovery-start-over")
        browser.click(".study-mode-btn")
        assert browser.evaluate(
            "document.querySelector('.active-quiz-title').textContent.trim()==="
            + json.dumps(title) + "&& !document.getElementById('studySessionIntro').hidden"
            "&& document.documentElement.scrollWidth<=innerWidth"
        ) is True

    browser.navigate(quiz_url)
    browser.wait_for("quizRecoveryReady === true && quiz.length === 4")
    if browser.evaluate("Boolean(document.querySelector('.quiz-recovery-start-over'))"):
        browser.click(".quiz-recovery-start-over")
    browser.click(".study-mode-btn")
    browser.click("#nextBtn")
    browser.wait_for("index === 1")
    recovery_key = browser.evaluate("quizRecoveryController.storageKey")
    browser.wait_for(
        f"JSON.parse(localStorage.getItem({json.dumps(recovery_key)})).view.questionIndex === 1"
    )
    browser.navigate(quiz_url)
    browser.wait_for("document.querySelector('.quiz-recovery-resume') !== null")
    browser.click(".quiz-recovery-resume")
    browser.wait_for(
        "index===1 && !document.getElementById('studySessionIntro').hidden && "
        "!document.getElementById('studyModeBadge').hidden"
    )

    browser.evaluate("startQuiz(true); true")
    exam = browser.evaluate(
        "(() => {const bar=document.querySelector('.top-bar');"
        "const intro=document.getElementById('studySessionIntro');"
        "const badge=document.getElementById('studyModeBadge');"
        "const visible=id=>getComputedStyle(document.getElementById(id)).display!=='none';"
        "return {introHidden:intro.hidden,badgeHidden:badge.hidden,"
        "submit:visible('submitBtn'),timer:visible('timer'),pause:visible('pauseBtn'),"
        "progressAfter:document.querySelector('.quiz-progress-card').previousElementSibling===bar};})()"
    )
    assert exam == {
        "introHidden": True, "badgeHidden": True, "submit": True,
        "timer": True, "pause": True, "progressAfter": True,
    }

    browser.navigate(quiz_url)
    browser.wait_for("quizRecoveryReady === true && quiz.length === 4")
    if browser.evaluate("Boolean(document.querySelector('.quiz-recovery-start-over'))"):
        browser.click(".quiz-recovery-start-over")
    browser.click(".exam-mode-btn")
    fresh_exam = browser.evaluate(
        "(() => {const bar=document.querySelector('.top-bar');"
        "return {introAbsent:!document.getElementById('studySessionIntro'),"
        "badgeAbsent:!document.getElementById('studyModeBadge'),"
        "submitInLeft:bar.querySelector('.top-left > #submitBtn') !== null,"
        "timerInRight:bar.querySelector(':scope > #timer.top-right') !== null,"
        "timerVisible:getComputedStyle(document.getElementById('timer')).display !== 'none',"
        "progressAfter:document.querySelector('.quiz-progress-card').previousElementSibling===bar};})()"
    )
    assert fresh_exam == {
        "introAbsent": True, "badgeAbsent": True, "submitInLeft": True,
        "timerInRight": True, "timerVisible": True, "progressAfter": True,
    }, fresh_exam


def test_quiz_question_tools_share_prompt_and_preserve_attempt_state(browser_stack):
    browser = browser_stack.browser
    browser.set_viewport(1440, 1000)
    quiz_url = f"{browser_stack.base_url}/quizzes/{browser_stack.metadata['recovery_html']}"
    browser.navigate(quiz_url)
    browser.wait_for("quizRecoveryReady === true && quiz.length === 4")
    browser.click(".study-mode-btn")
    browser.wait_for("document.getElementById('studyCopyBtn').offsetParent !== null")
    browser.evaluate(
        "studyAIConfig={ai_helper_enabled:true,ai_provider:'chatgpt'};"
        "window.__toolCalls={opens:[],copies:[],requests:[]};"
        "window.__syncCopies=0;"
        "window.open=(...args)=>{window.__toolCalls.opens.push(args);return null};"
        "window.__reviewExecCommand=command=>{if(command==='copy'){window.__syncCopies++;window.__toolCalls.copies.push(document.activeElement.value);return true}return false};"
        "document.execCommand=window.__reviewExecCommand;"
        "Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:async text=>{window.__toolCalls.copies.push(text)}}});"
        "window.__toolFetch=window.fetch;window.fetch=(...args)=>{window.__toolCalls.requests.push(String(args[0]));return window.__toolFetch(...args)};true"
    )
    browser.click("#studyAnkiBtn")
    browser.click("#choices .choice[data-index='1']")
    browser.wait_for("[...studyLearningEventSaves.values()].every(record => record.state === 'failed')")
    browser.evaluate("window.__toolCalls.requests=[];true")
    before = browser.evaluate(
        "({answers:JSON.stringify(userAnswers),anki:[...studyAnkiSelections],"
        "recovery:localStorage.getItem(quizRecoveryController.storageKey),index})"
    )
    browser.click("#studyAiBtn")
    review = browser.evaluate("({prompt:window.__toolCalls.copies.at(-1),opens:window.__toolCalls.opens})")
    assert review["opens"] == [["https://chatgpt.com/", "_blank", "noopener,noreferrer"]]
    assert "Recovery single-choice question?" in review["prompt"]
    assert "Answer Choices:" in review["prompt"]
    assert "My Answer:" in review["prompt"]
    browser.click("#studyCopyBtn")
    browser.wait_for("document.getElementById('questionCopyStatus').textContent === 'Copied to clipboard'")
    success = browser.evaluate(
        "({prompt:window.__toolCalls.copies.at(-1),opens:window.__toolCalls.opens.length,"
        "requests:window.__toolCalls.requests,answers:JSON.stringify(userAnswers),"
        "anki:[...studyAnkiSelections],recovery:localStorage.getItem(quizRecoveryController.storageKey),index})"
    )
    assert success["prompt"] == review["prompt"]
    assert success["opens"] == 1
    assert success["requests"] == []
    assert browser.evaluate("window.__syncCopies") == 1
    assert {key: success[key] for key in before} == before
    browser.evaluate("document.getElementById('studyCopyBtn').focus();true")
    assert browser.evaluate("document.activeElement.id") == "studyCopyBtn"
    browser.evaluate(
        "navigator.clipboard.writeText=async()=>{throw new Error('denied')};"
        "document.execCommand=()=>false;true"
    )
    browser.click("#studyCopyBtn")
    browser.wait_for("document.getElementById('questionCopyStatus').textContent.includes('Could not copy')")
    assert browser.evaluate("window.__toolCalls.opens.length") == 1
    assert browser.evaluate("JSON.stringify(userAnswers)") == before["answers"]
    browser.evaluate("document.execCommand=window.__reviewExecCommand;true")

    browser.click("#nextBtn")
    browser.wait_for("document.getElementById('qText').textContent.includes('multi-answer')")
    assert browser.evaluate("document.getElementById('studyCopyBtn').offsetParent !== null")
    browser.evaluate(
        "quiz[1].image_url='/static/favicon.ico';renderQuestion();"
        "navigator.clipboard.writeText=async text=>{window.__toolCalls.copies.push(text)};true"
    )
    browser.wait_for("document.querySelector('#choices .question-media-image')?.complete === true")
    browser.click("#choices .choice[data-index='0']")
    browser.click("#choices .choice[data-index='2']")
    browser.click("#studyAiBtn")
    multi_prompt = browser.evaluate("window.__toolCalls.copies.at(-1)")
    browser.click("#studyCopyBtn")
    browser.wait_for("document.getElementById('questionCopyStatus').textContent === 'Copied to clipboard'")
    assert browser.evaluate("window.__toolCalls.copies.at(-1)") == multi_prompt
    assert "First" in multi_prompt and "Third" in multi_prompt
    browser.click("#nextBtn")
    browser.wait_for("document.getElementById('qText').textContent.includes('matching')")
    assert browser.evaluate("getComputedStyle(document.getElementById('studyCopyBtn')).display") == "none"
    browser.click("#nextBtn")
    browser.wait_for("document.getElementById('qText').textContent.includes('hotspot')")
    assert browser.evaluate("getComputedStyle(document.getElementById('studyCopyBtn')).display") == "none"

    browser.navigate(f"{quiz_url}?exam=1")
    browser.wait_for("quizRecoveryReady === true")
    browser.click(".exam-mode-btn")
    assert browser.evaluate("getComputedStyle(document.getElementById('questionTools')).display") == "none"
    assert browser.evaluate("(() => {try {buildCurrentQuestionAIPrompt();return false}catch(error){return true}})()") is True


def test_quiz_question_copy_uses_real_legacy_fallback_when_clipboard_api_is_unavailable(browser_stack):
    browser = browser_stack.browser
    quiz_url = f"{browser_stack.base_url}/quizzes/{browser_stack.metadata['critical_html']}"
    browser.navigate(quiz_url)
    browser.wait_for("quizRecoveryReady === true")
    browser.click(".study-mode-btn")
    browser.evaluate(
        "Object.defineProperty(navigator,'clipboard',{configurable:true,value:undefined});"
        "window.__fallbackAttempts=0;window.__copiedSelection=null;window.__opens=0;"
        "window.open=()=>{window.__opens++};"
        "window.__nativeExec=document.execCommand.bind(document);"
        "document.execCommand=command=>{window.__fallbackAttempts++;return window.__nativeExec(command)};"
        "document.addEventListener('copy',()=>{const field=document.activeElement;"
        "window.__copiedSelection=field.value.slice(field.selectionStart,field.selectionEnd)});"
        "studyAIConfig={ai_helper_enabled:true,ai_provider:'chatgpt'};"
        "const button=document.getElementById('studyCopyBtn');"
        "button.scrollIntoView({block:'center'});button.focus();true"
    )
    browser.click("#studyAiBtn")
    review_prompt = browser.evaluate("window.__copiedSelection")
    assert browser.evaluate("window.__opens") == 1
    browser.evaluate("window.__opens=0;window.__fallbackAttempts=0;window.__copiedSelection=null;"
                     "document.getElementById('studyCopyBtn').scrollIntoView({block:'center'});"
                     "document.getElementById('studyCopyBtn').focus();true")
    before = browser.evaluate(
        "({prompt:buildCurrentQuestionAIPrompt(),focus:document.activeElement.id,scrollY,"
        "answers:JSON.stringify(userAnswers),anki:[...studyAnkiSelections],"
        "recovery:localStorage.getItem(quizRecoveryController.storageKey),index,"
        "textareas:document.querySelectorAll('textarea').length})"
    )
    browser.click("#studyCopyBtn")
    browser.wait_for("document.getElementById('questionCopyStatus').textContent === 'Copied to clipboard'")
    copied = browser.evaluate(
        "({selection:window.__copiedSelection,attempts:window.__fallbackAttempts,"
        "focus:document.activeElement.id,scrollY,answers:JSON.stringify(userAnswers),"
        "anki:[...studyAnkiSelections],recovery:localStorage.getItem(quizRecoveryController.storageKey),"
        "index,textareas:document.querySelectorAll('textarea').length,opens:window.__opens})"
    )
    assert copied["selection"] == review_prompt == before["prompt"]
    assert copied["attempts"] == 1
    assert copied["opens"] == 0
    assert {key: copied[key] for key in before if key != "prompt"} == {
        key: before[key] for key in before if key != "prompt"
    }

    browser.evaluate(
        "Object.defineProperty(navigator,'clipboard',{configurable:true,"
        "value:{writeText:async()=>{window.__modernAttempts=(window.__modernAttempts||0)+1;throw new Error('denied')}}});true"
    )
    browser.click("#studyCopyBtn")
    browser.wait_for("window.__fallbackAttempts === 2 && document.getElementById('questionCopyStatus').textContent === 'Copied to clipboard'")
    assert browser.evaluate("window.__modernAttempts") == 1
    assert browser.evaluate("window.__copiedSelection") == before["prompt"]
    assert browser.evaluate("document.querySelectorAll('textarea').length") == before["textareas"]

    browser.evaluate("document.execCommand=()=>false;true")
    browser.click("#studyCopyBtn")
    browser.wait_for("document.getElementById('questionCopyStatus').textContent.includes('Could not copy')")
    assert browser.evaluate("document.activeElement.id") == "studyCopyBtn"
    assert browser.evaluate("document.querySelectorAll('textarea').length") == before["textareas"]
    assert browser.evaluate("window.__opens") == 0
    assert browser.evaluate("JSON.stringify(userAnswers)") == before["answers"]

    browser.evaluate("document.execCommand=()=>{throw new Error('blocked')};true")
    browser.click("#studyCopyBtn")
    browser.wait_for("document.getElementById('questionCopyStatus').textContent.includes('Could not copy')")
    assert browser.evaluate("document.querySelectorAll('textarea').length") == before["textareas"]
    assert browser.evaluate("document.activeElement.id") == "studyCopyBtn"


def test_quiz_question_tools_wrap_across_themes_and_widths(browser_stack):
    browser = browser_stack.browser
    quiz_url = f"{browser_stack.base_url}/quizzes/{browser_stack.metadata['critical_html']}"
    for theme in ("light", "dark", "purple-gold", "maroon-gold"):
        browser.navigate(f"{browser_stack.base_url}/settings")
        _set_theme(browser, theme)
        browser.navigate(quiz_url)
        browser.wait_for("quizRecoveryReady === true")
        browser.click(".study-mode-btn")
        browser.evaluate("quiz[0].question='Long question '+ 'W'.repeat(180);renderQuestion();true")
        for width in (1440, 1024, 760, 420):
            browser.set_viewport(width, 900)
            layout = browser.evaluate(
                "(() => {const ids=['prevBtn','nextBtn','studyAiBtn','studyAnkiBtn','studyCopyBtn'];"
                "const buttons=ids.map(id=>document.getElementById(id));"
                "const bounds=buttons.map(button=>button.getBoundingClientRect());"
                "return {overflow:document.documentElement.scrollWidth>innerWidth,"
                "order:buttons.map(button=>button.id),"
                "contained:bounds.every(rect=>rect.left>=0&&rect.right<=innerWidth),"
                "navAboveTools:bounds[1].bottom<bounds[2].top,"
                "toolRows:new Set(bounds.slice(2).map(rect=>Math.round(rect.top))).size,"
                "types:buttons.map(button=>button.tagName),"
                "statusRole:document.getElementById('questionCopyStatus').getAttribute('role')};})()"
            )
            assert layout["overflow"] is False, (theme, width, layout)
            assert layout["contained"] is True, (theme, width, layout)
            assert layout["navAboveTools"] is True, (theme, width, layout)
            assert layout["order"] == ["prevBtn", "nextBtn", "studyAiBtn", "studyAnkiBtn", "studyCopyBtn"]
            assert layout["types"] == ["BUTTON"] * 5
            assert layout["statusRole"] == "status"
            if width == 420:
                assert layout["toolRows"] == 3
            contrast = _theme_contrast_snapshot(browser, {"tool": "#studyCopyBtn", "heading": ".quiz-question-tools h2"})
            assert contrast["tool"]["contrast"] >= 4.5, (theme, width, contrast)
            assert contrast["heading"]["contrast"] >= 4.5, (theme, width, contrast)


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

    browser.navigate(f"{browser_stack.base_url}/quizzes/{browser_stack.metadata['critical_html']}")
    browser.wait_for("quizRecoveryReady === true")
    browser.click(".study-mode-btn")
    browser.click("#choices .choice[data-index='0']")
    browser.wait_for("studyLearningEventSaves.size === 0")
    recovery_key = browser.evaluate("quizRecoveryController.storageKey")
    browser.evaluate("localStorage.setItem('unrelated.restore-segment118','preserve'); true")

    browser.navigate(f"{browser_stack.base_url}/edit_quiz/{quiz_id}")
    browser.wait_for("document.querySelector('[name=quiz_title]') !== null")
    browser.evaluate(
        f"(() => {{ document.querySelector('[name=quiz_title]').value = {json.dumps(changed_title)}; "
        f"document.querySelector('.question-text').value = {json.dumps(changed_question)}; "
        "return true; })()"
    )
    browser.click("#edit-quiz-form .build-primary-button")
    browser.wait_for_page_ready(
        f"location.pathname === '/edit_quiz/{quiz_id}' && "
        f"document.querySelector('[name=quiz_title]').value === {json.dumps(changed_title)}"
    )
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
    browser.wait_for_page_ready(
        "document.querySelector('h1')?.textContent.includes('Review backup before restore')"
    )
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
    assert browser.evaluate(f"localStorage.getItem({json.dumps(recovery_key)}) !== null") is True

    browser.click("form[action*='/restore/confirm/'] button[type='submit']")
    browser.wait_for_page_ready(
        "document.querySelector('h1')?.textContent.includes('Restore complete')",
        timeout=12.0,
    )
    browser.wait_for(f"localStorage.getItem({json.dumps(recovery_key)}) === null")
    assert browser.evaluate("localStorage.getItem('unrelated.restore-segment118')") == "preserve"
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


def test_cancelled_and_invalid_restore_preserve_quiz_recovery(browser_stack, tmp_path):
    browser = browser_stack.browser
    recovery_key = "dlms.quiz-progress.v1:restore-preserved-118"
    browser.navigate(f"{browser_stack.base_url}/settings/backup")
    browser.wait_for("document.getElementById('backupFile') !== null")
    browser.evaluate(f"localStorage.setItem({json.dumps(recovery_key)}, '{{preserve}}'); true")
    browser.set_files("#backupFile", [browser_stack.metadata["restore_path"]])
    browser.click("form[action='/settings/backup/restore/stage'] button[type='submit']")
    browser.wait_for("document.querySelector('h1')?.textContent.includes('Review backup before restore')")
    browser.click("form[action*='/restore/cancel/'] button[type='submit']")
    browser.wait_for("location.pathname === '/settings/backup' && location.search.includes('restore_cancelled=1')")
    assert browser.evaluate(f"localStorage.getItem({json.dumps(recovery_key)})") == "{preserve}"

    invalid = tmp_path / "invalid-segment118.zip"
    invalid.write_bytes(b"not a portable backup")
    browser.set_files("#backupFile", [str(invalid)])
    browser.click("form[action='/settings/backup/restore/stage'] button[type='submit']")
    browser.wait_for("document.querySelector('h1')?.textContent.includes('Backup rejected')")
    assert browser.evaluate(f"localStorage.getItem({json.dumps(recovery_key)})") == "{preserve}"


def test_manual_quiz_choice_labels_are_readable_across_themes(browser_stack):
    browser = browser_stack.browser
    base_url = browser_stack.base_url
    original_theme = json.loads(
        (browser_stack.data_root / "config" / "portal.json").read_text(encoding="utf-8")
    ).get("theme", "purple-gold")

    contrast_helpers = (
        "const parse=value=>{value=value.trim();if(value.startsWith('#')){let h=value.slice(1);"
        "if(h.length===3)h=[...h].map(c=>c+c).join('');return [parseInt(h.slice(0,2),16)/255,"
        "parseInt(h.slice(2,4),16)/255,parseInt(h.slice(4,6),16)/255,1];}"
        "const m=value.match(/^rgba?\\(([^)]+)\\)$/);if(m){const p=m[1].split(/[, ]+/).filter(Boolean).map(Number);"
        "return [p[0]/255,p[1]/255,p[2]/255,p.length>3?p[3]:1];}"
        "const s=value.match(/^color\\(srgb ([^/ )]+) ([^/ )]+) ([^/ )]+)(?: \\/ ([^)]+))?\\)$/);"
        "if(s)return [+s[1],+s[2],+s[3],s[4]===undefined?1:+s[4]];throw new Error(value);};"
        "const mix=(fg,bg)=>fg.slice(0,3).map((v,i)=>v*fg[3]+bg[i]*(1-fg[3]));"
        "const base=parse(getComputedStyle(document.documentElement).getPropertyValue('--theme-body-base')).slice(0,3);"
        "const effective=node=>{const layers=[];for(let item=node;item;item=item.parentElement)"
        "layers.push(parse(getComputedStyle(item).backgroundColor));"
        "return layers.reverse().reduce((bg,layer)=>mix(layer,bg),base);};"
        "const lum=rgb=>rgb.map(v=>v<=.04045?v/12.92:Math.pow((v+.055)/1.055,2.4))"
        ".reduce((sum,v,i)=>sum+v*[.2126,.7152,.0722][i],0);"
        "const measure=node=>{const background=effective(node);"
        "const foreground=mix(parse(getComputedStyle(node).color),background);"
        "return {color:getComputedStyle(node).color,opacity:getComputedStyle(node).opacity,"
        "contrast:(Math.max(lum(foreground),lum(background))+.05)/(Math.min(lum(foreground),lum(background))+.05)};};"
    )

    for theme in ("light", "dark", "purple-gold", "maroon-gold"):
        browser.navigate(f"{base_url}/settings")
        browser.wait_for("window.dlmsCsrfToken")
        assert browser.evaluate(
            f"fetch('/api/theme',{{method:'POST',headers:{{'Content-Type':'application/json'}},"
            f"body:JSON.stringify({{theme:{json.dumps(theme)}}})}}).then(response=>response.status)"
        ) == 200
        for width in (1280, 420):
            browser.set_viewport(width, 900)
            browser.navigate(f"{base_url}/create_short_quiz?count=1&theme={theme}&width={width}")
            browser.wait_for("document.querySelector('.build-correct-toggle .choice-correct')")
            state = browser.evaluate(
                "(() => {" + contrast_helpers
                + "const heading=document.querySelector('.build-choice-heading > span');"
                "const toggle=document.querySelector('.build-correct-toggle');"
                "const correct=toggle.querySelector('span');const checkbox=toggle.querySelector('input');"
                "const answerLabel=document.querySelector('.build-choice-list .choice-label');"
                "const pageText=getComputedStyle(document.documentElement).getPropertyValue('--theme-page-text').trim();"
                "const enabled=measure(correct);const headingMeasure=measure(heading);"
                "checkbox.focus();const focusable=document.activeElement===checkbox;checkbox.disabled=true;checkbox.blur();checkbox.focus();"
                "const disabled=measure(correct);"
                "return {heading:headingMeasure,enabled,disabled,focusable,"
                "disabledUnfocusable:document.activeElement!==checkbox,disabledFlag:checkbox.disabled,"
                "answerLabel:getComputedStyle(answerLabel).color,pageText,"
                "contained:document.documentElement.scrollWidth<=innerWidth+1};})()"
            )
            assert state["heading"]["contrast"] >= 4.5, (theme, width, state)
            assert state["enabled"]["contrast"] >= 4.5, (theme, width, state)
            assert state["heading"]["opacity"] == "1"
            assert state["enabled"]["opacity"] == "1"
            assert state["disabled"]["opacity"] == "0.62"
            assert state["disabled"]["color"] != state["enabled"]["color"]
            assert state["focusable"] is True
            assert state["disabledUnfocusable"] is True
            assert state["disabledFlag"] is True
            assert state["answerLabel"] != state["enabled"]["color"]
            assert state["contained"] is True

    browser.navigate(f"{base_url}/settings")
    browser.wait_for("window.dlmsCsrfToken")
    assert browser.evaluate(
        f"fetch('/api/theme',{{method:'POST',headers:{{'Content-Type':'application/json'}},"
        f"body:JSON.stringify({{theme:{json.dumps(original_theme)}}})}}).then(response=>response.status)"
    ) == 200


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
            "const addedKey = document.querySelector('.diff-added-key');"
            "const removedKey = document.querySelector('.diff-removed-key');"
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
            "addedKeyColor:getComputedStyle(addedKey).color,"
            "removedKeyColor:getComputedStyle(removedKey).color,"
            "pageText:resolve('--theme-page-text'),heading:resolve('--theme-heading'),"
            "accentText:resolve('--theme-accent-text'),muted:resolve('--theme-muted-text'),"
            "successText:resolve('--semantic-success-text'),"
            "errorText:resolve('--semantic-error-text')}; })()"
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
        assert preview_styles["addedKeyColor"] == preview_styles["successText"]
        assert preview_styles["removedKeyColor"] == preview_styles["errorText"]

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
        "clearRole:document.getElementById('clearDBStatus').getAttribute('role'),"
        "clearLive:document.getElementById('clearDBStatus').getAttribute('aria-live'),"
        "resetRole:document.getElementById('resetStatus').getAttribute('role'),"
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
        "clearRole": "status",
        "clearLive": "polite",
        "resetRole": "status",
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
        "status:document.getElementById('clearDBStatus').textContent,"
        "role:document.getElementById('clearDBStatus').getAttribute('role'),"
        "live:document.getElementById('clearDBStatus').getAttribute('aria-live')})"
    )
    assert clear_contract == {
        "calls": [{"url": "/api/clear_db_history", "method": "POST"}],
        "confirms": [
            "Clear all saved quiz attempts and missed-question history?\n\n"
            "Your quizzes will remain available.\n\n"
            "Create a backup first if you may need this history later."
        ],
        "status": "✅ Saved attempt and missed-question history cleared.",
        "role": "status",
        "live": "polite",
    }

    assert browser.evaluate(
        "(() => { sessionStorage.removeItem('dlms-reset-alert'); window.__resetCalls=[];"
        "localStorage.setItem('dlms.quiz-progress.v1:reset-success-118','preserve');"
        "localStorage.setItem('unrelated.reset-segment118','preserve');"
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
    assert browser.evaluate("localStorage.getItem('dlms.quiz-progress.v1:reset-success-118')") is None
    assert browser.evaluate("localStorage.getItem('unrelated.reset-segment118')") == "preserve"

    browser.wait_for("window.dlmsCsrfToken && document.getElementById('resetStatus')")
    browser.evaluate("localStorage.setItem('dlms.quiz-progress.v1:failed-reset-118','preserve'); true")
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
            "status:document.getElementById('resetStatus').textContent,"
            "role:document.getElementById('resetStatus').getAttribute('role'),"
            "live:document.getElementById('resetStatus').getAttribute('aria-live')})"
        )
        assert reset_failure["calls"] == [
            {"url": "/api/reset_all_data", "method": "POST", "headers": {}, "body": None}
        ]
        assert reset_failure["confirms"] == [
            "⚠ DLMS to Fresh State ⚠\n\n"
            "DLMS will create a safety backup first, then perform this reset.\n\n"
            "Continue?"
        ]
        assert "could not verify ownership" in reset_failure["status"]
        assert reset_failure["role"] == "alert"
        assert reset_failure["live"] == "assertive"
        assert browser.evaluate("localStorage.getItem('dlms.quiz-progress.v1:failed-reset-118')") == "preserve"
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
            "status:document.getElementById('resetStatus').textContent,"
            "role:document.getElementById('resetStatus').getAttribute('role'),"
            "live:document.getElementById('resetStatus').getAttribute('aria-live')})"
        )
        assert removal_failure["calls"] == [{
            "url": "/api/remove_all_dlms_data",
            "method": "POST",
            "headers": {"content-type": "application/json"},
            "body": '{"confirmation":"REMOVE DLMS DATA"}',
        }]
        assert removal_failure["confirms"] == [removal_confirmation]
        assert "could not verify ownership" in removal_failure["status"]
        assert removal_failure["role"] == "alert"
        assert removal_failure["live"] == "assertive"
        assert browser.evaluate("localStorage.getItem('dlms.quiz-progress.v1:failed-reset-118')") == "preserve"
        assert browser_stack.data_root.is_dir()
        assert disabled_marker.is_file()
    finally:
        if disabled_marker.exists():
            disabled_marker.rename(marker)

    assert browser.evaluate(
        "(() => {localStorage.setItem('dlms.quiz-progress.v1:remove-success-118','preserve');"
        "const input=document.getElementById('removeDlmsConfirmation');input.value='REMOVE DLMS DATA';"
        "input.dispatchEvent(new Event('input',{bubbles:true}));window.confirm=()=>true;window.alert=()=>{};"
        "window.fetch=()=>Promise.resolve(new Response(JSON.stringify({status:'ok'}),"
        "{status:200,headers:{'Content-Type':'application/json'}}));return true})()"
    ) is True
    browser.click("#removeAllDlmsDataBtn")
    browser.wait_for("document.getElementById('resetStatus').textContent.includes('runtime data removed')")
    assert browser.evaluate("localStorage.getItem('dlms.quiz-progress.v1:remove-success-118')") is None
    assert browser.evaluate("localStorage.getItem('unrelated.reset-segment118')") == "preserve"

    browser.navigate(f"{base_url}/settings/reset-remove")
    browser.wait_for("window.DLMSQuizRecovery && document.getElementById('resetStatus')")
    assert browser.evaluate(
        "(() => {localStorage.setItem('dlms.quiz-progress.v1:storage-failure-118','preserve');"
        "const original=Storage.prototype.removeItem;Storage.prototype.removeItem=function(){throw new Error('blocked')};"
        "window.confirm=()=>true;window.alert=message=>sessionStorage.setItem('dlms-storage-failure-alert',message);"
        "window.fetch=()=>Promise.resolve(new Response(JSON.stringify({status:'ok',backup:'safe.zip'}),"
        "{status:200,headers:{'Content-Type':'application/json'}}));return true})()"
    ) is True
    browser.click(".resetAction[data-endpoint='/api/reset_all_data']")
    browser.wait_for(
        "document.readyState === 'complete' && "
        "sessionStorage.getItem('dlms-storage-failure-alert') !== null"
    )
    assert "reset completed" in browser.evaluate("sessionStorage.getItem('dlms-storage-failure-alert')")


def test_packaged_clear_history_error_guidance_themes(browser_stack):
    browser = browser_stack.browser
    for theme in ("light", "dark", "purple-gold", "maroon-gold"):
        browser.navigate(f"{browser_stack.base_url}/settings/reset-remove")
        _set_theme(browser, theme)
        for width in (1280, 420):
            browser.set_viewport(width, 900)
            browser.navigate(f"{browser_stack.base_url}/settings/reset-remove")
            browser.wait_for("document.getElementById('clearDBBtn') && window.dlmsCsrfToken")
            browser.evaluate("window.confirm=()=>true;window.fetch=async()=>new Response(JSON.stringify({error:'Restart DLMS and retry. <img id=errorInjected> If it persists, report the action and DLMS version.'}),{status:500,headers:{'Content-Type':'application/json'}});true")
            browser.click("#clearDBBtn")
            browser.wait_for("!document.getElementById('clearDBBtn').disabled && document.getElementById('clearDBStatus').textContent.includes('Restart DLMS')")
            assert browser.evaluate("document.getElementById('errorInjected')===null")
            assert browser.evaluate("document.getElementById('clearDBStatus').getAttribute('role')") == "alert"
            assert browser.evaluate("document.documentElement.scrollWidth<=window.innerWidth+1"), (theme, width)
            contrast = _theme_contrast_snapshot(browser, {"error": "#clearDBStatus"})
            assert contrast["error"]["contrast"] >= 4.5, (theme, width, contrast)
            browser.evaluate("window.fetch=async()=>{throw new Error('PRIVATE network details')};document.getElementById('clearDBBtn').click();true")
            browser.wait_for("document.getElementById('clearDBStatus').textContent.includes('Could not confirm')")
            assert "PRIVATE" not in browser.evaluate("document.getElementById('clearDBStatus').textContent")


def test_backup_limit_guidance_layout_themes(browser_stack):
    # A small sparse fixture compresses beyond the unchanged restore ratio cap.
    # Exercise the real POST and rejected archive, without altering server limits.
    fixture = browser_stack.data_root / "data" / "backup-limit-fixture.txt"
    with fixture.open("wb") as handle:
        handle.truncate(17 * 1024 * 1024)
    browser = browser_stack.browser
    for theme in ("light", "dark", "purple-gold", "maroon-gold"):
        browser.navigate(f"{browser_stack.base_url}/settings/backup")
        _set_theme(browser, theme)
        for width in (1280, 420):
            browser.set_viewport(width, 900)
            browser.navigate(f"{browser_stack.base_url}/settings/backup")
            browser.wait_for("window.dlmsCsrfToken")
            browser.click("form[action='/settings/backup/create'] button")
            browser.wait_for("document.querySelector('.settings-critical-panel')?.textContent.includes('supported restore size')")
            assert browser.evaluate("document.documentElement.scrollWidth<=window.innerWidth+1"), (theme, width)
            assert "backup-limit-fixture" not in browser.evaluate("document.body.textContent")
            contrast = _theme_contrast_snapshot(browser, {"error": ".settings-critical-panel span"})
            assert contrast["error"]["contrast"] >= 4.5, (theme, width, contrast)
    assert not list((browser_stack.data_root / "backups").glob("*.tmp"))


def test_restore_failure_guidance_layout_themes(browser_stack):
    browser = browser_stack.browser
    for theme in ("light", "dark", "purple-gold", "maroon-gold"):
        browser.navigate(f"{browser_stack.base_url}/settings/backup")
        _set_theme(browser, theme)
        for width in (1280, 420):
            browser.set_viewport(width, 900)
            browser.navigate(f"{browser_stack.base_url}/settings/backup")
            browser.wait_for("window.dlmsCsrfToken")
            browser.evaluate("(() => {const form=document.createElement('form');form.method='POST';form.action='/settings/backup/restore/confirm/'+'0'.repeat(32);const input=document.createElement('input');input.name='csrf_token';input.value=window.dlmsCsrfToken;form.append(input);document.body.append(form);form.submit();return true})()")
            browser.wait_for("document.querySelector('.settings-critical-panel')?.textContent.includes('before changing live data')")
            # Service/integration tests establish this outcome. Exercise the same
            # error panel with the longest recovery guidance for layout coverage.
            browser.evaluate("document.querySelector('.settings-critical-panel span').textContent='Recovery is still required. DLMS could not confirm a complete recovery; live data may be partially restored. Stop making changes and keep the safety backup and retained recovery journal in the DLMS data folder. After checking disk space and data-folder access, restart DLMS to retry automatic recovery. If it still fails, seek help with your DLMS version and this message; do not delete recovery files or run a reset.';true")
            assert browser.evaluate("document.documentElement.scrollWidth<=window.innerWidth+1"), (theme, width)
            contrast = _theme_contrast_snapshot(browser, {"recovery": ".settings-critical-panel span"})
            assert contrast["recovery"]["contrast"] >= 4.5, (theme, width, contrast)


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
        "buttonDescription:document.getElementById('rebuildAllBtn').getAttribute('aria-describedby'),"
        "statusLive:document.getElementById('rebuildStatus').getAttribute('aria-live'),"
        "statusRole:document.getElementById('rebuildStatus').getAttribute('role'),"
        "statusAtomic:document.getElementById('rebuildStatus').getAttribute('aria-atomic'),"
        "guidance:document.querySelector('.system-tools-action p').textContent,"
        "imageEditorHref:document.querySelector('.system-tools-secondary-action').getAttribute('href')"
        "}))()"
    )
    assert accessibility == {
        "menuLabel": "Toggle navigation",
        "menuControls": "dashboardSidebar",
        "menuExpanded": "false",
        "buttonType": "button",
        "buttonDescription": "rebuildDescription",
        "statusLive": "polite",
        "statusRole": "status",
        "statusAtomic": "true",
        "guidance": "Occasional maintenance: You normally do not need to run this after updating DLMS. Use it when DLMS specifically instructs you to refresh generated quiz pages, when existing quiz pages look stale or inconsistent with the current quiz interface, or when their generated page files need repair.",
        "imageEditorHref": "/admin/image-editor",
    }

    for theme in ("light", "dark", "purple-gold", "maroon-gold"):
        _set_theme(browser, theme)
        for width in (1280, 420):
            browser.set_viewport(width, 900)
            browser.navigate(f"{browser_stack.base_url}/admin/maintenance")
            browser.wait_for("document.getElementById('rebuildAllBtn')")
            browser.evaluate("document.getElementById('rebuildFailures').textContent = "
                "'Quiz 17: DLMS could not write the page files. Check data-folder write permissions and retry.';true")
            layout = browser.evaluate(
                "(() => {const panel=document.querySelector('.system-tools-panel');"
                "const button=document.getElementById('rebuildAllBtn');"
                "const p=panel.getBoundingClientRect(),b=button.getBoundingClientRect();"
                "return {overflow:document.documentElement.scrollWidth<=window.innerWidth+1,"
                "panelContained:p.left>=0&&p.right<=window.innerWidth+1,"
                "buttonContained:b.left>=p.left&&b.right<=p.right,"
                "buttonHeight:Math.round(b.height),descriptionLines:Math.round("
                "document.getElementById('rebuildDescription').getBoundingClientRect().height/"
                "parseFloat(getComputedStyle(document.getElementById('rebuildDescription')).lineHeight))};})()"
            )
            assert layout["overflow"] is True, (theme, width, layout)
            assert layout["panelContained"] is True, (theme, width, layout)
            assert layout["buttonContained"] is True, (theme, width, layout)
            assert layout["buttonHeight"] >= 40, (theme, width, layout)
            assert layout["descriptionLines"] <= (6 if width == 420 else 3), (
                theme, width, layout,
            )
            contrast = _theme_contrast_snapshot(
                browser,
                {
                    "rebuild description": "#rebuildDescription",
                    "rebuild diagnostics": "#rebuildFailures",
                },
            )
            for role, state in contrast.items():
                assert state["contrast"] >= 4.5, (theme, width, role, state)

    browser.set_viewport(1280, 900)
    browser.navigate(f"{browser_stack.base_url}/admin/maintenance")
    browser.wait_for("window.dlmsCsrfToken && document.getElementById('rebuildAllBtn')")

    confirmation = (
        "Rebuild all registered quiz pages from saved quiz data?\n\n"
        "Only derived page files will be replaced. Questions, answers, IDs, "
        "lineage, folders, and learning history will not be changed."
    )
    cancelled = browser.evaluate(
        "(() => {window.__maintenanceCalls=[];window.__maintenanceConfirms=[];"
        "window.confirm=message=>{window.__maintenanceConfirms.push(message);return false};"
        "const originalFetch=window.fetch.bind(window);"
        "window.fetch=(input,init={})=>{window.__maintenanceCalls.push({url:String(input),method:init.method,body:init.body});"
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
        "window.fetch=(input,init={})=>{window.__maintenanceCalls.push({url:String(input),method:init.method,body:init.body});"
        "return new Promise(resolve=>{window.__resolveMaintenanceFetch=resolve})};return true;})()"
    ) is True
    browser.click("#rebuildAllBtn")
    browser.wait_for(
        "document.getElementById('rebuildAllBtn').disabled && "
        "document.getElementById('rebuildStatus').textContent === 'Rebuilding quiz pages...'"
    )
    browser.evaluate(
        "window.__resolveMaintenanceFetch(new Response(JSON.stringify({"
        "status:'complete',rebuilt:'<img id=maintenanceInjected>',failed:['<svg>'],"
        "failure_details:[{quiz_id:17,message:'<img id=diagnosticInjected> Check disk space.'}]}),"
        "{status:200,headers:{'Content-Type':'application/json'}}));true"
    )
    browser.wait_for(
        "!document.getElementById('rebuildAllBtn').disabled && "
        "document.getElementById('rebuildStatus').textContent.startsWith('Finished with issues:')"
    )
    safe_status = browser.evaluate(
        "(() => {const status=document.getElementById('rebuildStatus');return {"
        "text:status.textContent,html:status.innerHTML,"
        "injected:document.getElementById('maintenanceInjected')!==null,"
        "calls:window.__maintenanceCalls,confirms:window.__maintenanceConfirms};})()"
    )
    assert safe_status == {
        "text": "Finished with issues: <img id=maintenanceInjected> rebuilt, 1 failed. Failed quizzes kept their previous page files. Review the problems below.",
        "html": "Finished with issues: &lt;img id=maintenanceInjected&gt; rebuilt, 1 failed. Failed quizzes kept their previous page files. Review the problems below.",
        "injected": False,
        "calls": [{
            "url": "/admin/rebuild_all_quiz_html",
            "method": "POST",
            "body": '{"confirmation":"rebuild-all-quiz-pages"}',
        }],
        "confirms": [confirmation],
    }

    assert browser.evaluate("document.querySelector('#rebuildFailures li').textContent") == (
        'Quiz 17: <img id=diagnosticInjected> Check disk space.'
    )
    assert browser.evaluate("document.getElementById('diagnosticInjected') === null")

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
        "'forced failure'"
    )

    browser.navigate(f"{browser_stack.base_url}/admin/maintenance?live=1")
    browser.wait_for("window.dlmsCsrfToken && document.getElementById('rebuildAllBtn')")
    registered_quizzes = json.loads(
        (browser_stack.data_root / "config" / "quizzes.json").read_text(
            encoding="utf-8"
        )
    )
    expected_rebuilt = sum(entry.get("id") is not None for entry in registered_quizzes)
    live_entry = next(entry for entry in registered_quizzes if entry.get("id") is not None)
    live_html = browser_stack.data_root / "quizzes" / live_entry["html"]
    live_json = (
        browser_stack.data_root / "data" / live_entry["html"].replace(".html", ".json")
    )
    live_html.write_text("browser stale html", encoding="utf-8")
    live_json.write_text('[{"browser_stale":true}]', encoding="utf-8")
    assert browser.evaluate(
        "(() => {const protectedFetch=window.fetch.bind(window);window.__maintenanceCalls=[];"
        "window.confirm=()=>true;window.fetch=(input,init={})=>{"
        "window.__maintenanceCalls.push({url:String(input),method:init.method,body:init.body});"
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
        {
            "url": "/admin/rebuild_all_quiz_html",
            "method": "POST",
            "body": '{"confirmation":"rebuild-all-quiz-pages"}',
        }
    ]
    assert "browser stale html" not in live_html.read_text(encoding="utf-8")
    rebuilt_payload = json.loads(live_json.read_text(encoding="utf-8"))
    assert rebuilt_payload and "browser_stale" not in rebuilt_payload[0]


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

    folder = 'DLMS_Study_browser ?#% "double" \'single\' & Café'
    encoded_folder = urllib.parse.quote(folder, safe="!$&'()*+,/:;=@")
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
        "details": f"/content-packs/details/{encoded_folder}",
        "exportHref": f"/content-packs/export/{encoded_folder}",
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

    browser.evaluate(
        "document.querySelector(\"a[href*='/content-packs/details/']\").click();true"
    )
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
        "exportHref": f"/content-packs/export/{encoded_folder}",
        "injected": False,
    }


def test_content_pack_detail_and_library_consistency_across_themes(browser_stack):
    browser = browser_stack.browser
    base_url = browser_stack.base_url
    portal_path = browser_stack.data_root / "config" / "portal.json"
    original_theme = json.loads(portal_path.read_text(encoding="utf-8")).get(
        "theme", "purple-gold"
    )

    folder = "DLMS_Study_theme_" + "long-folder-segment-" * 8
    pack_root = browser_stack.data_root / "content_packs" / folder
    data_root = pack_root / "data"
    data_root.mkdir(parents=True)
    (pack_root / "manifest.json").write_text(
        json.dumps({
            "schema_version": 1,
            "id": "browser_theme_consistency",
            "name": "Browser theme consistency pack with a deliberately long readable title",
            "version": "1.0",
            "description": "Long descriptive metadata " + "continuous-description-value-" * 8,
            "content_domain": "Browser testing",
            "datasets": [{
                "id": "terms",
                "title": "Theme terms",
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
            "title": "Theme terms",
            "source": {"organization": "DLMS Browser Test", "license": "CC0"},
            "terms": [
                {"term": "Surface", "definition": "A semantic card layer."},
                {"term": "Contrast", "definition": "A readable foreground relationship."},
            ],
        }),
        encoding="utf-8",
    )
    encoded_folder = urllib.parse.quote(folder, safe="!$&'()*+,/:;=@")

    def set_theme(theme):
        browser.navigate(f"{base_url}/settings")
        browser.wait_for("window.dlmsCsrfToken && document.getElementById('dlmsQuickTheme')")
        status = browser.evaluate(
            f"fetch('/api/theme', {{method:'POST', headers:{{'Content-Type':'application/json'}}, "
            f"body:JSON.stringify({{theme:{json.dumps(theme)}}})}}).then(response => response.status)"
        )
        assert status == 200

    for theme in ("light", "dark", "purple-gold", "maroon-gold"):
        set_theme(theme)
        # Pack metrics have three text children, unlike icon+copy dashboard
        # cards. Check real layout across the four/two/one-column breakpoints.
        for width in (1920, 1024, 768, 420):
            browser.set_viewport(width, 1080)
            browser.navigate(f"{base_url}/content-packs/details/{encoded_folder}")
            browser.wait_for("document.querySelectorAll('.pack-detail-stat-grid > article').length === 4")
            assert browser.evaluate("""(() => {
                const cards=[...document.querySelectorAll('.pack-detail-stat-grid > article')];
                return cards.every(card => {
                    const [label,value,description]=[...card.children];
                    const [a,b,c]=[label,value,description].map(el=>el.getBoundingClientRect());
                    return Math.abs(a.left-b.left)<1 && Math.abs(b.left-c.left)<1
                        && a.bottom<=b.top && b.bottom<=c.top
                        && [card,label,value,description].every(el=>el.scrollWidth<=el.clientWidth+1)
                        && getComputedStyle(card).gridTemplateColumns.split(' ').length===1;
                });
            })()""") is True
        browser.set_viewport(420, 900)
        browser.navigate(f"{base_url}/content-packs/details/{encoded_folder}")
        browser.wait_for("document.querySelector('.pack-detail-meta span') !== null")
        detail = browser.evaluate(
            "(() => {"
            "const resolve = name => {const probe=document.createElement('span');"
            "probe.style.color=`var(${name})`;document.body.appendChild(probe);"
            "const value=getComputedStyle(probe).color;probe.remove();return value};"
            "const hero=document.querySelector('.pack-detail-hero');"
            "const stats=document.querySelector('.pack-detail-stat-grid');"
            "const validation=document.querySelector('.pack-validation-panel');"
            "const description=hero.querySelector('p');"
            "const meta=document.querySelector('.pack-detail-meta');"
            "const actions=document.querySelector('.pack-detail-actions');"
            "const label=meta.querySelector('strong');const value=meta.querySelector('span');"
            "const back=document.querySelector('.pack-detail-actions .medical-ai-secondary-button');"
            "const exportAction=document.querySelector('.pack-detail-actions .medical-primary-button');"
            "const backStyle=getComputedStyle(back);const exportStyle=getComputedStyle(exportAction);"
            "const resolveBackground = name => {const probe=document.createElement('span');"
            "probe.style.backgroundColor=`var(${name})`;document.body.appendChild(probe);"
            "const result=getComputedStyle(probe).backgroundColor;probe.remove();return result};"
            "const blockGap=(before,after)=>Math.round(after.getBoundingClientRect().top-"
            "before.getBoundingClientRect().bottom);"
            "return {pageText:resolve('--theme-page-text'),muted:resolve('--theme-muted-text'),"
            "secondaryText:resolve('--semantic-secondary-control-text'),"
            "secondarySurface:resolveBackground('--semantic-secondary-control-surface'),"
            "description:getComputedStyle(description).color,"
            "label:getComputedStyle(label).color,value:getComputedStyle(value).color,"
            "backText:back.textContent.trim(),backColor:backStyle.color,"
            "backBackground:backStyle.backgroundColor,backRadius:backStyle.borderRadius,"
            "backPadding:backStyle.padding,backMinHeight:backStyle.minHeight,"
            "backWeight:backStyle.fontWeight,backSize:backStyle.fontSize,"
            "backAlign:backStyle.alignItems,exportRadius:exportStyle.borderRadius,"
            "exportPadding:exportStyle.padding,exportMinHeight:exportStyle.minHeight,"
            "exportWeight:exportStyle.fontWeight,exportSize:exportStyle.fontSize,"
            "exportAlign:exportStyle.alignItems,"
            "heroStatsGap:blockGap(hero,stats),statsValidationGap:blockGap(stats,validation),"
            "validationMetaGap:blockGap(validation,meta),metaActionsGap:blockGap(meta,actions),"
            "actionsDistinct:backStyle.backgroundImage!==exportStyle.backgroundImage,"
            "descriptionWrap:getComputedStyle(description).overflowWrap,"
            "valueWrap:getComputedStyle(value).overflowWrap,"
            "documentContained:document.documentElement.scrollWidth<=document.documentElement.clientWidth+1,"
            "heroContained:hero.scrollWidth<=hero.clientWidth+1,"
            "metaContained:meta.scrollWidth<=meta.clientWidth+1,"
            "itemsContained:[...meta.children].every(item=>item.scrollWidth<=item.clientWidth+1)}"
            "})()"
        )
        assert detail == {
            "pageText": detail["pageText"],
            "muted": detail["muted"],
            "secondaryText": detail["secondaryText"],
            "secondarySurface": detail["secondarySurface"],
            "description": detail["pageText"],
            "label": detail["muted"],
            "value": detail["pageText"],
            "backText": "← Back to Content Packs",
            "backColor": detail["secondaryText"],
            "backBackground": detail["secondarySurface"],
            "backRadius": "9px",
            "backPadding": "10px 15px",
            "backMinHeight": "43px",
            "backWeight": "800",
            "backSize": "14px",
            "backAlign": "center",
            "exportRadius": "9px",
            "exportPadding": "10px 15px",
            "exportMinHeight": "43px",
            "exportWeight": "800",
            "exportSize": "14px",
            "exportAlign": "center",
            "heroStatsGap": 18,
            "statsValidationGap": 18,
            "validationMetaGap": 18,
            "metaActionsGap": 18,
            "actionsDistinct": True,
            "descriptionWrap": "anywhere",
            "valueWrap": "anywhere",
            "documentContained": True,
            "heroContained": True,
            "metaContained": True,
            "itemsContained": True,
        }

        browser.navigate(f"{base_url}/library?theme-consistency={theme}")
        browser.wait_for("document.querySelector('.library-folder') !== null")
        library = browser.evaluate(
            "(() => {"
            "const resolve = name => {const probe=document.createElement('span');"
            "probe.style.color=`var(${name})`;document.body.appendChild(probe);"
            "const value=getComputedStyle(probe).color;probe.remove();return value};"
            "const hero=document.querySelector('.library-hero');"
            "const stats=document.querySelector('.library-summary-grid');"
            "const smart=document.querySelector('.library-smart-views');"
            "const toolbar=document.querySelector('.library-toolbar');"
            "const tip=document.querySelector('.library-tip');"
            "const folder=document.querySelector('.library-folder');"
            "const footer=document.querySelector('.library-footer-actions');"
            "const header=folder.querySelector('.library-folder-header');"
            "const body=folder.querySelector('.library-folder-body');"
            "const title=folder.querySelector('h2');"
            "title.textContent='Folder-'+'unbroken-value-'.repeat(18);"
            "const selected=document.querySelector('.library-view-option.selected');"
            "const blockGap=(before,after)=>Math.round(after.getBoundingClientRect().top-"
            "before.getBoundingClientRect().bottom);"
            "return {"
            "pageText:resolve('--theme-page-text'),muted:resolve('--theme-muted-text'),"
            "accent:resolve('--theme-accent'),heading:resolve('--theme-heading'),"
            "heroImage:getComputedStyle(hero).backgroundImage,"
            "toolbarImage:getComputedStyle(toolbar).backgroundImage,"
            "toolbarColor:getComputedStyle(toolbar).backgroundColor,"
            "folderColor:getComputedStyle(folder).backgroundColor,"
            "headerColor:getComputedStyle(header).backgroundColor,"
            "bodyColor:getComputedStyle(body).backgroundColor,"
            "titleColor:getComputedStyle(title).color,titleWrap:getComputedStyle(title).overflowWrap,"
            "selectedBorder:getComputedStyle(selected).borderTopColor,"
            "heroStatsGap:blockGap(hero,stats),statsSmartGap:blockGap(stats,smart),"
            "smartToolbarGap:blockGap(smart,toolbar),"
            "toolbarTipGap:blockGap(toolbar,tip),tipFolderGap:blockGap(tip,folder),"
            "folderFooterGap:blockGap(document.querySelector('.library-folder:last-child'),footer),"
            "focusVisibleSupported:CSS.supports('selector(:focus-visible)'),"
            "documentContained:document.documentElement.scrollWidth<=document.documentElement.clientWidth+1,"
            "folderContained:folder.scrollWidth<=folder.clientWidth+1}"
            "})()"
        )
        assert library["heroImage"] != "none"
        assert library["toolbarImage"] == "none"
        assert library["toolbarColor"] != library["folderColor"]
        assert library["headerColor"] != library["bodyColor"]
        assert library["titleColor"] == library["heading"]
        assert library["titleWrap"] == "anywhere"
        assert library["selectedBorder"] == library["accent"]
        assert library["heroStatsGap"] == 18
        assert library["statsSmartGap"] == 18
        assert library["smartToolbarGap"] == 18
        assert 8 <= library["toolbarTipGap"] <= 12
        assert 8 <= library["tipFolderGap"] <= 12
        assert library["folderFooterGap"] == 18
        assert library["focusVisibleSupported"] is True
        assert library["documentContained"] is True
        assert library["folderContained"] is True

        browser.set_viewport(1280, 900)
        browser.navigate(f"{base_url}/library?theme-consistency-desktop={theme}")
        browser.wait_for("document.querySelector('.library-folder') !== null")
        desktop_gaps = browser.evaluate(
            "(() => {const hero=document.querySelector('.library-hero');"
            "const stats=document.querySelector('.library-summary-grid');"
            "const smart=document.querySelector('.library-smart-views');"
            "const toolbar=document.querySelector('.library-toolbar');"
            "const folders=[...document.querySelectorAll('.library-folder')];"
            "const footer=document.querySelector('.library-footer-actions');"
            "const gap=(before,after)=>Math.round(after.getBoundingClientRect().top-"
            "before.getBoundingClientRect().bottom);"
            "return {heroStats:gap(hero,stats),statsSmart:gap(stats,smart),"
            "smartToolbar:gap(smart,toolbar),"
            "folderFooter:gap(folders.at(-1),footer),"
            "contained:document.documentElement.scrollWidth<=document.documentElement.clientWidth+1};})()"
        )
        assert desktop_gaps == {
            "heroStats": 18,
            "statsSmart": 18,
            "smartToolbar": 18,
            "folderFooter": 18,
            "contained": True,
        }

    set_theme(original_theme)


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
        "statusRole:document.querySelector('.content-pack-status').getAttribute('role'),"
        "statusLive:document.querySelector('.content-pack-status').getAttribute('aria-live'),"
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
        "statusRole": "status",
        "statusLive": "polite",
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
        "(() => {const notice=document.querySelector('.content-pack-flashes .flash.success');"
        "return {text:notice.textContent,role:notice.getAttribute('role'),live:notice.getAttribute('aria-live')}})()"
    ) == {
        "text": f"Installed Study Pack '{pack_name}' successfully.",
        "role": "status",
        "live": "polite",
    }
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
        "(() => {const notice=document.querySelector('.content-pack-flashes .flash.success');"
        "return {text:notice.textContent,role:notice.getAttribute('role'),live:notice.getAttribute('aria-live')}})()"
    ) == {
        "text": "Study Pack import cancelled; staging files were removed.",
        "role": "status",
        "live": "polite",
    }


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
        "const control=name=>form.elements.namedItem(name);"
        "return {title:toggle.textContent.trim().replace(/^›\\s*/,''),"
        "description:document.querySelector('.medical-dataset-detail-content p').textContent,"
        "method:form.method,action:form.getAttribute('action'),"
        "packId:control('pack_id').value,datasetId:control('dataset_id').value,"
        "roundMin:control('round_size').min,roundMax:control('round_size').max,"
        "roundValue:control('round_size').value,direction:control('direction').value,"
        "csrf:form.querySelector('input[name=csrf_token]').value.length>0,"
        "associated:Array.from(document.querySelectorAll('[form='+form.id+']')).every(node=>node.form===form),"
        "expanded:toggle.getAttribute('aria-expanded'),"
        "controls:toggle.getAttribute('aria-controls'),"
        "controlled:document.getElementById(toggle.getAttribute('aria-controls'))===document.getElementById(toggle.dataset.medicalDetail),"
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
        "associated": True,
        "expanded": "false",
        "controls": "matching-detail-1",
        "controlled": True,
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
        "controls:toggle.getAttribute('aria-controls'),"
        "controlled:document.getElementById(toggle.getAttribute('aria-controls'))===document.getElementById(toggle.dataset.medicalDetail),"
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
        "controls": "anatomy-detail-1",
        "controlled": True,
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
        "expanded:toggle.getAttribute('aria-expanded'),controls:toggle.getAttribute('aria-controls'),"
        "controlled:document.getElementById(toggle.getAttribute('aria-controls'))===document.querySelector('.study-dataset-detail-row'),"
        "detailHidden:document.querySelector('.study-dataset-detail-row').hidden,"
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
        "expanded": "false",
        "controls": "it-match-1",
        "controlled": True,
        "detailHidden": True,
        "navCurrent": "page",
        "injected": False,
    }
    browser.click(".study-dataset-title-button")
    browser.wait_for(
        "!document.querySelector('.study-dataset-detail-row').hidden && "
        "document.querySelector('.study-dataset-title-button').getAttribute('aria-expanded')==='true'"
    )
    browser.evaluate(
        "Array.from(document.querySelectorAll('.medical-compact-panel-actions button'))"
        ".find(button=>button.textContent==='Collapse All').click()"
    )
    browser.wait_for(
        "document.querySelector('.study-dataset-detail-row').hidden && "
        "document.querySelector('.study-dataset-title-button').getAttribute('aria-expanded')==='false'"
    )
    browser.evaluate(
        "Array.from(document.querySelectorAll('.medical-compact-panel-actions button'))"
        ".find(button=>button.textContent==='Expand All').click()"
    )
    browser.wait_for(
        "!document.querySelector('.study-dataset-detail-row').hidden && "
        "document.querySelector('.study-dataset-title-button').getAttribute('aria-expanded')==='true'"
    )

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
        "expanded:toggle.getAttribute('aria-expanded'),controls:toggle.getAttribute('aria-controls'),"
        "controlled:document.getElementById(toggle.getAttribute('aria-controls'))===document.querySelector('.study-dataset-detail-row'),"
        "detailHidden:document.querySelector('.study-dataset-detail-row').hidden,"
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
        "expanded": "false",
        "controls": "it-image-1",
        "controlled": True,
        "detailHidden": True,
        "navCurrent": "page",
        "injected": False,
    }
    browser.click(".study-dataset-title-button")
    browser.wait_for(
        "!document.querySelector('.study-dataset-detail-row').hidden && "
        "document.querySelector('.study-dataset-title-button').getAttribute('aria-expanded')==='true'"
    )


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

    for folder_name, pack_id, pack_domain in (
        ("DLMS_Study_dlms121_it", "dlms121_it_filter", "information_technology"),
        ("DLMS_Study_dlms121_medical", "dlms121_medical_filter", "Medical"),
    ):
        filter_pack_root = browser_stack.data_root / "content_packs" / folder_name
        filter_data_root = filter_pack_root / "data"
        filter_data_root.mkdir(parents=True)
        (filter_pack_root / "manifest.json").write_text(
            json.dumps({
                "schema_version": 1,
                "id": pack_id,
                "name": f"DLMS-121 {pack_domain}",
                "version": "1.0",
                "description": "Domain filtering browser fixture.",
                "content_domain": pack_domain,
                "datasets": [{
                    "id": "terms",
                    "title": "Filter Terms",
                    "type": "matching",
                    "path": "data/terms.json",
                }],
            }),
            encoding="utf-8",
        )
        (filter_data_root / "terms.json").write_text(
            json.dumps({
                "schema_version": 1,
                "id": "terms",
                "title": "Filter Terms",
                "source": {"organization": "DLMS Browser", "license": "CC0"},
                "terms": [
                    {"term": "One", "definition": "First."},
                    {"term": "Two", "definition": "Second."},
                ],
            }),
            encoding="utf-8",
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

    filters = browser.evaluate(
        "(() => {const buttons=Array.from(document.querySelectorAll('.study-pack-domain-filter'));"
        "const cards=Array.from(document.querySelectorAll('.study-pack-collapsible'));"
        "return {label:document.querySelector('.study-pack-domain-filters').getAttribute('aria-label'),"
        "buttons:buttons.map(button=>({group:button.dataset.domainFilter,pressed:button.getAttribute('aria-pressed'),text:button.textContent.trim()})),"
        "groups:cards.map(card=>card.dataset.domainGroup),allVisible:cards.every(card=>!card.hidden),"
        "result:document.getElementById('studyPackResultCount').textContent.trim(),"
        "manage:document.querySelector('.study-pack-manage-link').getAttribute('href')};})()"
    )
    assert filters["label"] == "Filter installed content by domain"
    assert filters["buttons"][0]["group"] == "all"
    assert filters["buttons"][0]["pressed"] == "true"
    assert {button["group"] for button in filters["buttons"]} >= {
        "all", "it", "medical", "other",
    }
    assert "it" in filters["groups"]
    assert "medical" in filters["groups"]
    assert "other" in filters["groups"]
    assert filters["allVisible"] is True
    assert filters["result"].endswith("study packs")
    assert filters["manage"] == "/content-packs"

    # Native buttons remain keyboard-focusable; activation updates the
    # single-select pressed state and removes nonmatching cards from visual and
    # accessibility navigation.
    browser.activate()
    assert browser.evaluate(
        "(() => {const button=document.querySelector(\"[data-domain-filter='it']\");"
        "button.focus();return button.tagName==='BUTTON'&&button.type==='button'&&document.activeElement===button;})()"
    ) is True
    browser.click("[data-domain-filter='it']")
    browser.wait_for(
        "document.querySelector(\"[data-domain-filter='it']\").getAttribute('aria-pressed')==='true' && "
        "document.querySelector(\"[data-pack-id='dlms121_medical_filter']\").hidden"
    )
    it_filter = browser.evaluate(
        "(() => {const cards=Array.from(document.querySelectorAll('.study-pack-collapsible'));"
        "return {visible:cards.filter(card=>!card.hidden).map(card=>card.dataset.domainGroup),"
        "itHidden:document.querySelector(\"[data-pack-id='dlms121_it_filter']\").hidden,"
        "otherHidden:document.querySelector(\"[data-pack-id='browser_catalog']\").hidden,"
        "pressed:Array.from(document.querySelectorAll('.study-pack-domain-filter')).filter(button=>button.getAttribute('aria-pressed')==='true').map(button=>button.dataset.domainFilter),"
        "result:document.getElementById('studyPackResultCount').textContent.trim(),"
        "focused:document.activeElement.dataset.domainFilter};})()"
    )
    assert set(it_filter["visible"]) == {"it"}
    assert it_filter["itHidden"] is False
    assert it_filter["otherHidden"] is True
    assert it_filter["pressed"] == ["it"]
    assert it_filter["result"].startswith("Showing ")
    assert it_filter["focused"] == "it"

    # Hidden cards keep their disclosure state while bulk controls operate on
    # only the currently visible filter result.
    browser.evaluate(
        "document.querySelector(\"[data-pack-id='dlms121_it_filter']\").open=true;"
        "document.querySelector(\"[data-pack-id='dlms121_medical_filter']\").open=false;"
        "document.querySelector(\"[data-pack-id='browser_catalog']\").open=true; true"
    )
    browser.click("#collapseAllPacks")
    browser.wait_for(
        "!document.querySelector(\"[data-pack-id='dlms121_it_filter']\").open"
    )
    assert browser.evaluate(
        "document.querySelector(\"[data-pack-id='browser_catalog']\").open"
    ) is True
    browser.click("[data-domain-filter='medical']")
    browser.click("#expandAllPacks")
    browser.wait_for(
        "document.querySelector(\"[data-pack-id='dlms121_medical_filter']\").open"
    )
    hidden_state = browser.evaluate(
        "(() => ({it:document.querySelector(\"[data-pack-id='dlms121_it_filter']\").open,"
        "other:document.querySelector(\"[data-pack-id='browser_catalog']\").open,"
        "stored:JSON.parse(localStorage.getItem('dlms.studyPacks.openState.v1'))}))()"
    )
    assert hidden_state["it"] is False
    assert hidden_state["other"] is True
    assert hidden_state["stored"]["browser_catalog"] is True

    browser.navigate(f"{base_url}/study-packs")
    browser.wait_for(
        "document.querySelector(\"[data-domain-filter='all']\").getAttribute('aria-pressed')==='true'"
    )
    assert browser.evaluate(
        "Array.from(document.querySelectorAll('.study-pack-collapsible')).every(card=>!card.hidden)"
    ) is True

    browser.set_viewport(540, 900)
    narrow = browser.evaluate(
        "(() => {const toolbar=document.querySelector('.study-pack-toolbar');"
        "const filters=document.querySelector('.study-pack-domain-filters');"
        "return {overflow:toolbar.scrollWidth>toolbar.clientWidth,wrap:getComputedStyle(filters).flexWrap};})()"
    )
    assert narrow == {"overflow": False, "wrap": "wrap"}
    browser.set_viewport(1280, 900)

    filter_palettes = {}
    for theme in ("light", "dark", "purple-gold", "maroon-gold"):
        status = browser.evaluate(
            f"fetch('/api/theme', {{method:'POST', headers:{{'Content-Type':'application/json'}}, "
            f"body:JSON.stringify({{theme:{json.dumps(theme)}}})}}).then(response => response.status)"
        )
        assert status == 200
        browser.navigate(f"{base_url}/study-packs")
        browser.wait_for("document.querySelector(\"[data-domain-filter='it']\")")
        filter_palettes[theme] = browser.evaluate(
            "(() => {const active=document.querySelector(\"[data-domain-filter='all']\");"
            "const inactive=document.querySelector(\"[data-domain-filter='it']\");inactive.focus();"
            "const activeStyle=getComputedStyle(active);const inactiveStyle=getComputedStyle(inactive);"
            "return {active:[activeStyle.color,activeStyle.backgroundColor,activeStyle.borderColor],"
            "inactive:[inactiveStyle.color,inactiveStyle.backgroundColor,inactiveStyle.borderColor],"
            "pressed:active.getAttribute('aria-pressed')};})()"
        )
        assert filter_palettes[theme]["active"] != filter_palettes[theme]["inactive"]
        assert filter_palettes[theme]["pressed"] == "true"
    assert len({tuple(value["active"]) for value in filter_palettes.values()}) == 4

    status = browser.evaluate(
        "fetch('/api/theme', {method:'POST', headers:{'Content-Type':'application/json'}, "
        "body:JSON.stringify({theme:'purple-gold'})}).then(response => response.status)"
    )
    assert status == 200

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
        "!document.getElementById('dataset-browser_catalog-matching-1').hidden && "
        "document.querySelector(\"[aria-controls='dataset-browser_catalog-matching-1']\")"
        ".getAttribute('aria-expanded')==='true'"
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

    import_name = "law_import_20990907_120000_browser_catalog.txt"
    import_url_name = urllib.parse.quote(import_name, safe="!$&'()*+,/:;=@")
    (data_root / "law" / "imports" / import_name).write_text(
        "Browser catalog packet", encoding="utf-8"
    )

    registry_path = data_root / "config" / "law.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    case_id = "browser-catalog-case"
    case_url_id = urllib.parse.quote(case_id, safe="!$&'()*+,/:;=@")
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
        "open:open.getAttribute('data-law-navigation-url'),inlineOpen:open.getAttribute('onclick'),"
        "method:form.method,action:form.getAttribute('action'),"
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
        "open": f"/law/imports/{import_url_name}",
        "inlineOpen": None,
        "method": "post",
        "action": f"/law/imports/{import_url_name}/delete",
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
        "open:row.querySelector('.law-open-action').getAttribute('data-law-navigation-url'),"
        "inlineOpen:row.querySelector('.law-open-action').getAttribute('onclick'),method:form.method,"
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
        "open": f"/law/cases/{case_url_id}",
        "inlineOpen": None,
        "method": "post",
        "action": f"/law/cases/{case_url_id}/delete",
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


def test_law_import_detail_requires_exact_path_escapes_raw_packet_and_protects_form(browser_stack):
    browser = browser_stack.browser
    base_url = browser_stack.base_url
    normalized_name = "nested_browser-detail-packet.txt"
    raw_packet = (
        "Sources Used\n"
        'Source & <b id="lawDetailSourceInjected">unsafe</b> '
        '</textarea><script id="lawDetailScriptInjected">bad()</script> \u2028\u2029\n\n'
        "1. Case Brief\n"
        'Facts & <svg id="lawDetailFactsInjected"></svg>\n\n'
        "4. Rule Flashcards\n"
        "Q: What rule applies?\nA: The preserved rule."
    )
    import_path = browser_stack.data_root / "law" / "imports" / normalized_name
    import_path.write_text(raw_packet, encoding="utf-8")

    browser.set_viewport(760, 1100)
    browser.navigate(f"{base_url}/law/imports/nested/browser-detail-packet.txt")
    browser.wait_for("document.body.textContent.trim()==='Invalid import filename'")

    browser.navigate(f"{base_url}/law/imports/{normalized_name}?created_case=1")
    browser.wait_for(
        "document.querySelector('[data-nav-key=law][aria-current=page]') && "
        "document.querySelector('.law-detail-primary-form input[name=csrf_token]')"
    )
    detail = browser.evaluate(
        "(() => {const form=document.querySelector('.law-detail-primary-form');"
        "const stats=Array.from(document.querySelectorAll('.law-detail-stat strong')).map(node=>node.textContent);"
        "const cards=Array.from(document.querySelectorAll('.law-parse-card'));"
        "const textarea=document.querySelector('.law-raw-packet');"
        "return {heading:document.querySelector('.law-detail-heading h2').textContent,stats,"
        "status:document.querySelector('.law-status-pill').textContent,"
        "banner:document.querySelector('.law-message.success').textContent,"
        "titles:cards.map(card=>card.querySelector('h3').textContent),"
        "summary:Array.from(document.querySelectorAll('.law-message.success')).at(-1).textContent,"
        "raw:textarea.value,readOnly:textarea.readOnly,rows:textarea.rows,"
        "rawLabel:textarea.labels[0]?.textContent.trim(),"
        "method:form.method,action:form.getAttribute('action'),"
        "csrf:!!form.querySelector('input[name=csrf_token][type=hidden]'),"
        "createText:form.querySelector('button').textContent,"
        "confirm:form.querySelector('button').getAttribute('onclick'),"
        "backActions:Array.from(document.querySelectorAll('.law-detail-actions button')).map(button=>button.getAttribute('onclick')),"
        "primaryNav:document.querySelector('nav.dashboard-nav').getAttribute('aria-label'),"
        "systemNav:document.querySelector('nav.dashboard-nav-system').getAttribute('aria-label'),"
        "menuLabel:document.getElementById('menuButton').getAttribute('aria-label'),"
        "injected:!!document.getElementById('lawDetailSourceInjected')||"
        "!!document.getElementById('lawDetailScriptInjected')||"
        "!!document.getElementById('lawDetailFactsInjected')};})()"
    )
    assert detail == {
        "heading": normalized_name,
        "stats": [
            str(len(raw_packet.splitlines())),
            str(len(raw_packet)),
            f"{import_path.stat().st_size} bytes",
            detail["stats"][3],
        ],
        "status": "Raw Import",
        "banner": (
            "Case review created.The structured case file was saved and added to the "
            "Law Study registry."
        ),
        "titles": ["Sources Used", "1. Case Brief", "4. Rule Flashcards"],
        "summary": (
            "Parser preview:DLMS found 3 recognized sections. Nothing new is saved "
            "until you create the case review."
        ),
        "raw": raw_packet,
        "readOnly": True,
        "rows": 24,
        "rawLabel": "Raw Packet Text",
        "method": "post",
        "action": f"/law/imports/{normalized_name}/create_case",
        "csrf": True,
        "createText": "Create Case Review From Import",
        "confirm": (
            "return confirm('Create a structured Law Case Review from this import?');"
        ),
        "backActions": [
            "location.href='/law/imports'",
            "location.href='/law/cases'",
            "location.href='/law/import'",
        ],
        "primaryNav": "Primary navigation",
        "systemNav": "System navigation",
        "menuLabel": "Toggle navigation",
        "injected": False,
    }
    assert len(detail["stats"][3]) == 19
    assert detail["stats"][3][4] == "-"
    assert detail["stats"][3][7] == "-"

    browser.click("#menuButton")
    browser.wait_for("document.getElementById('dashboardSidebar').classList.contains('open')")
    assert browser.evaluate(
        "document.getElementById('menuButton').getAttribute('aria-expanded')"
    ) == "true"
    browser.click(".law-subpage-header h1")
    browser.wait_for("!document.getElementById('dashboardSidebar').classList.contains('open')")


def test_law_guided_create_import_preview_and_cancel_workflow(browser_stack):
    browser = browser_stack.browser
    base_url = browser_stack.base_url
    case_name = 'Browser Guided & <img id="lawGuidedCaseInjected"> Case'
    raw_packet = (
        '  Sources Used\nSource & </textarea><script id="lawGuidedRawInjected">bad()</script> '
        '\u2028line\u2029paragraph\n\n1. Case Brief\nBrowser facts.  '
    )
    stripped_packet = raw_packet.strip()

    browser.set_viewport(760, 1100)
    browser.navigate(f"{base_url}/law/create")
    browser.wait_for(
        "document.querySelector('[data-nav-key=law][aria-current=page]') && "
        "document.querySelector('.law-form input[name=csrf_token]')"
    )
    initial = browser.evaluate(
        "(() => {const form=document.querySelector('.law-form');"
        "return {heading:document.querySelector('h1').textContent,method:form.method,"
        "action:form.getAttribute('action'),csrf:!!form.querySelector('input[name=csrf_token][type=hidden]'),"
        "caseRequired:form.querySelector('[name=case_name]').required,"
        "placeholder:form.querySelector('[name=case_name]').placeholder,"
        "course:form.querySelector('[name=course]').value,provider:form.querySelector('[name=ai_provider]').value,"
        "checked:Array.from(form.querySelectorAll('input[type=checkbox]:checked')).map(node=>node.name),"
        "current:document.querySelector('[data-nav-key=law]').getAttribute('aria-current'),"
        "primaryNav:document.querySelector('nav.dashboard-nav').getAttribute('aria-label'),"
        "systemNav:document.querySelector('nav.dashboard-nav-system').getAttribute('aria-label'),"
        "menuLabel:document.getElementById('menuButton').getAttribute('aria-label')};})()"
    )
    assert initial == {
        "heading": "Create Case Review",
        "method": "post",
        "action": "/law/create",
        "csrf": True,
        "caseRequired": True,
        "placeholder": "Example: Palsgraf v. Long Island Railroad Co.",
        "course": "Torts",
        "provider": "chatgpt",
        "checked": [
            "include_case_brief",
            "include_socratic",
            "include_irac",
            "include_flashcards",
        ],
        "current": "page",
        "primaryNav": "Primary navigation",
        "systemNav": "System navigation",
        "menuLabel": "Toggle navigation",
    }

    browser.evaluate(
        "(() => {const form=document.querySelector('.law-form');"
        f"form.querySelector('[name=case_name]').value={json.dumps(case_name)};"
        "form.querySelector('[name=ai_provider]').value='chatgpt';"
        "form.querySelector('[name=include_socratic]').checked=false;"
        "form.querySelector('[name=include_flashcards]').checked=false;return true;})()"
    )
    browser.click("form[action='/law/create'] button[type=submit]")
    browser.wait_for("document.getElementById('lawPromptBox') !== null")
    generated = browser.evaluate(
        "(() => {const form=document.querySelector('.law-form');const prompt=document.getElementById('lawPromptBox');"
        "const open=Array.from(document.querySelectorAll('.law-generated-panel button')).find(button=>button.textContent.includes('Open AI'));"
        "return {caseValue:form.querySelector('[name=case_name]').value,course:form.querySelector('[name=course]').value,"
        "provider:form.querySelector('[name=ai_provider]').value,prompt:prompt.value,rows:prompt.rows,"
        "openAction:open.getAttribute('onclick'),"
        "checked:Array.from(form.querySelectorAll('input[type=checkbox]:checked')).map(node=>node.name),"
        "injected:!!document.getElementById('lawGuidedCaseInjected')};})()"
    )
    assert generated["caseValue"] == case_name
    assert generated["course"] == "Torts"
    assert generated["provider"] == "chatgpt"
    assert generated["rows"] == 18
    assert generated["openAction"] == 'copyPromptAndOpenAi("https://chatgpt.com/")'
    assert generated["checked"] == ["include_case_brief", "include_irac"]
    assert generated["injected"] is False
    assert case_name in generated["prompt"]
    assert "1. Case Brief" in generated["prompt"]
    assert "3. IRAC Drill" in generated["prompt"]
    assert "Five cold-call style questions" not in generated["prompt"]
    assert "Five active-recall flashcards" not in generated["prompt"]

    registry_path = browser_stack.data_root / "config" / "law.json"
    pending = json.loads(registry_path.read_text(encoding="utf-8"))["pending_case_workflow"]
    assert pending["case_name"] == case_name
    assert pending["course"] == "Torts"
    assert pending["case_slug"] == "browser_guided_img_id_lawguidedcaseinjected_case"

    browser.navigate(
        f"{base_url}/law/import?case_name=Stale%20Bookmark&case_slug=stale-bookmark"
    )
    browser.wait_for(
        "document.querySelector('.law-workflow-banner') && "
        "document.querySelectorAll('input[name=csrf_token]').length === 2"
    )
    active = browser.evaluate(
        "(() => {const banner=document.querySelector('.law-workflow-banner');"
        "const form=document.querySelector('form[action=\"/law/import\"]');const cancel=banner.querySelector('form');"
        "return {name:banner.querySelector('strong').textContent,slug:banner.querySelector('small').textContent,"
        "hiddenName:form.querySelector('[name=case_name]').value,hiddenSlug:form.querySelector('[name=case_slug]').value,"
        "method:form.method,action:form.getAttribute('action'),csrf:!!form.querySelector('input[name=csrf_token]'),"
        "cancelMethod:cancel.method,cancelAction:cancel.getAttribute('action'),"
        "cancelCsrf:!!cancel.querySelector('input[name=csrf_token]'),cancelConfirm:cancel.getAttribute('onsubmit')};})()"
    )
    assert active == {
        "name": case_name,
        "slug": "File slug: browser_guided_img_id_lawguidedcaseinjected_case",
        "hiddenName": case_name,
        "hiddenSlug": "browser_guided_img_id_lawguidedcaseinjected_case",
        "method": "post",
        "action": "/law/import",
        "csrf": True,
        "cancelMethod": "post",
        "cancelAction": "/law/workflow/cancel",
        "cancelCsrf": True,
        "cancelConfirm": (
            "return confirm('Cancel the active Law Study workflow? This will not delete "
            "saved imports or case reviews.');"
        ),
    }
    assert browser.evaluate(
        "!document.body.textContent.includes('Stale Bookmark') && "
        "!document.body.textContent.includes('stale-bookmark')"
    ) is True

    browser.evaluate(
        "(() => {const field=document.querySelector('[name=raw_packet]');"
        f"field.value={json.dumps(raw_packet)};return true;}})()"
    )
    browser.click("form[action='/law/import'] button[value=preview]")
    browser.wait_for("document.querySelector('.law-preview-panel') !== null")
    preview = browser.evaluate(
        "(() => {const field=document.querySelector('[name=raw_packet]');"
        "const metrics=Array.from(document.querySelectorAll('.law-metric-card strong')).map(node=>node.textContent);"
        "return {raw:field.value,rows:field.rows,placeholder:field.placeholder,metrics,"
        "injected:!!document.getElementById('lawGuidedRawInjected')};})()"
    )
    assert preview == {
        "raw": stripped_packet,
        "rows": 22,
        "placeholder": (
            "Paste the AI-generated case brief, Socratic review, IRAC drill, and "
            "flashcards here..."
        ),
        "metrics": [
            str(len(stripped_packet.splitlines())),
            str(len(stripped_packet) + stripped_packet.count("\n")),
            "Ready",
        ],
        "injected": False,
    }

    browser.evaluate(
        "sessionStorage.removeItem('lawCancelConfirm');"
        "window.confirm=message=>{sessionStorage.setItem('lawCancelConfirm',message);return true};true"
    )
    browser.click("form[action='/law/workflow/cancel'] button[type=submit]")
    browser.wait_for("document.body.textContent.includes('Active case workflow cancelled.')")
    assert browser.evaluate("sessionStorage.getItem('lawCancelConfirm')") == (
        "Cancel the active Law Study workflow? This will not delete saved imports or case reviews."
    )
    cancelled = json.loads(registry_path.read_text(encoding="utf-8"))
    assert "pending_case_workflow" not in cancelled
    assert browser.evaluate(
        "document.body.textContent.includes('No active case workflow.') && "
        "document.querySelector('[name=case_name]').value === '' && "
        "document.querySelector('[name=case_slug]').value === ''"
    ) is True
    browser.navigate(
        f"{base_url}/law/import?case_name=Explicit%20Case&case_slug=explicit-case"
    )
    browser.wait_for(
        "document.querySelector('[name=case_name]').value === 'Explicit Case' && "
        "document.querySelector('[name=case_slug]').value === 'explicit-case'"
    )


def test_segment19_smart_pdf_and_advanced_authoring_external_templates(browser_stack):
    browser = browser_stack.browser
    base_url = browser_stack.base_url
    data_root = browser_stack.data_root

    content_packs_root = data_root / "content_packs"
    held_content_packs_root = data_root / "content_packs-segment19-held"
    content_packs_root.rename(held_content_packs_root)
    content_packs_root.mkdir()
    browser.navigate(f"{base_url}/admin/image-editor")
    browser.wait_for(
        "EDITOR_DATA === null && "
        "document.body.textContent.includes('No installed content pack currently declares an image dataset.')"
    )
    empty_picker = browser.evaluate(
        "(() => {const select=document.getElementById('datasetKey');"
        "const option=document.createElement('option');option.value='empty::quiz::selection';"
        "select.appendChild(option);select.value=option.value;"
        "select.dispatchEvent(new Event('change'));return {"
        "pack:document.getElementById('packField').value,"
        "kind:document.getElementById('kindField').value,"
        "dataset:document.getElementById('datasetField').value,"
        "workspace:!!document.getElementById('editorImage')};})()"
    )
    assert empty_picker == {
        "pack": "empty",
        "kind": "quiz",
        "dataset": "selection",
        "workspace": False,
    }
    content_packs_root.rmdir()
    held_content_packs_root.rename(content_packs_root)

    browser.navigate(
        f"{base_url}/admin/image-editor?pack=missing&dataset=broken&kind=hotspot"
    )
    browser.wait_for(
        "EDITOR_DATA === null && document.querySelector('.flash.error')"
    )
    empty_editor = browser.evaluate(
        "(() => {const select=document.getElementById('datasetKey');"
        "const option=document.createElement('option');option.value='pack::hotspot::dataset';"
        "select.appendChild(option);select.value=option.value;"
        "select.dispatchEvent(new Event('change'));return {"
        "error:document.querySelector('.flash.error').textContent.trim(),"
        "pack:document.getElementById('packField').value,"
        "kind:document.getElementById('kindField').value,"
        "dataset:document.getElementById('datasetField').value,"
        "workspace:!!document.getElementById('editorImage')};})()"
    )
    assert empty_editor == {
        "error": (
            "The selected image dataset could not be loaded. Restart DLMS and retry. "
            "If it persists, report this action and your DLMS version."
        ),
        "pack": "pack",
        "kind": "hotspot",
        "dataset": "dataset",
        "workspace": False,
    }

    browser.navigate(f"{base_url}/pdf-import")
    browser.wait_for(
        "window.dlmsCsrfToken && "
        "document.querySelector('form[action=\"/pdf-import/analyze\"] input[name=csrf_token]')"
    )
    pdf_landing = browser.evaluate(
        "(() => {const form=document.querySelector('form[action=\"/pdf-import/analyze\"]');"
        "return {title:document.title,method:form.method,enctype:form.enctype,"
        "file:form.querySelector('[name=pdf_file]').required,"
        "rights:form.querySelector('[name=rights_ok]').required,"
        "csrf:form.querySelector('[name=csrf_token]').value.length>0,"
        "nav:document.querySelector('[data-nav-key=build]').getAttribute('aria-current')};})()"
    )
    assert pdf_landing == {
        "title": "PDF & Image Import - DLMS",
        "method": "post",
        "enctype": "multipart/form-data",
        "file": True,
        "rights": True,
        "csrf": True,
        "nav": None,
    }

    review_root = data_root / "pdf_import_drafts"
    review_root.mkdir(exist_ok=True)
    hostile = 'Browser </textarea><img id="segment19Injected"> & Review'
    question_draft = {
        "id": "browser_question_review",
        "source_name": hostile,
        "page_count": 2,
        "document_type": "question_bank",
        "detection": {"recovery_mode": True},
        "recovery_mode": True,
        "quiz_title": hostile,
        "exam_minutes": 45,
        "summary": {"detected": 1, "complete": 0, "review": 1, "incomplete": 0},
        "questions": [{
            "number": 7,
            "question": hostile,
            "choices": [{"label": "A", "text": hostile}, {"label": "B", "text": "Safe"}],
            "correct": "B",
            "declared_answer_text": "Safe",
            "explanation": hostile,
            "choice_feedback": {"A": hostile},
            "pages": [1, 2],
            "status": "review",
            "issues": [hostile],
        }],
    }
    glossary_draft = {
        "id": "browser_term_review",
        "source_name": hostile,
        "page_count": 1,
        "document_type": "glossary",
        "detection": {"recovery_mode": False},
        "recovery_mode": False,
        "quiz_title": hostile,
        "exam_minutes": 30,
        "summary": {"detected": 1, "complete": 1, "review": 0, "incomplete": 0},
        "terms": [{
            "number": 3,
            "term": hostile,
            "definition": hostile,
            "pages": [1],
            "status": "complete",
            "issues": [],
        }],
    }
    (review_root / "browser_question_review.json").write_text(
        json.dumps(question_draft), encoding="utf-8"
    )
    (review_root / "browser_term_review.json").write_text(
        json.dumps(glossary_draft), encoding="utf-8"
    )

    for draft_id, form_id, selector, live_id in (
        ("browser_question_review", "pdfReviewForm", '[data-pdf-role="select"]', "pdfSelectionCount"),
        ("browser_term_review", "pdfTermReviewForm", '[data-term-role="select"]', "pdfTermSelectionCount"),
    ):
        browser.navigate(f"{base_url}/pdf-import/review/{draft_id}")
        browser.wait_for(
            f"document.querySelector('#{form_id} input[name=csrf_token]') && "
            f"document.querySelector({json.dumps(selector)})"
        )
        state = browser.evaluate(
            f"(() => {{const form=document.getElementById('{form_id}');"
            f"document.querySelector({json.dumps(selector)}).click();"
            f"return {{method:form.method,action:form.getAttribute('action'),"
            f"selected:document.getElementById('{live_id}').textContent,"
            "csrf:form.querySelector('[name=csrf_token]').value.length>0,"
            "injected:!!document.getElementById('segment19Injected')};})()"
        )
        assert state == {
            "method": "post",
            "action": f"/pdf-import/save/{draft_id}",
            "selected": "1 selected",
            "csrf": True,
            "injected": False,
        }
        if draft_id == "browser_question_review":
            editor_state = browser.evaluate(
                "(() => {const card=document.querySelector('.pdf-import-question-card');"
                "const initialRows=[...card.querySelectorAll('[data-pdf-role=choice-row]')];"
                "const activeRadio=initialRows[0].querySelector('[data-pdf-role=single-correct]');activeRadio.focus();"
                "const initialActiveFocusWorks=document.activeElement===activeRadio;"
                "const inactiveCheckbox=initialRows[0].querySelector('[data-pdf-role=multiple-correct]');inactiveCheckbox.focus();"
                "const initialSingleOnly=initialRows.every(row=>{const single=row.querySelector('[data-pdf-role=single-correct]'),multiple=row.querySelector('[data-pdf-role=multiple-correct]');"
                "return getComputedStyle(single.closest('label')).display!=='none'&&!single.disabled&&getComputedStyle(multiple.closest('label')).display==='none'&&multiple.disabled;});"
                "const initialInactiveFocusBlocked=document.activeElement!==inactiveCheckbox;"
                "card.querySelector('[data-pdf-action=choice-add]').click();"
                "let rows=[...card.querySelectorAll('[data-pdf-role=choice-row]')];"
                "rows[2].querySelector('[data-pdf-role=choice]').value='Third answer';"
                "rows[2].querySelector('[data-pdf-action=choice-up]').click();"
                "const mode=card.querySelector('[data-pdf-role=answer-mode]');"
                "mode.value='multiple';mode.dispatchEvent(new Event('change'));"
                "rows=[...card.querySelectorAll('[data-pdf-role=choice-row]')];"
                "const retained=rows.find(row=>row.querySelector('[data-pdf-role=choice]').value==='Safe').querySelector('[data-pdf-role=multiple-correct]').checked;"
                "rows[0].querySelector('[data-pdf-role=multiple-correct]').checked=true;"
                "rows[1].querySelector('[data-pdf-role=multiple-correct]').checked=true;"
                "mode.value='single';mode.dispatchEvent(new Event('change'));"
                "const safeguardMessage=card.querySelector('[data-pdf-role=choice-message]').textContent;"
                "const beforeDelete=rows.map(row=>row.dataset.choiceLabel);"
                "rows[2].querySelector('[data-pdf-action=choice-delete]').click();"
                "const finalRows=[...card.querySelectorAll('[data-pdf-role=choice-row]')];"
                "const multipleOnly=finalRows.every(row=>{const single=row.querySelector('[data-pdf-role=single-correct]'),multiple=row.querySelector('[data-pdf-role=multiple-correct]');"
                "return getComputedStyle(single.closest('label')).display==='none'&&single.disabled&&getComputedStyle(multiple.closest('label')).display!=='none'&&!multiple.disabled;});"
                "return {count:card.querySelectorAll('[data-pdf-role=choice-row]').length,"
                "labels:[...card.querySelectorAll('[data-pdf-role=choice-row]')].map(row=>row.dataset.choiceLabel),"
                "beforeDelete,mode:mode.value,safeguardMessage,retained,initialSingleOnly,initialActiveFocusWorks,initialInactiveFocusBlocked,multipleOnly,"
                "addDisabled:card.querySelector('[data-pdf-action=choice-add]').disabled};})()"
            )
            assert editor_state == {
                "count": 2,
                "labels": ["A", "B"],
                "beforeDelete": ["A", "B", "C"],
                "mode": "multiple",
                "safeguardMessage": "Choose one correct answer before switching to single-answer mode.",
                "retained": True,
                "initialSingleOnly": True,
                "initialActiveFocusWorks": True,
                "initialInactiveFocusBlocked": True,
                "multipleOnly": True,
                "addDisabled": False,
            }
            browser.set_viewport(390, 820)
            assert browser.evaluate(
                "document.documentElement.scrollWidth <= window.innerWidth + 1"
            ) is True
            browser.set_viewport(1280, 1000)

    question_bank_root = data_root / "pdf_question_banks"
    term_bank_root = data_root / "pdf_terminology_banks"
    question_bank_root.mkdir(exist_ok=True)
    term_bank_root.mkdir(exist_ok=True)
    bank_title = (
        'Browser bank "double" \'single\' <strong>& </script>'
        '<img id="pdfBankTitleInjected"> \\ \u2028\u2029'
    )
    (question_bank_root / "browser_question_bank.json").write_text(
        json.dumps({
            "id": "browser_question_bank",
            "title": bank_title,
            "source_name": hostile,
            "default_exam_minutes": 60,
            "used_question_numbers": [1],
            "generated_quizzes": [{"quiz_id": 1}],
            "questions": [
                {"number": 1, "original_number": 1, "question": hostile, "active": True, "pages": [1]},
                {"number": 2, "original_number": 2, "question": "Excluded", "active": False, "pages": [2]},
            ],
        }),
        encoding="utf-8",
    )
    (term_bank_root / "browser_term_bank.json").write_text(
        json.dumps({
            "id": "browser_term_bank",
            "title": bank_title,
            "source_name": hostile,
            "default_exam_minutes": 60,
            "used_term_numbers": [1],
            "generated_quizzes": [{"quiz_id": 1}],
            "terms": [
                {"number": 1, "term": hostile, "definition": hostile, "active": True, "pages": [1]},
                {"number": 2, "term": "Excluded", "definition": "Preserved", "active": False, "pages": [2]},
            ],
        }),
        encoding="utf-8",
    )
    for url, action, count_name in (
        ("/pdf-import/bank/browser_question_bank", "/pdf-import/bank/browser_question_bank/generate", "question_count"),
        ("/pdf-import/terms/browser_term_bank", "/pdf-import/terms/browser_term_bank/generate", "term_count"),
    ):
        browser.navigate(f"{base_url}{url}")
        browser.wait_for(f"document.querySelector('form[action=\"{action}\"] input[name=csrf_token]')")
        bank_state = browser.evaluate(
            f"(() => {{const form=document.querySelector('form[action=\"{action}\"]');"
            f"return {{count:form.querySelector('[name={count_name}]').value,"
            "csrf:form.querySelector('[name=csrf_token]').value.length>0,"
            "excluded:document.body.textContent.includes('EXCLUDED'),"
            "injected:!!document.getElementById('segment19Injected')};})()"
        )
        assert bank_state == {"count": "1", "csrf": True, "excluded": True, "injected": False}

    browser.navigate(f"{base_url}/pdf-import?browser-banks=1")
    browser.wait_for(
        "document.querySelectorAll('.pdf-bank-manage-action[data-pdf-bank-title]').length === 2"
    )
    confirmation_state = browser.evaluate(
        "(() => {const forms=[...document.querySelectorAll('.pdf-bank-manage-action')];"
        "const messages=[];window.confirm=message=>{messages.push(message);return false};"
        "forms.forEach(form=>form.requestSubmit());return {messages,"
        "titles:forms.map(form=>form.dataset.pdfBankTitle),"
        "inline:forms.map(form=>form.getAttribute('onsubmit')),injected:"
        "!!document.getElementById('pdfBankTitleInjected')};})()"
    )
    assert confirmation_state == {
        "messages": [
            f"Delete source question bank “{bank_title}”? Existing quizzes generated from it will remain available.",
            f"Delete source terminology bank “{bank_title}”? Existing quizzes generated from it will remain available.",
        ],
        "titles": [bank_title, bank_title],
        "inline": [None, None],
        "injected": False,
    }

    browser.navigate(f"{base_url}/study-packs/ai-builder?domain=Medical&from=medical")
    browser.wait_for(
        "window.dlmsCsrfToken && document.querySelector('.medical-ai-builder-form input[name=csrf_token]')"
    )
    defaults = browser.evaluate(
        "(() => {const form=document.querySelector('.medical-ai-builder-form');"
        "return {domain:form.domain.value,difficulty:form.difficulty.value,"
        "matching:form.include_matching.checked,images:form.include_images.checked,"
        "multipleChoice:form.include_multiple_choice.checked,"
        "noticeHidden:document.getElementById('medicalGuardrailNotice').classList.contains('is-hidden'),"
        "back:document.querySelector('.medical-ai-action-row a').getAttribute('href')};})()"
    )
    assert defaults == {
        "domain": "Medical",
        "difficulty": "Foundational",
        "matching": True,
        "images": True,
        "multipleChoice": False,
        "noticeHidden": False,
        "back": "/medical",
    }
    browser.evaluate(
        "(() => {const form=document.querySelector('.medical-ai-builder-form');"
        "form.topic.value='Browser Segment 19';form.requestSubmit();return true;})()"
    )
    browser.wait_for(
        "document.getElementById('studyPrompt') && "
        "document.querySelector('form[action=\"/study-packs/ai-builder/import\"] input[name=csrf_token]')"
    )
    ai_state = browser.evaluate(
        "(() => {const prompt=document.getElementById('studyPrompt').value;"
        "const upload=document.querySelector('form[action=\"/study-packs/ai-builder/import\"]');"
        "return {topic:prompt.includes('Browser Segment 19'),medical:prompt.includes('MEDICAL-SPECIFIC SAFETY'),"
        "zip:upload.querySelector('[name=pack_zip]').required,"
        "csrf:upload.querySelector('[name=csrf_token]').value.length>0};})()"
    )
    assert ai_state == {"topic": True, "medical": True, "zip": True, "csrf": True}

    image_path = data_root / "segment19-browser.png"
    image_path.write_bytes(base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
    ))
    browser.navigate(f"{base_url}/study-packs/image-builder")
    browser.wait_for(
        "document.querySelector('.image-builder-upload-form input[name=csrf_token]') && "
        "document.querySelector('[name=study_images]')"
    )
    browser.set_files("[name=study_images]", [image_path])
    browser.click(".image-builder-upload-form button[type=submit]")
    browser.wait_for("document.getElementById('builderForm') && typeof DRAFT === 'object'")
    image_builder_state = browser.evaluate(
        "(() => {const form=document.getElementById('builderForm');"
        "return {action:form.getAttribute('action'),method:form.method,images:DRAFT.images.length,"
        "payload:!!document.getElementById('builderPayload'),rights:form.rights_ok.required,"
        "csrf:form.querySelector('[name=csrf_token]').value.length>0,questions:document.querySelectorAll('.image-builder-question-card').length,"
        "imageDescription:document.querySelector('.image-alt-input').getAttribute('aria-label'),"
        "choiceText:document.querySelector('.choice-text').getAttribute('aria-label'),"
        "correctChoice:document.querySelector('.choice-correct').getAttribute('aria-label'),"
        "hotspotStageRole:document.querySelector('.image-builder-hotspot-stage').getAttribute('role'),"
        "hotspotStageTabIndex:document.querySelector('.image-builder-hotspot-stage').tabIndex};})()"
    )
    assert image_builder_state == {
        "action": "/study-packs/image-builder/save",
        "method": "post",
        "images": 1,
        "payload": True,
        "rights": True,
        "csrf": True,
        "questions": 1,
        "imageDescription": "Accessible description for segment19-browser.png",
        "choiceText": "Answer choice text",
        "correctChoice": "Mark this answer correct",
        "hotspotStageRole": "group",
        "hotspotStageTabIndex": 0,
    }
    image_builder_keyboard = browser.evaluate(
        "(() => {const card=document.querySelector('.image-builder-question-card');"
        "const type=card.querySelector('.q-type');type.value='hotspot';"
        "type.dispatchEvent(new Event('change',{bubbles:true}));"
        "const stage=card.querySelector('.image-builder-hotspot-stage');stage.focus();"
        "stage.dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowRight',bubbles:true}));"
        "stage.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}));"
        "return {center:card._shape.center,status:card.querySelector('.hotspot-status').textContent,"
        "cursorHidden:card.querySelector('.hotspot-keyboard-cursor').hidden};})()"
    )
    assert image_builder_keyboard == {
        "center": [0.52, 0.5],
        "status": "Circle center placed with keyboard.",
        "cursorHidden": False,
    }

    pack_root = data_root / "content_packs" / "DLMS_Study_segment19_browser_editor"
    (pack_root / "data").mkdir(parents=True)
    (pack_root / "images").mkdir()
    (pack_root / "images" / "diagram.png").write_bytes(image_path.read_bytes())
    (pack_root / "manifest.json").write_text(json.dumps({
        "schema_version": 1,
        "id": "segment19_editor",
        "name": "Segment 19 Editor",
        "version": "1.0.0",
        "content_domain": "Science",
        "datasets": [],
        "image_datasets": [{
            "id": "visuals", "title": "Visuals", "type": "hotspot", "path": "data/visuals.json"
        }],
        "quiz_datasets": [],
    }), encoding="utf-8")
    editor_data_path = pack_root / "data" / "visuals.json"
    editor_data_path.write_text(json.dumps({
        "schema_version": 1,
        "id": "visuals",
        "title": "Segment 19 Visuals",
        "source": {"organization": "DLMS Browser", "license": "CC0"},
        "images": [{
            "id": "diagram",
            "file": "images/diagram.png",
            "alt_text": "Segment 19 diagram",
            "source": {"organization": "DLMS Browser", "license": "CC0"},
            "edits": [],
            "hotspots": [{
                "id": "target", "label": "Target", "prompt": "Identify target.",
                "shape": {"type": "circle", "x": .5, "y": .5, "radius": .1},
            }],
        }],
    }), encoding="utf-8")
    browser.navigate(
        f"{base_url}/admin/image-editor?pack=segment19_editor&dataset=visuals&kind=hotspot"
    )
    browser.wait_for(
        "window.dlmsCsrfToken && typeof EDITOR_DATA === 'object' && "
        "EDITOR_DATA.images.length === 1 && document.getElementById('saveBtn')"
    )
    editor_state = browser.evaluate(
        "(() => ({pack:EDITOR_DATA.pack_id,dataset:EDITOR_DATA.dataset_id,kind:EDITOR_DATA.dataset_kind,"
        "status:document.getElementById('editorStatus').textContent,"
        "statusRole:document.getElementById('editorStatus').getAttribute('role'),"
        "statusLive:document.getElementById('editorStatus').getAttribute('aria-live'),"
        "activeMode:document.getElementById('hotspotModeBtn').getAttribute('aria-pressed'),"
        "inactiveMode:document.getElementById('prepModeBtn').getAttribute('aria-pressed'),"
        "stageRole:document.getElementById('editorStage').getAttribute('role'),"
        "stageTabIndex:document.getElementById('editorStage').tabIndex,"
        "menuLabel:document.getElementById('menuButton').getAttribute('aria-label')}))()"
    )
    assert editor_state == {
        "pack": "segment19_editor",
        "dataset": "visuals",
        "kind": "hotspot",
        "status": "Clickable-region mode.",
        "statusRole": "status",
        "statusLive": "polite",
        "activeMode": "true",
        "inactiveMode": "false",
        "stageRole": "group",
        "stageTabIndex": 0,
        "menuLabel": "Toggle navigation",
    }
    editor_keyboard = browser.evaluate(
        "(() => {const stage=document.getElementById('editorStage');stage.focus();"
        "stage.dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowRight',bubbles:true}));"
        "stage.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}));"
        "return {shape:currentShape(),cursorHidden:document.getElementById('editorKeyboardCursor').hidden};})()"
    )
    assert editor_keyboard["cursorHidden"] is False
    assert editor_keyboard["shape"]["type"] == "circle"
    assert editor_keyboard["shape"]["x"] == pytest.approx(0.52, abs=0.002)
    assert editor_keyboard["shape"]["y"] == pytest.approx(0.5, abs=0.002)
    assert editor_keyboard["shape"]["radius"] == 0.1
    browser.click("#loadExistingBtn")
    browser.evaluate(
        "window.confirm=()=>true;document.getElementById('saveBtn').click();true"
    )
    browser.wait_for("document.getElementById('editorStatus').textContent.includes('Saved Target')")
    browser.evaluate(
        "document.getElementById('prepModeBtn').click();"
        "imageEdits=[{type:'mask',x:.1,y:.1,w:.2,h:.2,style:'blur'}];"
        "document.getElementById('saveEditsBtn').click();true"
    )
    browser.wait_for("document.getElementById('editorStatus').textContent.includes('Image prep saved')")
    assert browser.evaluate(
        "document.getElementById('prepModeBtn').getAttribute('aria-pressed')==='true' && "
        "document.getElementById('hotspotModeBtn').getAttribute('aria-pressed')==='false'"
    ) is True
    saved_editor_data = json.loads(editor_data_path.read_text(encoding="utf-8"))
    assert saved_editor_data["images"][0]["hotspots"][0]["shape"] == {
        "type": "circle", "x": .5, "y": .5, "radius": .1
    }
    assert saved_editor_data["images"][0]["edits"] == [
        {"type": "mask", "x": .1, "y": .1, "w": .2, "h": .2, "style": "blur"}
    ]


def test_external_ai_shared_review_editor_and_publication(browser_stack):
    browser = browser_stack.browser
    base_url = browser_stack.base_url
    browser.navigate(f"{base_url}/upload")
    browser.wait_for(
        "document.querySelector('a[href=\"/external-ai/quiz-builder\"]')"
    )
    browser.click('a[href="/external-ai/quiz-builder"]')
    browser.wait_for(
        "location.pathname === '/external-ai/quiz-builder' && "
        "document.getElementById('externalAiBuilderForm')"
    )
    builder_initial = browser.evaluate(
        "(() => ({copyDisabled:document.getElementById('externalAiCopyPrompt').disabled,"
        "responseLabel:document.querySelector('label[for=externalAiResponse] span').textContent,"
        "topNav:!!document.querySelector('.dashboard-nav-item[href=\"/external-ai/quiz-builder\"]'),"
        "csrf:document.querySelector('#externalAiBuilderForm input[name=csrf_token]').value.length>0}))()"
    )
    assert builder_initial == {
        "copyDisabled": True,
        "responseLabel": "AI Response",
        "topNav": False,
        "csrf": True,
    }
    browser.evaluate(
        "document.querySelector('[name=topic]').value='Neutral browser systems';"
        "document.querySelector('[name=question_count]').value='1';true"
    )
    browser.click('button[formaction="/external-ai/quiz-builder/prompt"]')
    browser.wait_for(
        "document.getElementById('externalAiPrompt').value.includes('Return exactly 1 question.') && "
        "!document.getElementById('externalAiCopyPrompt').disabled"
    )
    browser.click("#externalAiCopyPrompt")
    browser.wait_for(
        "document.getElementById('externalAiCopyStatus').textContent.includes('Prompt copied') || "
        "document.getElementById('externalAiCopyStatus').textContent.includes('copy it manually')"
    )

    builder_layout_script = """
        (() => {
            const cardSpecs = [
                {
                    name: 'configure',
                    card: '[aria-labelledby="externalAiConfigureHeading"]',
                    children: ['.build-section-heading', '.build-section-heading > *',
                               '.external-ai-builder-grid', '.external-ai-builder-grid > *',
                               '.external-ai-builder-grid input', '.external-ai-builder-grid select',
                               '.external-ai-builder-grid textarea', '.build-optional-source',
                               '.build-optional-source > summary', '.build-submit-row',
                               '.build-submit-row > *']
                },
                {
                    name: 'prompt',
                    card: '[aria-labelledby="externalAiPromptHeading"]',
                    children: ['.build-section-heading', '.build-section-heading > *',
                               'label[for="externalAiPrompt"]', '#externalAiPrompt',
                               '.external-ai-copy-row', '.external-ai-copy-row > *']
                },
                {
                    name: 'response',
                    card: '[aria-labelledby="externalAiResponseHeading"]',
                    children: ['.build-section-heading', '.build-section-heading > *',
                               'label[for="externalAiResponse"]', '#externalAiResponse',
                               '.external-ai-builder-actions',
                               '.external-ai-builder-actions > *']
                },
                {
                    name: 'workflow',
                    card: '.external-ai-workflow-distinction',
                    children: ['h2', 'p', 'p a']
                }
            ];
            const cards = cardSpecs.map(spec => {
                const card = document.querySelector(spec.card);
                const bounds = card.getBoundingClientRect();
                const style = getComputedStyle(card);
                const paddingLeft = parseFloat(style.paddingLeft);
                const paddingRight = parseFloat(style.paddingRight);
                const contentLeft = bounds.left + parseFloat(style.borderLeftWidth) + paddingLeft;
                const contentRight = bounds.right - parseFloat(style.borderRightWidth) - paddingRight;
                const children = spec.children.flatMap(selector => [...card.querySelectorAll(selector)]);
                return {
                    name: spec.name,
                    paddingLeft,
                    paddingRight,
                    childCount: children.length,
                    contentInset: children.length > 0 && children.every(child => {
                        const childBounds = child.getBoundingClientRect();
                        return childBounds.left >= contentLeft - 1 &&
                               childBounds.right <= contentRight + 1;
                    })
                };
            });
            const firstCard = document.querySelector('.external-ai-builder-card');
            const input = document.querySelector('[name=topic]');
            return {
                cards,
                cardBg: getComputedStyle(firstCard).backgroundImage,
                inputBg: getComputedStyle(input).backgroundColor,
                inputColor: getComputedStyle(input).color,
                headingDisplay: getComputedStyle(firstCard.querySelector('.build-section-heading')).display,
                overflow: document.documentElement.scrollWidth <= window.innerWidth + 1
            };
        })()
    """

    for theme in ("light", "dark", "purple-gold", "maroon-gold"):
        status = browser.evaluate(
            f"fetch('/api/theme', {{method:'POST', headers:{{'Content-Type':'application/json'}}, "
            f"body:JSON.stringify({{theme:{json.dumps(theme)}}})}}).then(response=>response.status)"
        )
        assert status == 200
        for width in (1440, 1280, 1024, 420, 390):
            browser.set_viewport(width, 1000 if width >= 1024 else 820)
            browser.navigate(f"{base_url}/external-ai/quiz-builder")
            browser.wait_for(
                "document.getElementById('externalAiBuilderForm') && "
                "getComputedStyle(document.documentElement).getPropertyValue('--theme-color-scheme').trim() === "
                f"{json.dumps('light' if theme == 'light' else 'dark')}"
            )
            theme_state = browser.evaluate(builder_layout_script)
            expected_padding = 17 if width <= 760 else 22
            assert theme_state["cardBg"] != "none"
            assert theme_state["inputBg"] != "rgba(0, 0, 0, 0)"
            assert theme_state["inputColor"] != theme_state["inputBg"]
            assert theme_state["headingDisplay"] == "grid"
            assert theme_state["overflow"] is True
            assert [card["name"] for card in theme_state["cards"]] == [
                "configure", "prompt", "response", "workflow",
            ]
            for card in theme_state["cards"]:
                assert card["childCount"] >= 2
                assert card["paddingLeft"] == expected_padding
                assert card["paddingRight"] == expected_padding
                assert card["contentInset"] is True

    browser.set_viewport(1280, 1000)

    browser.navigate(f"{base_url}/external-ai/quiz-builder")
    long_answer = "Second neutral option " + ("answersegment" * 100)
    long_question = "Which neutral browser option is first? " + ("questionsegment" * 70)
    long_source = "NeutralBrowserDataset" * 40
    raw_response = json.dumps({
        "schema_version": 1,
        "content_type": "quiz",
        "title": "Browser External AI Review",
        "source": {
            "organization": "Neutral Browser Source",
            "dataset": long_source,
            "version": "1",
            "url": "https://example.test/review",
            "license": "Test-only neutral content",
        },
        "questions": [{
            "question": long_question,
            "answer_mode": "single",
            "choices": [
                {"text": "First neutral option", "is_correct": True},
                {"text": long_answer, "is_correct": False},
            ],
            "explanation": "The first option is designated by the neutral fixture.",
            "concepts": ["browser-review"],
        }, {
            "question": "Which neutral browser option is second?",
            "answer_mode": "single",
            "choices": [
                {"text": "First secondary option", "is_correct": False},
                {"text": "Second secondary option", "is_correct": True},
            ],
            "explanation": "The second option is designated by this neutral fixture.",
            "concepts": ["browser-review-two"],
        }, {
            "question": "Which neutral browser option is excluded?",
            "answer_mode": "single",
            "choices": [
                {"text": "Included-looking option", "is_correct": True},
                {"text": "Alternative option", "is_correct": False},
            ],
            "explanation": "This neutral record is used to exercise exclusion.",
            "concepts": ["browser-review-excluded"],
        }],
    })
    browser.evaluate(
        "document.querySelector('[name=topic]').value='Neutral browser systems';"
        "document.querySelector('[name=question_count]').value='3';"
        f"document.getElementById('externalAiResponse').value={json.dumps(raw_response)};true"
    )
    browser.click("#externalAiBuilderForm .build-primary-button")
    browser.wait_for_page_ready(
        "location.pathname.startsWith('/external-ai/review/') && "
        "document.querySelector('.external-ai-review-page') && "
        "document.querySelector('[data-pdf-action=choice-add]')"
    )
    draft_id = browser.evaluate("location.pathname.split('/').pop()")
    browser.wait_for("window.dlmsCsrfToken")
    initial = browser.evaluate(
        "(() => {const card=document.querySelector('.pdf-import-question-card');"
        "const raw=document.querySelector('.external-ai-raw-reference');"
        "const rows=[...card.querySelectorAll('[data-pdf-role=choice-row]')];"
        "const active=rows[0].querySelector('[data-pdf-role=single-correct]');active.focus();"
        "const activeFocusWorks=document.activeElement===active;"
        "const inactive=rows[0].querySelector('[data-pdf-role=multiple-correct]');inactive.focus();"
        "return {title:document.querySelector('[name=quiz_title]').value,"
        "cards:document.querySelectorAll('.pdf-import-question-card').length,"
        "choices:card.querySelectorAll('[data-pdf-role=choice-row]').length,"
        "proposed:card.querySelector('[data-pdf-role=single-correct]:checked').dataset.choiceLabel,"
        "proposedText:card.querySelector('[data-pdf-role=single-correct]:checked').closest('[data-pdf-role=choice-row]').querySelector('[data-pdf-role=choice]').value,"
        "confirmed:card.querySelector('[data-pdf-role=correctness-confirmed]').checked,"
        "rawCollapsed:!raw.open,ocr:document.body.textContent.includes('OCR confidence'),"
        "bulkDisabled:document.getElementById('questionReviewConfirmSelected').disabled,"
        "individualControl:card.querySelector('[data-pdf-role=correctness-confirmed]').type==='checkbox',"
        "singleOnly:rows.every(row=>{const single=row.querySelector('[data-pdf-role=single-correct]'),multiple=row.querySelector('[data-pdf-role=multiple-correct]');return getComputedStyle(single.closest('label')).display!=='none'&&!single.disabled&&getComputedStyle(multiple.closest('label')).display==='none'&&multiple.disabled;}),"
        "activeFocusWorks,"
        "inactiveFocusBlocked:document.activeElement!==inactive,"
        "csrf:document.querySelector('#pdfReviewForm input[name=csrf_token]').value.length>0};})()"
    )
    assert initial.pop("proposed") in {"A", "B"}
    assert initial.pop("proposedText") == "First neutral option"
    assert initial == {
        "title": "Browser External AI Review",
        "cards": 3,
        "choices": 2,
        "confirmed": False,
        "rawCollapsed": True,
        "ocr": False,
        "bulkDisabled": True,
        "individualControl": True,
        "singleOnly": True,
        "activeFocusWorks": True,
        "inactiveFocusBlocked": True,
        "csrf": True,
    }
    assert browser.evaluate(
        "(() => {const control=document.querySelector('[data-pdf-role=correctness-confirmed]');"
        "control.click();const checked=control.checked;control.click();"
        "return checked && !control.checked;})()"
    ) is True

    review_url = browser.evaluate("location.href")
    for theme in ("light", "dark", "purple-gold", "maroon-gold"):
        status = browser.evaluate(
            f"fetch('/api/theme', {{method:'POST', headers:{{'Content-Type':'application/json'}}, "
            f"body:JSON.stringify({{theme:{json.dumps(theme)}}})}}).then(response=>response.status)"
        )
        assert status == 200
        browser.navigate(review_url)
        browser.wait_for("document.getElementById('questionReviewConfirmSelected')")
        theme_state = browser.evaluate(
            "(() => {const button=document.getElementById('questionReviewConfirmSelected');"
            "const control=document.querySelector('[data-pdf-role=choice]');"
            "const exclude=document.getElementById('pdfDeleteSelected'),keep=document.getElementById('pdfKeepSelected');"
            "const rows=[...document.querySelector('.pdf-import-question-card').querySelectorAll('[data-pdf-role=choice-row]')];"
            "const checkbox=document.querySelector('[data-pdf-role=select]');"
            "checkbox.checked=true;checkbox.dispatchEvent(new Event('change',{bubbles:true}));button.focus();"
            "const bs=getComputedStyle(button),cs=getComputedStyle(control),es=getComputedStyle(exclude),ks=getComputedStyle(keep);return {"
            "enabled:!button.disabled,focused:document.activeElement===button,"
            "buttonColor:bs.color,buttonBackground:bs.backgroundColor,"
            "inputColor:cs.color,inputBackground:cs.backgroundColor,"
            "excludeMatches:es.color===ks.color&&es.backgroundColor===ks.backgroundColor&&es.borderColor===ks.borderColor,"
            "excludeReversible:!exclude.classList.contains('pdf-review-danger-action'),"
            "singleOnly:rows.every(row=>{const single=row.querySelector('[data-pdf-role=single-correct]'),multiple=row.querySelector('[data-pdf-role=multiple-correct]');return getComputedStyle(single.closest('label')).display!=='none'&&!single.disabled&&getComputedStyle(multiple.closest('label')).display==='none'&&multiple.disabled;}),"
            "overflow:document.documentElement.scrollWidth<=window.innerWidth+1};})()"
        )
        assert theme_state["enabled"] is True
        assert theme_state["focused"] is True
        assert theme_state["buttonColor"] != theme_state["buttonBackground"]
        assert theme_state["inputColor"] != theme_state["inputBackground"]
        assert theme_state["excludeMatches"] is True
        assert theme_state["excludeReversible"] is True
        assert theme_state["singleOnly"] is True
        assert theme_state["overflow"] is True

    browser.navigate(review_url)
    browser.wait_for("document.getElementById('questionReviewConfirmSelected')")

    edited = browser.evaluate(
        "(() => {const card=document.querySelector('.pdf-import-question-card');"
        "card.querySelector('[data-pdf-action=choice-add]').click();"
        "let rows=[...card.querySelectorAll('[data-pdf-role=choice-row]')];"
        "rows[2].querySelector('[data-pdf-role=choice]').value='Third neutral option';"
        "rows[2].querySelector('[data-pdf-action=choice-up]').click();"
        "const mode=card.querySelector('[data-pdf-role=answer-mode]');"
        "mode.value='multiple';mode.dispatchEvent(new Event('change'));"
        "rows=[...card.querySelectorAll('[data-pdf-role=choice-row]')];"
        "rows.forEach(row=>row.querySelector('[data-pdf-role=multiple-correct]').checked=false);"
        "rows[0].querySelector('[data-pdf-role=multiple-correct]').checked=true;"
        "rows[1].querySelector('[data-pdf-role=multiple-correct]').checked=true;"
        "rows[1].querySelector('[data-pdf-role=multiple-correct]').dispatchEvent(new Event('change',{bubbles:true}));"
        "card.querySelector('[data-pdf-role=explanation]').value='Reviewed neutral explanation.';"
        "card.querySelector('[data-pdf-role=concepts]').value='browser-review\\nneutral-concept';"
        "const active=rows[0].querySelector('[data-pdf-role=multiple-correct]');active.focus();"
        "const activeFocusWorks=document.activeElement===active;"
        "const inactive=rows[0].querySelector('[data-pdf-role=single-correct]');inactive.focus();"
        "return {labels:rows.map(row=>row.dataset.choiceLabel),"
        "texts:rows.map(row=>row.querySelector('[data-pdf-role=choice]').value),"
        "correct:[...card.querySelectorAll('[data-pdf-role=multiple-correct]:checked')].map(input=>input.dataset.choiceLabel),"
        "multipleOnly:rows.every(row=>{const single=row.querySelector('[data-pdf-role=single-correct]'),multiple=row.querySelector('[data-pdf-role=multiple-correct]');return getComputedStyle(single.closest('label')).display==='none'&&single.disabled&&getComputedStyle(multiple.closest('label')).display!=='none'&&!multiple.disabled;}),"
        "activeFocusWorks,"
        "inactiveFocusBlocked:document.activeElement!==inactive,"
        "confirmed:card.querySelector('[data-pdf-role=correctness-confirmed]').checked};})()"
    )
    assert edited["labels"] == ["A", "B", "C"]
    assert set(edited["texts"]) == {
        "First neutral option", "Third neutral option", long_answer,
    }
    assert edited["correct"] == ["A", "B"]
    assert edited["multipleOnly"] is True
    assert edited["activeFocusWorks"] is True
    assert edited["inactiveFocusBlocked"] is True
    assert edited["confirmed"] is False
    mixed = browser.evaluate(
        "(() => {const cards=[...document.querySelectorAll('.pdf-import-question-card')];"
        "cards[1].querySelector('[data-pdf-role=choice]').value='';"
        "cards[2].querySelector('[data-pdf-role=delete]').checked=true;"
        "cards.forEach(card=>{const box=card.querySelector('[data-pdf-role=select]');box.checked=true;box.dispatchEvent(new Event('change',{bubbles:true}));});"
        "document.getElementById('questionReviewConfirmSelected').click();"
        "return {confirmations:cards.map(card=>card.querySelector('[data-pdf-role=correctness-confirmed]').checked),"
        "status:document.getElementById('questionReviewBulkConfirmationStatus').textContent,"
        "detailsHidden:document.getElementById('questionReviewSkippedDetails').hidden,"
        "details:document.getElementById('questionReviewSkippedList').textContent,"
        "selected:document.getElementById('pdfSelectionCount').textContent};})()"
    )
    assert mixed["confirmations"] == [True, False, False]
    assert mixed["selected"] == "3 selected"
    assert mixed["status"] == "1 question confirmed. 2 skipped."
    assert mixed["detailsHidden"] is False
    assert "Question 2: has an empty choice." in mixed["details"]
    assert "Question 3: excluded." in mixed["details"]

    repaired = browser.evaluate(
        "(() => {const cards=[...document.querySelectorAll('.pdf-import-question-card')];"
        "document.getElementById('pdfClearSelection').click();"
        "cards[1].querySelector('[data-pdf-role=choice]').value='Repaired secondary option';"
        "const box=cards[1].querySelector('[data-pdf-role=select]');box.checked=true;box.dispatchEvent(new Event('change',{bubbles:true}));"
        "document.getElementById('questionReviewConfirmSelected').click();"
        "return {confirmations:cards.map(card=>card.querySelector('[data-pdf-role=correctness-confirmed]').checked),"
        "status:document.getElementById('questionReviewBulkConfirmationStatus').textContent};})()"
    )
    assert repaired["confirmations"] == [True, True, False]
    assert repaired["status"] == "1 question confirmed. 0 skipped."

    browser.set_viewport(1600, 1000)
    desktop_layout = browser.evaluate(
        "(() => {const rows=[...document.querySelectorAll('.pdf-import-question-card:first-child [data-pdf-role=choice-row]')];"
        "return {columns:new Set(rows.map(row=>Math.round(row.getBoundingClientRect().left))).size,"
        "overflow:document.documentElement.scrollWidth<=window.innerWidth+1};})()"
    )
    assert desktop_layout == {"columns": 2, "overflow": True}
    for width in (420, 390):
        browser.set_viewport(width, 820)
        narrow_layout = browser.evaluate(
            "(() => {const rows=[...document.querySelectorAll('.pdf-import-question-card:first-child [data-pdf-role=choice-row]')];"
            "const controls=[...document.querySelectorAll('.external-ai-review-page input:not(:disabled),.external-ai-review-page textarea:not(:disabled),.external-ai-review-page select:not(:disabled),.external-ai-review-page .pdf-choice-order-controls button:not(:disabled)')].filter(control=>control.getClientRects().length);"
            "return {columns:new Set(rows.map(row=>Math.round(row.getBoundingClientRect().left))).size,"
            "multipleOnly:rows.every(row=>{const single=row.querySelector('[data-pdf-role=single-correct]'),multiple=row.querySelector('[data-pdf-role=multiple-correct]');return getComputedStyle(single.closest('label')).display==='none'&&single.disabled&&getComputedStyle(multiple.closest('label')).display!=='none'&&!multiple.disabled;}),"
            "contained:controls.every(control=>{const panel=control.closest('.dashboard-panel');if(!panel)return true;"
            "const a=control.getBoundingClientRect(),b=panel.getBoundingClientRect();return a.left>=b.left-1&&a.right<=b.right+1;}),"
            f"longValue:[...document.querySelectorAll('[data-pdf-role=choice]')].find(input=>input.value==={json.dumps(long_answer)}).value.length,"
            "overflow:document.documentElement.scrollWidth<=window.innerWidth+1};})()"
        )
        assert narrow_layout["columns"] == 1
        assert narrow_layout["multipleOnly"] is True
        assert narrow_layout["contained"] is True
        assert narrow_layout["longValue"] == len(long_answer)
        assert narrow_layout["overflow"] is True
    browser.set_viewport(1280, 1000)

    browser.click("#pdfReviewForm .build-primary-button")
    browser.wait_for("location.pathname.startsWith('/edit_quiz/')")
    quiz_id = int(browser.evaluate("location.pathname.split('/').pop()"))
    with sqlite3.connect(browser_stack.data_root / "results.db") as connection:
        quiz = connection.execute(
            "SELECT title FROM quizzes WHERE id = ?", (quiz_id,)
        ).fetchone()
    assert quiz == ("Browser External AI Review",)
    registry = json.loads(
        (browser_stack.data_root / "config" / "quizzes.json").read_text(
            encoding="utf-8"
        )
    )
    entry = next(item for item in registry if item["id"] == quiz_id)
    json_name = Path(entry["html"]).with_suffix(".json").name
    published = json.loads(
        (browser_stack.data_root / "data" / json_name).read_text(
            encoding="utf-8"
        )
    )
    assert len(published) == 2
    assert published[0]["answer_mode"] == "multiple"
    assert published[0]["correct"] == ["A", "B"]
    assert published[0]["explanation"] == "Reviewed neutral explanation."
    assert published[0]["concepts"] == ["browser-review", "neutral-concept"]
    assert not (
        browser_stack.data_root / "external_ai_drafts" / f"{draft_id}.json"
    ).exists()
    browser.navigate(f"{base_url}/quizzes/{entry['html']}")
    browser.wait_for("typeof quiz !== 'undefined' && quiz.length === 2")
    browser.click(".study-mode-btn")
    browser.wait_for("document.querySelectorAll('#choices .choice').length === 3")
    assert browser.evaluate(
        "document.getElementById('qText').textContent.includes('neutral browser option')"
    ) is True


def test_external_ai_matching_review_and_publication(browser_stack):
    browser = browser_stack.browser
    base_url = browser_stack.base_url
    browser.navigate(f"{base_url}/external-ai/quiz-builder")
    browser.wait_for("document.getElementById('externalAiContentType')")
    raw_response = json.dumps({
        "schema_version": 1,
        "content_type": "matching",
        "title": "Browser External Matching",
        "source": {
            "organization": "Neutral Browser Source",
            "dataset": "Neutral terminology",
            "version": "1",
            "url": "https://example.test/terms",
            "license": "Test-only neutral content",
        },
        "questions": [{
            "question": "Match each neutral marker to its description.",
            "direction": "term_to_definition",
            "round_size": 2,
            "pairs": [
                {"left": "Marker one", "right": "First neutral description",
                 "category": "markers", "explanation": "First pairing."},
                {"left": "Marker two", "right": "Second neutral description",
                 "category": "markers", "explanation": "Second pairing."},
            ],
            "explanation": "Use the neutral terminology source.",
            "concepts": ["browser-matching"],
        }],
    })
    browser.evaluate(
        "document.getElementById('externalAiContentType').value='matching';"
        "document.getElementById('externalAiContentType').dispatchEvent(new Event('change'));"
        "document.querySelector('[name=topic]').value='Neutral terminology';"
        "document.querySelector('[name=question_count]').value='2';"
        f"document.getElementById('externalAiResponse').value={json.dumps(raw_response)};true"
    )
    assert browser.evaluate(
        "document.getElementById('externalAiCountLabel').textContent"
    ) == "Pair count"
    browser.click("#externalAiBuilderForm .build-primary-button")
    browser.wait_for_page_ready(
        "location.pathname.startsWith('/external-ai/review/') && "
        "document.querySelector('[data-matching-role=pair-row]')"
    )
    initial = browser.evaluate(
        "(() => {const card=document.querySelector('.pdf-import-question-card');"
        "return {pairs:card.querySelectorAll('[data-matching-role=pair-row]').length,"
        "confirmed:card.querySelector('[data-matching-role=review-confirmed]').checked,"
        "choiceMode:!!card.querySelector('[data-pdf-role=answer-mode]'),"
        "overflow:document.documentElement.scrollWidth<=window.innerWidth+1};})()"
    )
    assert initial == {
        "pairs": 2, "confirmed": False, "choiceMode": False, "overflow": True,
    }
    review_url = browser.evaluate("location.href")
    matching_selectors = {
        "matching field label": ".external-ai-matching-pair .build-field > span",
        "matching optional label": ".external-ai-matching-pair .build-field em",
        "matching confirmation": ".pdf-correctness-confirmation span",
        "matching bulk status": ".pdf-review-bulk-status",
        "matching bulk help": ".pdf-review-bulk-help summary",
        "matching disabled bulk action": "#questionReviewConfirmSelected",
    }
    for theme in ("light", "dark", "purple-gold", "maroon-gold"):
        _set_theme(browser, theme)
        browser.navigate(review_url)
        browser.wait_for("document.querySelector('[data-matching-role=pair-row]')")
        matching_theme = _theme_contrast_snapshot(browser, matching_selectors)
        for role, state in matching_theme.items():
            assert state["contrast"] >= 4.5, (theme, role, state)
        assert matching_theme["matching disabled bulk action"]["opacity"] == "1"
    browser.set_viewport(840, 900)
    matching_layout = browser.evaluate(
        "(() => {const settings=document.querySelector('.external-ai-matching-settings');"
        "const fields=document.querySelector('.external-ai-matching-pair-fields');"
        "return {settingsColumns:getComputedStyle(settings).gridTemplateColumns.split(' ').length,"
        "fieldColumns:getComputedStyle(fields).gridTemplateColumns.split(' ').length,"
        "overflow:document.documentElement.scrollWidth<=window.innerWidth+1};})()"
    )
    assert matching_layout == {
        "settingsColumns": 1, "fieldColumns": 1, "overflow": True,
    }
    browser.set_viewport(1280, 1000)
    browser.evaluate(
        "(() => {const card=document.querySelector('.pdf-import-question-card');"
        "const select=card.querySelector('[data-pdf-role=select]');"
        "select.checked=true;select.dispatchEvent(new Event('change',{bubbles:true}));"
        "document.getElementById('questionReviewConfirmSelected').click();return true;})()"
    )
    assert browser.evaluate(
        "document.querySelector('[data-matching-role=review-confirmed]').checked"
    ) is True
    browser.click("#pdfReviewForm .build-primary-button")
    browser.wait_for("location.pathname.startsWith('/edit_quiz/')")
    quiz_id = int(browser.evaluate("location.pathname.split('/').pop()"))
    with sqlite3.connect(browser_stack.data_root / "results.db") as connection:
        question = connection.execute(
            "SELECT id, question_type FROM questions WHERE quiz_id = ?", (quiz_id,)
        ).fetchone()
        pair_count = connection.execute(
            "SELECT COUNT(*) FROM matching_pairs WHERE question_id = ?", (question[0],)
        ).fetchone()[0]
    assert question[1] == "matching"
    assert pair_count == 2


def test_ocr_matching_import_entry_is_clear_and_distinct(browser_stack):
    browser = browser_stack.browser
    browser.navigate(f"{browser_stack.base_url}/pdf-import")
    browser.wait_for(
        "document.querySelector('form[action=\"/pdf-import/ocr-matching\"]')"
    )
    state = browser.evaluate(
        "(() => {const form=document.querySelector('form[action=\"/pdf-import/ocr-matching\"]');"
        "return {images:!!form.querySelector('[name=matching_images][multiple]'),"
        "pdf:!!form.querySelector('[name=matching_pdf]'),"
        "direction:!!form.querySelector('[name=matching_direction]'),"
        "rights:!!form.querySelector('[name=rights_ok][required]'),"
        "copy:form.closest('section').textContent};})()"
    )
    assert state["images"] is True
    assert state["pdf"] is True
    assert state["direction"] is True
    assert state["rights"] is True
    assert "Pairing is deliberately conservative" in state["copy"]
    assert "No cloud OCR or external AI is used" in state["copy"]

    browser.set_viewport(1024, 900)
    ocr_layout = browser.evaluate(
        "(() => {const form=document.querySelector('form[action=\"/pdf-import/ocr-matching\"]');"
        "const panel=form.closest('.pdf-ocr-import-panel');"
        "const bounds=panel.getBoundingClientRect();"
        "const controls=[...form.querySelectorAll('input,select,button')]"
        ".filter(item=>item.getClientRects().length);"
        "return {formDirection:getComputedStyle(form).flexDirection,"
        "headingDirection:getComputedStyle(panel.querySelector('.pdf-bank-panel-heading')).flexDirection,"
        "contained:controls.every(item=>{const rect=item.getBoundingClientRect();"
        "return rect.left>=bounds.left&&rect.right<=bounds.right;}),"
        "overflow:document.documentElement.scrollWidth<=window.innerWidth+1};})()"
    )
    assert ocr_layout == {
        "formDirection": "column",
        "headingDirection": "column",
        "contained": True,
        "overflow": True,
    }
    browser.set_viewport(1280, 1000)


def test_external_ai_help_is_discoverable_and_twenty_five_screenshot_queue_is_rendered(
    browser_stack, tmp_path
):
    browser = browser_stack.browser
    base_url = browser_stack.base_url

    browser.navigate(f"{base_url}/help/")
    help_state = browser.evaluate(
        "(() => {const link=document.querySelector('.help-index-card[href=\"/help/external-ai\"]');"
        "return {found:!!link,label:link?.querySelector('strong')?.textContent.trim()||''};})()"
    )
    assert help_state == {"found": True, "label": "External AI Quiz Builder"}
    browser.navigate(f"{base_url}/help/external-ai")
    browser.wait_for("document.querySelector('.help-toc a[aria-current=page]')")
    assert browser.evaluate(
        "document.querySelector('.help-toc a[aria-current=page]').getAttribute('href')"
    ) == "/help/external-ai"

    upload_root = tmp_path / "twenty-five-screenshot-browser-fixtures"
    upload_root.mkdir(exist_ok=True)
    uploads = []
    for index in range(1, 26):
        target = upload_root / f"screenshot-{index:02d}.png"
        target.write_bytes(b"not an image")
        uploads.append(str(target))

    browser.navigate(f"{base_url}/pdf-import")
    browser.wait_for(
        "window.dlmsCsrfToken && "
        "document.querySelector('form[action=\"/pdf-import/screenshots\"] input[name=csrf_token]')"
    )
    assert browser.evaluate(
        "document.querySelector('form[action=\"/pdf-import/screenshots\"]')"
        ".closest('section').innerText.includes('Import up to 25')"
    ) is True
    browser.set_files(
        'form[action="/pdf-import/screenshots"] [name=screenshots]', uploads
    )
    browser.evaluate(
        "(() => {const form=document.querySelector('form[action=\"/pdf-import/screenshots\"]');"
        "form.querySelector('[name=quiz_title]').value='Twenty Five Queue';"
        "form.querySelector('[name=rights_ok]').checked=true;return true;})()"
    )
    browser.click('form[action="/pdf-import/screenshots"] button[type=submit]')
    browser.wait_for(
        "location.pathname.startsWith('/pdf-import/screenshots/process/') && "
        "document.querySelectorAll('#ocrSourceList > li').length === 25",
        timeout=20,
    )
    queue_state = browser.evaluate(
        "(() => ({rows:document.querySelectorAll('#ocrSourceList > li').length,"
        "maximum:Number(document.getElementById('ocrProgressBar').max),"
        "count:document.getElementById('ocrProgressCount').textContent.trim(),"
        "cancel:!document.getElementById('ocrCancelButton').disabled}))()"
    )
    assert queue_state["rows"] == 25
    assert queue_state["maximum"] == 25
    assert queue_state["count"].endswith("/ 25")
    assert queue_state["cancel"] is True


def test_screenshot_ocr_batch_review_confirmation_and_theme_flow(browser_stack):
    browser = browser_stack.browser
    base_url = browser_stack.base_url
    fixture = ROOT / "tests" / "fixtures" / "ocr" / "screenshot-explicit-abcd.png"

    browser.navigate(f"{base_url}/pdf-import")
    browser.wait_for(
        "window.dlmsCsrfToken && "
        "document.querySelector('form[action=\"/pdf-import/screenshots\"] input[name=csrf_token]')"
    )
    entry = browser.evaluate(
        "(() => {const form=document.querySelector('form[action=\"/pdf-import/screenshots\"]');"
        "return {method:form.method,enctype:form.enctype,multiple:form.querySelector('[name=screenshots]').multiple,"
        "disabled:form.querySelector('[name=screenshots]').disabled,rights:form.querySelector('[name=rights_ok]').required,"
        "help:form.closest('section').innerText.includes('selected or highlighted answer')};})()"
    )
    assert entry == {
        "method": "post",
        "enctype": "multipart/form-data",
        "multiple": True,
        "disabled": False,
        "rights": True,
        "help": True,
    }
    browser.set_files("form[action=\"/pdf-import/screenshots\"] [name=screenshots]", [str(fixture), str(fixture)])
    browser.evaluate(
        "(() => {const form=document.querySelector('form[action=\"/pdf-import/screenshots\"]');"
        "form.querySelector('[name=quiz_title]').value='Browser OCR Review';"
        "form.querySelector('[name=rights_ok]').checked=true;return true;})()"
    )
    browser.click("form[action=\"/pdf-import/screenshots\"] button[type=submit]")
    browser.wait_for_page_ready(
        "location.pathname.startsWith('/pdf-import/review/') && "
        "document.querySelectorAll('.pdf-import-question-card').length === 2",
        timeout=20,
    )

    state = browser.evaluate(
        "(() => {const cards=[...document.querySelectorAll('.pdf-import-question-card')];"
        "return {cards:cards.length,previews:document.querySelectorAll('.pdf-ocr-preview-frame img').length,"
        "duplicate:document.body.innerText.includes('exactly duplicates an earlier image'),"
        "modes:cards.map(card=>card.querySelector('[data-pdf-role=answer-mode]').value),"
        "answers:cards.map(card=>[...card.querySelectorAll('[data-pdf-role=multiple-correct]:checked')].map(input=>input.value)),"
        "multipleOnly:cards.every(card=>[...card.querySelectorAll('[data-pdf-role=choice-row]')].every(row=>{const single=row.querySelector('[data-pdf-role=single-correct]'),multiple=row.querySelector('[data-pdf-role=multiple-correct]');return getComputedStyle(single.closest('label')).display==='none'&&single.disabled&&getComputedStyle(multiple.closest('label')).display!=='none'&&!multiple.disabled;})),"
        "confirmations:cards.map(card=>card.querySelector('[data-pdf-role=correctness-confirmed]').checked),"
        "bulkConfirm:!!document.getElementById('questionReviewConfirmSelected'),"
        "bulkDisabled:document.getElementById('questionReviewConfirmSelected').disabled,"
        "bulkStatusLive:document.getElementById('questionReviewBulkConfirmationStatus').getAttribute('aria-live'),"
        "labels:[...cards[0].querySelectorAll('[data-pdf-role=choice-label]')].map(node=>node.textContent)};})()"
    )
    assert state == {
        "cards": 2,
        "previews": 2,
        "duplicate": True,
        "modes": ["multiple", "multiple"],
        "answers": [["B", "D"], ["B", "D"]],
        "multipleOnly": True,
        "confirmations": [False, False],
        "bulkConfirm": True,
        "bulkDisabled": True,
        "bulkStatusLive": "polite",
        "labels": ["A", "B", "C", "D"],
    }

    surfaces = {}
    review_url = browser.evaluate("location.href")
    contrast_helpers = (
        "const parse=value=>{value=value.trim();if(value.startsWith('#')){let h=value.slice(1);"
        "if(h.length===3)h=[...h].map(c=>c+c).join('');return [parseInt(h.slice(0,2),16)/255,"
        "parseInt(h.slice(2,4),16)/255,parseInt(h.slice(4,6),16)/255,1];}"
        "const m=value.match(/^rgba?\\(([^)]+)\\)$/);if(m){const p=m[1].split(/[, ]+/).filter(Boolean).map(Number);"
        "return [p[0]/255,p[1]/255,p[2]/255,p.length>3?p[3]:1];}"
        "const s=value.match(/^color\\(srgb ([^/ )]+) ([^/ )]+) ([^/ )]+)(?: \\/ ([^)]+))?\\)$/);"
        "if(s)return [+s[1],+s[2],+s[3],s[4]===undefined?1:+s[4]];throw new Error(value);};"
        "const mix=(fg,bg)=>fg.slice(0,3).map((v,i)=>v*fg[3]+bg[i]*(1-fg[3]));"
        "const base=parse(getComputedStyle(document.documentElement).getPropertyValue('--theme-body-base')).slice(0,3);"
        "const effective=node=>{const layers=[];for(let item=node;item;item=item.parentElement)"
        "layers.push(parse(getComputedStyle(item).backgroundColor));"
        "return layers.reverse().reduce((bg,layer)=>mix(layer,bg),base);};"
        "const lum=rgb=>rgb.map(v=>v<=.04045?v/12.92:Math.pow((v+.055)/1.055,2.4))"
        ".reduce((sum,v,i)=>sum+v*[.2126,.7152,.0722][i],0);"
        "const measure=node=>{const background=effective(node);"
        "const foreground=mix(parse(getComputedStyle(node).color),background);"
        "return {color:getComputedStyle(node).color,background:getComputedStyle(node).backgroundColor,"
        "contrast:(Math.max(lum(foreground),lum(background))+.05)/(Math.min(lum(foreground),lum(background))+.05)};};"
    )
    for theme in ("light", "dark", "purple-gold", "maroon-gold"):
        browser.navigate(f"{base_url}/settings")
        browser.wait_for("window.dlmsCsrfToken")
        status = browser.evaluate(
            f"fetch('/api/theme',{{method:'POST',headers:{{'Content-Type':'application/json'}},"
            f"body:JSON.stringify({{theme:{json.dumps(theme)}}})}}).then(response=>response.status)"
        )
        assert status == 200
        browser.navigate(f"{base_url}/pdf-import")
        browser.wait_for("document.querySelector('.pdf-ocr-guidance span')")
        landing_state = browser.evaluate(
            "(() => {" + contrast_helpers
            + "return {title:document.title,instruction:measure(document.querySelector('.pdf-ocr-guidance span')) ,"
            "rights:measure(document.querySelector('.pdf-import-rights span')) ,"
            "status:measure(document.querySelector('.pdf-ocr-local-note')) ,"
            "eyebrow:getComputedStyle(document.querySelector('.build-eyebrow')).color};})()"
        )
        assert landing_state["title"] == "PDF & Image Import - DLMS"
        for role in ("instruction", "rights", "status"):
            assert landing_state[role]["contrast"] >= 4.5, (
                theme, role, landing_state[role]
            )
        if theme in {"purple-gold", "maroon-gold"}:
            assert landing_state["instruction"]["color"] != landing_state["eyebrow"]

        browser.navigate(review_url)
        browser.wait_for("document.querySelector('.pdf-ocr-review-source')")
        theme_state = browser.evaluate(
            "(() => {" + contrast_helpers
            + "const source=document.querySelector('.pdf-ocr-review-source');"
            "const field=source.querySelector('.pdf-ocr-confidence-list span');"
            "const button=document.querySelector('[data-pdf-action=choice-add]');"
            "const bulk=document.getElementById('questionReviewConfirmSelected');"
            "const selected=document.querySelector('[data-pdf-role=select]');selected.click();bulk.focus();"
            "return {source:getComputedStyle(source).backgroundColor,field:measure(field),"
            "provenance:measure(document.querySelector('.pdf-import-source-note')) ,"
            "confirmation:measure(document.querySelector('.pdf-correctness-confirmation span')) ,"
            "control:measure(button),bulk:measure(bulk),eyebrow:getComputedStyle(document.querySelector('.build-eyebrow')).color,"
            "focusable:button.tabIndex===0&&!button.disabled,"
            "bulkEnabled:!bulk.disabled,bulkFocused:document.activeElement===bulk,"
            "overflow:document.documentElement.scrollWidth<=window.innerWidth+1};})()"
        )
        for role in ("field", "provenance", "confirmation", "control", "bulk"):
            assert theme_state[role]["contrast"] >= 4.5, (
                theme, role, theme_state[role]
            )
        if theme in {"purple-gold", "maroon-gold"}:
            assert theme_state["confirmation"]["color"] != theme_state["eyebrow"]
        assert theme_state["focusable"] is True
        assert theme_state["bulkEnabled"] is True
        assert theme_state["bulkFocused"] is True
        assert theme_state["overflow"] is True
        surfaces[theme] = theme_state["source"]
    assert len(set(surfaces.values())) == 4

    for width in (420, 390):
        browser.set_viewport(width, 820)
        assert browser.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1") is True
    browser.set_viewport(1280, 1000)
    bulk_single = browser.evaluate(
        "(() => {const cards=[...document.querySelectorAll('.pdf-import-question-card')];"
        "document.getElementById('pdfClearSelection').click();"
        "const select=cards[0].querySelector('[data-pdf-role=select]');select.checked=true;"
        "select.dispatchEvent(new Event('change',{bubbles:true}));"
        "document.getElementById('questionReviewConfirmSelected').click();"
        "return {confirmations:cards.map(card=>card.querySelector('[data-pdf-role=correctness-confirmed]').checked),"
        "status:document.getElementById('questionReviewBulkConfirmationStatus').textContent};})()"
    )
    assert bulk_single["confirmations"] == [True, False], bulk_single
    assert bulk_single["status"] == "1 question confirmed. 0 skipped."

    bulk_mixed = browser.evaluate(
        "(() => {const cards=[...document.querySelectorAll('.pdf-import-question-card')];"
        "const invalidChoice=cards[1].querySelector('[data-pdf-role=choice]');invalidChoice.value='';"
        "invalidChoice.dispatchEvent(new Event('input',{bubbles:true}));"
        "cards[1].querySelector('[data-pdf-role=select]').click();"
        "document.getElementById('questionReviewConfirmSelected').click();"
        "return {confirmations:cards.map(card=>card.querySelector('[data-pdf-role=correctness-confirmed]').checked),"
        "status:document.getElementById('questionReviewBulkConfirmationStatus').textContent};})()"
    )
    assert bulk_mixed["confirmations"] == [True, False]
    assert bulk_mixed["status"] == "1 question confirmed. 1 skipped."
    assert "Question 2: has an empty choice." in browser.evaluate(
        "document.getElementById('questionReviewSkippedList').textContent"
    )

    bulk_excluded = browser.evaluate(
        "(() => {const cards=[...document.querySelectorAll('.pdf-import-question-card')];"
        "cards[1].querySelector('[data-pdf-role=choice]').value='What is a control family?';"
        "cards[1].querySelector('[data-pdf-role=delete]').checked=true;"
        "document.getElementById('questionReviewConfirmSelected').click();"
        "return {confirmed:cards[1].querySelector('[data-pdf-role=correctness-confirmed]').checked,"
        "status:document.getElementById('questionReviewBulkConfirmationStatus').textContent};})()"
    )
    assert bulk_excluded["confirmed"] is False
    assert bulk_excluded["status"] == "1 question confirmed. 1 skipped."
    assert "Question 2: excluded." in browser.evaluate(
        "document.getElementById('questionReviewSkippedList').textContent"
    )

    bulk_ready = browser.evaluate(
        "(() => {const cards=[...document.querySelectorAll('.pdf-import-question-card')];"
        "cards[1].querySelector('[data-pdf-role=delete]').checked=false;"
        "cards[0].querySelector('[data-pdf-role=question]').value='Which controls should be selected?';"
        "cards[0].querySelector('[data-pdf-role=question]').dispatchEvent(new Event('input',{bubbles:true}));"
        "cards[0].querySelector('[data-pdf-action=choice-add]').click();"
        "const added=[...cards[0].querySelectorAll('[data-pdf-role=choice-row]')].at(-1);"
        "added.querySelector('[data-pdf-role=choice]').value='Manual fifth option';"
        "document.getElementById('questionReviewConfirmSelected').click();"
        "return {confirmations:cards.map(card=>card.querySelector('[data-pdf-role=correctness-confirmed]').checked),"
        "status:document.getElementById('questionReviewBulkConfirmationStatus').textContent};})()"
    )
    assert bulk_ready["confirmations"] == [True, True]
    assert bulk_ready["status"] == "2 questions confirmed. 0 skipped."
    assert browser.evaluate(
        "document.getElementById('questionReviewSkippedDetails').hidden"
    ) is True
    browser.click("#pdfReviewForm button[type=submit]:not([formaction])")
    browser.wait_for("location.pathname.startsWith('/pdf-import/bank/')")
    saved = browser.evaluate(
        "(() => ({title:document.querySelector('h1').textContent.trim(),"
        "source:document.body.innerText.includes('Browser OCR Review'),"
        "rows:document.querySelectorAll('.pdf-bank-question-table tbody tr').length}))()"
    )
    assert saved["source"] is True
    assert saved["rows"] == 2


def test_ocr_availability_diagnostics_and_badge_are_responsive(browser_stack):
    browser = browser_stack.browser
    base_url = browser_stack.base_url
    executable = browser_stack.data_root.parent / "ocr-runtime" / "tesseract"
    unavailable_executable = executable.with_name("tesseract.unavailable")

    def set_theme(theme):
        status = browser.evaluate(
            f"fetch('/api/theme',{{method:'POST',headers:{{'Content-Type':'application/json'}},"
            f"body:JSON.stringify({{theme:{json.dumps(theme)}}})}}).then(response=>response.status)"
        )
        assert status == 200

    def badge_state():
        return browser.evaluate(
            "(() => {const badge=document.querySelector('.pdf-ocr-availability');"
            "const style=getComputedStyle(badge),rect=badge.getBoundingClientRect();"
            "return {text:badge.textContent.trim(),whiteSpace:style.whiteSpace,"
            "overflowWrap:style.overflowWrap,wordBreak:style.wordBreak,height:rect.height,"
            "width:rect.width,scrollWidth:badge.scrollWidth,viewport:innerWidth,"
            "documentWidth:document.documentElement.scrollWidth,color:style.color,"
            "background:style.backgroundColor,border:style.borderColor};})()"
        )

    available_surfaces = {}
    unavailable_surfaces = {}
    for width in (1120, 760, 390):
        browser.set_viewport(width, 850)
        for theme in ("light", "dark", "purple-gold", "maroon-gold"):
            browser.navigate(f"{base_url}/pdf-import")
            set_theme(theme)
            browser.navigate(f"{base_url}/pdf-import")
            browser.wait_for("document.querySelector('.pdf-ocr-availability')")
            state = badge_state()
            assert state["text"].startswith("OCR available · Tesseract")
            assert state["whiteSpace"] == "nowrap"
            assert state["overflowWrap"] == "normal"
            assert state["wordBreak"] == "normal"
            assert state["height"] < 32
            assert state["documentWidth"] <= state["viewport"] + 1
            available_surfaces[theme] = (
                state["color"], state["background"], state["border"]
            )

    executable.rename(unavailable_executable)
    try:
        for width in (1120, 760, 390):
            browser.set_viewport(width, 850)
            for theme in ("light", "dark", "purple-gold", "maroon-gold"):
                browser.navigate(f"{base_url}/pdf-import")
                browser.wait_for(
                    "document.querySelector('.pdf-ocr-availability').textContent.includes('unavailable')"
                )
                set_theme(theme)
                browser.navigate(f"{base_url}/pdf-import")
                browser.wait_for(
                    "document.querySelector('.pdf-ocr-availability').textContent.includes('unavailable')"
                )
                state = badge_state()
                assert state["text"] == "OCR unavailable"
                assert state["whiteSpace"] == "nowrap"
                assert state["overflowWrap"] == "normal"
                assert state["wordBreak"] == "normal"
                assert state["height"] < 32
                assert state["documentWidth"] <= state["viewport"] + 1
                assert browser.evaluate(
                    "document.querySelector('.pdf-ocr-unavailable').innerText.includes("
                    "'Normal selectable-text PDF import remains fully available') && "
                    "document.querySelector('.pdf-ocr-unavailable').innerText.includes("
                    "'DLMS_TESSERACT_EXECUTABLE')"
                ) is True
                unavailable_surfaces[theme] = (
                    state["color"], state["background"], state["border"]
                )
    finally:
        unavailable_executable.rename(executable)

    assert len(set(available_surfaces.values())) == 4
    assert len(set(unavailable_surfaces.values())) == 4


def test_selective_scanned_pdf_ocr_offer_merge_preview_and_theme_flow(browser_stack):
    browser = browser_stack.browser
    base_url = browser_stack.base_url
    fixture = ROOT / "tests" / "fixtures" / "ocr" / "pdf" / "mixed-text-and-scan.pdf"

    browser.navigate(f"{base_url}/pdf-import")
    browser.wait_for(
        "window.dlmsCsrfToken && document.querySelector('form[action=\"/pdf-import/analyze\"] input[name=csrf_token]')"
    )
    browser.set_files("form[action=\"/pdf-import/analyze\"] [name=pdf_file]", [str(fixture)])
    browser.evaluate(
        "(() => {const form=document.querySelector('form[action=\"/pdf-import/analyze\"]');"
        "form.querySelector('[name=quiz_title]').value='Browser Mixed PDF OCR';"
        "form.querySelector('[name=pdf_content_type]').value='question_bank';"
        "form.querySelector('[name=rights_ok]').checked=true;return true;})()"
    )
    browser.click("form[action=\"/pdf-import/analyze\"] button[type=submit]")
    browser.wait_for("location.pathname.startsWith('/pdf-import/ocr/')", timeout=15)
    browser.wait_for("document.querySelectorAll('[name=ocr_pages]').length>0")
    offer = browser.evaluate(
        "(() => {const choices=[...document.querySelectorAll('[name=ocr_pages]')];"
        "const group=document.querySelector('.pdf-ocr-page-selection');return {pages:choices.map(input=>input.value),"
        "checked:choices.map(input=>input.checked),optional:document.body.innerText.includes('OCR is optional'),"
        "limit:document.body.innerText.includes('maximum 25'),overflow:document.documentElement.scrollWidth<=window.innerWidth+1};})()"
    )
    assert offer == {
        "pages": ["2"],
        "checked": [False],
        "optional": True,
        "limit": True,
        "overflow": True,
    }

    offer_url = browser.evaluate("location.href")
    surfaces = {}
    for theme in ("light", "dark", "purple-gold", "maroon-gold"):
        status = browser.evaluate(
            f"fetch('/api/theme',{{method:'POST',headers:{{'Content-Type':'application/json'}},"
            f"body:JSON.stringify({{theme:{json.dumps(theme)}}})}}).then(response=>response.status)"
        )
        assert status == 200
        browser.navigate(offer_url)
        browser.wait_for("document.querySelector('.pdf-ocr-page-option')")
        state = browser.evaluate(
            "(() => {const card=document.querySelector('.pdf-ocr-page-option'),style=getComputedStyle(card);"
            "return {background:style.backgroundColor,color:style.color,border:style.borderColor,"
            "focusable:card.querySelector('input').tabIndex===0,overflow:document.documentElement.scrollWidth<=window.innerWidth+1};})()"
        )
        assert state["focusable"] is True
        assert state["overflow"] is True
        surfaces[theme] = state["background"]
    assert len(set(surfaces.values())) == 4

    browser.set_viewport(390, 820)
    assert browser.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1") is True
    browser.set_viewport(1280, 1000)
    browser.click("[name=ocr_pages][value='2']")
    browser.click(".pdf-ocr-page-selection button[type=submit]")
    browser.wait_for_page_ready(
        "location.pathname.startsWith('/pdf-import/review/') && document.querySelectorAll('.pdf-import-question-card').length===2",
        timeout=25,
    )
    review = browser.evaluate(
        "(() => ({cards:document.querySelectorAll('.pdf-import-question-card').length,"
        "ocrCards:document.querySelectorAll('.pdf-ocr-review-source').length,"
        "preview:!!document.querySelector('.pdf-ocr-preview-frame img[src*=\"/page/2\"]'),"
        "pageLabel:document.body.innerText.includes('PDF page 2'),"
        "confirmation:!!document.querySelector('[data-pdf-role=correctness-confirmed]'),"
        "bulkConfirm:!!document.getElementById('questionReviewConfirmSelected')}))()"
    )
    assert review == {
        "cards": 2,
        "ocrCards": 1,
        "preview": True,
        "pageLabel": True,
        "confirmation": True,
        "bulkConfirm": True,
    }
    draft_id = browser.evaluate("location.pathname.split('/').pop()")
    scanned_bulk = browser.evaluate(
        "(() => {const card=document.querySelector('[data-pdf-role=correctness-confirmed]').closest('.pdf-import-question-card');"
        "const select=card.querySelector('[data-pdf-role=select]');select.checked=true;"
        "select.dispatchEvent(new Event('change',{bubbles:true}));"
        "document.getElementById('questionReviewConfirmSelected').click();"
        "return {confirmed:card.querySelector('[data-pdf-role=correctness-confirmed]').checked,"
        "status:document.getElementById('questionReviewBulkConfirmationStatus').textContent};})()"
    )
    assert scanned_bulk["confirmed"] is True, scanned_bulk
    assert scanned_bulk["status"] == "1 question confirmed. 0 skipped."
    browser.evaluate(
        "document.getElementById('pdfReviewForm').requestSubmit("
        "document.querySelector('#pdfReviewForm button[type=submit]:not([formaction])'))"
    )
    browser.wait_for(
        "location.pathname.startsWith('/pdf-import/bank/') || "
        "document.querySelector('.pdf-import-flash-stack .flash')"
    )
    save_state = browser.evaluate(
        "({path:location.pathname,flash:document.querySelector('.pdf-import-flash-stack .flash')?.textContent||''})"
    )
    assert save_state["path"].startswith("/pdf-import/bank/"), save_state
    saved = browser.evaluate(
        "(() => ({rows:document.querySelectorAll('.pdf-bank-question-table tbody tr').length,"
        "source:document.body.innerText.includes('Browser Mixed PDF OCR')}))()"
    )
    assert saved == {"rows": 2, "source": True}
    assert not (browser_stack.data_root / "uploads" / "ocr_pdfs" / draft_id).exists()


def test_pdf_review_large_bulk_confirmation_status_stays_compact(browser_stack):
    browser = browser_stack.browser
    base_url = browser_stack.base_url
    draft_id = "browser_large_bulk_status"
    questions = []
    for index in range(40):
        skipped = index >= 31
        questions.append({
            "number": index + 1,
            "question": f"Which neutral option applies to item {index + 1}?",
            "choices": [
                {"label": "A", "text": f"Applicable option {index + 1}"},
                {"label": "B", "text": "" if skipped else f"Alternative option {index + 1}"},
            ],
            "correct": "A",
            "answer_mode": "single",
            "correctness_confirmation_required": True,
            "correctness_confirmed": False,
            "explanation": f"Neutral explanation {index + 1}.",
            "pages": [index + 1],
            "status": "incomplete" if skipped else "complete",
            "issues": [],
        })
    draft = {
        "id": draft_id,
        "source_name": "neutral-large-review.pdf",
        "source_kind": "user-provided-pdf-ocr",
        "page_count": 40,
        "document_type": "question_bank",
        "detection": {"recovery_mode": True},
        "recovery_mode": True,
        "quiz_title": "Large Bulk Review",
        "exam_minutes": 45,
        "summary": {"detected": 40, "complete": 31, "review": 0, "incomplete": 9},
        "questions": questions,
    }
    review_root = browser_stack.data_root / "pdf_import_drafts"
    review_root.mkdir(exist_ok=True)
    (review_root / f"{draft_id}.json").write_text(
        json.dumps(draft), encoding="utf-8"
    )

    detail_surfaces = {}
    for theme in ("light", "dark", "purple-gold", "maroon-gold"):
        browser.navigate(f"{base_url}/settings")
        browser.wait_for("window.dlmsCsrfToken")
        status = browser.evaluate(
            f"fetch('/api/theme',{{method:'POST',headers:{{'Content-Type':'application/json'}},"
            f"body:JSON.stringify({{theme:{json.dumps(theme)}}})}}).then(response=>response.status)"
        )
        assert status == 200
        browser.navigate(f"{base_url}/pdf-import/review/{draft_id}")
        browser.wait_for_page_ready(
            "document.querySelectorAll('.pdf-import-question-card').length === 40 && "
            "document.getElementById('questionReviewConfirmSelected')"
        )
        browser.click("#pdfSelectAllVisible")
        browser.click("#questionReviewConfirmSelected")
        desktop = browser.evaluate(
            "(() => {const bar=document.querySelector('.pdf-review-bulk-bar');"
            "const actions=document.querySelector('.pdf-review-bulk-actions');"
            "const statusGroup=document.querySelector('.pdf-review-bulk-status-group');"
            "const status=document.getElementById('questionReviewBulkConfirmationStatus');"
            "const details=document.getElementById('questionReviewSkippedDetails');"
            "const summary=document.getElementById('questionReviewSkippedSummary');"
            "const list=document.getElementById('questionReviewSkippedList');"
            "const detailsStyle=getComputedStyle(details);summary.focus();details.open=true;"
            "const itemStyle=getComputedStyle(list.firstElementChild);"
            "const detailRect=details.getBoundingClientRect(),actionsRect=actions.getBoundingClientRect(),"
            "statusRect=statusGroup.getBoundingClientRect();return {"
            "selection:document.getElementById('pdfSelectionCount').textContent,"
            "status:status.textContent,statusLive:status.getAttribute('aria-live'),"
            "detailsHidden:details.hidden,summary:summary.textContent,items:list.children.length,"
            "first:list.firstElementChild.textContent,last:list.lastElementChild.textContent,"
            "confirmed:document.querySelectorAll('[data-pdf-role=correctness-confirmed]:checked').length,"
            "focused:document.activeElement===summary,open:details.open,"
            "belowToolbar:detailRect.top>=Math.max(actionsRect.bottom,statusRect.bottom),"
            "contained:detailRect.left>=bar.getBoundingClientRect().left&&detailRect.right<=bar.getBoundingClientRect().right,"
            "wrap:itemStyle.overflowWrap,background:detailsStyle.backgroundColor,"
            "overflow:document.documentElement.scrollWidth<=window.innerWidth+1};})()"
        )
        detail_background = desktop.pop("background")
        assert desktop == {
            "selection": "40 selected",
            "status": "31 questions confirmed. 9 skipped.",
            "statusLive": "polite",
            "detailsHidden": False,
            "summary": "Show skipped questions (9)",
            "items": 9,
            "first": "Question 32: has an empty choice.",
            "last": "Question 40: has an empty choice.",
            "confirmed": 31,
            "focused": True,
            "open": True,
            "belowToolbar": True,
            "contained": True,
            "wrap": "anywhere",
            "overflow": True,
        }
        detail_surfaces[theme] = detail_background
        browser.set_viewport(420, 820)
        narrow = browser.evaluate(
            "(() => {const bar=document.querySelector('.pdf-review-bulk-bar'),"
            "details=document.getElementById('questionReviewSkippedDetails'),"
            "rect=details.getBoundingClientRect(),barRect=bar.getBoundingClientRect();return {"
            "contained:rect.left>=barRect.left&&rect.right<=barRect.right,"
            "overflow:document.documentElement.scrollWidth<=window.innerWidth+1};})()"
        )
        assert narrow == {"contained": True, "overflow": True}
        browser.set_viewport(1280, 1000)
    assert len(set(detail_surfaces.values())) == 4


def test_law_semantic_surfaces_follow_all_themes(browser_stack):
    browser = browser_stack.browser
    base_url = browser_stack.base_url
    data_root = browser_stack.data_root
    case_id = "dlms120-theme-case"
    case_file = f"{case_id}.json"
    case_path = data_root / "law" / "cases" / case_file
    case_path.write_text(json.dumps({
        "id": case_id,
        "type": "law_case_review",
        "title": "DLMS-120 Theme Case",
        "course": "Theme Review",
        "created_at": "2026-09-09T12:00:00",
        "source_import": "dlms120-theme-case.txt",
        "sources_used": "Theme source one\nTheme source two",
        "student_notes": "Readable student notes.",
        "socratic_student_answers": {"question_1": "A saved answer."},
        "irac_student_response": {
            "issue": "Issue", "rule": "Rule", "analysis": "Analysis",
            "conclusion": "Conclusion",
        },
        "sections": {
            "case_brief": "Facts, issue, rule, holding, and reasoning.",
            "socratic_review": "1. What rule controls?",
            "socratic_answer_key": "1. The governing rule controls.",
            "irac_drill": "Apply the rule to the facts.",
            "rule_flashcards": "Q: What rule applies?\nA: The governing rule.",
        },
    }), encoding="utf-8")
    registry_path = data_root / "config" / "law.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    registry.pop("pending_case_workflow", None)
    registry.setdefault("folders", []).append("Theme Review")
    registry["cases"].append({
        "id": case_id, "title": "DLMS-120 Theme Case",
        "course": "Theme Review", "file": case_file, "hidden": False,
    })
    registry_path.write_text(json.dumps(registry), encoding="utf-8")

    def set_theme(theme):
        status = browser.evaluate(
            f"fetch('/api/theme', {{method:'POST', headers:{{'Content-Type':'application/json'}}, "
            f"body:JSON.stringify({{theme:{json.dumps(theme)}}})}}).then(response => response.status)"
        )
        assert status == 200

    probe_helpers = """
        const parseColor=value=>{
          const rgb=value.match(/^rgba?\\(([^)]+)\\)$/);
          if(rgb){const parts=rgb[1].split(/[, ]+/).filter(Boolean).map(Number);
            return [parts[0]/255,parts[1]/255,parts[2]/255,parts.length>3?parts[3]:1];}
          const srgb=value.match(/^color\\(srgb ([^/ )]+) ([^/ )]+) ([^/ )]+)(?: \\/ ([^)]+))?\\)$/);
          if(srgb)return [+srgb[1],+srgb[2],+srgb[3],srgb[4]===undefined?1:+srgb[4]];
          throw new Error('Unsupported computed color: '+value);
        };
        const resolveColor=value=>{const node=document.createElement('span');node.style.color=value;
          document.body.appendChild(node);const result=getComputedStyle(node).color;node.remove();return parseColor(result);};
        const composite=(foreground,background)=>foreground.slice(0,3).map((value,index)=>
          value*foreground[3]+background[index]*(1-foreground[3]));
        const luminance=rgb=>rgb.map(value=>value<=.04045?value/12.92:Math.pow((value+.055)/1.055,2.4))
          .reduce((sum,value,index)=>sum+value*[.2126,.7152,.0722][index],0);
        const contrast=(foreground,background)=>{const a=luminance(foreground.slice(0,3));const b=luminance(background);
          return (Math.max(a,b)+.05)/(Math.min(a,b)+.05);};
        const root=getComputedStyle(document.documentElement);
        const bodyBase=resolveColor(root.getPropertyValue('--theme-body-base'));
        const panel=composite(resolveColor(root.getPropertyValue('--theme-panel-1')),bodyBase.slice(0,3));
        const evaluateOn=(node,parentBackground)=>{const style=getComputedStyle(node);
          const background=composite(parseColor(style.backgroundColor),parentBackground);
          return {background,backgroundCss:style.backgroundColor,colorCss:style.color,
            borderCss:style.borderColor,borderStyle:style.borderStyle,
            contrast:contrast(parseColor(style.color),background)};};
    """

    def summary_card_style(selector):
        return browser.evaluate(
            "(() => {" + probe_helpers +
            f"const card=document.querySelector({json.dumps(selector)});"
            "const style=getComputedStyle(card);const surface=evaluateOn(card,panel);"
            "const label=evaluateOn(card.querySelector('span'),surface.background);"
            "const value=evaluateOn(card.querySelector('strong'),surface.background);"
            "const support=evaluateOn(card.querySelector('small'),surface.background);"
            "return {background:style.backgroundColor,border:style.borderColor,"
            "radius:style.borderRadius,shadow:style.boxShadow,padding:style.padding,"
            "minHeight:style.minHeight,labelSize:getComputedStyle(card.querySelector('span')).fontSize,"
            "valueSize:getComputedStyle(card.querySelector('strong')).fontSize,"
            "supportSize:getComputedStyle(card.querySelector('small')).fontSize,"
            "labelContrast:label.contrast,valueContrast:value.contrast,"
            "supportContrast:support.contrast};})()"
        )

    observed_section_backgrounds = {}
    observed_law_summary_backgrounds = {}
    for theme in ("light", "dark", "purple-gold", "maroon-gold"):
        browser.navigate(f"{base_url}/law/import")
        set_theme(theme)

        browser.navigate(f"{base_url}/it")
        browser.wait_for("document.querySelector('.medical-summary-grid .dashboard-stat-card')")
        it_summary = summary_card_style(
            ".medical-summary-grid .dashboard-stat-card",
        )
        browser.navigate(f"{base_url}/medical")
        browser.wait_for("document.querySelector('.medical-summary-grid .dashboard-stat-card')")
        medical_summary = summary_card_style(
            ".medical-summary-grid .dashboard-stat-card",
        )
        browser.navigate(f"{base_url}/law")
        browser.wait_for("document.querySelectorAll('.law-hub-summary .dashboard-stat-card').length === 3")
        law_summary = summary_card_style(
            ".law-hub-summary .dashboard-stat-card",
        )
        for property_name in (
            "background", "border", "radius", "shadow", "padding", "minHeight",
            "labelSize", "valueSize", "supportSize",
        ):
            assert law_summary[property_name] == it_summary[property_name], (
                theme, property_name, law_summary, it_summary,
            )
            assert law_summary[property_name] == medical_summary[property_name], (
                theme, property_name, law_summary, medical_summary,
            )
        for role in ("labelContrast", "valueContrast", "supportContrast"):
            assert law_summary[role] >= 4.5, (theme, role, law_summary)
        observed_law_summary_backgrounds[theme] = law_summary["background"]

        browser.navigate(f"{base_url}/law/import")
        browser.wait_for("document.querySelector('.law-notice.warning .law-secondary-action')")
        empty_state = browser.evaluate(
            "(() => {" + probe_helpers + "const notice=evaluateOn(document.querySelector('.law-notice.warning'),panel);"
            "const action=evaluateOn(document.querySelector('.law-notice.warning .law-secondary-action'),notice.background);"
            "const focus=document.querySelector('.law-notice.warning .law-secondary-action');"
            "focus.disabled=true;const disabled=getComputedStyle(focus);"
            "return {notice,action,"
            "disabledOpacity:disabled.opacity,disabledCursor:disabled.cursor};})()"
        )
        assert empty_state["notice"]["contrast"] >= 4.5
        assert empty_state["action"]["contrast"] >= 4.5
        assert empty_state["notice"]["borderStyle"] != "none"
        assert empty_state["action"]["borderStyle"] != "none"
        assert float(empty_state["disabledOpacity"]) < 1
        assert empty_state["disabledCursor"] == "not-allowed"

        browser.navigate(
            f"{base_url}/law/cases/{case_id}?updated=1&notes_updated=1&"
            "socratic_answers_updated=1&irac_updated=1"
        )
        browser.wait_for(
            "document.querySelector('.law-case-sources .law-case-readonly') && "
            "document.querySelector('.law-case-question-card') && "
            "document.querySelectorAll('.law-case-update-notice').length === 4"
        )
        case_state = browser.evaluate(
            "(() => {" + probe_helpers +
            "const sectionNode=document.querySelector('.law-case-section');"
            "const sourceNode=document.querySelector('.law-case-sources');"
            "const section=evaluateOn(sectionNode,panel);"
            "const heading=evaluateOn(document.querySelector('.law-case-section h2'),section.background);"
            "const muted=evaluateOn(document.querySelector('.law-case-section > p'),section.background);"
            "const inset=evaluateOn(document.querySelector('.law-case-section .law-case-readonly'),section.background);"
            "const sources=evaluateOn(sourceNode,panel);"
            "const sourceText=evaluateOn(document.querySelector('.law-case-sources > strong'),sources.background);"
            "const success=evaluateOn(document.querySelector('.law-case-update-notice'),panel);"
            "const warning=evaluateOn(document.querySelector('.law-case-reminder'),panel);"
            "const info=evaluateOn(document.querySelector('.law-status-pill.info'),panel);"
            "const secondary=evaluateOn(document.querySelector('.law-case-section .law-secondary-action'),section.background);"
            "const sectionRect=sectionNode.getBoundingClientRect();const sourceRect=sourceNode.getBoundingClientRect();"
            "const sectionStyle=getComputedStyle(sectionNode);const sourceStyle=getComputedStyle(sourceNode);"
            "return {scheme:root.getPropertyValue('--theme-color-scheme').trim(),accent:root.getPropertyValue('--theme-accent').trim(),"
            "section,heading,muted,inset,sources,sourceText,success,warning,info,secondary,"
            "geometry:{sectionWidth:sectionRect.width,sourceWidth:sourceRect.width,sectionLeft:sectionRect.left,"
            "sourceLeft:sourceRect.left,sectionRadius:sectionStyle.borderRadius,sourceRadius:sourceStyle.borderRadius,"
            "sectionPadding:sectionStyle.padding,sourcePadding:sourceStyle.padding,"
            "sourceOverflow:sourceRect.right-document.documentElement.clientWidth}};})()"
        )
        for role in (
            "heading", "muted", "inset", "sourceText", "success", "warning",
            "info", "secondary",
        ):
            assert case_state[role]["contrast"] >= 4.5, (theme, role, case_state[role])
        assert case_state["section"]["borderStyle"] != "none"
        assert case_state["inset"]["borderStyle"] != "none"
        assert case_state["section"]["backgroundCss"] != case_state["inset"]["backgroundCss"]
        assert abs(case_state["geometry"]["sectionWidth"] - case_state["geometry"]["sourceWidth"]) <= 1
        assert abs(case_state["geometry"]["sectionLeft"] - case_state["geometry"]["sourceLeft"]) <= 1
        assert case_state["geometry"]["sectionRadius"] == case_state["geometry"]["sourceRadius"]
        assert case_state["geometry"]["sectionPadding"] == case_state["geometry"]["sourcePadding"]
        assert case_state["geometry"]["sourceOverflow"] <= 0
        observed_section_backgrounds[theme] = case_state["section"]["backgroundCss"]

        if theme == "light":
            assert case_state["scheme"] == "light"
            assert min(case_state["section"]["background"]) > .80
            assert min(case_state["inset"]["background"]) > .88
        else:
            assert case_state["scheme"] == "dark"
            assert max(case_state["section"]["background"]) < .40

    assert len(set(observed_section_backgrounds.values())) == 4
    assert len(set(observed_law_summary_backgrounds.values())) == 4

    browser.set_viewport(390, 820)
    browser.navigate(f"{base_url}/law/cases/{case_id}")
    browser.wait_for("document.querySelector('.law-case-sources')")
    narrow_geometry = browser.evaluate(
        "(() => {const sources=document.querySelector('.law-case-sources').getBoundingClientRect();"
        "const section=document.querySelector('.law-case-section').getBoundingClientRect();"
        "return {sourceWidth:sources.width,sectionWidth:section.width,sourceLeft:sources.left,"
        "sectionLeft:section.left,documentWidth:document.documentElement.scrollWidth,"
        "viewportWidth:document.documentElement.clientWidth};})()"
    )
    assert abs(narrow_geometry["sourceWidth"] - narrow_geometry["sectionWidth"]) <= 1
    assert abs(narrow_geometry["sourceLeft"] - narrow_geometry["sectionLeft"]) <= 1
    assert narrow_geometry["documentWidth"] <= narrow_geometry["viewportWidth"]


def test_stateful_learning_and_editor_surfaces_follow_all_themes(browser_stack):
    browser = browser_stack.browser
    base_url = browser_stack.base_url
    data_root = browser_stack.data_root

    review_root = data_root / "pdf_import_drafts"
    review_root.mkdir(exist_ok=True)
    draft_id = "dlms120_batch2_review"
    (review_root / f"{draft_id}.json").write_text(json.dumps({
        "id": draft_id,
        "source_name": "DLMS-120 visual review.pdf",
        "page_count": 2,
        "document_type": "question_bank",
        "detection": {"recovery_mode": True},
        "recovery_mode": True,
        "quiz_title": "DLMS-120 Visual Review",
        "exam_minutes": 30,
        "summary": {"detected": 2, "complete": 0, "review": 1, "incomplete": 1},
        "questions": [
            {
                "number": 1,
                "question": "Question needing review?",
                "choices": [
                    {"label": "A", "text": "First"},
                    {"label": "B", "text": "Second"},
                ],
                "correct": "B",
                "declared_answer_text": "Second",
                "explanation": "Review explanation.",
                "choice_feedback": {"A": "This choice needs review."},
                "pages": [1],
                "status": "review",
                "issues": ["Answer confidence requires review."],
            },
            {
                "number": 2,
                "question": "Incomplete question?",
                "choices": [{"label": "A", "text": "Only detected choice"}],
                "correct": "",
                "declared_answer_text": "",
                "explanation": "",
                "choice_feedback": {},
                "pages": [2],
                "status": "incomplete",
                "issues": ["A correct answer was not detected."],
            },
        ],
    }), encoding="utf-8")

    matching_json = "dlms120_batch2_matching.json"
    matching_html = "dlms120_batch2_matching.html"
    matching_questions = [{
        "number": 1,
        "type": "matching",
        "question": "Match each term to its definition.",
        "round_size": 2,
        "direction": "term_to_definition",
        "pairs": [
            {"left": "Alpha", "right": "First", "explanation": "Alpha is first."},
            {"left": "Beta", "right": "Second", "explanation": "Beta is second."},
        ],
        "concepts": ["dlms-120-theme"],
    }]
    data_folder = data_root / "data"
    quiz_folder = data_root / "quizzes"
    data_folder.mkdir(exist_ok=True)
    quiz_folder.mkdir(exist_ok=True)
    (data_folder / matching_json).write_text(
        json.dumps(matching_questions), encoding="utf-8"
    )
    build_quiz_html(
        matching_html,
        matching_json,
        str(quiz_folder / matching_html),
        "DLMS",
        "DLMS-120 Matching Theme",
        None,
        browser_stack.metadata["critical_id"],
        5,
        normalize_exam_minutes=lambda value: int(value),
    )

    pack_root = data_root / "content_packs" / "DLMS_Study_dlms120_batch2_editor"
    (pack_root / "data").mkdir(parents=True, exist_ok=True)
    (pack_root / "images").mkdir(exist_ok=True)
    image_bytes = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
    )
    (pack_root / "images" / "diagram.png").write_bytes(image_bytes)
    (pack_root / "manifest.json").write_text(json.dumps({
        "schema_version": 1,
        "id": "dlms120_batch2_editor",
        "name": "DLMS-120 Batch 2 Editor",
        "version": "1.0.0",
        "content_domain": "Science",
        "datasets": [],
        "image_datasets": [{
            "id": "visuals", "title": "Visuals", "type": "hotspot",
            "path": "data/visuals.json",
        }],
        "quiz_datasets": [],
    }), encoding="utf-8")
    (pack_root / "data" / "visuals.json").write_text(json.dumps({
        "schema_version": 1,
        "id": "visuals",
        "title": "DLMS-120 Visuals",
        "source": {"organization": "DLMS", "license": "CC0"},
        "images": [{
            "id": "diagram",
            "file": "images/diagram.png",
            "alt_text": "DLMS-120 diagram",
            "source": {"organization": "DLMS", "license": "CC0"},
            "edits": [],
            "hotspots": [{
                "id": "target", "label": "Target", "prompt": "Identify target.",
                "shape": {"type": "circle", "x": .5, "y": .5, "radius": .1},
            }],
        }],
    }), encoding="utf-8")

    def set_theme(theme):
        status = browser.evaluate(
            f"fetch('/api/theme', {{method:'POST', headers:{{'Content-Type':'application/json'}}, "
            f"body:JSON.stringify({{theme:{json.dumps(theme)}}})}}).then(response => response.status)"
        )
        assert status == 200

    probe_helpers = """
        const parseColor=value=>{
          const rgb=value.match(/^rgba?\\(([^)]+)\\)$/);
          if(rgb){const parts=rgb[1].split(/[, ]+/).filter(Boolean).map(Number);
            return [parts[0]/255,parts[1]/255,parts[2]/255,parts.length>3?parts[3]:1];}
          const srgb=value.match(/^color\\(srgb ([^/ )]+) ([^/ )]+) ([^/ )]+)(?: \\/ ([^)]+))?\\)$/);
          if(srgb)return [+srgb[1],+srgb[2],+srgb[3],srgb[4]===undefined?1:+srgb[4]];
          throw new Error('Unsupported computed color: '+value);
        };
        const resolveColor=value=>{const node=document.createElement('span');node.style.color=value;
          document.body.appendChild(node);const result=getComputedStyle(node).color;node.remove();return parseColor(result);};
        const composite=(foreground,background)=>foreground.slice(0,3).map((value,index)=>
          value*foreground[3]+background[index]*(1-foreground[3]));
        const luminance=rgb=>rgb.map(value=>value<=.04045?value/12.92:Math.pow((value+.055)/1.055,2.4))
          .reduce((sum,value,index)=>sum+value*[.2126,.7152,.0722][index],0);
        const contrast=(foreground,background)=>{const a=luminance(foreground.slice(0,3));const b=luminance(background);
          return (Math.max(a,b)+.05)/(Math.min(a,b)+.05);};
        const root=getComputedStyle(document.documentElement);
        const base=resolveColor(root.getPropertyValue('--theme-body-base')).slice(0,3);
        const effectiveBackground=node=>{const layers=[];for(let item=node;item;item=item.parentElement){
          layers.push(parseColor(getComputedStyle(item).backgroundColor));}
          return layers.reverse().reduce((background,layer)=>composite(layer,background),base);};
        const measure=node=>{const style=getComputedStyle(node),background=effectiveBackground(node);
          const foreground=composite(parseColor(style.color),background);return {
            background,backgroundCss:style.backgroundColor,colorCss:style.color,
            borderCss:style.borderColor,borderStyle:style.borderStyle,
            outlineStyle:style.outlineStyle,opacity:style.opacity,cursor:style.cursor,
            contrast:contrast(foreground,background),text:node.textContent.trim()};};
    """

    surfaces_by_theme = {}
    quiz_url = f"{base_url}/quizzes/{matching_html}"
    editor_url = (
        f"{base_url}/admin/image-editor?pack=dlms120_batch2_editor&dataset=visuals&kind=hotspot"
    )
    for theme in ("light", "dark", "purple-gold", "maroon-gold"):
        browser.navigate(f"{base_url}/pdf-import/review/{draft_id}")
        set_theme(theme)
        browser.navigate(f"{base_url}/pdf-import/review/{draft_id}")
        browser.wait_for(
            "document.querySelector('.pdf-status.review') && "
            "document.querySelector('.pdf-status.incomplete') && "
            "document.querySelector('.pdf-feedback-details summary')"
        )
        pdf_state = browser.evaluate(
            "(() => {" + probe_helpers
            + (
                "return {scheme:root.getPropertyValue('--theme-color-scheme').trim(),"
                "review:measure(document.querySelector('.pdf-status.review')),"
                "incomplete:measure(document.querySelector('.pdf-status.incomplete')),"
                "issue:measure(document.querySelector('.pdf-import-issues')),"
                "feedback:measure(document.querySelector('.pdf-feedback-details summary')),"
                "deleteToggle:measure(document.querySelector('.pdf-delete-toggle')),"
                "muted:measure(document.querySelector('.dashboard-header p'))};})()"
            )
        )
        for role in ("review", "incomplete", "issue", "feedback", "deleteToggle", "muted"):
            assert pdf_state[role]["contrast"] >= 4.5, (theme, role, pdf_state[role])
        assert "REVIEW" in pdf_state["review"]["text"]
        assert "INCOMPLETE" in pdf_state["incomplete"]["text"]
        assert pdf_state["review"]["borderStyle"] != "none"
        assert pdf_state["incomplete"]["borderStyle"] != "none"

        browser.navigate(quiz_url)
        browser.evaluate(
            "Object.keys(localStorage).filter(key=>key.startsWith('dlms.quiz-progress.v1:'))"
            ".forEach(key=>localStorage.removeItem(key));true"
        )
        browser.navigate(quiz_url)
        browser.wait_for("quizRecoveryReady === true && quiz.length === 1")
        browser.click(".study-mode-btn")
        browser.wait_for("document.querySelector('.matching-answer-chip')")
        initial_matching = browser.evaluate(
            "(() => {" + probe_helpers
            + (
                "const chip=document.querySelector('.matching-answer-chip');"
                "const target=document.querySelector('.matching-drop-target');"
                "const mode=document.querySelector('.matching-mode-button.active');"
                "chip.focus();return {pool:measure(document.querySelector('.matching-answer-pool')),"
                "chip:measure(chip),target:measure(target),mode:measure(mode)};})()"
            )
        )
        for role in ("chip", "target", "mode"):
            assert initial_matching[role]["contrast"] >= 4.5, (
                theme, role, initial_matching[role]
            )
        assert initial_matching["pool"]["borderStyle"] != "none"

        browser.evaluate("document.querySelector('.matching-answer-chip').click();true")
        browser.wait_for("document.querySelector('.matching-answer-chip.selected')")
        selected = browser.evaluate(
            "(() => {" + probe_helpers
            + "return measure(document.querySelector('.matching-answer-chip.selected'));})()"
        )
        assert selected["contrast"] >= 4.5
        assert selected["outlineStyle"] != "none"

        drag_over = browser.evaluate(
            "(() => {const target=document.querySelector('.matching-drop-target');"
            "const event=new Event('dragover',{bubbles:true,cancelable:true});"
            "Object.defineProperty(event,'dataTransfer',{value:{dropEffect:'none'}});"
            "target.dispatchEvent(event);" + probe_helpers
            + "return measure(target);})()"
        )
        assert drag_over["contrast"] >= 4.5
        assert drag_over["outlineStyle"] != "none"
        browser.evaluate(
            "document.querySelector('.matching-drop-target')"
            ".dispatchEvent(new Event('dragleave',{bubbles:true}));true"
        )

        browser.evaluate(
            "(() => {const chip=document.querySelector('.matching-answer-chip.selected');"
            "const right=Number(chip.dataset.matchAnswer);const left=right===0?1:0;"
            "document.querySelector(`[data-match-target='${left}']`).click();return true;})()"
        )
        browser.wait_for("document.querySelector('.matching-drag-row.matching-wrong')")
        wrong = browser.evaluate(
            "(() => {" + probe_helpers
            + "return measure(document.querySelector('.matching-study-feedback.is-wrong'));})()"
        )
        assert wrong["contrast"] >= 4.5
        assert "Not quite" in wrong["text"]
        browser.click(".matching-clear-match")
        browser.wait_for("!document.querySelector('.matching-clear-match')")
        assert browser.evaluate(
            "!document.querySelector('.matching-drag-row.matching-wrong') && "
            "document.querySelectorAll('.matching-answer-chip').length === 2"
        ) is True

        browser.evaluate(
            "document.querySelector('[data-match-answer=\"0\"]').click();"
            "document.querySelector('[data-match-target=\"0\"]').click();true"
        )
        browser.wait_for("document.querySelector('.matching-drag-row.matching-correct')")
        correct = browser.evaluate(
            "(() => {" + probe_helpers
            + "const feedback=measure(document.querySelector('.matching-study-feedback.is-correct'));"
            "const clear=document.querySelector('.matching-clear-match');clear.disabled=true;"
            "const disabled=measure(clear);return {feedback,disabled};})()"
        )
        assert correct["feedback"]["contrast"] >= 4.5
        assert "Correct" in correct["feedback"]["text"]
        assert float(correct["disabled"]["opacity"]) < 1
        assert correct["disabled"]["cursor"] == "not-allowed"

        browser.navigate(f"{base_url}/admin/image-editor?pack=missing&dataset=broken&kind=hotspot")
        browser.wait_for("document.querySelector('.flash.error') && EDITOR_DATA === null")
        load_error = browser.evaluate(
            "(() => {" + probe_helpers
            + "const error=measure(document.querySelector('.flash.error'));return {error,"
            "empty:!document.querySelector('.hotspot-editor-workspace')};})()"
        )
        assert load_error["empty"] is True
        assert "could not be loaded" in load_error["error"]["text"]
        assert load_error["error"]["contrast"] >= 4.5

        browser.navigate(editor_url)
        browser.wait_for(
            "typeof setStatus === 'function' && document.querySelector('.image-editor-mode-tabs .active')"
        )
        editor_info = browser.evaluate(
            "(() => {" + probe_helpers
            + "document.querySelector('.hotspot-editor-json').open=true;"
            "const active=measure(document.querySelector('.image-editor-mode-tabs .active'));"
            "const inactive=measure(document.querySelector('.image-editor-mode-tabs button:not(.active)'));"
            "const status=measure(document.getElementById('editorStatus'));"
            "const metadata=measure(document.getElementById('geometryPreview'));"
            "return {active,inactive,status,metadata};})()"
        )
        for role in ("active", "inactive", "status", "metadata"):
            assert editor_info[role]["contrast"] >= 4.5, (
                theme, role, editor_info[role]
            )
        assert editor_info["metadata"]["borderStyle"] != "none"

        editor_states = browser.evaluate(
            "(() => {" + probe_helpers
            + "setStatus('Saved editor state.','success');const success=measure(document.getElementById('editorStatus'));"
            "setStatus('Editor state failed.','error');const error=measure(document.getElementById('editorStatus'));"
            "const inactive=document.querySelector('.image-editor-mode-tabs button:not(.active)');"
            "inactive.disabled=true;const disabled=measure(inactive);return {success,error,disabled};})()"
        )
        assert editor_states["success"]["contrast"] >= 4.5
        assert editor_states["error"]["contrast"] >= 4.5
        assert "Saved" in editor_states["success"]["text"]
        assert "failed" in editor_states["error"]["text"]
        assert float(editor_states["disabled"]["opacity"]) < 1
        assert editor_states["disabled"]["cursor"] == "not-allowed"

        surfaces_by_theme[theme] = (
            pdf_state["review"]["backgroundCss"],
            initial_matching["pool"]["backgroundCss"],
            editor_info["status"]["backgroundCss"],
        )
        if theme == "light":
            assert pdf_state["scheme"] == "light"
            assert min(pdf_state["review"]["background"]) > .70
            assert min(initial_matching["pool"]["background"]) > .70
            assert min(editor_info["status"]["background"]) > .70
        else:
            assert pdf_state["scheme"] == "dark"
            assert max(initial_matching["pool"]["background"]) < .45

    assert len(set(surfaces_by_theme.values())) == 4


def test_segment20_law_case_editor_and_anki_external_templates(browser_stack):
    browser = browser_stack.browser
    base_url = browser_stack.base_url
    data_root = browser_stack.data_root
    hostile = 'Browser </textarea><img id="segment20BrowserInjected"> & \u2028\u2029'

    registry_path = data_root / "config" / "law.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    case_id = "segment20-browser-case"
    case_file = f"{case_id}.json"
    case_path = data_root / "law" / "cases" / case_file
    case_path.write_text(json.dumps({
        "id": case_id,
        "type": "law_case_review",
        "title": hostile,
        "course": "Browser Procedure",
        "created_at": "2026-09-07T12:00:00",
        "source_import": "segment20-browser.txt",
        "sources_used": hostile,
        "student_notes": hostile,
        "socratic_student_answers": {"question_1": hostile},
        "irac_student_response": {
            "issue": hostile, "rule": hostile, "analysis": hostile, "conclusion": hostile,
        },
        "sections": {
            "case_brief": hostile,
            "irac_drill": hostile,
            "socratic_review": "1. What rule controls?",
            "socratic_answer_key": hostile,
            "rule_flashcards": "Q: Browser rule?\nA: Browser answer.",
        },
    }), encoding="utf-8")
    registry.setdefault("folders", []).append("Browser Procedure")
    registry["cases"].append({
        "id": case_id,
        "title": hostile,
        "course": "Browser Procedure",
        "file": case_file,
        "hidden": False,
    })
    registry_path.write_text(json.dumps(registry), encoding="utf-8")

    browser.navigate(
        f"{base_url}/law/cases/{case_id}?updated=1&notes_updated=1&"
        "socratic_answers_updated=1&irac_updated=1"
    )
    browser.wait_for(
        "document.querySelectorAll('form input[name=csrf_token]').length === 4 && "
        "document.querySelector('[data-nav-key=law][aria-current=page]')"
    )
    law_state = browser.evaluate(
        "(() => {const forms=[...document.querySelectorAll('main form')];return {"
        "title:document.querySelector('h1').textContent,"
        "actions:forms.map(form=>form.getAttribute('action')),"
        "methods:forms.map(form=>form.method),"
        "csrf:forms.every(form=>!!form.querySelector('input[name=csrf_token]')),"
        "banners:['Case details updated.','Student notes updated.','Socratic answers updated.',"
        "'IRAC response updated.'].every(text=>document.body.textContent.includes(text)),"
        "bannerSemantics:[...document.querySelectorAll('main [role=status]')].every(node=>node.getAttribute('aria-live')==='polite'),"
        "bannerCount:document.querySelectorAll('main [role=status]').length,"
        "titleLabel:document.getElementById('lawCaseTitle').labels[0]?.textContent.trim(),"
        "courseLabel:document.getElementById('lawCaseCourse').labels[0]?.textContent.trim(),"
        "iracLabels:['lawIracIssue','lawIracRule','lawIracAnalysis','lawIracConclusion'].map(id=>document.getElementById(id).labels[0]?.textContent.trim()),"
        "socraticLabel:document.querySelector('[name^=answer_]').labels[0]?.textContent.trim(),"
        "notesName:document.getElementById('lawStudentNotes').getAttribute('aria-labelledby'),"
        "revealState:[...document.querySelectorAll('[aria-controls=iracDrillBox],[aria-controls=socraticAnswerKey]')].map(button=>({expanded:button.getAttribute('aria-expanded'),controlled:!!document.getElementById(button.getAttribute('aria-controls'))})),"
        "exportAction:[...document.querySelectorAll('button')].find(button=>"
        "button.textContent.includes('Export Case Review')).getAttribute('data-law-navigation-url'),"
        "exportInline:[...document.querySelectorAll('button')].find(button=>"
        "button.textContent.includes('Export Case Review')).getAttribute('onclick'),"
        "injected:!!document.getElementById('segment20BrowserInjected'),"
        "current:document.querySelector('[data-nav-key=law]').getAttribute('aria-current'),"
        "menuLabel:document.getElementById('menuButton').getAttribute('aria-label')};})()"
    )
    assert law_state == {
        "title": hostile,
        "actions": [
            f"/law/cases/{case_id}/update_details",
            f"/law/cases/{case_id}/update_irac_response",
            f"/law/cases/{case_id}/update_socratic_answers",
            f"/law/cases/{case_id}/update_notes",
        ],
        "methods": ["post", "post", "post", "post"],
        "csrf": True,
        "banners": True,
        "bannerSemantics": True,
        "bannerCount": 4,
        "titleLabel": "Case Title",
        "courseLabel": "Course",
        "iracLabels": ["Issue", "Rule", "Analysis / Application", "Conclusion"],
        "socraticLabel": "Your Answer",
        "notesName": "lawStudentNotesHeading",
        "revealState": [
            {"expanded": "false", "controlled": True},
            {"expanded": "false", "controlled": True},
        ],
        "exportAction": f"/law/cases/{case_id}/export.txt",
        "exportInline": None,
        "injected": False,
        "current": "page",
        "menuLabel": "Toggle navigation",
    }
    browser.click("[aria-controls=iracDrillBox]")
    browser.click("[aria-controls=socraticAnswerKey]")
    assert browser.evaluate(
        "document.getElementById('iracDrillBox').style.display === 'block' && "
        "document.getElementById('socraticAnswerKey').style.display === 'block' && "
        "document.querySelector('[aria-controls=iracDrillBox]').getAttribute('aria-expanded')==='true' && "
        "document.querySelector('[aria-controls=socraticAnswerKey]').getAttribute('aria-expanded')==='true'"
    ) is True
    browser.evaluate(
        "(() => {const notes=document.querySelector('[name=student_notes]');"
        "notes.value='Segment 20 persisted browser notes';notes.form.requestSubmit();return true;})()"
    )
    browser.wait_for("location.search === '?notes_updated=1'")
    assert json.loads(case_path.read_text(encoding="utf-8"))["student_notes"] == (
        "Segment 20 persisted browser notes"
    )

    quiz_id = browser_stack.metadata["critical_id"]
    browser.navigate(f"{base_url}/anki?source=quiz&quiz_id={quiz_id}#ankiPreview")
    browser.wait_for(
        "document.querySelector('#ankiPreview .anki-preview-card') && "
        "document.querySelector('form[action=\"/anki/export/quiz\"] input[name=csrf_token]')"
    )
    anki_state = browser.evaluate(
        "(() => {const exportForm=document.querySelector('form[action=\"/anki/export/quiz\"]');"
        "return {preview:document.querySelectorAll('#ankiPreview .anki-preview-card').length,"
        "quiz:document.querySelector('select[name=quiz_id]').value,method:exportForm.method,"
        "csrf:!!exportForm.querySelector('[name=csrf_token]'),"
        "current:document.querySelector('[data-nav-key=anki]').getAttribute('aria-current')};})()"
    )
    assert anki_state == {
        "preview": 2,
        "quiz": str(quiz_id),
        "method": "post",
        "csrf": True,
        "current": "page",
    }

    browser.navigate(f"{base_url}/anki/custom")
    browser.wait_for(
        "document.querySelector('[name=quiz_cards]') && "
        "document.querySelector('#customAnkiForm input[name=csrf_token]')"
    )
    browser.evaluate(
        f"(() => {{const form=document.getElementById('customAnkiForm');"
        f"form.deck_name.value={json.dumps(hostile)};"
        "form.querySelector('[name=quiz_cards]').click();"
        "form.querySelector('[formaction=\"/anki/custom\"]').click();return true;})()"
    )
    browser.wait_for(
        "document.querySelector('#ankiPreview .anki-preview-card') && "
        "document.querySelector('[name=quiz_cards]:checked') && "
        "document.querySelector('#customAnkiForm input[name=csrf_token]') && "
        "document.getElementById('ankiSelectedCount').textContent.trim() === '1 card selected'"
    )
    custom_state = browser.evaluate(
        "(() => ({deck:document.querySelector('[name=deck_name]').value,"
        "count:document.getElementById('ankiSelectedCount').textContent.trim(),"
        "preview:document.querySelectorAll('#ankiPreview .anki-preview-card').length,"
        "csrf:!!document.querySelector('#customAnkiForm input[name=csrf_token]'),"
        "injected:!!document.getElementById('segment20BrowserInjected')}))()"
    )
    assert custom_state == {
        "deck": hostile.strip(),
        "count": "1 card selected",
        "preview": 1,
        "csrf": True,
        "injected": False,
    }
    printable = browser.evaluate(
        "(() => {const form=document.getElementById('customAnkiForm');"
        "form.querySelector('[name=duplex_flip]').value='short';"
        "return fetch('/anki/printable',{method:'POST',body:new FormData(form)}).then(async response=>"
        "({status:response.status,text:await response.text()}));})()"
    )
    assert printable["status"] == 200
    assert "Avery 5388" in printable["text"]
    assert "short-edge flip" in printable["text"]
    assert "&lt;/textarea&gt;&lt;img id=&#34;segment20BrowserInjected&#34;&gt;" in printable["text"]
    assert 'id="segment20BrowserInjected"' not in printable["text"]

    law_anki_case_id = "browser-law-negligence"
    browser.navigate(
        f"{base_url}/anki/law?preview=1&law_scope=cases&case_ids={law_anki_case_id}"
    )
    browser.wait_for("document.title === 'Law Study Anki - DLMS'")
    law_anki_state = browser.evaluate(
        "(() => {const form=document.getElementById('lawAnkiForm');return {"
        "scope:form.law_scope.value,caseId:[...form.case_ids.selectedOptions][0].value,"
        "preview:document.querySelectorAll('#ankiPreview .anki-preview-card').length,"
        "cards:document.querySelector('.anki-count-pill')?.textContent.trim()||'',"
        "message:document.querySelector('#ankiPreview .anki-empty-message')?.textContent.trim()||'',"
        "current:document.querySelector('.dashboard-nav-subitem.active').lastElementChild.textContent.trim()};})()"
    )
    assert law_anki_state == {
        "scope": "cases",
        "caseId": law_anki_case_id,
        "preview": 2,
        "cards": "2 cards",
        "message": "",
        "current": "Law Study Anki",
    }


def test_quiz_deletion_prunes_only_deleted_progress_and_stops_former_owner(browser_stack):
    browser = browser_stack.browser
    critical_url = f"{browser_stack.base_url}/quizzes/{browser_stack.metadata['critical_html']}"
    companion_url = f"{browser_stack.base_url}/quizzes/{browser_stack.metadata['companion_html']}"
    browser.navigate(critical_url)
    browser.wait_for("quizRecoveryReady === true")
    browser.click(".study-mode-btn")
    browser.click("#choices .choice[data-index='0']")
    critical_key = browser.evaluate("quizRecoveryController.storageKey")
    first_context = browser.context
    created = browser.command("browsingContext.create", {"type": "tab"})
    companion_context = created["context"]
    try:
        browser.context = companion_context
        browser.navigate(companion_url)
        browser.wait_for("quizRecoveryReady === true")
        browser.click(".study-mode-btn")
        companion_key = browser.evaluate("quizRecoveryController.storageKey")

        browser.context = first_context
        browser.navigate(f"{browser_stack.base_url}/library")
        browser.wait_for("window.DLMSQuizRecovery !== undefined")
        failed_status = browser.evaluate(
            f"fetch('/delete_quiz/{browser_stack.metadata['companion_id']}',"
            "{method:'POST',headers:{'X-CSRFToken':'intentionally-invalid'}}).then(response=>response.status)"
        )
        assert failed_status == 400
        assert browser.evaluate(f"localStorage.getItem({json.dumps(companion_key)}) !== null") is True

        browser.evaluate("window.confirm=()=>true; true")
        browser.click(
            f"form[action='/delete_quiz/{browser_stack.metadata['companion_id']}'] button[type='submit']"
        )
        browser.wait_for("location.pathname === '/library' && window.DLMSQuizRecovery !== undefined")
        browser.wait_for(f"localStorage.getItem({json.dumps(companion_key)}) === null")
        assert browser.evaluate(f"localStorage.getItem({json.dumps(critical_key)}) !== null") is True

        browser.context = companion_context
        browser.wait_for("quizRecoveryController.ownsState === false")
        assert "was cleared" in browser.evaluate(
            "document.getElementById('quizRecoveryNotice').textContent"
        )
        browser.evaluate("checkpointQuizRecovery(); true")
        assert browser.evaluate(f"localStorage.getItem({json.dumps(companion_key)})") is None
    finally:
        browser.context = companion_context
        browser.command("browsingContext.close", {"context": companion_context})
        browser.context = first_context


@pytest.mark.parametrize(
    ("bind_host", "automatic_shutdown_expected"),
    (("127.0.0.1", True), ("0.0.0.0", False)),
    ids=("local-loopback", "lan-server"),
)
def test_browser_presence_runtime_mode_isolated_server(
    tmp_path, bind_host, automatic_shutdown_expected
):
    firefox = shutil.which("firefox") or shutil.which("firefox-esr")
    if not firefox:
        pytest.skip("Firefox is not installed")

    data_root = tmp_path / "presence-data"
    server_port = _free_loopback_port()
    browser_port = _free_loopback_port()
    base_url = f"http://127.0.0.1:{server_port}"
    server_log = tmp_path / "presence-server.log"
    browser_log = tmp_path / "presence-firefox.log"
    profile = tmp_path / "presence-profile"
    profile.mkdir()
    env = os.environ.copy()
    env.update({
        "QUIZAPP_DATA_DIR": str(data_root),
        "DLMS_NO_BROWSER": "1",
        "DLMS_BROWSER_TEST_PORT": str(server_port),
        "DLMS_BROWSER_TEST_BIND_HOST": bind_host,
        "DLMS_BROWSER_PRESENCE_TEST_GRACE_SECONDS": "3",
        "DLMS_BROWSER_PRESENCE_TEST_TOKEN_TTL_SECONDS": "0.8",
        "DLMS_BROWSER_PRESENCE_TEST_POLL_SECONDS": "0.05",
        "MOZ_CRASHREPORTER_DISABLE": "1",
        "MOZ_DISABLE_AUTO_SAFE_MODE": "1",
        "PYTHONUNBUFFERED": "1",
    })
    process_options = {"start_new_session": True} if os.name == "posix" else {}
    server_process = None
    browser_process = None
    browser = None
    try:
        with server_log.open("w", encoding="utf-8") as server_output:
            server_process = subprocess.Popen(
                [sys.executable, str(ROOT / "tests" / "browser" / "_server.py")],
                cwd=ROOT,
                env=env,
                stdout=server_output,
                stderr=subprocess.STDOUT,
                **process_options,
            )
            _wait_for_server(f"{base_url}/library", server_process, server_log)

        with browser_log.open("w", encoding="utf-8") as browser_output:
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

        for path in ("/", "/library", "/library"):
            browser.navigate(base_url + path)
            browser.wait_for("window.dlmsBrowserPresence?.enabled === true")
            browser.wait_for(
                "document.getElementById('shutdownBtn')?.disabled === "
                + ("false" if automatic_shutdown_expected else "true")
            )
            if automatic_shutdown_expected:
                assert browser.evaluate(
                    "document.getElementById('dashboardShutdownUnavailable')"
                ) is None
            else:
                shutdown_state = browser.evaluate(
                    "(() => {const button=document.getElementById('shutdownBtn');"
                    "const note=document.getElementById('dashboardShutdownUnavailable');"
                    "return {disabled:button.disabled,ariaDisabled:button.getAttribute('aria-disabled'),"
                    "describedBy:button.getAttribute('aria-describedby'),"
                    "label:button.querySelector('span:last-child').textContent.trim(),"
                    "note:note?.textContent.trim(),role:note?.getAttribute('role')};})()"
                )
                assert shutdown_state == {
                    "disabled": True,
                    "ariaDisabled": "true",
                    "describedBy": "dashboardShutdownUnavailable",
                    "label": "Shutdown unavailable",
                    "note": (
                        "DLMS is running in LAN/server mode. "
                        "Stop the DLMS process or service from the host computer."
                    ),
                    "role": "status",
                }
            accepted = browser.evaluate(
                "fetch('/api/browser-presence',{method:'POST',"
                "headers:{'Content-Type':'application/json'},"
                "body:JSON.stringify({token:window.dlmsBrowserPresence.token,event:'present'})})"
                ".then(response=>response.json()).then(value=>value.accepted)"
            )
            assert accepted is automatic_shutdown_expected
            assert server_process.poll() is None

        if not automatic_shutdown_expected:
            browser.navigate(base_url + "/settings/lifecycle")
            assert browser.evaluate(
                "document.querySelector('[name=automatic_browser_shutdown_enabled]').disabled"
            ) is True
            assert "Unavailable in LAN/server mode" in browser.evaluate(
                "document.body.innerText"
            )

        browser.close()
        browser = None
        _terminate_process_tree(browser_process)
        browser_process = None

        if automatic_shutdown_expected:
            deadline = time.monotonic() + 7
            while server_process.poll() is None and time.monotonic() < deadline:
                time.sleep(0.05)
            assert server_process.poll() is not None, (
                "presence-enabled local server did not stop after its final page expired\n"
                + server_log.read_text(encoding="utf-8", errors="replace")[-4000:]
            )
        else:
            time.sleep(4)
            assert server_process.poll() is None, (
                "LAN/server-mode DLMS stopped because browser presence disappeared\n"
                + server_log.read_text(encoding="utf-8", errors="replace")[-4000:]
            )
            cookie_jar = http.cookiejar.CookieJar()
            opener = urllib.request.build_opener(
                urllib.request.ProxyHandler({}),
                urllib.request.HTTPCookieProcessor(cookie_jar),
            )
            with opener.open(base_url + "/settings/lifecycle", timeout=3):
                pass
            csrf_cookie = next(
                cookie.value
                for cookie in cookie_jar
                if cookie.name == "dlms_csrf_token"
            )
            shutdown_request = urllib.request.Request(
                base_url + "/api/shutdown",
                data=b"",
                headers={"X-CSRFToken": csrf_cookie},
            )
            with pytest.raises(urllib.error.HTTPError) as rejected:
                opener.open(shutdown_request, timeout=3)
            assert rejected.value.code == 403
            assert json.load(rejected.value) == {
                "status": "unavailable",
                "error": (
                    "Shutdown DLMS is unavailable in LAN/server mode. "
                    "Stop the DLMS process or service from the host computer."
                ),
            }
            assert server_process.poll() is None
    finally:
        if browser is not None:
            browser.close()
        _terminate_process_tree(browser_process)
        _terminate_process_tree(server_process)


def test_legacy_shell_theme_closure_across_all_themes(browser_stack):
    browser = browser_stack.browser
    base_url = browser_stack.base_url
    browser.set_viewport(1280, 1000)
    browser.navigate(base_url + "/")

    def set_theme(theme):
        status = browser.evaluate(
            f"fetch('/api/theme', {{method:'POST', headers:{{'Content-Type':'application/json'}}, "
            f"body:JSON.stringify({{theme:{json.dumps(theme)}}})}}).then(response => response.status)"
        )
        assert status == 200

    probe_helpers = """
        const parseColor=value=>{
          const rgb=value.match(/^rgba?\\(([^)]+)\\)$/);
          if(rgb){const parts=rgb[1].split(/[, ]+/).filter(Boolean).map(Number);
            return [parts[0]/255,parts[1]/255,parts[2]/255,parts.length>3?parts[3]:1];}
          const srgb=value.match(/^color\\(srgb ([^/ )]+) ([^/ )]+) ([^/ )]+)(?: \\/ ([^)]+))?\\)$/);
          if(srgb)return [+srgb[1],+srgb[2],+srgb[3],srgb[4]===undefined?1:+srgb[4]];
          throw new Error('Unsupported computed color: '+value);
        };
        const resolveColor=value=>{const node=document.createElement('span');node.style.color=value;
          document.body.appendChild(node);const result=getComputedStyle(node).color;node.remove();return parseColor(result);};
        const composite=(foreground,background)=>foreground.slice(0,3).map((value,index)=>
          value*foreground[3]+background[index]*(1-foreground[3]));
        const luminance=rgb=>rgb.map(value=>value<=.04045?value/12.92:Math.pow((value+.055)/1.055,2.4))
          .reduce((sum,value,index)=>sum+value*[.2126,.7152,.0722][index],0);
        const contrast=(foreground,background)=>{const a=luminance(foreground.slice(0,3));const b=luminance(background);
          return (Math.max(a,b)+.05)/(Math.min(a,b)+.05);};
        const root=getComputedStyle(document.documentElement);
        const base=resolveColor(root.getPropertyValue('--theme-body-base')).slice(0,3);
        const effectiveBackground=node=>{const layers=[];for(let item=node;item;item=item.parentElement){
          layers.push(parseColor(getComputedStyle(item).backgroundColor));}
          return layers.reverse().reduce((background,layer)=>composite(layer,background),base);};
        const measure=node=>{const style=getComputedStyle(node),background=effectiveBackground(node);
          const foreground=composite(parseColor(style.color),background);return {
            background,backgroundCss:style.backgroundColor,colorCss:style.color,
            borderCss:style.borderColor,borderStyle:style.borderStyle,
            outlineStyle:style.outlineStyle,contrast:contrast(foreground,background),
            text:node.textContent.trim()};};
    """

    surfaces = {}
    for theme in ("light", "dark", "purple-gold", "maroon-gold"):
        browser.navigate(base_url + "/")
        set_theme(theme)
        browser.navigate(base_url + "/")
        browser.wait_for("document.querySelector('.dashboard-welcome')")
        browser.wait_for(
            "getComputedStyle(document.documentElement)"
            ".getPropertyValue('--theme-page-text').trim().length > 0"
        )
        dashboard = browser.evaluate(
            "(() => {" + probe_helpers
            + "return {scheme:root.getPropertyValue('--theme-color-scheme').trim(),"
            "panel:measure(document.querySelector('.dashboard-welcome'))};})()"
        )

        browser.navigate(base_url + "/regex-help")
        browser.wait_for("document.body.classList.contains('regex-help-page')")
        browser.wait_for(
            "getComputedStyle(document.documentElement)"
            ".getPropertyValue('--theme-page-text').trim().length > 0"
        )
        regex_state = browser.evaluate(
            "(() => {" + probe_helpers
            + (
                "const copy=document.querySelector('.copy-btn');copy.classList.add('copied');"
                "return {scheme:root.getPropertyValue('--theme-color-scheme').trim(),"
                "pre:measure(document.querySelector('pre')),"
                "tip:measure(document.querySelector('.tip')),"
                "warning:measure(document.querySelector('.warning')),"
                "copied:measure(copy),nav:measure(document.querySelector('.help-topic-nav a'))};})()"
            )
        )
        for role in ("pre", "tip", "warning", "copied", "nav"):
            assert regex_state[role]["contrast"] >= 4.5, (theme, role, regex_state[role])
            assert regex_state[role]["borderStyle"] != "none", (theme, role)

        browser.navigate(base_url + "/paste")
        browser.wait_for("document.querySelector('form[action=\"/preview_paste\"]')")
        browser.evaluate(
            "(() => {const form=document.createElement('form');form.method='POST';"
            "form.action='/process_paste';document.body.appendChild(form);form.submit();return true;})()"
        )
        browser.wait_for("document.body.classList.contains('request-rejected-page')")
        browser.wait_for(
            "getComputedStyle(document.documentElement)"
            ".getPropertyValue('--theme-page-text').trim().length > 0"
        )
        rejected = browser.evaluate(
            "(() => {" + probe_helpers
            + "return {heading:measure(document.querySelector('h1')),"
            "message:measure(document.querySelector('.request-rejected-card p')),"
            "action:measure(document.querySelector('.legacy-shell-action'))};})()"
        )
        assert "security token" in rejected["message"]["text"].lower()
        for role in ("heading", "message", "action"):
            assert rejected[role]["contrast"] >= 4.5, (theme, role, rejected[role])

        browser.navigate(base_url + "/paste")
        browser.wait_for(
            "document.querySelector('form[action=\"/preview_paste\"] input[name=csrf_token]')"
        )
        browser.evaluate(
            "(() => {const token=document.querySelector('input[name=csrf_token]').value;"
            "const form=document.createElement('form');form.method='POST';form.action='/process_paste';"
            "for(const [name,value] of Object.entries({csrf_token:token,quiz_title:'Theme closure',"
            "quiz_text:'This text cannot be parsed as a quiz.'})){const input=document.createElement('input');"
            "input.name=name;input.value=value;form.appendChild(input);}document.body.appendChild(form);"
            "form.submit();return true;})()"
        )
        browser.wait_for("document.body.classList.contains('parse-failed-page')")
        browser.wait_for(
            "getComputedStyle(document.documentElement)"
            ".getPropertyValue('--theme-page-text').trim().length > 0"
        )
        parse_state = browser.evaluate(
            "(() => {" + probe_helpers
            + "return {heading:measure(document.querySelector('.legacy-shell-heading')),"
            "copy:measure(document.querySelector('.parse-failed-card p')),"
            "action:measure(document.querySelector('.legacy-shell-actions button'))};})()"
        )
        for role in ("heading", "copy", "action"):
            assert parse_state[role]["contrast"] >= 4.5, (theme, role, parse_state[role])
        assert parse_state["heading"]["borderStyle"] != "none"

        expected_scheme = "light" if theme == "light" else "dark"
        assert dashboard["scheme"] == regex_state["scheme"] == expected_scheme
        surfaces[theme] = {
            "dashboard": dashboard["panel"]["backgroundCss"],
            "regex": regex_state["pre"]["backgroundCss"],
            "rejected": rejected["action"]["backgroundCss"],
            "parse": parse_state["action"]["backgroundCss"],
        }

    assert len({state["regex"] for state in surfaces.values()}) == 4
    assert len({state["rejected"] for state in surfaces.values()}) == 4
    assert len({state["parse"] for state in surfaces.values()}) == 4

    browser.set_viewport(390, 780)
    for path, ready in (
        ("/regex-help", "document.body.classList.contains('regex-help-page')"),
        ("/paste", "document.querySelector('form[action=\"/preview_paste\"]')"),
    ):
        browser.navigate(base_url + path)
        browser.wait_for(ready)
        assert browser.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1") is True


def test_post_310_workflows_stack_by_available_content_width(browser_stack):
    """Sidebar-constrained workflows must respond to content, not viewport, width."""
    browser = browser_stack.browser
    base_url = browser_stack.base_url
    cases = (
        (
            "/quiz-composer",
            "document.querySelector('.mixed-builder-intro')",
            "getComputedStyle(document.querySelector('.mixed-builder-intro')).flexDirection === 'column' && "
            "getComputedStyle(document.querySelector('.mixed-builder-plan')).flexDirection === 'column'",
        ),
        (
            "/library/duplicates",
            "document.querySelector('.duplicate-question-intro')",
            "getComputedStyle(document.querySelector('.duplicate-question-intro')).flexDirection === 'column'",
        ),
        (
            "/learning-intelligence",
            "document.getElementById('liLoading').hidden",
            "getComputedStyle(document.querySelector('.learning-intelligence-panel-head')).flexDirection === 'column'",
        ),
        (
            "/review-schedule",
            "document.querySelector('.review-schedule-actions')",
            "getComputedStyle(document.querySelector('.review-schedule-actions')).flexDirection === 'column'",
        ),
        (
            "/pdf-import",
            "document.querySelector('.pdf-ocr-import-panel .pdf-bank-panel-heading')",
            "getComputedStyle(document.querySelector('.pdf-ocr-import-panel .pdf-bank-panel-heading')).flexDirection === 'column' && "
            "getComputedStyle(document.querySelector('.pdf-import-upload-form')).flexDirection === 'column'",
        ),
    )

    browser.set_viewport(1024, 900)
    for path, ready, stacked in cases:
        browser.navigate(base_url + path)
        browser.wait_for(ready)
        state = browser.evaluate(
            "(() => {const main=document.querySelector('.dashboard-main');"
            "const controls=[...main.querySelectorAll('a,button,input,select,textarea')]"
            ".filter(item=>item.getClientRects().length);const bounds=main.getBoundingClientRect();"
            "return {stacked:" + stacked + ","
            "contained:controls.every(item=>{const rect=item.getBoundingClientRect();"
            "return rect.left>=bounds.left-1&&rect.right<=bounds.right+1;}),"
            "overflow:document.documentElement.scrollWidth<=window.innerWidth+1};})()"
        )
        assert state == {"stacked": True, "contained": True, "overflow": True}, (
            path, state,
        )

    # Concept performance is intentionally a horizontally scrollable comparison
    # table at this width. Its Practice column remains pinned so the primary row
    # action is reachable before and after the user scrolls the metrics. The
    # pinned cells use an opaque theme base beneath their themed overlay so
    # neighboring metric text cannot show through them.
    for theme in ("light", "dark", "purple-gold", "maroon-gold"):
        browser.set_viewport(1024, 900)
        _set_theme(browser, theme)
        browser.navigate(base_url + "/learning-intelligence")
        browser.wait_for("document.getElementById('liLoading').hidden")
        if browser.evaluate("!document.getElementById('liToggleZeroEvidence').hidden"):
            browser.click("#liToggleZeroEvidence")
        browser.wait_for(
            "!document.getElementById('liTableWrap').hidden && "
            "document.querySelector('.li-concept-review-form .build-secondary-link')"
        )
        table_state = browser.evaluate(
            "(() => {const wrap=document.getElementById('liTableWrap');"
            "const action=document.querySelector('.li-concept-review-form .build-secondary-link');"
            "const cell=action.closest('td');const header=document.querySelector("
            "'.learning-intelligence-table th:last-child');"
            "const bounds=wrap.getBoundingClientRect();"
            "const resolve=value=>{const probe=document.createElement('span');"
            "probe.style.color=value;document.body.appendChild(probe);"
            "const result=getComputedStyle(probe).color;probe.remove();return result;};"
            "const base=resolve(getComputedStyle(document.documentElement)"
            ".getPropertyValue('--theme-body-base'));"
            "const occludes=target=>{const rect=target.getBoundingClientRect();"
            "const top=document.elementFromPoint(rect.left+Math.min(8,rect.width/2),"
            "rect.top+rect.height/2);return top?.closest('td,th')===target;};"
            "const contained=()=>{const rect=action.getBoundingClientRect();"
            "return rect.left>=bounds.left-1&&rect.right<=bounds.right+1;};"
            "const cellStyle=getComputedStyle(cell),headerStyle=getComputedStyle(header);"
            "const before=contained(),cellTopBefore=occludes(cell),headerTopBefore=occludes(header);"
            "wrap.scrollLeft=wrap.scrollWidth;"
            "return {scrollable:wrap.scrollWidth>wrap.clientWidth,"
            "practicePosition:getComputedStyle(cell).position,"
            "actionBeforeScroll:before,actionAfterScroll:contained(),"
            "cellOpaqueBase:cellStyle.backgroundColor===base,"
            "headerOpaqueBase:headerStyle.backgroundColor===base,"
            "cellOverlay:cellStyle.backgroundImage!=='none',"
            "headerOverlay:headerStyle.backgroundImage!=='none',"
            "cellTopBefore,headerTopBefore,cellTopAfter:occludes(cell),"
            "headerTopAfter:occludes(header),"
            "documentFits:document.documentElement.scrollWidth<=window.innerWidth+1};})()"
        )
        assert table_state == {
            "scrollable": True,
            "practicePosition": "sticky",
            "actionBeforeScroll": True,
            "actionAfterScroll": True,
            "cellOpaqueBase": True,
            "headerOpaqueBase": True,
            "cellOverlay": True,
            "headerOverlay": True,
            "cellTopBefore": True,
            "headerTopBefore": True,
            "cellTopAfter": True,
            "headerTopAfter": True,
            "documentFits": True,
        }, (theme, table_state)

        browser.set_viewport(1600, 1000)
        wide_state = browser.evaluate(
            "(() => {const cell=document.querySelector("
            "'.learning-intelligence-table td:last-child');"
            "const header=document.querySelector('.learning-intelligence-table th:last-child');"
            "const resolve=value=>{const probe=document.createElement('span');"
            "probe.style.color=value;document.body.appendChild(probe);"
            "const result=getComputedStyle(probe).color;probe.remove();return result;};"
            "const base=resolve(getComputedStyle(document.documentElement)"
            ".getPropertyValue('--theme-body-base'));"
            "return {position:getComputedStyle(cell).position,"
            "cellOpaque:getComputedStyle(cell).backgroundColor===base,"
            "headerOpaque:getComputedStyle(header).backgroundColor===base,"
            "documentFits:document.documentElement.scrollWidth<=window.innerWidth+1};})()"
        )
        assert wide_state == {
            "position": "sticky",
            "cellOpaque": True,
            "headerOpaque": True,
            "documentFits": True,
        }, (theme, wide_state)

    browser.set_viewport(920, 900)
    browser.navigate(base_url + "/external-ai/quiz-builder")
    browser.wait_for("document.querySelector('.external-ai-builder-grid')")
    external_ai = browser.evaluate(
        "(() => {const grid=document.querySelector('.external-ai-builder-grid');"
        "const steps=document.querySelector('.external-ai-builder-steps');"
        "return {gridColumns:getComputedStyle(grid).gridTemplateColumns.split(' ').length,"
        "stepColumns:new Set([...steps.children].map(item=>"
        "Math.round(item.getBoundingClientRect().left))).size,"
        "overflow:document.documentElement.scrollWidth<=window.innerWidth+1};})()"
    )
    assert external_ai == {"gridColumns": 1, "stepColumns": 1, "overflow": True}

    browser.navigate(base_url + "/")
    browser.wait_for("document.querySelector('.daily-review-item')")
    daily = browser.evaluate(
        "(() => {const item=document.querySelector('.daily-review-item');"
        "const copy=item.querySelector('.daily-review-copy').getBoundingClientRect();"
        "const action=item.querySelector('.daily-review-item-action').getBoundingClientRect();"
        "return {actionBelow:action.top>=copy.bottom,"
        "actionContained:action.left>=item.getBoundingClientRect().left&&"
        "action.right<=item.getBoundingClientRect().right,"
        "overflow:document.documentElement.scrollWidth<=window.innerWidth+1};})()"
    )
    assert daily == {"actionBelow": True, "actionContained": True, "overflow": True}

    for path, ready, _stacked in cases + (
        ("/external-ai/quiz-builder", "document.querySelector('.external-ai-builder-grid')", "true"),
        ("/", "document.querySelector('.daily-review-item')", "true"),
        ("/quiz-bundles", "document.querySelector('.portable-bundle-workflows')", "true"),
        ("/help/learning-intelligence", "document.getElementById('which-review')", "true"),
    ):
        browser.set_viewport(420, 820)
        browser.navigate(base_url + path)
        browser.wait_for(ready)
        assert browser.evaluate(
            "document.documentElement.scrollWidth <= window.innerWidth + 1"
        ) is True, path


def test_learning_scope_management_filters_active_recommendations_across_themes_and_widths(browser_stack):
    browser = browser_stack.browser
    base_url = browser_stack.base_url
    portal_path = browser_stack.data_root / "config" / "portal.json"
    portal = json.loads(portal_path.read_text(encoding="utf-8"))
    long_folder = "ArchivedCourseWithoutSpaces" * 5
    portal["quiz_folders"].append(long_folder)
    portal_path.write_text(json.dumps(portal), encoding="utf-8")

    browser.navigate(base_url + "/learning-scope")
    browser.wait_for("document.querySelectorAll('.learning-scope-folder').length === 3")
    assert browser.evaluate(
        "document.body.textContent.includes('2 source quizzes included')"
    ) is True

    for theme in ("light", "dark", "purple-gold", "maroon-gold"):
        _set_theme(browser, theme)
        browser.navigate(base_url + "/learning-scope")
        browser.wait_for("document.querySelectorAll('.learning-scope-folder').length === 3")
        contrast = _theme_contrast_snapshot(browser, {
            "folder name": ".learning-scope-folder h3",
            "folder detail": ".learning-scope-folder p",
            "folder status": ".learning-scope-folder strong",
            "folder action": ".learning-scope-folder button",
        })
        assert all(item["contrast"] >= 4.5 for item in contrast.values()), (theme, contrast)
        for width in (1440, 1024, 760, 420):
            browser.set_viewport(width, 900)
            layout = browser.evaluate(
                "(() => {const rows=[...document.querySelectorAll('.learning-scope-folder')];"
                "return {overflow:document.documentElement.scrollWidth>window.innerWidth+1,"
                "buttons:rows.every(row=>{const button=row.querySelector('button');"
                "const rect=button.getBoundingClientRect();return rect.width>=100&&rect.right<=window.innerWidth+1}),"
                "names:rows.every(row=>row.querySelector('h3').scrollWidth<=row.querySelector('h3').clientWidth+1)};})()"
            )
            assert layout == {"overflow": False, "buttons": True, "names": True}, (theme, width, layout)

    browser.navigate(f"{base_url}/quizzes/{browser_stack.metadata['critical_html']}")
    browser.wait_for("quizRecoveryReady === true && quiz.length === 2")
    browser.click(".study-mode-btn")
    browser.click("#choices .choice[data-index='0']")
    browser.wait_for("studyLearningEventSaves.size === 0")
    browser.click("#nextBtn")
    browser.wait_for("index === 1")
    browser.navigate(base_url + "/learning-scope")
    browser.wait_for("document.querySelectorAll('.learning-scope-folder').length === 3")
    browser.set_viewport(1024, 900)
    browser.activate()
    assert browser.evaluate(
        "(() => {const form=[...document.querySelectorAll('.learning-scope-folder form')]"
        ".find(item=>item.querySelector('[name=folder]').value==='Browser Regression');"
        "form.querySelector('button').focus();return document.activeElement===form.querySelector('button');})()"
    ) is True
    browser.click(".learning-scope-folder form:has([name=folder][value='Browser Regression']) button")
    browser.wait_for("document.body.textContent.includes('Browser Regression is excluded from Learning Scope')")
    assert browser.evaluate(
        "fetch('/api/learning-scope').then(r=>r.json()).then(x=>x.excluded_folders===1&&x.included_source_quizzes===0)"
    ) is True
    assert browser.evaluate(
        "fetch('/api/learning-intelligence/topics').then(r=>r.json()).then(x=>x.summary.concepts===0)"
    ) is True
    assert browser.evaluate(
        "fetch('/api/review-schedule').then(r=>r.json()).then(x=>x.question_summary.eligible_questions===0)"
    ) is True
    assert browser.evaluate(
        "fetch('/api/daily-review-plan').then(r=>r.json()).then(x=>x.summary.adaptive_candidates===0)"
    ) is True
    for theme in ("light", "dark", "purple-gold", "maroon-gold"):
        _set_theme(browser, theme)
        for width in (1440, 1024, 760, 420):
            browser.set_viewport(width, 900)
            browser.navigate(base_url + "/learning-intelligence")
            browser.wait_for(
                "document.getElementById('liScopeSummary')?.textContent.includes('1 folder excluded')"
            )
            assert browser.evaluate(
                "document.documentElement.scrollWidth <= window.innerWidth + 1"
            ) is True, (theme, width, "Learning Intelligence")
            browser.navigate(base_url + "/library?view=all")
            browser.wait_for("document.querySelector('.library-learning-scope-badge')")
            assert browser.evaluate(
                "document.documentElement.scrollWidth <= window.innerWidth + 1"
            ) is True, (theme, width, "Quiz Library")
    browser.navigate(base_url + "/")
    browser.wait_for(
        "document.querySelector('.daily-review-unfinished')?.textContent.includes('Browser Critical Workflow')"
    )
    assert browser.evaluate(
        "document.querySelector('.daily-review-unfinished').textContent.includes('This browser')"
    ) is True

    browser.navigate(base_url + "/library?view=all")
    browser.wait_for("document.querySelector('.library-folder')")
    assert browser.evaluate(
        "document.body.textContent.includes('Excluded from Learning Scope') && "
        "document.body.textContent.includes('Browser Critical Workflow')"
    ) is True
    browser.navigate(base_url + "/history")
    browser.wait_for("document.body.textContent.includes('Browser Critical Workflow')")


def test_review_schedule_summary_and_queue_controls_stay_contained(browser_stack):
    """Review metrics and the Question Queue controls remain contained."""
    browser = browser_stack.browser
    base_url = browser_stack.base_url
    probe = (
        "(() => {const cards=[...document.querySelectorAll("
        "'.review-schedule-summary .dashboard-stat-card')];"
        "const inspect=card=>{const [label,value,support]=card.children;"
        "const cardRect=card.getBoundingClientRect(),labelRect=label.getBoundingClientRect(),"
        "valueRect=value.getBoundingClientRect(),supportRect=support.getBoundingClientRect();"
        "const contained=rect=>rect.left>=cardRect.left-1&&rect.right<=cardRect.right+1&&"
        "rect.top>=cardRect.top-1&&rect.bottom<=cardRect.bottom+1;"
        "return {columns:getComputedStyle(card).gridTemplateColumns.split(' ').length,"
        "labelBeforeValue:labelRect.bottom<=valueRect.top+1,"
        "valueBeforeSupport:valueRect.bottom<=supportRect.top+1,"
        "contained:[labelRect,valueRect,supportRect].every(contained),"
        "fits:card.scrollWidth<=card.clientWidth+1};};"
        "const panel=document.querySelector('.native-review-list-panel'),"
        "head=panel.querySelector('.native-review-list-head'),"
        "eyebrow=head.querySelector('.build-eyebrow'),heading=head.querySelector('h2'),"
        "count=head.querySelector('#nrsQueueCount'),toggle=head.querySelector('#nrsQueueToggle'),"
        "body=panel.querySelector('#nrsQueueBody'),copy=body.querySelector('p'),"
        "toolbar=body.querySelector('.native-review-queue-toolbar'),"
        "filters=[...body.querySelectorAll('[data-question-status]')],"
        "search=body.querySelector('#nrsSearch'),table=panel.querySelector('#nrsTableWrap'),"
        "panelRect=panel.getBoundingClientRect();"
        "const inside=element=>{const rect=element.getBoundingClientRect();"
        "return rect.left>=panelRect.left-1&&rect.right<=panelRect.right+1&&"
        "rect.top>=panelRect.top-1&&rect.bottom<=panelRect.bottom+1;};"
        "const headStyle=getComputedStyle(head),toolbarStyle=getComputedStyle(toolbar),"
        "tableRect=table.getBoundingClientRect();"
        "return {count:cards.length,cards:cards.map(inspect),queue:{"
        "contained:[eyebrow,heading,count,toggle,copy,search,...filters].every(inside),"
        "topInset:eyebrow.getBoundingClientRect().top-panelRect.top,"
        "paddingTop:parseFloat(headStyle.paddingTop),"
        "stacked:headStyle.gridTemplateColumns.split(' ').length===1,"
        "toolbarStacked:toolbarStyle.flexDirection==='column',"
        "expanded:toggle.getAttribute('aria-expanded'),bodyHidden:body.hidden,"
        "selected:filters.filter(button=>button.getAttribute('aria-pressed')==='true').map(button=>button.dataset.questionStatus),"
        "tableFullWidth:Math.abs(tableRect.left-panelRect.left)<=1&&"
        "Math.abs(tableRect.right-panelRect.right)<=1},"
        "documentFits:document.documentElement.scrollWidth<=window.innerWidth+1};})()"
    )

    browser.navigate(base_url + "/")
    browser.wait_for("document.querySelector('.dashboard-shell')")
    for theme in ("light", "dark", "purple-gold", "maroon-gold"):
        _set_theme(browser, theme)
        for width in (1440, 1024, 760, 420):
            browser.set_viewport(width, 900)
            browser.navigate(base_url + "/review-schedule")
            browser.wait_for(
                "document.getElementById('nrsDue').textContent !== '—' && "
                "document.getElementById('rsDue').textContent !== '—'"
            )
            state = browser.evaluate(probe)
            case = (theme, width, state)
            assert state["count"] == 8, case
            assert state["documentFits"] is True, case
            expected_padding = 18 if width == 420 else 22
            assert state["queue"]["paddingTop"] == expected_padding, case
            assert state["queue"]["topInset"] >= expected_padding - 1, case
            assert state["queue"]["contained"] is True, case
            assert state["queue"]["stacked"] is (width <= 1024), case
            assert state["queue"]["toolbarStacked"] is (width <= 1024), case
            assert state["queue"]["expanded"] == "true", case
            assert state["queue"]["bodyHidden"] is False, case
            assert state["queue"]["selected"] == ["all"], case
            assert state["queue"]["tableFullWidth"] is True, case
            assert all(
                card["columns"] == 1
                and card["labelBeforeValue"]
                and card["valueBeforeSupport"]
                and card["contained"]
                and card["fits"]
                for card in state["cards"]
            ), case
            if width == 1440:
                contrast = _theme_contrast_snapshot(browser, {
                    "queue toggle": "#nrsQueueToggle",
                    "selected status": "[data-question-status='all']",
                    "inactive status": "[data-question-status='upcoming']",
                    "question count": "#nrsQueueCount",
                })
                assert all(item["contrast"] >= 4.5 for item in contrast.values()), (
                    theme, contrast,
                )


def test_post_310_workflow_text_and_controls_remain_readable_across_themes(
    browser_stack,
):
    """Rendered 3.2.0 surfaces must keep semantic text contrast in every palette."""
    browser = browser_stack.browser
    base_url = browser_stack.base_url
    browser.set_viewport(1280, 1000)
    browser.navigate(base_url + "/")
    browser.wait_for("document.querySelector('.daily-review-panel')")

    pages = (
        (
            "/",
            "document.querySelector('.daily-review-action')",
            {
                "daily intro": ".daily-review-intro",
                "daily count": ".daily-review-count",
                "daily explanation": ".daily-review-copy p",
                "daily action": ".daily-review-action",
            },
        ),
        (
            "/learning-intelligence",
            "document.getElementById('liLoading').hidden",
            {
                "intelligence description": ".learning-intelligence-panel-head p",
                "adaptive signal": ".adaptive-study-signals li span",
                "adaptive helper": ".learning-intelligence-review-form > span",
                "active intelligence filter": ".learning-intelligence-filters button.active",
                "mastery help action": "#liModelButton",
            },
        ),
        (
            "/review-schedule",
            "document.querySelector('.review-schedule-actions')",
            {
                "due review description": ".native-review-actions p",
                "due review field label": ".native-review-actions label",
                "due review batch summary": "#nrsBatchSummary",
                "schedule model description": ".native-review-model p",
            },
        ),
        (
            "/quiz-composer",
            "document.querySelector('.mixed-builder-filters')",
            {
                "mixed back link": ".mixed-builder-intro .build-secondary-link",
                "mixed filter label": ".mixed-builder-filter-grid label",
                "mixed bulk action": ".mixed-builder-bulk-actions button",
                "mixed question metadata": ".mixed-builder-question-meta span",
                "mixed create action": ".mixed-builder-plan .library-primary-action",
            },
        ),
        (
            "/external-ai/quiz-builder",
            "document.getElementById('externalAiCopyPrompt')",
            {
                "external AI card copy": ".external-ai-builder-card .build-section-heading p",
                "external AI field label": ".external-ai-builder-card .build-field",
                "external AI field helper": ".external-ai-builder-card .build-field small",
                "external AI status": "#externalAiCopyStatus",
                "external AI disabled action": "#externalAiCopyPrompt",
                "external AI back link": ".external-ai-builder-actions .build-secondary-link",
            },
        ),
        (
            "/pdf-import",
            "document.getElementById('ocrMatchingUploadForm')",
            {
                "OCR matching label": "#ocrMatchingUploadForm .build-field",
                "OCR matching helper": "#ocrMatchingUploadForm .build-field small",
                "OCR matching guidance heading": "#ocrMatchingUploadForm .pdf-ocr-guidance strong",
                "OCR matching guidance copy": "#ocrMatchingUploadForm .pdf-ocr-guidance span",
                "OCR local note": "#ocrMatchingUploadForm .pdf-ocr-local-note",
            },
        ),
        (
            "/library/duplicates",
            "document.querySelector('.duplicate-question-summary')",
            {
                "duplicate back link": ".duplicate-question-intro .build-secondary-link",
                "duplicate explanation": ".duplicate-question-intro p",
                "duplicate summary helper": ".duplicate-question-summary .library-stat-card small",
            },
        ),
        (
            "/quiz-bundles",
            "document.querySelector('.portable-bundle-selection-actions')",
            {
                "bundle back link": ".portable-bundle-intro .build-secondary-link",
                "bundle select all": "#selectAllBundleQuizzes",
                "bundle clear": "#clearBundleQuizzes",
                "bundle file label": ".portable-bundle-upload-form .build-field",
                "bundle file helper": ".portable-bundle-upload-form .build-field small",
                "bundle step": ".portable-bundle-step",
                "bundle boundary copy": ".portable-bundle-boundary p",
                "bundle validate action": ".portable-bundle-upload-form .library-primary-action",
            },
        ),
        (
            "/library",
            "document.querySelector('.library-hero-actions a[href=\"/quiz-bundles\"]')",
            {
                "bundle library action": ".library-hero-actions a[href=\"/quiz-bundles\"]",
                "duplicate library action": ".library-hero-actions a[href=\"/library/duplicates\"]",
                "mixed library action": ".library-hero-actions a[href=\"/quiz-composer\"]",
            },
        ),
        (
            "/upload",
            "document.querySelector('.build-option-card-external-ai')",
            {
                "external AI build label": ".build-option-card-external-ai .build-method-label",
                "external AI build copy": ".build-option-card-external-ai p",
                "PDF build label": ".build-option-card-pdf .build-method-label",
                "PDF build copy": ".build-option-card-pdf p",
            },
        ),
        (
            "/help/learning-intelligence",
            "document.getElementById('which-review')",
            {
                "review guide intro": "#which-review .help-callout",
                "review guide table": "#which-review .help-table td",
                "review guide action": ".help-topic-nav a",
            },
        ),
    )

    for theme in ("light", "dark", "purple-gold", "maroon-gold"):
        _set_theme(browser, theme)
        for path, ready, selectors in pages:
            browser.navigate(base_url + path)
            browser.wait_for(ready)
            snapshot = _theme_contrast_snapshot(browser, selectors)
            for role, state in snapshot.items():
                assert state["contrast"] >= 4.5, (theme, path, role, state)

        browser.navigate(base_url + "/quiz-bundles")
        browser.wait_for("document.getElementById('selectAllBundleQuizzes')")
        browser.click("#selectAllBundleQuizzes")
        assert browser.evaluate(
            "document.getElementById('selectAllBundleQuizzes').matches(':hover')"
        ) is True
        hovered = _theme_contrast_snapshot(
            browser, {"hovered bundle action": "#selectAllBundleQuizzes"},
        )["hovered bundle action"]
        assert hovered["contrast"] >= 4.5, (theme, hovered)
        browser.evaluate("document.getElementById('selectAllBundleQuizzes').focus();true")
        browser.press_key("\ue004")
        assert browser.evaluate("document.activeElement.id") == "clearBundleQuizzes"
        focused = _theme_contrast_snapshot(
            browser, {"focused bundle action": "#clearBundleQuizzes"},
        )["focused bundle action"]
        assert focused["contrast"] >= 4.5, (theme, focused)
        assert focused["borderStyle"] != "none", (theme, focused)

        browser.navigate(base_url + "/external-ai/quiz-builder")
        browser.wait_for("document.getElementById('externalAiCopyPrompt')")
        disabled = _theme_contrast_snapshot(
            browser, {"disabled copy action": "#externalAiCopyPrompt"},
        )["disabled copy action"]
        assert disabled["opacity"] == "1", (theme, disabled)
        assert disabled["cursor"] == "not-allowed", (theme, disabled)


def test_mastery_explanation_and_recovery_actions_are_accessible_across_themes(
    browser_stack,
):
    browser = browser_stack.browser
    base_url = browser_stack.base_url

    def move_pointer(selector, *, pressed=False):
        coordinates = browser.evaluate(
            "(() => {const rect=document.querySelector("
            + json.dumps(selector)
            + ").getBoundingClientRect();return {x:rect.left+rect.width/2,"
            "y:rect.top+rect.height/2};})()"
        )
        actions = [{
            "type": "pointerMove",
            "x": round(coordinates["x"]),
            "y": round(coordinates["y"]),
            "duration": 0,
            "origin": "viewport",
        }]
        if pressed:
            actions.append({"type": "pointerDown", "button": 0})
        browser.command("input.performActions", {
            "context": browser.context,
            "actions": [{
                "type": "pointer",
                "id": "recovery-action-mouse",
                "parameters": {"pointerType": "mouse"},
                "actions": actions,
            }],
        })

    for theme in ("light", "dark", "purple-gold", "maroon-gold"):
        browser.set_viewport(520, 900)
        browser.navigate(base_url + "/learning-intelligence")
        browser.wait_for("document.getElementById('liLoading').hidden")
        _set_theme(browser, theme)
        browser.navigate(base_url + "/learning-intelligence")
        browser.wait_for("document.getElementById('liLoading').hidden")
        browser.click("#liModelButton")
        browser.wait_for("!document.getElementById('liModel').hidden")
        mastery = browser.evaluate(
            "(() => {const dialog=document.querySelector('.learning-intelligence-model-dialog');"
            "const factors=[...document.querySelectorAll('.li-mastery-factors li')];"
            "return {text:dialog.innerText,factorCount:factors.length,"
            "oneColumn:factors.length>1 && Math.abs(factors[0].getBoundingClientRect().left-"
            "factors[1].getBoundingClientRect().left)<1,"
            "overflow:document.documentElement.scrollWidth-window.innerWidth};})()"
        )
        assert mastery["factorCount"] == 4
        assert mastery["oneColumn"] is True
        assert mastery["overflow"] <= 1
        for phrase in (
            "Your score combines four things",
            "Not enough data",
            "Weak area",
            "Trend is different from Mastery",
            "Technical details",
        ):
            assert phrase in mastery["text"]
        explanation_contrast = _theme_contrast_snapshot(browser, {
            "mastery introduction": ".li-mastery-intro",
            "mastery factor": ".li-mastery-factors li strong",
            "mastery factor detail": ".li-mastery-factors li p",
            "technical disclosure": ".li-mastery-technical summary",
        })
        for role, state in explanation_contrast.items():
            assert state["contrast"] >= 4.5, (theme, role, state)
        browser.wait_for(
            "document.activeElement.matches('.learning-intelligence-model-close')"
        )
        browser.evaluate(
            "document.querySelector('.li-mastery-technical summary').focus();true"
        )
        active_element = browser.evaluate(
            "(() => ({tag:document.activeElement.tagName,"
            "className:document.activeElement.className}))()"
        )
        assert active_element["tag"] == "SUMMARY", (theme, active_element)
        browser.click(".li-mastery-technical summary")
        assert browser.evaluate("document.querySelector('.li-mastery-technical').open") is True
        browser.press_key("\ue00c")
        assert browser.evaluate("document.getElementById('liModel').hidden") is True
        assert browser.evaluate("document.activeElement.id") == "liModelButton"

        browser.set_viewport(760, 800)
        browser.navigate(base_url + "/")
        browser.wait_for("document.querySelector('.daily-review-panel')")
        browser.evaluate(
            "(() => {const host=document.querySelector('.dashboard-main');"
            "const panel=document.createElement('section');panel.className='mode-center';"
            "panel.innerHTML='<div class=\"quiz-recovery-actions\">' +"
            "'<button class=\"quiz-recovery-resume\">Resume</button>' +"
            "'<button class=\"quiz-recovery-start-over\">Start Over</button></div>';"
            "host.prepend(panel);return true;})()"
        )
        normal = _theme_contrast_snapshot(browser, {
            "resume": ".quiz-recovery-resume",
            "start over": ".quiz-recovery-start-over",
        })
        assert normal["start over"]["contrast"] >= 4.5, (theme, normal)
        assert normal["resume"]["background"] != normal["start over"]["background"]

        move_pointer(".quiz-recovery-start-over")
        browser.wait_for("document.querySelector('.quiz-recovery-start-over').matches(':hover')")
        hovered = _theme_contrast_snapshot(
            browser, {"start over": ".quiz-recovery-start-over"},
        )["start over"]
        assert hovered["contrast"] >= 4.5, (theme, hovered)

        move_pointer(".quiz-recovery-start-over", pressed=True)
        browser.wait_for("document.querySelector('.quiz-recovery-start-over').matches(':active')")
        active = _theme_contrast_snapshot(
            browser, {"start over": ".quiz-recovery-start-over"},
        )["start over"]
        try:
            assert active["contrast"] >= 4.5, (theme, active)
        finally:
            browser.command("input.releaseActions", {"context": browser.context})

        browser.evaluate(
            "document.querySelectorAll('.quiz-recovery-actions button')"
            ".forEach(button=>button.disabled=true);true"
        )
        disabled = _theme_contrast_snapshot(
            browser, {"start over": ".quiz-recovery-start-over"},
        )
        for role, state in disabled.items():
            assert state["contrast"] >= 4.5, (theme, role, state)
            assert state["opacity"] == "1", (theme, role, state)
            assert state["cursor"] == "not-allowed", (theme, role, state)


def test_mixed_quiz_builder_filters_selects_and_publishes_without_changing_sources(
    browser_stack,
):
    """Exercise the DLMS-128 client filtering and normal publication seam."""
    database_path = browser_stack.data_root / "results.db"
    source_rows = (
        ("Browser Mixed Source A", "browser-mixed-a.html", "Browser mixed prompt A?"),
        ("Browser Mixed Source B", "browser-mixed-b.html", "Browser mixed prompt B?"),
    )
    source_ids = []
    with sqlite3.connect(database_path) as connection:
        for title, source_file, prompt in source_rows:
            cursor = connection.execute(
                "INSERT INTO quizzes (title, source_file) VALUES (?, ?)",
                (title, source_file),
            )
            quiz_id = cursor.lastrowid
            source_ids.append(quiz_id)
            cursor = connection.execute(
                """
                INSERT INTO questions (
                    quiz_id, question_number, question_text, question_type,
                    explanation, media_json
                ) VALUES (?, 1, ?, 'choice', ?, '{}')
                """,
                (quiz_id, prompt, f"Explanation for {prompt}"),
            )
            question_id = cursor.lastrowid
            connection.executemany(
                "INSERT INTO choices (question_id, label, text, is_correct) VALUES (?, ?, ?, ?)",
                [
                    (question_id, "A", "Expected", 1),
                    (question_id, "B", "Alternative", 0),
                ],
            )

    registry_path = browser_stack.data_root / "config" / "quizzes.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    for quiz_id, (title, source_file, _prompt) in zip(source_ids, source_rows):
        registry.append({
            "id": quiz_id,
            "title": title,
            "html": source_file,
            "folder": "Browser Mixed Sources",
            "exam_minutes": 90,
        })
    registry_path.write_text(json.dumps(registry, indent=4), encoding="utf-8")

    browser = browser_stack.browser
    browser.navigate(f"{browser_stack.base_url}/quiz-composer")
    browser.wait_for(
        "document.querySelectorAll('.mixed-builder-question').length >= 2 && "
        "document.querySelector('#mixedQuizForm input[name=csrf_token]')"
    )
    for quiz_id in source_ids:
        browser.evaluate(
            "(() => {const select=document.getElementById('sourceFilter');"
            f"select.value='{quiz_id}';"
            "select.dispatchEvent(new Event('input',{bubbles:true}));return true;})()"
        )
        browser.wait_for(
            "document.querySelectorAll('.mixed-builder-question:not([hidden])').length === 1"
        )
        browser.click(
            ".mixed-builder-question:not([hidden]) input[name='question_ids']"
        )
    browser.wait_for("document.getElementById('selectedCount').textContent === '2 selected'")
    browser.evaluate(
        "document.getElementById('mixedQuizTitle').value='Browser Composed Quiz'"
    )
    browser.click("#mixedQuizForm button[type='submit']")
    browser.wait_for("location.pathname.startsWith('/quizzes/mixed_quiz_')")

    with sqlite3.connect(database_path) as connection:
        created = connection.execute(
            "SELECT id, source_file, generation_kind FROM quizzes "
            "WHERE title = 'Browser Composed Quiz'"
        ).fetchone()
        assert created is not None
        assert created[1].startswith("mixed_quiz_")
        assert created[2] == "mixed_quiz"
        assert connection.execute(
            "SELECT COUNT(*) FROM questions WHERE quiz_id = ?", (created[0],)
        ).fetchone()[0] == 2
        copied = connection.execute(
            """
            SELECT question_uid, canonical_question_uid,
                   source_question_uid, is_generated_copy
            FROM questions WHERE quiz_id = ? ORDER BY question_number
            """,
            (created[0],),
        ).fetchall()
        sources = [
            connection.execute(
                """
                SELECT question_uid, canonical_question_uid
                FROM questions WHERE quiz_id = ?
                """,
                (quiz_id,),
            ).fetchone()
            for quiz_id in source_ids
        ]
        assert all(row[3] == 1 for row in copied)
        assert [row[2] for row in copied] == [row[0] for row in sources]
        assert [row[1] for row in copied] == [row[1] for row in sources]
        for quiz_id in source_ids:
            assert connection.execute(
                "SELECT COUNT(*) FROM questions WHERE quiz_id = ?", (quiz_id,)
            ).fetchone()[0] == 1


def _assert_library_tool_metrics_contained(browser, selector):
    geometry = browser.evaluate(
        "(() => {const rect=n=>n.getBoundingClientRect();"
        f"const cards=[...document.querySelectorAll('{selector} .library-stat-card')];"
        "return {count:cards.length,overflow:document.documentElement.scrollWidth>innerWidth+1,"
        "contained:cards.every(card=>{const b=rect(card),c=[...card.children].map(rect);"
        "return c.length===3&&c.every(r=>r.left>=b.left+10&&r.right<=b.right-10&&"
        "r.top>=b.top&&r.bottom<=b.bottom)&&c[0].bottom<=c[1].top&&c[1].bottom<=c[2].top;})};})()"
    )
    assert geometry == {'count': 4, 'overflow': False, 'contained': True}, geometry


def test_duplicate_question_report_is_advisory_and_links_to_source_editors(
    browser_stack,
):
    """Exercise the DLMS-132 Library entry point and read-only report."""
    database_path = browser_stack.data_root / "results.db"
    prompt = "Which neutral protocol provides secure remote access?"
    quiz_ids = []
    with sqlite3.connect(database_path) as connection:
        for index in range(2):
            cursor = connection.execute(
                "INSERT INTO quizzes (title, source_file) VALUES (?, ?)",
                (f"Browser Duplicate Source {index + 1}", f"browser-duplicate-{index + 1}.html"),
            )
            quiz_id = cursor.lastrowid
            quiz_ids.append(quiz_id)
            cursor = connection.execute(
                """
                INSERT INTO questions (
                    quiz_id, question_number, question_text, question_type,
                    explanation, media_json
                ) VALUES (?, 1, ?, 'choice', '', '{}')
                """,
                (quiz_id, prompt),
            )
            question_id = cursor.lastrowid
            connection.executemany(
                "INSERT INTO choices (question_id, label, text, is_correct) VALUES (?, ?, ?, ?)",
                [
                    (question_id, "A", "Secure Shell", 1),
                    (question_id, "B", "File Transfer", 0),
                ],
            )

    registry_path = browser_stack.data_root / "config" / "quizzes.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    for index, quiz_id in enumerate(quiz_ids):
        registry.append({
            "id": quiz_id,
            "title": f"Browser Duplicate Source {index + 1}",
            "html": f"browser-duplicate-{index + 1}.html",
            "folder": "Browser Duplicate Sources",
            "exam_minutes": 90,
        })
    registry_path.write_text(json.dumps(registry, indent=4), encoding="utf-8")

    browser = browser_stack.browser
    browser.navigate(f"{browser_stack.base_url}/library")
    browser.wait_for("document.querySelector(\"a[href='/library/duplicates']\") !== null")
    browser.click("a[href='/library/duplicates']")
    browser.wait_for(
        "location.pathname === '/library/duplicates' && "
        "document.querySelectorAll('.duplicate-question-group').length >= 1"
    )
    state = browser.evaluate(
        "(() => ({"
        "heading:document.querySelector('h1')?.textContent.trim(),"
        "exact:document.getElementById('exactDuplicateHeading')?.textContent.trim(),"
        "sources:[...document.querySelectorAll('.duplicate-question-source strong')]"
        ".map(node=>node.textContent.trim()),"
        "editLinks:[...document.querySelectorAll('.duplicate-question-location a')]"
        ".map(node=>node.getAttribute('href')),"
        "hasMutationForm:[...document.querySelectorAll('form')].some(form=>form.method.toLowerCase() !== 'get')"
        "}))()"
    )
    assert state["heading"] == "Duplicate Question Review"
    assert state["exact"] == "Exact duplicates"
    assert {f"Browser Duplicate Source {index + 1}" for index in range(2)} <= set(state["sources"])
    assert {f"/edit_quiz/{quiz_id}" for quiz_id in quiz_ids} <= set(state["editLinks"])
    assert state["hasMutationForm"] is False

    browser.evaluate("document.querySelector('#duplicateQuizFilter').focus()")
    browser.press_key('\ue004')
    assert browser.evaluate("document.activeElement.id") == 'duplicateFolderFilter'
    browser.press_key('\ue004')
    assert browser.evaluate("document.activeElement.id") == 'duplicateResultTypeFilter'
    browser.press_key('\ue004')
    assert browser.evaluate("document.activeElement.id") == 'duplicateSearch'

    duplicate_url = browser.evaluate("location.href")
    browser.click('#collapseDuplicateGroups')
    browser.wait_for("[...document.querySelectorAll('.duplicate-question-group')].every(g=>!g.open&&g.querySelector('summary').getAttribute('aria-expanded')==='false')")
    # Firefox retains layout rectangles under closed native details; check paint visibility.
    assert browser.evaluate("[...document.querySelectorAll('.duplicate-question-location')].every(n=>!n.checkVisibility())")
    browser.click('#expandDuplicateGroups')
    browser.wait_for("[...document.querySelectorAll('.duplicate-question-group')].every(g=>g.open&&g.querySelector('summary').getAttribute('aria-expanded')==='true')")
    browser.click('details.duplicate-question-group summary')
    browser.wait_for("!document.querySelector('details.duplicate-question-group').open")
    browser.click('details.duplicate-question-group summary')
    for theme in ("light", "dark", "purple-gold", "maroon-gold"):
        _set_theme(browser, theme)
        browser.navigate(duplicate_url)
        browser.wait_for("document.querySelector('.duplicate-question-badge.exact')")
        themed_duplicate = _theme_contrast_snapshot(browser, {
            "exact badge": ".duplicate-question-badge.exact",
            "source metadata": ".duplicate-question-source span",
            "correct badge": ".duplicate-question-correct",
            "edit action": ".duplicate-question-location .library-secondary-action",
            "metric label": ".duplicate-question-summary .library-stat-card span",
            "metric description": ".duplicate-question-summary .library-stat-card small",
            "filter label": ".duplicate-question-filters .build-field span",
            "quiz selector": "#duplicateQuizFilter",
            "result type selector": "#duplicateResultTypeFilter",
            "search text": "#duplicateSearch",
            "collapse action": "#collapseDuplicateGroups",
        })
        for role, themed_state in themed_duplicate.items():
            assert themed_state["contrast"] >= 4.5, (theme, role, themed_state)
        for width in (1440, 1024, 760, 420):
            browser.set_viewport(width, 1000)
            _assert_library_tool_metrics_contained(browser, '.duplicate-question-summary')
            assert browser.evaluate("(() => {const p=document.querySelector('.duplicate-question-tools').getBoundingClientRect();return [...document.querySelectorAll('.duplicate-question-filters input,.duplicate-question-filters select,.duplicate-question-filters button')].every(n=>{const r=n.getBoundingClientRect();return r.left>=p.left&&r.right<=p.right;});})()")
            browser.evaluate("document.querySelector('.duplicate-question-summary .library-stat-card span').textContent='Source questions scanned across your entire library'")
            _assert_library_tool_metrics_contained(browser, '.duplicate-question-summary')

    with sqlite3.connect(database_path) as connection:
        for quiz_id in quiz_ids:
            assert connection.execute(
                "SELECT COUNT(*) FROM questions WHERE quiz_id = ?", (quiz_id,)
            ).fetchone()[0] == 1


def test_duplicate_question_large_results_filters_and_pagination(browser_stack):
    """Exercise a real large scan, bounded DOM, and presentation-only filters."""
    database = browser_stack.data_root / 'results.db'
    ids = []
    with sqlite3.connect(database) as connection:
        for index in range(2):
            cursor = connection.execute('INSERT INTO quizzes(title,source_file,generation_kind) VALUES(?,?,?)',
                                        (f'Large Source {index + 1}', f'large-{index}.html', 'source'))
            ids.append(cursor.lastrowid)
            for number in range(1, 45):
                cursor = connection.execute("INSERT INTO questions(quiz_id,question_number,question_text,question_type) VALUES(?,?,?,'choice')",
                                            (ids[-1], number, f'Compare synthetic item {number}: which option applies?'))
                connection.executemany('INSERT INTO choices(question_id,label,text,is_correct) VALUES(?,?,?,?)',
                                       [(cursor.lastrowid, 'A', 'Expected', 1), (cursor.lastrowid, 'B', 'Alternative', 0)])
            prompt = ('Which command displays the active network configuration?' if index == 0
                      else 'Which command displays active network configuration?')
            cursor = connection.execute("INSERT INTO questions(quiz_id,question_number,question_text,question_type) VALUES(?,45,?,'choice')", (ids[-1], prompt))
            connection.executemany('INSERT INTO choices(question_id,label,text,is_correct) VALUES(?,?,?,?)',
                                   [(cursor.lastrowid, 'A', 'Expected', 1), (cursor.lastrowid, 'B', 'Alternative', 0)])
        connection.commit()
        before = list(connection.iterdump())
    registry_path = browser_stack.data_root / 'config' / 'quizzes.json'
    registry = json.loads(registry_path.read_text())
    registry.extend(dict(id=quiz, title=f'Large Source {i + 1}', html=f'large-{i}.html',
                         folder='Uncategorized' if i == 0 else 'Hidden folder', hidden=i == 1)
                    for i, quiz in enumerate(ids))
    # Mechanical fixture serialization, isolated from the user's data.
    registry_path.write_text(json.dumps(registry))
    browser = browser_stack.browser
    url = f'{browser_stack.base_url}/library/duplicates'
    browser.navigate(url)
    browser.wait_for("document.querySelector('details.duplicate-question-group')")
    full_totals = browser.evaluate("[...document.querySelectorAll('.duplicate-question-summary strong')].map(n=>n.textContent)")
    assert browser.evaluate("document.querySelectorAll('details.duplicate-question-group').length") == 20
    assert browser.evaluate("[...document.querySelectorAll('details.duplicate-question-group')].every(g=>!g.open)")
    browser.click('a[rel=next]')
    browser.wait_for("new URLSearchParams(location.search).get('page')==='2'")
    assert browser.evaluate("document.querySelectorAll('details.duplicate-question-group').length") <= 20
    browser.evaluate(f"document.querySelector('#duplicateQuizFilter').value='{ids[1]}';document.querySelector('#duplicateFolderFilter').value='Uncategorized';document.querySelector('#duplicateSearch').value='network configuration';document.querySelector('#duplicateResultTypeFilter').value='possible'")
    browser.click('.duplicate-question-filters button[type=submit]')
    browser.wait_for("new URLSearchParams(location.search).get('result_type')==='possible'&&document.querySelector('#nearDuplicateHeading')")
    assert browser.evaluate("!new URLSearchParams(location.search).has('page')&&document.querySelector('#duplicateResultTypeFilter').value==='possible'")
    assert browser.evaluate("document.querySelector('#exactDuplicateHeading')===null&&document.querySelectorAll('details.duplicate-question-group').length===1")
    assert browser.evaluate("document.querySelector('.duplicate-question-navigation [role=status]').textContent.includes('of 1 possible match')")
    assert browser.evaluate("[...document.querySelectorAll('.duplicate-question-summary strong')].map(n=>n.textContent)") == full_totals
    browser.click('#expandDuplicateGroups')
    browser.wait_for("document.querySelector('details.duplicate-question-group').open")
    browser.click('#collapseDuplicateGroups')
    browser.wait_for("!document.querySelector('details.duplicate-question-group').open")
    browser.evaluate("document.querySelector('#duplicateResultTypeFilter').value='exact';document.querySelector('#duplicateSearch').value=''")
    browser.click('.duplicate-question-filters button[type=submit]')
    browser.wait_for("new URLSearchParams(location.search).get('result_type')==='exact'&&document.querySelector('#exactDuplicateHeading')")
    assert browser.evaluate("document.querySelector('#nearDuplicateHeading')===null&&document.querySelector('a[rel=next]').href.includes('result_type=exact')")
    browser.click('a[rel=next]')
    browser.wait_for("new URLSearchParams(location.search).get('page')==='2'")
    assert browser.evaluate(f"document.querySelector('#duplicateQuizFilter').value==='{ids[1]}'&&document.querySelector('#duplicateFolderFilter').value==='Uncategorized'&&document.querySelector('#duplicateResultTypeFilter').value==='exact'")
    browser.evaluate(f"document.querySelector('#duplicateQuizFilter').value='{ids[1]}';document.querySelector('#duplicateFolderFilter').value='Uncategorized';document.querySelector('#duplicateSearch').value='item 44:'")
    browser.click('.duplicate-question-filters button[type=submit]')
    browser.wait_for("new URLSearchParams(location.search).get('search')==='item 44:'")
    assert browser.evaluate("document.querySelectorAll('details.duplicate-question-group').length") == 1
    assert browser.evaluate(f"document.querySelector('#duplicateQuizFilter').value==='{ids[1]}'")
    browser.evaluate("document.querySelector('#duplicateSearch').value='no such source question'")
    browser.click('.duplicate-question-filters button[type=submit]')
    browser.wait_for("document.querySelector('.duplicate-question-empty h2')?.textContent==='No matching groups'")
    browser.click('.duplicate-question-filters a')
    browser.wait_for("!location.search&&document.querySelectorAll('details.duplicate-question-group').length===20")
    assert browser.evaluate("document.querySelector('#duplicateResultTypeFilter').value") == 'all'
    with sqlite3.connect(database) as connection:
        assert before == list(connection.iterdump())


def test_portable_quiz_bundle_library_preview_and_import(browser_stack):
    """Exercise the DLMS-133 Library entry point and confirmed publication."""
    database_path = browser_stack.data_root / "results.db"
    source_title = "Browser Portable Source"
    with sqlite3.connect(database_path) as connection:
        cursor = connection.execute(
            "INSERT INTO quizzes (title, source_file) VALUES (?, ?)",
            (source_title, "browser-portable-source.html"),
        )
        source_id = cursor.lastrowid
        cursor = connection.execute(
            """
            INSERT INTO questions (
                quiz_id, question_number, question_text, question_type,
                explanation, media_json
            ) VALUES (?, 1, ?, 'choice', '', '{}')
            """,
            (source_id, "Which browser source option is expected?"),
        )
        question_id = cursor.lastrowid
        connection.executemany(
            "INSERT INTO choices (question_id, label, text, is_correct) VALUES (?, ?, ?, ?)",
            [
                (question_id, "A", "Expected", 1),
                (question_id, "B", "Alternative", 0),
            ],
        )

    registry_path = browser_stack.data_root / "config" / "quizzes.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    registry.append({
        "id": source_id,
        "title": source_title,
        "html": "browser-portable-source.html",
        "folder": "Browser Portable Sources",
        "exam_minutes": 90,
    })
    registry_path.write_text(json.dumps(registry, indent=4), encoding="utf-8")

    import_title = "Browser Portable Import"
    manifest = {
        "format": "dlms-portable-quiz-bundle",
        "schema_version": 1,
        "created_at": "2026-09-13T10:00:00-05:00",
        # A prior producer version exercises the portable compatibility contract.
        "created_by": {"application": "DLMS", "version": "3.1.0"},
        "quizzes": [{
            "bundle_id": "quiz-001",
            "title": import_title,
            "folder": "Browser Imported Folder",
            "exam_minutes": 30,
            "logo": None,
            "assets": [],
            "questions": [{
                "number": 1,
                "type": "choice",
                "question": "Which imported browser option is expected?",
                "explanation": "A browser workflow fixture.",
                "concepts": ["Portable browser concept"],
                "source": {},
                "media": {},
                "choices": [
                    {"label": "A", "text": "Expected", "is_correct": True},
                    {"label": "B", "text": "Alternative", "is_correct": False},
                ],
            }],
        }],
    }
    bundle_path = browser_stack.data_root.parent / "browser-portable-bundle.zip"
    with zipfile.ZipFile(bundle_path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("dlms-quiz-bundle.json", json.dumps(manifest))

    browser = browser_stack.browser
    browser.navigate(f"{browser_stack.base_url}/library")
    browser.wait_for("document.querySelector(\"a[href='/quiz-bundles']\") !== null")
    browser.click("a[href='/quiz-bundles']")
    browser.wait_for(
        "location.pathname === '/quiz-bundles' && "
        "document.querySelectorAll(\"input[name='quiz_ids']\").length >= 1"
    )
    state = browser.evaluate(
        "(() => ({"
        "heading:document.querySelector('h1')?.textContent.trim(),"
        "sources:[...document.querySelectorAll('.portable-bundle-quiz strong')]"
        ".map(node=>node.textContent.trim()),"
        "studyPackBoundary:document.querySelector('.portable-bundle-boundary')?.textContent"
        "}))()"
    )
    assert state["heading"] == "Portable Quiz Bundles"
    assert source_title in state["sources"]
    assert "Content Packs" in state["studyPackBoundary"]

    browser.wait_for("window.dlmsCsrfToken && typeof window.fetch === 'function'")
    for theme in ("light", "dark", "purple-gold", "maroon-gold"):
        status = browser.evaluate(
            f"fetch('/api/theme',{{method:'POST',headers:{{'Content-Type':'application/json'}},"
            f"body:JSON.stringify({{theme:{json.dumps(theme)}}})}}).then(response=>response.status)"
        )
        assert status == 200
        for width in (1280, 1024, 840, 420):
            browser.set_viewport(width, 900 if width >= 840 else 820)
            browser.navigate(f"{browser_stack.base_url}/quiz-bundles")
            browser.wait_for("document.querySelectorAll('.portable-bundle-panel').length === 2")
            layout = browser.evaluate(
                "(() => {const panels=[...document.querySelectorAll('.portable-bundle-panel')];"
                "const intro=document.querySelector('.portable-bundle-intro');"
                "const back=intro.querySelector('.build-secondary-link');"
                "const file=document.querySelector('.portable-bundle-upload-form input[type=file]');"
                "const rect=node=>node.getBoundingClientRect();"
                "const headings=panels.map(panel=>panel.querySelector('h2'));"
                "return {sideBySide:Math.abs(rect(panels[0]).top-rect(panels[1]).top)<=1,"
                "panelWidths:panels.map(panel=>Math.round(rect(panel).width)),"
                "panelInsets:panels.map(panel=>Math.round(rect(panel.firstElementChild).left-rect(panel).left)),"
                "headingHeights:headings.map(heading=>Math.round(rect(heading).height)),"
                "backWidth:Math.round(rect(back).width),"
                "backContained:rect(back).left>=rect(intro).left+20&&rect(back).right<=rect(intro).right-20,"
                "fileContained:rect(file).left>=rect(panels[1]).left+20&&rect(file).right<=rect(panels[1]).right-20,"
                "cardsContained:[intro,...panels].every(card=>card.scrollWidth<=card.clientWidth+1),"
                "overflow:document.documentElement.scrollWidth<=window.innerWidth+1};})()"
            )
            assert layout["sideBySide"] == (width == 1280), (theme, width, layout)
            assert min(layout["panelWidths"]) >= min(388, width - 32), (
                theme, width, layout,
            )
            assert min(layout["panelInsets"]) >= 20, (theme, width, layout)
            assert max(layout["headingHeights"]) <= 32, (theme, width, layout)
            assert layout["backWidth"] >= 120, (theme, width, layout)
            assert layout["backContained"] is True, (theme, width, layout)
            assert layout["fileContained"] is True, (theme, width, layout)
            assert layout["cardsContained"] is True, (theme, width, layout)
            assert layout["overflow"] is True, (theme, width, layout)

    browser.set_viewport(1280, 1000)
    browser.navigate(f"{browser_stack.base_url}/quiz-bundles")
    browser.wait_for("document.querySelector('form[action=\"/quiz-bundles/import\"]')")

    browser.set_files("input[name='bundle_zip']", [str(bundle_path)])
    browser.click("form[action='/quiz-bundles/import'] button[type='submit']")
    browser.wait_for(
        "location.pathname.startsWith('/quiz-bundles/import/') && "
        "document.querySelector(\"input[name='confirm_import']\") !== null"
    )
    review = browser.evaluate(
        "(() => ({"
        "heading:document.querySelector('h1')?.textContent.trim(),"
        "quiz:document.querySelector('.portable-bundle-review-quiz h2')?.textContent.trim(),"
        "folder:document.querySelector('.portable-bundle-review-meta')?.textContent"
        "}))()"
    )
    assert review["heading"] == "Review Portable Bundle"
    assert review["quiz"] == import_title
    assert "Browser Imported Folder" in review["folder"]
    review_url = browser.evaluate("location.href")
    review_selectors = {
        "bundle review back link": ".portable-bundle-intro .build-secondary-link",
        "bundle review summary helper": ".portable-bundle-summary .library-stat-card small",
        "bundle review metadata": ".portable-bundle-review-meta span",
        "bundle review preview": ".portable-bundle-review-quiz details summary",
        "bundle review explanation": ".portable-bundle-confirm-panel p",
        "bundle review confirmation": ".portable-bundle-confirm-actions label",
        "bundle review cancel": ".portable-bundle-confirm-actions .library-secondary-action",
        "bundle review submit": ".portable-bundle-confirm-actions .library-primary-action",
    }
    for theme in ("light", "dark", "purple-gold", "maroon-gold"):
        _set_theme(browser, theme)
        browser.navigate(review_url)
        browser.wait_for("document.querySelector('.portable-bundle-confirm-panel')")
        themed_review = _theme_contrast_snapshot(browser, review_selectors)
        for role, state in themed_review.items():
            assert state["contrast"] >= 4.5, (theme, role, state)
        for width in (1440, 1024, 760, 420):
            browser.set_viewport(width, 1000)
            _assert_library_tool_metrics_contained(browser, '.portable-bundle-summary')
    for width in (1024, 420):
        browser.set_viewport(width, 900 if width == 1024 else 820)
        browser.navigate(review_url)
        browser.wait_for("document.querySelector('.portable-bundle-confirm-panel')")
        review_layout = browser.evaluate(
            "(() => {const panel=document.querySelector('.portable-bundle-confirm-panel');"
            "const bounds=panel.getBoundingClientRect();"
            "const controls=[...panel.querySelectorAll('button,input')].filter(item=>"
            "item.getClientRects().length);return {"
            "direction:getComputedStyle(panel).flexDirection,"
            "contained:controls.every(item=>{const rect=item.getBoundingClientRect();"
            "return rect.left>=bounds.left+20&&rect.right<=bounds.right-20;}),"
            "overflow:document.documentElement.scrollWidth<=window.innerWidth+1};})()"
        )
        assert review_layout == {
            "direction": "column", "contained": True, "overflow": True,
        }, (width, review_layout)
    browser.set_viewport(1280, 1000)
    browser.navigate(review_url)
    browser.wait_for("document.querySelector(\"input[name='confirm_import']\")")
    browser.click("input[name='confirm_import']")
    browser.click("form[action$='/confirm'] button[type='submit']")
    browser.wait_for(
        "location.pathname === '/quiz-bundles' && "
        "document.body.textContent.includes('Imported 1 quiz.')"
    )

    with sqlite3.connect(database_path) as connection:
        imported = connection.execute(
            "SELECT id, source_file FROM quizzes WHERE title = ?", (import_title,)
        ).fetchone()
        assert imported is not None
        assert imported[1].startswith("portable_quiz_")
        assert connection.execute(
            "SELECT COUNT(*) FROM questions WHERE quiz_id = ?", (imported[0],)
        ).fetchone()[0] == 1


def test_native_spaced_review_displays_due_reason_and_creates_session(browser_stack):
    """Exercise the DLMS-129 schedule UI and normal quiz-publication seam."""
    database_path = browser_stack.data_root / "results.db"
    prompt = "Browser native spaced-review prompt?"
    with sqlite3.connect(database_path) as connection:
        cursor = connection.execute(
            "INSERT INTO quizzes (title, source_file) VALUES (?, ?)",
            ("Browser Native Schedule Source", "browser-native-schedule.html"),
        )
        quiz_id = cursor.lastrowid
        cursor = connection.execute(
            """
            INSERT INTO questions (
                quiz_id, question_number, question_text, question_type,
                explanation, media_json
            ) VALUES (?, 1, ?, 'choice', 'Browser schedule explanation', '{}')
            """,
            (quiz_id, prompt),
        )
        question_id = cursor.lastrowid
        connection.executemany(
            "INSERT INTO choices (question_id, label, text, is_correct) VALUES (?, ?, ?, ?)",
            [
                (question_id, "A", "Expected", 1),
                (question_id, "B", "Alternative", 0),
            ],
        )
        connection.execute(
            """
            INSERT INTO learning_events (
                event_type, quiz_id, question_id, attempt_id, mode,
                was_correct, response_json, occurred_at
            ) VALUES ('exam_answer', ?, ?, ?, 'Exam', 0, '{}', ?)
            """,
            (quiz_id, question_id, "browser-native-attempt", "2020-01-01T00:00:00+00:00"),
        )
        for ordinal in range(2, 12):
            cursor = connection.execute(
                """
                INSERT INTO questions (
                    quiz_id, question_number, question_text, question_type,
                    explanation, media_json
                ) VALUES (?, ?, ?, 'choice', 'Browser schedule explanation', '{}')
                """,
                (quiz_id, ordinal, f"Browser batch question {ordinal}?"),
            )
            batch_question_id = cursor.lastrowid
            connection.executemany(
                "INSERT INTO choices (question_id, label, text, is_correct) VALUES (?, ?, ?, ?)",
                [
                    (batch_question_id, "A", "Expected", 1),
                    (batch_question_id, "B", "Alternative", 0),
                ],
            )
            connection.execute(
                """
                INSERT INTO learning_events (
                    event_type, quiz_id, question_id, attempt_id, mode,
                    was_correct, response_json, occurred_at
                ) VALUES ('exam_answer', ?, ?, ?, 'Exam', 0, '{}', ?)
                """,
                (
                    quiz_id,
                    batch_question_id,
                    f"browser-native-attempt-{ordinal}",
                    "2020-01-01T00:00:00+00:00",
                ),
            )
        for ordinal, question_text in (
            (12, "Browser not-yet-scheduled filter question?"),
            (13, "Browser upcoming filter question?"),
        ):
            cursor = connection.execute(
                """
                INSERT INTO questions (
                    quiz_id, question_number, question_text, question_type,
                    explanation, media_json
                ) VALUES (?, ?, ?, 'choice', 'Browser schedule explanation', '{}')
                """,
                (quiz_id, ordinal, question_text),
            )
            filtered_question_id = cursor.lastrowid
            connection.executemany(
                "INSERT INTO choices (question_id, label, text, is_correct) VALUES (?, ?, ?, ?)",
                [
                    (filtered_question_id, "A", "Expected", 1),
                    (filtered_question_id, "B", "Alternative", 0),
                ],
            )
            if ordinal == 13:
                connection.execute(
                    """
                    INSERT INTO learning_events (
                        event_type, quiz_id, question_id, attempt_id, mode,
                        was_correct, response_json, occurred_at
                    ) VALUES ('exam_answer', ?, ?, ?, 'Exam', 1, '{}', ?)
                    """,
                    (
                        quiz_id,
                        filtered_question_id,
                        "browser-native-attempt-upcoming",
                        datetime.now(timezone.utc).isoformat(),
                    ),
                )

        schedule_db_snapshot = (
            connection.execute("SELECT COUNT(*) FROM questions").fetchone()[0],
            connection.execute("SELECT COUNT(*) FROM learning_events").fetchone()[0],
        )

    browser = browser_stack.browser
    browser.navigate(f"{browser_stack.base_url}/review-schedule")
    browser.wait_for(
        "document.querySelector('#nrsRows')?.textContent.includes(" + json.dumps(prompt) + ") && "
        "document.querySelector('form[action=\"/native-spaced-review/generate\"] "
        "input[name=csrf_token]')"
    )
    schedule_state = browser.evaluate(
        "(() => {const row=[...document.querySelectorAll('#nrsRows tr')].find(item=>"
        "item.textContent.includes(" + json.dumps(prompt) + "));"
        "return {due:Number(document.getElementById('nrsDue').textContent),"
        "batch:document.getElementById('nrsBatchSummary').textContent,"
        "row:row?.textContent||'',status:row?.querySelector('.review-state')?.textContent||''};})()"
    )
    assert schedule_state["due"] >= 11
    assert schedule_state["batch"] == (
        f"{schedule_state['due']} questions are due · "
        f"This review includes all {schedule_state['due']}."
    )
    assert "latest response was incorrect" in schedule_state["row"]
    assert schedule_state["status"] == "Overdue"

    search_state = browser.evaluate(
        "(() => {const input=document.getElementById('nrsSearch');"
        "const count=()=>document.querySelectorAll('#nrsRows tr').length;"
        "const original=count();input.value='Browser native spaced-review prompt';"
        "input.dispatchEvent(new Event('input',{bubbles:true}));"
        "const filtered=count(),text=document.getElementById('nrsRows').textContent;"
        "input.value='';input.dispatchEvent(new Event('input',{bubbles:true}));"
        "return {original,filtered,matches:text.includes("
        + json.dumps(prompt)
        + "),restored:count()};})()"
    )
    assert search_state["original"] >= 11
    assert search_state["filtered"] == 1
    assert search_state["matches"] is True
    assert search_state["restored"] == search_state["original"]

    default_queue = browser.evaluate(
        "(() => {const toggle=document.getElementById('nrsQueueToggle');"
        "return {expanded:toggle.getAttribute('aria-expanded'),"
        "bodyHidden:document.getElementById('nrsQueueBody').hidden,"
        "pressed:[...document.querySelectorAll('[data-question-status]')]"
        ".filter(button=>button.getAttribute('aria-pressed')==='true')"
        ".map(button=>button.dataset.questionStatus),"
        "count:document.getElementById('nrsQueueCount').textContent};})()"
    )
    assert default_queue == {
        "expanded": "true",
        "bodyHidden": False,
        "pressed": ["all"],
        "count": f"{search_state['original']} questions",
    }

    browser.activate()
    assert browser.evaluate(
        "(() => {const toggle=document.getElementById('nrsQueueToggle');toggle.focus();"
        "return document.activeElement===toggle&&toggle.tagName==='BUTTON'&&"
        "toggle.type==='button'&&toggle.tabIndex===0;})()"
    ) is True
    browser.click("#nrsQueueToggle")
    browser.wait_for(
        "document.getElementById('nrsQueueToggle').getAttribute('aria-expanded')==='false' && "
        "document.getElementById('nrsQueueBody').hidden"
    )
    assert browser.evaluate(
        "localStorage.getItem('dlms.reviewSchedule.questionQueueCollapsed')"
    ) == "1"
    browser.navigate(f"{browser_stack.base_url}/review-schedule")
    browser.wait_for("document.getElementById('nrsQueueCount').textContent.includes('questions')")
    assert browser.evaluate(
        "document.getElementById('nrsQueueToggle').getAttribute('aria-expanded')==='false' && "
        "document.getElementById('nrsQueueBody').hidden"
    ) is True
    assert browser.evaluate(
        "(() => {const toggle=document.getElementById('nrsQueueToggle');toggle.focus();"
        "return document.activeElement===toggle&&toggle.tagName==='BUTTON'&&"
        "toggle.type==='button'&&toggle.tabIndex===0;})()"
    ) is True
    browser.click("#nrsQueueToggle")
    browser.wait_for(
        "document.getElementById('nrsQueueToggle').getAttribute('aria-expanded')==='true' && "
        "!document.getElementById('nrsQueueBody').hidden"
    )

    def question_filter_state():
        return browser.evaluate(
            "(() => {const rows=[...document.querySelectorAll('#nrsRows tr')];"
            "return {count:rows.length,statuses:[...new Set(rows.map(row=>"
            "row.querySelector('.review-state')?.textContent.trim()))],"
            "text:document.getElementById('nrsRows').textContent,"
            "emptyHidden:document.getElementById('nrsEmpty').hidden,"
            "empty:document.getElementById('nrsEmpty').textContent,"
            "summary:document.getElementById('nrsQueueCount').textContent,"
            "pressed:[...document.querySelectorAll('[data-question-status]')]"
            ".filter(button=>button.getAttribute('aria-pressed')==='true')"
            ".map(button=>button.dataset.questionStatus)};})()"
        )

    browser.click("[data-question-status='overdue']")
    overdue_filter = question_filter_state()
    assert overdue_filter["count"] >= 11
    assert overdue_filter["statuses"] == ["Overdue"]
    assert overdue_filter["pressed"] == ["overdue"]

    browser.click("[data-question-status='upcoming']")
    upcoming_filter = question_filter_state()
    assert upcoming_filter["count"] == 1
    assert upcoming_filter["statuses"] == ["Upcoming"]
    assert "Browser upcoming filter question?" in upcoming_filter["text"]

    browser.click("[data-question-status='unscheduled']")
    unscheduled_filter = question_filter_state()
    assert unscheduled_filter["count"] >= 1
    assert unscheduled_filter["statuses"] == ["Not yet scheduled"]
    assert "Browser not-yet-scheduled filter question?" in unscheduled_filter["text"]

    browser.click("[data-question-status='due']")
    due_filter = question_filter_state()
    assert due_filter["statuses"] in ([], ["Due now"])
    assert due_filter["emptyHidden"] is bool(due_filter["count"])
    if not due_filter["count"]:
        assert due_filter["empty"] == "No questions match the current search and status filter."
    assert due_filter["pressed"] == ["due"]

    browser.click("[data-question-status='overdue']")
    combined_filter = browser.evaluate(
        "(() => {const input=document.getElementById('nrsSearch');"
        "input.value='Browser native spaced-review prompt';"
        "input.dispatchEvent(new Event('input',{bubbles:true}));"
        "return document.querySelectorAll('#nrsRows tr').length;})()"
    )
    assert combined_filter == 1
    browser.click("#nrsQueueToggle")
    browser.click("#nrsQueueToggle")
    assert question_filter_state()["count"] == 1

    browser.evaluate(
        "document.getElementById('nrsSearch').value='';"
        "document.getElementById('nrsSearch').dispatchEvent(new Event('input',{bubbles:true}));true"
    )
    browser.click("[data-question-status='all']")
    restored_filter = question_filter_state()
    assert restored_filter["count"] == search_state["original"]
    assert restored_filter["pressed"] == ["all"]
    assert restored_filter["summary"] == f"{search_state['original']} questions"

    with sqlite3.connect(database_path) as connection:
        assert (
            connection.execute("SELECT COUNT(*) FROM questions").fetchone()[0],
            connection.execute("SELECT COUNT(*) FROM learning_events").fetchone()[0],
        ) == schedule_db_snapshot

    selected_batch = browser.evaluate(
        "(() => {const select=document.getElementById('nrsBatchSize');"
        "select.value='10';select.dispatchEvent(new Event('change',{bubbles:true}));"
        "return document.getElementById('nrsBatchSummary').textContent;})()"
    )
    assert selected_batch == (
        f"{schedule_state['due']} questions are due · "
        "This review includes up to 10 questions."
    )
    browser.evaluate(
        "document.getElementById('nrsBatchSize').value='20';"
        "document.getElementById('nrsBatchSize').dispatchEvent("
        "new Event('change',{bubbles:true}));true"
    )

    browser.click(
        "form[action='/native-spaced-review/generate'] button[type='submit']"
    )
    browser.wait_for("location.pathname.startsWith('/quizzes/spaced_review_native_')")

    with sqlite3.connect(database_path) as connection:
        created = connection.execute(
            """
            SELECT id, source_file, generation_kind FROM quizzes
            WHERE title = 'Spaced Review — Due Questions'
            ORDER BY id DESC LIMIT 1
            """
        ).fetchone()
        assert created is not None
        assert created[1].startswith("spaced_review_native_")
        assert created[2] == "native_spaced_review"
        assert connection.execute(
            "SELECT COUNT(*) FROM questions WHERE quiz_id = ? AND question_text = ?",
            (created[0], prompt),
        ).fetchone()[0] == 1
        source_lineage = connection.execute(
            """
            SELECT question_uid, canonical_question_uid
            FROM questions WHERE id = ?
            """,
            (question_id,),
        ).fetchone()
        copy_lineage = connection.execute(
            """
            SELECT canonical_question_uid, source_question_uid,
                   is_generated_copy
            FROM questions WHERE quiz_id = ?
            """,
            (created[0],),
        ).fetchone()
        assert source_lineage[0] is not None
        assert copy_lineage == (source_lineage[1], source_lineage[0], 1)
        assert connection.execute(
            "SELECT COUNT(*) FROM questions WHERE quiz_id = ?", (quiz_id,)
        ).fetchone()[0] == 13


def test_core_filter_state_and_repeated_builder_fields_are_accessible(browser_stack):
    browser = browser_stack.browser
    base_url = browser_stack.base_url

    browser.set_viewport(640, 900)  # 1280px desktop content at a 200% zoom equivalent.
    browser.navigate(f"{base_url}/create_short_quiz?count=2")
    browser.wait_for("document.getElementById('create-short-quiz-form')")
    choice_names = browser.evaluate(
        "[...document.querySelectorAll('.choice-text')].map(input=>input.getAttribute('aria-label'))"
    )
    assert choice_names == [
        "Question 1 answer A text", "Question 1 answer B text",
        "Question 1 answer C text", "Question 1 answer D text",
        "Question 2 answer A text", "Question 2 answer B text",
        "Question 2 answer C text", "Question 2 answer D text",
    ]
    dynamic_names = browser.evaluate(
        "(() => {const first=document.querySelector('.question-block');"
        "const type=first.querySelector('.question-type');type.value='matching';"
        "type.dispatchEvent(new Event('change',{bubbles:true}));"
        "first.querySelector('.choice-editor .build-add-choice').click();first.querySelector('.matching-editor .build-add-choice').click();"
        "const pairs=[...first.querySelectorAll('.build-match-pair')];"
        "return {choice:[...first.querySelectorAll('.choice-text')].at(-1).getAttribute('aria-label'),"
        "left:pairs.at(-1).querySelector('.match-left').getAttribute('aria-label'),"
        "right:pairs.at(-1).querySelector('.match-right').getAttribute('aria-label'),"
        "deletePair:pairs.at(-1).querySelector('.btn-delete').getAttribute('aria-label'),"
        "overflow:document.documentElement.scrollWidth<=window.innerWidth+1};})()"
    )
    assert dynamic_names == {
        "choice": "Question 1 answer E text",
        "left": "Question 1 matching term 5",
        "right": "Question 1 matching definition 5",
        "deletePair": "Delete question 1 matching pair 5",
        "overflow": True,
    }

    for theme in ("light", "dark", "purple-gold", "maroon-gold"):
        _set_theme(browser, theme)
        browser.navigate(f"{base_url}/learning-intelligence")
        browser.wait_for("document.getElementById('liLoading').hidden")
        browser.click('[data-li-filter="weak"]')
        learning_state = browser.evaluate(
            "(() => {const buttons=[...document.querySelectorAll('[data-li-filter]')];"
            "return {pressed:buttons.filter(button=>button.getAttribute('aria-pressed')==='true').map(button=>button.dataset.liFilter),"
            "active:buttons.filter(button=>button.classList.contains('active')).map(button=>button.dataset.liFilter),"
            "overflow:document.documentElement.scrollWidth<=window.innerWidth+1};})()"
        )
        assert learning_state == {"pressed": ["weak"], "active": ["weak"], "overflow": True}

    browser.navigate(f"{base_url}/history")
    browser.wait_for("document.getElementById('historyAttemptCount').textContent !== 'Loading…'")
    browser.click('[data-origin-filter="quiz"]')
    browser.wait_for(
        "document.querySelector('[data-origin-filter=quiz]').getAttribute('aria-pressed')==='true'"
    )
    assert browser.evaluate(
        "[...document.querySelectorAll('[data-origin-filter]')].filter(button=>button.getAttribute('aria-pressed')==='true').map(button=>button.dataset.originFilter)"
    ) == ["quiz"]


def test_dashboard_today_review_unifies_due_and_unfinished_actions(browser_stack):
    """The daily plan orders canonical due work before browser-local progress."""
    database_path = browser_stack.data_root / "results.db"
    prompt = "Browser daily-review due prompt?"
    with sqlite3.connect(database_path) as connection:
        cursor = connection.execute(
            "INSERT INTO quizzes (title, source_file) VALUES (?, ?)",
            ("Browser Daily Review Source", "browser-daily-review-source.html"),
        )
        source_quiz_id = cursor.lastrowid
        cursor = connection.execute(
            """
            INSERT INTO questions (
                quiz_id, question_number, question_text, question_type,
                explanation, media_json
            ) VALUES (?, 1, ?, 'choice', 'Daily review explanation', '{}')
            """,
            (source_quiz_id, prompt),
        )
        source_question_id = cursor.lastrowid
        connection.executemany(
            "INSERT INTO choices (question_id, label, text, is_correct) VALUES (?, ?, ?, ?)",
            [
                (source_question_id, "A", "Expected", 1),
                (source_question_id, "B", "Alternative", 0),
            ],
        )
        connection.execute(
            """
            INSERT INTO learning_events (
                event_type, quiz_id, question_id, attempt_id, mode,
                was_correct, response_json, occurred_at
            ) VALUES ('exam_answer', ?, ?, ?, 'Exam', 0, '{}', ?)
            """,
            (
                source_quiz_id,
                source_question_id,
                "browser-daily-review-attempt",
                "2020-01-01T00:00:00+00:00",
            ),
        )

    browser = browser_stack.browser
    critical_url = (
        f"{browser_stack.base_url}/quizzes/"
        f"{browser_stack.metadata['critical_html']}"
    )
    browser.navigate(critical_url)
    browser.wait_for("quizRecoveryReady === true")
    browser.click(".study-mode-btn")
    browser.click("#choices .choice[data-index='0']")
    browser.wait_for(
        "window.DLMSQuizRecovery.listStoredRecords({activeQuizIds:["
        + json.dumps(str(browser_stack.metadata["critical_id"]))
        + "]}).records.length === 1"
    )

    browser.navigate(f"{browser_stack.base_url}/")
    browser.wait_for(
        "document.querySelector('.daily-review-native_due') && "
        "document.querySelector('.daily-review-unfinished a')"
    )
    plan = browser.evaluate(
        "(() => ({"
        "kinds:[...document.querySelectorAll('.daily-review-item')].map(item => "
        "[...item.classList].find(name => name.startsWith('daily-review-') && "
        "name !== 'daily-review-item').replace('daily-review-', '')) ,"
        "dueText:document.querySelector('.daily-review-native_due').textContent,"
        "resumeText:document.querySelector('.daily-review-unfinished').textContent,"
        "csrf:Boolean(document.querySelector("
        "'.daily-review-native_due form input[name=csrf_token]'))"
        "}))()"
    )
    assert plan["kinds"][:2] == ["native_due", "unfinished"]
    assert "due" in plan["dueText"].lower()
    assert "Browser Critical Workflow" in plan["resumeText"]
    assert plan["csrf"] is True

    browser.click(".daily-review-unfinished a")
    browser.wait_for("document.querySelector('.quiz-recovery-resume') !== null")
    assert browser.evaluate("location.pathname") == (
        f"/quizzes/{browser_stack.metadata['critical_html']}"
    )

    browser.navigate(f"{browser_stack.base_url}/")
    browser.wait_for("document.querySelector('.daily-review-native_due button')")
    browser.click(".daily-review-native_due button")
    browser.wait_for("location.pathname.startsWith('/quizzes/spaced_review_native_')")
    with sqlite3.connect(database_path) as connection:
        generated = connection.execute(
            """
            SELECT q.id, q.quiz_id, z.generation_kind
            FROM questions q
            JOIN quizzes z ON z.id = q.quiz_id
            WHERE z.source_file LIKE 'spaced_review_native_%'
              AND q.question_text = ?
            ORDER BY q.id DESC LIMIT 1
            """,
            (prompt,),
        ).fetchone()
        assert generated is not None
        assert generated[2] == "native_spaced_review"
        assert connection.execute(
            "SELECT COUNT(*) FROM questions WHERE quiz_id = ? AND id = ?",
            (source_quiz_id, source_question_id),
        ).fetchone()[0] == 1

    browser.wait_for("quizRecoveryReady === true && generatedPracticeStatus?.is_transient === true")
    browser.click(".study-mode-btn")
    browser.wait_for(
        "window.DLMSQuizRecovery.listStoredRecords({activeQuizIds:["
        + json.dumps(str(generated[1]))
        + "]}).records.length === 1"
    )
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            UPDATE quizzes
            SET title = 'Renamed due session',
                source_file = 'renamed-due-session.html'
            WHERE id = ?
            """,
            (generated[1],),
        )

    browser.navigate(f"{browser_stack.base_url}/")
    browser.wait_for(
        "document.getElementById('dailyReviewCount').textContent !== 'Loading…' && "
        "document.querySelector('.daily-review-unfinished')"
    )
    assert browser.evaluate(
        "document.querySelector('.daily-review-native_due') === null"
    ) is True
    assert "Spaced Review — Due Questions" in browser.evaluate(
        "document.querySelector('.daily-review-unfinished').textContent"
    )

    # Abandoning generated recovery restores its valid server recommendation,
    # without deleting the generated quiz, lineage, saved activity or schedule.
    with sqlite3.connect(database_path) as connection:
        before_clear = list(connection.iterdump())
    browser.click(".daily-review-unfinished .daily-review-remove")
    browser.wait_for("document.getElementById('dailyReviewClearDialog').open")
    browser.click("#dailyReviewClearDialog button[value='clear']")
    browser.wait_for("document.getElementById('dailyReviewStatus').textContent.includes('resume point cleared')")
    assert browser.evaluate("document.querySelector('.daily-review-native_due') !== null") is True
    assert browser.evaluate(
        "[...document.querySelectorAll('.daily-review-unfinished')].every(card=>!card.textContent.includes('Spaced Review'))"
    ) is True
    with sqlite3.connect(database_path) as connection:
        assert list(connection.iterdump()) == before_clear


def test_today_review_keeps_recovery_local_and_due_state_shared_between_profiles(
    browser_server,
):
    """Two browser profiles share scheduling data, never recovery checkpoints."""
    database_path = browser_server.data_root / "results.db"
    with sqlite3.connect(database_path) as connection:
        for ordinal in (1, 2):
            cursor = connection.execute(
                "INSERT INTO quizzes (title, source_file) VALUES (?, ?)",
                (
                    f"Shared due source {ordinal}",
                    f"shared-due-source-{ordinal}.html",
                ),
            )
            quiz_id = cursor.lastrowid
            cursor = connection.execute(
                """
                INSERT INTO questions (
                    quiz_id, question_number, question_text, question_type,
                    explanation, media_json
                ) VALUES (?, 1, ?, 'choice', 'Shared due explanation', '{}')
                """,
                (quiz_id, f"Shared due question {ordinal}?"),
            )
            question_id = cursor.lastrowid
            connection.executemany(
                "INSERT INTO choices (question_id, label, text, is_correct) VALUES (?, ?, ?, ?)",
                [
                    (question_id, "A", "Expected", 1),
                    (question_id, "B", "Alternative", 0),
                ],
            )
            connection.execute(
                """
                INSERT INTO learning_events (
                    event_type, quiz_id, question_id, attempt_id, session_id,
                    mode, was_correct, response_json, occurred_at
                ) VALUES ('exam_answer', ?, ?, ?, NULL, 'Exam', 0, '{}', ?)
                """,
                (
                    quiz_id,
                    question_id,
                    f"shared-due-history-{ordinal}",
                    "2020-01-01T00:00:00+00:00",
                ),
            )

    launched = []

    def launch(label):
        port = _free_loopback_port()
        session_root = browser_server.work_root / f"multi-client-{label}"
        profile = session_root / "profile"
        profile.mkdir(parents=True)
        log_path = session_root / "firefox.log"
        output = log_path.open("w", encoding="utf-8")
        process = subprocess.Popen(
            [
                browser_server.firefox,
                "--headless",
                "--no-remote",
                "--profile",
                str(profile),
                "--remote-debugging-port",
                str(port),
                "about:blank",
            ],
            cwd=ROOT,
            env=browser_server.env,
            stdout=output,
            stderr=subprocess.STDOUT,
            **browser_server.process_options,
        )
        try:
            browser = _connect_firefox(port, process, log_path)
        except Exception:
            _terminate_process_tree(process)
            output.close()
            raise
        launched.append((browser, process, output))
        return browser

    def dashboard_state(browser, due_count):
        browser.navigate(f"{browser_server.base_url}/")
        due_condition = (
            f"document.querySelector('.daily-review-native_due')?.textContent.includes('{due_count} source question')"
            if due_count
            else "document.getElementById('dailyReviewCount').textContent !== 'Loading…' && !document.querySelector('.daily-review-native_due')"
        )
        browser.wait_for(due_condition)
        return browser.evaluate(
            "(() => ({"
            "due:document.querySelector('.daily-review-native_due')?.textContent||'',"
            "unfinished:[...document.querySelectorAll('.daily-review-unfinished')].map(item=>item.textContent)"
            "}))()"
        )

    def complete_one_due_question(browser):
        assert browser.evaluate(
            "(() => {const input=document.querySelector("
            "'.daily-review-native_due input[name=question_count]');"
            "if(!input)return false;input.value='1';return true;})()"
        ) is True
        browser.click(".daily-review-native_due button")
        browser.wait_for("location.pathname.startsWith('/quizzes/spaced_review_native_')")
        browser.wait_for("quizRecoveryReady === true && quiz.length === 1")
        browser.click(".study-mode-btn")
        recovery_key = browser.evaluate("quizRecoveryController.storageKey")
        browser.click("#choices .choice[data-index='0']")
        browser.wait_for("studyLearningEventSaves.size === 0")
        # Generated Study sessions remain resumable until Finish Review succeeds.
        # Saving the last answer alone must not clear this browser's checkpoint.
        assert browser.evaluate("generatedPracticeStatus.completed") is False
        assert browser.evaluate(
            f"localStorage.getItem({json.dumps(recovery_key)}) !== null"
        ) is True
        browser.click("#finishReviewBtn")
        browser.wait_for(
            f"localStorage.getItem({json.dumps(recovery_key)}) === null && "
            "studyLearningEventSaves.size === 0 && generatedPracticeStatus.completed === true"
        )
        return recovery_key

    try:
        first = launch("first")
        second = launch("second")

        first.navigate(
            f"{browser_server.base_url}/quizzes/{browser_server.metadata['critical_html']}"
        )
        first.wait_for("quizRecoveryReady === true")
        first.click(".study-mode-btn")
        first_recovery_key = first.evaluate("quizRecoveryController.storageKey")

        second.navigate(
            f"{browser_server.base_url}/quizzes/{browser_server.metadata['companion_html']}"
        )
        second.wait_for("quizRecoveryReady === true")
        second.click(".study-mode-btn")
        second_recovery_key = second.evaluate("quizRecoveryController.storageKey")

        first_state = dashboard_state(first, 2)
        second_state = dashboard_state(second, 2)
        assert "Browser Critical Workflow" in " ".join(first_state["unfinished"])
        assert "Browser Companion" not in " ".join(first_state["unfinished"])
        assert "Browser Companion" in " ".join(second_state["unfinished"])
        assert "Browser Critical Workflow" not in " ".join(second_state["unfinished"])
        assert "This browser" in " ".join(first_state["unfinished"])
        assert "This browser" in " ".join(second_state["unfinished"])
        assert first.evaluate(
            f"localStorage.getItem({json.dumps(second_recovery_key)}) === null"
        ) is True
        assert second.evaluate(
            f"localStorage.getItem({json.dumps(first_recovery_key)}) === null"
        ) is True

        # Clear one profile's checkpoint while the other keeps its own intact.
        second.navigate(f"{browser_server.base_url}/quizzes/{browser_server.metadata['critical_html']}")
        second.wait_for("quizRecoveryReady === true")
        second.click(".exam-mode-btn")
        dashboard_state(second, 2)
        first.click(".daily-review-unfinished .daily-review-remove")
        first.click("#dailyReviewClearDialog button[value='clear']")
        first.wait_for("document.getElementById('dailyReviewStatus').textContent.includes('resume point cleared')")
        assert first.evaluate(f"localStorage.getItem({json.dumps(first_recovery_key)}) === null") is True
        assert second.evaluate(f"localStorage.getItem({json.dumps(second_recovery_key)}) !== null") is True
        assert second.evaluate(f"localStorage.getItem({json.dumps(first_recovery_key)}) !== null") is True
        assert first.evaluate("document.querySelector('.daily-review-unfinished') === null") is True
        second_state = dashboard_state(second, 2)
        assert "Browser Companion" in " ".join(second_state["unfinished"])

        first_generated_key = complete_one_due_question(first)
        first_after = dashboard_state(first, 1)
        second_after = dashboard_state(second, 1)
        assert first_after["due"] == second_after["due"]
        assert all(
            "Spaced Review — Due Questions" not in text
            for text in first_after["unfinished"]
        )
        assert first.evaluate(
            f"localStorage.getItem({json.dumps(first_generated_key)}) === null"
        ) is True

        final_generated_key = complete_one_due_question(first)
        first_final = dashboard_state(first, 0)
        second_final = dashboard_state(second, 0)
        assert not first_final["due"] and not second_final["due"]
        assert all(
            "Spaced Review — Due Questions" not in text
            for text in first_final["unfinished"]
        )
        assert first.evaluate(
            f"localStorage.getItem({json.dumps(final_generated_key)}) === null"
        ) is True
        assert not first_final["unfinished"]  # This profile explicitly abandoned its session.
        assert "Browser Companion" in " ".join(second_final["unfinished"])
    finally:
        for browser, process, output in reversed(launched):
            try:
                browser.command("browser.close", {}, timeout=3.0)
            except Exception:
                browser.close()
            _terminate_process_tree(process)
            output.close()


def test_today_review_clear_is_guarded_accessible_and_preserves_other_checkpoints(browser_stack):
    browser = browser_stack.browser
    base_url = browser_stack.base_url
    # The mixed-type fixture has playable artifacts but is normally deliberately
    # absent from the Library registry. Expose it here as the third real quiz.
    registry_path = browser_stack.data_root / "config" / "quizzes.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    registry.append({"id": "browser-recovery-mixed", "html": browser_stack.metadata["recovery_html"],
                     "title": "Browser Recovery Mixed Types",
                     "folder": "Browser Regression", "hidden": False})
    registry_path.write_text(json.dumps(registry), encoding="utf-8")
    keys = []
    for name, mode in (("critical", "study"), ("companion", "exam"), ("recovery", "study")):
        browser.navigate(f"{base_url}/quizzes/{browser_stack.metadata[name + '_html']}")
        browser.wait_for("quizRecoveryReady === true")
        browser.click(f".{mode}-mode-btn")
        keys.append(browser.evaluate("quizRecoveryController.storageKey"))
    # Rename and move after checkpoint creation: recovery still targets quiz ID.
    registry[-1].update({
        "title": "Renamed Browser Recovery — a deliberately long quiz title for narrow-window wrapping",
        "folder": "Uncategorized",
    })
    registry_path.write_text(json.dumps(registry), encoding="utf-8")
    browser.navigate(base_url + "/")
    browser.wait_for("document.querySelectorAll('#dailyReviewList .daily-review-remove').length === 2")

    # Exercise real Tab order, modal focus, contrast and geometry across palettes.
    # This headless host never gains document focus: Enter/Space does not activate
    # even an independent native button. Keep production native button semantics;
    # use live-element clicks for activation rather than a test-only UI workaround.
    for theme in ("light", "dark", "purple-gold", "maroon-gold"):
        _set_theme(browser, theme)
        browser.navigate(base_url + "/")
        browser.wait_for("document.querySelector('#dailyReviewList .daily-review-remove')")
        for width in (1440, 1024, 760, 420):
            browser.set_viewport(width, 1000)
            browser.wait_for_page_ready()
            browser.activate()
            browser.evaluate("document.querySelector('.daily-review-unfinished a').focus(); true")
            browser.press_key("\ue004")
            assert browser.evaluate("document.activeElement.className") == "daily-review-remove"
            browser.click("#dailyReviewList .daily-review-remove")
            browser.wait_for("document.getElementById('dailyReviewClearDialog').open")
            geometry = browser.evaluate(
                "(() => {const d=document.getElementById('dailyReviewClearDialog');"
                "const r=d.getBoundingClientRect();return {overflow:document.documentElement.scrollWidth-innerWidth,"
                "dialogOverflow:d.scrollWidth-d.clientWidth,left:r.left,right:r.right,"
                "cancelFocused:document.activeElement.value==='cancel',"
                "contained:[...d.querySelectorAll('button')].every(n=>{const b=n.getBoundingClientRect();return b.left>=r.left&&b.right<=r.right}),"
                "cards:[...document.querySelectorAll('.daily-review-item')].every(n=>n.scrollWidth<=n.clientWidth+1)};})()"
            )
            assert geometry["overflow"] <= 1 and geometry["dialogOverflow"] <= 1
            assert geometry["left"] >= 0 and geometry["right"] <= width
            assert geometry["cancelFocused"] and geometry["contained"] and geometry["cards"]
            contrast = _theme_contrast_snapshot(browser, {
                "secondary": ".daily-review-remove", "cancel": "#dailyReviewClearDialog button[value='cancel']",
                "confirm": "#dailyReviewClearDialog button[value='clear']",
                "description": "#dailyReviewClearDescription",
            })
            assert all(value["contrast"] >= 4.5 for value in contrast.values()), (theme, width, contrast)
            browser.press_key("\ue004")
            assert browser.evaluate("document.activeElement.value") == "clear"
            browser.command("input.performActions", {
                "context": browser.context,
                "actions": [{"type": "key", "id": "keyboard", "actions": [
                    {"type": "keyDown", "value": "\ue008"},
                    {"type": "keyDown", "value": "\ue004"},
                    {"type": "keyUp", "value": "\ue004"},
                    {"type": "keyUp", "value": "\ue008"},
                ]}],
            })
            browser.command("input.releaseActions", {"context": browser.context})
            assert browser.evaluate("document.activeElement.value") == "cancel"
            browser.click("#dailyReviewClearDialog button[value='cancel']")
            browser.wait_for("!document.getElementById('dailyReviewClearDialog').open")
            assert browser.evaluate("document.activeElement.classList.contains('daily-review-remove')") is True
    assert browser.evaluate(f"{json.dumps(keys)}.every(key=>localStorage.getItem(key)!==null)") is True

    # Cancel leaves the same record/card intact, including the older third slot.
    target = ".daily-review-unfinished:has(a[href$='/browser_recovery_mixed.html']) .daily-review-remove"
    before = browser.evaluate(f"{json.dumps(keys)}.map(key=>localStorage.getItem(key))")
    browser.click(target)
    browser.click("#dailyReviewClearDialog button[value='cancel']")
    assert browser.evaluate(f"{json.dumps(keys)}.map(key=>localStorage.getItem(key))") == before

    # A revision written during confirmation must not be cleared.
    browser.click(target)
    changed_key = browser.evaluate(
        "(() => {const r=DLMSQuizRecovery.listStoredRecords().records.find(r=>r.quizId==='browser-recovery-mixed');"
        "const key=DLMSQuizRecovery.STORAGE_PREFIX+encodeURIComponent(r.quizId);"
        "const record=JSON.parse(localStorage.getItem(key));record.session.revision++;"
        "localStorage.setItem(key,JSON.stringify(record));return key;})()"
    )
    browser.click("#dailyReviewClearDialog button[value='clear']")
    browser.wait_for("document.getElementById('dailyReviewStatus').textContent.includes('session changed')")
    assert browser.evaluate(f"localStorage.getItem({json.dumps(changed_key)}) !== null") is True

    # Removal failure is visible, preserves all records, and never hides the card.
    for method in ("removeItem", "getItem"):
        browser.evaluate(f"window.__storageMethod=Storage.prototype.{method};Storage.prototype.{method}=function(){{throw new Error('storage denied')}}; true")
        try:
            browser.click(target)
            browser.click("#dailyReviewClearDialog button[value='clear']")
            browser.wait_for("document.getElementById('dailyReviewStatus').textContent.includes('could not be cleared')")
            assert browser.evaluate("document.querySelectorAll('#dailyReviewList .daily-review-remove').length === 2")
        finally:
            browser.evaluate(f"Storage.prototype.{method}=window.__storageMethod; true")

    with sqlite3.connect(browser_stack.data_root / "results.db") as connection:
        saved_data = list(connection.iterdump())
    saved_registry = registry_path.read_bytes()
    browser.click(target)
    browser.click("#dailyReviewClearDialog button[value='clear']")
    browser.wait_for("document.getElementById('dailyReviewStatus').textContent.includes('resume point cleared')")
    assert browser.evaluate(f"localStorage.getItem({json.dumps(changed_key)}) === null") is True
    assert browser.evaluate(f"{json.dumps(keys[:2])}.every(key=>localStorage.getItem(key)!==null)") is True
    assert "Browser Critical Workflow" in browser.evaluate("document.getElementById('dailyReviewList').textContent")
    # The remaining ordinary Exam checkpoint can also be abandoned.
    browser.click(".daily-review-unfinished:has(a[href*='browser_companion']) .daily-review-remove")
    browser.click("#dailyReviewClearDialog button[value='clear']")
    browser.wait_for(f"localStorage.getItem({json.dumps(keys[1])}) === null")
    with sqlite3.connect(browser_stack.data_root / "results.db") as connection:
        assert list(connection.iterdump()) == saved_data
    assert registry_path.read_bytes() == saved_registry


def test_today_review_clear_protects_failed_study_and_submitted_exam_saves(browser_stack):
    browser = browser_stack.browser
    base_url = browser_stack.base_url
    for name, mode, endpoint in (("critical", "study", "/api/learning-events/study-response"), ("companion", "exam", "/record_attempt")):
        browser.navigate(f"{base_url}/quizzes/{browser_stack.metadata[name + '_html']}")
        browser.wait_for("quizRecoveryReady === true")
        browser.evaluate(
            "window.__originalFetch=window.fetch.bind(window);window.fetch=(...args)=>String(args[0]).includes("
            + json.dumps(endpoint) + ")?Promise.reject(new Error('simulated save failure')):window.__originalFetch(...args); true"
        )
        browser.click(f".{mode}-mode-btn")
        browser.click("#choices .choice[data-index='0']")
        if mode == "exam":
            browser.evaluate("window.confirm=()=>true; true")
            browser.click("#submitBtn")
            browser.wait_for("document.getElementById('result').textContent.includes('was not saved')")
        else:
            browser.wait_for("document.querySelector('.study-learning-save-retry:not([hidden])')")
    browser.navigate(base_url + "/")
    browser.wait_for("document.querySelectorAll('#dailyReviewList .daily-review-remove').length === 2")
    before = browser.evaluate("DLMSQuizRecovery.listStoredRecords().records.map(r=>localStorage.getItem(DLMSQuizRecovery.STORAGE_PREFIX+encodeURIComponent(r.quizId)))")
    for name, message in (("companion", "Use Finish Saving"), ("critical", "Study answers waiting")):
        browser.click(f".daily-review-unfinished:has(a[href*='browser_{name}']) .daily-review-remove")
        browser.click("#dailyReviewClearDialog button[value='clear']")
        browser.wait_for(f"document.getElementById('dailyReviewStatus').textContent.includes({json.dumps(message)})")
        assert browser.evaluate("document.querySelectorAll('#dailyReviewList .daily-review-remove').length === 2")
    assert browser.evaluate("DLMSQuizRecovery.listStoredRecords().records.map(r=>localStorage.getItem(DLMSQuizRecovery.STORAGE_PREFIX+encodeURIComponent(r.quizId)))") == before


def test_today_review_clear_does_not_control_or_resurrect_an_active_quiz_tab(browser_stack):
    browser = browser_stack.browser
    browser.navigate(f"{browser_stack.base_url}/quizzes/{browser_stack.metadata['critical_html']}")
    browser.wait_for("quizRecoveryReady === true")
    browser.click(".study-mode-btn")
    key = browser.evaluate("quizRecoveryController.storageKey")
    quiz_context = browser.context
    dashboard_context = browser.command("browsingContext.create", {"type": "tab"})["context"]
    try:
        browser.context = dashboard_context
        browser.navigate(browser_stack.base_url + "/")
        browser.wait_for("document.querySelector('#dailyReviewList .daily-review-remove')")
        browser.click(".daily-review-remove")
        browser.click("#dailyReviewClearDialog button[value='clear']")
        browser.wait_for("document.getElementById('dailyReviewStatus').textContent.includes('resume point cleared')")
        browser.context = quiz_context
        browser.wait_for("quizRecoveryController.ownsState === false")
        assert browser.evaluate("quizRecoveryController.checkpoint()") is False
        assert browser.evaluate("index === 0 && !examMode && !document.getElementById('quiz').hidden") is True
        assert "cleared by another DLMS page" in browser.evaluate("document.getElementById('quizRecoveryNotice').textContent")
        browser.navigate(browser_stack.base_url + "/")  # pagehide must not recreate it.
        browser.wait_for("document.getElementById('dailyReviewCount').textContent !== 'Loading…'")
        assert browser.evaluate(f"localStorage.getItem({json.dumps(key)}) === null") is True
    finally:
        _close_context_after_pagehide(browser, dashboard_context, quiz_context)
