"""Actual Qt window: canonical Local Settings navigation and all captured themes."""
from __future__ import annotations

import argparse
import json

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QFontInfo
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLabel, QPushButton

from desktop.settings_surface import THEME_REGISTRY, _solid
from tests.gate1.qt_checks import QtChecks


def run(profile: str, sample: bool):
    q = QtChecks(profile, automated=True)
    report = {"profile": profile, "themes": {}, "screenshots": {}, "scale": q.app.devicePixelRatio()}
    ids = ["light", "dark", "ethereal", "omarchy-catppuccin-latte", "omarchy-tokyo-night"] if sample else list(THEME_REGISTRY)
    try:
        for theme in ids:
            q.go("/settings/appearance")
            q.js("window._themeResult='pending'; fetch('/api/theme',{method:'POST',"
                 "headers:{'Content-Type':'application/json'},body:JSON.stringify({theme:" + repr(theme) + "})})"
                 ".then(r=>window._themeResult=r.ok?'ok':'failed').catch(()=>window._themeResult='failed'); true")
            q.wait("window._themeResult === 'ok'")
            for kind in ("backup", "reset-remove"):
                q.go("/settings/" + kind)
                assert q.window._settings_ready(kind)
                panel = q.window.settings_panel
                assert panel._theme == theme, (theme, panel._theme)
                web_shell = json.loads(q.js("JSON.stringify((()=>{const e=document.querySelector('.dashboard-shell');"
                                             "const c=getComputedStyle(e),r=e.getBoundingClientRect();"
                                             "return {left:r.left,top:r.top,radius:c.borderTopLeftRadius,"
                                             "border:c.borderTopWidth}})())"))
                assert web_shell == {"left": 12, "top": 12, "radius": "24px", "border": "1px"}, (theme, web_shell)
                assert panel.shell.pos() == QPoint(12, 12)
                assert not panel.shell.mask().contains(QPoint(0, 0))
                assert panel.shell.mask().contains(QPoint(panel.shell.width() // 2, 1))
                colors = THEME_REGISTRY[theme]['colors']
                expected_outline = _solid(colors['border'], _solid(colors['shell'], colors['body_base']))
                assert panel.shell.outline.color.name().lower() == expected_outline.lower()
                assert panel.shell.outline.radius == 24 and panel.shell.outline.isVisible()
                assert panel.shell.outline.geometry() == panel.shell.rect()
                web_style = json.loads(q.js("JSON.stringify((()=>{const s=document.querySelector('.dashboard-sidebar');"
                                            "const b=s.querySelector('.dashboard-brand-title');"
                                            "const n=s.querySelector('.dashboard-nav-item');"
                                            "return {border:getComputedStyle(s).borderRightWidth,"
                                            "borderColor:getComputedStyle(s).borderRightColor,"
                                            "brandFont:getComputedStyle(b).fontFamily,"
                                            "brandSize:getComputedStyle(b).fontSize,"
                                            "navFont:getComputedStyle(n).fontFamily,"
                                            "navSize:getComputedStyle(n).fontSize}})())"))
                assert web_style["border"] == "1px", (theme, web_style)
                assert panel.brand_mark.pixmap().width() == 34
                assert (panel.brand_mark.width(), panel.brand_mark.height()) == (
                    (40, 44) if theme == "ethereal" else (48, 54))
                assert panel.brand_title.font().pixelSize() == int(web_style["brandSize"][:-2])
                assert panel.nav_buttons[0].font().pixelSize() == int(web_style["navSize"][:-2])
                assert QFontInfo(panel.brand_title.font()).family() == (
                    "Noto Sans Mono" if theme == "ethereal" else "Liberation Sans")
                entry = THEME_REGISTRY[theme]
                assert f"border-right: 1px solid {entry['colors']['border_soft']}" in panel.styleSheet()
                report.setdefault("web_native_metrics", {})[theme] = {
                    "web": web_style,
                    "native_brand_family": QFontInfo(panel.brand_title.font()).family(),
                    "native_nav_family": QFontInfo(panel.nav_buttons[0].font()).family(),
                    "badge": [panel.brand_mark.width(), panel.brand_mark.height()],
                }
                if theme == ids[0] and kind == "backup":
                    details = panel.backup_page[0].findChild(QPushButton, "settingsDetailsToggle")
                    path_label = panel.backup_page[0].findChild(QLabel, "settingsDetails")
                    assert details is not None and path_label is not None and not path_label.isVisible()
                    details.click()
                    assert path_label.isVisible() and str(q.paths["root"]) in path_label.text()
                    details.click()
                    assert not path_label.isVisible()
                assert q.js("document.querySelector('.dashboard-sidebar').dataset.theme") == theme
                expected = q.js("JSON.stringify([...document.querySelectorAll('.dashboard-nav-normalized .dashboard-nav-item')]"
                                ".filter(x=>!x.closest('[hidden]')).map(x=>x.getAttribute('href')))")
                actual = [button.property("navPath") for button in panel.nav_buttons
                          if button.property("navPath") not in {"/settings/backup", "/settings/reset-remove", "/settings/appearance"}]
                assert actual == json.loads(expected), (theme, kind, actual, expected)
                assert any(button.property("selected") is True for button in panel.nav_buttons
                           if button.property("navPath") == "/settings/" + kind)
                library_nav = next(button for button in panel.nav_buttons
                                   if button.property("navPath") == "/library")
                assert library_nav.property("selected") is False
                if theme == "ethereal" and kind == "reset-remove":
                    report["quiz_library_outline_probe"] = {
                        "selected": library_nav.property("selected"),
                        "focused": library_nav.hasFocus(), "hovered": library_nav.underMouse()}
                    assert not library_nav.hasFocus() or library_nav.property("selected") is False
                if kind == "backup":
                    chart = panel.storage_composition
                    assert chart.donut.total >= 0 and len(chart._labels) == 10
                    assert "DLMS data" in chart.donut.accessibleName()
                for width in (1280, 690):
                    q.window.resize(width, 850)
                    q.delay(.12)
                    if width == 1280:
                        assert panel.shell.pos() == QPoint(12, 12)
                        assert not panel.shell.mask().contains(QPoint(0, 0))
                        assert panel.shell.mask().contains(QPoint(panel.shell.width() // 2, 1))
                        assert panel.shell.outline.isVisible() and "24px" in panel.shell.styleSheet()
                    else:
                        assert panel.shell.pos() == QPoint(0, 0)
                        assert panel.shell.outline.radius == 0 and not panel.shell.outline.isVisible()
                        assert "0px" in panel.shell.styleSheet()
                    assert panel.stack.isVisible(), (theme, kind, width)
                    if width == 1280:
                        assert panel.sidebar.horizontalScrollBar().maximum() == 0, (theme, kind, "sidebar overflow")
                    if width == 690:
                        assert panel.nav_toggle.isVisible() and not panel.sidebar.isVisible()
                        panel.nav_toggle.click()
                        assert panel.sidebar.isVisible() and not panel.stack.isVisible()
                        assert panel.sidebar.horizontalScrollBar().maximum() == 0, (theme, kind, "compact sidebar overflow")
                        if theme == "ethereal" and kind == "reset-remove":
                            panel.sidebar.verticalScrollBar().setValue(panel.sidebar.verticalScrollBar().maximum())
                            q.delay(.1)
                            target = q.paths["root"] / "sidebar-ethereal-selected-reset.png"
                            assert q.window.grab().save(str(target))
                            report["screenshots"]["ethereal:selected-reset"] = str(target)
                        if theme in {"light", "ethereal", "omarchy-tokyo-night"} and kind == "backup":
                            target = q.paths["root"] / f"sidebar-{theme}-navigation-narrow.png"
                            assert q.window.grab().save(str(target))
                            report["screenshots"][f"{theme}:navigation"] = str(target)
                        panel.nav_toggle.click()
                        assert panel.stack.isVisible()
                button = q.window.settings_buttons["backup" if kind == "backup" else "exam"]
                button.setFocus()
                q.delay(.1)
                assert button.hasFocus() and button.accessibleName()
                assert button.rect().width() > 150 and button.rect().height() >= 42
                if theme in {"light", "dark", "ethereal", "omarchy-catppuccin-latte", "omarchy-tokyo-night"}:
                    target = q.paths["root"] / f"sidebar-{theme}-{kind}-narrow.png"
                    assert q.window.grab().save(str(target))
                    report["screenshots"][f"{theme}:{kind}"] = str(target)
                q.window.resize(1280, 850)
                q.delay(.1)
                if theme in {"light", "dark", "ethereal"} and kind == "backup":
                    target = q.paths["root"] / f"sidebar-{theme}-backup-wide.png"
                    assert q.window.grab().save(str(target))
                    report["screenshots"][f"{theme}:wide"] = str(target)
            report["themes"][theme] = "both native pages, selected palette, canonical navigation, compact toggle and focused action passed"
        q.go("/settings/backup")
        panel = q.window.settings_panel
        q.window.resize(690, 850)
        q.delay(.1)
        panel.nav_toggle.setFocus()
        QTest.keyClick(panel.nav_toggle, Qt.Key.Key_Tab)
        assert q.app.focusWidget() is not panel.nav_toggle
        QTest.keyClick(q.app.focusWidget(), Qt.Key.Key_Backtab)
        assert panel.nav_toggle.hasFocus()
        report["application_local_tab_traversal"] = True
        panel.nav_toggle.click() if panel.nav_toggle.isVisible() else None
        q.window._settings_action_busy = True
        before = bytes(q.window.view.url().toEncoded())
        next(button for button in panel.nav_buttons if button.property("navPath") == "/library").click()
        assert bytes(q.window.view.url().toEncoded()) == before
        q.window._settings_action_busy = False
        assert q.window._settings_ready("backup")
        report["busy_navigation_refused"] = True
        q.window._navigate_settings("http://remote.example/")
        assert bytes(q.window.view.url().toEncoded()) == before
        report["external_navigation_refused"] = True
        report["pass"] = True
    finally:
        (q.paths["root"] / "sidebar-themes.json").write_text(json.dumps(report, indent=2) + "\n")
        q.close()
    print(json.dumps(report, indent=2))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    parser.add_argument("--sample", action="store_true")
    args = parser.parse_args()
    run(args.profile, args.sample)


if __name__ == "__main__":
    main()
