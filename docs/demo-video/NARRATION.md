# DLMS demo video — V3 narration and editorial plan

Authoritative narration and editorial timing for `develop/3.2.0`, reviewed against the current repository, all 36 V2 captures, and the four approved V3 additions on 2026-09-19. This is a product overview for independent and certification learners, technical users, privacy-oriented users, and prospective GitHub users. All examples use the prepared synthetic learner data.

## Recording cut and timing

- **37 narrated scenes:** 36 essential frames plus optional frame **033 kept**.
- **859 narration words**, excluding separators, production notes, and alternate lines for omitted frames. V3 redistributes the existing Study and Packs explanation across four new visual scenes.
- **Estimated speech: 6:02**, using scene-specific reference rates of 138–148 words per minute. At 135–150 WPM, the written-word envelope is **5:44–6:22**. The completed V3 Heart clips contain **6:30.300 of spoken audio**; natural pauses and acronym letter names explain the difference from the written estimate.
- **Editorial scene targets total 7:05 (425 seconds)**. The completed static V3 review build uses actual narration durations and runs **7:19.667**. Its 37-cue subtitle timestamps come from that actual timeline.
- **Long version: 38 scenes, 888 words**, adding only frame 020 and its 13-second target; not being produced in this pass.
- **CUT:** 017 and 035. **KEEP FOR LONG VERSION:** 020. **KEEP:** 033. No assets deleted, renamed, reordered, altered, or recaptured.

The scene numbers below retain the capture IDs, including additive alphanumeric IDs that avoid renumbering V2. Gaps in the recording cut are intentional. [NARRATION_PLAIN.txt](NARRATION_PLAIN.txt) contains only the 37 main-cut passages with `=== SCENE NNN ===` or `=== SCENE NNNA ===` separators; separators are not spoken. Alternate narration is retained here for every omitted frame, excluded from main totals and plain text.

Word counts use whitespace-separated written tokens: contractions and hyphenated words count once. Written acronyms retain normal spelling, including AI, OCR and API; their individual letter names add spoken syllables. Pronounce DLMS as “dee el em ess,” AI as “ay eye,” OCR/API/PDF/CSV as letters, and Anki as “AHN-kee.” Allow the opening acronym to breathe. Do not read production notes. Use a calm conversational delivery, with modest emphasis on the practical consequence of each feature.

## V3 editorial integration

Added: **013A** (Matching), **013B** (Hotspot), **028A** (Content Packs), and **028B** (Study Packs). Tightened: **013** keeps Question Tools separate from richer question types, while **028** now introduces portable bundles and the distinct packaged-dataset path. The approved V2 wording remains elsewhere, including the concise printable physical-card mention in **032**. Pronunciation changes still live only in the synthesis adapter. Individual scene notes mark V3 changes.

V3 inserts the four approved captures without renumbering or altering the V2 set: **013 → 013A → 013B → 014** and **028 → 028A → 028B → 029**. The print layout remains outside the overview; 032 mentions printable cards without pretending the layout is visible. See the [V3 additions manifest](v3-additions-manifest.json), [V3 contact sheet](v3-additions-contact-sheet.png), and [V2 audit and pronunciation review](EDITORIAL_V2.md).

## Assembly notes

Use the canonical 1920 × 1080 Purple & Gold PNGs. Targets are minimum complete scene slots. The existing builder uses straight cuts within workflows and five-frame fades on either side of chapter boundaries, about one third of a second through black in total, with no narration overlap. Earlier scene notes saying “0.3-second dissolve” mean this implemented chapter fade; no new transition implementation is requested. Actual narration duration plus the builder's tail/incoming fade allowance can extend a slot. Leave a brief pause where the picture needs more time than the voice. Never stretch speech to fill a slot.

Use static screenshots throughout. Do not add zoom, pan, Ken Burns movement, fake cursor, typing, click, download, or processing animation. A screenshot of a control establishes an available workflow, not that the action has run.

The story stays in capture order: priorities → sources and Scope → import and repair → Study feedback → evidence and interpretation → scheduling → generated practice and completion → history → portability and source maintenance → Anki → optional external AI → backup → Dashboard. Scope chooses eligible material; intelligence interprets evidence; generated practice assembles questions. These explanations have separate jobs.

[video-manifest.json](video-manifest.json) remains the unchanged V2 capture/provenance contract. [v3-additions-manifest.json](v3-additions-manifest.json) supplies the four additive capture records. Their capture-phase `duration_estimate` values do **not** drive the narrated cut. This document owns editorial inclusion, final spoken text, and revised scene durations; the production tool derives its sequence from both capture manifests plus this narration. Do not regenerate capture assets for narration changes.

## Redundancy decisions

All 40 production frames were assessed, including the essential frames; the original optional flags did not determine the outcome alone.

