# Demo-video screenshot plan — captured sequence

All 36 V2 frames remain captured in [captures/](captures/), separate from proof and manual images. Purple & Gold · 1920 × 1080 · scale 1. Four additive V3 proposal frames use alphanumeric IDs so none of the V2 assets need renumbering. The six V2 contact sheets and [video-manifest.json](video-manifest.json) remain stable; the V3 handoff is [v3-additions-manifest.json](v3-additions-manifest.json) and [v3-additions-contact-sheet.png](v3-additions-contact-sheet.png).

**36 frames · 402 seconds (6:42)** before transitions. Frames 017, 020, 033, 035 are optional and retained. See [STORYBOARD.md](STORYBOARD.md) for narration objectives and focus suggestions.

The four proposed V3 additions total **44 seconds**. Against the current approximately 6:43 assembled overview, they estimate an approximately **7:27** V3. Narration, audio, and video have not been regenerated.

Framing uses real page scrolling and existing collapse/filter controls. Only the target teaching area needs to fit; adjoining long-page content may continue beyond the viewport. No UI text, layout, or data values were painted over. Pointer moved off controls for the final Study detail captures.

## 001 — A personal learning workspace

- **File:** [001-dashboard.png](captures/001-dashboard.png)
- **Route:** `/`
- **Purpose:** A personal learning workspace.
- **Required fixture:** Evidence, due questions, no browser Resume.
- **Exact state / expansion / filters:** Default controls; no search; no open dialogs.
- **Framing:** Overview; page top (dialog if specified).
- **Duration / priority:** ~10 seconds; essential.

## 002 — Choose a useful next step

- **File:** [002-todays-review.png](captures/002-todays-review.png)
- **Route:** `/`
- **Purpose:** Choose a useful next step.
- **Required fixture:** Real server-derived recommendations; no fabricated ranking.
- **Exact state / expansion / filters:** Default controls; no search; no open dialogs.
- **Framing:** Teaching detail; anchor `.daily-review-panel`, 24px top margin where scroll limits permit.
- **Duration / priority:** ~12 seconds; essential.

## 003 — Organize original study content

- **File:** [003-quiz-library.png](captures/003-quiz-library.png)
- **Route:** `/library`
- **Purpose:** Organize original study content.
- **Required fixture:** Base synthetic library.
- **Exact state / expansion / filters:** Visible; no Smart View/search; Core Skills expanded; all other groups collapsed.
- **Framing:** Teaching detail; anchor `#quizList`, 24px top margin where scroll limits permit.
- **Duration / priority:** ~10 seconds; essential.

## 004 — Choose active material

- **File:** [004-learning-scope.png](captures/004-learning-scope.png)
- **Route:** `/learning-scope`
- **Purpose:** Choose active material.
- **Required fixture:** One excluded saved source; no hiding or deletion.
- **Exact state / expansion / filters:** Past Projects excluded; other folders and Uncategorized included.
- **Framing:** Overview; page top (dialog if specified).
- **Duration / priority:** ~12 seconds; essential.

## 005 — Saved does not mean active

- **File:** [005-scope-library.png](captures/005-scope-library.png)
- **Route:** `/library`
- **Purpose:** Saved does not mean active.
- **Required fixture:** Base synthetic library.
- **Exact state / expansion / filters:** Visible; Past Projects expanded and excluded from Learning Scope; other groups collapsed.
- **Framing:** Teaching detail; anchor `#quizList`, 24px top margin where scroll limits permit.
- **Duration / priority:** ~10 seconds; essential.

## 006 — Bring your own content

- **File:** [006-build-quiz.png](captures/006-build-quiz.png)
- **Route:** `/upload`
- **Purpose:** Bring your own content.
- **Required fixture:** Base synthetic library.
- **Exact state / expansion / filters:** Default controls; no search; no open dialogs.
- **Framing:** Overview; page top (dialog if specified).
- **Duration / priority:** ~10 seconds; essential.

## 007 — PDF and image import

- **File:** [007-pdf-import.png](captures/007-pdf-import.png)
- **Route:** `/pdf-import`
- **Purpose:** PDF and image import.
- **Required fixture:** Base synthetic library.
- **Exact state / expansion / filters:** Empty form; no extraction claims.
- **Framing:** Overview; page top (dialog if specified).
- **Duration / priority:** ~10 seconds; essential.

## 008 — An original image as input

