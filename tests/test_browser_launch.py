"""Host browser subprocesses must not inherit bundled Linux libraries."""
import os
import subprocess
import sys
from unittest import mock

import pytest

from dlms import browser_launch as browser


@pytest.mark.parametrize("original", [None, "", "/host/lib:/app/usr/lib:/frozen/lib"])
def test_child_environment_restores_host_paths_without_mutating_runtime(original):
    environment = {
        "LD_LIBRARY_PATH": "/frozen:/app/usr/lib:/host/lib",
        "LD_PRELOAD": "/app/shim.so /host/shim.so:/frozen/shim.so",
        "LD_AUDIT": "/frozen/audit.so:/host/audit.so",
        "PATH": "/app/bin:/frozen/bin:/usr/bin:/application/bin",
        "DISPLAY": ":1", "WAYLAND_DISPLAY": "wayland-1",
        "DBUS_SESSION_BUS_ADDRESS": "unix:path=/host/session",
    }
    if original is not None:
        environment["LD_LIBRARY_PATH_ORIG"] = original
    before = environment.copy()
    child = browser.external_browser_environment(environment, ["/frozen", "/app"])
    assert environment == before
    assert child.get("LD_LIBRARY_PATH") == ("/host/lib" if original else None)
    assert "LD_LIBRARY_PATH_ORIG" not in child
    assert child["LD_PRELOAD"] == "/host/shim.so"
    assert child["LD_AUDIT"] == "/host/audit.so"
    assert child["PATH"] == "/usr/bin:/application/bin"
    for key in ("DISPLAY", "WAYLAND_DISPLAY", "DBUS_SESSION_BUS_ADDRESS"):
        assert child[key] == before[key]


@pytest.mark.parametrize("platform,frozen", [("linux", False), ("win32", True), ("darwin", True)])
def test_existing_platform_and_source_browser_behavior(platform, frozen, monkeypatch):
    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setattr(sys, "frozen", frozen, raising=False)
    with mock.patch.object(browser.webbrowser, "open", return_value=True) as opened:
        assert browser.open_browser("http://127.0.0.1:9001")
    opened.assert_called_once_with("http://127.0.0.1:9001", new=2)


@pytest.fixture
def frozen(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", "/frozen", raising=False)
    monkeypatch.setenv("LD_LIBRARY_PATH", "/frozen")
    monkeypatch.delenv("LD_LIBRARY_PATH_ORIG", raising=False)
    monkeypatch.delenv("BROWSER", raising=False)


def test_desktop_dispatch_uses_child_environment(frozen):
    before = dict(os.environ)
    with mock.patch.object(browser.shutil, "which", side_effect=lambda name, **_: "/usr/bin/" + name), \
            mock.patch.object(browser.subprocess, "Popen") as launch:
        launch.return_value.wait.return_value = 0
        assert browser.open_browser("http://127.0.0.1:9001")
    assert launch.call_args.args[0] == ["/usr/bin/xdg-open", "http://127.0.0.1:9001"]
    assert "LD_LIBRARY_PATH" not in launch.call_args.kwargs["env"]
    assert dict(os.environ) == before


def test_browser_override_real_shell_child(frozen, monkeypatch, tmp_path):
    # Exercise exec/environment propagation, not just a mocked Popen call.
    output = tmp_path / "environment"
    script = tmp_path / "browser with spaces"
    script.write_text('#!/bin/sh\nprintf "%s\\n" "$1" "${LD_LIBRARY_PATH-unset}" > "$PROBE_OUTPUT"\n')
    script.chmod(0o755)
    monkeypatch.setenv("BROWSER", f'"{script}" %s')
    monkeypatch.setenv("PROBE_OUTPUT", str(output))
    monkeypatch.setenv("LD_LIBRARY_PATH_ORIG", str(tmp_path))
    before = dict(os.environ)
    assert browser.open_browser("http://127.0.0.1:9001")
    assert output.read_text().splitlines() == ["http://127.0.0.1:9001", str(tmp_path)]
    assert dict(os.environ) == before


def test_dispatch_failure_falls_back_and_exhaustion_is_reported(frozen):
    with mock.patch.object(browser.shutil, "which", side_effect=lambda name, **_: "/usr/bin/" + name), \
            mock.patch.object(browser.subprocess, "Popen") as launch:
        launch.return_value.wait.side_effect = [1, 0]
        assert browser.open_browser("http://127.0.0.1:9001")
        assert launch.call_args.args[0][1] == "open"  # gio fallback
        launch.return_value.wait.side_effect = None
        launch.return_value.wait.return_value = 1
        assert not browser.open_browser("http://127.0.0.1:9001")


def test_long_lived_browser_is_not_killed(frozen):
    with mock.patch.object(browser.shutil, "which", return_value="/usr/bin/xdg-open"), \
            mock.patch.object(browser.subprocess, "Popen") as launch:
        launch.return_value.wait.side_effect = subprocess.TimeoutExpired("browser", 5)
        assert browser.open_browser("http://127.0.0.1:9001")
        launch.return_value.kill.assert_not_called()
        launch.return_value.terminate.assert_not_called()
