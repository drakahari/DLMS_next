# Demo-video screenshot plan

Preparation manifest; no UM IDs. See [README](README.md) for fixture, privacy and capture rules.

**36 proposed frames · 402 seconds (6:42)** before transitions. Optional frames can be dropped to shorten the cut. All defaults mean no search, no tooltip, no dialog unless specified. Teaching frames scroll to the named real section; overview frames start at page top.

The machine-readable equivalent is `tools/capture_demo_video_screenshots.py --list`. Only 001, 003 and 014 have proof images; other frames await visual approval.

## 001 — A personal learning workspace

- **File:** `001-dashboard.png`
- **Route:** `/`
- **Purpose:** A personal learning workspace.
- **Required fixture:** Evidence, due questions, no browser Resume.
- **Exact state / expansion / filters:** Default controls; no search; no open dialogs.
- **Framing:** Overview; page top (dialog if specified).
- **Duration / priority:** ~10 seconds; essential.

## 002 — Choose a useful next step

- **File:** `002-todays-review.png`
- **Route:** `/`
- **Purpose:** Choose a useful next step.
- **Required fixture:** Real server-derived recommendations; no fabricated ranking.
- **Exact state / expansion / filters:** Default controls; no search; no open dialogs.
- **Framing:** Teaching detail; scroll to `.daily-review-panel`.
- **Duration / priority:** ~12 seconds; essential.

## 003 — Organize original study content

- **File:** `003-quiz-library.png`
- **Route:** `/library`
- **Purpose:** Organize original study content.
- **Required fixture:** Base synthetic library.
- **Exact state / expansion / filters:** Visible; no Smart View/search; folders expanded; Completed collapsed.
- **Framing:** Teaching detail; scroll to `#quizList`.
- **Duration / priority:** ~10 seconds; essential.

## 004 — Choose active material

- **File:** `004-learning-scope.png`
- **Route:** `/learning-scope`
- **Purpose:** Choose active material.
- **Required fixture:** One excluded saved source; no hiding or deletion.
- **Exact state / expansion / filters:** Past Projects excluded; other folders and Uncategorized included.
- **Framing:** Overview; page top (dialog if specified).
- **Duration / priority:** ~12 seconds; essential.

## 005 — Saved does not mean active

- **File:** `005-scope-library.png`
- **Route:** `/library`
- **Purpose:** Saved does not mean active.
- **Required fixture:** Base synthetic library.
- **Exact state / expansion / filters:** Past Projects visible, expanded, excluded from Learning Scope.
- **Framing:** Teaching detail; scroll to `[data-folder-label="Past Projects"]`.
- **Duration / priority:** ~10 seconds; essential.

## 006 — Bring your own content

- **File:** `006-build-quiz.png`
- **Route:** `/upload`
- **Purpose:** Bring your own content.
- **Required fixture:** Base synthetic library.
- **Exact state / expansion / filters:** Default controls; no search; no open dialogs.
- **Framing:** Overview; page top (dialog if specified).
- **Duration / priority:** ~10 seconds; essential.

## 007 — PDF and image import

- **File:** `007-pdf-import.png`
- **Route:** `/pdf-import`
- **Purpose:** PDF and image import.
- **Required fixture:** Base synthetic library.
- **Exact state / expansion / filters:** Empty form; no extraction claims.
- **Framing:** Overview; page top (dialog if specified).
- **Duration / priority:** ~10 seconds; essential.

## 008 — An original image as input

- **File:** `008-ocr-source.png`
- **Route:** `/pdf-import`
- **Purpose:** An original image as input.
- **Required fixture:** Pillow-rendered original text; no external content.
- **Exact state / expansion / filters:** Original study-skills.png selected; rights confirmed; not submitted.
- **Framing:** Teaching detail; scroll to `.pdf-ocr-import-panel`.
- **Duration / priority:** ~12 seconds; essential.

## 009 — Inspect before publishing

- **File:** `009-review-repair.png`
- **Route:** `/pdf-import/review/video_review`
- **Purpose:** Inspect before publishing.
- **Required fixture:** Original synthetic staged parser draft; not a claim of OCR accuracy.
- **Exact state / expansion / filters:** Seeded staged draft: one complete, one incomplete; nothing published.
- **Framing:** Teaching detail; scroll to `.pdf-import-summary-grid`.
- **Duration / priority:** ~12 seconds; essential.