- **File:** [008-ocr-source.png](captures/008-ocr-source.png)
- **Route:** `/pdf-import`
- **Purpose:** An original image as input.
- **Required fixture:** Pillow-rendered original text; no external content.
- **Exact state / expansion / filters:** Original study-skills.png selected; rights confirmed; not submitted.
- **Framing:** Teaching detail; anchor `.pdf-ocr-import-panel`, 24px top margin where scroll limits permit.
- **Duration / priority:** ~12 seconds; essential.

## 009 — Inspect before publishing

- **File:** [009-review-repair.png](captures/009-review-repair.png)
- **Route:** `/pdf-import/review/video_review`
- **Purpose:** Inspect before publishing.
- **Required fixture:** Original synthetic staged parser draft; not a claim of OCR accuracy.
- **Exact state / expansion / filters:** Seeded staged draft: one complete, one incomplete; nothing published.
- **Framing:** Teaching detail; anchor `.pdf-import-summary-grid`, 24px top margin where scroll limits permit.
- **Duration / priority:** ~12 seconds; essential.

## 010 — Missing answers remain your decision

- **File:** [010-repair-detail.png](captures/010-repair-detail.png)
- **Route:** `/pdf-import/review/video_review`
- **Purpose:** Missing answers remain your decision.
- **Required fixture:** Same staged draft.
- **Exact state / expansion / filters:** Incomplete filter selected; recovered question visible; no answer invented.
- **Framing:** Teaching detail; anchor `.pdf-import-filter-row`, 24px top margin where scroll limits permit.
- **Duration / priority:** ~10 seconds; essential.

## 011 — Start a self-paced session

- **File:** [011-study-start.png](captures/011-study-start.png)
- **Route:** `@critical_quiz`
- **Purpose:** Start a self-paced session.
- **Required fixture:** Network Troubleshooting source quiz.
- **Exact state / expansion / filters:** Study Mode, question 1; no answer selected.
- **Framing:** Teaching detail; anchor `.active-quiz-logo-banner`, 24px top margin where scroll limits permit.
- **Duration / priority:** ~10 seconds; essential.

## 012 — Learn from an answer

- **File:** [012-study-feedback.png](captures/012-study-feedback.png)
- **Route:** `@critical_quiz`
- **Purpose:** Learn from an answer.
- **Required fixture:** Original network question.
- **Exact state / expansion / filters:** Study Mode question 1, B selected; incorrect feedback visible.
- **Framing:** Teaching detail; anchor `.quiz-toolbar`, 24px top margin where scroll limits permit.
- **Duration / priority:** ~12 seconds; essential.

## 013 — Use optional question tools

- **File:** [013-question-tools.png](captures/013-question-tools.png)
- **Route:** `@critical_quiz`
- **Purpose:** Use optional question tools.
- **Required fixture:** Same original source question.
- **Exact state / expansion / filters:** Correct answer selected after feedback; explanation and Question Tools visible; no provider opened.
- **Framing:** Teaching detail; anchor `.quiz-toolbar`, 8px top margin where scroll limits permit.
- **Duration / priority:** ~14 seconds; essential.

## 013A — Match concepts through direct interaction

- **File:** [013A-matching-question.png](captures/013A-matching-question.png)
- **Proposed placement:** Immediately after 013 and before the Learning Intelligence chapter at 014.
- **Route:** `@matching_quiz`
- **Purpose:** Show matching as a distinct interaction, with all three relationships placed and confirmed.
- **Narration objective:** Explain that matching practice uses shuffled answers and immediate Study Mode feedback without spending time on an interaction tutorial.
- **Required fixture:** Original Recovery & Reliability activity from the synthetic Practical Systems Lab pack.
- **Exact state / expansion / filters:** Study Mode; all three matching answers placed correctly; answer pool empty; correctness feedback visible.
- **Framing:** Teaching detail; anchor `#qHeader` so every pair and feedback row remains visible.
- **Duration / priority:** ~11 seconds; essential V3 addition.

## 013B — Answer by selecting a region

- **File:** [013B-hotspot-question.png](captures/013B-hotspot-question.png)
- **Proposed placement:** Immediately after 013A and before 014.
- **Route:** `@hotspot_quiz`
- **Purpose:** Show that a hotspot answer is a location on an image rather than a conventional answer button.
- **Narration objective:** Let the correct marker, named structure, and brief feedback carry most of the explanation.
- **Required fixture:** Original resilient-service diagram from the synthetic Practical Systems Lab pack.
- **Exact state / expansion / filters:** Study Mode; Recovery copy region selected correctly; marker and explanation visible.
- **Framing:** Teaching detail; the prompt, complete image, selected marker, attribution, and feedback all fit at 1920×1080.
- **Duration / priority:** ~11 seconds; essential V3 addition.

## 014 — See the learning pattern

