# Final installer source and unchanged runtime

The normal `windows-330-preview1-06` payload remains the accepted6982-file build
from public base `58bcd13870b97c44201226ca3cf064772444a5ae` plus source snapshot
`29736002f7c115bd4d38a48a845bcb46f31bda08e494fca111cbb929b6a222a2`.
Its executable SHA-256 is
`b929d0155f1b92d278f3d6aee1275a1ac72b1652b102807998e748de4c86854a`;
payload-inventory SHA-256 is
`c124d7c1a3965e1aa9060161f3cc07fc43682ffec9e67ca247fcbc6fabae03b3`.
No runtime source/dependency input changes for the final installer correction.

Keep the original notices/source companions: their byte-bound embedded index
continues to describe that exact runtime build. In addition, the final distribution
requires `DLMS-Desktop-3.3.0-windows-preview1-source-final-installer.zip` and
`FINAL_DISTRIBUTION.json`. The supplemental ZIP is the complete public source
tree at the final source commit, including revised installer, tests, build code
and instructions; it contains no Git history, private operational reports,
profiles or compiled payloads. The external final index binds this source commit,
all original companions, unchanged runtime inventory and revised setup hash.

The supplement supersedes the original runtime kit's statement that updates drop
custom profile shortcut arguments. The revised installer verifies an existing
launch shortcut, preserves supported `--profile <name>` arguments and refuses
unsafe/unsupported state. It does not migrate profiles or replay arbitrary
commands. Start menu and optional desktop selections are treated separately;
optional post-install launch uses the primary Start menu selection.

Rebuild using the final supplemental source tree, verified Inno 7.1.0 compiler and
the unchanged full runtime payload. From an isolated Windows build workspace:

```powershell
& $buildPython -m package_windows_webview2.build_installer `
  --candidate windows-330-preview1-06 `
  --acceptance $verifiedNormalOcrReceipt `
  --installer-revision profile-preserve01
```

The receipt must bind the actual accepted payload at that workspace's explicit
path. A copied receipt with an old path is insufficient. For an isolated update
test add `--test-scope`; it creates only synthetic menu/optional desktop shortcuts
below the test installation and no real Start menu/desktop/uninstall-registry entries. Never
execute the shipping setup as an automated qualification shortcut.

This is an installer-only source correction. The final installer source commit
does not claim that the preserved runtime was rebuilt after that commit. Compiler,
script, unchanged payload inventory, normal receipt and setup hashes are recorded
separately. Original and final source/material identities remain explicit.