| Frames | Decision and reason |
| --- | --- |
| 001–002 | Keep the brief orientation followed by concrete recommendations. Avoid a second feature list. |
| 003–005 | Keep organization, active scope, and proof that excluded content remains usable. Each answers a different question. |
| 006–008 | Keep creation choices, supported import paths, and local OCR limits. Do not narrate both import forms field by field. |
| 009–010 | Keep overview plus one unresolved answer. This makes human review concrete. |
| 011–013B | Keep unanswered, incorrect, and corrected choice states, then briefly show Matching and Hotspot as richer Study interactions. Question Tools stays with the visible explanation in 013. |
| 014–016 | Keep evidence, interpretation, and inspectable model. Avoid repeating mastery mechanics in each scene. |
| 017 | **CUT.** The profile is useful in the app but repeats the recommendation and intelligence story here. |
| 018–019 | Keep schedule overview and one readable overdue queue with timing reasons. |
| 020 | **KEEP FOR LONG VERSION.** Topic timing is distinct, but explaining another schedule interrupts the main loop. |
| 021–022 | Keep the saved Adaptive session and its expanded provenance. Do not repeat the Library tour. |
| 023–025 | Keep explicit finish, successful acknowledgment, and retained playable session. Shorten the acknowledgment hold rather than remove this evidence. |
| 026–027 | Keep individual Exam attempts and aggregate results, with one clear distinction from Study evidence. |
| 028–028B | Keep portable bundles distinct from reusable packaged datasets. Content Packs shows package management; Study Packs shows learner-facing quiz creation. |
| 029–030 | Keep scan context and one exact comparison. These prove manual source maintenance without promising automatic cleanup. |
| 031–032 | Keep digital export and shared card selection; mention browser-printable physical cards without pretending the offscreen print layout is displayed. |
| 033 | **KEEP.** Makes optional, provider-neutral content creation and manual return explicit; 013 covers a different question-explanation handoff. |
| 034 | Keep persistent-workspace backup and local ownership context. |
| 035 | **CUT.** Most expendable: a broad settings menu would delay the close and repeat preferences/backup context. |
| 036 | Keep the Dashboard bookend, now framed around reusable history rather than another tour. |

## Scene timing overview

The speech estimate is word count divided by the scene's reference rate, rounded to one decimal second. The target allows more time for the image and natural cadence. Omitted scenes show zero main-cut time and a reusable alternate slot.

| Scene | Main status | Words | Reference WPM | Speech estimate | Main target |
| --- | --- | ---: | ---: | ---: | ---: |
| 001 | Essential | 25 | 145 | 10.3s | 11s |
| 002 | Essential | 24 | 145 | 9.9s | 11s |
| 003 | Essential | 27 | 148 | 10.9s | 12s |
| 004 | Essential | 25 | 138 | 10.9s | 12s |
| 005 | Essential | 12 | 148 | 4.9s | 7s |
| 006 | Essential | 31 | 148 | 12.6s | 15s |
| 007 | Essential | 29 | 145 | 12.0s | 15s |
| 008 | Essential | 36 | 138 | 15.7s | 18s |
| 009 | Essential | 26 | 145 | 10.8s | 13s |
| 010 | Essential | 22 | 145 | 9.1s | 10s |
| 011 | Essential | 24 | 148 | 9.7s | 11s |
| 012 | Essential | 26 | 148 | 10.5s | 12s |
| 013 | Essential | 26 | 138 | 11.3s | 14s |
| 013A | Essential | 19 | 138 | 8.3s | 11s |
| 013B | Essential | 24 | 138 | 10.4s | 11s |
| 014 | Essential | 18 | 138 | 7.8s | 10s |
| 015 | Essential | 15 | 138 | 6.5s | 8s |
| 016 | Essential | 16 | 138 | 7.0s | 9s |
| 017 | CUT | 21 | 145 | 8.7s | 0s |
| 018 | Essential | 24 | 138 | 10.4s | 12s |
| 019 | Essential | 19 | 138 | 8.3s | 10s |
| 020 | LONG VERSION | 29 | 145 | 12.0s | 0s |
| 021 | Essential | 25 | 145 | 10.3s | 11s |
| 022 | Essential | 25 | 138 | 10.9s | 12s |
| 023 | Essential | 20 | 138 | 8.7s | 10s |
| 024 | Essential | 13 | 145 | 5.4s | 8s |
| 025 | Essential | 20 | 148 | 8.1s | 9s |
| 026 | Essential | 24 | 145 | 9.9s | 11s |
| 027 | Essential | 16 | 145 | 6.6s | 9s |
| 028 | Essential | 23 | 138 | 10.0s | 12s |
| 028A | Essential | 20 | 138 | 8.7s | 10s |
| 028B | Essential | 23 | 138 | 10.0s | 12s |
| 029 | Essential | 21 | 148 | 8.5s | 10s |
| 030 | Essential | 22 | 148 | 8.9s | 10s |
| 031 | Essential | 25 | 148 | 10.1s | 11s |
| 032 | Essential | 29 | 148 | 11.8s | 15s |
| 033 | Optional — KEEP | 29 | 138 | 12.6s | 15s |
| 034 | Essential | 28 | 138 | 12.2s | 13s |
| 035 | CUT | 22 | 145 | 9.1s | 0s |
| 036 | Essential | 28 | 145 | 11.6s | 15s |

## Scene 001 — A useful next study session

**Image:** [001-dashboard.png](captures/001-dashboard.png)
**Status:** Essential — KEEP
**Target:** 11 sec
**Speech estimate:** 25 words; 10.3 sec at 145 WPM
**Visual focus:** Dashboard title and Today’s Review panel.
**Motion:** Static hold; retain the full Dashboard context.

**Narration**

> DLMS is a local-first study workspace that connects quiz practice with learning intelligence. It remembers your practice and helps you decide what deserves attention next.

**Production / transition note:** Establish the workspace before cutting to its recommendations. Local operation is product context, not something a still image proves.

## Scene 002 — Today’s Review

**Image:** [002-todays-review.png](captures/002-todays-review.png)
**Status:** Essential — KEEP
**Target:** 11 sec
**Speech estimate:** 24 words; 9.9 sec at 145 WPM
**Visual focus:** The two recommendation rows: due questions and Access Control.
**Motion:** Static hold; retain both action buttons.

**Narration**

> Today’s Review turns that history into a short plan. Here, it suggests overdue questions and a weak concept, with a reason for each recommendation.

**Production / transition note:** Straight cut from 001. Do not describe the panel as a fixed daily assignment or a separate AI algorithm.

## Scene 003 — Organize the material

