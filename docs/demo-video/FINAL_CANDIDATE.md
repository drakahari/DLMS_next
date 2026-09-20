# CONTENT COMPLETE / FINAL CANDIDATE

Not publicly released. Overview content is frozen except actual defects identified
by the user during final review. Future detail belongs in focused videos.

## Final master

- Main: **40 narrated scenes**, **911 words**, **7:45.700**.
- Long plan: **41 scenes**, 940 words; not generated.
- Master: `build/demo-video/DLMS-3.2-demo.mp4`.
- Size: **49,791,315 bytes** (49.79 MB / 47.48 MiB).
- SHA-256: `7a247ac5fc64adf216bcd9fcf3c3d4434aa63694972473191b58826255283209`.
- 1920×1080, 30 fps, H.264 CRF 0 lossless yuv420p static holds, clean cuts.
- Audio: af_heart, speed 1.0; unchanged two-pass normalization, AAC 48 kHz mono.
- Spoken audio: **413.200 seconds (6:53.200)**. Shortest 024: 5.275 seconds;
  longest 008: 16.625 seconds; average: 10.330 seconds.
- Runtime increase over the prior 7:19.667 V3: **26.033 seconds**.
- Separate SRT: `build/demo-video/DLMS-3.2-demo.srt`, **40 cues**, also muxed as
  selectable English mov_text. Not burned in.
- Prior master, timeline, SRT, production manifest, and all prior WAVs/sidecars:
  `build/demo-video/archive-before-final-exam/`.

## Incremental narration and sequence

New 011A (6.825 seconds): “For assessment, each quiz has a configurable Exam Mode
time limit, while Study Mode stays untimed.”

New 011B (7.350 seconds): “In this separate Exam example, answers stay selected,
but correctness and explanations wait until you finish.”

New 011C (7.425 seconds): “Pause freezes the countdown and obscures the exam
behind this overlay. Resume continues the same attempt.”

Only existing scene 012 was revised, adding “Back in Study Mode” before its
approved feedback explanation; its new clip is 10.375 seconds and still fits the
existing 12-second visual slot. The three new visual slots are 9, 9, and 8.033
seconds. All other narration remains verbatim.

Reused 36 WAVs and generation sidecars are byte-identical to the archive:
001, 002, 003, 004, 005, 006, 007, 008, 009, 010, 011, 013, 013A, 013B, 014, 015, 016, 018, 019, 021, 022, 023, 024, 025, 026, 027, 028, 028A, 028B, 029, 030, 031, 032, 033, 034, 036.

Sequence: **011 → 011A → 011B → 011C → 012**, then the existing
**013 → 013A → 013B → 014** and **028 → 028A → 028B → 029**.
017/035 remain cut; 020 is long-only; 033 remains included.

## Audit and visual review

The editor saves a per-quiz duration used when Exam Mode starts; Study Mode is
untimed. The runtime suppresses immediate correctness/explanations and Study
tools during Exam Mode. Pause freezes countdown updates and blurs/covers the
question wrapper; Resume restores the same attempt and remaining countdown.
This is visual obscuring, not secure lockdown or proctoring. Source references
and limitations are recorded in NARRATION.md's assessment audit.

Opening, OCR/imports, timing, Exam, Pause, Matching, Hotspot, Content Packs,
Study Packs, the physical-card narration point, and closing were inspected.
Encoded frames for all three Exam additions and corrected 028A were inspected
at full resolution. The setup, assessment, and Pause stills have distinct roles;
012 explicitly returns to Study feedback. No new narration/visual mismatch was
found. The timing field is an unsaved 20-minute edit; narration explicitly calls
the 90-minute Exam screen a separate example. No save or continuing configured
20-minute attempt is implied.

All **13,971 decoded frames** match their source screenshots after the same
expected yuv420p conversion. Each scene has one decoded pixel hash throughout
its hold. This verifies no unwanted blank/brown frames, geometric movement,
resampling, zoom/pan, or shimmer. Corrected 028A is included unchanged. All 43
capture hashes remain unchanged; nothing was recaptured.

Existing limitations remain: physical cards are mentioned over selection UI,
not a print-layout preview; dense interface labels benefit from full-screen
1080p playback; the paused question screen is intentionally blurred. Lossless
H.264 uses High 4:4:4 Predictive profile with yuv420p pixels, so some hardware or
browser players may need the later delivery encode. No delivery encode was made.

## Validation

- **129 focused automated tests passed**: build, narration, captures, manual
  capture tooling, and quiz recovery. Includes deterministic main/long/audition
  mapping, Exam screenshot hash-drift rejection, focused generation ordering,
  stale-text/synthesis/voice/speed/hash rejection, and real FFmpeg stability smoke.
- All 40 WAVs passed ffprobe and decode validation and match authoritative text,
  synthesis transforms, voice, speed, filenames, and recorded payload hashes.
- Exactly four clips were generated/replaced: 011A, 011B, 011C, 012.
- Every final narration interval is non-silent; minimum measured RMS is
  3834.648. Every narration has at least a 0.6-second tail.
- All subtitles match actual audio timing; muxed English SRT round-trips to the
  separate 40-cue SRT. No truncation; full MP4 decode succeeds.
- Dimensions, frame rate, codecs, lossless/static filters, deterministic ordering,
  capture hashes and corrected Content Packs image verified.
- Temporary render/TTS intermediates cleaned. No browser was started in this pass.
- `git diff --check` passed. Full repository suite was not run for this tooling-only pass.
- Machine-readable evidence: `build/demo-video/final-candidate-review/validation.json`.
- [Listening checklist](LISTENING_REVIEW.md): exact final timestamps for Exam,
  pronunciation terms, Matching/Hotspot, Packs, and physical-card mention.
  Human listening and final approval remain pending; automated checks do not
  claim to establish pronunciation quality.

## Files changed and boundaries

Narration: NARRATION.md and NARRATION_PLAIN.txt. Planning: README.md,
STORYBOARD.md, SCREENSHOT_PLAN.md, exam-additions-manifest.json,
FINAL_CANDIDATE.md and LISTENING_REVIEW.md. Tooling: build_demo_video.py,
generate_demo_narration.py, capture_demo_video_screenshots.py. Tests:
test_demo_video_build.py, test_demo_narration.py, test_demo_video_capture.py.

No production application files changed in this pass. The already-completed
Content Packs CSS fix remains intact. APP_VERSION/release metadata are untouched.
Only local Kokoro at 127.0.0.1:7860 was used. No long cut, delivery encode,
publication, commit, or push.

Future focused videos: PDF/OCR/CSV importing; Review & Repair; Exam Mode and
timing; Matching/Hotspot; Study Packs/Content Packs; Anki/physical cards; Learning
Intelligence; Generated Practice; Learning Scope. Do not extend the overview
further unless final review identifies an actual defect.
