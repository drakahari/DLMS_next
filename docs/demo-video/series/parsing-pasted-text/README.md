# Parsing Pasted Quiz Text in DLMS — From Text to a Working Quiz

**Tutorial 14 · CANDIDATE — pending listening and editorial review.**
Ten scenes; 465 words; 3:22.900 spoken audio; **3:29.067** final runtime.
Separate and selectable English captions contain ten synchronized cues.

Recommended playlist position: immediately after Import and Repair. Existing
video identifiers and definitions are unchanged; playlist position is not a
renaming of previous tutorials.

[video.json](video.json) is the authoritative narration/storyboard and publishing
specification. [sample.txt](sample.txt) is original, reusable demonstration text.
The written companions are [Chapter 4](../../../user-manual/04-creating-and-importing-content.md#import-structured-choice-question-text)
and [Parsing settings](../../../user-manual/16-settings-and-runtime.md#configure-text-parsing-tools).

The ten static scenes cover method selection, numbered source and answer keys,
default settings, literal cleanup, source preview, differences and Build,
published library entry, single-answer verification, multiple-answer verification,
and choosing an alternative input workflow. Eight new Purple & Gold 1920×1080
captures use the real forms and parser in an isolated disposable data root.
No production behavior is changed and no private source material is used.

## Reproduce

Use the existing local Kokoro service at 127.0.0.1:7860 (af_heart, speed 1.0).
Run each command from the repository root:

```sh
.venv/bin/python tools/build_documentation_videos.py validate --all
.venv/bin/python tools/build_documentation_videos.py capture --videos parsing-pasted-text
.venv/bin/python tools/build_documentation_videos.py export --videos parsing-pasted-text
.venv/bin/python tools/build_documentation_videos.py narrate --videos parsing-pasted-text
.venv/bin/python tools/build_documentation_videos.py build --videos parsing-pasted-text
.venv/bin/python tools/build_documentation_videos.py verify --videos parsing-pasted-text
.venv/bin/python tools/build_documentation_videos.py delivery --videos parsing-pasted-text
```

Capture refreshes go to the existing review area and require deliberate promotion;
source hashes are not silently rewritten. Initial sources are under [captures](captures/).
Generated media, transcript, timed chapters, description, SRT, listening checklist,
and publishing JSON belong under `build/demo-video/series/parsing-pasted-text/`.
Use `delivery.mp4` for editorial review; nothing is published automatically.

Thumbnail specification: use capture 307, crop around the question and correct
answer, retain Purple & Gold, and add **TEXT TO QUIZ** in large readable type.
Do not finalize a thumbnail until the candidate is approved.

## Historical boundary

The manual deliberately says uploaded text preceded pasted-text creation.
The recoverable history records file-based parsing in `100cfb5` and paste creation
in `3fb453f`; this is not a claim about unavailable earlier prototypes. The
original public project is [DLMS_auto_quiz](https://github.com/drakahari/DLMS_auto_quiz).
History occupies only the opening narration; this is a modern task tutorial.

## Candidate validation — 2026-09-21

- All 14 series definitions and 93 capture references validate; all eight new
  screenshots were inspected at full resolution.
- The manual's exact sample parses as two questions with keys `A` and `AC`.
- 264 local manual/tutorial links and anchors resolve.
- Focused documentation/video tests: 58 passed, 565 subtests passed.
- Required non-browser gate: 1,793 passed, 104 deselected, 2,450 subtests passed.
- Required Firefox critical-workflow gate: 96 passed.
- Master verification: all 6,272 decoded frames match source pixels after the
  expected color conversion; ten scenes, current narration provenance, and
  matching separate/muxed English captions.
- Delivery: full decode passed; H.264 1920×1080 at 30 fps, AAC, selectable captions.
  Representative preview, library and multi-answer delivery frames inspected.
- 388 pre-existing screenshot, definition, MP4 and WAV hashes remained unchanged.
- `git diff --check` passed. No production/version/release changes.

Technical validation does not replace listening review. Review the generated
`LISTENING_REVIEW.md` before approving this candidate or publishing it.