**Image:** [003-quiz-library.png](captures/003-quiz-library.png)
**Status:** Essential — KEEP
**Target:** 12 sec
**Speech estimate:** 27 words; 10.9 sec at 148 WPM
**Visual focus:** Expanded Core Skills folder and its four quiz cards.
**Motion:** Static hold; keep Core Skills and surrounding Library context visible.

**Narration**

> The Quiz Library organizes source material in folders, so related quizzes stay together. You can return to a subject or edit its questions as your studies grow.

**Production / transition note:** Keep the automatic review groups in context, but leave their explanation for 021–025.

## Scene 004 — Choose Learning Scope

**Image:** [004-learning-scope.png](captures/004-learning-scope.png)
**Status:** Essential — KEEP
**Target:** 12 sec
**Speech estimate:** 25 words; 10.9 sec at 138 WPM
**Visual focus:** Scope summary and excluded Past Projects row.
**Motion:** Static hold; both summary and exclusion must remain visible.

**Narration**

> Learning Scope chooses which folders inform current recommendations and intelligence. Excluding Past Projects leaves its quizzes, history, and schedules saved, while keeping current priorities focused.

**Production / transition note:** Scope selects eligible material. It does not pause or reset saved schedules.

## Scene 005 — Keep access to past work

**Image:** [005-scope-library.png](captures/005-scope-library.png)
**Status:** Essential — KEEP
**Target:** 7 sec
**Speech estimate:** 12 words; 4.9 sec at 148 WPM
**Visual focus:** Past Projects exclusion badge, Open Quiz and Hide controls.
**Motion:** Static hold; keep the expanded Past Projects card visible.

**V2 change:** Tightened to fund the stronger content workflow.

**Narration**

> Excluded quizzes remain available. Hiding a folder is a separate browsing choice.

**Production / transition note:** This is evidence of retained access, not a second Library tour.

## Scene 006 — Bring your own content

**Image:** [006-build-quiz.png](captures/006-build-quiz.png)
**Status:** Essential — KEEP
**Target:** 15 sec
**Speech estimate:** 31 words; 12.6 sec at 148 WPM
**Visual focus:** Text upload, Paste questions, PDF import and Import matching pairs cards.
**Motion:** Static hold across the two columns.

**V2 change:** Substantially rewritten for import / reusable-content / printable-card coverage.

**Narration**

> You do not have to enter every question by hand. Bring in a formatted text file, paste questions for cleanup and preview, or turn a CSV terminology list into matching practice.

**Production / transition note:** Use a 0.3-second chapter dissolve into 006.

## Scene 007 — PDF and image import

**Image:** [007-pdf-import.png](captures/007-pdf-import.png)
**Status:** Essential — KEEP
**Target:** 15 sec
**Speech estimate:** 29 words; 12.0 sec at 145 WPM
**Visual focus:** PDF form and local screenshot import panel.
**Motion:** Static hold across the import forms.

**V2 change:** Substantially rewritten for import / reusable-content / printable-card coverage.

**Narration**

> For PDFs, DLMS extracts selectable text from question banks and glossaries. Review the extracted material, then build quizzes from saved banks. Reviewed terminology can become matching or multiple-choice practice.

**Production / transition note:** Say PDF as letters. No general textbook-to-quiz claim and no implication that analysis has run.

## Scene 008 — Local OCR, reviewed output

**Image:** [008-ocr-source.png](captures/008-ocr-source.png)
**Status:** Essential — KEEP
**Target:** 18 sec
**Speech estimate:** 36 words; 15.7 sec at 138 WPM
**Visual focus:** Both local OCR panels: question screenshots and terminology images or scanned PDF.
**Motion:** Static hold across both panels; retain the current-import-scope note.

**V2 change:** Substantially rewritten for import / reusable-content / printable-card coverage.

**Narration**

> When text is trapped in a scan or screenshot, local OCR can recover candidate questions or terminology pairs. Supported paths include selected scanned question-bank pages and scanned glossaries. The result is a draft, ready for checking.

**Production / transition note:** Selected file only; source image pixels and extraction results are not displayed. No simulated click or processing animation.

## Scene 009 — Review before saving

**Image:** [009-review-repair.png](captures/009-review-repair.png)
**Status:** Essential — KEEP
**Target:** 13 sec
**Speech estimate:** 26 words; 10.8 sec at 145 WPM
**Visual focus:** Two-question summary and complete first question with editable explanation.
**Motion:** Static hold; keep the first question readable.

**V2 change:** Substantially rewritten for import / reusable-content / printable-card coverage.

**Narration**

> This separate prepared example shows Review and Repair. Check extracted wording, choices, answers, and explanations before saving. Recovery helps preserve useful material while keeping uncertainty visible.

**Production / transition note:** A 0.3-second dissolve marks a separate example after 008. Keep “separate prepared example” in the recording; this is not the output of the selected image.

## Scene 010 — Resolve uncertainty

**Image:** [010-repair-detail.png](captures/010-repair-detail.png)
**Status:** Essential — KEEP
**Target:** 10 sec
**Speech estimate:** 22 words; 9.1 sec at 145 WPM
**Visual focus:** Incomplete filter, missing-answer warning, unselected correctness controls.
**Motion:** Static hold.

**Narration**

> The incomplete question has no detected correct answer. Repair it or exclude it, so uncertain material does not quietly become trusted practice.

**Production / transition note:** Do not animate a repair or successful save. Dissolve to a different, already published quiz in 011.

## Scene 011 — Study at your own pace

**Image:** [011-study-start.png](captures/011-study-start.png)
**Status:** Essential — KEEP
**Target:** 11 sec
**Speech estimate:** 24 words; 9.7 sec at 148 WPM
**Visual focus:** Network Troubleshooting title, untimed Study banner, first unanswered question.
**Motion:** Static hold; preserve full question and choices.

