# DLMS 3.2.0 user-manual screenshot manifest

This manifest records the first reproducible capture of the 27 screenshots in
the [screenshot plan](SCREENSHOT_PLAN.md). All listed PNG files are real DLMS
application views captured with Firefox from an isolated synthetic data root.
No screenshot contains the repository owner's DLMS data or normal browser
profile.

## Capture standard

- **Application:** DLMS 3.2.0
- **Browser:** Firefox, clean headless WebDriver BiDi profile
- **Viewport:** 1440 × 1000 CSS pixels at device scale 1
- **Theme:** Light
- **Fixture:** `dlms-user-manual-3.2-v1`
- **Framing:** application viewport, with instructional sections scrolled into
  view where the plan calls for a focused capture
- **Annotations:** none baked into the source images
- **Output:** [`images/`](images/)

`Fully automatable` means the planned teaching state is represented by the
canonical asset. `Partially automatable` means the canonical asset represents
the primary state, while the plan also suggests a distinct optional second
frame. The second state remains automatable; it is deferred until human asset
review establishes that the extra image is worth maintaining. No entry requires
a native operating-system capture.

## Assets

Audit result: **21 fully automatable**, **6 partially automatable**, **0
manual/native-OS captures**, and **0 redundant entries**. All 27 IDs have a
captured primary PNG. For the six partial entries, the capture note identifies
the second state that remains intentionally outside the canonical 27-file set.
All 27 canonical PNGs are now referenced exactly once in the narrative manual;
the optional secondary states remain uninserted.

