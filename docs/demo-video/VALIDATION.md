# Final demo-video capture validation

Captured on develop/3.2.0 after the owner declared the UI visually stable.
Canonical deliverables: **36 PNGs** in `captures/`, **six contact sheets** at the
project root, and `video-manifest.json`. Proof and manual assets are unchanged.
No narration, audio, or video was generated.

## Capture and visual review

- Full 36-frame capture completed in clean isolated Firefox against disposable
  synthetic data. Purple & Gold, 1920 × 1080, device scale 1.
- Every final frame was visually inspected in sequence on labeled contact sheets.
  Dense intelligence, queue, Anki and Study/completion frames were also checked
  at full resolution. All recaptured frames were reviewed again.
- Real page controls, source data and server responses were used. No image text
  substitution, fabricated values, product CSS changes or data-provider calls.
- Overview frames intentionally show a long page continuing below the viewport;
  teaching subjects, their labels, and their relevant controls are visible.
  Scrolled detail frames retain contextual navigation, sometimes below its top.
- No private data, commercial question-bank material, debug overlays, native
  browser dialogs, stale Resume cards or cursor-obscured subjects were found.
- OCR uses the approved original source selection and separate staged draft.
  It is not portrayed as an end-to-end measured extraction result.

## Corrections and focused recaptures

The initial full capture revealed an empty Due-now filter and a trend that
became stable after the demonstrated wrong answers. Fixture v2 changes only the
synthetic Networking response sequence (same overall score) so the actual
calculated trend remains declining. The queue now uses the genuine Overdue
filter. Frame 013 corrects the answer and shows the explanation. No rendered
metrics were overridden.

Recaptured **001, 002, 003, 005, 009–030, 032, 036** (28 frames) for affected
fixture evidence, scroll margins, folder collapse state, filter state, source
comparison, or Anki selection. Frames **013, 023, 024** received an additional
framing pass; **013 and 023** received a final pointer/edge refinement. All
focused recaptures replayed preceding story actions without overwriting other
frames, preserving downstream data relationships. Capture sidecars record each
run; `video-manifest.json` points to the record for the current file and hashes
its exact contents.

## Fixture sanity

- Six original source quizzes, two generated reviews; five sources included in
  Learning Scope and one visible source excluded in Past Projects.
- Eighteen completed Exam attempts remain in History/Analytics. Demonstrated
  Study activity adds learning evidence without inventing Exam attempts.
- At frame 014: Networking has 20 responses, 50% overall / 20% recent accuracy,
  declining trend and 57% mastery; Access Control improves with 73% mastery;
  Data Safety is strong at 100%; Cloud has one response and a provisional 59%
  mastery value explicitly labeled Not enough data.
- The initial Dashboard has four due questions; after source practice the
  schedule has three overdue questions. Generated answers continue updating
  their actual source schedules. No due dates were rewritten to dress a screen.
- Source provenance resolves three source quizzes. Actual Finish Review succeeds
  after acknowledged Study saves and clears recovery ownership. The completed
  Library frame retains both the seeded Smart Review and finished Adaptive quiz.
- Duplicate Review finds two exact groups across original sources, including
  the excluded folder. Frame 030 filters to the intended risky-change pair.
- Bundle candidates include six source quizzes and exclude generated containers.
  Anki shows a real one-question selection and historical missed questions.

## Editorial review

All four optional frames remain: **017, 020, 033, 035**. 017 repeats some topic
intelligence, and 035 is the most expendable broad settings tour. 020 explains
the separate topic schedule; 033 broadens the optional AI workflow. Overview /
detail pairs 001/002 and 014/015 and Dashboard bookends 001/036 are intentional.
No files were deleted for editorial brevity. Planned duration: 402 seconds
before transitions, or 362 seconds without the four optional frames.

## Existing product issue observed, not changed

Purple & Gold correct-answer hover can replace the light feedback background
with a dark surface while retaining dark answer text. This was visible during
frame 013 capture; `.choice:hover` has higher selector specificity than
`.correct-choice` in `static/style.css`. Moving the real pointer off controls
restores the normal readable feedback appearance. The capture tool now does
that before screenshots. Production styling was not changed; this is a separate
potential UI fix, not an excuse to alter screenshot pixels.

## Automated validation

- `--list`: all 36 ordered recipes, no application/browser startup.
- Full capture and focused recaptures: passed, with successful cleanup.
- Focused tests: **12 passed** (`test_demo_video_capture.py` and
  `test_manual_screenshot_capture.py`). Includes final filename/count/state/hash
  consistency, sidecar provenance, optional flags, duration, PNG dimensions,
  dark-purple canvas checks and six contact-sheet dimensions.
- Asset builder: 36 source images validated; six labeled 1968 × 1824 sheets
  generated with 960 × 540 thumbnails; originals unchanged.
- Local documentation links and new-text whitespace checked.
- `git diff --check`: passed.
- No capture-created Firefox or server processes remained.
- Manual Light defaults, 1440 × 1000 dimensions and existing images unchanged.
- No production code, APP_VERSION, release metadata, or packaging changes.
- No commit or push. No unrelated broad application suites run.

## Targeted V3 visual expansion — 2026-09-19

Four additive proposal frames were captured with fixture v3 and alphanumeric IDs; the 36 V2 PNGs, six V2 contact sheets, canonical `video-manifest.json`, narration, audio, and assembled video were not regenerated.

- **013A:** all three matching answers are placed correctly; the empty answer pool, pair relationships, and three feedback rows are readable without clipping.
- **013B:** the original synthetic service map is fully visible; the selection marker is inside the Recovery copy region and correct feedback is visible.
- **028A:** the actual Content Pack report shows valid status, three dataset types, two tracked generated quizzes, zero warnings, and independent checks. The pack-detail route avoids displaying the disposable randomized data-root path.
- **028B:** the actual Study Packs catalog shows the expanded Practical Systems Lab pack, matching/image/mixed badges, dataset counts, options, and Create Quiz actions.
- The physical print layout was audited but not captured. Its paper-first white template is theme-independent, and the complete Letter sheet plus on-screen guidance exceeds 1080 pixels; forcing it into this set would break the Purple & Gold or no-clipping standard.
- All four final PNGs are 1920 × 1080, device scale 1, Purple & Gold, and backed by one coherent capture sidecar. Full-resolution visual inspection found no obscuring cursor, focus outline, private information, commercial content, or clipped teaching subject.
- The V3-only 1968 × 1224 contact sheet and hash-bearing sequencing manifest validate all four additions. Their 44-second target estimates a 7:27 V3 from the current 6:43.600 V2 render.
- Focused results: 11 demo-capture tests passed; 55 demo-build tests passed; 55 pack/catalog tests plus 39 subtests passed; 29 matching/OCR/image workflow tests passed. Python compilation and `git diff --check` passed.
- All 36 hashes in the canonical V2 manifest still match their PNGs. Capture cleanup left no Firefox, geckodriver, or demo server process.