## 010 — Missing answers remain your decision

- **File:** `010-repair-detail.png`
- **Route:** `/pdf-import/review/video_review`
- **Purpose:** Missing answers remain your decision.
- **Required fixture:** Same staged draft.
- **Exact state / expansion / filters:** Incomplete recovered question; no answer invented.
- **Framing:** Teaching detail; scroll to `.pdf-import-question-card:last-of-type`.
- **Duration / priority:** ~10 seconds; essential.

## 011 — Start a self-paced session

- **File:** `011-study-start.png`
- **Route:** `@critical_quiz` (`@critical_quiz` = newly published Network Troubleshooting; `@adaptive_quiz` = newly published Adaptive Study).
- **Purpose:** Start a self-paced session.
- **Required fixture:** Network Troubleshooting source quiz.
- **Exact state / expansion / filters:** Study Mode, question 1; no answer selected.
- **Framing:** Teaching detail; scroll to `.quiz-progress-card`.
- **Duration / priority:** ~10 seconds; essential.

## 012 — Learn from an answer

- **File:** `012-study-feedback.png`
- **Route:** `@critical_quiz` (`@critical_quiz` = newly published Network Troubleshooting; `@adaptive_quiz` = newly published Adaptive Study).
- **Purpose:** Learn from an answer.
- **Required fixture:** Original network question.
- **Exact state / expansion / filters:** Study Mode question 1, B selected; incorrect feedback visible.
- **Framing:** Teaching detail; scroll to `.quiz-progress-card`.
- **Duration / priority:** ~12 seconds; essential.

## 013 — Use optional question tools

- **File:** `013-question-tools.png`
- **Route:** `@critical_quiz` (`@critical_quiz` = newly published Network Troubleshooting; `@adaptive_quiz` = newly published Adaptive Study).
- **Purpose:** Use optional question tools.
- **Required fixture:** Same original source question.
- **Exact state / expansion / filters:** Same answered question; Review with AI, Mark for Anki, Copy Question visible; no provider opened.
- **Framing:** Teaching detail; scroll to `#questionTools`.
- **Duration / priority:** ~14 seconds; essential.

## 014 — See the learning pattern

- **File:** `014-learning-intelligence.png`
- **Route:** `/learning-intelligence`
- **Purpose:** See the learning pattern.
- **Required fixture:** Strong Data Safety; declining Networking; improving Access Control; low-evidence Cloud.
- **Exact state / expansion / filters:** All concepts, empty search; mastery explanation closed; scope summary visible.
- **Framing:** Overview; page top (dialog if specified).
- **Duration / priority:** ~14 seconds; essential.

## 015 — Compare evidence and trends

- **File:** `015-concept-trends.png`
- **Route:** `/learning-intelligence`
- **Purpose:** Compare evidence and trends.
- **Required fixture:** 18 responses per established concept, one Cloud response.
- **Exact state / expansion / filters:** All concepts, no filter; compare actual calculated values.
- **Framing:** Teaching detail; scroll to `#liTableWrap`.
- **Duration / priority:** ~14 seconds; essential.

## 016 — Explainable intelligence

- **File:** `016-mastery-model.png`
- **Route:** `/learning-intelligence`
- **Purpose:** Explainable intelligence.
- **Required fixture:** Same evidence; no invented percentages.
- **Exact state / expansion / filters:** How mastery works dialog open.
- **Framing:** Overview; page top (dialog if specified).
- **Duration / priority:** ~12 seconds; essential.

## 017 — Turn results into a next action

- **File:** `017-learning-profile.png`
- **Route:** `/learning-profile`
- **Purpose:** Turn results into a next action.
- **Required fixture:** Scoped evidence.
- **Exact state / expansion / filters:** Default controls; no search; no open dialogs.
- **Framing:** Overview; page top (dialog if specified).
- **Duration / priority:** ~10 seconds; optional.

## 018 — Review when it is due

