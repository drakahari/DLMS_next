# DLMS 3.2.1 version convergence inventory

Date: September 23, 2026. Branch: `develop/3.2.1`.
Initial HEAD: `1e8fe20dce0cfda9fa575009d33fd56293711324`.
Initial tracked/untracked working-tree status was clean.

## Classification before editing

The repository-wide text audit located active current-version declarations,
current build/install examples and current-version assertions; dated historical
records; and generated/release artifact references. Each was classified before
editing. No blanket repository-wide substitution was performed.

**ACTIVE CURRENT VERSION:** `app.py:APP_VERSION`, current README/source target,
Help/About/static documentation labels, package support README, dependency-lock
and build-environment comments, native/OCR/AppImage command examples, current
manual chapters and release/version/export tests. These now identify 3.2.1.
`SECURITY.md` now names `develop/3.2.1` but separately identifies the actual
published stable version returned by GitHub, v3.2.0.

**HISTORICAL RECORD:** dated old audits/release notes/checklists, original manual
inventory/terminology/capture-planning records, screenshot metadata and video
production provenance. These do not identify the current runtime. Old
`docs/releases/3.2.0*` records were preserved; new 3.2.1 documents supply the
current release notes, readiness record and execution checklist.

**GENERATED / RELEASE ARTIFACT REFERENCE:** existing files under ignored
`build/`, `dist/` and root `releases/`, including the old six-package set,
`SHA256SUMS.txt`, Fedora binary and AppImage candidates. These were not rebuilt,
renamed, rehashed as new release evidence or promoted. Their versioned names
and old acceptance evidence remain intact. Existing screenshots/audio/video
outputs were not regenerated.

## Active version files changed

- `README.md`
- `SECURITY.md`
- `app.py`
- `docs/OCR_PACKAGING.md`
- `docs/RELEASE_VERIFICATION.md`
- `docs/user-manual/01-introduction.md`
- `docs/user-manual/02-installation-and-first-launch.md`
- `docs/user-manual/19-feature-and-format-reference.md`
- `docs/user-manual/README.md`
- `docs/user-manual/appendix-platform-and-runtime-notes.md`
- `release_assets/README.txt`
- `requirements-build.txt`
- `requirements-lock.txt`
- `static/about.html`
- `static/advanced-features.html`
- `static/help-anki.html`
- `static/help-build-quiz.html`
- `static/help-content-management.html`
- `static/help-external-ai.html`
- `static/help-getting-started.html`
- `static/help-history-analytics.html`
- `static/help-learning-intelligence.html`
- `static/help-maintenance.html`
- `static/help-quizzes.html`
- `static/help-settings.html`
- `static/help-smart-pdf.html`
- `static/help-study-modules.html`
- `static/help-study-packs.html`
- `static/help-troubleshooting.html`
- `static/help.html`
- `static/quiz-help.html`
- `tests/browser/test_critical_workflows.py`
- `tests/test_backup_semantic_validation.py`
- `tests/test_downloaded_release_acceptance.py`
- `tests/test_portable_quiz_bundles.py`
- `tests/test_release_artifact_verification.py`
- `tests/test_release_hygiene.py`
- `tests/test_release_package_verification.py`
- `tools/accept_downloaded_release.py`
- `docs/APPIMAGE.md` (active examples only; original candidate evidence retained).

The application constant feeds response `X-DLMS-Version`, rendered template
footers and export/backup metadata. `DLMS.spec` and release/package tools already
derive their version from `app.py`; their code required no duplicate constant.
The existing metadata tests execute the spec metadata portion and verify the
3.2.1 macOS release, short and build version values.

The screenshot contract originally required historical metadata to equal
today's runtime, which failed after convergence. The explicit version-only
screenshot preservation requirement makes that old assertion incorrect.
`tests/test_manual_screenshot_capture.py` now checks capture-version agreement
with the historical manifest and separately tests current-version discovery
for future captures. Existing image dimensions, IDs, classes and provenance
checks are retained. Tutorial validators retain their screenshot hash checks.

## Remaining old-version text occurrences

The following exhaustive tracked/source-text inventory was taken after active
version edits and before writing this audit and the new scored audit/readiness
records. Line numbers refer to that converged tree. Each row classifies all
listed occurrences; none is a stale active-version defect. The new September 23
records introduce only historical comparison, classification and provenance
references themselves.