| ID | Title | Classification | Capture status | File | Capture note |
| --- | --- | --- | --- | --- | --- |
| UM-01 | Dashboard and Today’s Review | Fully automatable | Captured | [UM-01-dashboard.png](images/UM-01-dashboard.png) | Refreshed with the Manage Learning Scope link; populated recommendations and one genuine `This browser` checkpoint remain visible. |
| UM-02 | Build Quiz hub | Fully automatable | Captured | [UM-02-build-quiz-hub.png](images/UM-02-build-quiz-hub.png) | Current content-acquisition choices without a selected local file. |
| UM-03 | Generated Practice Smart View | Fully automatable | Captured | [UM-03-generated-practice-smart-view.png](images/UM-03-generated-practice-smart-view.png) | Refreshed with one Completed generated review badge and date; the Manage Learning Scope link, v2 synthetic lineage, active Smart View, and source-quiz disclosures remain visible. |
| UM-04 | Mixed Quiz Builder | Fully automatable | Captured | [UM-04-mixed-quiz-builder.png](images/UM-04-mixed-quiz-builder.png) | Four questions selected from two synthetic sources. |
| UM-05 | Duplicate Question Review | Fully automatable | Captured | [UM-05-duplicate-question-review.png](images/UM-05-duplicate-question-review.png) | Advisory matches with result-type/quiz/folder/search filters and page-scoped expand/collapse controls. |
| UM-06 | Portable Quiz Bundle review | Partially automatable | Primary state captured | [UM-06-portable-quiz-bundle-review.png](images/UM-06-portable-quiz-bundle-review.png) | Validated collision/rename preview with stacked summary metrics; export selection is an optional second frame. |
| UM-07 | Study Mode feedback | Fully automatable | Captured | [UM-07-study-mode-feedback.png](images/UM-07-study-mode-feedback.png) | Saved incorrect answer, navigation, and the three Question Tools. |
| UM-08 | Exam Mode in progress | Fully automatable | Captured | [UM-08-exam-mode.png](images/UM-08-exam-mode.png) | Multi-answer question in progress without correctness feedback. |
| UM-09 | Interrupted quiz recovery | Fully automatable | Captured | [UM-09-quiz-recovery.png](images/UM-09-quiz-recovery.png) | Real browser-local checkpoint with Resume and Start Over. |
| UM-10 | Which review should I use? | Fully automatable | Captured | [UM-10-review-options-guide.png](images/UM-10-review-options-guide.png) | Current Help comparison rather than an artificial collage. |
| UM-11 | Review Schedule | Fully automatable | Captured | [UM-11-review-schedule.png](images/UM-11-review-schedule.png) | Due Questions and Topic Retention shown together; Question Queue expanded with search and status filters. |
| UM-12 | Learning Intelligence and Mastery | Fully automatable | Captured | [UM-12-learning-intelligence-mastery.png](images/UM-12-learning-intelligence-mastery.png) | Refreshed with the Learning Scope summary behind the Mastery explanation and populated concept table. |
| UM-13 | Learning Diagnostics | Fully automatable | Captured | [UM-13-learning-diagnostics.png](images/UM-13-learning-diagnostics.png) | Repeated confusion and question-review signals from synthetic evidence. |
| UM-14 | History | Partially automatable | Primary state captured | [UM-14-history.png](images/UM-14-history.png) | Populated History list captured; attempt detail is an optional second frame. |
| UM-15 | PDF & Image Import | Fully automatable | Captured | [UM-15-pdf-image-import.png](images/UM-15-pdf-image-import.png) | Synthetic PDF selected with source-rights acknowledgement. |
| UM-16 | Question Review & Repair | Fully automatable | Captured | [UM-16-review-and-repair.png](images/UM-16-review-and-repair.png) | Complete, review, incomplete, and unassigned staging data. |
| UM-17 | Screenshot OCR source selection | Fully automatable | Captured | [UM-17-screenshot-ocr-selection.png](images/UM-17-screenshot-ocr-selection.png) | Repository-safe synthetic image selected without displaying a native file picker. |
| UM-18 | OCR matching Review & Repair | Fully automatable | Captured | [UM-18-ocr-matching-review.png](images/UM-18-ocr-matching-review.png) | Paired and unassigned OCR output in the real editor. |
| UM-19 | Image Study Editor | Fully automatable | Captured | [UM-19-image-study-editor.png](images/UM-19-image-study-editor.png) | Clickable-region editor with a keyboard-authored polygon. |
| UM-20 | External AI matching workflow | Partially automatable | Primary state captured | [UM-20-external-ai-matching.png](images/UM-20-external-ai-matching.png) | Provider-neutral Matching/Terminology builder captured; validated Review & Repair is an optional second frame. |
| UM-21 | AI Study Pack Builder | Fully automatable | Captured | [UM-21-ai-study-pack-builder.png](images/UM-21-ai-study-pack-builder.png) | Selected pack options and ZIP-return workflow. |
| UM-22 | Study Packs catalog | Partially automatable | Primary state captured | [UM-22-study-packs-catalog.png](images/UM-22-study-packs-catalog.png) | Learner catalog captured; Content Pack validation is an optional second management frame. |
| UM-23 | Law Case Review | Fully automatable | Captured | [UM-23-law-case-review.png](images/UM-23-law-case-review.png) | Fictional saved case with embedded Case Review activities. |
| UM-24 | Custom Anki Deck | Partially automatable | Primary state captured | [UM-24-custom-anki-deck.png](images/UM-24-custom-anki-deck.png) | Custom deck selection captured; printable-card preview is an optional second frame. |
| UM-25 | LAN/server lifecycle | Fully automatable | Captured | [UM-25-lan-server-lifecycle.png](images/UM-25-lan-server-lifecycle.png) | Captured from a real explicit LAN/server-mode process, with lifecycle controls disabled. |
| UM-26 | Validated backup restore | Fully automatable | Captured | [UM-26-backup-restore-confirmation.png](images/UM-26-backup-restore-confirmation.png) | Synthetic backup staged on the real review-before-restore screen. |
| UM-27 | Rebuild All Quiz Pages | Partially automatable | Primary state captured | [UM-27-rebuild-all-quiz-pages.png](images/UM-27-rebuild-all-quiz-pages.png) | Complete maintenance card captured; the browser-native confirmation is cancelled and deliberately omitted from the viewport asset. |

## Manual or native capture queue

None. The plan does not require Windows SmartScreen, macOS Gatekeeper, Finder,
native file pickers, or other operating-system UI. UM-27's browser-native
confirmation is intentionally not fabricated or baked into the application
viewport; the manual text documents the confirmation contract.

## Regeneration

From the repository root:

```text
.venv/bin/python tools/capture_user_manual_screenshots.py
```

The tool replaces only the named manual screenshot assets and writes machine-
readable capture details to
[`images/capture-metadata.json`](images/capture-metadata.json). Use a focused
refresh while reviewing one UI area:

```text
.venv/bin/python tools/capture_user_manual_screenshots.py --only UM-12,UM-13
```

The complete command should be used before accepting a refreshed set so the
metadata sidecar accounts for all 27 IDs.

## 3.3.0 refresh (current instructional assets)