- **File:** `018-review-schedule.png`
- **Route:** `/review-schedule`
- **Purpose:** Review when it is due.
- **Required fixture:** Recent and older source evidence; unseen Cloud questions.
- **Exact state / expansion / filters:** Queue expanded; All status; blank search; default batch size.
- **Framing:** Overview; page top (dialog if specified).
- **Duration / priority:** ~12 seconds; essential.

## 019 — Inspect the source question queue

- **File:** `019-due-queue.png`
- **Route:** `/review-schedule`
- **Purpose:** Inspect the source question queue.
- **Required fixture:** Only genuinely due source questions.
- **Exact state / expansion / filters:** Due status; queue expanded; empty search.
- **Framing:** Teaching detail; scroll to `#nrsQueuePanel`.
- **Duration / priority:** ~12 seconds; essential.

## 020 — Question timing and topic retention

- **File:** `020-topic-retention.png`
- **Route:** `/review-schedule`
- **Purpose:** Question timing and topic retention.
- **Required fixture:** Derived concept evidence.
- **Exact state / expansion / filters:** Question Queue collapsed; Topic Retention visible.
- **Framing:** Teaching detail; scroll to `.review-schedule-summary:not(.native-review-summary)`.
- **Duration / priority:** ~10 seconds; optional.

## 021 — A review built from your sources

- **File:** `021-generated-practice.png`
- **Route:** `/library`
- **Purpose:** A review built from your sources.
- **Required fixture:** Adaptive active plus a retained completed Smart Review.
- **Exact state / expansion / filters:** Visible Library; active Generated Practice group open; Completed collapsed.
- **Framing:** Teaching detail; scroll to `[data-generated-practice-group="true"]`.
- **Duration / priority:** ~12 seconds; essential.

## 022 — Keep the connection to source material

- **File:** `022-source-provenance.png`
- **Route:** `/library?view=visible&smart=generated-practice`
- **Purpose:** Keep the connection to source material.
- **Required fixture:** Question Identity v2 payloads from three real source quiz rows.
- **Exact state / expansion / filters:** Generated Practice Smart View (all review sessions); first source disclosure expanded; normal folder grouping.
- **Framing:** Teaching detail; scroll to `.library-source-provenance`.
- **Duration / priority:** ~12 seconds; essential.

## 023 — Explicitly close the review

- **File:** `023-finish-review.png`
- **Route:** `@adaptive_quiz` (`@critical_quiz` = newly published Network Troubleshooting; `@adaptive_quiz` = newly published Adaptive Study).
- **Purpose:** Explicitly close the review.
- **Required fixture:** Fresh Adaptive Study session; completion marker absent.
- **Exact state / expansion / filters:** All 3 questions answered and saved; final question; Finish Review not yet clicked.
- **Framing:** Teaching detail; scroll to `.quiz-progress-card`.
- **Duration / priority:** ~12 seconds; essential.

## 024 — Finish with acknowledged saves

- **File:** `024-review-finished.png`
- **Route:** `@adaptive_quiz` (`@critical_quiz` = newly published Network Troubleshooting; `@adaptive_quiz` = newly published Adaptive Study).
- **Purpose:** Finish with acknowledged saves.
- **Required fixture:** Real Study saves and server completion handshake.
- **Exact state / expansion / filters:** Finish Review succeeded; success status visible; checkpoint cleared.
- **Framing:** Teaching detail; scroll to `.quiz-progress-card`.
- **Duration / priority:** ~10 seconds; essential.

## 025 — Completed is retained, not deleted

- **File:** `025-completed-practice.png`
- **Route:** `/library`
- **Purpose:** Completed is retained, not deleted.
- **Required fixture:** Seeded retained Smart Review; Adaptive also completed during a full run.
- **Exact state / expansion / filters:** Completed Generated Practice expanded; quizzes playable.
- **Framing:** Teaching detail; scroll to `.library-folder-completed-practice`.
- **Duration / priority:** ~12 seconds; essential.

## 026 — Keep a record of learning

- **File:** `026-history.png`
- **Route:** `/history`
- **Purpose:** Keep a record of learning.
- **Required fixture:** 18 original synthetic Exam attempts, Demo Learner.
- **Exact state / expansion / filters:** Default controls; no search; no open dialogs.
- **Framing:** Overview; page top (dialog if specified).
- **Duration / priority:** ~10 seconds; essential.

## 027 — Look back across your history

