# V3 stability, Exam capture, and Content Pack layout follow-up

Branch: develop/3.2.0. The canonical review remains 37 scenes, 13,190 frames,
7:19.667, with 37 selectable English subtitle cues. No narration was regenerated.

## Root causes and fixes

1. The previous static renderer still applied five-frame chapter fades to black.
   Full-file black detection found twelve internal two-frame black intervals,
   starting at 55.933, 104.867, 130.133, 189.433, 216.433, 238.433, 290.533,
   310.833, 367.733, 394.867, 409.867, and 424.633 seconds. The final scene also
   faded out. These were deliberate filter outputs, not missing screenshots.
   Static mode now holds the screenshot through those slots and uses straight
   cuts. Audio lead frames, tails, scene durations, and subtitle times are retained.
2. Removing zoom/pan had removed geometric movement, but CRF 18 H.264 still
   quantized identical input frames differently. A one-second hold at 150 seconds
   contained 4 distinct decoded frame hashes, with alternating I/P/B-frame
   reconstruction. Static mode now uses CRF 0, eliminating temporal compression
   differences. The historical planned mode still supports its original fades
   and encoding. Regression coverage decodes two entire scene slots and requires
   exactly one pixel hash within each slot, including boundary frames.
3. Content Pack metrics used the generic dashboard icon-plus-copy grid with a
   56-pixel first column. Direct label/value/description children were auto-placed
   in that grid, forcing labels such as Generated Quizzes into the narrow column.
   A selector scoped to Content Pack report cards now stacks three text rows,
   aligns their left edges, and provides consistent spacing/line height. Existing
   theme variables and the outer four/two/one-column responsive grid are retained.
   No other summary-card selector or application behavior changed.

## Build verification

- Old MP4, SRT, timeline, changed screenshot, and protected hashes are archived in
  `build/demo-video/followup-before/`.
- Final MP4: `build/demo-video/DLMS-3.2-demo.mp4`, 47,691,291 bytes.
- H.264 lossless, 1920×1080, 30 fps, yuv420p, AAC, selectable English mov_text.
- All 13,190 decoded frames were compared against their actual PNG source after
  the same yuv420p conversion. Every frame matched exactly: no flat filler,
  missing image, fade to black, or per-scene pixel shimmer remains.
- All 37 audio mappings match authoritative narration and synthesis transforms,
  af_heart at speed 1.0, and the recorded WAV hashes.
- Every WAV and generation sidecar is unchanged. Encoded AAC and decoded PCM
  hashes match the preceding V3 build. Normalization and actual audio durations
  are unchanged. Source narration totals 390.300 seconds.
- All scene IDs, starts, frame counts, narration leads, and audio mappings match
  the archive. Runtime is unchanged, and the separate SRT is byte-identical.
- Muxed subtitles round-trip to the SRT. Full MP4 decode succeeds.
- Main remains 37; long plan remains 38. No long cut was generated.
- Thirty-nine existing screenshot hashes remain unchanged. Only 028A was
  deliberately recaptured to show the fixed cards; its manifest and V3 contact
  sheet were refreshed. All three new Exam stills were inspected at 1920×1080.
- Evidence: `build/demo-video/followup-validation.json` and
  `build/demo-video/pack-layout-review/`.

Lossless H.264 reports High 4:4:4 Predictive profile even though the actual pixel
format is yuv420p. This is a software-decodable review master; compatibility with
all hardware/browser playback paths is not claimed. A later delivery encode can
be evaluated separately without replacing this stable reference master.

## Supplemental captures and editorial decision

- `exam-additions/011A-quiz-timing.png`: real quiz editor with the timer changed to
  20 minutes, unsaved. This is a separate example from the following stills.
- `exam-additions/011B-exam-mode.png`: selected Exam answer, 90-minute source
  default, visible timer and Pause; no immediate Study feedback.
- `exam-additions/011C-exam-paused.png`: actual Pause overlay, frozen clock,
  frosted/covered question screen, and Resume button.

They use the existing isolated Firefox capture harness with original synthetic
content, Purple & Gold, 1920×1080, scale 1. The capture-only clock stop is not a
production change. No external study material or personal data was used.

These are retained as optional focused-Exam tutorial material. Inserting a setup
and pause detour under current Study narration would create a mismatch; adding
speech would change the approved pacing and require new audio. The overview
therefore retains all 37 approved narration clips and its existing sequence.
The physical-card section, long cut, and pronunciation transforms are unchanged.

## Tests and visual review

- Demo build/narration/capture/manual-capture/theme suite: **170 passed,
  364 subtests passed**.
- Content Pack catalog/import-review/validation and quiz recovery tests:
  **69 passed, 20 subtests passed**.
- Live isolated Firefox test: **1 passed**; all four themes at 1920, 1024, 768,
  and 420 pixels wide. Tests verify nonoverlapping stacked children, matching
  left edges, containment, single-column card interiors, and existing theme
  consistency assertions, with deliberately long pack metadata.
- Visual evidence inspected: Light 1920, Dark 768, Purple & Gold 1024, Maroon &
  Gold 420, and the refreshed Purple & Gold 1920 capture. Metrics remain readable,
  correctly aligned, and contained at each width.
- `git diff --check` passed. Browser/server processes use finally-based cleanup;
  no render intermediates remain. No full repository test suite was run.

## Changed source and planning files

- `static/style.css`
- `tools/build_demo_video.py`
- `tools/capture_demo_video_screenshots.py`
- `tools/demo_video_fixture.py`
- `tests/test_demo_video_build.py`
- `tests/test_demo_video_capture.py`
- `tests/browser/test_critical_workflows.py`
- `docs/demo-video/NARRATION.md` (transition guidance only; spoken text unchanged)
- `docs/demo-video/README.md`
- `docs/demo-video/SCREENSHOT_PLAN.md`
- `docs/demo-video/STORYBOARD.md`
- `docs/demo-video/FOLLOWUP_VALIDATION.md`
- `docs/demo-video/v3-additions-manifest.json`
- `docs/demo-video/v3-additions-contact-sheet.png`
- `docs/demo-video/captures/028A-content-packs.png`
- `docs/demo-video/captures/capture-028A.json`
- `docs/demo-video/exam-additions/` (three screenshots and capture sidecar)

APP_VERSION and release metadata are untouched. No commit, push, or publication.