- **File:** [014-learning-intelligence.png](captures/014-learning-intelligence.png)
- **Route:** `/learning-intelligence`
- **Purpose:** See the learning pattern.
- **Required fixture:** Strong Data Safety; declining Networking; improving Access Control; low-evidence Cloud.
- **Exact state / expansion / filters:** All concepts, empty search; mastery explanation closed; scope summary visible.
- **Framing:** Overview; page top (dialog if specified).
- **Duration / priority:** ~14 seconds; essential.

## 015 — Compare evidence and trends

- **File:** [015-concept-trends.png](captures/015-concept-trends.png)
- **Route:** `/learning-intelligence`
- **Purpose:** Compare evidence and trends.
- **Required fixture:** 18 baseline responses per established concept plus demonstrated Study saves; one Cloud response.
- **Exact state / expansion / filters:** All concepts, no filter; compare actual calculated values.
- **Framing:** Teaching detail; anchor `#liToolbar`, 24px top margin where scroll limits permit.
- **Duration / priority:** ~14 seconds; essential.

## 016 — Explainable intelligence

- **File:** [016-mastery-model.png](captures/016-mastery-model.png)
- **Route:** `/learning-intelligence`
- **Purpose:** Explainable intelligence.
- **Required fixture:** Same evidence; no invented percentages.
- **Exact state / expansion / filters:** How mastery works dialog open.
- **Framing:** Overview; page top (dialog if specified).
- **Duration / priority:** ~12 seconds; essential.

## 017 — Turn results into a next action

- **File:** [017-learning-profile.png](captures/017-learning-profile.png)
- **Route:** `/learning-profile`
- **Purpose:** Turn results into a next action.
- **Required fixture:** Scoped evidence.
- **Exact state / expansion / filters:** Default controls; no search; no open dialogs.
- **Framing:** Overview; page top (dialog if specified).
- **Duration / priority:** ~10 seconds; optional.

## 018 — Review when it is due

- **File:** [018-review-schedule.png](captures/018-review-schedule.png)
- **Route:** `/review-schedule`
- **Purpose:** Review when it is due.
- **Required fixture:** Recent and older source evidence; unseen Cloud questions.
- **Exact state / expansion / filters:** Queue expanded; All status; blank search; default batch size.
- **Framing:** Overview; page top (dialog if specified).
- **Duration / priority:** ~12 seconds; essential.

## 019 — Inspect the source question queue

- **File:** [019-due-queue.png](captures/019-due-queue.png)
- **Route:** `/review-schedule`
- **Purpose:** Inspect the source question queue.
- **Required fixture:** Real overdue source backlog; Due now is a separate status.
- **Exact state / expansion / filters:** Overdue status; queue expanded; empty search.
- **Framing:** Teaching detail; anchor `#nrsQueuePanel`, 24px top margin where scroll limits permit.
- **Duration / priority:** ~12 seconds; essential.

## 020 — Question timing and topic retention

- **File:** [020-topic-retention.png](captures/020-topic-retention.png)
- **Route:** `/review-schedule`
- **Purpose:** Question timing and topic retention.
- **Required fixture:** Derived concept evidence.
- **Exact state / expansion / filters:** Question Queue collapsed; Topic Retention visible.
- **Framing:** Teaching detail; anchor `.review-schedule-summary:not(.native-review-summary)`, 24px top margin where scroll limits permit.
- **Duration / priority:** ~10 seconds; optional.

## 021 — A review built from your sources

- **File:** [021-generated-practice.png](captures/021-generated-practice.png)
- **Route:** `/library`
- **Purpose:** A review built from your sources.
- **Required fixture:** Adaptive active plus a retained completed Smart Review.
- **Exact state / expansion / filters:** Visible Library; active Generated Practice expanded; other groups collapsed.
- **Framing:** Teaching detail; anchor `#quizList`, 24px top margin where scroll limits permit.
- **Duration / priority:** ~12 seconds; essential.

## 022 — Keep the connection to source material

- **File:** [022-source-provenance.png](captures/022-source-provenance.png)
- **Route:** `/library?view=visible&smart=generated-practice`
- **Purpose:** Keep the connection to source material.
- **Required fixture:** Question Identity v2 payloads from three real source quiz rows.
- **Exact state / expansion / filters:** Generated Practice Smart View (all review sessions); first source disclosure expanded; normal folder grouping.
- **Framing:** Teaching detail; anchor `.library-smart-active`, 24px top margin where scroll limits permit.
- **Duration / priority:** ~12 seconds; essential.

## 023 — Explicitly close the review

