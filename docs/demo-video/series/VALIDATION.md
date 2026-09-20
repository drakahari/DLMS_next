# DLMS-138 validation and production handoff

Implementation status: **COMPLETE — six rendered instructional candidates**.
Publication status: **not published; owner listening/editorial approval pending**.
This distinction is deliberate: successful automation does not approve narration
delivery, thumbnail design, or instructional pacing on the owner's behalf.

## Narrated candidate set

All paths below are relative to ignored `build/demo-video/series/`. Each directory
contains `master.mp4`, `master.srt`, `master.timeline.json`, `delivery.mp4`, actual
`CHAPTERS.txt`, `DESCRIPTION.txt`, `publishing.json` and `LISTENING_REVIEW.md`.

| Directory | Scenes / subtitle cues | Words | Spoken seconds | Master seconds | Master bytes |
|---|---:|---:|---:|---:|---:|
| `imports-and-repair` | 6 | 316 | 132.850 | 136.533 | 15,530,220 |
| `study-and-exam` | 7 | 355 | 141.975 | 146.233 | 11,007,616 |
| `daily-review` | 8 | 424 | 170.025 | 174.933 | 17,926,546 |
| `organize-your-library` | 6 | 332 | 130.300 | 133.900 | 14,443,111 |
| `reusable-study-packs` | 6 | 326 | 127.300 | 130.967 | 13,485,615 |
| `portability-and-backup` | 6 | 328 | 143.600 | 147.300 | 17,189,475 |

Total: **39 scenes, 2,081 words, 846.050 seconds of source narration,
869.867 seconds of master video**. All candidates fall within their declared
editorial ranges. Six silent previews are also retained as explicitly labeled
editorial artifacts, using estimates rather than actual audio timing.

## Audio and service isolation

- Generated 39 new clips with **af_heart, speed 1.0**, using the existing local
  Kokoro adapter and pronunciation transforms. No overview clip was regenerated.
- The initially unavailable service was supplied by the already-cached
  `docker.io/hangrylabs/kokorotts:v0.2` Podman image, started with `--pull=never`,
  `--rm`, task-owned name `dlms138-kokoro`, and port binding
  `127.0.0.1:7860:7860`. The container was stopped after generation.
- A second `narrate --all` run with the service stopped reused **all 39 clips**,
  generating none. Exact text, synthesis payload, voice, speed and WAV hashes
  are checked; stale text or altered payload is rejected by regression tests.
- Every PCM WAV passed structural and ffprobe validation; builds also performed
  decode checks. Normalization produced finite loudness measurements, rejecting
  entirely silent inputs. Full narration duration fits inside each scene with
  a post-audio tail; no source clip is shortened to hit an editorial estimate.
- These technical checks do not replace listening to sentence endings,
  pronunciation and natural pauses. Use each candidate's timestamped checklist.

## Render and caption checks

`verify --all --preview` passed for all silent previews. `verify --all` passed
for all narrated masters:

- 1920×1080, 30 fps, static lossless H.264/yuv420p; AAC narration at 48 kHz;
- **26,096 narrated frames** fully decoded and compared with source PNG pixels
  after the expected RGB-to-YUV conversion;
- every hold matches its source exactly, including scene boundaries: no blank
  replacement, fade, geometric motion or repeated rescaling;
- 39 separate SRT cues across the series, in authoritative scene order;
- selectable English `mov_text` captions agree with the separate SRT and actual
  audio timeline;
- three actual-time chapter groups per candidate, starting at 00:00, all at
  least ten seconds;
- temporary `.render-*` intermediates removed after completion.

The new full-resolution screenshots were visually inspected. The saved-bank
frame shows real publication acknowledgement and the practice generator; the
bundle frame shows a real proposed rename and unconfirmed publication; the
Smart View preserves folder grouping; the matching frame shows empty targets
and the answer pool. The viewport intentionally shows a working area rather
than every part of each long page. No personal data or commercial study content
appears in these fixtures.

## Delivery candidates

All six separate delivery files completed full decode and stream/timing checks.
They use H.264 High, CRF 18, slow/stillimage, yuv420p, native 1080p/30 fps,
BT.709 SDR, copied AAC and selectable English captions. MP4 atom inspection
confirmed Fast Start for each file. Extracted captions match each separate SRT;
AAC payload hashes match the corresponding master, and master hashes remain intact.

