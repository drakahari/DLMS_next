> Unpublished focused Mac candidate `macos-focus-fix-20261019`.
> Exact source/handoff: `717dd01a5efa9c6cbc8f95f463e70714ec198597`;
> shared runtime correction: `c1268daaf8a1dab2919b912c117a1ac4f86ea6c6`.
> Uncommitted shared Qt Server focus correction, test tooling and packaging identity
> overlay are recorded separately.
> Bundle: `DLMS Desktop Focus Candidate.app`. During this task open only via
> the verified task wrapper with its fixed synthetic data-root/profile. The bare
> app retains the public Preview default directory; do not open against existing
> installed/personal storage. No installation/release is authorized. Ad hoc only,
> no Developer ID/notarization; downloaded/quarantined approval is unqualified for
> this artifact. Same-user malicious native processes remain outside the selected
> file snapshot guarantee. Historical Preview1 instructions below are reference,
> not this candidate's identity or qualification.

# Proposed Mac preview release — approval required

**DLMS Desktop 3.3.0 Preview 1 — Apple Silicon**

This preview packages the DLMS Local backend and Server client in one normal
Finder application. File selection, TXT/PDF/image import, OCR, study, exports and
native backup/restore remain enabled. Local and Server retain separate storage,
credentials, origins and privileges; outage never silently switches to Local.
Normal browser handoff uses your actual default browser/profile without automatic
paste or submission. The original MIT DLMS badge is included.

Open the DMG and copy `DLMS Desktop.app` to a new location that does not overwrite
an existing app or private Candidate launcher. Double-click that single app.
It uses a new, separately marked `DLMS Desktop Preview` data namespace and profile
`default`. No automatic import, migration, installation replacement or production
server change is performed. Choose your Server through the native mode control.
A first local-network connection can require macOS permission and a retry.

**Signing:** local ad hoc integrity signature only, with no Developer ID or
notarization. A browser-downloaded/quarantined copy may be blocked because Apple
cannot verify its developer or check it for malicious software. Apple's supported
procedure is: attempt opening, then use **System Settings → Privacy & Security →
Open Anyway**, followed by **Open**, if macOS offers this for the trusted app.
Managed Macs may disallow that exception. Never disable Gatekeeper, remove
quarantine or override a malware/damage warning. If approval is unavailable or
does not work, stop and report the exact message. Original current-host private
launch success is not proof of downloaded-artifact acceptance.

**Selected-file guarantee:** explicit page-owned consent, exact origin/path
checks, pinned descriptors and content-integrity verification remain enabled.
Detected changes fail closed. Snapshots use macOS user-immutable flags; another
malicious native process already running as the same user can clear those flags
and change bytes after verification. Such a process is outside this preview's
guarantee. This is **not Linux-equivalent irrevocable sealing**. A remote page
alone does not receive an API to clear flags or select arbitrary private paths.

Download all accompanying notices and exact application/Qt/Python/Mac-native
source companions. Read REDISTRIBUTION.md and BUILD_AND_REPLACEMENT.md. SHA-256
checksums detect mismatches; they do not independently verify the publisher.

Reuse of accepted Mac Local and synthetic Server walkthrough evidence is labeled
with its original scope. The owner also reported installed private launch,
Server Dashboard/Library and Cmd-Q/reopen passed: initial Allow access plus retry,
then prompt-free connection on subsequent launch. Those observations are not new
public-artifact results or a general login-persistence guarantee. New packaging,
entry point and downloaded-opening checks are recorded separately.

Qualified host baseline is macOS26.6.2 arm64. Intel Mac, other macOS versions,
cross-platform native regressions, long-duration use and full Server Study/Exam
acceptance are not inferred from these checks. Developer ID/notarization and any
general release beyond this explicitly limited preview remain separate work.
This proposal and prepared artifacts require owner approval before merge or
publication. No such action has occurred.

Apple references: [Safely open apps](https://support.apple.com/en-us/102445) and
[Developer ID](https://developer.apple.com/developer-id/).