**Narration**

> With a published quiz, Study Mode gives you time to think. This networking example is untimed, so you can work at your own pace.

**Production / transition note:** 0.3-second dissolve. This quiz is not the preceding repair draft.

## Scene 012 — Use feedback

**Image:** [012-study-feedback.png](captures/012-study-feedback.png)
**Status:** Essential — KEEP
**Target:** 12 sec
**Speech estimate:** 26 words; 10.5 sec at 148 WPM
**Visual focus:** Red choice B and “Not quite” feedback.
**Motion:** Static hold matched to 013 as closely as existing framing permits.

**Narration**

> An incorrect choice gets immediate feedback and an invitation to try again. You can reconsider your reasoning while the question is still in front of you.

**Production / transition note:** Straight cut. The explanation appears only after the corrected answer in 013.

## Scene 013 — Question Tools

**Image:** [013-question-tools.png](captures/013-question-tools.png)
**Status:** Essential — KEEP
**Target:** 14 sec
**Speech estimate:** 26 words; 11.3 sec at 138 WPM
**Visual focus:** Green answer, explanation, then the three Question Tools.
**Motion:** Static hold; keep the answer, explanation, and Question Tools visible.

**V3 change:** Tightened so the following frames can establish richer question interactions without repeating the feedback story. Written acronym pronunciation belongs only in synthesis input.

**Narration**

> The correct answer reveals the explanation. Question Tools can mark it for Anki, copy a prompt, or open your configured AI provider for a manual handoff.

**Production / transition note:** No provider visit or clipboard result is shown. Mark for Anki is a session selection, not an exported deck. Straight cut to the first richer question type.

## Scene 013A — Match related concepts

**Image:** [013A-matching-question.png](captures/013A-matching-question.png)
**Status:** Essential — KEEP
**Target:** 11 sec
**Speech estimate:** 19 words; 8.3 sec at 138 WPM
**Visual focus:** Three completed pairs, the empty answer pool, and the correct-result feedback.
**Motion:** Static hold; keep all pairs and feedback visible.

**V3 addition:** Briefly establishes Matching as a direct question interaction inside Study Mode.

**Narration**

> Matching questions let you pair related concepts directly. Completed pairs receive immediate correctness feedback within the normal Study workflow.

**Production / transition note:** Straight cut from 013. The completed state communicates placement and result without an interaction tutorial.

## Scene 013B — Answer on an image

**Image:** [013B-hotspot-question.png](captures/013B-hotspot-question.png)
**Status:** Essential — KEEP
**Target:** 11 sec
**Speech estimate:** 24 words; 10.4 sec at 138 WPM
**Visual focus:** Original service diagram, selected Recovery copy region, marker, and correct-result feedback.
**Motion:** Static hold; keep the diagram, selected region, and feedback visible.

**V3 addition:** Establishes Hotspot as a spatial question interaction using original synthetic artwork.

**Narration**

> Hotspot questions make answers spatial. Select the relevant region on an image, then review the result and explanation through the same Study feedback workflow.

**Production / transition note:** Straight cut from 013A, then use the existing chapter fade into 014. The screenshot shows a completed correct selection; do not simulate a click.

## Scene 014 — Read learning evidence

**Image:** [014-learning-intelligence.png](captures/014-learning-intelligence.png)
**Status:** Essential — KEEP
**Target:** 10 sec
**Speech estimate:** 18 words; 7.8 sec at 138 WPM
**Visual focus:** Concept table, response counts, Study/Exam evidence and mastery columns.
**Motion:** Static hold across the whole table.

**V2 change:** Tightened to fund the stronger content workflow.

**Narration**

> Saved Study answers and Exam results feed Learning Intelligence. Concept-level evidence helps you look beyond a single score.

**Production / transition note:** 0.3-second chapter dissolve. Introduce evidence here; leave interpretation and model details to 015 and 016.

## Scene 015 — Compare direction and confidence

**Image:** [015-concept-trends.png](captures/015-concept-trends.png)
**Status:** Essential — KEEP
**Target:** 8 sec
**Speech estimate:** 15 words; 6.5 sec at 138 WPM
**Visual focus:** Four concept rows, especially Trend, overall Accuracy and Not enough data.
**Motion:** Static hold; do not pan between rows while viewers compare them.

**V2 change:** Tightened to fund the stronger content workflow.

**Narration**

> Access Control is improving but still weak overall. Cloud needs more evidence before drawing conclusions.

**Production / transition note:** Allow a short pause after the Cloud comparison. The practice controls below remain visible but are explained when the saved session appears in 021.

## Scene 016 — Understand mastery

**Image:** [016-mastery-model.png](captures/016-mastery-model.png)
**Status:** Essential — KEEP
**Target:** 9 sec
**Speech estimate:** 16 words; 7.0 sec at 138 WPM
**Visual focus:** Mastery dialog introduction and four weighted factors.
**Motion:** Static hold; avoid cropping the dialog.

**V2 change:** Tightened to fund the stronger content workflow.

**Narration**

> The mastery explanation shows how overall results, recent performance, evidence, and recency contribute to the estimate.

**Production / transition note:** Do not read the formula or percentages aloud. Cut directly to 018 in the main version.

## Scene 017 — Learning Profile

**Image:** [017-learning-profile.png](captures/017-learning-profile.png)
**Status:** Optional — CUT
**Target:** 0 sec in main cut; 10 sec if restored
**Speech estimate:** 21 words; 8.7 sec at 145 WPM
**Visual focus:** Next Best Action and strength/weakness panels.
**Motion:** Static hold if reused.

**Alternate narration — not in main cut**