| Candidate | Delivery bytes | Overall bit/s | Full-video SSIM against matrix-converted master |
|---|---:|---:|---:|
| Import and repair | 14,555,889 | 852,886 | 0.999422 |
| Study and Exam | 9,344,555 | 511,214 | 0.999630 |
| Daily review | 17,680,195 | 808,547 | 0.999436 |
| Organize your library | 13,333,394 | 796,618 | 0.999444 |
| Reusable Study Packs | 11,769,993 | 718,964 | 0.999520 |
| Portability and backup | 14,187,723 | 770,548 | 0.999488 |

Decoded delivery frames were visually inspected for all six topics, plus the
frosted Exam pause and hotspot diagram. Text, borders and Purple & Gold surfaces
remain readable and close to the source. Full-frame master equality proves
static geometry; delivery is lossy and is not claimed to be pixel-identical.
Normal-playback listening and final editorial approval remain with the owner.
Local comparison evidence is in `build/demo-video/series/delivery-quality.json`
and per-video `delivery-review.png` files.

A second `build --all` reused all six verified masters without rerendering,
demonstrating the output-hash/fingerprint cache with real artifacts. Temporary
delivery and synthesis directories were cleaned as well as render intermediates.

## Automated and browser validation

Commands run:

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider \
  tests/test_documentation_videos.py tests/test_demo_video_build.py \
  tests/test_demo_narration.py tests/test_demo_video_capture.py

PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider -m 'not browser'

.venv/bin/python tools/build_documentation_videos.py validate --all --require-audio
.venv/bin/python tools/build_demo_video.py validate --require-audio --verify-production-audio
git diff --check
```

- Focused tooling suites: **140 passed**.
- Full non-browser suite: **1,589 passed, 87 deselected, 2,425 subtests passed**.
- Tests cover invalid definitions, duplicate IDs, missing resources/manual
  anchors, capture hash drift, safe output paths, all/single/subset selection,
  alphanumeric scene IDs, subtitles/chapters, incremental audio, altered cache
  artifacts, batch failure continuation and real FFmpeg source-pixel comparison.
- Four new recipes were exercised through real isolated Firefox sessions in
  **Light, Dark, Purple & Gold, and Maroon & Gold**. They also completed at
  **960×720** in Purple & Gold without changing accepted 1080p assets. These
  narrower/theme checks establish functional recipe completion, not a new full
  accessibility or visual audit of every application screen.
- The selected-video `capture --videos study-and-exam` command completed end to
  end, replaying existing story prerequisites and staging seven refreshed images
  under ignored build/ only. Accepted screenshots were not replaced.
- The full 87-test browser suite was not rerun: no production browser behavior
  changed. The new capture actions received direct browser validation instead.
- Browser/server lifecycle cleanup remains in the shared harness's nested
  `finally` blocks; completed capture sessions left no task-owned service running.
- All **104 relative documentation links** checked across the new series docs and
  the two updated entry points resolve. Manifest validation separately checks
  every manual and implementation reference. `git diff --check` passes.

## Protected overview

The original overview remains **40 main scenes / 41 long-plan scenes**, 911 words,
**465.700 seconds**, with the existing audition selection. All 43 accepted
overview screenshots still match their manifests. Existing main audio passes
the original production provenance validation.

Unchanged SHA-256 values:

| Artifact | SHA-256 |
|---|---|
| `build/demo-video/DLMS-3.2-demo.mp4` | `7a247ac5fc64adf216bcd9fcf3c3d4434aa63694972473191b58826255283209` |
| `build/demo-video/DLMS-3.2-demo-delivery.mp4` | `1b6f823f329b08ee5d6fe3c3a6aad7c8ebb83c83b2b0fffb3952f65b38a5406b` |
| `build/demo-video/DLMS-3.2-demo.srt` | `c57fe92c816951d9adeb8e13b248c02339ef54ff53e62d6cba8a892d96b1db9d` |

No application code, application assets, APP_VERSION or release metadata changed.
No MP4, WAV, local container artifact or generated publishing output is added to
normal Git tracking. Nothing was committed, pushed, merged, tagged or published.

## Remaining human handoff

1. Listen to each complete narrated candidate and inspect delivery playback at
   normal size; check the generated listening checklist rather than assuming
   technical validation approves the voice performance.
2. Approve the scripts and pacing. Revise only affected scene paragraphs and
   use incremental narration/build if changes are needed.
3. Produce the final related thumbnails from the provided actual-screenshot
   specifications; no unnecessary thumbnail binaries were generated in advance.
4. Replace repository-relative paths in publishing descriptions with the intended
   public manual URLs, then use the existing publishing checklist. No fake video
   URL or automatic upload was introduced.
5. If demand justifies more material, prioritize a real External AI
   prompt/validation/repair walkthrough, then Anki/physical-card handoff and
   image/hotspot authoring. Do not extend this series just to match every menu.
