"""Run production installer path guards without activating an installer.

The generated no-payload executable exits from InitializeSetup before setup.
ACL descriptors exist only in memory; no host ACL, owner, settings or profile is
changed. A test-only CreateDirectory adapter exercises the create race refusal.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / '.gate1/windows-native'


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def literal(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def directory_sddl(path: Path) -> str:
    import ctypes as c
    from ctypes import wintypes as w
    api = c.WinDLL('advapi32', use_last_error=True)
    kernel = c.WinDLL('kernel32', use_last_error=True)
    get = api.GetNamedSecurityInfoW
    get.argtypes = [w.LPWSTR, w.DWORD, w.DWORD, *([c.POINTER(c.c_void_p)] * 5)]
    get.restype = w.DWORD
    convert = api.ConvertSecurityDescriptorToStringSecurityDescriptorW
    convert.argtypes = [c.c_void_p, w.DWORD, w.DWORD, c.POINTER(w.LPWSTR), c.POINTER(w.DWORD)]
    convert.restype = w.BOOL
    free = kernel.LocalFree
    free.argtypes = [c.c_void_p]
    free.restype = c.c_void_p
    owner, group, dacl, sacl, descriptor = [c.c_void_p() for _ in range(5)]
    error = get(str(path), 1, 7, *(c.byref(x) for x in (owner, group, dacl, sacl, descriptor)))
    if error:
        raise c.WinError(error)
    text, size = w.LPWSTR(), w.DWORD()
    try:
        if not convert(descriptor, 1, 7, c.byref(text), c.byref(size)):
            raise c.WinError(c.get_last_error())
        try:
            return text.value
        finally:
            free(c.cast(text, c.c_void_p))
    finally:
        free(descriptor)


def fresh_scope(requested: Path) -> Path:
    from desktop.windows_files import assert_path
    # Check the lexical path before resolving: resolution must not hide a
    # junction, traversal alias or unsafe existing prefix from assert_path.
    candidate = requested.absolute()
    assert_path(candidate)
    work = WORK.resolve(strict=True)
    out = candidate.resolve(strict=False)
    assert_path(out)
    if not out.is_relative_to(work) or out == work or out.exists():
        raise ValueError('A fresh project-local scope is required')
    return out


def production_code(source: str) -> str:
    code = source.split('[Code]\n', 1)[1]
    declaration = "function CreatePrivateDirectory(Name: String; Security: NativeUInt): Boolean;"
    assert code.count(declaration) == 1
    code = code.replace(declaration, declaration.replace('CreatePrivateDirectory', 'RawCreatePrivateDirectory'))
    adapter = '''var RaceTarget: String;
function CreatePrivateDirectory(Name: String; Security: NativeUInt): Boolean;
begin
  if (RaceTarget <> '') and (CompareText(Name, RaceTarget) = 0) then begin
    RaceTarget := '';
    { Simulate another creator winning immediately before the real syscall. }
    RawCreatePrivateDirectory(Name, Security);
  end;
  Result := RawCreatePrivateDirectory(Name, Security);
end;

'''
    marker = 'function SidString(Sid: NativeUInt): String;'
    assert code.count(marker) == 1
    return code.replace(marker, adapter + marker)


def probe_script(source: str, out: Path, real_parent: Path) -> str:
    return fr'''#define Release "guard-probe-only"
[Setup]
AppName=DLMS path guard non-installing probe
AppVersion=1
DefaultDirName={out / 'never-installed'}
CreateAppDir=no
Uninstallable=no
CreateUninstallRegKey=no
PrivilegesRequired=lowest
ArchitecturesAllowed=x64os
ArchitecturesInstallIn64BitMode=x64os
OutputDir={out}
OutputBaseFilename=path-guard-probe
Compression=none
DisableStartupPrompt=yes
[Code]
{production_code(source)}
function ParseDescriptor(Text: String; Revision: LongWord; var Descriptor: NativeUInt;
  Size: NativeUInt): Boolean;
  external 'ConvertStringSecurityDescriptorToSecurityDescriptorW@advapi32.dll stdcall';
function DescriptorOwner(Descriptor: NativeUInt; var Owner: NativeUInt;
  var Defaulted: LongWord): Boolean;
  external 'GetSecurityDescriptorOwner@advapi32.dll stdcall';
function DescriptorDacl(Descriptor: NativeUInt; var Present: LongWord;
  var Dacl: NativeUInt; var Defaulted: LongWord): Boolean;
  external 'GetSecurityDescriptorDacl@advapi32.dll stdcall';
function NativeMove(OldName, NewName: String; Flags: LongWord): Boolean;
  external 'MoveFileExW@kernel32.dll stdcall';
function RestrictedToken(Token: THandle): Boolean;
  external 'IsTokenRestricted@advapi32.dll stdcall';
function ElevationInformation(Token: THandle; Kind: Integer; var Elevated: LongWord;
  Size: LongWord; var Needed: LongWord): Boolean;
  external 'GetTokenInformation@advapi32.dll stdcall';
var Rows: String; Failures: Integer;
procedure AccessDiagnostic(Name: String; Descriptor: NativeUInt);
var Token, Duplicate: THandle; Mapping: TDirectoryMapping;
    Privileges: TPrivilegeBuffer; Size, Granted, AccessStatus: LongWord;
    Ok: Boolean;
begin
  Ok := OpenToken(CurrentProcess, 10, Token);
  Rows := Rows + 'diagnostic|' + Name + '|open=' + IntToStr(Ord(Ok)) + '|error=' + IntToStr(NativeLastError) + #13#10;
  if not Ok then Exit;
  try
    Rows := Rows + 'diagnostic|' + Name + '|restricted=' + IntToStr(Ord(RestrictedToken(Token))) + '|sid=' + CurrentSid + #13#10;
    Ok := DuplicateAccessToken(Token, 2, Duplicate);
    Rows := Rows + 'diagnostic|' + Name + '|duplicate=' + IntToStr(Ord(Ok)) + '|error=' + IntToStr(NativeLastError) + #13#10;
    if not Ok then Exit;
    try
      Mapping.ReadAccess := $120089; Mapping.WriteAccess := $120116;
      Mapping.ExecuteAccess := $1200A0; Mapping.AllAccess := $1F01FF;
      Size := SizeOf(Privileges); Granted := 0; AccessStatus := 0;
      Ok := NativeAccessCheck(Descriptor, Duplicate, 4, Mapping, Privileges, Size, Granted, AccessStatus);
      Rows := Rows + 'diagnostic|' + Name + '|check=' + IntToStr(Ord(Ok)) + '|error=' + IntToStr(NativeLastError) + '|granted=' + IntToStr(Granted) + '|status=' + IntToStr(AccessStatus) + '|size=' + IntToStr(Size) + #13#10;
    finally CloseNative(Duplicate); end;
  finally CloseNative(Token); end;
end;
procedure Check(Name: String; Actual, Expected: Boolean);
begin
  Rows := Rows + Name + '|' + IntToStr(Ord(Actual)) + '|' + IntToStr(Ord(Expected)) + #13#10;
  if Actual <> Expected then Failures := Failures + 1;
end;
procedure DescriptorCase(Name, Text: String; Parent, Expected: Boolean);
var Descriptor, Owner, Dacl: NativeUInt; Present, Defaulted: LongWord;
begin
  if not ParseDescriptor(Text, 1, Descriptor, 0) then begin
    Check(Name + '-descriptor-parse', False, True); Exit;
  end;
  try
    if not DescriptorOwner(Descriptor, Owner, Defaulted) or
       not DescriptorDacl(Descriptor, Present, Dacl, Defaulted) then begin
      Check(Name + '-descriptor-read', False, True); Exit;
    end;
    Check(Name, DirectorySecurityAllowed(Owner, Dacl, Descriptor, Parent), Expected);
    if Parent then AccessDiagnostic(Name, Descriptor);
  finally FreeNative(Descriptor); end;
end;
procedure RunCases;
var Trusted, Prefix, Path, Parent, Moved: String; N: Integer; H: THandle;
    Elevated, Needed: LongWord;
begin
  if not InitializeGuard then RaiseException('Guard initialization failed');
  if not OpenToken(CurrentProcess, 8, H) then RaiseException('Token query failed');
  try
    if not ElevationInformation(H, 20, Elevated, SizeOf(Elevated), Needed) then
      RaiseException('Elevation query failed');
    Check('normal-non-elevated-token', Elevated <> 0, False);
    Check('normal-non-restricted-token', RestrictedToken(H), False);
  finally CloseNative(H); end;
  Trusted := '(A;;FA;;;' + CurrentSid + ')(A;;FA;;;SY)(A;;FA;;;BA)';
  Prefix := 'O:BAG:BAD:';
  DescriptorCase('admin-parent-user-system-admin-full', Prefix + Trusted, True, True);
  DescriptorCase('admin-parent-not-an-app-root', Prefix + Trusted, False, False);
  DescriptorCase('user-owned-app-root', 'O:' + CurrentSid + 'G:BAD:' + Trusted, False, True);
  DescriptorCase('missing-group-fails-access-check', 'O:BAD:' + Trusted, True, False);
  DescriptorCase('admin-parent-no-effective-create', Prefix + '(A;;FR;;;' + CurrentSid + ')(A;;FA;;;SY)(A;;FA;;;BA)', True, False);
  DescriptorCase('admin-parent-explicit-create-deny', Prefix + '(D;;0x4;;;' + CurrentSid + ')' + Trusted, True, False);
  DescriptorCase('unknown-owner', 'O:S-1-5-21-1-2-3-999G:BAD:' + Trusted, True, False);
  DescriptorCase('system-owner-not-parent-exception', 'O:SYG:BAD:' + Trusted, True, False);
  DescriptorCase('null-dacl', 'O:BAG:BAD:NO_ACCESS_CONTROL', True, False);
  DescriptorCase('empty-dacl', Prefix, True, False);
  DescriptorCase('everyone-file-write', Prefix + Trusted + '(A;;0x2;;;WD)', True, False);
  DescriptorCase('everyone-child-create', Prefix + Trusted + '(A;;0x4;;;WD)', True, False);
  DescriptorCase('everyone-delete', Prefix + Trusted + '(A;;0x10000;;;WD)', True, False);
  DescriptorCase('everyone-write-dacl', Prefix + Trusted + '(A;;0x40000;;;WD)', True, False);
  DescriptorCase('everyone-write-owner', Prefix + Trusted + '(A;;0x80000;;;WD)', True, False);
  DescriptorCase('inheritable-only-untrusted-create', Prefix + Trusted + '(A;OICIIO;0x4;;;WD)', True, False);
  DescriptorCase('untrusted-read-only', Prefix + Trusted + '(A;;FR;;;WD)', True, True);
  DescriptorCase('deny-does-not-grant-write', Prefix + '(D;;0x2;;;WD)' + Trusted, True, True);
  Parent := {literal(real_parent)};
  Check('real-programs-safe-creation-parent', SafeCreationParent(Parent), True);
  N := PinnedPaths.IndexOf(Lowercase(Parent));
  Check('real-programs-pinned', N >= 0, True);
  if N >= 0 then Check('real-programs-not-current-user-owned', OwnedDirectory(Pins[N]), False);
  ReleasePins;
  Path := {literal(out / 'nested new 日本語' / 'child')};
  Check('nested-private-directory-create', EnsurePrivateDirectory(Path), True);
  Check('nested-created-current-user-owned', PinDirectory(Path, True), True);
  Moved := Path + '.moved';
  Check('pinned-directory-rename-refused', NativeMove(NativeLocalPath(Path), NativeLocalPath(Moved), 0), False);
  Check('pinned-directory-rename-sharing-error', NativeLastError = 32, True);
  ReleasePins;
  Check('same-directory-rename-after-release', NativeMove(NativeLocalPath(Path), NativeLocalPath(Moved), 0), True);
  Check('rename-restored-after-release', NativeMove(NativeLocalPath(Moved), NativeLocalPath(Path), 0), True);
  Path := {literal(out / 'race-created')};
  RaceTarget := NativeLocalPath(Path);
  Check('racing-creator-is-not-adopted', EnsurePrivateDirectory(Path), False);
  Check('racing-creator-fixture-exists', DirExists(Path), True);
  ReleasePins;
  Check('junction-chain-refused', SafeDirectoryChain({literal(out / 'junction')}), False);
  ReleasePins;
  Check('junction-create-refused', EnsurePrivateDirectory({literal(out / 'junction' / 'child')}), False);
  ReleasePins;
  Check('reject-relative', NativeLocalPath('relative\path') <> '', False);
  Check('reject-unc', NativeLocalPath('\\server\share\child') <> '', False);
  Check('reject-device-prefix', NativeLocalPath('\\?\C:\child') <> '', False);
  Check('reject-ads', NativeLocalPath('C:\child:stream') <> '', False);
  Check('reject-traversal', NativeLocalPath('C:\safe\..\child') <> '', False);
  Check('reject-trailing-dot', NativeLocalPath('C:\safe\child.') <> '', False);
  Check('reject-reserved', NativeLocalPath('C:\safe\CON.txt') <> '', False);
end;
function InitializeSetup: Boolean;
begin
  Result := False;
  Rows := ''; Failures := 0;
  try
    RunCases;
  except
    Rows := Rows + 'exception|' + GetExceptionMessage + #13#10;
    Failures := Failures + 1;
  end;
  ReleasePins;
  Rows := Rows + 'failures|' + IntToStr(Failures) + #13#10;
  SaveStringToFile({literal(out / 'cases.txt')}, Rows, False);
  {{ ALWAYS abort before wizard, files, registry, icons or uninstall actions. }}
end;
'''


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    out = fresh_scope(args.output)
    source_path = ROOT / 'package_windows_webview2/installer.iss'
    source = source_path.read_text(encoding='utf-8')
    # CPython 3.14 on Windows applies 0700 at this new directory's creation.
    # Never alter any existing directory ACL (especially host Programs).
    out.mkdir(mode=0o700)
    fixture_acl = directory_sddl(out)
    outside = out / 'junction target'
    outside.mkdir()
    (outside / 'sentinel.txt').write_bytes(b'unchanged synthetic evidence')
    subprocess.run(['cmd.exe', '/c', 'mklink', '/J', str(out / 'junction'), str(outside)],
                   check=True, capture_output=True)
    # The real Programs parent is inspected but no child is created there.
    from desktop.windows_processes import default_data_root
    real_parent = default_data_root().parent.parent / 'Programs'
    script = out / 'probe.iss'
    script.write_text(probe_script(source, out, real_parent), encoding='utf-8-sig')
    compiler = WORK / 'inno-portable/ISCC.exe'
    temp = out / 'private temp'
    temp.mkdir()
    environment = dict(os.environ, TEMP=str(temp), TMP=str(temp))
    build = subprocess.run([str(compiler), str(script)], capture_output=True, text=True, timeout=60,
                           env=environment)
    (out / 'compile.log').write_text(build.stdout + build.stderr, encoding='utf-8')
    if build.returncode:
        raise RuntimeError(f'Probe compilation failed: {out / "compile.log"}')
    exe = out / 'path-guard-probe.exe'
    run = subprocess.run([str(exe), '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART',
                          '/LOG=' + str(out / 'probe.log')], timeout=60, env=environment)
    rows = (out / 'cases.txt').read_text(encoding='utf-8-sig').splitlines()
    result = {'production_installer_sha256': sha(source_path), 'generated_probe_sha256': sha(script),
              'probe_exe_sha256': sha(exe), 'compiler_sha256': sha(compiler),
              'exit_code': run.returncode, 'real_parent': str(real_parent), 'cases': rows,
              'new_fixture_root_sddl': fixture_acl,
              'no_payload': True, 'initialize_setup_always_false': True,
              'acl_fixtures_in_memory_only': True, 'create_race_adapter_test_only': True,
              'normal_installer_activated': False, 'existing_acl_changed': False}
    assert (outside / 'sentinel.txt').read_bytes() == b'unchanged synthetic evidence'
    assert not (outside / 'child').exists()
    assert not (out / 'never-installed').exists()
    (out / 'result.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    assert rows[-1] == 'failures|0', rows
    assert source_path.read_text(encoding='utf-8') == source, 'Source changed during probe'
    print(f'Production non-installing path guard probe passed: '
          f'{sum(not row.startswith("diagnostic|") for row in rows) - 1} cases')


if __name__ == '__main__':
    main()
