# Build and replace the Windows Desktop preview

Use native Windows 11 x86-64 and a disposable build directory. Source baseline is
public DLMS_next `58bcd13870b97c44201226ca3cf064772444a5ae` plus the reviewed
working-tree Windows overlay contained in the application-source companion.
There is no private Git history. Verify all SOURCE_MATERIALS.json archive hashes.
Keep the full executable folder together. Never build into installed payloads or
profiles. Source/binary publication and normal-user installation need approval.

Use the verified isolated CPython 3.14.7 and exact
package_windows/requirements-build-lock.txt pins. The Windows acquisition and
prepare_python scripts verify publisher SHA-256 before execution; do not use an
unverified downloaded interpreter or change global Python. SDK1.0.4258.31 input
SHA is checked by windows_webview2/build.ps1. Prepare the OCR bundle through
package_windows/prepare_ocr.py and its exact conda lock; run no package scripts.
Recreate source/material inputs from the supplied archives/indexes and retained
conda recipes/patches, not a broad dependency upgrade.

Required native tools: Windows .NET Framework 4.8 compiler/runtime and Inno 7.1.0
portable compiler (verified via package_windows/acquire_inputs.py). These were
already available for the prepared build. Ask before installing missing host
prerequisites. In an ordinary PowerShell shell from the source root:

```powershell
& .\windows_webview2\build.ps1 -BuildName webview2-host-candidate-01
& $buildPython -m pip check
& $buildPython -m package_windows_webview2.assemble_preview_materials `
  --linux-materials $verifiedLinuxCompanions --native-sources $windowsSources `
  --python-extras $windowsPythonSources --installer-sources $innoSources `
  --wheelhouse $pinnedWindowsWheels `
  --output .gate1/windows-native/preview-materials `
  --delivery .gate1/windows-native/preview-delivery
& $buildPython -m package_windows_webview2.build `
  --release windows-330-preview1-20261017 --host-build webview2-host-candidate-01 `
  --native-packages $verifiedNativeProducerArchiveCache `
  --preview-materials .gate1/windows-native/preview-materials
```

Variables name explicit verified build inputs, never owner profiles. The two
unmodified reusable Linux source companions are hash-pinned by the material
assembler. Windows native SOURCE_INDEX_FINAL.json records each source/archive
SHA and includes conda recipes, patches, local inputs and static dependencies;
Windows Python SOURCE_INDEX.json records official CPython external tags and
Windows-specific Python source downloads. All recipe commands run only if
rebuilding a dependency deliberately. The producer recipes retain compiler and
host/build dependency versions; compatible replacement is not bit reproduction.
The assembler refuses missing/substituted source inputs and exports only public
source plus the implementation overlay, excluding ignored operational data.

Run the focused tests and normal-package startup/reopen/OCR receipt before:

```powershell
& $buildPython -m package_windows_webview2.build_installer `
  --candidate windows-330-preview1-20261017 --acceptance $normalAcceptance
```

Use --test-scope and a separate /DIR for isolated installer/update qualification;
the shipping installer must never be executed by an automated test. The existing
AppId, legacy Candidate installation/data namespaces and current-user menu names
are retained for compatibility; preview wizard/About identity is explicit. Setup
requires an already installed supported protected machine Evergreen Runtime and
installs no prerequisite. .NET Framework is host-provided. All payloads/setup are
unsigned; never disable Windows security warnings or browser sandboxing.

For library replacement, make a separate payload copy. Rebuild shared Qt/PySide
6.11.2 with the supplied official sources and upstream CMake/PySide Windows build
instructions, using ABI-compatible DLLs, plugins and Python bindings. Replace the
matching shared files in that copy or rebuild the whole frozen application using
the source/lock/spec above. No publisher signing key is needed. Keep licenses and
verify new inventories. Qt fallback helper/resources must remain compatible.
For OCR, use the exact producer recipes/patches, DLL closure and trained data,
then rebuild the payload with a new OCR inventory; retain the manifest-modification
notice. Microsoft system runtime servicing is separate from replacing bundled
open-source libraries. Do not alter system graphics, ACLs, drivers or security.

The preview uses the current signed/protected Evergreen runtime. Exact known
built-in component metadata may name an older runtime. Retained old executables
still need signature/version/ACL proof; an absent old directory/image is accepted only
under the strictly protected same runtime namespace. No old executable is loaded,
no browser metadata is rewritten and no profile reset is required. Malformed,
future, foreign or unsafe component/extension state still fails closed.

Known preview path limitation: the unchanged public host also fails with a generic
native COM error for a deeply nested 195-UTF16-unit browser-storage root; a matched
fresh 115-unit root loads. The existing239-unit leaf check does not guarantee
native initialization; the exact internal failing lookup is unproven. Use the ordinary default data location or a
short explicit disposable root; no universal long-path acceptance is claimed.
This predates the Evergreen correction and remains separate. The default namespace
is `%LOCALAPPDATA%\DLMSDesktop\WebView2Candidate`; the installer keeps prior version
payloads and external data. The original06 installer did not preserve custom
`--profile` arguments. The final profile-preservation
installer revision corrects this: its exact source/provenance supplement supersedes
this original installer behavior while keeping the accepted runtime payload
unchanged. Only a verified `--profile <name>` selection is retained; unsupported
or unsafe arguments stop setup rather than silently selecting default. Use the
final supplemental public source tree to rebuild that installer. Neither the
path limitation nor per-user Runtime restriction is relaxed.
