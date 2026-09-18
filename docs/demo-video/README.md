# DLMS demo-video screenshot project

Screenshot capture is complete on **develop/3.2.0** after visual stabilization.
The canonical set contains **36 final screenshots** in [captures/](captures/).
No narration, audio, or final video has been produced. This is not a release announcement.

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

Next phase: choose optional cuts and write narration against the canonical
manifest, then create audio and assemble the video. None of those tasks ran here.