- **File:** `027-analytics.png`
- **Route:** `/dashboard`
- **Purpose:** Look back across your history.
- **Required fixture:** Same completed attempts; all-history view.
- **Exact state / expansion / filters:** Default controls; no search; no open dialogs.
- **Framing:** Overview; page top (dialog if specified).
- **Duration / priority:** ~10 seconds; essential.

## 028 — Move content without moving personal history

- **File:** `028-bundles.png`
- **Route:** `/quiz-bundles`
- **Purpose:** Move content without moving personal history.
- **Required fixture:** Source quizzes eligible; generated sessions excluded.
- **Exact state / expansion / filters:** Export/import landing; source candidates only; no upload yet.
- **Framing:** Teaching detail; scroll to `.portable-bundle-workflows`.
- **Duration / priority:** ~12 seconds; essential.

## 029 — Find duplicate source questions

- **File:** `029-duplicates.png`
- **Route:** `/library/duplicates`
- **Purpose:** Find duplicate source questions.
- **Required fixture:** One deliberate exact duplicate across source quizzes.
- **Exact state / expansion / filters:** All types; page 1; small result groups expanded by current product default; no search.
- **Framing:** Teaching detail; scroll to `.duplicate-question-summary`.
- **Duration / priority:** ~10 seconds; essential.

## 030 — Compare before editing

- **File:** `030-duplicate-detail.png`
- **Route:** `/library/duplicates?result_type=exact&expanded=1`
- **Purpose:** Compare before editing.
- **Required fixture:** Change Readiness Checklist and Everyday Data Safety.
- **Exact state / expansion / filters:** Exact filter, first group expanded, page 1; no automatic deletion.
- **Framing:** Teaching detail; scroll to `.duplicate-question-group`.
- **Duration / priority:** ~12 seconds; essential.

## 031 — Take study material further

- **File:** `031-anki-tools.png`
- **Route:** `/anki`
- **Purpose:** Take study material further.
- **Required fixture:** Base synthetic library.
- **Exact state / expansion / filters:** Tools overview; no external program launched.
- **Framing:** Overview; page top (dialog if specified).
- **Duration / priority:** ~10 seconds; essential.

## 032 — Choose an export deliberately

- **File:** `032-anki-selection.png`
- **Route:** `/anki/custom`
- **Purpose:** Choose an export deliberately.
- **Required fixture:** Original sources and missed records.
- **Exact state / expansion / filters:** Custom deck form; no download or native dialog.
- **Framing:** Teaching detail; scroll to `.anki-tools-header`.
- **Duration / priority:** ~10 seconds; essential.

## 033 — An optional external workflow

- **File:** `033-external-ai.png`
- **Route:** `/external-ai/quiz-builder`
- **Purpose:** An optional external workflow.
- **Required fixture:** Base synthetic library.
- **Exact state / expansion / filters:** Provider-neutral builder; no provider opened; no claim of local AI.
- **Framing:** Overview; page top (dialog if specified).
- **Duration / priority:** ~10 seconds; optional.

## 034 — Preserve your local workspace

- **File:** `034-backup.png`
- **Route:** `/settings/backup`
- **Purpose:** Preserve your local workspace.
- **Required fixture:** Base synthetic library.
- **Exact state / expansion / filters:** Backup/restore overview; no restore/reset initiated.
- **Framing:** Overview; page top (dialog if specified).
- **Duration / priority:** ~12 seconds; essential.

## 035 — Your workspace, your choices

- **File:** `035-settings.png`
- **Route:** `/settings`
- **Purpose:** Your workspace, your choices.
- **Required fixture:** Base synthetic library.
- **Exact state / expansion / filters:** Purple & Gold; isolated demo identity; no destructive action.
- **Framing:** Overview; page top (dialog if specified).
- **Duration / priority:** ~10 seconds; optional.

## 036 — Return to the next useful step

- **File:** `036-closing-dashboard.png`
- **Route:** `/`
- **Purpose:** Return to the next useful step.
- **Required fixture:** No unwanted Resume; server recommendations may remain after a review.
- **Exact state / expansion / filters:** Default controls; no search; no open dialogs.
- **Framing:** Overview; page top (dialog if specified).
- **Duration / priority:** ~10 seconds; essential.
