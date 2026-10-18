# Apple Silicon preview: opening and validation

Prepared on 2026-10-17 for owner review. No merge, push, publication or installed
application replacement is authorized by this preparation.

## Opening the downloaded app

This is an **ad hoc signed, unnotarized** preview. It has no Developer ID identity.
On the qualified Mac, a downloaded and quarantined copy initially produced:

> “DLMS Desktop.app” Not Opened

Apple said it could not verify the app was free of malware. The supported flow
that actually worked on macOS 26.6.2 was:

1. Attempt to open the exact trusted `DLMS Desktop.app` in Finder.
2. Choose **Done** on that initial warning, preserving the app.
3. Open **System Settings → Privacy & Security → Open Anyway** for this app.
4. Confirm **Open Anyway** on the subsequent app-specific dialog (some macOS
   versions label this **Open**).
5. Authenticate personally at the macOS prompt using the existing password or
   Touch ID. Do not share credentials with an agent or publisher.

The owner completed step 5. The app then opened normally, including under App
Translocation. A real Cmd-Q closed it and all observed bundle-owned helpers;
both instance and backend-writer locks were released. Finder double-click
reopened the same profile without another approval prompt. A second Cmd-Q left
it closed. Quarantine remained present on the DMG and app; strict signatures
and payload hashes still matched. No global Gatekeeper setting was changed and
no quarantine was removed. Stop for a malware/damage warning, unavailable
per-app exception, unexpected elevation or an organizational restriction.

The exact DMG was downloaded over a task-owned loopback HTTP server using the
native download API, marked through macOS's quarantine API, mounted read-only,
and its app copied with quarantine retained. Its bytes matched the build before
the actual Finder launch. This verifies a real quarantined artifact on this
host; it is **not** a Safari/GitHub end-to-end download or another Mac's acceptance.
The temporary download server and preview processes are stopped.

The previous three release documents embedded in the immutable app/notice kit
were written before this check. This supplementary record supplies the final
opening result without changing or rebuilding the tested payload. Intermediate
stopped harness receipts are retained privately: metadata representation,
pending-warning detection and a Python xattr API mismatch were corrected. The
last issue occurred after Cmd-Q/reopen; only read-only metadata checks resumed.
No failed result was silently relabeled or core safeguard weakened.

## Single entry and separate data

The DMG contains one user-facing `DLMS Desktop.app`, with the cleared MIT icon.
It opens directly with no shell shortcut or external wrapper. The private
installed Candidate and its explicit-root launcher remain untouched. Do not
overwrite an existing app with the same name when choosing a preview location.

Normal preview launch uses a separately marked
`~/Library/Application Support/DLMS Desktop Preview`, profile `default`. The root
was absent before the opening check; only this new preview profile was created.
UUID, epoch, origin and port remained identical on reopen. Existing Candidate,
Personal and legacy roots are neither discovered nor adopted. Explicit
`--data-root` and `--profile` options remain available. No cleanup or migration of
existing data is performed.

Local backend and Server client remain enabled. File selection, imports, OCR,
exports, backup/restore/reset and normal default-browser AI handoff retain the
accepted implementation. Server failure does not silently switch to Local.
This check used Local synthetic/empty preview data and no production connection.

## Evidence reused, focused checks added

The public base is `e084c04a2be7b1e5f593b12fc0f232b7d3c2c75b` on the separate
`feature/macos-desktop-public-preview` worktree. The accepted Mac runtime and
shared integration hooks were already present there; 24 relevant implementation
files matched the accepted private implementation byte for byte. No private Git
history was merged, copied or cherry-picked.

Previously completed evidence is reused with its original scope:

- 54 Mac unit tests; 173 affected shared tests plus 92 subtests; additional
  focused backup/Settings checks; final 17-step bounded native qualification.
- Packaged synthetic TXT save/reopen, Study persistence, export, PNG/PDF OCR,
  duplicate ownership, Local/Server separation and shutdown checks.
- Source/instrumented chooser and backup/restore/reset checks, distinguished
  from normal packaged physical interaction.
- Owner-reported Local and synthetic Server walkthrough passes, including
  mode separation, outage handling, close/reopen and normal browser handoff.
- Owner-reported private installed-app launch, Server Dashboard/Library and
  Cmd-Q/reopen. Initial connection required Allow access and retry; subsequent
  launch connected without prompting. This is not a general login guarantee.

Changed-path checks for this public preview:

- 14 focused pruning/dependency tests and 15 affected path/filesystem tests pass.
- 326 packaged Mach-O files are arm64; no developer Homebrew/source dylib links.
  Required dependencies remain after removing seven unused GPL/commercial Qt
  families. Deep strict ad hoc signature verification passes.
- Single app identity, cleared icon and frozen `--help` pass. The actual bundled
  Tesseract recognizes the normal Documents synthetic PNG text; bundled PDFium
  opens the one-page scanned-PDF fixture. No production input was used.
- DMG verification, exact mounted/downloaded payload comparison and the actual
  quarantined Finder/Cmd-Q/reopen sequence above pass.
- Independent reviews covered the runtime/source correspondence, retained Qt
  dependency closure, native source/notices kit and outgoing source privacy.
  New companion archive metadata is normalized to avoid exporting host ownership.

The build records all 432 runtime-source file hashes and an aggregate snapshot.
These match the source companion. The base commit alone does not contain these
uncommitted preview changes. Repository policy reserves commits for the owner
unless explicitly authorized; the exact application source archive and its
manifest are the reviewed working-tree snapshot, not a claimed pristine commit.

## Accepted limitations and release gates

The owner accepts fully functional selected-file workflows for this preview
with the documented same-user limitation. Explicit consent, page/origin/path
checks, pinned descriptors and content-integrity verification remain; detected
changes fail closed. A malicious native process already running as the same user
can clear immutable flags and potentially alter bytes after verification. This
is outside the preview guarantee and is **not Linux-equivalent sealing**. Ordinary
Server navigation/answers that do not select a local file are separate from this
selected-file threat boundary.

The complete exact Mac materials include Python/Qt source companions reused
unchanged from the public release, Mac producer formulas/patches, English OCR
model, wheel notices/SBOMs and separate FFmpeg 7.1.5 source/configuration. No Linux
or Windows binary-license mapping is substituted. This is technical source
correspondence, not legal certification or bit-reproducibility of vendor builds.

Remaining gates: owner review/commit and merge/publication approval; recipient
download acceptance after any future publication. No Developer ID/notarization
is claimed or required for this explicitly approved ad hoc route. Managed Macs
may prohibit opening. Intel and other macOS versions, native Linux/Windows
validation of future shared changes, long-duration use and full Server Study/Exam
acceptance are outside this check. No additional owner walkthrough is requested.

Apple's supported guidance: [Safely open apps](https://support.apple.com/en-us/102445).