> Learning Profile gathers strengths, weak areas, and a suggested next action into one summary. Here, it points toward reviewing weak topics.

**Production / transition note:** CUT. Repeats the recommendation and interpretation already established in 002 and 014–016. Alternate narration only; exclude from main recording.

## Scene 018 — Space the review

**Image:** [018-review-schedule.png](captures/018-review-schedule.png)
**Status:** Essential — KEEP
**Target:** 12 sec
**Speech estimate:** 24 words; 10.4 sec at 138 WPM
**Visual focus:** Question-level schedule summary and Review Due Questions action.
**Motion:** Static hold; retain the schedule summary and surrounding context.

**Narration**

> Due Questions adds spaced review. Each source question gets a schedule from recorded answers, helping you revisit material without choosing every review date yourself.

**Production / transition note:** 0.3-second chapter dissolve. This is question-level timing, not a mastery score.

## Scene 019 — Inspect what is overdue

**Image:** [019-due-queue.png](captures/019-due-queue.png)
**Status:** Essential — KEEP
**Target:** 10 sec
**Speech estimate:** 19 words; 8.3 sec at 138 WPM
**Visual focus:** Three overdue rows and interval-model cards beneath them.
**Motion:** Static hold with queue and interval explanation visible.

**V2 change:** Tightened to fund the stronger content workflow.

**Narration**

> Correct streaks extend review intervals. An incorrect answer resets the interval to one day. Overdue questions stay visible here.

**Production / transition note:** Due now and Overdue are separate table filters. Do not imply table filters change the generated review batch. Cut to 021 in the main version.

## Scene 020 — Topic retention

**Image:** [020-topic-retention.png](captures/020-topic-retention.png)
**Status:** Optional — KEEP FOR LONG VERSION
**Target:** 0 sec in main cut; 13 sec if restored
**Speech estimate:** 29 words; 12.0 sec at 145 WPM
**Visual focus:** Topic retention table and base-mastery versus retention columns.
**Motion:** Static hold if included in the longer cut.

**Alternate narration — not in main cut**

> Topic Retention offers a separate schedule for whole concepts, using mastery and recent activity. Its retention estimate helps time another review while leaving the underlying answers and accuracy intact.

**Production / transition note:** KEEP FOR LONG VERSION. Distinct capability, but a second timing model interrupts the short feedback-loop story. Insert between 019 and 021; alternate narration only.

## Scene 021 — Generate focused practice

**Image:** [021-generated-practice.png](captures/021-generated-practice.png)
**Status:** Essential — KEEP
**Target:** 11 sec
**Speech estimate:** 25 words; 10.3 sec at 145 WPM
**Visual focus:** Active Generated Practice group and Adaptive Study card.
**Motion:** Static hold; retain the Adaptive Study card and Library context.

**Narration**

> Adaptive Study assembles existing questions around weak areas, recent misses, and review timing. The Library keeps the saved session under Generated Practice, ready to open.

**Production / transition note:** 0.3-second dissolve from schedule. This is an existing Adaptive session, not the result of clicking Review Due Questions. Generated means assembled from source questions, not AI-authored.

## Scene 022 — Keep source provenance

**Image:** [022-source-provenance.png](captures/022-source-provenance.png)
**Status:** Essential — KEEP
**Target:** 12 sec
**Speech estimate:** 25 words; 10.9 sec at 138 WPM
**Visual focus:** Expanded three-source disclosure under Adaptive Study.
**Motion:** Static hold; retain the source names and card title.

**Narration**

> The source list shows where those questions came from. Practice answers feed the original questions’ learning records, adding evidence without creating an independent source pool.

**Production / transition note:** Straight cut. The Smart View groups by normal folder placement; do not call Uncategorized a new storage location caused by this view.

## Scene 023 — Finish explicitly

**Image:** [023-finish-review.png](captures/023-finish-review.png)
**Status:** Essential — KEEP
**Target:** 10 sec
**Speech estimate:** 20 words; 8.7 sec at 138 WPM
**Visual focus:** Final question, full progress bar and enabled Finish Review button.
**Motion:** Static hold.

**Narration**

> Finish Review explicitly closes a generated Study session. Answering the final question alone does not mark the saved review complete.

**Production / transition note:** Cut forward to the end of the saved Adaptive session. No implication that only this question was answered.

## Scene 024 — Confirm completion

**Image:** [024-review-finished.png](captures/024-review-finished.png)
**Status:** Essential — KEEP
**Target:** 8 sec
**Speech estimate:** 13 words; 5.4 sec at 145 WPM
**Visual focus:** “Review completed” status under the answer explanation.
**Motion:** Static hold; keep status line readable.

**V2 change:** Tightened to fund the stronger content workflow.

**Narration**

> The completion message confirms that the answers were saved and the session closed.

**Production / transition note:** Straight cut from 023; no fake pointer. A brief silent hold lets viewers find the small success message.

## Scene 025 — Retain completed practice

**Image:** [025-completed-practice.png](captures/025-completed-practice.png)
**Status:** Essential — KEEP
**Target:** 9 sec
**Speech estimate:** 20 words; 8.1 sec at 148 WPM
**Visual focus:** Completed group, Adaptive completion badge, source disclosure and Open Quiz.
**Motion:** Static hold; retain the completed Adaptive card and its actions.

**Narration**

> Completed Generated Practice retains the session. It stays playable, with its source links and learning evidence preserved for later use.

**Production / transition note:** Straight cut. Automatic groups are presentations, not physical folders; completion is not deletion.

## Scene 026 — Revisit scored attempts

