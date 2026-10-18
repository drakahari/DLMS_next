"""Direct managed-policy and native trust checks, without starting a browser.

Compile the actual host sources with the already pinned SDK, then reflect only
the component-policy/trust methods. This neither reads existing profiles nor
constructs a Form. Full normal-executable persisted-profile evidence is separate.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / '.gate1/windows-native'
FAMILY = Path('C:/Program Files (x86)/Microsoft/EdgeWebView/Application')
ACTIVE = str(FAMILY / '155.0.4283.60')
OLDER = str(FAMILY / '155.0.4283.45')

pytestmark = pytest.mark.skipif(os.name != 'nt', reason='Native Windows protected Runtime metadata policy')

PROBE = r'''
using System;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using System.Runtime.Serialization;
using System.Security.AccessControl;
using System.Security.Principal;
using System.Web.Script.Serialization;
using Microsoft.Win32.SafeHandles;
class ComponentMetadataProbe {
    static readonly BindingFlags Hidden=BindingFlags.NonPublic|BindingFlags.Instance|BindingFlags.Static;
    static int Main(string[] args) {
        // Match the shipping Host.Main process-local path compatibility setup.
        AppContext.SetSwitch("Switch.System.IO.UseLegacyPathHandling",false);
        AppContext.SetSwitch("Switch.System.IO.BlockLongPaths",false);
        var serializer=new JavaScriptSerializer();
        var input=serializer.Deserialize<Dictionary<string,object>>(Console.In.ReadToEnd());
        var type=Assembly.LoadFrom(args[0]).GetType("DesktopRenderer",true);
        object host=null;
        var pins=new List<SafeFileHandle>();
        try {
            string operation=(string)input["operation"];
            object result=null;
            if(operation=="predicate")
                result=type.GetMethod("ComponentMetadataRuntime",Hidden).Invoke(null,new[]{input["location"],input["path"],input["active"],input["resource"]});
            else if(operation=="signature")
                type.GetMethod("VerifySignedRuntimeImage",Hidden).Invoke(null,new[]{input["path"],input["version"]});
            else if(operation=="missing")
                result=type.GetMethod("RuntimeObjectMissing",Hidden).Invoke(null,new[]{input["path"],input["directory"]});
            else if(operation=="acl") {
                // In-memory descriptors only: never change a Windows ACL.
                var acl=new DirectorySecurity();acl.SetOwner(new SecurityIdentifier((string)input["owner"]));
                acl.AddAccessRule(new FileSystemAccessRule(new SecurityIdentifier((string)input["sid"]),
                    (FileSystemRights)Enum.Parse(typeof(FileSystemRights),(string)input["rights"]),AccessControlType.Allow));
                type.GetMethod("CheckRuntimeAcl",Hidden).Invoke(null,new object[]{acl,input["ancestor"]});
            }
            else {
                host=FormatterServices.GetUninitializedObject(type);
                type.GetField("trustedRuntimeDirectory",Hidden).SetValue(host,input["active"]);
                type.GetField("policyHandles",Hidden).SetValue(host,pins);
                type.GetField("pinnedPolicyDirectories",Hidden).SetValue(host,new HashSet<string>(StringComparer.OrdinalIgnoreCase));
                type.GetField("verifiedHistoricalComponentRuntimes",Hidden).SetValue(host,new HashSet<string>(StringComparer.OrdinalIgnoreCase));
                type.GetField("json",Hidden).SetValue(host,serializer);
                if(operation=="historical")
                    type.GetMethod("VerifyHistoricalComponentRuntime",Hidden).Invoke(host,new[]{input["path"]});
                else if(operation=="metadata")
                    type.GetMethod("CheckComponentMetadata",Hidden).Invoke(host,new[]{input["path"]});
                else if(operation=="protected")
                    type.GetMethod("ProtectedRuntimePath",Hidden).Invoke(host,new[]{input["path"],input["directory"],(object)true});
                else throw new InvalidOperationException("Unknown test operation");
            }
            Console.Write(serializer.Serialize(new{accepted=true,value=result,pins=pins.Count}));
        }catch(Exception ex) {
            while(ex is TargetInvocationException&&ex.InnerException!=null)ex=ex.InnerException;
            Console.Write(serializer.Serialize(new{accepted=false,type=ex.GetType().FullName,message=ex.Message,inner=ex.InnerException==null?null:ex.InnerException.GetType().FullName}));
        }finally {foreach(var handle in pins)handle.Dispose();}
        return 0;
    }
}
'''


@pytest.fixture(scope='module')
def probe(tmp_path_factory):
    from package_windows_webview2.build import verify_sdk_inputs
    compiler = Path('C:/Windows/Microsoft.NET/Framework64/v4.0.30319/csc.exe')
    sdk = WORK / 'webview2-host-candidate-01/payload'
    if not compiler.is_file() or not sdk.is_dir():
        pytest.skip('Existing .NET Framework compiler and pinned canonical SDK payload required; no prerequisites installed')
    verify_sdk_inputs(sdk, WORK / 'webview2-inputs-01/webview2.nupkg')
    out = tmp_path_factory.mktemp('component-metadata')
    for name in ('Microsoft.Web.WebView2.Core.dll', 'Microsoft.Web.WebView2.WinForms.dll'):
        shutil.copyfile(sdk / name, out / name)
    host = out / 'DLMS-WebView2-Host.exe'
    sources = ('Host.cs', 'BrowserSurface.cs', 'FetchMetadata.cs', 'BrowserHandoff.cs',
               'AiActions.cs', 'AiScripts.cs', 'AiActionLease.cs', 'RequestProtocol.cs')
    common = [str(compiler), '/nologo', '/platform:x64', '/optimize+', '/reference:System.dll',
              '/reference:System.Core.dll', '/reference:System.Drawing.dll', '/reference:System.Windows.Forms.dll',
              '/reference:System.Web.Extensions.dll']
    subprocess.run(common + ['/target:winexe', '/out:' + str(host),
                   '/reference:' + str(out / 'Microsoft.Web.WebView2.Core.dll')] +
                   [str(ROOT / 'windows_webview2' / name) for name in sources],
                   check=True, capture_output=True, text=True, timeout=60)
    source = out / 'ComponentMetadataProbe.cs'; source.write_text(PROBE, encoding='utf-8')
    exe = out / 'ComponentMetadataProbe.exe'
    subprocess.run(common + ['/target:exe', '/out:' + str(exe), str(source)],
                   check=True, capture_output=True, text=True, timeout=30)
    target = host
    if os.environ.get('DLMS_WV_POLICY_TEST_HOST'):
        target = Path(os.environ['DLMS_WV_POLICY_TEST_HOST']).resolve(strict=True)
        if not target.is_relative_to(WORK) or target.name != 'DLMS-WebView2-Host.exe':
            raise ValueError('Only an explicitly selected task-local normal host may be inspected')

    def invoke(operation, **data):
        result = subprocess.run([str(exe), str(target)], input=json.dumps(dict(operation=operation, **data)),
                                capture_output=True, text=True, timeout=30, check=True)
        return json.loads(result.stdout)
    invoke.compiler = common
    return invoke


def virtual(version='155.0.4283.45', resource='edge_clipboard'):
    return str(FAMILY / version / 'resources' / resource)


@pytest.mark.parametrize('resource', ['edge_clipboard', 'edge_pdf'])
@pytest.mark.parametrize('version', ['155.0.4283.45', '155.0.4283.60'])
def test_exact_current_and_supported_historical_virtual_resources(probe, resource, version):
    result = probe('predicate', location=5, path=virtual(version, resource), active=ACTIVE, resource=resource)
    assert result == {'accepted': True, 'value': str(FAMILY / version), 'pins': 0}


@pytest.mark.parametrize('location', [None, '5', True, 5.0, 0, 4, 6])
def test_location_is_exact_component_integer(probe, location):
    assert not probe('predicate', location=location, path=virtual(), active=ACTIVE, resource='edge_clipboard')['accepted']


@pytest.mark.parametrize('path', [
    virtual('155.0.4283.61'), virtual('155.0.4283.44'), virtual('154.0.4283.45'),
    virtual('155.0'), virtual('155.0.4283'), virtual('155.00.4283.45'), virtual('155.0.4283.045'),
    virtual('155.0.4283.45.1'), virtual('155.0.4283.45 '), virtual('155.0.4283.45.'),
    virtual('155.0.70000.45'), virtual('70000.0.4283.45'),
    virtual(resource='edge_pdf'), virtual(resource='edge_clipboard.evil'),
    virtual().replace('EdgeWebView', 'EdgeWebView-lookalike'),
    virtual().replace('resources', 'Resources-lookalike'),
    virtual() + '\\extra', virtual() + ':stream',
    virtual().replace('\\resources\\', '\\resources\\..\\resources\\'),
    'resources\\edge_clipboard', '\\\\server\\share\\resources\\edge_clipboard',
    'C:\\Users\\synthetic\\155.0.4283.45\\resources\\edge_clipboard',
    virtual('SetupMetrics'),
])
def test_inexact_unsupported_future_and_foreign_paths_fail_closed(probe, path):
    assert not probe('predicate', location=5, path=path, active=ACTIVE, resource='edge_clipboard')['accepted']


def test_unknown_resource_is_not_authorized(probe):
    assert not probe('predicate', location=5, path=virtual(resource='evil'), active=ACTIVE, resource='evil')['accepted']


def test_retained_old_runtime_has_real_protected_signed_proof(probe):
    image = Path(OLDER) / 'msedgewebview2.exe'
    if not image.is_file():
        pytest.skip('Exact previously supported Runtime155.0.4283.45 no longer retained; missing-old-runtime refusal remains covered')
    before = hashlib.sha256(image.read_bytes()).hexdigest()
    result = probe('historical', active=ACTIVE, path=OLDER)
    assert result['accepted'], result
    assert result['pins'] >= 7, 'Historical directory chain and image must remain pinned through verification'
    assert hashlib.sha256(image.read_bytes()).hexdigest() == before


def test_removed_old_runtime_uses_strict_protected_namespace_without_reset(probe):
    missing = str(FAMILY / '155.0.4283.46')
    assert not Path(missing).exists(), 'Choose an actually absent synthetic version, never remove a Runtime'
    result = probe('historical', active=ACTIVE, path=missing)
    assert result['accepted'] and result['pins'] == len(FAMILY.parents) + 1, result
    assert not Path(missing).exists(), 'No historical Runtime may be recreated'


def test_user_owned_runtime_and_reparse_root_are_refused(probe, tmp_path):
    folder = tmp_path / '155.0.4283.45'; folder.mkdir()
    result = probe('protected', active=ACTIVE, path=str(folder), directory=True)
    assert not result['accepted'] and 'not system-owned' in result['message']
    link = tmp_path / 'runtime-link'
    subprocess.run(['cmd.exe', '/c', 'mklink', '/J', str(link), str(folder)], check=True, capture_output=True)
    try:
        result = probe('protected', active=ACTIVE, path=str(link), directory=True)
        assert not result['accepted'] and 'reparse' in result['message']
    finally:
        link.rmdir()


def test_runtime_image_version_and_signature_are_not_inferred_from_path(probe, tmp_path):
    image = Path(OLDER) / 'msedgewebview2.exe'
    if image.is_file():
        result = probe('signature', path=str(image), version='155.0.4283.60')
        assert not result['accepted'] and 'version' in result['message']
    source = tmp_path / 'Unsigned.cs'
    source.write_text('using System.Reflection;[assembly:AssemblyFileVersion("155.0.4283.45")]class Unsigned { static void Main() {} }')
    unsigned = tmp_path / 'msedgewebview2.exe'
    subprocess.run(probe.compiler + ['/target:exe', '/out:' + str(unsigned), str(source)],
                   check=True, capture_output=True, timeout=30)
    result = probe('signature', path=str(unsigned), version='155.0.4283.45')
    assert not result['accepted'] and 'Authenticode' in result['message'], result
    result = probe('signature', path=str(tmp_path / 'missing.exe'), version='155.0.4283.45')
    assert not result['accepted'], result


@pytest.mark.parametrize('rights', ['WriteData', 'AppendData', 'WriteExtendedAttributes', 'WriteAttributes',
                                    'Delete', 'DeleteSubdirectoriesAndFiles', 'ChangePermissions', 'TakeOwnership'])
def test_old_version_root_rejects_untrusted_write_acl_including_child_creation(probe, rights):
    result = probe('acl', owner='S-1-5-32-544', sid='S-1-1-0', rights=rights, ancestor=False)
    assert not result['accepted'] and 'untrusted writes' in result['message']


def test_ancestor_creation_exception_is_not_the_old_version_root_policy(probe):
    assert probe('acl', owner='S-1-5-32-544', sid='S-1-1-0', rights='WriteData', ancestor=True)['accepted']
    assert not probe('acl', owner='S-1-5-32-544', sid='S-1-1-0', rights='WriteData', ancestor=False)['accepted']
    assert probe('acl', owner='S-1-5-18', sid='S-1-5-32-544', rights='FullControl', ancestor=False)['accepted']
    assert probe('acl', owner='S-1-5-32-544', sid='S-1-1-0', rights='ReadAndExecute', ancestor=False)['accepted']
    assert not probe('acl', owner='S-1-1-0', sid='S-1-5-18', rights='FullControl', ancestor=False)['accepted']


@pytest.mark.parametrize('filename', ['Preferences', 'Secure Preferences'])
def test_real_component_metadata_reader_accepts_old_and_current_bound_resources(probe, tmp_path, filename):
    if not (Path(OLDER) / 'msedgewebview2.exe').is_file():
        pytest.skip('Exact protected supported Runtime155.0.4283.45 no longer retained')
    path = tmp_path / filename
    body = {'extensions': {'settings': {
        'dgiklkfkllikcanfonkcabmbdfmgleag': {'location': 5, 'path': virtual()},
        'mhjfbmdgcfjbbpaeojofohoefgiehjai': {'location': 5, 'path': virtual('155.0.4283.60', 'edge_pdf')},
    }}}
    path.write_text(json.dumps(body), encoding='utf-8')
    before = path.read_bytes()
    result = probe('metadata', path=str(path), active=ACTIVE)
    assert result['accepted'] and result['pins'] >= 7, result
    assert path.read_bytes() == before, 'Validation must never rewrite component metadata'


@pytest.mark.parametrize('value', [None, {}, {'location': '5', 'path': virtual()},
                                 {'location': 5, 'path': virtual(resource='edge_pdf')},
                                 {'location': 5, 'path': virtual('155.0.4283.44')}])
def test_real_component_metadata_reader_fails_closed_without_mutation(probe, tmp_path, value):
    path = tmp_path / 'Secure Preferences'
    path.write_text(json.dumps({'extensions': {'settings': {'dgiklkfkllikcanfonkcabmbdfmgleag': value}}}), encoding='utf-8')
    before = path.read_bytes()
    result = probe('metadata', path=str(path), active=ACTIVE)
    assert not result['accepted'], result
    assert path.read_bytes() == before


@pytest.mark.parametrize('filename', ['Preferences', 'Secure Preferences'])
def test_removed_runtime_metadata_is_accepted_without_rewriting_selected_bytes(probe, tmp_path, filename):
    missing = str(FAMILY / '155.0.4283.46')
    assert not Path(missing).exists()
    path = tmp_path / filename
    path.write_text(json.dumps({'extensions': {'settings': {
        'dgiklkfkllikcanfonkcabmbdfmgleag': {'location': 5, 'path': virtual('155.0.4283.46')},
        'mhjfbmdgcfjbbpaeojofohoefgiehjai': {'location': 5, 'path': virtual('155.0.4283.46', 'edge_pdf')},
    }}}), encoding='utf-8')
    before = path.read_bytes()
    result = probe('metadata', path=str(path), active=ACTIVE)
    assert result['accepted'] and result['pins'] == len(FAMILY.parents) + 1, result
    assert path.read_bytes() == before
    assert not Path(missing).exists()


def test_missing_old_runtime_cannot_be_attested_under_user_writable_family(probe, tmp_path):
    family=tmp_path/'Application';family.mkdir()
    result=probe('historical', active=str(family/'155.0.4283.60'), path=str(family/'155.0.4283.46'))
    assert not result['accepted'] and 'not system-owned' in result['message'], result


def test_old_runtime_family_must_equal_active_family(probe, tmp_path):
    result=probe('historical', active=ACTIVE, path=str(tmp_path/'155.0.4283.46'))
    assert not result['accepted'] and 'escaped' in result['message'], result


def test_missing_image_and_wrong_type_are_distinct_from_missing_directory(probe, tmp_path):
    missing=tmp_path/'msedgewebview2.exe'
    assert probe('missing',path=str(missing),directory=False)['value'] is True
    missing.mkdir()
    assert not probe('missing',path=str(missing),directory=False)['accepted']
    assert probe('missing',path=str(missing),directory=True)['value'] is False


def test_image_free_sibling_requires_the_same_strict_directory_proof(probe):
    # Its ACL is host-dependent. On the qualification host it permits untrusted
    # writes, so it must be rejected; no system permission is changed for a pass.
    directory=FAMILY/'SetupMetrics'
    if not directory.is_dir() or (directory/'msedgewebview2.exe').exists():
        pytest.skip('Existing protected image-free sibling unavailable; no system fixture is created')
    result=probe('historical',active=ACTIVE,path=str(directory))
    strict=probe('protected',active=ACTIVE,path=str(directory),directory=True)
    assert result['accepted'] == strict['accepted'], (result,strict)
    if not strict['accepted']:
        assert result['message'] == strict['message'], (result,strict)


def test_strict_retained_version_proof_and_missing_image_lookup_without_system_mutation(probe):
    directory=Path(OLDER)
    if not directory.is_dir():
        pytest.skip('Protected historical version no longer present; absence path remains separately covered')
    proof=probe('protected',active=ACTIVE,path=str(directory),directory=True)
    assert proof['accepted'] and proof['pins']==len(directory.parents)+1,proof
    missing=directory/'dlms-preview-absent-image-control.exe'
    assert not missing.exists()
    assert probe('missing',path=str(missing),directory=False)['value'] is True
    assert not missing.exists(), 'No system fixture may be created'
