"""Focused packaging boundaries; these do not establish normal-package acceptance."""
import hashlib
import json
from pathlib import Path
import re
import sys
import zipfile

import pytest

pytestmark = pytest.mark.skipif(sys.platform != 'win32', reason='Windows candidate packaging and native ownership')

import package_windows.entry as inherited
import package_windows_webview2
from package_windows_webview2 import entry
from package_windows_webview2.build import verify_environment, verify_host, verify_sdk_inputs

ROOT = Path(__file__).resolve().parents[2]


def test_default_root_is_distinct_without_environment_fallback(monkeypatch):
    import desktop.windows_processes as processes
    monkeypatch.setattr(processes, "default_data_root", lambda: Path("C:/owned/DLMSDesktop/WindowsCandidate"))
    assert entry.default_data_root() == Path("C:/owned/DLMSDesktop/WebView2Candidate")


def test_normal_entry_marks_host_and_injects_only_distinct_default(monkeypatch):
    import desktop.windows_processes as processes
    calls = []
    monkeypatch.delenv('DLMS_DESKTOP_DATA_ROOT', raising=False)
    monkeypatch.delenv('DLMS_DESKTOP_ROOT_KIND', raising=False)
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(processes, '_webview2_default_root', None)
    monkeypatch.setattr(package_windows_webview2, "ACTIVE", False)
    monkeypatch.setattr(sys, "argv", ["candidate.exe", "--profile", "test"])
    monkeypatch.setattr(entry, "default_data_root", lambda: Path("C:/fresh/WebView2Candidate"))
    monkeypatch.setattr(inherited, "root_path", lambda root, **kwargs: calls.append((root, kwargs)) or root)
    monkeypatch.setattr(inherited, "main", lambda: list(sys.argv))
    result = entry.main()
    assert package_windows_webview2.ACTIVE is True
    assert calls == [(Path("C:/fresh/WebView2Candidate"), {"create": True})]
    assert result[-2:] == ["--data-root", str(Path("C:/fresh/WebView2Candidate"))]


@pytest.mark.parametrize("arguments", [
    ["--desktop-worker", "backend"], ["--desktop-worker", "maintenance"],
    ["--profile", "x", "--data-root", "C:/explicit"], ["--data-root=C:/explicit"],
])
def test_authenticated_worker_and_explicit_root_argv_are_unchanged(monkeypatch, arguments):
    monkeypatch.setattr(package_windows_webview2, "ACTIVE", False)
    monkeypatch.setattr(sys, "argv", ["candidate.exe", *arguments])
    monkeypatch.setattr(inherited, "root_path", lambda *a, **kw: pytest.fail("must not create a default root"))
    monkeypatch.setattr(inherited, "main", lambda: list(sys.argv))
    assert entry.main() == ["candidate.exe", *arguments]


def make_host(tmp_path):
    host = tmp_path / "payload"
    host.mkdir()
    (host / "extension").mkdir()
    inventory = []
    for name in ("DLMS-WebView2-Host.exe", "Microsoft.Web.WebView2.Core.dll",
                 "Microsoft.Web.WebView2.WinForms.dll", "WebView2Loader.dll", "LICENSE.txt",
                 "extension/manifest.json", "extension/rules.json"):
        path = host / name
        path.write_bytes(name.encode())
        inventory.append({"Path": str(path), "Hash": hashlib.sha256(path.read_bytes()).hexdigest()})
    (tmp_path / "SHA256.json").write_text(json.dumps(inventory))
    return host


def test_host_exact_bytes_and_unknown_files(tmp_path):
    host = make_host(tmp_path)
    assert len(verify_host(host)) == 7
    (host / "WebView2Loader.dll").write_bytes(b"changed")
    with pytest.raises(ValueError, match="bytes changed"):
        verify_host(host)


def test_host_unknown_files_are_refused(tmp_path):
    host = make_host(tmp_path)
    (host / "unreviewed.exe").write_bytes(b"unknown")
    with pytest.raises(ValueError, match="Unknown or missing"):
        verify_host(host)


def test_host_unknown_subtree_is_refused_before_recursive_packaging(tmp_path):
    host = make_host(tmp_path)
    extra = host / "extra"
    extra.mkdir()
    (extra / "unexpected-native.dll").write_bytes(b"must never enter the payload")
    with pytest.raises(ValueError, match="non-regular entry"):
        verify_host(host)


