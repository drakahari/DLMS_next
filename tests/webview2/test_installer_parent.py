"""Probe construction checks; actual ACL/path acceptance uses the compiled probe."""
from pathlib import Path
import os

import pytest

from tests.webview2 import installer_parent_probe as probe
from tests.webview2.installer_parent_probe import ROOT, probe_script, production_code


def test_compiled_probe_retains_production_guards_except_explicit_race_adapter():
    source = (ROOT / 'package_windows_webview2/installer.iss').read_text(encoding='utf-8')
    original = source.split('[Code]\n', 1)[1]
    generated = production_code(source)
    start = generated.index('var RaceTarget: String;')
    end = generated.index('function SidString(Sid: NativeUInt): String;')
    restored = generated[:start] + generated[end:]
    restored = restored.replace('function RawCreatePrivateDirectory(Name: String; Security: NativeUInt): Boolean;',
                                'function CreatePrivateDirectory(Name: String; Security: NativeUInt): Boolean;')
    assert restored == original


def test_probe_cannot_install_payload_or_user_integration():
    source = (ROOT / 'package_windows_webview2/installer.iss').read_text(encoding='utf-8')
    text = probe_script(source, Path('C:/synthetic/probe'), Path('C:/synthetic/Programs'))
    assert '[Files]' not in text
    assert '[Icons]' not in text
    assert '[Registry]' not in text
    assert 'CreateAppDir=no' in text
    assert 'Uninstallable=no' in text
    assert 'CreateUninstallRegKey=no' in text
    initialize = text.split('function InitializeSetup: Boolean;', 1)[1]
    assert initialize.count('Result := False;') == 1
    assert 'Result := True;' not in initialize
    assert 'PrivilegesRequired=lowest' in text


@pytest.mark.skipif(os.name != 'nt', reason='Driver uses Windows pinned-path/ACL primitives; native Windows validation required')
def test_driver_preflight_rejects_traversal_escape_and_existing_scope(tmp_path, monkeypatch):
    work = tmp_path / 'work'
    work.mkdir()
    monkeypatch.setattr(probe, 'WORK', work)
    for path in (work / '..' / 'escape', tmp_path / 'outside', work):
        with pytest.raises(ValueError):
            probe.fresh_scope(path)
    fresh = work / 'new scope'
    assert probe.fresh_scope(fresh) == fresh.resolve()
    assert not fresh.exists()
