# Qt Avery PDF repair — committed source and existing Mac artifact

## Exact correspondence

- Public base: `a8cd5182b6870e8bfdc1fca569b2cda9f191a1be`.
- Exact reviewed 14-file overlay committed as
  `7f49e5ea43f6829a29f681a5261a41c58afe6393`.
- Complete overlay SHA-256:
  `f90c0b0abc4e782ba0937d1c1ab9506375d98a5c387ef4b56abb4c96361d80a3`.
  This is `git diff --binary <base> <repair-commit>`, not the later documentation
  addendum. It equals the literal `PACKAGING_CHANGES.patch` distributed in the
  source companion, notices and separate download.
- Qt-only reviewed patch SHA-256:
  `0a810021ca00e2c665456f60148126ce9f4554d249a6ec8727d53b0e2fe4d106`.
- Existing DMG: `DLMS-Desktop-3.3.0-macos-arm64-preview.dmg`, SHA-256
  `dfdab2e406911bbc6c8291551ab4bc42ed01d6c668ab29471531fce9a667e7da`.
- Embedded runtime snapshot SHA-256:
  `3d75d9ab85b1694a0efc4b86f07c8a44cf5f5cc6658d1e139d5d374954634d1c`.
- Canonical application inventory SHA-256:
  `e613a82f2e93f608c25a69bc633b01930e8b430c09f3f76796b5d8fc2848d90f`.
- Main executable SHA-256:
  `0618f81bc23a377a75f1b0bd289ac2e5d3b11101a55d222a97986d13d2cabca0`.

All 1,581 application-source files in `APPLICATION_SOURCE_MANIFEST.json` match
that repair commit byte for byte. The archive's two additional generated records
are `PACKAGING_SOURCE.json` and the literal patch. Independent review verified
all 1,583 source members, 3,735 notice files, 326 native arm64 hashes, strict app
signatures and the DMG. Frozen `desktop.qt_printing` and `desktop.shell` code
objects match compiled reviewed source after filename normalization; both changed
templates match exact bytes. The original round blue icon and one direct,
self-contained `DLMS Desktop.app` are retained. This records correspondence, not
a new build or a reproducible vendor-binary claim.

The artifact was built before this commit, from the base plus that overlay. Its
embedded base/overlay identity is intentionally preserved rather than relabeled
as a pristine build of the new commit. The subsequent release clarification and
this acceptance record are documentation-only post-build addenda: they do not
appear in the immutable source/notices companions or change the packaged runtime.
To reproduce the package inputs, reconstruct the pinned base plus the exact
reviewed patch; the pinned-source packaging guard must not be bypassed to pretend
that a later checkout is the original build environment.

## Cause and retained focused qualification

Server Qt emitted `printRequested` without a connected handler. Local wrote a
PDF to private staging without a user Save As. The correction installs one
scoped Qt controller for each mode, generates a Letter PDF, and reuses the
unchanged protected export publisher. It retains explicit trusted action,
exact origin/document/lifetime checks, consent, no-replace destinations and
visible success/cancellation/failure/refusal feedback. See
[SOURCE_ACCEPTANCE.md](SOURCE_ACCEPTANCE.md) for the prebuild source evidence and
[HANDOFF.md](HANDOFF.md) for the precise shared Qt/Linux and Windows boundaries.

Independent prebuild source review and final artifact review passed. Reused
source Qt checks cover Local plus a task-owned synthetic Server: selected
ALPHA/CHARLIE questions and answers only, BRAVO excluded; two Letter pages;
Save As cancellation; existing-destination protection; scripted/frame refusals;
mode-specific staging; and selection/deck-name/short-edge Return state with
updated shared templates. A separate legacy-Server case produced the same
selected-only PDF without a button ID/status element. Those source journeys used
simulated native chooser responses, not genuine native-dialog acceptance.
The 11 focused policy/lifetime checks, 44 affected existing output/template
checks with 5 subtests, and 5 provenance checks remain reused at their recorded
scope. No broad audit or workflow tests were repeated to commit this repair.

## New bounded normal-package native attempt

The exact existing packaged executable was launched through LaunchServices,
with fresh explicitly marked synthetic storage and a fixed synthetic profile.
No remote debugging, renderer injection or simulated dialog response was used.

| Check | Result |
| --- | --- |
| Local exact package/profile launch and synthetic seed | PASS |
| Local native navigation to Avery | BLOCKED: direct AX lookup and the existing System Events alternative exposed no Anki Tools link; interaction stopped |
| Server exact package/profile launch, own loopback synthetic endpoint | PASS after correcting test preparation as described below |
| Server native navigation to Avery | BLOCKED: dashboard links were exposed, but the required Anki Tools link was absent from the inspected native tree; no successful alternative interaction was established |
| Genuine Print Cards → native Save As → saved PDF, both modes | PENDING: Avery was not reached; no new native-journey PDF was produced |
| Selected-card content in a genuine native-save PDF | PENDING; the prior genuine Qt PDF/simulated-dialog evidence is separate |
| Genuine native Save As cancellation | PENDING; no native Save As was reached or answered |
| Task app/server cleanup | PASS: Local normally closed; Server's ordinary close confirmation was captured and completed; task endpoint stopped |

The first Server setup accidentally created a nonprivate intermediate test
`shell` directory and produced no instance lock; that rejected setup and evidence
were preserved. One corrected setup used a new root with explicit private
ancestors, preserving the unchanged application's protections. No personal
storage was adopted or changed.

The Server cleanup helper initially waited for exit without answering the
ordinary "Close DLMS Desktop" warning that the remote save state cannot be
verified. This was a helper limitation, not a reproduced Quit defect. The warning
was read and accepted only for the disposable task session. No security prompt
was approved and no force termination was needed. Private process identities,
nonces, raw UI trees and operational logs remain local and are excluded from Git.

Native-dialog acceptance is unresolved; no claim of an app printing defect or
native pass follows from this navigation/control-automation limitation. Physical
printer feeding/alignment, Linux packaged acceptance, Windows WebView2 printing,
other macOS versions, and downloaded/quarantined opening of this ad hoc package
remain unqualified. No new owner walkthrough is requested.

## User-facing print and older Server behavior

Desktop **Print Cards offers Save As PDF**. Open the saved PDF in Preview or
another PDF viewer and use that viewer's Print command, at actual size (100%).
It is not a direct hardware-printer dialog. Older Server templates can still
print PDFs, but need the shared template update to retain a nondefault short-edge
setting on Return. The POST-only layout route and selected-card contract remain
unchanged. Do not substitute GET, port WebView2 native code into Qt, or infer
Linux acceptance from Mac evidence.

The prior DMGs, all 17 replacement delivery assets/hashes and original local
evidence are preserved. Committing/pushing/opening a draft PR was subsequently
authorized; installation, merge, tags, release publication and production access
remain unauthorized. CI results belong to the PR checks, distinct from native
package acceptance. No assertion is weakened for a failing CI job.
