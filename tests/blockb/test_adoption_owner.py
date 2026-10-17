"""The offline adoption worker keeps parent and window ownership mandatory."""
from __future__ import annotations

import json
import os

import pytest

from desktop import adopt, maintenance, ownership
from desktop.transition import TransitionUnresolved


@pytest.fixture
def owned_window(tmp_path, monkeypatch):
    profile = tmp_path / "profiles/pilot01"
    profile.mkdir(parents=True)
    descriptor = profile / "instance-owner.json"
    descriptor.write_text(json.dumps({"pid": os.getppid(), "name": "pilot01"}))
    monkeypatch.setattr(maintenance, "read_marker", lambda _name: None)
    monkeypatch.setattr(adopt, "profile_paths", lambda _name: {"root": profile})
    monkeypatch.setattr(ownership, "verified_instance", lambda _path, _name: "a" * 64)
    monkeypatch.setenv("DLMS_DESKTOP_ADOPT_OWNER_SECRET", "a" * 64)
    return descriptor


def test_legitimate_owner_reaches_adoption_transaction(owned_window, monkeypatch):
    reached = []
    monkeypatch.setattr(adopt, "_run_owned", lambda *args, **kwargs: reached.append(args) or {"outcome": "test"})
    assert adopt.run("pilot01", selection_token="b" * 32) == {"outcome": "test"}
    assert len(reached) == 1


def test_wrong_secret_cannot_reach_adoption(owned_window, monkeypatch):
    monkeypatch.setenv("DLMS_DESKTOP_ADOPT_OWNER_SECRET", "b" * 64)
    monkeypatch.setattr(adopt, "_run_owned", lambda *args, **kwargs: pytest.fail("restore started"))
    with pytest.raises(TransitionUnresolved, match="does not own"):
        adopt.run("pilot01", selection_token="b" * 32)


def test_other_parent_cannot_reach_adoption(owned_window, monkeypatch):
    data = json.loads(owned_window.read_text())
    data["pid"] = os.getppid() + 1
    owned_window.write_text(json.dumps(data))
    monkeypatch.setattr(adopt, "_run_owned", lambda *args, **kwargs: pytest.fail("restore started"))
    with pytest.raises(TransitionUnresolved, match="not a child"):
        adopt.run("pilot01", selection_token="b" * 32)
