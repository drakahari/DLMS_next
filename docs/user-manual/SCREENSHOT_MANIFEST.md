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
| UM-01 | Dashboard and Today’s Review | Fully automatable | Captured | [UM-01-dashboard.png](images/UM-01-dashboard.png) | Populated recommendations and one genuine `This browser` checkpoint. |
| UM-02 | Build Quiz hub | Fully automatable | Captured | [UM-02-build-quiz-hub.png](images/UM-02-build-quiz-hub.png) | Current content-acquisition choices without a selected local file. |
| UM-03 | Generated Practice Smart View | Fully automatable | Captured | [UM-03-generated-practice-smart-view.png](images/UM-03-generated-practice-smart-view.png) | Refreshed with v2 synthetic lineage data; active dynamic view, generated badges, and aggregate source-quiz disclosures are visible. |
| UM-04 | Mixed Quiz Builder | Fully automatable | Captured | [UM-04-mixed-quiz-builder.png](images/UM-04-mixed-quiz-builder.png) | Four questions selected from two synthetic sources. |
| UM-05 | Duplicate Question Review | Fully automatable | Captured | [UM-05-duplicate-question-review.png](images/UM-05-duplicate-question-review.png) | Exact and possible matches in the advisory review. |
| UM-06 | Portable Quiz Bundle review | Partially automatable | Primary state captured | [UM-06-portable-quiz-bundle-review.png](images/UM-06-portable-quiz-bundle-review.png) | Validated collision/rename preview captured; export selection is an optional second frame. |
| UM-07 | Study Mode feedback | Fully automatable | Captured | [UM-07-study-mode-feedback.png](images/UM-07-study-mode-feedback.png) | Saved incorrect answer with immediate feedback. |
| UM-08 | Exam Mode in progress | Fully automatable | Captured | [UM-08-exam-mode.png](images/UM-08-exam-mode.png) | Multi-answer question in progress without correctness feedback. |
| UM-09 | Interrupted quiz recovery | Fully automatable | Captured | [UM-09-quiz-recovery.png](images/UM-09-quiz-recovery.png) | Real browser-local checkpoint with Resume and Start Over. |
| UM-10 | Which review should I use? | Fully automatable | Captured | [UM-10-review-options-guide.png](images/UM-10-review-options-guide.png) | Current Help comparison rather than an artificial collage. |
| UM-11 | Review Schedule | Fully automatable | Captured | [UM-11-review-schedule.png](images/UM-11-review-schedule.png) | Due Questions and Topic Retention shown together; Question Queue expanded with search and status filters. |
| UM-12 | Learning Intelligence and Mastery | Fully automatable | Captured | [UM-12-learning-intelligence-mastery.png](images/UM-12-learning-intelligence-mastery.png) | Mastery explanation open over a populated concept table. |
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
