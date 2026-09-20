# DLMS-139 — Phase 2 instructional candidates

The six DLMS-138 delivery videos have been **approved by the repository owner**.
Their scripts, captures, audio and rendered outputs are protected. The seven
additions below are **candidates pending listening and editorial review**, not
approved or published. `index.json` defines playlist order; each `video.json`
remains the sole narration/storyboard/publishing definition.

## Required-topic assessment

| Requirement | Coverage | Reason for the grouping |
|---|---|---|
| 1. IT Study | `specialized-study`, scenes 1–3 | Installed IT-domain packs, terminology, diagrams and prepared questions; same underlying study engine |
| 2. Law Study | `law-case-review` | Separate raw imports and case records, saved IRAC/Socratic responses, notes and export justify a separate tutorial |
| 3. Medical Study | `specialized-study`, scenes 4–5 | Installed medical-domain terminology and available anatomy/image sources; no claim of a bundled curriculum |
| 4. Other Studies | `specialized-study`, scene 6 | Catalog filtering and ordinary imported quizzes, rather than another learning engine |
| 5. Reset & Maintenance | `reset-and-maintenance` | Independent persistence scopes require a dedicated explanation; see [reset audit](RESET_SCOPE.md) |
| 6. AI settings/external AI | `ai-settings-and-handoff` | Optional destination and prompt controls, explicit copying, structured response and Review & Repair |
| 7. AI plus packs | `ai-to-study-pack` | ZIP return, independent validation and explicit installation differ from the question-response path |
| 8. Anki/physical cards | `anki-and-physical-cards` | Actual APKG response and HTML front/back print layout now demonstrated |
| 9. Image/hotspot authoring | `image-and-hotspot-authoring` | Actual upload, geometry, save, study feedback and installed-source editor are sufficiently mature |

No required topic was deferred for lack of capture infrastructure. Separate IT,
Medical and Other videos would repeat catalog and generation controls. Law's
inactive Future Study Modes are not presented as working standalone features.
The medical fixture deliberately contains only original basic direction terms;
the narration explains that image practice requires an image dataset.

## Source audit and boundaries

Inspected manual chapters 7, 11–14, 16–17 and the feature/reference inventory;
subject, Law, External AI, Study/Content Pack, Anki, image-editor, maintenance and
history routes; content-pack mutation/validation, Law persistence, reset services;
their templates; quiz/recovery JavaScript and associated tests. Per-video
`implementation_refs` and `manual_refs` identify maintenance entry points.

AI fixtures are **author-written original responses**, never misrepresented as
output from a provider. Captures do not contact an external AI. Medical/legal
accuracy is not inferred from structural validation. The Law packet is fictional
and follows the actual recognized section headings. Case responses are saved
locally; this is not an automated legal grading demonstration.

The image builder creates a real installed pack and playable quiz. Image editor
frames show an existing installed dataset's test and unsaved overlay preview;
they do not pretend those previews have already been saved. Anki export is
exercised without a download dialog. Anki itself and physical printing remain
external steps, not simulated UI. Print-layout pages use their actual light
paper styling even when the application theme is Purple & Gold.

## Capture and build architecture

`tools/documentation_video_phase2.py` supplies recipes 201–238 to the existing
`capture_demo_video_screenshots.py`. It is not a second capture system. A marker
inside the capture-owned temporary directory opts into the extra fixtures.
Ordinary overview and phase-one capture runs retain their original fixture.
Original service artwork is reused; no commercial datasets or user data enter
the fixture. The original renderer, TTS, batch script and encoding logic are
unchanged, preserving existing build fingerprints.

```sh
.venv/bin/python tools/build_documentation_videos.py list
.venv/bin/python tools/build_documentation_videos.py validate --all
.venv/bin/python tools/build_documentation_videos.py narrate --videos law-case-review
.venv/bin/python tools/build_documentation_videos.py build --videos law-case-review
.venv/bin/python tools/build_documentation_videos.py verify --videos law-case-review
.venv/bin/python tools/build_documentation_videos.py delivery --videos law-case-review
```

Use comma-separated IDs for a subset, or `--all` for the complete playlist.
Narration reuses exact text/voice/hash matches; build caching protects approved
masters. Delivery has no skip cache: select only new videos when preserving
approved delivery files. Capture refreshes stage through the existing `capture`
command for review before replacing source images and recording new hashes.

The new-video subset is:

```text
specialized-study,law-case-review,reset-and-maintenance,ai-settings-and-handoff,ai-to-study-pack,anki-and-physical-cards,image-and-hotspot-authoring
```

Outputs stay in ignored `build/demo-video/series/<id>/`: `master.mp4`,
`delivery.mp4`, `master.srt`, `master.timeline.json`, audio provenance, chapters,
description, publishing metadata and timestamped listening checklist. Only the
new subset is narrated/rendered for this pass. Generated media is not source.

## Publishing and manual handoff

Playlist positions 7–13 follow the existing six. Each definition supplies a
restrained title, description, 3–5 actual-timeline chapters, subtitle path,
manual references and a thumbnail source/text specification. Reuse the series
thumbnail design in README: 16:9 Purple & Gold, one topic screenshot, a readable
short label, and a small consistent DLMS mark. No thumbnail bitmap is finalized
before editorial review. No external URLs are invented.

The canonical manual stays complete without videos. Its series link reaches
these definitions and their chapter mappings; the videos supplement it.
Before publication, listen end to end, check the pronunciation of IRAC as well
as the established DLMS/AI/API/Anki terms, inspect delivery text, finalize the
thumbnail, and replace publishing-relative manual links with public URLs.
No upload is part of this task. Future topics should follow actual user feedback,
not split these workflows into redundant feature tours.