- **File:** [023-finish-review.png](captures/023-finish-review.png)
- **Route:** `@adaptive_quiz`
- **Purpose:** Explicitly close the review.
- **Required fixture:** Fresh Adaptive Study session; completion marker absent.
- **Exact state / expansion / filters:** All 3 questions answered and saved; final question; Finish Review not yet clicked.
- **Framing:** Teaching detail; anchor `.quiz-toolbar`, 8px top margin where scroll limits permit.
- **Duration / priority:** ~12 seconds; essential.

## 024 — Finish with acknowledged saves

- **File:** [024-review-finished.png](captures/024-review-finished.png)
- **Route:** `@adaptive_quiz`
- **Purpose:** Finish with acknowledged saves.
- **Required fixture:** Real Study saves and server completion handshake.
- **Exact state / expansion / filters:** Finish Review succeeded; success status visible; checkpoint cleared.
- **Framing:** Teaching detail; anchor `.active-quiz-logo-banner`, 24px top margin where scroll limits permit.
- **Duration / priority:** ~10 seconds; essential.

## 025 — Completed is retained, not deleted

- **File:** [025-completed-practice.png](captures/025-completed-practice.png)
- **Route:** `/library`
- **Purpose:** Completed is retained, not deleted.
- **Required fixture:** Seeded retained Smart Review; Adaptive also completed during a full run.
- **Exact state / expansion / filters:** Completed Generated Practice expanded; other groups collapsed; quizzes playable.
- **Framing:** Teaching detail; anchor `#quizList`, 24px top margin where scroll limits permit.
- **Duration / priority:** ~12 seconds; essential.

## 026 — Keep a record of learning

- **File:** [026-history.png](captures/026-history.png)
- **Route:** `/history`
- **Purpose:** Keep a record of learning.
- **Required fixture:** 18 original synthetic Exam attempts, Demo Learner.
- **Exact state / expansion / filters:** Default controls; no search; no open dialogs.
- **Framing:** Overview; page top (dialog if specified).
- **Duration / priority:** ~10 seconds; essential.

## 027 — Look back across your history

- **File:** [027-analytics.png](captures/027-analytics.png)
- **Route:** `/dashboard`
- **Purpose:** Look back across your history.
- **Required fixture:** Same completed attempts; all-history view.
- **Exact state / expansion / filters:** Default controls; no search; no open dialogs.
- **Framing:** Overview; page top (dialog if specified).
- **Duration / priority:** ~10 seconds; essential.

## 028 — Move content without moving personal history

- **File:** [028-bundles.png](captures/028-bundles.png)
- **Route:** `/quiz-bundles`
- **Purpose:** Move content without moving personal history.
- **Required fixture:** Source quizzes eligible; generated sessions excluded.
- **Exact state / expansion / filters:** Export/import landing; source candidates only; no upload yet.
- **Framing:** Teaching detail; anchor `.portable-bundle-workflows`, 24px top margin where scroll limits permit.
- **Duration / priority:** ~12 seconds; essential.

## 028A — Manage reusable content packages

- **File:** [028A-content-packs.png](captures/028A-content-packs.png)
- **Proposed placement:** Immediately after 028.
- **Route:** `/content-packs/details/DLMS_Study_practical_systems_lab`
- **Purpose:** Show Content Packs as the package-management and validation side of reusable study material.
- **Narration objective:** Distinguish an installed source package from generated quizzes, using the validation report and tracked-quiz count as visible evidence.
- **Required fixture:** Installed Practical Systems Lab pack with matching, image, and prepared-question datasets; original content only.
- **Exact state / expansion / filters:** Pack details; valid status; three datasets; two generated quizzes; zero warnings and blocking errors; validation checks visible.
- **Framing:** Overview at page top; no temporary data-root path appears.
- **Duration / priority:** ~10 seconds; essential V3 addition.

## 028B — Launch practice from installed datasets

- **File:** [028B-study-packs.png](captures/028B-study-packs.png)
- **Proposed placement:** Immediately after 028A and before duplicate review at 029.
- **Route:** `/study-packs`
- **Purpose:** Show Study Packs as the learner-facing catalog that turns reusable datasets into quizzes.
- **Narration objective:** Make matching, image/hotspot, and prepared-question sources understandable through their rows and Create Quiz actions.
- **Required fixture:** The same installed Practical Systems Lab pack.
- **Exact state / expansion / filters:** Practical Systems Lab expanded; matching, image/hotspot, and prepared-question rows visible; no quiz generated during capture.
- **Framing:** Overview at page top; heading, creation tools, installed-pack controls, and the complete dataset table fit at 1920×1080.
- **Duration / priority:** ~12 seconds; essential V3 addition.

