# DLMS 3.2 YouTube publishing package

Status: **CONTENT COMPLETE / FINAL CANDIDATE**. Publishing preparation only;
no upload or public release has occurred. Prepared against `develop/3.2.0` and
current YouTube Help guidance checked on 2026-09-19.

## Artifact handoff

- Upload: `build/demo-video/DLMS-3.2-demo-delivery.mp4`.
- Keep archival master unchanged: `build/demo-video/DLMS-3.2-demo.mp4`.
- Upload English captions separately: `build/demo-video/DLMS-3.2-demo.srt`.
- Actual timeline: `build/demo-video/DLMS-3.2-demo.timeline.json`.
- Final cut: 40 scenes, 7:45.700, 1920×1080, 30 fps, static Purple & Gold UI,
  af_heart narration, 40 selectable English subtitle cues.

## Title

1. **DLMS 3.2 Overview — Local-First Study, Quizzes & Learning Intelligence** — 70 characters (**recommended**).
2. **DLMS 3.2 Demo — A Local-First Study and Quiz Workspace** — 54 characters.
3. **DLMS 3.2 Overview — Import, Study, Test and Review Locally** — 58 characters.
4. **DLMS 3.2 — Local-First Learning Platform: A Practical Overview** — 62 characters.

The recommended title leads with the product/version, says this is an overview,
and names both the familiar study workflow and Learning Intelligence. All titles
are below the [100-character limit](https://support.google.com/youtube/answer/57407?hl=en).

## Description

Paste [YOUTUBE_DESCRIPTION.txt](YOUTUBE_DESCRIPTION.txt), reproduced below.
Replace the clearly marked repository placeholder before publishing. The current
root README uses relative release links and does not establish a public repository
URL appropriate for this handoff; no remote URL or publication status is inferred.

```text
DLMS is a local-first study and quiz workspace that connects your learning material with practical review and Learning Intelligence.
This DLMS 3.2 overview follows the workflow from importing content to studying, taking timed assessments, and deciding what to revisit.

DLMS is privacy-oriented, single-user native desktop software: its packages run the application locally and open its interface in your browser. No cloud account or direct AI-provider API is required. Optional external AI uses a manual prompt-and-paste workflow; what you share with a provider stays your choice.

Organize quizzes into folders and choose your Learning Scope. Bring in text, CSV terminology lists, PDFs, and supported scanned documents through local OCR, then check uncertain material in Review & Repair before saving it.

Practice with Study Mode feedback, Matching pairs, and image-based Hotspot questions, or set an Exam Mode time limit for assessment. Pause freezes the countdown and obscures the exam. Learning Intelligence and due-question review scheduling help identify what needs attention; Generated Practice assembles focused sessions from existing questions.

Content Packs handles package validation and management; Study Packs lets you create quizzes from installed reusable datasets. Portable quiz bundles move source content without learning history. Anki export and printable three-by-five physical flash cards offer ways to study away from DLMS, while backups preserve your workspace and learning history.

GitHub repository: [GITHUB_REPOSITORY_URL — replace with the approved public URL before publishing]

Chapters
00:00 Introduction & Dashboard
00:23 Quiz Library & Learning Scope
00:56 Importing text, CSV & PDFs
01:27 Local OCR & Review and Repair
02:10 Study vs. Exam: timing & Pause
02:47 Study feedback, Matching & Hotspot
03:36 Learning Intelligence & spaced review
04:25 Generated Practice, History & Analytics
05:37 Portable bundles, Content Packs & Study Packs
06:12 Finding duplicate questions
06:34 Anki, physical flash cards & optional AI
07:16 Backups, local ownership & closing

Shown with original synthetic demo content in the Purple & Gold theme. Narration is AI-generated using local Kokoro text-to-speech (af_heart). English captions are available.
```

## Chapter provenance

[YOUTUBE_CHAPTERS.txt](YOUTUBE_CHAPTERS.txt) contains the same copy-ready chapter
block used in the description. Starts come from each selected scene's
`start_frame / fps` in the actual final timeline, rounded to the nearest whole
second (half seconds round up). These are not estimates from narration or target
scene lengths. Rounding can place a seek up to half a second either side of a cut.

| Chapter start | Source scene | Start frame | Exact seconds | Viewer-facing name |
|---|---|---:|---:|---|
| 00:00 | 001 | 0 | 0.000 | Introduction & Dashboard |
| 00:23 | 003 | 704 | 23.467 | Quiz Library & Learning Scope |
| 00:56 | 006 | 1679 | 55.967 | Importing text, CSV & PDFs |
| 01:27 | 008 | 2607 | 86.900 | Local OCR & Review and Repair |
| 02:10 | 011 | 3905 | 130.167 | Study vs. Exam: timing & Pause |
| 02:47 | 012 | 5016 | 167.200 | Study feedback, Matching & Hotspot |
| 03:36 | 014 | 6465 | 215.500 | Learning Intelligence & spaced review |
| 04:25 | 021 | 7935 | 264.500 | Generated Practice, History & Analytics |
| 05:37 | 028 | 10107 | 336.900 | Portable bundles, Content Packs & Study Packs |
| 06:12 | 029 | 11150 | 371.667 | Finding duplicate questions |
| 06:34 | 031 | 11814 | 393.800 | Anki, physical flash cards & optional AI |
| 07:16 | 034 | 13078 | 435.933 | Backups, local ownership & closing |

All 12 chapters are ascending, begin at 00:00, and exceed 10 seconds, including
the final chapter to 7:45.700. Scene 011 briefly establishes untimed Study before
011A–011C demonstrate assessment. Scene 012 explicitly returns to Study feedback.
History/Analytics remain with Generated Practice; duplicate review has its own
short chapter; optional AI follows the Anki/cards section. Backup and the closing
Dashboard share the final chapter. This follows the actual sequence without
moving any content. YouTube requires at least three ascending timestamps,
00:00 first, and chapters at least 10 seconds; manual chapters override automatic
ones. Chapter access can depend on advanced-feature eligibility.
[YouTube chapter guidance](https://support.google.com/youtube/answer/9884579?hl=en).

## Thumbnail brief — do not generate yet

Use one real screenshot with a simple title panel, not a collage of feature
screens. Basis: [001-dashboard.png](captures/001-dashboard.png). It shows the
actual Today’s Review workflow and recognisable Purple & Gold cards. The closing
[036-closing-dashboard.png](captures/036-closing-dashboard.png) is an alternative,
but use one, not both; avoid dense Learning Intelligence tables at thumbnail size.

- Canvas: 16:9, proposed 1920×1080 design canvas.
- Left 40%: solid deep purple sampled from the screenshot, large white **DLMS 3.2**,
  with gold **LOCAL-FIRST STUDY** below on two lines if needed. This is the entire
  added text; no feature checklist, claim badge, or decorative AI graphic.
- Right 60%: crop 001 around Today’s Review and the first row of Quiz Library /
  Build Quiz / Study Packs cards, approximately source bounds
  `(445, 304)` to `(1787, 823)`. Fit proportionally in the panel with purple padding;
  do not stretch or tilt. Preserve the actual UI wording. The screenshot is visual
  context; viewers should not have to read its helper text.
- Thin gold divider; generous text margins. Keep the lower-right corner free of
  essential text for the duration badge. The large DLMS title provides branding;
  an extra logo is unnecessary.
- Check a 320×180 preview when the thumbnail is eventually made. If the UI becomes
  too dense, tighten to the Today’s Review card rather than shrinking the title.

Exact thumbnail text: **DLMS 3.2 / LOCAL-FIRST STUDY**.
No thumbnail file is created by this task.

## Recommended upload settings

These are recommendations for the later manual upload, not settings applied here.

| Setting | Recommendation |
|---|---|
| Initial visibility | **Unlisted** for review; publish only after approval of the hosted result. |
| Audience | **Not made for kids**: this is a general-audience software walkthrough for self-directed learners, not content directed at children. |
| Category | **Science & Technology**, since the primary subject is software and its workflow. |
| Video/title/description language | **English**. |
| Captions | English → Upload file → **With timing** → authoritative SRT; verify all 40 cues after upload. Do not depend on MP4 subtitle-track import or replace the SRT with auto-sync. |
| Comments | Enable, with **Basic** moderation/hold potentially inappropriate comments for review. Invite specific, constructive feedback. |
| Chapters | Paste the supplied manual block in the description. |
| Automatic chapters | Disable “Allow automatic chapters” for this upload to retain editorial control. Manual chapters already override automatic ones; disabling is a preference, not a requirement. |
| AI / altered-content disclosure | **Yes**, as a conservative disclosure of realistic synthetic narration; see rationale below. |

The audience recommendation applies to the actual general-audience intent, not
merely to its educational subject. [Audience guidance](https://support.google.com/youtube/answer/9528076?hl=en).
Caption upload steps follow [YouTube's caption instructions](https://support.google.com/youtube/answer/2734796?hl=en).
Comments can remain available during unlisted review; see
[comment settings](https://support.google.com/youtube/answer/9482556?hl=en).
The Basic moderation option is described in
[YouTube's moderation guidance](https://support.google.com/youtube/answer/9483359?hl=en).

### Synthetic narration disclosure

The visuals are actual DLMS captures with synthetic demonstration data; the
voiceover is generated locally with Kokoro af_heart. It is not presented as the
repository owner's recorded voice. Recommend **Yes** in the AI-use/altered-content
field, plus the factual description note above. Current guidance requires
disclosure for realistic, meaningfully AI-generated or altered content and
exempts some production assistance and own-voice cloning. It does not expressly
settle every generic stock-TTS software narration case. “Yes” here is a conservative
editorial choice, not a claim that every TTS narration necessarily requires it.
The current Help page calls the setting “AI use”; Studio wording may vary.
[Current YouTube disclosure guidance](https://support.google.com/youtube/answer/14328491?hl=en).

After the future upload, wait for 1080p processing and review small text, static
holds, audio, manual chapter seeks, and captions on the hosted result before
switching visibility. This package does not claim to validate YouTube's transcode.

## Tags

```text
DLMS, DLMS 3.2, local first, study software, quiz software, learning intelligence, OCR study tools, spaced review, flashcards, Anki, local software, exam mode
```

Use these in the tags field, not as a keyword block in the public description.
Prefer “local software” over “self-hosted” here: the desktop/browser experience is
the focus, and the repository's advanced LAN/server mode is not a multi-user hosted
service. Titles, thumbnails, and descriptions matter more than tags; tags have a
limited discovery role. [YouTube tag guidance](https://support.google.com/youtube/answer/146402?hl=en).

## Optional pinned comment

```text
Project details and documentation: [GITHUB_REPOSITORY_URL]
If you try DLMS, feedback on the workflow is welcome. A timestamp or a concrete example helps make suggestions easier to act on.
```

Replace the placeholder before posting; do not post a fabricated repository link.

## Future GitHub README handoff

Draft only; the root README has not been edited. Replace both placeholder tokens
with the published YouTube URL and the eventual repository-relative thumbnail
path. The thumbnail is not yet generated. The same YouTube URL is used for both
links; no guessed video ID is supplied.

```markdown
## Watch DLMS in Action

See how DLMS 3.2 brings local-first importing, quiz practice, timed assessments, and learning-guided review into one desktop workspace.

[![Watch the DLMS 3.2 overview](THUMBNAIL_PATH)](YOUTUBE_VIDEO_URL)

[Watch the 7:45 overview on YouTube](YOUTUBE_VIDEO_URL).
```

Keep MP4s out of Git history; link to the hosted video. A downloadable release
asset can be considered separately and is not created by this task.

## Scope and checks

Product wording was checked against the current root README (local browser UI,
native packages, single-user model, imports, packs, external AI, and backups),
the final timeline's spoken text, and `FINAL_CANDIDATE.md`. The description does
not promise flawless OCR, cloud/mobile collaboration, AI-generated practice
questions, or a direct AI-provider integration. Generated Practice selects
existing questions; pack management and learner-facing datasets remain distinct.

Validation: title lengths below 100, description below 5,000 characters, chapter
rounding/order/minimum spans and description/chapter-file agreement, unchanged
media hashes, and `git diff --check`. No application tests or video rebuild are
needed for these documentation-only additions. No video/audio/captions, screenshots,
production code, APP_VERSION, release metadata, or root README changed.