**Image:** [026-history.png](captures/026-history.png)
**Status:** Essential — KEEP
**Target:** 11 sec
**Speech estimate:** 24 words; 9.9 sec at 145 WPM
**Visual focus:** History attempt rows, Exam mode labels and Review actions.
**Motion:** Static hold.

**Narration**

> History keeps completed Exam attempts available for review. Study answers feed learning evidence separately, so our practice does not add a scored attempt here.

**Production / transition note:** 0.3-second chapter dissolve. The eighteen Exam attempts are prepared history, not results produced by the shown Study session.

## Scene 027 — Compare results over time

**Image:** [027-analytics.png](captures/027-analytics.png)
**Status:** Essential — KEEP
**Target:** 9 sec
**Speech estimate:** 16 words; 6.6 sec at 145 WPM
**Visual focus:** Quiz Performance rows and average/best/latest columns.
**Motion:** Static hold; retain the full quiz table.

**V2 change:** Tightened to fund the stronger content workflow.

**Narration**

> Analytics compares saved results by quiz across your history, showing average, best, and latest performance together.

**Production / transition note:** Do not equate Analytics “Steady” with concept-level trend. These are different calculations; avoid narrating that column.

## Scene 028 — Portable quizzes and packaged datasets

**Image:** [028-bundles.png](captures/028-bundles.png)
**Status:** Essential — KEEP
**Target:** 12 sec
**Speech estimate:** 23 words; 10.0 sec at 138 WPM
**Visual focus:** Bundle import/export columns, Not a Study Pack callout, Study Packs and Content Packs navigation.
**Motion:** Static hold across export and import columns.

**V3 change:** Tightened to introduce two distinct content paths before the dedicated Content Packs and Study Packs frames.

**Narration**

> Portable bundles move source quizzes and supported images without learning history. Reusable packaged datasets provide a separate way to bring material into DLMS.

**Production / transition note:** Use the existing chapter fade into 028. No export, file write, or import occurs. Portable bundles are distinct from Content Pack installation and ordinary PDF, OCR, or CSV import.

## Scene 028A — Manage Content Packs

**Image:** [028A-content-packs.png](captures/028A-content-packs.png)
**Status:** Essential — KEEP
**Target:** 10 sec
**Speech estimate:** 20 words; 8.7 sec at 138 WPM
**Visual focus:** Pack metadata, independent validation, three dataset types, and the two tracked generated quizzes.
**Motion:** Static hold; retain metadata, validation, datasets, and generated-quiz tracking.

**V3 addition:** Shows Content Packs as the package and dataset management workspace.

**Narration**

> Content Packs is the management side: it validates installed packages, reports their datasets, and tracks the quizzes created from them.

**Production / transition note:** Straight cut from 028. Let the visible metadata and dataset rows carry the detail; do not read them item by item.

## Scene 028B — Create from Study Packs

**Image:** [028B-study-packs.png](captures/028B-study-packs.png)
**Status:** Essential — KEEP
**Target:** 12 sec
**Speech estimate:** 23 words; 10.0 sec at 138 WPM
**Visual focus:** Expanded Study Pack catalog with matching, image or hotspot, and prepared-question datasets plus Create Quiz actions.
**Motion:** Static hold; retain all three dataset rows and their Create Quiz actions.

**V3 addition:** Shows Study Packs as the learner-facing catalog for creating quizzes from installed reusable datasets.

**Narration**

> Study Packs is the learner-facing catalog. Choose a matching, image, or prepared-question dataset and create a quiz while keeping the reusable source installed.

**Production / transition note:** Straight cut from 028A, then straight cut to 029. No quiz is generated during capture; the visible actions establish the available workflow.

## Scene 029 — Find source overlap

**Image:** [029-duplicates.png](captures/029-duplicates.png)
**Status:** Essential — KEEP
**Target:** 10 sec
**Speech estimate:** 21 words; 8.5 sec at 148 WPM
**Visual focus:** Two exact groups and source-scan summary, including Past Projects.
**Motion:** Static hold.

**Narration**

> Duplicate Review locates overlapping source questions as your library grows. Generated practice copies are excluded, keeping comparisons focused on original material.

**Production / transition note:** All-library maintenance includes the excluded Past Projects source. This is not the active Learning Scope.

## Scene 030 — Compare before changing

**Image:** [030-duplicate-detail.png](captures/030-duplicate-detail.png)
**Status:** Essential — KEEP
**Target:** 10 sec
**Speech estimate:** 22 words; 8.9 sec at 148 WPM
**Visual focus:** Exact risky-change pair, correct answers and Edit source quiz links.
**Motion:** Static hold; retain both compared records.

**Narration**

> Here, one question appears in two quizzes. Compare the answers and open either source for editing. The report itself makes no changes.

**Production / transition note:** Straight cut. Keep this detail proof, but avoid another explanation of source provenance or automatic cleanup.

## Scene 031 — Use Anki alongside DLMS

**Image:** [031-anki-tools.png](captures/031-anki-tools.png)
**Status:** Essential — KEEP
**Target:** 11 sec
**Speech estimate:** 25 words; 10.1 sec at 148 WPM
**Visual focus:** Quiz to Anki and Missed Questions to Anki panels.
**Motion:** Static hold across both panels.

**Narration**

> Anki Tools exports quiz questions or recorded misses as flashcards. Import the deck into Anki for its study workflow while keeping your material in DLMS.

**Production / transition note:** 0.3-second chapter dissolve. Text front/back export, not embedded image interaction or synchronization. No external application is shown.

## Scene 032 — Select a smaller deck

**Image:** [032-anki-selection.png](captures/032-anki-selection.png)
**Status:** Essential — KEEP
**Target:** 15 sec
**Speech estimate:** 29 words; 11.8 sec at 148 WPM
**Visual focus:** One checked Everyday Data Safety question and unselected missed-question list.
**Motion:** Static hold; retain the selection count and list headings.

