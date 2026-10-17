"""Frozen owner checks must accept only the selected packaged launch form."""
from __future__ import annotations

import json
import subprocess
import sys

import pytest

from desktop import ownership


@pytest.fixture
def installed_owner(tmp_path, monkeypatch):
    root = tmp_path / "home/.local/share/dlms-desktop-pilot"
    profile = root / "profiles/pilot01"
    profile.mkdir(parents=True)
    monkeypatch.setattr(ownership, "FROZEN", True)
    monkeypatch.setattr(ownership, "AREA", root)
    monkeypatch.setenv("DLMS_DESKTOP_ROOT_KIND", "installed-pilot")
    processes = []

    def start(*args):
        process = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)", *args],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        processes.append(process)
        descriptor = {
            "pid": process.pid,
            "start_ticks": ownership.process_start_ticks(process.pid),
            "name": "pilot01",
            "secret": "a" * 64,
        }
        path = profile / "instance-owner.json"
        path.write_text(json.dumps(descriptor))
        return path

    yield root, start
    for process in processes:
        process.terminate()
        process.wait(timeout=5)


def test_installed_pilot_owner_is_verified(installed_owner):
    root, start = installed_owner
    descriptor = start("--profile", "pilot01", "--installed-pilot-root", str(root))
    assert ownership.verified_instance(descriptor, "pilot01") == "a" * 64


@pytest.mark.parametrize("arguments", [
    ("--profile", "pilot01", "--installed-pilot-root", "wrong-root"),
    ("--profile", "other", "--installed-pilot-root", "{root}"),
    ("--desktop-worker", "adopt", "--profile", "pilot01", "--installed-pilot-root", "{root}"),
    ("--profile", "pilot01", "--data-root", "{root}"),
    ("--profile", "pilot01", "--installed-pilot-root", "{root}", "--data-root", "{root}"),
    ("--profile", "pilot01", "--profile", "pilot01", "--installed-pilot-root", "{root}"),
    ("--profile", "pilot01", "--installed-pilot-root", "{root}",
     "--installed-pilot-root", "{root}"),
    ("--profile", "other", "pilot01", "--installed-pilot-root", "{root}"),
    ("--profile", "pilot01", "--installed-pilot-root", "wrong-root", "{root}"),
])
def test_installed_pilot_rejects_wrong_or_unauthorized_caller(installed_owner, arguments):
    root, start = installed_owner
    descriptor = start(*(str(root) if value == "{root}" else value for value in arguments))
    assert ownership.verified_instance(descriptor, "pilot01") is None


def test_unknown_root_kind_refuses(installed_owner, monkeypatch):
    root, start = installed_owner
    descriptor = start("--profile", "pilot01", "--installed-pilot-root", str(root))
    monkeypatch.setenv("DLMS_DESKTOP_ROOT_KIND", "unexpected")
    assert ownership.verified_instance(descriptor, "pilot01") is None


def test_changed_start_identity_refuses(installed_owner):
    root, start = installed_owner
    descriptor = start("--profile", "pilot01", "--installed-pilot-root", str(root))
    value = json.loads(descriptor.read_text())
    value["start_ticks"] += 1
    descriptor.write_text(json.dumps(value))
    assert ownership.verified_instance(descriptor, "pilot01") is None