def test_host_empty_unknown_directory_is_refused(tmp_path):
    host = make_host(tmp_path)
    (host / "extra").mkdir()
    with pytest.raises(ValueError, match="non-regular entry"):
        verify_host(host)


def test_host_hardlinked_file_is_refused(tmp_path):
    host = make_host(tmp_path)
    (tmp_path / "second-name").hardlink_to(host / "WebView2Loader.dll")
    with pytest.raises(ValueError, match="non-regular entry"):
        verify_host(host)


def test_host_unknown_extension_file_is_refused(tmp_path):
    host = make_host(tmp_path)
    (host / "extension/background.js").write_text("must not ship")
    with pytest.raises(ValueError, match="Unknown or missing"):
        verify_host(host)


def test_host_unknown_nested_extension_directory_is_refused(tmp_path):
    host = make_host(tmp_path)
    nested = host / "extension/nested"
    nested.mkdir()
    (nested / "extra.json").write_text("{}")
    with pytest.raises(ValueError, match="non-regular entry"):
        verify_host(host)


def test_host_missing_extension_rule_is_refused(tmp_path):
    host = make_host(tmp_path)
    (host / "extension/rules.json").unlink()
    with pytest.raises(ValueError, match="Unknown or missing"):
        verify_host(host)


def test_host_sdk_bytes_must_correspond_to_pinned_archive(tmp_path):
    host = make_host(tmp_path)
    archive = tmp_path / "sdk.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        for member in ("lib/net462/Microsoft.Web.WebView2.Core.dll",
                       "lib/net462/Microsoft.Web.WebView2.WinForms.dll",
                       "runtimes/win-x64/native/WebView2Loader.dll", "LICENSE.txt"):
            bundle.writestr(member, (host / Path(member).name).read_bytes())
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    verify_sdk_inputs(host, archive, expected=digest)
    (host / "WebView2Loader.dll").write_bytes(b"substituted")
    with pytest.raises(ValueError, match="differs from pinned archive"):
        verify_sdk_inputs(host, archive, expected=digest)
    with pytest.raises(ValueError, match="SDK archive changed"):
        verify_sdk_inputs(host, archive, expected="0" * 64)


def test_reviewed_dependency_pin_drift_is_refused(tmp_path, monkeypatch):
    import package_windows_webview2.build as build
    lock = tmp_path / "pins.txt"
    lock.write_text("example==1.2.3\n")
    monkeypatch.setattr(build.metadata, "version", lambda name: "9.9")
    with pytest.raises(ValueError, match="Dependency drift"):
        verify_environment(lock)


def test_installer_has_distinct_identity_and_no_prerequisite_install_or_data_delete():
    script = (ROOT / "package_windows_webview2/installer.iss").read_text()
    assert "PrivilegesRequired=lowest" in script
    assert "DLMSDesktop.WebView2Candidate.Running" in script
    assert "C7FCBD76-02F4-49C4-B187-9A143237A1F9" in script
    assert "HKCU32" not in script and "HKLM32" in script
    assert "if not HasWebView2Runtime then begin" in script
    assert "Microsoft Edge WebView2 Evergreen Runtime 155.0.4283.45 or newer is required" in script
    assert "Per-user/AppData Runtime installations are unsupported" in script
    assert "ExpandConstant('{pf32}')" in script
    assert "\\Microsoft\\EdgeWebView\\Application\\' + Version + '\\msedgewebview2.exe'" in script
    assert "FileExists(Image) and GetVersionNumbersString(Image, FileVersion) and (FileVersion = Version)" in script
    assert "SupportedWebView2Version(Version)" in script
    assert "[UninstallDelete]" not in script and "[InstallDelete]" not in script
    assert '#ifdef TestScope\n; Compile-time isolated qualification variant.' in script
    assert 'CreateUninstallRegKey=no\n#else\nCreateUninstallRegKey=yes\n#endif' in script
    assert "SafeDirectoryChain" in script and "GuardApplication(False)" in script
    assert "NativeLocalPath" in script and "OpenDirectory(NativePath," in script
    assert "FindFirst(AddBackslash(NativeLocalPath(Path)) + '*', Found)" in script
    assert "until not FindNext(Found);" in script and "if NativeLastError <> 18 then Exit;" in script
    assert "RemoveDir(NativeLocalPath(AppDirectories[I]))" in script
    assert "NativeAttributes(NativePath)" in script
    assert "Result := '\\\\?\\' + Path;" in script
    assert "if ReservedDosStem(Part) then Exit;" in script
    assert all("Stem = '"+name+"'" in script for name in ('CON','PRN','AUX','NUL'))
    assert "Copy(Stem, 1, 3) = 'COM'" in script and "Copy(Stem, 1, 3) = 'LPT'" in script
    assert all('Stem[4] = #'+str(code) in script for code in (185,178,179))
    assert "DLMS-Desktop.exe" not in script


