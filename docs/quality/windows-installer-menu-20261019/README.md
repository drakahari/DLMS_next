# Windows installer: explicit profile and optional Start menu

Base: `2107e5cffc787705dfbbb495995655ebd504dedd`.
Installer-only correction on `fix/windows-installer-safe-menu-opt-out`;
application payload, Avery printing, dependencies, runtime and canonical icon
remain unchanged. The correction itself changed no host installation or ACL.
Subsequent owner-authorized actual-host acceptance is recorded below.

## Behavior

- Additional Tasks offers **Install without Start menu entries**, unchecked on
  every setup run. Setup never silently selects this option after a guard
  failure. It skips both Start menu launch and uninstall entries. Existing menu
  entries are left unchanged and may still launch an earlier version.
- Setup distinguishes an unsafe/inaccessible/reparse creation parent (showing
  the actual nearest existing parent) from an invalid/unsafe existing shortcut.
  The latter still cannot be overwritten by the menu-enabled path.
- The profile page requires a valid exact profile name and explicit checkbox
  confirmation. A safely captured existing launcher can suggest a profile; an
  unsafe menu cannot. New/reinstalled setups have no implicit default. Enter
  `fresh-20261017` to reuse that profile; enter `default` only deliberately.
  Silent setup requires `/DLMSPROFILE=the-name`, including on upgrades.
- Every successful installation creates **Launch DLMS Desktop.lnk** in the
  guarded installation root. Its target, working folder and `--profile` bind to
  this installation/version and the confirmed profile. Open this shortcut in
  File Explorer; no Start menu location or unsafe parent is required. The usual
  root is `%LOCALAPPDATA%\Programs\DLMS Desktop WebView2 Candidate`.
- Windows **Installed apps** and `{app}\uninstall\unins000.exe` remain supported
  uninstall paths without a Start menu entry. Automatic launch and the optional
  desktop shortcut remain unchecked. A valid existing optional desktop
  shortcut keeps its separately captured profile; a new one uses the confirmed
  profile. Its own guards still apply when selected.
- Opt-out does not erase earlier Inno uninstall ownership records: an update
  leaves old menu entries untouched, but subsequent uninstall still removes
  entries owned by earlier menu-enabled installations. The separate never-owned
  synthetic menu entry remained unchanged; historical installer-owned paths
  retain Inno's existing uninstall semantics. This was checked in isolation.

No capability SID is trusted or whitelisted. The ACL/ownership/path/reparse
guard functions are byte-identical to the base. No parent ACL, inheritance,
security setting, profile, server or credential is altered.

## Focused evidence

Source tests: 14 passed, covering exact unchanged guard code, icon task gating,
explicit profile requirement, silent validation, accurate diagnostics, isolated
registry scope and installer bindings. The existing packaging test expected a
preprocessor marker absent even at the unchanged base; its assertion now checks
the actual stronger TestScope/normal registry branches.

Native installer driver: 14 cases passed using tiny inert TestScope payloads
(never executed), real shortcut files and new synthetic directories whose
initial ACLs reproduce the two rejecting capability ACEs. Fresh install,
upgrade and reinstall after uninstall work with explicit no-menu/profile
selection. Missing/invalid profiles fail; an invalid old target has a separate
refusal; existing unsafe menu bytes stay unchanged. Ordinary safe-menu fresh
and upgrade paths work. Synthetic data and both parent descriptors are
unchanged. No normal registry or shell integration was activated.

An initial new-code silent-validation message box caused a bounded timeout.
The log was preserved; the exact surviving inert worker was identified and
stopped. Silent callbacks now defer validation to PrepareToInstall, and the
complete corrected matrix passed. This is not a passing run by inference from
cleanup. No owner UI/checkbox/focus acceptance or application workflow run is
claimed. Existing runtime/workflow/printing acceptance is reused.

Focused commands:

```powershell
python -B -X utf8 -m pytest -q -p no:cacheprovider --basetemp=.gate1/windows-native/menu-policy-pytest-02 tests/webview2/test_installer_menu_policy.py tests/webview2/test_installer_parent.py tests/webview2/test_installer_upgrade.py tests/webview2/test_packaging.py::test_installer_has_distinct_identity_and_no_prerequisite_install_or_data_delete
python -B -X utf8 -m tests.webview2.installer_menu_policy --output .gate1/windows-native/menu-policy-native-02
```

## Release handling proposal

Preserve the existing Preview 2 release/tag and every asset unchanged. After
source review/integration and separate publication approval, publish a clearly
identified installer revision with its exact installer-only source patch,
provenance and updated checksums. Application source/notices companions can be
reused byte-for-byte because the application payload is unchanged; the revised
installer source must accompany the new installer. Do not advertise the old
application source ZIP alone as the complete revised installer source.

This record does not authorize publication or another installation. Reusing an
existing profile requires explicitly confirming its exact name; setup must not
infer a profile from an unsafe shortcut. The later owner-authorized installation
deliberately selected a fresh Local profile instead of reusing `fresh-20261017`.

## Actual-host shipping-installer acceptance

The owner subsequently authorized and completed the actual unsigned Preview 2.1
installer on Windows 11, choosing **Install without Start menu entries** and
explicitly confirming the fresh Local profile `local-preview21-01`. The supported
application-folder launcher opened that same profile before and after a normal
close/reopen. All 6,987 installed payload files matched; saved directory owners
and security descriptors were unchanged. No application or installer rebuild was
needed. This supersedes the earlier shipping-UI environment blocker; it does not
turn the earlier inert TestScope cases into shipping-installer evidence.

See [actual-host acceptance and exact artifact binding](HOST_ACCEPTANCE.md) for
results, launch location, evidence boundaries and retained limitations. Publication
remains paused pending separate authorization.