## 029 — Find duplicate source questions

- **File:** [029-duplicates.png](captures/029-duplicates.png)
- **Route:** `/library/duplicates`
- **Purpose:** Find duplicate source questions.
- **Required fixture:** One deliberate exact duplicate across source quizzes.
- **Exact state / expansion / filters:** All types; page 1; small result groups expanded by current product default; no search.
- **Framing:** Teaching detail; anchor `.duplicate-question-summary`, 24px top margin where scroll limits permit.
- **Duration / priority:** ~10 seconds; essential.

## 030 — Compare before editing

- **File:** [030-duplicate-detail.png](captures/030-duplicate-detail.png)
- **Route:** `/library/duplicates?result_type=exact&search=risky`
- **Purpose:** Compare before editing.
- **Required fixture:** Change Readiness Checklist and Everyday Data Safety.
- **Exact state / expansion / filters:** Exact filter; search risky; one matching group expanded; page 1; no automatic deletion.
- **Framing:** Teaching detail; anchor `.duplicate-question-group`, 24px top margin where scroll limits permit.
- **Duration / priority:** ~12 seconds; essential.

## 031 — Take study material further

- **File:** [031-anki-tools.png](captures/031-anki-tools.png)
- **Route:** `/anki`
- **Purpose:** Take study material further.
- **Required fixture:** Base synthetic library.
- **Exact state / expansion / filters:** Tools overview; no external program launched.
- **Framing:** Overview; page top (dialog if specified).
- **Duration / priority:** ~10 seconds; essential.

## 032 — Choose an export deliberately

- **File:** [032-anki-selection.png](captures/032-anki-selection.png)
- **Route:** `/anki/custom`
- **Purpose:** Choose an export deliberately.
- **Required fixture:** Original sources and missed records.
- **Exact state / expansion / filters:** Filter Everyday Data Safety; expand source and select its first question; no download.
- **Framing:** Teaching detail; anchor `.anki-custom-quiz-filter`, 24px top margin where scroll limits permit.
- **Duration / priority:** ~10 seconds; essential.

**V3 print-layout decision:** Keep the physical-card mention on 032 without adding a new frame. The actual `/anki/printable` HTML is deterministic, but its paper-first white layout is intentionally independent of the selected DLMS theme. A complete Letter sheet plus the on-screen duplex guidance also exceeds the fixed 1080-pixel viewport. A capture would therefore violate the Purple & Gold standard or clip the physical layout it is meant to prove. Reserve front/back sheet visuals for a print-focused tutorial.

## 033 — An optional external workflow

- **File:** [033-external-ai.png](captures/033-external-ai.png)
- **Route:** `/external-ai/quiz-builder`
- **Purpose:** An optional external workflow.
- **Required fixture:** Base synthetic library.
- **Exact state / expansion / filters:** Provider-neutral builder; no provider opened; no claim of local AI.
- **Framing:** Overview; page top (dialog if specified).
- **Duration / priority:** ~10 seconds; optional.

## 034 — Preserve your local workspace

- **File:** [034-backup.png](captures/034-backup.png)
- **Route:** `/settings/backup`
- **Purpose:** Preserve your local workspace.
- **Required fixture:** Base synthetic library.
- **Exact state / expansion / filters:** Backup/restore overview; no restore/reset initiated.
- **Framing:** Overview; page top (dialog if specified).
- **Duration / priority:** ~12 seconds; essential.

## 035 — Your workspace, your choices

- **File:** [035-settings.png](captures/035-settings.png)
- **Route:** `/settings`
- **Purpose:** Your workspace, your choices.
- **Required fixture:** Base synthetic library.
- **Exact state / expansion / filters:** Purple & Gold; isolated demo identity; no destructive action.
- **Framing:** Overview; page top (dialog if specified).
- **Duration / priority:** ~10 seconds; optional.

## 036 — Return to the next useful step

- **File:** [036-closing-dashboard.png](captures/036-closing-dashboard.png)
- **Route:** `/`
- **Purpose:** Return to the next useful step.
- **Required fixture:** No unwanted Resume; server recommendations may remain after a review.
- **Exact state / expansion / filters:** Default controls; no search; no open dialogs.
- **Framing:** Overview; page top (dialog if specified).
- **Duration / priority:** ~10 seconds; essential.

`@critical_quiz` resolves to the fixture Network Troubleshooting source quiz; `@adaptive_quiz` resolves to the fixture Adaptive Study generated review. Full-run state includes real Study saves from earlier frames. Focused recaptures use `--replay-prefix` to reproduce them.