def test_normal_spec_keeps_windowed_entry_and_separate_host_payload():
    spec = (ROOT / "package_windows_webview2/DLMS-Desktop-WebView2.spec").read_text()
    assert "package_windows_webview2/entry.py" in spec
    assert '(str(host), "windows_webview2")' in spec
    assert "name = 'DLMS-Desktop-WebView2-Instrumented' if instrumented else 'DLMS-Desktop-WebView2'" in spec
    assert "*([] if instrumented else ['tests'])" in spec
    assert "debug=False" in spec and "console=False" in spec
    assert "upx=False" in spec


def test_no_root_owner_uses_only_selected_windows_candidate_default(tmp_path, monkeypatch):
    import desktop.ownership as ownership
    import desktop.windows_files as files
    import desktop.windows_processes as processes
    root = tmp_path / "WebView2Candidate"
    descriptor = tmp_path / "instance-owner.json"
    descriptor.write_text(json.dumps({"pid": 42, "name": "default", "start_ticks": 123, "secret": "a" * 64}))
    monkeypatch.setattr(package_windows_webview2, "ACTIVE", True)
    monkeypatch.setattr(ownership, "FROZEN", True)
    monkeypatch.setattr(ownership, "AREA", root)
    monkeypatch.setattr(ownership, "assert_safe_leaf", lambda path: None)
    monkeypatch.setattr(ownership, "process_start_ticks", lambda pid: 123)
    monkeypatch.setattr(processes, "default_data_root", lambda: tmp_path / "WindowsCandidate")
    monkeypatch.setattr(processes, "captured_webview2_default_root", lambda: root)
    monkeypatch.setattr(processes, "identity", lambda pid: {"start": 123, "image": "same.exe", "sid": "same-owner"})
    monkeypatch.setattr(processes, "arguments", lambda pid: ["same.exe"])
    monkeypatch.setattr(files, "owned", lambda *args, **kwargs: None)
    assert ownership.verified_instance(descriptor, "default") == "a" * 64
    # Same executable/SID and absent --data-root cannot reinterpret the Qt default
    # as a WebView2 profile, or vice versa.
    monkeypatch.setattr(ownership, "AREA", tmp_path / "WindowsCandidate")
    assert ownership.verified_instance(descriptor, "default") is None
    monkeypatch.setattr(package_windows_webview2, "ACTIVE", False)
    assert ownership.verified_instance(descriptor, "default") == "a" * 64
    monkeypatch.setattr(ownership, "AREA", root)
    assert ownership.verified_instance(descriptor, "default") is None


def test_source_owner_module_is_renderer_specific(monkeypatch):
    from desktop.ownership import windows_source_launch_matches
    monkeypatch.setattr(package_windows_webview2, "ACTIVE", True)
    assert windows_source_launch_matches(["python.exe", "-m", "desktop.webview2_entry", "--profile", "synthetic"], "synthetic")
    assert not windows_source_launch_matches(["python.exe", "-m", "desktop", "--profile", "synthetic"], "synthetic")
    assert not windows_source_launch_matches(["python.exe", "-m", "other", "--profile", "synthetic"], "synthetic")
    assert not windows_source_launch_matches(["python.exe", "-m", "desktop.webview2_entry", "--profile", "synthetic", "--profile", "synthetic"], "synthetic")
    assert not windows_source_launch_matches(["python.exe", "-m", "desktop.webview2_entry", "--profile", "synthetic", "--profile=other"], "synthetic")
    monkeypatch.setattr(package_windows_webview2, "ACTIVE", False)
    assert windows_source_launch_matches(["python.exe", "-m", "desktop", "--profile", "synthetic"], "synthetic")
    assert not windows_source_launch_matches(["python.exe", "-m", "desktop.webview2_entry", "--profile", "synthetic"], "synthetic")


