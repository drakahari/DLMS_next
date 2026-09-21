# DLMS focused documentation videos

DLMS-138 extends the existing overview workflow into an ordered instructional
series. **The six phase-one delivery videos are approved by the repository
owner.** DLMS-139 adds seven **candidates pending listening and editorial
review**, covering specialized studies, resets, external AI, pack creation,
card exports and image authoring. See [Phase 2](PHASE2.md) for the required-topic
assessment and [editorial status](editorial-status.json) for the approval boundary.
No tutorial is automatically published by this tooling.

The [published overview](https://www.youtube.com/watch?v=nrUz3umt8vk) remains the
short orientation. The [Markdown manual](../../user-manual/README.md) remains
the canonical written guide. These videos teach decisions and sequences, not
every field, file format or implementation detail.

## Playlist and manual companions

Each linked `video.json` is the authoritative script and storyboard. Narration
appears beside its scene, visual focus and capture reference, so editors cannot
accidentally update a separate transcript but leave subtitles behind.

| Stable tutorial number | Video definition | What the sequence adds | Written guide | Narrated duration |
|---|---|---|---|---|
| 1 | [Import and repair](imports-and-repair/video.json) | Source choice → uncertain answers → saved bank → practice generator | [Creating content](../../user-manual/04-creating-and-importing-content.md), [PDF/OCR](../../user-manual/10-pdf-smart-pdf-and-ocr.md) | 2:16.533 |
| 2 | [Study and Exam](study-and-exam/video.json) | Feedback versus assessment, timer, covered Pause, matching before/after, hotspot result | [Taking quizzes](../../user-manual/06-taking-quizzes.md), [Rich questions](../../user-manual/11-matching-terminology-and-image-based-content.md) | 2:26.233 |
| 3 | [Daily review](daily-review/video.json) | Scope → evidence → due batch → source provenance → explicit Finish Review → retained completion | [Study and review](../../user-manual/07-study-and-review.md), [Learning Intelligence](../../user-manual/08-learning-intelligence.md) | 2:54.933 |
| 4 | [Organize your library](organize-your-library/video.json) | Separate placement, visibility, filters and learning scope; compare duplicate records | [Library organization](../../user-manual/05-quiz-library-and-organization.md) | 2:13.900 |
| 5 | [Reusable Study Packs](reusable-study-packs/video.json) | Management versus learner catalog, matching options, generated activities and retained sources | [Packs](../../user-manual/13-study-packs-and-content-packs.md) | 2:10.967 |
| 6 | [Portability and backup](portability-and-backup/video.json) | Choose a transfer format, inspect a real title-collision preview, distinguish backups and study exports | [Portability](../../user-manual/15-import-export-and-portability.md), [Backup](../../user-manual/17-maintenance-backup-and-data-management.md) | 2:27.300 |
| 7 | [Specialized studies](specialized-study/video.json) | IT, Medical and Other catalogs; installed sources versus shared quiz behavior | [Packs](../../user-manual/13-study-packs-and-content-packs.md), [Rich questions](../../user-manual/11-matching-terminology-and-image-based-content.md) | 2:23.367 |
| 8 | [Law case review](law-case-review/video.json) | Prepared packet → saved case → IRAC and Socratic responses → notes | [External workflows](../../user-manual/12-external-ai-workflows.md), [Packs and Law](../../user-manual/13-study-packs-and-content-packs.md) | 2:14.733 |
| 9 | [Reset and maintenance](reset-and-maintenance/video.json) | Choose the correct scope; distinguish history, evidence, sources and browser checkpoints | [Maintenance](../../user-manual/17-maintenance-backup-and-data-management.md), [Reset audit](RESET_SCOPE.md) | 4:01.033 |
| 10 | [AI settings and handoff](ai-settings-and-handoff/video.json) | Optional settings → deliberate external handoff → local validation and repair | [External AI](../../user-manual/12-external-ai-workflows.md), [Settings](../../user-manual/16-settings-and-runtime.md) | 2:35.800 |
| 11 | [AI to Study Pack](ai-to-study-pack/video.json) | Request → returned ZIP → independent validation → install → dataset practice | [External AI](../../user-manual/12-external-ai-workflows.md), [Packs](../../user-manual/13-study-packs-and-content-packs.md) | 2:26.900 |
| 12 | [Anki and physical cards](anki-and-physical-cards/video.json) | Select and preview → APKG handoff → actual printable fronts and backs | [Anki and cards](../../user-manual/14-anki-decks-and-printable-cards.md) | 2:19.567 |
| 13 | [Image and hotspot authoring](image-and-hotspot-authoring/video.json) | Original upload → target geometry → saved playable quiz → installed-source editing | [Image content](../../user-manual/11-matching-terminology-and-image-based-content.md), [Packs](../../user-manual/13-study-packs-and-content-packs.md) | 2:16.000 |
| 14 | [Parsing pasted text](parsing-pasted-text/video.json) | Numbered source → cleanup → source preview → publication → answer verification | [Creating content](../../user-manual/04-creating-and-importing-content.md), [Parsing settings](../../user-manual/16-settings-and-runtime.md#configure-text-parsing-tools) | 3:29.067 (candidate) |

Tutorial 14 is a **candidate pending editorial review**. Its recommended viewing
position is immediately after Import and Repair, as recorded in `index.json`.
Existing tutorial numbers and source definitions remain unchanged. See its
[production notes and sample](parsing-pasted-text/README.md).

Silent previews use a declared **135 WPM estimate plus scene tails**, not synthesized
speech. The table above uses actual narration, which also determines SRT cues and chapter markers.
The target ranges are editorial guidance, not forced truncation or time stretching.

## Commands

Run from the repository root with the existing development environment. Core
definition validation/export uses Python's standard library and no network.
Rendering needs the same FFmpeg/ffprobe encoders and filters as the overview.
Capture uses the existing Firefox/Pillow infrastructure. Nothing installs packages,
downloads models or contacts an external provider automatically.

```sh
.venv/bin/python tools/build_documentation_videos.py list
.venv/bin/python tools/build_documentation_videos.py validate --all
.venv/bin/python tools/build_documentation_videos.py export --all

# Build one, a subset, or all: the same selector applies to every operation.
.venv/bin/python tools/build_documentation_videos.py preview --videos imports-and-repair
.venv/bin/python tools/build_documentation_videos.py preview --videos study-and-exam,daily-review
.venv/bin/python tools/build_documentation_videos.py preview --all
.venv/bin/python tools/build_documentation_videos.py verify --all --preview

# Start your existing local Kokoro service first; production voice is af_heart, 1.0.
.venv/bin/python tools/build_documentation_videos.py narrate --all
.venv/bin/python tools/build_documentation_videos.py validate --all --require-audio
.venv/bin/python tools/build_documentation_videos.py build --all
.venv/bin/python tools/build_documentation_videos.py verify --all

# After listening and visual review, create separate web upload artifacts.
.venv/bin/python tools/build_documentation_videos.py delivery --all
```

`--videos` accepts exact comma-separated identifiers. Unknown, repeated and empty
IDs fail; selection always follows playlist order. `--all` and `--videos` are
exclusive. A failed video does not prevent other selected videos being attempted;
the process exits nonzero and writes an action report identifying failures.
Invalid shared metadata fails before the batch begins.

`narrate` generates **only missing, corrupt or stale clips**. Reuse requires exact
written text, synthesis transforms, voice, speed, filename and WAV hash matches.
It uses the existing local-only Kokoro adapter and approved DLMS/AI/OCR/API/Anki
pronunciation handling. Build never starts TTS implicitly. There is no fallback
to a cloud provider or to misleading test-tone narration.

`build` reuses a current master only when its definition, screenshot hashes,
audio hashes and pipeline code fingerprint agree, and the MP4/SRT/timeline hashes
still match. `--force` rebuilds a master; it does not regenerate valid audio.
Do not run two writers against the same video output directory simultaneously.

## Output contract

All derived output is ignored under `build/demo-video/series/<video-id>/`:

```text
plan.json                     resolved scene/capture definitions
NARRATION.txt                 derived editor/listening transcript
audio/001.wav                 isolated per-video clip namespace
audio/001.generation.json     text/voice/synthesis/WAV provenance
silent-preview.mp4            silent editorial preview, never an upload artifact
silent-preview.timeline.json estimated timing, explicitly separate from master
master.mp4                    narrated static lossless review master
master.srt                    separate English captions from actual audio
master.timeline.json          actual scene timing and normalization evidence
build-record.json             cache fingerprint and output hashes
CHAPTERS.txt                  actual-time chapter groups, not one per scene
DESCRIPTION.txt               publishing draft and manual references
publishing.json               title, caption/thumbnail handoff and candidate status
LISTENING_REVIEW.md            actual timestamps, visual focus and listening gates
delivery.mp4                  optional separate H.264 High / AAC web encode
```

Every video owns its own numeric/alphanumeric audio labels. `001.wav` in one
video can never replace `001.wav` in another or the overview. IDs remain stable
when inserting a scene such as `001A`; scene array order is authoritative.

Masters reuse `build_demo_video.render`, its normalization, lossless yuv420p,
1920×1080/30 fps, static geometry, cuts, actual audio duration and 0.6-second tail.
Subtitles are selectable English plus a separate SRT, never burned in.
`verify` decodes the entire video and compares **every frame in every scene** to
the source PNG after the expected RGB-to-YUV conversion. It also checks current
audio provenance, timing and both caption representations on narrated masters.

Delivery reuses the overview's approved CRF 18 / slow / stillimage approach, with
one BT.601-to-BT.709 matrix conversion and correct SDR tags, no resizing, copied
AAC/subtitles and Fast Start. It preserves the master and performs a full decode.
Lossless equality is a master requirement, not a promise about lossy delivery.
Inspect small text and gradients before approving each delivery artifact.

## Capture ownership and refresh

Existing captures are referenced, not copied or renumbered. `overview:013A`, for
example, resolves against the frozen overview capture manifests. The series-only
registry [captures.json](captures.json) holds hashes for four phase-one captures
and 38 phase-two captures. The original recipes are:

| Recipe | Teaching state | Origin and limits |
|---|---|---|
| `series:101` | Saved Question Bank and practice generator | Repairs answer A in the original staged draft, then submits the real Save Reviewed Question Bank form; not an OCR accuracy demonstration |
| `series:102` | Bundle preview with RENAMED notice | Exports a synthetic quiz and stages it back through real validation; does not publish the import |
| `series:103` | Generated Practice Smart View | Actual filter retains folder grouping and active/completed sessions |
| `series:104` | Matching before placement | Original three-pair activity with empty targets and answer pool |

These recipes are opt-in `DOCUMENTATION_FRAMES` in the existing capture tool.
The overview's default `FRAMES`, numbering and `--list` output are unchanged.

```sh
.venv/bin/python tools/capture_demo_video_screenshots.py --documentation --list
# Stage refreshed captures for selected videos under ignored build/, including
# overview recipes replayed in their established story order.
.venv/bin/python tools/build_documentation_videos.py capture --videos study-and-exam
```

Capture creates a disposable data root, synthetic source material and a task-owned
Firefox process, all cleaned in `finally`. Refreshes land in
`build/demo-video/series/capture-review/{overview,series}/` with proposed hashes;
they **never overwrite the overview screenshots or accept new hashes automatically**.
Review framing, synthetic-only content, feedback state and text at full resolution
before promoting an asset and changing its recorded hash.

Fixture content and state recipes are deterministic, but the existing evidence
anchor follows the current UTC day and Firefox/font versions can affect pixels.
Recorded hashes pin accepted images; recapture is not advertised as byte-identical
across dates or machines. No native dialogs, personal profiles or live browser
recordings are needed. The series uses Purple & Gold at device scale 1.

When a changed UI needs a different instructional frame, add a series recipe and
asset rather than silently replacing a frozen overview capture. Update the affected
definitions to refer to that asset. This lets the historical overview stay intact.

## Editing and maintenance

1. Use `manual_refs` and `implementation_refs` to identify affected videos when a
   workflow changes. Shared capture references identify other affected scripts.
2. Verify the current application/manual before revising narration; do not infer
   supported behavior from the screenshot alone.
3. Keep each narration paragraph beside its visual focus. Add a stable scene ID,
   a capture reference, and a chapter label only when a new viewer topic begins.
4. Validate all definitions; review the derived transcript and silent preview.
5. Refresh only needed captures, inspect them and explicitly accept their hashes.
6. Run incremental narration, build, full verification and listening review.
7. Approve content before delivery encoding and publishing. Keep the manual usable
   without video; add a public companion link only after a real URL exists.

No chapter timestamps are guessed for publishing. The actual timeline rounds
chapter starts to the nearest second, requires a 00:00 start and at least three
chapters of at least ten seconds. Each scene produces one authoritative subtitle
cue through the shared renderer. Subtitles can be editorially split later only
with a deliberate shared-tool change; this pass preserves the established contract.

## Thumbnail and publishing template

Use a consistent **1280×720** canvas. Purple background `#211039`, gold accent
`#e6b923`, white topic text. Put a small **DLMS • FOCUSED WORKFLOWS** label at
top left; below it use the definition's `thumbnail_text` in two or three large
lines (at most six words). Put the selected actual `thumbnail_capture` on the
right in a simple gold-bordered panel. Crop to the relevant working area, not
the sidebar; never crop away a state that changes the meaning. Do not rely on
tiny UI text being readable at thumbnail size. Use the same font and spacing
for the whole series, with the playlist number in a small gold badge.

This is a specification; thumbnail images are finalized after editorial review.
Finalize crops after content review. Do not generate generic AI imagery or fake UI.
Export the finished thumbnail as an optimized PNG/JPEG outside build/ only when
it is approved for repository use.

Each definition supplies a restrained YouTube title, description and thumbnail
choice. Actual-time chapters and captions are exported beside the master. Set
the playlist order from [index.json](index.json), retain candidate/Unlisted review
status, and use the [existing publishing checklist](../YOUTUBE_PUBLISHING.md) as
the handoff. Recheck platform policy at upload time. Do not invent a video URL.
The generated description's repository-relative manual paths must be changed to
the intended public documentation URLs before upload.

YouTube hosts public videos. GitHub can link thumbnails to those real URLs;
MP4s, WAVs, TTS caches and generated publishing exports do not belong in normal
Git history. The archival master and web delivery file remain distinct.

## Deliberately omitted from this first series

This list records the original DLMS-138 scope. DLMS-139 now supplies the missing
AI, card-printing and image-authoring captures and tutorials; those deferrals
do not apply to the current phase-two lineup. See [PHASE2.md](PHASE2.md).

- **Another getting-started tour:** duplicates the published overview and setup
  chapters. Platform security prompts are better kept as current written guidance.
- **Separate Learning Intelligence, Scope, Due Questions and Generated Practice
  videos:** one end-to-end daily loop explains their relationship with less repetition.
- **Standalone Matching/Hotspot taking tutorial:** included in Study/Exam and Pack
  practice. A later authoring tutorial is justified only with new editor-state captures.
- **A separate duplicate detector tour:** comparison is the final part of Library
  organization; it does not need its own short feature advertisement.
- **External AI prompt/paste workflow:** useful future candidate, but deserves a
  real prompt → local validation → repair sequence. No external provider UI or
  fabricated model output has been introduced to fill that gap.
- **Anki and physical printing tutorial:** the current selection screen does not
  demonstrate importing an `.apkg` in Anki or aligning front/back paper. A focused
  follow-up should first add the deterministic HTML print layout and an honest
  external-application handoff. The current scripts mention the boundary only.
- **Settings, themes, History dashboards and format reference tours:** written
  reference plus the overview is sufficient; no separate video merely to cover a menu.

See [AUDIT.md](AUDIT.md) for source boundaries and [VALIDATION.md](VALIDATION.md)
for this implementation's evidence and remaining production work.

See [Phase 2 validation](PHASE2_VALIDATION.md) for the seven new candidate builds.
