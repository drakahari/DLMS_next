# DLMS demo-video project

Screenshot capture is complete on **develop/3.2.0** after visual stabilization.
The production sequence uses the **36 unchanged V2 screenshots** plus four
approved V3 additions in [captures/](captures/). The revised
[V3 narration/editorial plan](NARRATION.md) and
[recording script](NARRATION_PLAIN.txt) contain **37 scenes, 859 words**, with a
7:05 minimum editorial timeline and an estimated complete runtime of about
**7:19** after narration. The existing V2 review build still uses **af_heart** at
speed 1.0 and runs **6:43.600**; no V3 narration audio, subtitles, or video have
been generated.

The targeted V3 expansion shows completed Matching and Hotspot interactions
after 013, then Content Pack management and the Study Packs catalog after 028.
Review the additions in [v3-additions-contact-sheet.png](v3-additions-contact-sheet.png)
and [v3-additions-manifest.json](v3-additions-manifest.json). Their visual holds
total 44 seconds, while tightening existing Scene 028 makes the complete main
editorial target 35 seconds longer than V2.

The V1 build (6:37.200) is archived. See the [V2 review build](#complete-v2-narrated-review-build),
[editorial audit](EDITORIAL_V2.md) and [production workflow](#video-production-workflow).
This is not a release announcement.

Editing handoff: [video-manifest.json](video-manifest.json), [storyboard](STORYBOARD.md),
and contact sheets [1](contact-sheet-01.png), [2](contact-sheet-02.png),
[3](contact-sheet-03.png), [4](contact-sheet-04.png), [5](contact-sheet-05.png),
[6](contact-sheet-06.png).

## Capture standard

- **1920 × 1080 CSS pixels**, 16:9, device scale 1; PNG viewport captures.
- **Purple & Gold** by default; `--theme` also accepts Light, Dark, Maroon & Gold.
- Headless Firefox/BiDi with a new disposable profile, no browser chrome,
  personal bookmarks, operator data, or external provider visits.
- Generic identity: **DLMS Demo Training & Practice Center**; **Demo Learner**.
- Original synthetic content only. No certification brands, commercial question
  banks, imported personal content, or copyrighted training images.
- Real page layout; no text replacement, simulated UI, zoom changes, or CSS
  reflow for video. Animation/caret suppression reuses the manual harness.
- Overview frames retain navigation context. Teaching frames scroll a named
  section into view; narration should not ask viewers to read the entire page.

1080p is a standard video canvas and passed the three-frame Firefox proof at
scale 1. It gives the intelligence table room for all four concepts while the
Dashboard's two recommendations remain readable. The manual's 1440 × 1000
portrait-like canvas is not reused. Full-size inspection is required: a
thumbnail or a scaled chat preview cannot establish final video readability.

## Plan and commands

[SCREENSHOT_PLAN.md](SCREENSHOT_PLAN.md) is the capture manifest.
[STORYBOARD.md](STORYBOARD.md) gives viewer attention, timings, and narration
objectives, not final narration prose. The Python `FRAMES` contract is the
machine-readable manifest; `--list` prints all per-frame state requirements.

```sh
# Side-effect-free listing, no application import/server/browser:
.venv/bin/python tools/capture_demo_video_screenshots.py --list

# Preparation proof ONLY (three frames):
.venv/bin/python tools/capture_demo_video_screenshots.py \
  --only 001,003,014 --theme 'Purple & Gold' --output docs/demo-video/proof

# Validate real states without writing any PNGs:
.venv/bin/python tools/capture_demo_video_screenshots.py \
  --check --only 023,024,025 --output docs/demo-video/validation

# Regenerate the canonical full set: no --only means the complete sequence.
.venv/bin/python tools/capture_demo_video_screenshots.py \
  --theme 'Purple & Gold' --output docs/demo-video/captures
```

Requires the repository venv, Firefox, Pillow and the existing application/test
browser dependencies. Run from the repository root. Each invocation creates a
new temporary server data root, marks it as capture-owned, and seeds it through
normal quiz publication. Direct server mode refuses an unowned root. There is
no option to point at production data. It never reads production configuration.
Output is restricted to a subdirectory of `docs/demo-video`; UM assets cannot be
overwritten by this tool. Focused runs select IDs in story order.

Each run writes its own JSON sidecar with selected IDs, exact state recipes,
version read from the app, Git revision/dirty flag, theme, viewport, fixture
version, capture time, and evidence date anchor. Failed runs do not claim a
complete sidecar. Existing unrelated frames are not relabeled by a focused run.
`--check` writes check metadata, not screenshot files. Browser/server process
groups and temporary data are cleaned in nested `finally` blocks, including
startup failures. Interrupt with Ctrl-C, not an uncatchable process kill.

The sibling tool imports the manual harness's Firefox, screenshot and process
helpers. The only manual-tool extensions are an optional server entrypoint and
startup-failure cleanup. Its default seed, Light theme, viewport, filenames and
CLI remain unchanged. No new framework or production theme changes.

## Synthetic learner fixture

[`tools/demo_video_fixture.py`](../../tools/demo_video_fixture.py) defines the
original questions, evidence and names. No external demo-launch kit was found
in the repository or nearby Documents/workspace locations checked; this is a
self-contained baseline, not a claim to have imported an unavailable kit.

| Folder | Content / purpose |
|---|---|
| Core Skills | Everyday Data Safety; Network Troubleshooting; Practical Access Decisions; Change Readiness Checklist |
| New Horizons | Cloud Planning Basics, with one answer and two unseen questions |
| Past Projects | Past Project — File Organization; excluded from Learning Scope, still visible/playable |
| Uncategorized | No ordinary content needed; still manageable in Learning Scope |
| Generated Practice (virtual) | Adaptive Study — What I Need Most; three canonical source questions |
| Completed Generated Practice (virtual) | Retained Smart Review — Core Skills; same source provenance |

There are six source quizzes and two generated containers. Three established
concepts each have 18 responses across six complete synthetic Exam attempts;
all answer labels, correctness, scores and missed snapshots agree. Data Safety
is strong; Networking declines; Access Control improves (it can still be
classified Weak because lifetime accuracy is 50%); Cloud has too little evidence
for a reliable mastery claim. Do not rename a calculated category just to fit
narration. One deliberate included exact duplicate makes source comparison
useful without filling pages with duplicates. The excluded source also reuses
one original question, so duplicate review remains an all-library workflow.

Evidence is anchored to UTC noon on the capture date, at fixed relative ages;
IDs, content, ordering and response patterns are deterministic. Dates and
schedule labels can change across calendar days and are recorded in metadata.
This is reproducible synthetic state, not a frozen application clock. Recheck
real counts before final narration. The retained completion marker is a fixture
of past successful completion; frame 024 separately exercises the **real**
Finish Review handshake on Adaptive Study. No historical Study sessions are
reconstructed or mass-marked in the application.

Every frame starts after leaving any quiz page and clearing only the disposable
browser storage. Thus focused runs do not depend on earlier screenshots or
accidentally create Resume cards on the opening Dashboard. In a full run,
server-side saves persist: finishing Adaptive adds it to Completed. Capturing
025 alone shows the pre-seeded completed Smart Review. The sidecar identifies
the selection; do not splice conflicting counts into a final video.

### Import and portability setup

- The tool creates `study-skills.png` from original text inside the disposable
  data root, and selects it through Firefox's file-upload command. No native
  file dialog, external OCR provider, or protected source is involved.
- Review & Repair is a **seeded synthetic staged draft**, not a measured result
  of the image in frame 008. It contains one complete and one missing-answer
  question. The transition should say that extracted material needs review,
  not claim this particular OCR execution produced these results.
- Before final capture, if a continuous import story is desired, create an
  original two-question source matching the draft, run the actual local OCR/PDF
  analysis, review the result, and replace the draft recipe with that validated
  route. Do not invent OCR success/confidence. Current plan teaches the two
  screens separately and does not show extraction running.
- Bundles use the real source-only candidate catalog. No staged import success
  or download confirmation is fabricated. A validated bundle-import preview is
  optional future refinement, not required for this short story.
- Anki uses original source questions and missed records. Do not launch Anki or
  an AI provider. Question Tools are visible; no clipboard contents are exposed.

## Current-product audit and exclusions

The plan follows current `dlms/rendering/quiz_artifacts.py`, `static/script.js`,
`static/quiz-recovery.js`, `dlms/services/generated_practice_lifecycle.py`,
`templates/quiz/library.html`, `static/learning-intelligence.html`,
`static/review-schedule.html`, `templates/quiz/duplicates.html`,
`dlms/services/quiz_duplicate_view.py`, and the existing manual capture tool.

- Generated Practice and Completed Generated Practice are virtual presentations
  in the unfiltered Library, not physical protected folders. The Generated
  Practice Smart View includes both lifecycle states in their normal folder
  grouping, with completion badges. Provenance uses actual source payloads.
- Finish Review requires all Study saves and server verification; merely
  answering the last question is not shown as closing a generated session.
- Completed sessions stay playable. Recovery/Resume is independent of a previous
  completion. This video avoids stale Resume cards rather than changing DLMS.
- Scope is independent of Hide; history and schedules are preserved. Scope
  screenshots use actual excluded-folder configuration in the disposable root.
- Queue collapse and status filters are real controls. “Due” and “Overdue” are
  separate filters; the Due filter is not described as all overdue backlog.
- Duplicate results are paginated at 20 groups. This small fixture needs one
  page; do not seed 21 duplicates merely to demonstrate pagination. Small result
  sets expand by product default, which the manifest records.
- Copy Question copies the rendered AI-ready context without opening/sending to
  a provider; Review with AI opens the configured provider. Do not describe
  automatic image embedding or hidden Exam answers.
- Current Study panel and single branded quiz-title area are used as rendered;
  neither is replaced with manual-screenshot-era markup.

Leave Exam timers, destructive reset/restore confirmation, personal host/IP
screens, native file dialogs, empty study-pack catalogs, niche law/medical
workflows, and broad diagnostics out of the main story. Mixed Quiz remains a
manual tool and is not presented as transient Generated Practice. These are
editorial omissions, not missing product support.

## Proof review and final gate

Only [three proof PNGs](proof/) were captured. All are 1920 × 1080 Purple & Gold,
with original synthetic quiz names, generic identity and no debug overlays or
browser chrome. Dashboard has two genuine recommendations and no Resume.
Intelligence fits the scope summary, metrics and four concept rows. Library is
a focused teaching frame with active and collapsed completed groups plus source
cards; the sidebar is scrolled and its top is clipped. This remains a historical proof; final frame 003 now collapses surrounding
groups to give the source folder more room. Leave small margins when choosing the final
scroll position; do not solve framing by changing product CSS.

## Final handoff and regeneration

All final frames were visually reviewed in order on the six contact sheets,
with full-resolution checks of dense intelligence, queue, Anki and Study states.
See [VALIDATION.md](VALIDATION.md) for findings, recaptures and checks.
The original proof directory remains unchanged.

```sh
# Recapture selected frames while replaying earlier answers/completion first:
.venv/bin/python tools/capture_demo_video_screenshots.py \
  --only 013,023 --replay-prefix --theme 'Purple & Gold'

# Rebuild contact sheets and production metadata without altering screenshots:
.venv/bin/python tools/prepare_demo_video_assets.py
```

Fixture v2 adjusts the Networking response sequence so its declining trend
survives the two demonstrated source Study sessions. Scores and selections
remain consistent; no rendered percentages were altered. Frame 013 corrects
the initial wrong answer, exposing the real explanation. Frame 019 selects
Overdue rather than the empty Due-now subset. Frame 030 filters the intended
source duplicate and 032 makes a real single-question Anki selection.

A focused recapture writes only requested PNGs. `--replay-prefix` executes prior
story actions without recapturing their images, preserving downstream learning
counts and lifecycle state. Without it, focused capture uses a fresh fixture.
The asset tool selects the newest per-frame capture record and emits hashes;
keep all capture sidecars for provenance. Its six 1968 × 1824 PNG sheets contain
six 960 × 540 labeled thumbnails each. Original screenshots stay untouched.

The narration/editorial phase is complete. [NARRATION.md](NARRATION.md) owns the
revised cut and timing; the capture manifest retains its original estimates and
provenance. The assembly infrastructure and silent preview are now available;
narration recording and final narrated assembly remain future work.

## Video production workflow

[`tools/build_demo_video.py`](../../tools/build_demo_video.py) uses Python's
standard library plus **FFmpeg/ffprobe on PATH**. It never imports or starts
DLMS, calls a voice provider, or installs packages. FFmpeg must provide
`libx264`, AAC, PCM WAV, `mov_text`, and the standard motion/audio filters.
Missing executables or capabilities produce an explicit error.

Run these commands from the repository root. No application virtual environment
is needed for assembly; use the repository venv for pytest.

```sh
# Validate narration/capture contracts, image hashes/dimensions and media tools.
python tools/build_demo_video.py validate --cut main
python tools/build_demo_video.py validate --cut long

# Export individual spoken passages and their scene/audio mapping.
# Export alone works even without FFmpeg/ffprobe.
python tools/build_demo_video.py export --cut main
python tools/build_demo_video.py export --cut long

# Silent editorial preview: no audio inputs or subtitle estimates required.
python tools/build_demo_video.py preview --cut main
python tools/build_demo_video.py preview --cut long
```

Add `--overwrite` to replace an existing MP4 or SRT. The full main preview has
already been generated, so reproducing it requires that flag. Failed rendering
does not replace a previous completed video. All temporary segment media lives
in a disposable `.render-*` directory and is removed on success, error, or
normal interruption. An uncatchable process termination may require manually
removing the abandoned `.render-*` directory.

### Sources and generated production manifest

**NARRATION.md remains the sole editorial authority** for scene order,
inclusion, spoken text, target duration, focus, and static presentation.
`NARRATION_PLAIN.txt` must agree exactly with its main cut. The builder fails
on unrecognized scene fields instead of silently dropping narration. The
V2 and V3 additions capture manifests supply image paths and hashes; their
capture-phase timing estimates are not used for assembly. Neither document is
rewritten.

The tool derives `build/demo-video/production-manifest.json` on export or
assembly. This generated manifest contains all 40 records, included cuts,
narration, target seconds, image/hash, future audio name, text name, visual
focus, static-presentation/transition instructions, and source-document hashes.
It is a reproducible output, **not a second file to edit**. No tracked production
JSON is needed. The builder always derives a fresh manifest from the sources.

Main includes **37 scenes**: all except 017, 020, 035. Long includes **38**:
all except 017 and 035. Scene 033 is retained in both. No source image is deleted.
The long cut adds 020 at its existing sequence position. Additive IDs retain
their deterministic positions after 013 and 028.

Generated files stay in the already ignored `build/demo-video/` directory:

| Path beneath `build/demo-video/` | Purpose |
| --- | --- |
| `production-manifest.json` | Derived metadata for all 40 source scenes |
| `narration-text/main/001.txt`, `013A.txt`, etc. | 37 main-cut files, spoken text only |
| `narration-text/long/001.txt`, `013A.txt`, etc. | 38 long-cut files, including 020 |
| `narration-text/main/index.json` and `long/index.json` | Scene, image, target seconds, text filename and future audio filename |
| `audio/001.wav`, `013A.wav`, etc. | Future narration inputs supplied by the user |
| `DLMS-3.2-demo-silent-preview.mp4` | Main preview, no audio or subtitle streams |
| `DLMS-3.2-demo-long-silent-preview.mp4` | Long preview when requested |
| `DLMS-3.2-demo.mp4` and `.srt` | Future main narrated output and sidecar captions |
| `DLMS-3.2-demo-long.mp4` and `.srt` | Future long narrated output and sidecar captions |
| `*.timeline.json` | Actual frame/audio timeline, input hashes, media versions and encoded stream validation |

Paths in the production manifest are relative to the repository/image base
stated in the JSON. Each text-export index resolves text filenames in its own
directory and audio filenames under its `audio_base`. Use a different
`--work-dir "build/demo-video alternate"` for another assembly workspace;
the command requires an output subdirectory of the repository's `build/` tree.
Absolute or relative `--audio-dir` paths, including spaces, are supported.

### Narration audio contract

Place future recordings in **`build/demo-video/audio/`**, using exactly
**`001.wav`, `002.wav`, …** with stable scene IDs; the additions use
**`013A.wav`, `013B.wav`, `028A.wav`, and `028B.wav`**. Keep one take per
included scene; filenames do not change when a scene is cut. Main needs 37
files; long also needs `020.wav`. Known excluded scene files are ignored, and
never required. Files are read only.

Use **lossless PCM WAV, mono or stereo**, preferably 48 kHz. Other PCM sample
rates are resampled non-destructively during assembly. Compressed files such as
MP3/M4A are deliberately unsupported in this first version; convert them to
separate WAV copies before assembly. Do not merely rename their extension.
Unmapped audio names, missing clips, malformed media, unsupported streams,
non-finite/empty durations, or decode errors fail validation with scene IDs.

Record only the exported passage. Avoid large leading/trailing silence: the
whole supplied clip is treated as the scene's narration span. The builder can
validate filenames and media, but cannot verify that a narrator spoke the
correct passage. Review each recording against its text export before assembly.
The voice may be human or generated externally; the tool has no provider,
account, API-key, network, or cloud-service dependency.

Once real audio exists, these commands become usable:

```sh
# Check every required clip before rendering.
python tools/build_demo_video.py validate --cut main --require-audio

# Build main MP4, sidecar SRT and actual timeline.
python tools/build_demo_video.py build --cut main

# Also include English captions as an optional selectable MP4 subtitle track.
python tools/build_demo_video.py build --cut main --mux-subtitles --overwrite

# Long cut requires 020.wav in addition to the main recordings.
python tools/build_demo_video.py build --cut long --mux-subtitles

# Generate just the SRT from the same actual-audio timeline, without video.
python tools/build_demo_video.py subtitles --cut main
python tools/build_demo_video.py subtitles --cut long
```

The `subtitles` action also writes a `.subtitle-timeline.json` audit file. Add
`--overwrite` if the SRT already exists. Use identical `--cut`, `--tail`, and
audio inputs for standalone subtitles and the corresponding video. Changing
a recording requires regenerating both. Missing narration is an error for
`build` and `subtitles`; only the explicit `preview` action is silent.

### Timing and transitions

Silent previews use the V3 editorial targets: **425 seconds main**, **438 seconds
long**, at 30 fps. Narrated slots use the greater of the editorial viewing
minimum and **actual ffprobe audio duration + incoming visual lead + tail**,
rounded up to a whole video frame. The tail defaults to **0.6 seconds** and
can be adjusted with `--tail 0.8`. It must cover the outgoing fade. Narration is
never sped up or truncated to fit the old estimate; a longer take extends the
scene and every subsequent timestamp. Extra viewing time in the editorial
target is retained, including the completion message and closing hold.

**Static screenshots are the production default** (`--motion none`) across main,
long and audition rendering. Native 1920×1080 images are held without scaling,
zoom, pan or frame interpolation, keeping small UI text and borders stable.
Only the existing chapter fades intentionally vary image pixels over time; lossy
encoding can still produce small decoded-pixel differences. Every V3 production
scene is marked static. The legacy `--motion planned` compatibility option is
still accepted, but it adds no movement when all scene metadata is static. The
generated timeline records the selected mode and exact filters.

Within workflows, transitions are clean cuts. At chapter/example boundaries
006, 009, 011, 014, 018, 021, 026, 028, 031, 033, 034 and 036, this implementation
uses a **short fade through black**, an intentional simple alternative to the
suggested cross-dissolve. Five frames on each side make approximately one third
of a second total, entirely inside existing scene slots. The final scene also
fades out. No scenes or narration overlap. After an incoming fade, narration
starts five frames into the new scene; the outgoing fade fits in its tail.

Output is MP4 with **H.264, 1920 × 1080, 30 fps, yuv420p**, CRF 18, and fast-start
metadata for web playback. Narrated output uses **48 kHz mono AAC at 192 kb/s**.
Processing is sequential with bounded FFmpeg calls, avoiding a large graph
holding every 1080p scene in memory. The timeline and settings are deterministic;
byte-identical encoding across different FFmpeg builds/platforms is not promised.

### Normalization and subtitles

The default is **two-pass FFmpeg `loudnorm` for each scene**, targeting
**−18 LUFS integrated, −2 dBTP true peak, LRA 11**. Scene-wise measurement helps
match separately recorded takes. Linear correction is requested; FFmpeg may
use dynamic correction when required by the peak/range constraints. Only
temporary copies are processed. Short clips receive temporary measurement
padding, then return to the exact frame-aligned slot length. The builder does
not fade speech, overlap narration, or destructively alter source files.
Completely silent/unmeasurable input fails normalization rather than being
treated as narration. Use `--normalization none` for already mastered input.
Final listening review with the chosen voice remains necessary.

Subtitles use **one block per scene**, from its actual audio start to its
actual audio end, excluding the visual tail. This is scene-level timing, not
word alignment or sentence-level speech recognition. Internal silence remains
inside that span. No approximate SRT is emitted for a silent preview. The
sidecar is always available for narrated output; `--mux-subtitles` optionally
adds a selectable English `mov_text` track. Captions are never burned into the UI.

### Production validation

The first main silent preview was generated with FFmpeg/ffprobe **8.1.2**:
`build/demo-video/DLMS-3.2-demo-silent-preview.mp4`, **375.000 seconds**, **11,250
frames**, H.264/yuv420p, 1920 × 1080, 30 fps, no audio/subtitle streams, about
40 MiB. Full decoding completed without errors. Encoded frames 001, 013, 015,
022, 024, 032 and 036 were visually inspected; narrated subjects and controls
remain readable. A sampled 005→006 boundary verified the fade through black.
No `.render-*` intermediates remained.

Run the focused suite with:

```sh
.venv/bin/python -m pytest -q tests/test_demo_video_build.py tests/test_demo_video_capture.py tests/test_manual_screenshot_capture.py
```

Tests cover both cuts, source drift/hashes, exact deterministic text exports,
prerequisite detection, audio names/missing files/invalid duration, frame-rounded
timing and tails, actual-audio SRT boundaries, motion filters, paths with spaces,
output protection, and failure cleanup. A small real-media smoke test runs when
FFmpeg is installed, using disposable **test tones, not narration**, to exercise
PCM decoding, differently leveled takes, normalization, AAC, selectable subtitles,
and encoded timing. It skips explicitly when the media tools are absent.

No voice provider was chosen and no narration audio, final narrated demo, or
production SRT was generated during this phase. Production application behavior,
APP_VERSION, release metadata, canonical screenshots and narration are unchanged.

### Voice audition

The fixed audition samples **001 → 013 → 014**, preserving main-cut order:

| Scene | Purpose | Words | Editorial target |
| --- | --- | ---: | ---: |
| 001 — Dashboard | Opening, product positioning, DLMS pronunciation | 25 | 11 sec |
| 013 — Question Tools | Conversational Study workflow, Anki and AI pronunciation | 28 | 14 sec |
| 014 — Learning Intelligence | Technical explanation connecting Study and Exam evidence | 18 | 10 sec |

These screenshots have been inspected against their narration. The selection
includes short and longer sentences, an opening acronym, and a transition from
Study answers to learning evidence. V2 total: **71 words, 35 seconds of editorial
target time**. Actual WAV lengths may extend the audition; pacing is not forced.

From the repository root:

```sh
python tools/build_demo_video.py export --audition
python tools/build_demo_video.py validate --audition
# After supplying all three real narration WAVs:
python tools/build_demo_video.py validate --audition --require-audio
python tools/build_demo_video.py build --audition
```

Export writes `build/demo-video/voice-audition/001.txt`, `013.txt`, and `014.txt`
containing only exact spoken text from `NARRATION.md`. The derived `manifest.json`
records scene order, screenshots, text, word counts, targets, future audio names,
and the usual production motion/transition metadata. `README.txt` provides
provider-neutral recording instructions; `PRONUNCIATION_NOTES.md` documents
letter-by-letter DLMS and AI, Anki, and technical phrasing. Neither file is
spoken narration. Re-export is deterministic and does not overwrite audio.

Supply **lossless mono/stereo PCM WAV** files with these exact paths:

```text
build/demo-video/voice-audition/audio/001.wav
build/demo-video/voice-audition/audio/013.wav
build/demo-video/voice-audition/audio/014.wav
```

Use the same voice/settings for all three, natural US English, normal pauses,
and no music or effects. Keep each candidate's originals in a separate directory;
`--audio-dir "path with spaces/candidate/audio"` selects it. To preserve separate
outputs, add `--work-dir build/demo-video-candidate-a` (export there first if
using its default audio location). Production audio remains
`build/demo-video/audio/NNN.wav`; audition clips are not promoted automatically.

The build writes `build/demo-video/DLMS-3.2-voice-audition.mp4`, its timeline JSON,
and scene-level SRT through the **same production renderer**: actual audio timing,
visual tails, static screenshots by default, clean cut to
013, short fade through black into 014, and default two-pass normalization.
`--mux-subtitles` and `subtitles --audition` also work. Missing WAVs fail with their
exact names; no placeholder speech or silent audition is substituted. Audition
cannot be combined with `preview` or `--cut long`. Main/long cuts contain 37/38
scenes, with their existing exclusions unchanged.

No audio or audition MP4 is created by export/validation. To run deterministic
regressions without the existing media smoke test that generates test tones:

```sh
.venv/bin/python -m pytest -q tests/test_demo_video_build.py tests/test_demo_video_capture.py tests/test_manual_screenshot_capture.py -k 'not real_media_smoke'
```

### Local narration with Kokoro TTS

This is an **optional demo-video tool**, isolated from DLMS runtime. It uses
Python's standard library to call a separately running local Kokoro HTTP server;
no SDK, model, API key, subscription, or application dependency is added. The
video builder remains voice-provider-neutral and accepts the same PCM WAVs from
human recording or other generators.

The [upstream quick start](https://github.com/hangry-labs/kokoroTTS#quick-start)
currently documents `hangrylabs/kokorotts:v0.2`. Start its full image on CPU,
binding only to this computer (Docker/image download is a separate prerequisite):

```sh
docker run --rm -p 127.0.0.1:7860:7860 hangrylabs/kokorotts:v0.2
```

Wait for startup, open `http://127.0.0.1:7860` for the browser UI, or check:

```sh
curl --fail http://127.0.0.1:7860/tts/status
python tools/generate_demo_narration.py --list-voices
```

The generator queries the documented `GET /tts/speakers?language=a` endpoint
before synthesis, both to check connectivity and to validate the selected voice.
Discovery lists the running server's American English voices; no fallback IDs
are silently assumed. Initial candidates are `af_heart`, `af_nicole`, `af_sarah`,
`af_bella`, and `af_sky`, if advertised. Upstream also lists `af_aoede`, `af_kore`,
`af_nova`, `af_alloy`, `af_jessica`, and `af_river`; use discovery to establish
availability in your image. See [upstream voice examples](https://github.com/hangry-labs/kokoroTTS#voice-examples).

**Default: `af_sarah`, speed 1.0**, as an audition convenience, not an approved
voice or a claim of matching Ainsley. Listen for calm, polished, clear,
professional delivery without advertising emphasis. Test one three-scene set:

```sh
python tools/generate_demo_narration.py --audition --voice af_sarah
python tools/build_demo_video.py validate --audition --require-audio
python tools/build_demo_video.py build --audition
```

This re-exports the authoritative audition text and generates only **001, 013,
014**, into `build/demo-video/voice-audition/audio/NNN.wav`. Existing WAVs cause
an error before synthesis; replacing them requires explicit `--force`. Failed
responses are validated in disposable temporary files before publication, so
an invalid response cannot replace an existing good take. A failed batch retains
completed clips; retry into a new candidate set or explicitly regenerate with
`--force`. Each WAV has a `.generation.json` sidecar recording source and synthesis
text, voice, speed, duration, endpoint, and audio hash.

Compare candidates without overwriting one another:

```sh
python tools/generate_demo_narration.py --audition --voice af_sarah --output-set sarah
python tools/generate_demo_narration.py --audition --voice af_nicole --output-set nicole
python tools/build_demo_video.py build --audition --audio-set sarah
python tools/build_demo_video.py build --audition --audio-set nicole
```

Candidate WAVs live directly in `voice-audition/candidates/SET/`. To promote a
chosen set, copy its `001.wav`, `013.wav`, and `014.wav` into
`voice-audition/audio/` using your file manager, confirming any replacements.
Alternatively, keep using `--audio-dir`; no promotion is required to render.
Only requested voices are generated. No multi-voice batch runs automatically.
`--audio-set NAME` is shorthand for the matching candidate directory and writes
`DLMS-3.2-voice-audition-NAME.mp4` in the normal demo-video build directory.
For Kokoro-style names, the `af_` or `am_` prefix is omitted from the MP4 name.

The configurable base URL defaults to `http://127.0.0.1:7860`; append
`--base-url http://127.0.0.1:OTHER_PORT` as needed. Localhost, loopback, and private
IP addresses are accepted; public service URLs, proxies, and redirects are not
used. `--timeout 300` is the default synthesis timeout; increase it for slow CPU
runs. Ordinary failures have concise diagnostics; `--verbose` enables tracebacks.
The adapter uses `POST /tts/generate`, omitting `output_format` for WAV. Its
`--speed` range is conservatively limited to 0.8–1.2 and controls Kokoro synthesis
speed, not post-generation stretching. No pitch, music, effects, or normalization
is requested from Kokoro. Normalization remains the video builder's job.

Only synthesis input changes: standalone `DLMS`, `AI`, `OCR` and `API`, including
legacy space-separated forms, receive explicit Kokoro/Misaki letter-name
phonemes. `Anki` receives the phonemes for **AHN-kee**. Written narration,
scene-text exports and subtitles retain normal product spelling. The adapter
does not transform substrings inside unrelated words. See the [V2 pronunciation
table and upstream references](EDITORIAL_V2.md#pronunciation-correction).
These corrections follow the user's V1 listening feedback. The user listened to
and approved the isolated Heart pronunciation test before authorizing the full
V2 generation. The completed V2 recording still needs whole-video listening review.

Prepare a tiny test without contacting Kokoro, then run it later when available:

```sh
python tools/generate_demo_narration.py --pronunciation-test --voice af_heart --dry-run
python tools/generate_demo_narration.py --pronunciation-test --voice af_heart
```

The second command writes only `build/demo-video/pronunciation-test/pronunciation.wav`
and its metadata. Existing files require `--force`. It touches neither production
clips nor audition sets. The earlier editorial pass prepared the dry-run payload;
the user subsequently ran and approved the pronunciation test. Do not redesign
the approved transforms or regenerate clips solely on speculative pronunciation concerns.

WAVs are checked for nonempty, complete PCM data and mono/stereo channels.
When available, ffprobe additionally checks codec and duration. No invalid
HTML/JSON payload is accepted as WAV. Without ffprobe, the WAV parser still
validates data and records duration; final video assembly requires FFmpeg/ffprobe.

**Selected production voice: `af_heart`**, approved after the Sarah, Nicole and
Heart auditions. Use natural synthesis speed 1.0. The earlier `af_sarah` CLI
default remains an audition convenience; explicitly select Heart for production.
Generate main narration and assemble the first narrated review build with:

```sh
python tools/generate_demo_narration.py --cut main --voice af_heart
python tools/build_demo_video.py validate --cut main --require-audio
python tools/build_demo_video.py build --cut main --mux-subtitles
# Optional long version, using the same production audio directory:
python tools/generate_demo_narration.py --cut long --voice af_heart
python tools/build_demo_video.py build --cut long
```

Main/long select 37/38 scenes using the existing authoritative manifest parser.
WAVs go to `build/demo-video/audio/SCENE_ID.wav`, including the additive
`013A.wav`, `013B.wav`, `028A.wav`, and `028B.wav`; excluded scenes are not requested.
Main and long share filenames, so a subsequent full long generation requires
`--force` if main WAVs already exist. That regenerates all included long clips;
it is not an incremental missing-only mode. Full production generation must be
explicitly invoked; the audition command never generates production audio.

Validation without a live service:

```sh
.venv/bin/python -m pytest -q tests/test_demo_narration.py tests/test_demo_video_build.py tests/test_demo_video_capture.py tests/test_manual_screenshot_capture.py -k 'not real_media_smoke'
```

HTTP is mocked. Tiny PCM test fixtures validate file handling; no model or real
speech is used. At implementation time, no server was listening on the default
local port, so no live narration was generated or auditioned. Docker was neither
installed nor started automatically.

### Complete V2 narrated review build

**Current presentation: static screenshots throughout.** Following the user's
shimmer report, the canonical MP4 was rebuilt with the existing V2 WAVs and
`--motion none`. Runtime remains **6:43.600**; all scene timings, the SRT and
even the encoded AAC stream are unchanged. The previous motion-enabled MP4,
SRT and timeline are preserved under `build/demo-video/archive-v2-motion/`.

```sh
python tools/build_demo_video.py build --cut main --motion none --mux-subtitles --overwrite
```

The changing 100–102% zoom and its 3840×2160 supersampling/zoompan path are now
bypassed. Native screenshots stay at 1920×1080; existing fades/cuts and encoding
quality settings remain. No Kokoro request or narration regeneration was made.
Static rebuild evidence is in `build/demo-video/static-review/REVIEW_BUILD.md`.
All 33 scene timings and protected asset hashes pass; full decoding and subtitle
roundtrip pass; **105 focused tests pass** (one separate render smoke test omitted
in favor of this complete render validation).

Opening, PDF/import, OCR, Study, Learning Intelligence, packs, printable cards
and closing frames remain sharp with fixed geometry in inspected samples.
Before encoding, repeated hold frames in those eight scenes are pixel-identical.
Decoded H.264 frames retain small compression differences, so the MP4 is not
claimed to be pixel-identical throughout each hold. There is no remaining
zoom/pan/resampling motion; no new encoding-quality adjustment was made.

The user approved the 790-word V2 script and the isolated Heart pronunciation
test. All **33 main-cut clips** were then regenerated locally with **`af_heart`,
speed 1.0**, from the current narration and approved synthesis-only transforms.
No V1 clips were reused. Generation completed with no failures or retries.

Commands used after archiving V1:

```sh
python tools/generate_demo_narration.py --cut main --voice af_heart --speed 1.0 --force
python tools/build_demo_video.py build --cut main --mux-subtitles --overwrite
```

- Review MP4: `build/demo-video/DLMS-3.2-demo.mp4` — **6:43.600**, 12,108 frames;
  **6.400 seconds longer** than V1. 1920×1080, 30 fps, H.264/yuv420p,
  AAC 48 kHz mono. This is a review build, not a published release.
- Source WAVs: `build/demo-video/audio/NNN.wav` — exactly 33 mono 24 kHz signed
  16-bit PCM files. Total **5:59.250**; mean **10.886 sec**; shortest **024,
  5.275 sec**; longest **028, 19.075 sec**. Source WAV levels are untouched.
- SRT: `build/demo-video/DLMS-3.2-demo.srt` — 33 scene-level cues using actual
  audio timing; also muxed as selectable English subtitles, never burned in.
- Listening checklist: `build/demo-video/v2-review/LISTENING_REVIEW.md`.
  Prioritize imports at **0:56–2:10**, Anki/AI at **2:33**, packs at **4:49**,
  digital Anki at **5:32**, physical cards at **5:44**, and AI/API at **5:59**.
- Evidence: `build/demo-video/v2-review/REVIEW_BUILD.md`,
  `production-audio-summary.csv` / `.json`, `validation.json`, generation/build
  logs and representative encoded frames. The editorial audit's no-recording
  statements describe the earlier planning phase, not this completed build.

Validation checked every WAV with ffprobe and PCM data validation, exact V2
source/synthesis text and audio hashes, Heart/speed metadata and new generation
timestamps. All 33 encoded narration intervals contain non-silent audio and fit
their scene slots with the established tails. The video passed full decoding;
the extracted selectable subtitles exactly match the sidecar. All 36 screenshot
hashes and all audition assets remain unchanged; no temporary render directories
remain. **98 focused tests passed**, with the separate render smoke test omitted
because this complete production render was validated instead. `git diff --check`
passed. No long cut was generated.

Encoded frames inspected: 001, 003, 007–009, 011, 014, 028, 031–032 and 036,
plus the 005→006 chapter fade. Narrated subjects remain readable, with no new
focus cropping or visible transition artifacts in these samples. The approved
visual limits remain: 007 shows import setup rather than bank generation; 028
uses the pack callout/navigation rather than the catalog; 032 shows shared card
selection rather than the Avery print layout. These frames provide overview
context without pretending the unpictured steps happened. The approved spoken
script says “three-by-five index cards”; it does not read the Avery model number.
Complete human listening/viewing review is still required before publishing.

### First complete narrated review build

**Historical V1 result.** Before the authorized V2 regeneration, these files were
copied into `build/demo-video/archive-v1-before-v2/`, including audio/metadata,
MP4, SRT, timeline, narration export, production manifest and review reports.
Their narration and subtitles are not the revised V2 script. Do not assemble V2
with these archived WAVs: audio-format validation alone does not prove text or
pronunciation-version alignment.
The preserved Sarah/Nicole/Heart audition recordings likewise use V1 text;
future audition exports will reflect V2. Do not overwrite the reference sets.

The first main review build used local Kokoro voice **`af_heart`** at speed 1.0
for all **33 scenes**. It was reviewed by the user and led to the V2 revisions.
No long cut was generated.

- Archived review video: `build/demo-video/archive-v1-before-v2/DLMS-3.2-demo.mp4` — **6:37.200**, 1920×1080,
  30 fps, H.264/yuv420p, AAC 48 kHz mono.
- Archived subtitles: `build/demo-video/archive-v1-before-v2/DLMS-3.2-demo.srt` — 33 scene-level cues based on
  actual audio timing; also included as a selectable English track, not burned in.
- Archived source narration: `build/demo-video/archive-v1-before-v2/audio/NNN.wav` — 33 mono 24 kHz PCM WAVs,
  **5:58.575** total, mean **10.866 seconds**, with generation metadata for each.
- Archived audio summary: `build/demo-video/archive-v1-before-v2/main-review/production-audio-summary.csv`
  and `.json`; shortest 011 (8.225 sec), longest 034 (14.000 sec).
- Archived review evidence: `build/demo-video/archive-v1-before-v2/main-review/REVIEW_BUILD.md` and
  `build/demo-video/archive-v1-before-v2/main-review/LISTENING_REVIEW.md`, including pronunciation
  checkpoints with timestamps and representative encoded frames.

The runtime is 22.2 seconds above the original 6:15 target because actual delivery
and existing minimum viewing times are preserved. Generation completed without
failures/retries; no new pronunciation transforms were needed. Full decoding,
all audio/scene mappings, subtitle timing, screenshot hashes, representative visual
checks and audition preservation checks passed. The source WAVs retain their
original generated levels; the existing builder normalizes temporary copies.

Listen to the whole video before publishing, especially DLMS in 001, PDF in 007,
OCR in 008, Anki/AI in 013, and API in 033. Check natural cadence, scene joins,
and caption density as well. Successful encoding cannot confirm speech quality.
The archived V1 media, screenshots and all three audition sets remain intact.

### Future focused videos

Good follow-ups are importing PDFs/scans/images/CSV; OCR and Review & Repair;
Learning Intelligence; Generated Practice; Study Packs and Content Packs;
question types including Matching and Hotspot; Anki and printable physical flash
cards; building/importing quizzes; and Learning Scope. [The V2 audit](EDITORIAL_V2.md#future-focused-videos)
gives a short scope for the existing recommendations. This is planning only;
none of those videos is being created now.