The UM-01–UM-27 table above is the historical 3.2.0 capture set. The current
refresh documents application commit `57d536f9bb20f91e8b275555e8bbfad6f0d6e83d`
and documentation edits only. Source runs use Fedora 44, Firefox 157.0,
disposable profiles and synthetic quiz/certification/course records. No production
service, owner profile, credential identifiers or uploaded owner evidence is used.

Current assets are shared with in-app Help in `static/help_assets/`; chapters
reference those files rather than maintaining duplicate image copies. Help links
open the existing keyboard-accessible enlargement viewer. Markdown viewers can
open the linked/source image at its original size. Written steps remain complete.

| Current asset | Route / teaching state | Capture evidence |
| --- | --- | --- |
| `dashboard.webp` | Dashboard: primary plan, separate browser Resume entries, sequence and histories | `test_dashboard_generated_resume_identity_and_sequence` |
| `study-history-row.webp`, `study-history-expanded.webp` | Compact and expanded saved Study sessions, wrong-first correction and local timestamps | `test_compact_study_history_pagination_and_recovery` |
| `history.webp` | Exam History with Study History access and an explicitly ambiguous timestamp | Documentation safety/navigation check; crop ends after results panel |
| `learning-profile-current.webp` | Learning Profile with limited-evidence state and distinct study destinations | Documentation safety/navigation check |
| `exam-plan-setup.webp`, `exam-plan-availability.webp`, `exam-plan-selection.webp`, `exam-plan-dashboard.webp` | Real plan setup, Study days, selection and primary study action | `test_exam_plan_setup_dashboard_practice_and_help` |
| `settings-appearance-theme.webp`, `settings-appearance-save.webp`, `sidebar-theme-selector.webp`, `settings-layout-study-areas.webp`, `settings-layout-restore.webp` | 26-choice selector, separate Save, independent IT/Law choices, scoped Restore | `test_help_screenshot_capture_controls` |
| `certifications-form.webp`, `certifications-goal.webp`, `certifications-use.webp`, `certifications-ai.webp`, `certifications-display.webp` | Independent files, short goal, explicit selected links, manual AI handoff and Settings count/sort | `test_certification_guided_nine_credentials` |
| `certifications-training.webp`, `certifications-training-library.webp` | Add training and reusable library showing exact 9 h 22 min plus distinct older 9 h credit association | Simple training and guided nine-credential checks |
| `certifications-cycle.webp` | Three independently labeled dates and explicitly unclassified old date | `test_certification_deadline_dates` |
| `settings-backup.webp`, `settings-reset_remove.webp` | Current backup controls and eight destructive scopes/warnings | Documentation safety/navigation check; reset crop excludes the machine-specific path and final removal control |

All published crops are actual unmodified UI regions, without compositing or
invented controls. Cropping excludes irrelevant margins and machine-specific
paths. Sample dates, counts and IDs are illustrative data, not defaults or proof
of certification ownership. Reset/removal controls were never executed to obtain
these images. Per-asset dimensions/hashes and commands are retained in the task
report; refresh instructions are in [Help screenshot maintenance](../help-screenshots.md).

Representative desktop/narrow Light, Dark and Ethereal application/Help images
are retained under `/home/drak/.cache/dlms-documentation-20261009-rjfygunb/screenshots`.
The same directory contains local Markdown reading-preview captures; these are
QA artifacts, not a configured canonical PDF/export pipeline. Older materially
unchanged UM images remain dated by the original table. The obsolete review-options
illustration and old mastery explanation were removed from the current chapters.

### Portable selection refresh (2026-10-09)

`images/UM-06-portable-quiz-selection.webp` shows the actual updated application
with disposable sample courses. It replaces no owner content and supplements
UM-06's existing import-preview image. Refresh it from the
`test_portable_batch_selection_and_label_grading[light]` browser check using
`DLMS_BUNDLE_CAPTURE_DIR`; inspect the captured crop before copying it to this
manual and `static/help_assets/portable-bundle-selection.webp`. The same Help
image supports its existing full-size enlargement link.

### Portable preservation selection check

- `images/UM-06-portable-quiz-preflight.webp`: actual isolated sample preflight, two warning quizzes and one blocked quiz; repeated labels, empty text, no answer and missing images are distinguished. Source: `test_portable_complete_preflight_and_explicit_editor`; refresh with `DLMS_BUNDLE_CAPTURE_DIR` and copy the Light crop.
