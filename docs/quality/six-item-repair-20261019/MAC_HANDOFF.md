# Mac native continuation — six-item repair

Status: supplied-report diagnosis and tooling handoff only; no native Mac execution, signing, attribute change or launch in this Fedora task. Accepted build source `4b50e2b3fb39dd478d355bf785b319805579076c`, shared runtime `bfdffb720f743e9d720cd07292ec7e1ec325e059`; retained macOS 26.6.2 arm64 DMG SHA-256 `6e3dd5c27af920d9972a2204801d650587bd6a5dbe350d22d04a72da04b97db2`. Retain the separate five-file metadata overlay SHA-256 `a6741cc4084b8fb42ccbe50aba5fbe0fb25ff13b90e793aa58cca1cc08e8b76d`. Another machine's retained paths are references, not assumed available here.

Use the native task's isolated candidate/profile and task-created ordinary Documents fixtures only. Preserve the original wrapper, accepted payload, DMG, metadata overlay and evidence. No installed change, production connection, commit or push. Review source/tooling before any affected candidate build; do not rebuild the accepted payload solely to fix an external test wrapper.

## Test wrapper integrity and fail-fast correction

The supplied report establishes `Open DLMS Safety Candidate.app` in Documents failed strict codesign with **“resource fork, Finder information, or similar detritus not allowed”** and FinderInfo present. The protected candidate payload passed deep strict verification. Owner Finder launch/reopen passed separately. These facts identify a test-wrapper/procedure issue; they do not establish payload tampering or repair the wrapper's failed integrity check. The initial command proceeded to LaunchServices open because verification was not fail-fast.

The exact external wrapper-generation/open recipe is not present in this source tree. Retrieve it from the native task's retained materials and correct that tooling. `package_macos/build.py` already stages the payload in its dedicated private cache, removes only `com.apple.FinderInfo` and `com.apple.ResourceFork` on freshly built payload output, then ad hoc signs and checks strictly. That existing payload recipe is not evidence the external Documents wrapper was built or opened correctly.

Native bounded correction:

1. Record original wrapper/payload identity, regular-file inventory, symlinks, modes and xattrs read-only. Preserve the original wrapper in place as evidence. Create a fresh task wrapper from its reviewed recipe in a fresh owned staging directory outside the Documents metadata provider. Keep fixed explicit candidate/root/profile arguments. Use a bundled icon resource/Info.plist icon reference if mutable Finder icon customization is the trigger.
2. Inventory the fresh staging wrapper's metadata. Before signing, remove only confirmed signing-incompatible FinderInfo/ResourceFork from that fresh owned output, recording exact affected paths/attributes. Preserve quarantine and unrelated xattrs. Do not use `xattr -c`, a quarantine deletion, a security override, in-place installed edits or removal on the accepted candidate/original wrapper.
3. Ad hoc sign the fresh wrapper and verify strictly; verify the accepted candidate deep/strict and compare its retained file inventory/hash unchanged. Recheck after placing any fresh test wrapper in its intended ordinary Documents location. If the provider reattaches prohibited metadata, stop using that location for the executable wrapper; retain task fixtures/reports in Documents and use the verified private staging wrapper through ordinary Finder/LaunchServices. Do not keep clearing metadata at launch to hide the defect.
4. Put verification and open in one checked control flow. A native helper should invoke each verifier with checked exit status and invoke `/usr/bin/open` only after both successful results and matching pinned identities. A shell equivalent for already validated absolute task paths is:

   ```sh
   /bin/zsh -f -c '
     set -euo pipefail
     test "$#" -eq 2
     /usr/bin/codesign --verify --deep --strict "$1"
     /usr/bin/codesign --verify --deep --strict "$2"
     /usr/bin/open "$1"
   ' dlms-verified-test-open "$task_wrapper" "$accepted_candidate"
   ```

   Set those variables from the native task's verified local inventory, not this report's other-machine paths. Keep the wrapper fixed to the accepted candidate; the second argument must not be an unrelated app that happens to verify. Pin/check wrapper and payload inventories before opening. Check a successful open's exact executable/root/profile and normal Cmd-Q/reopen only within the authorized native session; do not infer success from open's exit code alone.
5. On a separately named disposable copy only, attach the confirmed Finder metadata, reproduce the same strict failure, and run the corrected control flow with an observable test opener: verification failure must produce a nonzero result and zero opener calls. Also confirm the real LaunchServices step is unreachable on failure. Do not open the intentionally invalid copy. Correct a fresh staging copy and show it passes. Preserve failure evidence and quarantine bytes. If any security warning/elevation occurs, stop without bypass.

This qualifies test-wrapper integrity and launch tooling only. Keep ad hoc/no Developer ID/notarization, unqualified downloaded/quarantined approval flow and same-user immutable-flag limitation explicit.

## Reuse native passes; preserve missing qualification

The supplied native Avery POST/rendered-sheet/Return-selection result is a pass; no Mac Avery rework or printing rerun is needed. Browser/profile handoff was owner-observed; exact clipboard bytes were not inspected. Marked/attempt-selected APKG contents and Save As cancellation passed within the supplied report's scope. Preserve the actual trailing-space output filename recorded there; do not rename historical evidence.

Existing-destination application refusal remains **unqualified**: owner canceled the macOS Replace prompt and then Save As; the sentinel stayed unchanged. It is neither a confirmed overwrite defect nor a qualified refusal. Only in an explicitly authorized isolated native follow-up, use a new task-created APKG sentinel in ordinary Documents, record its hash, select it and accept native Replace to reach the application refusal, then verify unchanged bytes/no premature success. Stop on unexpected mutation and retain evidence. Never target owner files or installed storage.

Native Rebuild All and new Server Study/Exam answer/save/reopen were omitted under the owner walkthrough's latest restrictions. They are **untested**, not failed or passed. After shared repair review and an authorized affected native candidate, qualify Rebuild with a new task-created ordinary quiz and partial Study: two no-op rebuilds preserve bytes/IDs/revision/session/answers, reopen resumes, and a genuine question/key change still refuses stale Resume; verify missing/corrupt authority leaves prior artifacts unchanged. Preserve hotspot authority and reuse focused shared hotspot evidence; do not claim new native hotspot qualification from the omitted check.

A fresh native Server answer/save/reopen journey requires a separately explicit native qualification scope; prior mode visibility/reopen/Local isolation and shared/Fedora evidence do not establish it. Do not add this unrelated omitted branch to the wrapper repair silently.

For the reviewed clipboard/navigation patch, create synthetic Q2+Q4, inspect exact selected prompt clipboard bytes, deliberate mouse/keyboard browser opening and denial feedback without provider submission, then reach Marked questions from the shared sidebar with correct selected state/keyboard access. Use a newly created ordinary Documents fixture directory, preserving prior walkthrough outputs. Formal accessibility/scaling, physical printing/duplex and external-provider behavior retain their original limits.