| File | Lines | Disposition |
| --- | --- | --- |
| `SECURITY.md` | 6, 13 | Intentional published-version support; GitHub latest is v3.2.0. |
| `docs/APPIMAGE.md` | 190, 191, 194 | Historical original candidate path, version and checksum evidence. |
| `docs/RELEASE_VERIFICATION.md` | 12, 568 | Historical older-build warning and older-release smoke-header compatibility note. |
| `docs/audits/2026-09-13-product-quality-assessment.md` | 1, 4, 14, 18, 344 | Historical dated release/audit/video-production record or link to it. |
| `docs/audits/README.md` | 21 | Historical dated release/audit/video-production record or link to it. |
| `docs/demo-video/FOLLOWUP_VALIDATION.md` | 3 | Historical dated release/audit/video-production record or link to it. |
| `docs/demo-video/NARRATION.md` | 5 | Historical dated release/audit/video-production record or link to it. |
| `docs/demo-video/VALIDATION.md` | 3 | Historical dated release/audit/video-production record or link to it. |
| `docs/demo-video/YOUTUBE_PUBLISHING.md` | 4 | Historical dated release/audit/video-production record or link to it. |
| `docs/demo-video/captures/capture-001-002-003-005-009-010-011-012-013-014-015-016-017-018-019-020-021-022-023-024-025-026-027-028-029-030-032-036.json` | 2 | Historical screenshot/capture provenance; original version retained. |
| `docs/demo-video/captures/capture-013-023-024.json` | 2 | Historical screenshot/capture provenance; original version retained. |
| `docs/demo-video/captures/capture-013-023.json` | 2 | Historical screenshot/capture provenance; original version retained. |
| `docs/demo-video/captures/capture-013A-013B-028A-028B.json` | 2 | Historical screenshot/capture provenance; original version retained. |
| `docs/demo-video/captures/capture-028A.json` | 2 | Historical screenshot/capture provenance; original version retained. |
| `docs/demo-video/captures/capture-all.json` | 2 | Historical screenshot/capture provenance; original version retained. |
| `docs/demo-video/exam-additions/capture-011A-011B-011C.json` | 2 | Historical screenshot/capture provenance; original version retained. |
| `docs/demo-video/proof/capture-001-003-014.json` | 2 | Historical screenshot/capture provenance; original version retained. |
| `docs/demo-video/series/captures/capture-101.json` | 2 | Historical screenshot/capture provenance; original version retained. |
| `docs/demo-video/series/parsing-pasted-text/captures/capture-301-302-303-304-305-306-307-308.json` | 2 | Historical screenshot/capture provenance; original version retained. |
| `docs/releases/3.2.0-READINESS.md` | 1, 4, 14, 34, 42, 44 | Historical dated release/audit/video-production record or link to it. |
| `docs/releases/3.2.0-RELEASE-CHECKLIST.md` | 1, 5, 6, 14, 23, 29, 33, 34, 35, 46, 49, 79, 82, 83, 90, 111, 113, 114, 115, 116, 117, 118, 150, 188, 189, 190, 191, 192, 193, 209, 210, 211, 212, 213, 230, 231, 232, 233, 234, 261, 265, 267, 268, 269, 270, 271, 272, 274, 275, 276, 277, 278, 279 | Historical dated release/audit/video-production record or link to it. |
| `docs/releases/3.2.0.md` | 1, 3, 61, 71, 75, 76, 77, 78, 79, 80 | Historical dated release/audit/video-production record or link to it. |
| `docs/releases/3.2.1.md` | 7, 30 | Intentional prior-release comparison and historical notes link. |
| `docs/user-manual/FEATURE_INVENTORY.md` | 1, 5, 7, 51, 784, 992 | Historical September 14 / 50baed8 inventory and drafting scope. |
| `docs/user-manual/SCREENSHOT_MANIFEST.md` | 1, 11 | Historical screenshot/capture provenance; original version retained. |
| `docs/user-manual/SCREENSHOT_PLAN.md` | 1, 5, 100 | Historical capture-plan baseline and original viewport acceptance instructions. |
| `docs/user-manual/TERMINOLOGY.md` | 1 | Historical manual terminology audit title; vocabulary reference, not current version display. |
| `docs/user-manual/images/capture-metadata.json` | 3 | Historical screenshot/capture provenance; original version retained. |
| `tests/test_appimage_packaging.py` | 93, 96, 111, 112, 140, 157 | Intentional isolated mocked/synthetic version fixtures; no assertion about the current source release. |
| `tests/test_native_release_orchestration.py` | 39, 42, 43, 46, 63, 68, 72, 94, 96, 116, 130, 144, 145, 175, 184, 191, 192, 195, 203 | Intentional isolated mocked/synthetic version fixtures; no assertion about the current source release. |
| `tests/test_release_hygiene.py` | 94 | Intentional rejected obsolete release-candidate filename fixture. |

No screenshot was replaced, retaken or regenerated for version text. Historical
manual capture metadata remains paired with its original manifest. Current
reader-facing manual chapters identify 3.2.1; the original inventory/plan records
remain contextual history rather than a second runtime version authority.

Ignored generated-artifact names found in addition to text occurrences:

- `releases/DLMS-3.2.0-fedora44-x86_64`
- `build/release-packages/3.2.0/`: six native archives and `SHA256SUMS.txt`
- `build/appimage-evaluation/fedora44-candidate/DLMS-3.2.0-fedora44-x86_64.AppImage`
- `build/appimage-evaluation/browser-environment-fix/DLMS-3.2.0-fedora44-x86_64.AppImage`

These are historical/generated artifacts, not 3.2.1 source defects. This audit
does not claim that every binary contains no old strings; old binaries are
expected to contain their original versions. Dependencies' independent version
numbers and legacy-format compatibility identifiers are not application versions.

## Verification and handoff

See [readiness evidence](../releases/3.2.1-READINESS.md#validation-evidence) for
focused/full test results, link and tutorial validators and final diff hygiene.
The source change introduces no persistence schema or scoring changes.
All edits remain local for owner review; no commit, push, tag, package build or
release publication was performed.