def test_app_user_model_id_changes_only_for_selected_windows_webview2(monkeypatch):
    import desktop.identity as identity
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(package_windows_webview2, "ACTIVE", True)
    assert identity.windows_application_id() == identity.DESKTOP_FILE_ID + ".WebView2Candidate"
    monkeypatch.setattr(package_windows_webview2, "ACTIVE", False)
    assert identity.windows_application_id() == identity.DESKTOP_FILE_ID + ".WindowsCandidate"
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(package_windows_webview2, "ACTIVE", True)
    assert identity.windows_application_id() == identity.DESKTOP_FILE_ID + ".WindowsCandidate"


@pytest.mark.parametrize("version, expected", [
    ("155.0.4283.45", True), ("155.0.4283.60", True), ("156.0.0.0", True),
    ("155.0.4283.44", False), ("154.9.9999.9999", False), ("0.0.0.0", False),
    ("155.0.4283", False), ("155.0.4283.45 beta", False),
    ("155.0.4283.45.0", False), ("65536.0.0.0", False),
])
def test_explicit_runtime_floor(version, expected):
    from package_windows_webview2.runtime import supported_runtime
    assert supported_runtime(version) is expected


def test_installer_floor_matches_single_windows_launch_policy():
    from package_windows_webview2.runtime import MINIMUM_VERSION, supported_runtime
    from desktop.webview2_runtime import compatible_runtime
    script = (ROOT / "package_windows_webview2/installer.iss").read_text()
    fields = re.findall(r"[0-3]: Minimum := ([0-9]+);", script)
    assert tuple(map(int, fields)) == MINIMUM_VERSION
    assert supported_runtime is compatible_runtime


def test_installer_qualification_refuses_scope_escape_and_unsafe_release(tmp_path, monkeypatch):
    import package_windows_webview2.qualify_installer as qualifier
    monkeypatch.setattr(qualifier, "WORK", tmp_path)
    assert qualifier.fresh_scope(tmp_path / "fresh-scope") == tmp_path / "fresh-scope"
    for path in (tmp_path / ".." / "outside", tmp_path / "nested" / "scope", tmp_path):
        with pytest.raises(ValueError, match="fresh direct"):
            qualifier.fresh_scope(path)
    for release in ("../escape", "a/b", "a\\b", "--x", "a;run", ""):
        with pytest.raises(ValueError, match="Unsafe isolated"):
            qualifier.release_identity(release)
    assert qualifier.release_identity("windows-webview2-01") == "windows-webview2-01"
    assert {'CON','NUL.txt','COM\u00b9.txt','LPT\u00b2.txt','CON .txt'} <= set(qualifier.RESERVED_FIXTURES)
    with pytest.raises(ValueError,match='Refuse reserved-name fixture'):
        qualifier.reserved_fixture(tmp_path/'..'/'outside','CON')
    with pytest.raises(ValueError,match='Refuse reserved-name fixture'):
        qualifier.reserved_fixture(tmp_path,'unexpected')


