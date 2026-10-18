# Windows native build and bounded safety qualification

Build the same pinned application tree as Linux; do not port Qt transport code blindly into WebView2 or incorporate an unfinished Windows branch. This handoff authorizes no installation, runtime architecture change, security exception or release. The Fedora audit is complete and is inherited shared evidence, not a Windows native pass.

## Exact source and current boundary

- Shared runtime: `bfdffb720f743e9d720cd07292ec7e1ec325e059`.
- Full build source: `4b50e2b3fb39dd478d355bf785b319805579076c` on `docs/workflow-recovery-audit-20261018`, repository `https://github.com/drakahari/DLMS_next`.
- Handoff/fixture preparation: branch `build/linux-safety-candidate-20261018`, the exact Git commit containing this handoff (record the fetched head). Later preparation files are documentation/fixtures only; record them separately from runtime/build source.
- Linux comparison identity: `linux-330-safety-20261018`, AppImage SHA **af46249a70520c2f5374419ccf7760aabee230887cc4eacaee2e02e74c12b9a5**. Windows must produce its own native manifest, dependency inventory, SHA-256 and About identity; no Windows artifact exists for this handoff.
- Canonical application: root `app.py`, `dlms/`, `templates/`, `static/`, `init.sql`, `tests/`, `tools/`. No active `source/` copy.
- Windows host/adapters: `windows_webview2/`, `package_windows_webview2/`, `package_windows/`, `desktop/windows_*.py`. Linux Qt/OpenURI and Darwin paths must remain unchanged. The separate historical uninstalled Windows repair `0fbd31ce162d93c847f54d8b868ca007c370b308` is not authority to merge unrelated runtime changes.

Fetch the handoff branch only to read its documentation/fixtures, then create the Windows build branch at the exact source commit. Preserve unrelated working changes rather than resetting them. In a new checkout:

```powershell
$ErrorActionPreference = 'Stop'
$checkout = Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'DLMS-safety-source-20261018'
if (Test-Path -LiteralPath $checkout) { throw 'Preserve existing checkout; choose a fresh directory.' }
git clone --single-branch --branch build/linux-safety-candidate-20261018 https://github.com/drakahari/DLMS_next.git $checkout
if ($LASTEXITCODE -ne 0) { throw 'Clone failed.' }
Set-Location $checkout
git merge-base --is-ancestor 4b50e2b3fb39dd478d355bf785b319805579076c HEAD
if ($LASTEXITCODE -ne 0) { throw 'Handoff branch does not contain pinned build source.' }
git rev-parse HEAD
$visible = Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'DLMS safety Windows fixtures 20261018'
if (Test-Path -LiteralPath $visible) { throw 'Preserve existing fixtures.' }
New-Item -ItemType Directory -Path $visible | Out-Null
Copy-Item -LiteralPath 'docs/platform-candidate-20261018/fixtures' -Destination (Join-Path $visible 'inputs') -Recurse
git switch --create feature/windows-safety-candidate-20261018 4b50e2b3fb39dd478d355bf785b319805579076c
if ($LASTEXITCODE -ne 0) { throw 'Pinned build branch creation failed.' }
if ((git rev-parse HEAD).Trim() -ne '4b50e2b3fb39dd478d355bf785b319805579076c') { throw 'Build source mismatch.' }
if (git status --porcelain) { throw 'Build source must be clean.' }
```

Verify every supplied fixture against its SHA256SUMS before use, using `Get-FileHash -Algorithm SHA256`; stop on mismatch. Fixtures contain synthetic choice questions, an original hotspot pack and OCR images/PDF only. No prebuilt APKG, personal data, profile or backup is supplied. The expected neutral answer order is B,C,A,B. Keep selectable files and resulting exports under the ordinary Documents folder above.

## Existing build entry points; prerequisites first

Use native Windows 11 x86-64, isolated verified **CPython 3.14.7**, current unmodified `package_windows/requirements-build-lock.txt` and `package_windows_webview2/requirements-build-lock.txt`. Host prerequisites are .NET Framework 4.8 compiler/runtime and a supported protected machine Microsoft WebView2 Evergreen runtime. Do not install a runtime or modify ACLs/security to force a pass. WebView2 SDK `1.0.4258.31` is pinned by `windows_webview2/build.ps1`, SHA-256 `56f7f4b8bf9aee4b8efefbbdd4f67d5f74ebd1b100ed0806da71bf76af481aa9`.

The existing reproducible build recipe is [BUILD_AND_REPLACEMENT.md](../windows-preview/BUILD_AND_REPLACEMENT.md). Its historical source IDs and release names describe earlier binaries, not this candidate. Reuse verified dependency inputs read-only where their hashes match. Recipient-local prerequisites must be populated before the following commands: isolated interpreter, hash-verified SDK archive/extracted SDK at `.gate1/windows-native/webview2-inputs-01`, verified native/OCR source cache, and recipient-specific preview materials. `package_windows/prepare_python.py` and `acquire_inputs.py` download explicitly pinned inputs but do not grant permission to install host tools. No private producer cache is assumed downloadable.

From the pinned source checkout, after setting the four explicit verified-input paths below to actual existing directories, use the current supported commands. These placeholders are required recipient inputs, not hidden dependencies to invent:

