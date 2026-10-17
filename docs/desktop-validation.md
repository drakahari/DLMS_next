# Consolidated validation contracts

The proposed workflows validate changes; they do not publish or sign releases.
Native CI execution is not established merely by writing a workflow.

Install the existing declared requirements in a disposable environment. The
application suite also needs `requirements-build.txt` for spec metadata tests.
Desktop Linux uses the pinned `package_fedora/requirements-build-lock.txt` plus
`requirements-test.txt`. Windows uses its existing package-specific lock.

```sh
python tools/run_consolidation_checks.py application --basetemp /tmp/dlms-new-core
python tools/run_consolidation_checks.py desktop-linux --basetemp /tmp/dlms-new-linux
python tools/run_consolidation_checks.py windows-portable --basetemp /tmp/dlms-new-controller
```

Use fresh paths. Qt module groups run in separate processes: mixing unrelated
QCoreApplication and QApplication fixtures in one process is invalid. The
canonical application suite has no historical captured-snapshot exclusions.

## Windows validation handoff — required before Windows acceptance

Use the exact final private consolidation commit, never a concurrent unfinished
checkout. No Linux result establishes COM, ACL, native chooser or WebView2
acceptance. On a separately authorized Windows 11 x86_64 machine:

1. Resolve the existing Windows requirements and `pip check`. Acquire the pinned
   WebView2 SDK described in `windows_webview2/build.ps1` (SHA-256
   `56f7f4b8bf9aee4b8efefbbdd4f67d5f74ebd1b100ed0806da71bf76af481aa9`),
   from `https://api.nuget.org/v3-flatcontainer/microsoft.web.webview2/1.0.4258.31/microsoft.web.webview2.1.0.4258.31.nupkg`; verify extracted
   members. The .NET Framework compiler and trusted Evergreen runtime are
   prerequisites. Stop if absent; do not install them automatically.
2. Run `python tools/run_consolidation_checks.py windows-native --basetemp C:/Temp/dlms-new-windows`.
   This isolates Qt module lifetimes and excludes two retired private diagnostic
   harnesses, not active host contracts. Native checks that skip
   or lack an SDK/runtime remain pending; do not count a portable subset as full.
3. Build a fresh host using the existing PowerShell build script and an unused
   supported BuildName. Run request/fetch/AI lease C# tests and source UI drivers.
4. Exercise Local and synthetic Server: deliberate AI/clipboard, TXT/ZIP/Anki
   Save As/repeat/cancel, ordinary-folder consent and byte sealing, remembered
   folders, frames/navigation rejection and outage without fallback.
5. Verify Study/Exam accepted-save crash/reopen, lost acknowledgment, backup
   import/maintenance refusal with pending work, duplicate exclusion, exact
   helper cleanup, profile/origin and content/asset persistence.
6. Freeze with `package_windows_webview2`, inspect canonical code/assets/About
   identity, then repeat representative normal-package workflows. Keep source,
   instrumented and normal-package evidence distinct. No installed replacement.

Linux frozen checks must use the existing Ubuntu24-compatible pinned image,
minimal bundle, host Fontconfig/GBM policy, OCR and notice inputs. Neither a
Fedora source run nor an Ubuntu container establishes native Ubuntu/Omarchy
graphics, physical input or accessibility acceptance.