def make_normal_payload(tmp_path):
    payload = tmp_path / "normal-payload"
    payload.mkdir()
    exe = payload / "DLMS-Desktop-WebView2.exe"
    exe.write_bytes(b"normal executable bytes")
    (payload / "renderer.dll").write_bytes(b"normal dependency bytes")
    inventory = tmp_path / "payload-inventory.json"
    def publish_inventory():
        inventory.write_text(json.dumps([{"path":p.relative_to(payload).as_posix(),
            "sha256":hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted(payload.rglob("*")) if p.is_file()]))
    publish_inventory()
    return exe, inventory, publish_inventory


def test_installer_acceptance_binds_exact_normal_package_bytes(tmp_path):
    from package_windows_webview2.acceptance import payload_binding, require_normal_acceptance
    exe, inventory, publish = make_normal_payload(tmp_path)
    receipt = {"normal_executable":str(exe),"runs":[{"exact_cleanup":True},{"exact_cleanup":True}],
               "instrumented":False,"ocr":True,"payload_verified_before_and_after":True,
               "owned_webview2_renderer_verified":True, "ocr":True, **payload_binding(exe,inventory)}
    require_normal_acceptance(receipt,exe,inventory)
    # Updating both payload and manifest after a successful run must still fail
    # against the old acceptance receipt, even when the EXE itself is unchanged.
    (exe.parent / "renderer.dll").write_bytes(b"untested renderer bytes")
    publish()
    with pytest.raises(ValueError,match="not bound"):
        require_normal_acceptance(receipt,exe,inventory)


def test_unbound_or_instrumented_acceptance_cannot_build_installer(tmp_path):
    from package_windows_webview2.acceptance import payload_binding, require_normal_acceptance
    exe, inventory, _ = make_normal_payload(tmp_path)
    receipt = {"normal_executable":str(exe),"runs":[{"exact_cleanup":True},{"exact_cleanup":True}],
               "instrumented":False,"ocr":True,"payload_verified_before_and_after":True,
               "owned_webview2_renderer_verified":True, "ocr":True, **payload_binding(exe,inventory)}
    for changed in ({"instrumented":True},{"ocr":False},{"ocr":None},{"payload_verified_before_and_after":False},
                    {"owned_webview2_renderer_verified":False},{"runs":[{"exact_cleanup":True}]},
                    {"normal_executable_sha256":"0"*64}, {"ocr":False}, {"ocr":None}):
        with pytest.raises(ValueError,match="acceptance"):
            require_normal_acceptance(receipt | changed,exe,inventory)
    missing_ocr=receipt.copy()
    missing_ocr.pop("ocr")
    with pytest.raises(ValueError,match="acceptance"):
        require_normal_acceptance(missing_ocr,exe,inventory)
    missing_ocr = dict(receipt)
    missing_ocr.pop('ocr')
    with pytest.raises(ValueError, match='acceptance'):
        require_normal_acceptance(missing_ocr, exe, inventory)


def test_normal_payload_unknown_file_is_refused(tmp_path):
    from package_windows_webview2.acceptance import payload_binding
    exe, inventory, _ = make_normal_payload(tmp_path)
    (exe.parent / "unexpected.dll").write_bytes(b"not inventoried")
    with pytest.raises(ValueError,match="Unknown, missing or changed"):
        payload_binding(exe,inventory)


def test_normal_renderer_argument_metadata_never_retains_full_arguments():
    from tests.webview2.normal_candidate import argument_metadata
    observed=argument_metadata(['host.exe','--secret=never-record-this','--use-angle=d3d11',
        '--disable-blink-features=SharedWorker','--enable-features=FeatureA:param/secret,FeatureB<Trial',
        '--type=gpu-process'])
    serialized=json.dumps(observed)
    assert 'never-record-this' not in serialized and 'param/secret' not in serialized
    assert {'flag':'--use-angle','value':'d3d11'} in observed['graphics_flags']
    assert observed['role']=='--type=gpu-process' and observed['arguments_read'] is True
    assert any(row.get('feature_names')==['FeatureA','FeatureB'] for row in observed['graphics_flags'])


def test_normal_renderer_inspection_requires_complete_args_and_runtime_version():
    from tests.webview2.normal_candidate import inspection_coverage,renderer_ready
    image='C:/Program Files (x86)/Microsoft/EdgeWebView/Application/155.0.4283.45/msedgewebview2.exe'
    host={'identity':{'image':'C:/payload/DLMS-WebView2-Host.exe'},'arguments_read':True,'role':'main'}
    browser={'identity':{'image':image},'arguments_read':True,'role':'main',
             'selected_file_versions':{image:{'version':'155.0.4283.45'}}}
    gpu={'identity':{'image':image},'arguments_read':True,'role':'--type=gpu-process'}
    good=[{'parent':parent,'processes':[host,browser,gpu]} for parent in (101,102)]
    assert len(inspection_coverage(good))==2
    assert renderer_ready(good,101)
    assert not renderer_ready([{'parent':101,'processes':[host]}],101)
    assert not renderer_ready(good,999)
    incomplete=[{'parent':parent,'processes':[host,browser,gpu|{'arguments_read':False,'argument_inspection_error':{'type':'OSError'}}]} for parent in (101,102)]
    with pytest.raises(AssertionError,match='Incomplete'):
        inspection_coverage(incomplete)
    missing_version=[{'parent':parent,'processes':[host,browser|{'selected_file_versions':{}},gpu]} for parent in (101,102)]
    with pytest.raises(AssertionError,match='Incomplete'):
        inspection_coverage(missing_version)
