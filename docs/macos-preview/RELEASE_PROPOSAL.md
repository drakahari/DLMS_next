# Proposed Mac preview release — approval required

**DLMS Desktop 3.3.0 Preview — Apple Silicon**

Public source: `a8cd5182b6870e8bfdc1fca569b2cda9f191a1be`, plus the separately
recorded Mac public-packaging changes and shared Qt Avery printing correction
supplied in the exact source companion. The source record explicitly lists these
runtime changes; this is not a clean, unmodified build of the base commit.

This preview packages the DLMS Local backend and Server client in one normal
Finder application. File selection, TXT/PDF/image import, OCR, study, exports and
native backup/restore remain enabled. Local and Server retain separate storage,
credentials, origins and privileges; outage never silently switches to Local.
Normal browser handoff uses your actual default browser/profile without automatic
paste or submission. The original round blue DLMS icon is restored without a
redesign; its provenance and owner redistribution permission are recorded in
desktop_assets/ICON_PROVENANCE.md.

In Desktop, Avery **Print Cards** creates a US Letter PDF and offers the native
Save As chooser. Save it, then open it to print at actual size (100%). Cancellation,
failure and refusal have visible feedback; existing destinations are not replaced.
Selection, deck name and duplex setting survive Return. Physical printer alignment
remains unqualified. The original POST-only layout route is unchanged.

Open the DMG and copy `DLMS Desktop.app` to a new location that does not overwrite
an existing app or private Candidate launcher. Double-click that single app.
It uses the separately marked `DLMS Desktop Preview` data namespace and profile
`default`; an existing valid preview root is reused without adopting unmarked data.
No automatic import, migration, installation replacement or production
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

Ordinary users need only the DMG. Matching notices and exact application, Qt,
Python and Mac-native source companions accompany the distribution for licensing,
inspection and rebuilding; retain their availability together. See
REDISTRIBUTION.md and BUILD_AND_REPLACEMENT.md. SHA-256
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

The restored round blue artwork is owner-identified as AI-generated. Its known
provenance, owner permission and unknown generation details are recorded separately
from the code license. Previously published artifacts remain unchanged.