**V2 change:** Substantially rewritten for import / reusable-content / printable-card coverage.

**Narration**

> Choose individual questions or recorded misses for a focused set. Those same selected cards can also become printable physical flash cards, through a browser layout for three-by-five index cards.

**Production / transition note:** The Custom Deck & Printable Cards navigation label and card selection establish the shared workflow. The Avery 5388 layout and print controls are below this viewport, not pictured. Mention availability only; do not imply printing, downloading, or selecting missed items has happened. Keep the sidebar visible. No additional capture is needed for this brief overview mention.

## Scene 033 — Optional external AI content

**Image:** [033-external-ai.png](captures/033-external-ai.png)
**Status:** Optional — KEEP in main cut
**Target:** 15 sec
**Speech estimate:** 29 words; 12.6 sec at 138 WPM
**Visual focus:** Six workflow steps and provider-neutral configuration description.
**Motion:** Static hold on the workflow strip and form.

**V2 change:** Written acronym normalized; pronunciation belongs only in synthesis input.

**Narration**

> External AI uses a manual handoff. Take a prompt to your chosen provider, then paste its structured response back for validation and repair. No direct provider API is required.

**Production / transition note:** KEEP, despite optional capture status. 0.3-second dissolve separates this content-input workflow from Anki output. Do not imply background transmission or automatic retrieval.

## Scene 034 — Preserve the workspace

**Image:** [034-backup.png](captures/034-backup.png)
**Status:** Essential — KEEP
**Target:** 13 sec
**Speech estimate:** 28 words; 12.2 sec at 138 WPM
**Visual focus:** Portable Backup scope and Create & Download Backup.
**Motion:** Static hold; retain Portable Backup and page context.

**Narration**

> Backups preserve quizzes, settings, and learning history. DLMS is a single-user application with native desktop packages and no required cloud account. Your study data stays under your control.

**Production / transition note:** 0.3-second chapter dissolve. Native packages and account requirements are verified product context, not a visible installation demonstration. No backup or restore action is performed.

## Scene 035 — Settings overview

**Image:** [035-settings.png](captures/035-settings.png)
**Status:** Optional — CUT
**Target:** 0 sec in main cut; 10 sec if restored
**Speech estimate:** 22 words; 9.1 sec at 145 WPM
**Visual focus:** Appearance, Navigation and AI Integration cards.
**Motion:** Static hold if reused.

**Alternate narration — not in main cut**

> Settings gathers appearance, navigation, and optional helper preferences in one place, so you can adjust the workspace around the way you study.

**Production / transition note:** CUT. Broad settings tour adds no necessary story beat after backup; most expendable frame. Alternate narration only.

## Scene 036 — Return to the next useful step

**Image:** [036-closing-dashboard.png](captures/036-closing-dashboard.png)
**Status:** Essential — KEEP
**Target:** 15 sec
**Speech estimate:** 28 words; 11.6 sec at 145 WPM
**Visual focus:** Dashboard title, Today’s Review and entry points for content/study.
**Motion:** Static hold for the closing Dashboard.

**Narration**

> Back on the Dashboard, each study decision builds on earlier work. Bring in useful material, review it, and practice. Your content and learning history remain yours to reuse.

**Production / transition note:** 0.3-second dissolve from 034. Recommendations remain; do not imply that finishing one review clears every need. Final hold and fade are included in the target.

## Factual and visual QA

Every spoken factual claim, including alternate passages, was checked against the current product documentation, rendered final captures, and relevant implementation where behavior needed disambiguation. All 36 V2 PNGs and the four full-resolution V3 additions were inspected. The continuous main script received an editorial pass for repetition, transitions, cadence, and timing. No product-behavior questions remain unresolved for this script.

