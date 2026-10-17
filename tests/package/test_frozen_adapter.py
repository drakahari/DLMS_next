"""Focused guards for the normal Fedora package entry and child ownership path."""
from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

from desktop import frozen_runtime, package_entry


def _marked(root: Path) -> Path:
    root.mkdir()
    (root / ".dlms-desktop-disposable.json").write_text(
        json.dumps({"kind": "dlms-desktop-fedora-package-feasibility", "version": 1})
    )
    return root


def test_frozen_children_use_same_executable_and_abstract_profile_ipc(monkeypatch, tmp_path):
    monkeypatch.setattr(frozen_runtime, "FROZEN", True)
    monkeypatch.setattr(sys, "executable", "/payload/DLMS-Desktop")
    assert frozen_runtime.child_command("backend", "--ready") == [
        "/payload/DLMS-Desktop", "--desktop-worker", "backend", "--ready"]
    assert frozen_runtime.child_command("adopt")[-2:] == ["--desktop-worker", "adopt"]
    with pytest.raises(ValueError, match="Unknown"):
        frozen_runtime.child_command("other")
    first = frozen_runtime.instance_socket_name(tmp_path / "very-long-profile")
    second = frozen_runtime.instance_socket_name(tmp_path / "very-long-profile")
    assert first == second and first.startswith("dlms-desktop-") and len(first) < 108
    assert first != frozen_runtime.instance_socket_name(tmp_path / "different-profile")


def test_package_root_rejects_missing_marker_symlink_and_payload(monkeypatch, tmp_path):
    payload = tmp_path / "payload"
    payload.mkdir()
    monkeypatch.setattr(sys, "_MEIPASS", str(payload), raising=False)
    good = _marked(tmp_path / "good")
    assert package_entry._root(str(good)) == good
    with pytest.raises(ValueError, match="existing absolute"):
        package_entry._root("relative")
    (tmp_path / "unmarked").mkdir()
    with pytest.raises(ValueError, match="marker"):
        package_entry._root(str(tmp_path / "unmarked"))
    (tmp_path / "link").symlink_to(good, target_is_directory=True)
    with pytest.raises(ValueError, match="disposable data directory"):
        package_entry._root(str(tmp_path / "link"))
    _marked(payload / "inside")
    with pytest.raises(ValueError, match="separate"):
        package_entry._root(str(payload / "inside"))


def test_normal_entry_rejects_fault_flags_before_shell(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", "/payload", raising=False)
    monkeypatch.setattr(sys, "argv", ["DLMS-Desktop", "--automated"])
    monkeypatch.setenv("DLMS_DESKTOP_AUTOMATED", "1")
    with pytest.raises(ValueError, match="fault-injection"):
        package_entry.main(instrumented=False)
    assert "DLMS_DESKTOP_AUTOMATED" not in __import__("os").environ
