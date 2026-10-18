# Windows preview validation and review

Public base: `58bcd13870b97c44201226ca3cf064772444a5ae`.
Branch: `feature/windows-desktop-public-preview`. Final source identity is the PR
head commit. No private history is merged; no installer/payload/profile/log is
committed. Source-only PR and owner release approval are separate gates.

## Preserved runtime evidence

The unchanged normal `windows-330-preview1-06` executable and 6982-file payload are
identified in INSTALLER_SOURCE_SUPPLEMENT.md. Its original build snapshot is
`29736002f7c115bd4d38a48a845bcb46f31bda08e494fca111cbb929b6a222a2`.

* 104 focused final-host/material/native-input/browser-handoff tests passed with
no failures/skips. Policy checks include exact IDs/location/resources, canonical
same-family bounded versions, signature/version/ACL/pinning, absence versus
lookup error, foreign/unsafe paths and unknown native consumers.
* Normal executable launch/duplicate/theme/Study/Exam/history/import/TXT/backup,
PDF/image OCR, authenticated shutdown, reopen and owned cleanup passed in
disposable synthetic profiles. No application test hooks were included.
* Normal Local and synthetic Server retained 155.0.4283.45/absent 155.0.4283.46
metadata startup passed under active 155.0.4283.60. Standalone unchanged-baseline
controls reproduced failure before repair. Reopens retained synthetic records
and a browser localStorage marker. No production endpoint or owner profile used.
* Isolated consolidated05→preview update verified old 4158/new 6982 payload files,
unchanged data bytes during setup, twice-reopened quiz/Study/Exam/history/theme,
exports and backup. Isolated uninstall retained external data. Real installed
payload and selected-profile shortcut remained unchanged.
* All 361 native dependency files match pinned producers; all 5 embedded icon
images match the cleared MIT icon. pip check passed. Independent material review
verified the 3582-file notice manifest, all 7 original source companion hashes,
exact notice ZIP and absence of Git history/profiles/binaries from application
source. Windows source/recipe/patch/LZO and vendor licenses were inspected.

The absent-version case edits only disposable persisted metadata to name an
actually absent version. **No machine Runtime was uninstalled or serviced.** A
residual protected directory without an executable is covered by strict native
directory proof plus native absent-image lookup, not an actual servicing run.
Server tests used retained-handle forced cleanup after preference publication;
they do not establish normal physical close acceptance. Source/reflection tests
and normal-package evidence are distinct. None proves physical focus, correct
displayed pixels, long-duration graphics or every future Evergreen change.

## Focused installer correction

Independent review found that the original installer recreated shortcuts without
Parameters, selecting `default` instead of an existing named profile. Previous
TestScope tests passed explicit --profile commands and did not exercise this.
The correction preserves only a verified canonical `--profile <name>` from a
safe existing shortcut/target. Other arguments or unsafe state stop setup. It
does not migrate data or infer authority from a page. Start, optional desktop
and optional post-install dispatch behavior is described in RELEASE_PROPOSAL.md.

The focused native test driver is `tests/webview2/installer_profile_update.py`.
It uses actual synthetic .lnk files beneath an isolated installation, checks
their target/working-directory/arguments after update, and reopens disposable
named-profile data through the normal payload. TestScope never writes real
Start menu, desktop or uninstall-registry entries. Its final receipt and all
revised installer hashes accompany the external final distribution index.

The first combined shortcut test reached and passed its actual shortcut-update
assertions, then stopped with WinError5 while copying synthetic Windows cache
junctions. That failed attempt remains preserved. The fixture now copies only
durable synthetic marker/manifest/backend data and refuses unexpected aliases;
only the remaining named reopen/default-install/uninstall phases were resumed.
This is combined phase evidence, not an uninterrupted successful full-driver run.

The runtime repair and distribution materials received independent read-only
reviews. The installer correction is cross-reviewed independently of its author.
No broad local test cycle is repeated. Applicable protected-main CI runs on the
feature PR; its final head SHA and results must be recorded before handoff.

## Explicit limitations

* A protected **machine-wide** WebView2 Runtime 155.0.4283.45+ and .NET 4.8 are required.
Per-user/AppData-only WebView2 is unsupported. Setup installs no prerequisite.
* Deep custom browser-storage paths can fail with native COM E_FAIL. This also
reproduces on the unchanged public baseline: 195 UTF16 units failed and 115 loaded
in matched fresh controls. These observations are not a universal length limit.
Use the ordinary default data path or a short explicit root.
* Application and installer remain unsigned. No certificate/security-setting
change, installed-app replacement, public asset upload, tag or merge occurred.

Keep all original runtime source/notices plus the final installer source/index
supplement. Technical correspondence approval is not legal certification.