| Scenes | Verification sources and limits |
| --- | --- |
| 001–002, 036 | [Introduction](../user-manual/01-introduction.md), [Today’s Review](../user-manual/07-study-and-review.md#start-with-todays-review), [daily-review service](../../dlms/services/daily_review.py). A short plan combines existing signals. The opening has four due questions; the closing has three and still recommends Access Control. No claim that all needs disappear. |
| 003–005 | [Library](../user-manual/05-quiz-library-and-organization.md), [Learning Scope](../user-manual/08-learning-intelligence.md#choose-your-learning-scope), [scope service](../../dlms/services/learning_scope.py), [scope template](../../templates/learning/scope.html). Exclusion preserves evidence and elapsed schedule time; Hide is separate. |
| 006–010 | [Creation/import](../user-manual/04-creating-and-importing-content.md), [PDF and OCR](../user-manual/10-pdf-smart-pdf-and-ocr.md), [capture setup](README.md#import-and-portability-setup), [fixture](../../tools/demo_video_fixture.py). Local supported extraction, editable draft, and missing answer are accurate. Frame 009 is a separate seeded PDF draft, not measured output from frame 008. |
| 011–013B | [Quiz behavior](../user-manual/06-taking-quizzes.md), [Study Packs help](../../static/help-study-packs.html), [external explanation](../user-manual/12-external-ai-workflows.md#ask-for-an-external-explanation), [Study script](../../static/script.js). Incorrect feedback precedes the corrected answer and visible explanation. Matching pairs and hotspot selections use the normal Study response and feedback path in the captured states. Copy Question copies an AI-ready prompt locally; Review with AI copies and opens the configured provider, requiring manual pasting. Mark for Anki collects session choices. |
| 014–017 | [Learning Intelligence](../user-manual/08-learning-intelligence.md), [rendered model/table](../../static/learning-intelligence.html), [fixture validation](VALIDATION.md#fixture-sanity). Access Control is improving but still weak by overall accuracy. Cloud has one response and provisional mastery, not a reliable strength/weakness classification. Mastery is a study signal. |
| 018–020 | [Study and Review](../user-manual/07-study-and-review.md), [schedule UI](../../static/review-schedule.html), [question review service](../../dlms/services/question_review.py). Correct streaks extend intervals; incorrect responses reset to one day. Question and topic schedules differ. Overdue and Due now are distinct table filters. |
| 021–022 | [Adaptive Study and Generated Practice](../user-manual/07-study-and-review.md), [Library provenance](../user-manual/05-quiz-library-and-organization.md#recognize-generated-practice), [mastery explanation](../../static/learning-intelligence.html). Existing source questions form Adaptive practice; known lineage credits originals. This fixture has three resolved sources. No claim of AI authorship or newly generated wording. |
| 023–025 | [Generated Practice lifecycle](../../dlms/services/generated_practice_lifecycle.py), [Study script](../../static/script.js), [Library template](../../templates/quiz/library.html), [review documentation](../user-manual/07-study-and-review.md#understand-generated-practice). Finish waits for saved responses and server verification; successful completion retains a playable quiz and evidence. Automatic groups are not physical folders. |
| 026–027 | [History and Analytics](../user-manual/09-history-results-and-progress.md), [Learning Scope](../user-manual/08-learning-intelligence.md#choose-your-learning-scope). Study evidence is not a scored Exam attempt. All-history analytics is separate from current scope; its trend is not the concept trend. |
| 028–028B | [Portability](../user-manual/15-import-export-and-portability.md), [Study Packs help](../../static/help-study-packs.html), [Content management help](../../static/help-content-management.html), [bundle service](../../dlms/services/portable_quiz_bundles.py), and [Content Pack service](../../dlms/services/content_packs.py). Eligible ordinary source content and supported media transfer without personal learning history. Content Packs manages validated installed package sources; Study Packs launches learner-facing activities from their datasets. No bundle transfer, pack installation, or quiz creation is shown. |
| 029–030 | [Duplicate Review](../user-manual/05-quiz-library-and-organization.md#review-possible-duplicates), [duplicate template](../../templates/quiz/duplicates.html), [report view](../../dlms/services/quiz_duplicate_view.py). Source scan includes excluded/hidden sources, omits generated copies, and offers manual source editing. No automatic merge/deletion. |
| 031–032 | [Anki workflows](../user-manual/14-anki-decks-and-printable-cards.md), [Anki overview](../../templates/anki/index.html), [custom selection](../../templates/anki/custom.html). Text front/back deck output and selected/missed questions; no Anki synchronization or automatic import. One source question is checked; no missed items are checked. |
| 033 | [External AI](../user-manual/12-external-ai-workflows.md), [privacy boundary](../user-manual/appendix-privacy-and-data-handling.md#external-ai-is-a-manual-optional-boundary), frame 033 workflow strip. Provider-neutral manual prompt/response exchange; no direct provider API or background transmission. Validation does not establish factual correctness. |
| 034–036 | [Installation](../user-manual/02-installation-and-first-launch.md), [backup scope](../user-manual/17-maintenance-backup-and-data-management.md), [privacy](../user-manual/appendix-privacy-and-data-handling.md), [backup service](../../dlms/services/backups.py), [backup template](../../templates/settings/backup.html). Native packages, single-user workspace, no required cloud account, and persistent-data backup. No claim that all temporary files are backed up, that backups are encrypted, or that external services receive no data after a deliberate handoff. |

### Visual limits resolved in the script

- **008 → 009 → 011:** These are workflow illustrations, not one uninterrupted import. Narration explicitly introduces a separate prepared repair example, then a published networking quiz. A chapter dissolve preserves that distinction. No recapture is needed.
- **013 → 013A → 013B:** 013 keeps the explanation and optional tools visible together. The two additions show completed interaction states rather than simulated clicks. Do not narrate every pair, region label, or control.
- **015–016:** The table and model dialog contain more detail than can be read aloud. Narration selects the visible pattern and factors rather than reading percentages or the whole formula. Static holds preserve comparisons.
- **021:** A saved Adaptive session proves the resulting Library item, not the selection algorithm running. Explain the documented behavior without pretending it resulted from the preceding Due Questions action.
- **022:** Source names are small, so the narration explains provenance without requiring viewers to read each name.
- **024:** The success line is small but readable in the canonical image. Allow the dedicated eight-second static hold.
- **028 → 028A → 028B, 031–034:** These show available workflows and selection, not completed transfers. Do not add download confirmations. Native packaging/account requirements in 034 are documented product context; the screenshot itself is a backup screen.
- **035:** The settings overview does not visibly demonstrate a theme change. Its alternate line describes categories only.

No capture defect prevented narration, and no further screenshots are required for this V3 overview. The previously reported correct-answer hover issue remains documented in [VALIDATION.md](VALIDATION.md#existing-product-issue-observed-not-changed); it is not present in the final narrated feedback images and was not modified here.

This phase produces revised text and isolated production-tooling changes. No real audio, video, subtitle timestamps, application changes, version/release edits, commits, or pushes are part of this handoff. Earlier implementation evidence remains in [EDITORIAL_V2.md](EDITORIAL_V2.md).

### Handoff checks

- Text consistency: 40 scene entries; 37 main-cut passages in deterministic V3 order; plain-text passages exactly match their narration blocks; 859 main-cut words; 425 seconds of main-cut targets.
- All linked local files resolve. All 36 V2 image hashes match the unchanged capture manifest, and all four additions match their V3 manifest records.
- Focused narration/video/capture tests and `git diff --check` are the V3 handoff gates. No application code changed; no full render is needed for this editorial/tooling pass.