```powershell
$ErrorActionPreference = 'Stop'
$buildPython = 'C:\ABSOLUTE\verified-isolated-python\python.exe'
$verifiedNativeProducerArchiveCache = 'C:\ABSOLUTE\verified-native-producer-archives'
$previewMaterials = 'C:\ABSOLUTE\verified-windows-preview-materials'
if (!(Test-Path -LiteralPath $buildPython -PathType Leaf)) { throw 'Missing verified interpreter.' }
if (!(Test-Path -LiteralPath $verifiedNativeProducerArchiveCache -PathType Container)) { throw 'Missing native inputs.' }
if (!(Test-Path -LiteralPath $previewMaterials -PathType Container)) { throw 'Missing source/notices materials.' }
& $buildPython -m pip check
if ($LASTEXITCODE -ne 0) { throw 'Dependency check failed.' }
& $buildPython -B tools/check_release_dependencies.py
if ($LASTEXITCODE -ne 0) { throw 'Release dependency preflight failed.' }
& .\windows_webview2\build.ps1 -BuildName webview2-host-candidate-18
& $buildPython -m package_windows_webview2.build --release windows-330-safety-20261018 --host-build webview2-host-candidate-18 --native-packages $verifiedNativeProducerArchiveCache --preview-materials $previewMaterials
if ($LASTEXITCODE -ne 0) { throw 'Preserve failed output; do not relabel it qualified.' }
```

Choose a different unused bounded host number only if `18` already exists; never overwrite its evidence. The material assembly command and exact source-index inputs are in the linked build document and `package_windows_webview2/assemble_preview_materials.py`. Existing source/notice archives can be reused only if inputs match; regenerate this candidate's application-source manifest/provenance. Keep dependencies pinned. The builder is intentionally fail-closed; missing matching material is a concrete prerequisite to report, not a reason to omit it.

Run affected native/shared tests only, such as the selected changed feature tests and `tests/windows/ci_adapter_contracts.py` / `tests/webview2/` paths appropriate to the adapter. Inspect their prerequisites rather than treating native skips as passes. Existing broad shared CI and the bounded Fedora audit are reused; do not repeat the whole workflow audit. Keep any instrumented host separate; the normal build above omits `--instrumented` and `-AiRaceProbe`.

## Isolated ordinary launch and reopen

Keep the complete frozen folder together. Use an explicit **fresh, private, marked** data root outside the payload. `package_windows.entry.root_path` refuses existing unmarked roots by design; changing `LOCALAPPDATA` alone does not redirect the Known Folder default. Do not bypass it. The following uses the pinned build environment's existing adapter to create only a new synthetic root with its normal marker, then runs the normal executable. Set `$normalExe` to the actual new build's inventoried executable, not an installed executable.

```powershell
$normalExe = 'C:\ABSOLUTE\new-candidate\DLMS-Desktop-WebView2.exe'
$reviewRoot = Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'DLMS safety Windows data 20261018'
if (Test-Path -LiteralPath $reviewRoot) { throw 'Preserve existing data; choose a fresh namespace.' }
& $buildPython -c 'import sys; from package_windows.entry import root_path; root_path(sys.argv[1],create=True)' $reviewRoot
if ($LASTEXITCODE -ne 0) { throw 'Synthetic root preparation failed.' }
& $normalExe --data-root $reviewRoot --profile safetywindows01
```

Reopen after orderly exit with the same complete arguments:

```powershell
& 'C:\ABSOLUTE\new-candidate\DLMS-Desktop-WebView2.exe' --data-root (Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'DLMS safety Windows data 20261018') --profile safetywindows01
```

A default/short explicit root avoids the documented unqualified deep browser-storage path limitation. Preserve Windows runtime-update compatibility checks: retained browser metadata, protected Evergreen ownership/version/ACL, no metadata rewrites/profile resets. Native WebView2 upload consent and exact-byte snapshots need their own verification; Linux sealed-file evidence is not Windows acceptance.

## Short native acceptance and return record

1. Import neutral quiz through ordinary chooser, Study 4/4, Exam first two wrong (2/4), close/reopen; verify answers and histories, Local identity and About source/build. Check duplicate launch and owned helper cleanup using task processes only.
2. Import hotspot pack, grade circle/polygon, mark, Rebuild All and reopen; compare full geometry/assets/quiz/history identity. Refusal of invalid authoritative content is expected; historical recovery/migrations are excluded.
3. Marked Anki initial/fallback where presented: native Save As, readable valid APKG, repeat/Cancel/collision and truthful feedback. Attempt-specific export must include only the selected second missed question, not all misses. Keep marked and history-wide exports working. WebView2 must preserve its own document/origin/trusted-action guards; do not broadly permit Blob downloads to copy Qt's fix.
4. Avery preview preserves POST/body and return selection/deck name; rendered layout success is not physical printing/duplex acceptance. Quiz Bundles hamburger must open/close with keyboard, sensible focus and aria state at narrow width, without changing selections.
5. Check revised Help, Local Settings backup/import, native export Cancel/focus, default-browser AI mouse/keyboard and clipboard without auto-paste/submit. The ordinary fixture PNG/PDF exercises OCR and review, not parser perfection. Check narrow and native 200% scaling in representative light/dark themes.
6. Run a task-owned synthetic server at the pinned runtime, explicit loopback origin/private-HTTP consent, with visibly distinct content. Verify Server Study/Exam save/reopen/history, Local unchanged, outage without silent fallback and orderly Server close wording/Keep open default. No owner endpoint, credential or unsolicited upload. A Desktop update cannot fix an older remote server's shared subset/menu/hotspot code.

Reuse [final safety report](../quality/workflow-final-safety-20261018.md) and [findings ledger](../quality/workflow-findings-20261018.md). Fault-injected normal Linux evidence is labeled, not vanilla Windows evidence. The interrupted Exam observation preserves one exact saved result through History; absent Resume cause remains unresolved and that branch did not retry. Keep lower-risk branches, external provider/Anki, physical accessibility/printing, power loss and real disk exhaustion explicitly unqualified. Return exact source, locks, native versions, inventories/hashes, focused results and owner-only gaps. Do not build a release installer, update an installed app or publish in this handoff.
