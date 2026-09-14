# DLMS 3.2.0 authoritative feature inventory

**Audit date:** 2026-09-14

**Branch / commit:** `develop/3.2.0` / `50baed8`

**Application version:** `3.2.0` (`app.py` authoritative value)

**Purpose:** Phase 1 end-user manual architecture; not finished user guidance

This inventory describes what a DLMS user can see or do in the current source
tree. It is organized by user goal rather than by Python module. Route names,
services, templates, tests, and current Help are cited only as evidence.

## Audit method and scope

The audit cross-checked application composition and all registered Flask routes
against templates, static pages and JavaScript, user-facing service behavior,
forms/limits, tests, Help assets, release documentation, and current audit
records. The application exposes 218 registered routes including HTML pages,
JSON actions, generated quiz/media delivery, compatibility endpoints, and
maintenance APIs; routes that form one guided workflow are documented together
rather than inflated into separate “features.” A second-pass coverage matrix is
at the end of this file.

The 18 major functional areas used in this inventory are:

1. runtime, first launch, and Dashboard;
2. quiz creation and text import;
3. quiz editing and publication;
4. Quiz Library and organization;
5. composition, duplicates, and portability;
6. quiz-taking and recovery;
7. Today’s Review and targeted study;
8. scheduling;
9. Learning Intelligence and diagnostics;
10. History and Analytics;
11. PDF, Smart PDF, and saved banks;
12. OCR and Review & Repair;
13. matching, terminology, images, and hotspots;
14. external-AI-assisted workflows;
15. Study Packs, Content Packs, and subject spaces;
16. Anki and decks;
17. settings, data management, and maintenance;
18. Help, platform, and runtime differences.

## Current application and documentation state

### Product/runtime state

- DLMS 3.2.0 is a local-first, single-user application with a Flask-backed
  browser interface and native packaged releases. The normal packaged launch is
  loopback-only at `127.0.0.1:9001`; explicit non-loopback binding enables a
  trusted-LAN/server mode.
- Documented native targets are Fedora 44 x86_64, Ubuntu 24.04 x86_64, Ubuntu
  26.04 x86_64, Omarchy Quattro x86_64, Windows 11 x86_64, and macOS Apple
  Silicon arm64. User packages include the native application, `README.txt`,
  and `sample_quiz.txt`. Windows/Linux use a versioned wrapper directory;
  macOS places `DLMS.app` and both text assets directly at the ZIP root.
- Native packages bundle the local OCR runtime. Source execution can use an
  installed Tesseract 5 English-data setup; without it, selectable-text PDF
  extraction remains available while OCR-dependent paths are unavailable.
- Default data locations are `%APPDATA%\DLMS` on Windows,
  `~/Library/Application Support/DLMS` on macOS, and
  `$XDG_DATA_HOME/DLMS` or `~/.local/share/DLMS` on Linux.
- Native Windows and macOS packages are not represented as code-signed or
  notarized; current release guidance explains SmartScreen/Gatekeeper handling.
  Those platform warnings belong in installation prose, not build instructions.

**Evidence:** `app.py`; `dlms/runtime.py`; `release_assets/README.txt`;
`README.md`; `docs/OCR_PACKAGING.md`; `docs/RELEASE_VERIFICATION.md`;
`tools/package_release.py`; release-verifier tests.

**Manual home:** Chapters 1–3, 16, 18, and platform appendices.

**Screenshot:** UM-01 and UM-25.

**Status:** **Verified**, with LAN shutdown documentation conflicts recorded
below.

### Existing documentation and assets

- The root `README.md` is the product/repository front page and points ordinary
  users toward packaged releases. `release_assets/README.txt` is the compact
  package-side guide.
- The in-app Help Center is the most complete existing user guide. Its topic
  families are Getting Started, Quizzes, Build Quiz, External AI, PDF & Image
  Import, Study Packs, Study Modules, Content Management, History & Analytics,
  Learning Intelligence, Anki, Settings, Maintenance, and Troubleshooting.
  About, Quiz Help, Advanced Features, and Regex Help are additional pages.
- `static/help_assets/` contains 47 screenshots covering many 3.1-era and some
  current workflows. They are candidates, not automatically approved manual
  assets. The repository also has older `docs/screenshots/` images.
- `docs/OCR_PACKAGING.md`, `docs/RELEASE_VERIFICATION.md`, CI/security material,
  and `docs/audits/` are maintainer sources. Their user-visible consequences may
  be summarized, but native build/probe/verification procedures should not be
  copied into the end-user manual.
- No canonical Markdown end-user manual existed before this directory.

**Evidence:** `dlms/routes/help.py`; `static/help-*.html`;
`static/help_assets/`; `docs/`; `README.md`; `release_assets/README.txt`.

**Manual home:** This architecture, then all Phase 2 chapters.

**Screenshot:** Existing candidates are evaluated in `SCREENSHOT_PLAN.md`.

**Status:** **Verified; existing docs incomplete** for several 3.2 workflows.

## Detailed functional inventory

### 1. Runtime, first launch, and Dashboard

#### First launch and local desktop experience

| Inventory field | Verified behavior |
| --- | --- |
| Screen / reach | Launch the native application (or source runtime), then use the locally opened browser page. |
| What and why | Starts a private, single-user DLMS instance and presents the Dashboard without requiring a cloud account. |
| Primary behavior | A packaged launch normally opens the browser; `--browser` and `--no-browser` explicitly control launch. Headless/SSH detection affects opening a browser, not the bind address. |
| Inputs / output | No first-run account. DLMS creates/uses its writable application-data directory and serves the local UI. |
| Warnings / dependencies | The browser UI does not make DLMS a cloud service. Explicit `--host 0.0.0.0` is LAN/server mode and has a different security/shutdown contract. |
| State boundary | Application content is server-side local data; some UI preferences and interrupted-quiz checkpoints are browser-local. |
| Evidence | `app.py`; `dlms/runtime.py`; `templates/dashboard/index.html`; runtime/release tests. |
| Manual / screenshot / status | Ch. 1–3 and platform appendix; UM-01; **Verified**. |

#### Dashboard and Today’s Review summary

| Inventory field | Verified behavior |
| --- | --- |
| Screen / reach | Dashboard, the primary home route. |
| What and why | Provides the recommended “what should I study now?” plan plus Quick Access, Recent Activity, and overview metrics. |
| Controls / destinations | Recommendation cards launch Due Questions, Concept Review, Adaptive Study, resume the local quiz, or return to relevant Study Pack activity. Quick Access leads to core authoring/study areas. |
| State-dependent behavior | Server recommendations are ordered and capped; browser-local recovery records are merged on the client and marked `This browser`. Empty/low-history states lead to useful starting actions. |
| Persistence | Due/concept/adaptive/pack signals are derived from server data. Resume cards come from this browser’s storage and may differ across clients using one server. |
| Evidence | `dlms/services/daily_review.py`; `templates/dashboard/index.html`; `static/daily-review.js`; `tests/test_daily_review_plan.py`; Dashboard Firefox tests. |
| Manual / screenshot / status | Ch. 3 and 7; UM-01; **Verified**. |

### 2. Quiz creation and text import

#### Build Quiz hub

| Inventory field | Verified behavior |
| --- | --- |
| Screen / reach | Build Quiz from primary navigation/Dashboard. |
| What and why | Chooses among manual short quiz, text-file import, pasted text cleanup/parsing, PDF & Image Import, matching CSV, image-based content, and External AI workflows. |
| Controls / output | Each tile opens its own validated workflow; successful publication creates a normal playable quiz and Library entry. |
| Evidence | `dlms/routes/quiz/authoring.py`; authoring templates; `static/help-build-quiz.html`; authoring tests. |
| Manual / screenshot / status | Ch. 4; UM-02; **Verified**. |

#### Manual short quiz builder

| Inventory field | Verified behavior |
| --- | --- |
| Screen / reach | Build Quiz → manual/short builder. |
| What and why | Creates a quiz directly without preparing an import file. |
| Inputs | Title, optional logo, Exam Mode minutes, initial 1–100 question rows; choice/multi-answer questions or matching questions. Choice rows can be added/removed and every correct answer is checked. Matching requires pair rows, direction, and optional round size. |
| Review / output | Client editing is revalidated server-side, then published through shared quiz publication/rendering. The resulting quiz can be edited further. |
| Choice contract | Choice questions normally start with four A–D rows. The supported builder UI allows 1–26 nonblank choices, requires at least one nonblank choice and one marked correct choice, and ignores blank unused rows. One marked correct answer produces single-answer behavior; multiple marked correct answers automatically produce multi-select behavior. There is no separate answer-mode selector. Four rows is the initial default, not an invariant for a newly cloned question block. |
| Limits / validation | Timer is 1–1440 minutes (90 default). Matching requires at least two pairs. The browser prevents deleting the final choice row or adding beyond Z. The server rejects a choice question with no nonblank choice or no correct nonblank choice. The browser’s 26-choice maximum is not independently enforced by the current POST route; this is an implementation observation, not supported behavior beyond 26. |
| Evidence | `templates/quiz/short-builder.html`; `dlms/routes/quiz/authoring.py`; publication and template tests. |
| Manual / screenshot / status | Ch. 4 and 11; no separate screenshot beyond UM-02; **Verified**. Use the 1–26 user-facing contract above and do not describe crafted requests beyond that range as supported. |

#### Text-file import

| Inventory field | Verified behavior |
| --- | --- |
| Screen / reach | Build Quiz → upload text file. |
| What and why | Parses a structured `.txt` question set into a quiz. |
| Inputs | UTF-8 text up to 16 MiB, title, optional raster logo, optional timer. Correctness uses supported explicit answer-marker syntax. |
| Failure / review | Validation and parse failures return actionable pages without silently publishing malformed content. Users can return to Build Quiz or choose a different input path. |
| Evidence | `templates/quiz/upload.html`; `dlms/routes/quiz/authoring.py`; `dlms/parsing/quiz_text.py`; parser/authoring tests. |
| Manual / screenshot / status | Ch. 4 and format reference; no dedicated screenshot; **Verified**. |

#### Paste, clean, and parse text

| Inventory field | Verified behavior |
| --- | --- |
| Screen / reach | Build Quiz → paste text. |
| What and why | Cleans copied question text, previews transformations, and parses it without requiring a file. |
| Controls / options | Optional removal strings; numbered-prefix, PDF-wrapping, and header-cleanup presets; optional manual regular expressions; BOM/invisible-character cleanup; Smart Suggestions; optional confidence analysis; original/cleaned/diff/invisible previews; download cleaned text. |
| Validation | Supported explicit answer markers include `Suggested Answer:` and `Correct Answer:`. A bare `Answer:` is deliberately not treated as correctness evidence. Settings can disable advanced parsing tools. |
| Output / failure | Valid preview proceeds to shared publication. Parse-failure and confidence results preserve context for revision rather than inventing answers. |
| Evidence | `templates/quiz/paste.html`; `paste-preview.html`; `parse-failed.html`; parsing settings; `dlms/parsing/quiz_text.py`; parser tests. |
| Manual / screenshot / status | Ch. 4 and 18; focused crop optional; **Verified**. |

#### Matching CSV import

| Inventory field | Verified behavior |
| --- | --- |
| Screen / reach | Build Quiz → matching/terminology CSV import. |
| What and why | Creates a matching quiz from a simple table of pairs. |
| Inputs | UTF-8 CSV up to 16 MiB; headers `term` + `definition` or `left` + `right`/`match`; title, direction, round size, optional source organization/dataset/version/URL/license. |
| Validation / output | At least two valid unique, non-conflicting pairs are required. The staged result is editable before normal publication. Round size is bounded 2–100. |
| Evidence | `templates/quiz/matching-bank-import.html`; quiz authoring routes; matching-import tests. |
| Manual / screenshot / status | Ch. 4 and 11; no dedicated screenshot; **Verified**. |

### 3. Quiz editing, publication, and export

#### Quiz editor

| Inventory field | Verified behavior |
| --- | --- |
| Screen / reach | Quiz Library → Edit, or source links from management/review screens. |
| What and why | Updates a saved quiz’s title, timer, logo, questions, concepts, answers/pairs, explanations, and question order. |
| Controls | Add/delete/reorder questions; edit choice and multi-answer correctness; edit matching pairs/direction/round size; edit source/explanation metadata supported by the stored question; delete the quiz through its confirmed action. |
| Integrity | Shared mutation/publication helpers rebuild derived HTML and playable JSON. Question/quiz identity and explicit generated lineage are preserved according to Question Identity v2; a failed artifact update preserves the previous usable state. |
| Warnings | Editing content may make a browser-local recovery checkpoint incompatible. Deleting a source quiz does not imply cascading deletion of unrelated history; exact behavior should be stated only where the UI confirms it. |
| Evidence | `templates/quiz/edit.html`; `dlms/routes/quiz/editor.py`; `dlms/services/quiz_mutations.py`; `quiz_publication.py`; identity/publication tests. |
| Manual / screenshot / status | Ch. 4–6; focused screenshot optional; **Verified**, with deletion/history wording to keep conservative. |

#### Canonical publication and generated quiz pages

| Inventory field | Verified behavior |
| --- | --- |
| Screen / reach | Underlies every builder, import, bank, pack, and generated-review publication. Users see a playable quiz and Library entry. |
| What and why | Persists canonical quiz/question data and creates derived playable HTML/JSON/assets using one publication/rendering path. |
| Integrity / failure | Publication validates first and uses atomic/reconciled artifact handling so incomplete writes do not silently become canonical success. IDs, lineage, provenance, and source ownership are recorded where supported. |
| Evidence | `dlms/services/quiz_publication.py`; `dlms/rendering/quiz_artifacts.py`; publication/reconciliation tests. |
| Manual / screenshot / status | Explain outcomes throughout; technical details belong only in maintenance/troubleshooting; **Verified**. |

#### Text export

| Inventory field | Verified behavior |
| --- | --- |
| Screen / reach | Quiz Library quiz actions and all-quiz export actions. |
| What and why | Downloads one or all quizzes in a human-readable text form for inspection/portability. |
| Boundary | This is not the versioned Portable Quiz Bundle and may not preserve all rich metadata/media. |
| Evidence | Quiz library/core export routes; export tests; current Help. |
| Manual / screenshot / status | Ch. 15 and format reference; no screenshot; **Verified**. |

### 4. Quiz Library and organization

#### Library visibility, search, folders, and ordering

| Inventory field | Verified behavior |
| --- | --- |
| Screen / reach | Primary navigation → Quiz Library. |
| What and why | Opens, edits, exports, hides, moves, orders, and deletes saved quizzes while preserving user-defined organization. |
| Controls | Visible/hidden/all scope; text search; open/edit/export/hide/delete; create/rename/delete/hide/reorder folders; move and reorder quizzes. Library Tools exposes composition, duplicates, bundles, and building. |
| State-dependent behavior | Hidden folders/quizzes are separated from normal display; search and scope can expose matching hidden content. Empty folders and empty searches have specific states. |
| Integrity | Folder and order changes affect organization, not quiz content, identity, or history. |
| Evidence | `templates/quiz/library.html`; `dlms/routes/quiz/library.py`; registry/folder services; library/folder/browser tests. |
| Manual / screenshot / status | Ch. 5; UM-03; **Verified**. |

#### Built-in Smart Views

| Inventory field | Verified behavior |
| --- | --- |
| Screen / reach | Compact Smart Views area in Quiz Library. |
| What and why | Applies dynamic filters without creating/moving folders: Needs Review, Recently Added, Low Score, Unfinished, OCR Imported, Generated Practice. |
| Exact criteria | Needs Review: at least one canonical source question due/overdue. Recently Added: reliable creation/import time within 30 days. Low Score: latest completed attempt below 75%. Unfinished: valid recovery in this browser. OCR Imported: explicit local OCR provenance. Generated Practice: Adaptive, Smart, Concept, Due Questions, or Topic Retention generated kinds. |
| Interactions | Search narrows the active view; a clear/full-library action resets it. A quiz may qualify for multiple views. Ordering remains deterministic. |
| Important distinction | Mixed Quiz is intentionally excluded from Generated Practice and remains visibly distinct as a curated composition. Unfinished differs by browser/device. |
| Evidence | `dlms/services/quiz_smart_views.py`; `templates/quiz/library.html`; library JS; Smart View unit/Firefox tests. |
| Manual / screenshot / status | Ch. 5; UM-03; **Verified**. |

### 5. Composition, duplicates, and portable bundles

#### Mixed Quiz Builder

| Inventory field | Verified behavior |
| --- | --- |
| Screen / reach | Quiz Library → Library Tools → Mix Questions. |
| What and why | Previews and selects questions from multiple source quizzes to create one non-destructive curated quiz. |
| Filters / inputs | Folder, source quiz, concept, missed status, text search; at least two source quizzes and at least two selected questions; title up to 200 characters. Previews source, question, choices/pairs, and concepts. |
| Identity / output | Exact-equivalent source candidates are collapsed once, with useful provenance/concepts retained. The output is a normal generated `Mixed Quiz` with explicit source lineage; source quizzes are unchanged. Generated review copies do not recursively become preferred sources. |
| Evidence | `templates/quiz/mixed-builder.html`; `dlms/services/quiz_composition.py`; quiz composition routes/tests/browser workflow. |
| Manual / screenshot / status | Ch. 5; UM-04; **Verified**. |

#### Duplicate Question Review

| Inventory field | Verified behavior |
| --- | --- |
| Screen / reach | Quiz Library → Library Tools → Find Duplicates. |
| What and why | Advises about exact and high-confidence possible duplicates across or within source quizzes without deleting, merging, or rewriting. |
| Result detail | Shows question type/text, answers or matching pairs, source quiz/folder/question context, and an Edit source link. Exact and possible groups are clearly distinguished. |
| Matching rules | Exact comparison uses compatible type, normalized wording, and complete response structure. Near comparison is conservative: compatible response fingerprint, sufficient wording, very high sequence/token similarity, close length, equal negation/numeric tokens, and shared significant words. |
| Exclusions / identity | Generated review/composition copies are excluded. Duplicate equivalence is not treated as canonical learning lineage; independently authored identical questions remain independent sources. |
| Evidence | `templates/quiz/duplicates.html`; `dlms/services/quiz_duplicates.py`; duplicate tests/browser workflow. |
| Manual / screenshot / status | Ch. 5; UM-05; **Verified**. |

#### Portable Quiz Bundle export/import

| Inventory field | Verified behavior |
| --- | --- |
| Screen / reach | Quiz Library → Library Tools → Quiz Bundles. |
| What and why | Exports one or more ordinary quizzes to a portable, inspectable, validated ZIP and imports it into another DLMS installation. |
| Preserved | Titles, choice/matching content, concepts, supported metadata/folder placement, source/provenance that is portable, and required safe quiz media. Source exports are non-mutating. |
| Excluded | Attempts, scores, learning events, schedules/adaptive state, personal history, and Generated Practice/Mixed or other non-exportable generated quizzes. Installation-local IDs are not portability dependencies. |
| Review / collision | Import validates and stages a preview before confirmation. Existing quiz names are not overwritten or merged; collisions are renamed deterministically and explained. New local identities are created on publication. |
| Safety / limits | Versioned manifest `dlms-quiz-bundle.json` format v1; strict allowed structure, paths, hashes/types; traversal/symlink/unexpected-file protection; uploaded 128 MiB, expanded 256 MiB, 512 files, 100 quizzes, 2,000 questions/quiz, 10,000 total, 1,000 matching pairs, 100 assets/quiz, 32 MiB per file, compression ratio 200. Failed import rolls back completed bundle publications where practical and reports that nothing was kept. |
| Evidence | `templates/quiz/bundles.html`; `bundle-review.html`; `dlms/routes/quiz/bundles.py`; bundle service/validation/tests/browser workflow. |
| Manual / screenshot / status | Ch. 5 and 15; UM-06; **Verified**. |

### 6. Quiz-taking, results, and browser recovery

#### Mode selection and supported question interactions

| Inventory field | Verified behavior |
| --- | --- |
| Screen / reach | Open a playable quiz from the Dashboard, Library, pack/bank generation, or a review action; choose Study Mode or Exam Mode. |
| What and why | Runs single-answer, multi-answer, matching, image-supported, and hotspot questions through the shared quiz runtime. |
| Controls | Choice inputs and keyboard controls; matching by drag/drop or accessible select controls; previous/next navigation; hotspot pointer selection or focus + arrow keys + Enter/Space. Choice order and matching presentation can be shuffled according to saved configuration. |
| Media / output | Quiz-owned or validated pack images appear with supported question content. Answers feed the relevant mode’s result/history/learning behavior. |
| Evidence | `dlms/rendering/quiz_artifacts.py`; `static/script.js`; generated quiz templates; quiz runtime, matching, hotspot, and browser tests. |
| Manual / screenshot / status | Ch. 6 and keyboard appendix; UM-07–UM-09/UM-19; **Verified**. |

#### Study Mode

| Inventory field | Verified behavior |
| --- | --- |
| What and why | Provides immediate learning feedback rather than a single final scored submission. |
| Controls / results | Complete an answer, see correctness and the supported correct response, read explanation/source detail, navigate onward, and optionally mark supported questions for Anki export or use configured external-AI explanation help. |
| Persistence / failure | Each completed answer is saved as learning evidence. A lost/failed save is visibly retryable and remains recoverable; DLMS does not clear the checkpoint until every question is complete and every required save is acknowledged. |
| Correctness safety | A multi-answer response is complete only under the saved question’s correctness rules. Matching/hotspot interactions keep their type-specific scoring. |
| Evidence | `static/script.js`; `dlms/services/learning.py`; learning-event endpoints/tests; Study Mode Firefox tests. |
| Manual / screenshot / status | Ch. 6; UM-07; **Verified**. |

#### Exam Mode and results

| Inventory field | Verified behavior |
| --- | --- |
| What and why | Runs a timed test-like attempt and records one completed result. |
| Controls | Timer (quiz default usually 90 minutes), pause/resume, previous/next, answer status, submit confirmation; timeout can submit automatically. |
| Results / next steps | Score/result review, missed answers, History, retake, and Dashboard links. The attempt is persisted before recovery is cleared. |
| Failure behavior | If final persistence is not acknowledged, the exact pending attempt remains recoverable for an explicit retry rather than being silently duplicated or lost. |
| Evidence | `static/script.js`; attempt/history services and routes; `static/review.html`; attempt/recovery/browser tests. |
| Manual / screenshot / status | Ch. 6 and 9; UM-08 and UM-14; **Verified**. |

#### Interrupted-quiz recovery and Start Over

| Inventory field | Verified behavior |
| --- | --- |
| Screen / reach | Recovery prompt on opening a quiz; Resume cards in Today’s Review; Unfinished Smart View. |
| What and why | Restores an interrupted Study or Exam session from this browser without treating it as durable cross-device history. |
| State and limits | Records live in browser local storage, expire after 30 days, and are bounded to roughly 512 KiB each. A quiz fingerprint rejects incompatible content. Starting over clears that browser checkpoint after confirmation/action. |
| Completion contract | Being on question N of N is not completion. Study recovery clears only after all final answers are complete and saved; Exam recovery clears only after the final attempt is persisted. Save failure leaves recovery active. |
| Cross-client behavior | Two clients of one server can legitimately show different unfinished quizzes. One client’s recovery is never a global recommendation; server-derived due/intelligence/history updates are shared after refresh. |
| Evidence | `static/quiz-recovery.js`; `static/daily-review.js`; quiz runtime; recovery tests including multi-profile Firefox coverage. |
| Manual / screenshot / status | Ch. 6–7 and 18; UM-09/UM-01; **Verified**. |

### 7. Today’s Review and targeted study

#### Today’s Review composition

| Inventory field | Verified behavior |
| --- | --- |
| Screen / reach | Dashboard → Today’s Review. |
| What and why | Gives one concise, deterministic daily action plan by reusing established review/intelligence services. |
| Priority / deduplication | Due/overdue question action first; weak/developing concept next; Adaptive Study only when specific due/concept work is absent; recent Study Pack activity later. Server plan is capped at four. Current-browser recoveries are merged, capped at two, and equivalent unfinished generated practice can replace the matching action on that client. |
| Explanation | Every card states why it is present and leads to an existing workflow rather than duplicating generation logic. Completed generated sessions cannot remain as stale Resume items. |
| Limited history | When recommendation sources lack evidence, the panel remains useful through available actions/empty guidance rather than claiming personalized precision. |
| Evidence | `dlms/services/daily_review.py`; Dashboard template; `static/daily-review.js`; daily-plan/recovery/browser tests. |
| Manual / screenshot / status | Ch. 7; UM-01 and UM-10; **Verified**. |

#### Adaptive Study (“Study What I Need Most”)

| Inventory field | Verified behavior |
| --- | --- |
| Screen / reach | Today’s Review and Learning Intelligence actions. |
| What and why | Builds a normal generated study quiz when the user wants DLMS to choose a balanced cross-library focus. |
| Inputs / options | Session sizes 10, 20, 30, or 50 where offered. Eligible material is canonical source content, not recursively selected generated copies. |
| Selection explanation | Deterministic ranking favors weak concepts, developing concepts, due/older material, recent misses, low recent accuracy where supported by enough evidence, and unseen/underexposed material; exposure penalties and diversity avoid repeatedly selecting the same content. The UI explains selection reasons without presenting false statistical precision. |
| Fallback | With partial or no history, selection falls back to a balanced deterministic source set and safely handles questions without concept metadata. |
| Output / persistence | Creates a normal playable generated session with explicit source lineage and `Adaptive Study` presentation; resulting answers contribute evidence to source questions. |
| Evidence | learning/adaptive services; Learning Intelligence routes/static pages; adaptive tests; identity tests. |
| Manual / screenshot / status | Ch. 7; UM-10; **Verified**. |

#### Smart Review

| Inventory field | Verified behavior |
| --- | --- |
| Screen / reach | Learning Intelligence review controls. |
| What and why | Generates practice across source questions belonging to concepts currently classified as weak. |
| Options / output | Sizes 10, 20, 30, or 50; selection balances available concepts/sources and records generated lineage. |
| Distinction | Broader than reviewing one selected concept; narrower and less general than Adaptive Study. It is unavailable/empty when weak-concept evidence does not support it. |
| Evidence | Learning Intelligence routes/services/static pages; Smart Review and identity tests. |
| Manual / screenshot / status | Ch. 7; UM-10; **Verified**. |

#### Concept Review

| Inventory field | Verified behavior |
| --- | --- |
| Screen / reach | Practice action beside a concept in Learning Intelligence or a weak-concept Today’s Review card. |
| What and why | Creates focused practice for one canonical concept across relevant source quizzes. |
| Output | Selects up to 20 applicable source questions, preserves provenance/lineage, and creates a normal generated quiz. |
| Limits | Requires questions with matching concept metadata; a concept metric does not imply unlimited unique practice. |
| Evidence | concept intelligence/review services and routes; Learning Intelligence template/tests. |
| Manual / screenshot / status | Ch. 7–8; UM-10/UM-12; **Verified**. |

#### Missed-question review

| Inventory field | Verified behavior |
| --- | --- |
| Screen / reach | Completed result/History, missed-question actions, and Anki Tools. |
| What and why | Revisits or exports actual questions the learner answered incorrectly. |
| Options | Depending on surface, select missed items, review a quiz’s misses, filter by number/status, export to Anki, or request an explanation using the configured external AI helper. |
| Distinction | Starts from recorded misses, unlike Smart Review’s concept classification or Due Questions’ schedule. |
| Evidence | history/Anki routes and services; result pages; missed-question and browser tests. |
| Manual / screenshot / status | Ch. 7, 9, and 14; UM-14/UM-24; **Verified**. |

### 8. Native question and topic scheduling

#### Due Questions

| Inventory field | Verified behavior |
| --- | --- |
| Screen / reach | Dashboard Today’s Review or Review Schedule → Start Due Review. |
| What and why | Reviews individual source questions whose deterministic native schedule is due or overdue. |
| Scheduling states | Due, overdue, upcoming, and not yet scheduled. Unseen questions are not scheduled. Consecutive successful reviews advance nominal intervals 1, 3, 7, 14, then 30 days; an incorrect result resets to 1 day. |
| Batch behavior | Review Schedule offers 10/20/30/50. Today’s Review uses a default batch cap of 20 and displays the total due separately from “Next review: up to 20” when more remain. After completion, the server recalculates and offers a new batch for any remaining due sources, not Resume for the completed quiz. |
| Identity / correctness | Generated-copy activity resolves to canonical source questions. Scheduling uses explicit saved correctness/history; it does not infer correctness from OCR/layout. |
| Evidence | native scheduling service/routes; Review Schedule; Today’s Review service/template; scheduler, identity, recovery, and browser tests. |
| Manual / screenshot / status | Ch. 7; UM-11; **Verified**. |

#### Topic Retention Schedule

| Inventory field | Verified behavior |
| --- | --- |
| Screen / reach | Review Schedule/Learning Intelligence. |
| What and why | Schedules concept-level reinforcement separately from question-level Due Questions. |
| Rules / options | Requires at least three evidence records. Current mastery bands schedule approximately 1 day below 60, 3 days at 60–74, 7 days at 75–89, and 14 days at 90+. Filters include due, due plus two days, or all; generated session sizes are 10/20/30/50. |
| Display | Shows due/upcoming concept timing and retained/decayed mastery. Decay begins only after due and is bounded; it does not rewrite actual answer history. |
| Evidence | learning/retention services; `static/review-schedule.html`; review-schedule tests/browser workflow. |
| Manual / screenshot / status | Ch. 7–8; UM-11; **Verified**. |

### 9. Learning Intelligence and diagnostics

#### Learning Profile

| Inventory field | Verified behavior |
| --- | --- |
| Screen / reach | Learning Intelligence navigation → Learning Profile. |
| What and why | Summarizes accuracy/mastery, weak/strong areas, quizzes studied, recent activity, retention, and a next useful action. |
| State behavior | Uses available canonical history and avoids treating missing evidence as mastery. Links into relevant review/intelligence surfaces. |
| Evidence | learning routes/services; `static/learning-profile.html`; learning-profile tests. |
| Manual / screenshot / status | Ch. 8; optional focused crop; **Verified**. |

#### Cross-quiz concept intelligence, Mastery, and Trend

| Inventory field | Verified behavior |
| --- | --- |
| Screen / reach | Learning Intelligence → Topics/concept table and mastery explanation dialog. |
| What and why | Aggregates concepts across source quizzes to show source-question/quiz counts, evidence, correct/incorrect totals, overall and recent accuracy, Mastery, status, Trend, and targeted Practice. |
| Canonical concept behavior | Concept names match case-insensitively under normalized identity while preserving a display-friendly name. Missing concept metadata is safe and excluded from concept aggregation. Recent accuracy uses the latest five applicable observations. |
| Mastery | Score combines 55% overall accuracy, 20% recent accuracy, 15% evidence, and 10% recency. Evidence reaches full credit at 8 responses. Recency credit is 100 within 7 days, 90 through 30, 75 through 90, 60 through 180, then 45. Fewer than 3 responses is `Not enough data` and caps mastery at 59; 3–4 responses cap at 74. Weak requires at least 3 responses and mastery or overall accuracy below 60; Developing is below 75, Proficient below 90, and Strong at least 90. |
| Trend | Requires at least six applicable observations. It compares two adjacent windows of 3–5; a difference of at least 15 percentage points is Improving or Declining, otherwise Stable. Less evidence is insufficient. Trend measures direction and can differ from Mastery. |
| Generated practice | Explicit question lineage attributes generated-session evidence to the canonical source rather than creating a second independent learner record. Legacy items use conservative compatibility fallback. |
| Evidence | `dlms/services/learning.py` and extracted learning services; Learning Intelligence routes; `static/learning-intelligence.html`; concept/mastery/identity tests. |
| Manual / screenshot / status | Ch. 8 and reference appendix; UM-12; **Verified**. |

#### Learning Diagnostics and question-quality signals

| Inventory field | Verified behavior |
| --- | --- |
| Screen / reach | Learning Intelligence → diagnostics/confusions/question review. |
| What and why | Surfaces repeated wrong-choice confusions and questions whose response patterns merit user review. Results are advisory, not automatic quiz mutations. |
| Controls / limits | Filters and search narrow findings; evidence/context lets the user decide what to study or edit. Matching/hotspot types are not forced into a misleading choice-confusion model. |
| Evidence | learning/question-review services; `static/learning-diagnostics.html`; `static/question-review.js`; diagnostics tests. |
| Manual / screenshot / status | Ch. 8; UM-13; **Verified**. |

### 10. History, results, and Analytics

#### History and attempt review

| Inventory field | Verified behavior |
| --- | --- |
| Screen / reach | Primary navigation → History; links from quiz results and Dashboard recent activity. |
| What and why | Lists durable completed attempts, opens a result for question-level review, and supports missed-question follow-up. |
| Controls | Pagination and supported domain/source filters; open an attempt's missed-question review; inspect the saved expected/submitted context for misses; export supported selected missed questions or use explanation actions where offered. Exam results separately offer Retake Exam. |
| State boundary | History is stored with DLMS server data and is shared across browsers of the same instance after refresh. It is distinct from an unfinished browser checkpoint. |
| Evidence | `dlms/routes/history.py`; `dlms/services/history.py`; `static/history.html`; `static/review.html`; history tests/browser workflow. |
| Manual / screenshot / status | Ch. 9; UM-14; **Verified**. |

#### Analytics

| Inventory field | Verified behavior |
| --- | --- |
| Screen / reach | History/Analytics links. |
| What and why | Summarizes total attempts, average/best/latest performance, per-quiz results, pass information where configured, and trends over recorded attempts. |
| Distinction | Attempt Analytics is not the same as concept-level Learning Intelligence or native scheduling. |
| Evidence | history/analytics routes and static pages; analytics tests; `static/help-history-analytics.html`. |
| Manual / screenshot / status | Ch. 9; UM-14; **Verified**. |

### 11. PDF, Smart PDF, and saved banks

#### PDF & Image Import entry and selectable-text extraction

| Inventory field | Verified behavior |
| --- | --- |
| Screen / reach | Build Quiz → PDF & Image Import. |
| What and why | Extracts supported question banks or terminology/glossaries from PDFs and routes screenshots/scans into local OCR-assisted workflows. |
| Inputs / controls | PDF, images, or workflow-specific source selection; target type Auto-detect, Question Bank, or Glossary/Terminology where applicable; title/timer; source-rights confirmation. PDF is bounded to 64 MiB and 2,000 pages, with per-page/total extraction limits. |
| Behavior | Selectable text is authoritative. The parser uses document structure and layout signals, not filename/content-specific literals. Unsupported or uncertain material is staged for review rather than silently fabricated. |
| Dependency | Selectable-text extraction works without Tesseract. Native packages include required PDF/OCR resources; source mode may require optional local components for raster OCR. |
| Evidence | `dlms/routes/pdf_import.py`; `dlms/parsing/smart_pdf.py`; PDF import templates; PDF parser/import tests. |
| Manual / screenshot / status | Ch. 10; UM-15; **Verified**. |

#### Smart PDF question-bank recognition

| Inventory field | Verified behavior |
| --- | --- |
| What and why | Recognizes structured numbered question blocks, choices, explanations/correctness when explicit, page continuations, and no-answer banks suitable for later completion. |
| Supported structure | Exact `Question #N` and a narrow repeated extended heading form with global/topic-local numbering; ordered A–Z choices (2–26); multiline/code choice bodies; explicit multi-answer wording can set mode but never select the correct choices. |
| Conservative cases | No-answer banks remain review/incomplete; fill-in source records preserve text/numbering and remain unsupported/incomplete for the choice model; near-miss headings are rejected; trailing end matter is retained as unassigned diagnostics instead of appended to the last stem. |
| Boundaries | Cross-page choice continuations stay with the known question. Separately numbered semantically similar questions remain separate. Correctness is accepted only from explicit evidence. |
| Evidence | `dlms/parsing/smart_pdf.py`; PDF question parser/review tests; PDF & Image Import Help. |
| Manual / screenshot / status | Ch. 10 and reference; UM-16; **Verified**. |

#### Question Bank and Terminology Bank practice

| Inventory field | Verified behavior |
| --- | --- |
| Screen / reach | Save a reviewed PDF/question or glossary import, then open its bank page. |
| What and why | Keeps the full reviewed source bank and creates reusable practice without consuming/deleting source records. |
| Controls | Question Bank: random, unused, sequential, range, or all active questions; count/timer. Terminology Bank: same selection strategies, Matching or Multiple Choice practice, and direction where supported. Used/generated counts help plan reuse. |
| Persistence | Banks are persistent sources; each generated practice quiz is separate. Deleting a bank does not silently remove already generated quizzes. |
| Evidence | PDF bank routes/services/templates; bank persistence/generation tests; `static/help-smart-pdf.html`. |
| Manual / screenshot / status | Ch. 10–11; existing bank Help assets are candidates; **Verified**. |

### 12. OCR and Review & Repair

#### Low-text/scanned PDF OCR and targeted mixed-raster augmentation

| Inventory field | Verified behavior |
| --- | --- |
| What and why | Offers local OCR when selected PDF pages contain too little usable selectable text, and augments a known selectable-text question when substantive raster-only content occupies its bounded region. |
| User control | Low-text PDF flow offers up to 25 candidate pages for selection and lets the user OCR selected pages, continue without OCR, or cancel. One page failure does not discard successful pages. |
| Targeted behavior | Selectable text remains authoritative; only structurally relevant raster regions inside known question boundaries are OCRed. Decorative/shared images are ignored; OCR does not reparse the whole page, create a duplicate question, absorb neighboring questions, or consume trailing matter. |
| Correctness | Layout, selection appearance, color, or check glyphs do not prove a correct answer. Missing/noncontiguous/ambiguous labels remain defects for Review & Repair; no labels are silently invented or renumbered. |
| Evidence | PDF/OCR services and routes; targeted raster, OCR packaging, and PDF Review tests. |
| Manual / screenshot / status | Ch. 10; UM-17; **Verified**, with platform-specific source-runtime setup to explain. |

#### Screenshot question OCR

| Inventory field | Verified behavior |
| --- | --- |
| Screen / reach | PDF & Image Import → screenshot/image question workflow. |
| What and why | OCRs one or multiple screenshots locally, extracts conservative question/choice candidates, and stages them for repair/publication. |
| Inputs / limits | Up to 25 PNG/JPG/JPEG/WebP images, 16 MiB each and 64 MiB total; maximum 40 million pixels and 12,000 pixels on either side. Files are processed in deterministic submitted order. |
| Recovery / temporary data | Individual OCR failures do not discard other successes. Exact duplicates are retained for the user to decide. Original temporary uploads/previews are removed after save/cancel/expiry according to staging behavior. |
| Interpretation | Standalone A–Z labels and multiline/code bodies are supported conservatively (2–26 choices). Visual selected/highlighted appearance is not correctness. Users must review and explicitly confirm. |
| Evidence | screenshot OCR services/routes/templates; `tests/test_ocr_screenshot_import.py`; OCR inference/browser tests. |
| Manual / screenshot / status | Ch. 10; UM-17; **Verified**. |

#### Shared question/glossary Review & Repair

| Inventory field | Verified behavior |
| --- | --- |
| Screen / reach | Follows Smart PDF/OCR detection and opens the staged question or glossary review. |
| What and why | Converts untrusted/uncertain extraction into deliberate, validated user content. |
| Question controls | Complete/review/incomplete filters; edit stem, choices, single/multiple mode, correct choices, explanation, concepts; add/remove/reorder; include/exclude; bulk visible-record controls; explicit final correctness confirmation. |
| Terminology controls | Edit term/definition, include/exclude, bulk visible controls, and preserve recoverable source text for manual reconstruction. |
| Diagnostics / output | Unassigned text and unsupported fill-in records remain visible for diagnosis but are not silently published. Save rejects incomplete correctness/pairs and creates the persistent source bank only after validation. |
| Evidence | PDF review templates and inline workflow JavaScript; PDF routes/services; PDF review contract/import tests. |
| Manual / screenshot / status | Ch. 10–11; UM-16; **Verified**. |

#### OCR-assisted terminology/matching

| Inventory field | Verified behavior |
| --- | --- |
| Screen / reach | PDF & Image Import → OCR matching/terminology. |
| What and why | Converts screenshots/images or a scanned PDF containing clear term-definition material into canonical matching content. |
| Inputs | Up to 25 images or one scanned PDF of up to 25 selected pages; images and a PDF are not mixed in one submission. Local OCR supports explicit `Term — Definition`, colon forms, labeled separated lines, and reliable two-column layouts. |
| Ambiguity / review | Ambiguous or incomplete text remains unassigned instead of being guessed. Candidate pairs and source/page context enter the matching Review & Repair workflow; users can edit/add/remove/reorder and must confirm all final pairings. Duplicate/invalid pairs are rejected on server-side revalidation. |
| Retention | Original uploads/rendered temporary pages follow transient OCR staging and are removed after completion/cancel/expiry; published matching content uses normal persistence. |
| Evidence | `dlms/parsing/ocr_matching.py`; `dlms/services/ocr_matching.py`; `templates/pdf_import/process-ocr-matching.html`; OCR matching tests/browser workflow. |
| Manual / screenshot / status | Ch. 10–11; UM-18; **Verified**. |

### 13. Matching, terminology, images, and hotspots

#### Canonical matching questions

| Inventory field | Verified behavior |
| --- | --- |
| What and why | Presents a set of left/right pairs as an interactive matching activity in Study or Exam Mode. |
| Authoring options | Pair editing, Term → Definition, Definition → Term, or randomized direction where the source workflow supports it; optional round size; at least two pairs. Matching sources include manual/CSV, terminology banks, packs, OCR, External AI, and portable imports. |
| Interaction / scoring | Drag-and-drop is supplemented by accessible select controls. Pair order/direction may be shuffled, while correctness remains based on saved canonical pairs. Generic matching stems with different pair structures remain different exact duplicates. |
| Evidence | quiz renderer/runtime; matching builders/services; matching and identity/duplicate tests. |
| Manual / screenshot / status | Ch. 6 and 11; existing matching Help asset; **Verified**. |

#### Image Study builder

| Inventory field | Verified behavior |
| --- | --- |
| Screen / reach | Study Packs/Image Study → create an image-based pack/quiz draft. |
| What and why | Builds choice/multi-select, matching, and hotspot questions around user-supplied images and source/rights metadata. |
| Inputs / controls | Study Pack/quiz title, subject/domain, timer, description/source credit; image uploads; per-question image/type/text/explanation; choice correctness, pairs, or hotspot shape/label/radius/points. |
| Review / output | Client draft is validated before saving into the existing content-pack/quiz publication path. Source and rights notes should be completed for material the user is allowed to use. |
| Evidence | `templates/study_packs/image-builder.html`; image builder routes/services/tests; authoring accessibility tests. |
| Manual / screenshot / status | Ch. 11 and 13; no separate start screenshot; **Verified**. |

#### Image Study Editor: Clickable Regions and Image Prep

| Inventory field | Verified behavior |
| --- | --- |
| Screen / reach | System Tools/Image Study Editor or subject image-study links; select an installed pack/dataset. |
| What and why | Repairs hotspot regions or prepares non-destructive image-study derivatives without replacing source images. |
| Controls | Clickable Regions: polygon/circle, load existing, keyboard cursor, undo, clear, test, save. Image Prep: blur/white/black masks, labels, size/tone, undo/clear/save. |
| Accessibility | The image stage is focusable and named; arrow keys move the authoring cursor and Enter/Space places points. Finished hotspots also support keyboard answers. Status updates use accessible semantics. |
| Persistence / failure | Source image remains unchanged; saved overlays/regions are derived pack data. UI indicates backup/preservation behavior where applicable. |
| Evidence | `templates/admin/image-editor.html`; editor JS/CSS; `dlms/routes/admin_images.py`; image editor/accessibility/browser tests. |
| Manual / screenshot / status | Ch. 11; UM-19; **Verified**; complex spatial authoring still merits manual keyboard/assistive-technology review. |

### 14. External-AI-assisted workflows

#### External AI choice and matching structured-text builder

| Inventory field | Verified behavior |
| --- | --- |
| Screen / reach | Build Quiz → External AI Builder; choose Choice Questions or Matching/Terminology. |
| What and why | Generates a bounded prompt to use in ChatGPT, Gemini, Claude, a local model, or another conversational tool; the user pastes returned structured JSON into DLMS. No AI-provider API or account is required by DLMS. |
| Prompt inputs | Topic (up to 500 characters), audience/source expectations (up to 2,000), Introductory/Intermediate/Advanced/Mixed difficulty, count, and optional source metadata. |
| Response contract | At most 1 MiB, either bare JSON or one fenced `json` block; choice questions have bounded fields/choices and explicit correctness, while matching uses the existing canonical one-question pair structure (2–100 pairs). Maximum 100 returned questions. |
| Validation / safety | Malformed JSON, unexpected/unsupported fields/types/content types, unsafe URLs, count/size violations, missing data, conflicting duplicates, or invalid correctness are rejected or surfaced as repair issues. AI output is always untrusted. |
| Review / persistence | Transient staging enters type-appropriate Review & Repair; users edit/add/remove/reorder and explicitly confirm before normal quiz publication. Draft is removed on publish/start-over and expires if abandoned. |
| Evidence | external AI routes/services/templates; prompt definitions; `static/external-ai-matching-review.js`; External AI choice/matching/publication/browser tests. |
| Manual / screenshot / status | Ch. 12; UM-20; **Verified**. |

#### External explanation helper

| Inventory field | Verified behavior |
| --- | --- |
| Screen / reach | Supported Study Mode/result/missed-question actions when enabled in Settings. |
| What and why | Copies a bounded explanation prompt and optionally opens the configured provider so the user can ask an external tool for teaching help. |
| Settings | Enable/disable, auto-copy, provider (ChatGPT, Claude, Gemini, local, or custom URL), and editable prompt templates. |
| Boundary | DLMS does not transmit the question to an AI API; clipboard/browser handoff is user-controlled. Returned explanations are not automatically made canonical correctness. |
| Evidence | Settings AI routes/templates; `static/script.js`; prompts; AI-helper tests/Help. |
| Manual / screenshot / status | Ch. 12 and 16; no dedicated screenshot; **Verified**. |

#### AI Study Pack ZIP workflow

| Inventory field | Verified behavior |
| --- | --- |
| Screen / reach | Study Packs → AI Study Pack Builder and subject-space links. |
| What and why | Produces a controlled prompt asking an external AI for a DLMS Study Pack ZIP, then validates/stages that ZIP through Content Pack import. |
| Inputs | Topic/domain, difficulty, size, images/style, and supported combinations of matching, image, and multiple-choice material; configured provider handoff. |
| Important distinction | This is a ZIP/archive workflow, not the External AI Builder’s pasted structured text. It still uses no direct provider API. |
| Review / output | Uploaded ZIP undergoes strict Content Pack validation and Review before installation; it is never trusted merely because it came from the prompt. |
| Evidence | `templates/study_packs/ai-builder.html`; pack prompts/routes; Content Pack validator/tests; existing Help assets. |
| Manual / screenshot / status | Ch. 12–13; UM-21; **Verified**. |

### 15. Study Packs, Content Packs, and subject spaces

#### Study Packs catalog and generated activities

| Inventory field | Verified behavior |
| --- | --- |
| Screen / reach | Primary Study Packs navigation; IT/Medical/Other Studies links can open filtered subject views. |
| What and why | Browses installed learner-facing matching, image/hotspot, mixed, or quiz datasets and generates configured activities. |
| Controls | Domain filters (IT, Medical, Other); expand/collapse packs; choose matching pair count/direction or supported image/quiz options; start generated practice. Empty states direct users toward installation/creation. |
| State | Expand/collapse preference is browser-local. Installed pack content and generated quizzes/history are server data. Generated quizzes retain source-pack provenance without mutating the installed source. |
| Evidence | study pack routes/templates/services; `static/help-study-packs.html`; Study Pack generation/browser tests. |
| Manual / screenshot / status | Ch. 13; UM-22; **Verified**. |

#### Content Pack management

| Inventory field | Verified behavior |
| --- | --- |
| Screen / reach | Content Packs management from Study Packs/settings/navigation links. |
| What and why | Imports, validates, reviews, installs, inspects, exports, and deletes the packaged content that supplies Study Packs. |
| Import / review | ZIP upload up to 256 MiB; safe archive/schema/media validation; review of errors/warnings and explicit confirmation; atomic installation preserves an existing pack if replacement fails. |
| Delete / preservation | Protected packs cannot be deleted. Deleting an installed pack does not erase existing quizzes/history; quiz-owned legacy media needed by published quizzes is preserved. |
| Boundary | Content Pack management is distinct from Portable Quiz Bundles, backups, and the learner-facing Study Packs catalog. |
| Evidence | `dlms/routes/content_packs.py`; content-pack templates/services/tests; Help content-management pages. |
| Manual / screenshot / status | Ch. 13; UM-22; **Verified**. |

#### IT, Medical, and Other Studies spaces

| Inventory field | Verified behavior |
| --- | --- |
| Screen / reach | Optional primary-navigation subject destinations, controlled in Settings → Navigation. |
| What and why | Presents installed packs through subject-oriented landing pages and shortcuts rather than introducing separate persistence. IT includes concepts/matching, diagrams/images, and AI builder; Medical includes matching, anatomy/images, and AI builder; Other Studies filters packs outside the dedicated domains. |
| State / settings | Hiding a navigation item does not delete data or prevent direct access. Empty states explain how to install/create material. Medical AI prompt handling includes configurable safety/addendum text. |
| Evidence | IT/Medical routes/templates; Study Pack aggregation services; Navigation/AI settings; subject tests/Help. |
| Manual / screenshot / status | Ch. 13 and 16; existing subject landing candidates; **Verified**. |

#### Law Case Reviews

| Inventory field | Verified behavior |
| --- | --- |
| Screen / reach | Optional Law Study navigation → Create Case Review / Import Case Packet / Saved Imports / Case Reviews. |
| What and why | Uses a provider-neutral prompt/paste flow to preserve a raw case packet, preview recognized sections, create a structured Case Review, and study it locally. |
| Inputs / workflow | Case/course and chosen sections; external prompt; pasted complete packet; Save & Preview; review parsed headings; create exact saved Case Review. |
| Study controls | Case brief sections; an editable IRAC response with revealable imported guidance; Socratic questions with saved responses, progress, and revealable guidance; displayed rule material; notes; text export; and Law Anki export. Raw Saved Imports and created Case Reviews have separate management/deletion. |
| Future-mode distinction | The four non-interactive `Future Study Modes` previews are IRAC Practice, Socratic Prep, Rule Flashcards, and Case Compare. There are no separate standalone IRAC, Socratic, or native interactive flashcard modes, although related activities/material already exist inside a saved Case Review. Case Compare is not implemented. The manual must document the embedded workflow without presenting the preview cards as available features. |
| Evidence | `dlms/routes/law.py`; Law templates; `static/help-study-modules.html`; Law persistence/import/Anki tests. |
| Manual / screenshot / status | Ch. 13–14; UM-23; **Verified**. Distinguish embedded Case Review activities from unimplemented standalone preview modes. |

### 16. Anki, decks, and printable cards

#### Anki Tools and custom decks

| Inventory field | Verified behavior |
| --- | --- |
| Screen / reach | Anki Tools navigation; quiz Study Mode; History/missed results; Law Study. |
| What and why | Turns selected quiz questions, missed questions, or recognized Law rule-card material into text front/back Anki-compatible study packages without replacing DLMS study/history. The current card model is best suited to choice questions and Law cards; it does not expand matching pairs into individual cards or embed image/hotspot interaction. |
| Controls | Export quiz questions; filter missed questions by quiz/all, minimum misses (1–100), and currently weak/repeated/recovered/once status; select individual cards into a named Custom Deck; preview first 20 while exporting all. |
| Outputs | Current guided workflows produce `.apkg` decks or printable physical flashcards with front/back and duplex flip controls. Law exports can select cases/course/all. Two legacy TSV compatibility endpoints remain for quiz-choice and selected missed-question data, but no current Anki Tools, quiz runtime, History Review, or Help control links to them. |
| External dependency | Anki is an external application used to import/open `.apkg`; DLMS creates the package locally. |
| Evidence | `dlms/routes/anki.py`; Anki templates/services/tests; Study runtime; Help Anki/assets. |
| Manual / screenshot / status | Ch. 14; UM-24; **Verified**. Present `.apkg` and printable cards as ordinary workflows. Mention TSV, if needed, only as advanced/legacy compatibility and do not present the missed-question POST endpoint as a normal procedure. |

### 17. Settings, backup, maintenance, and removal

#### Appearance and navigation settings

| Inventory field | Verified behavior |
| --- | --- |
| Screen / reach | Settings → Appearance / Navigation. |
| What and why | Personalizes the local UI and controls optional subject-navigation visibility. |
| Options | Light, Dark, Purple & Gold, and Maroon & Gold themes; portal title; background image. Show/hide IT, Law, Medical, and Other Studies navigation. |
| Boundary | Navigation visibility does not delete or disable underlying content. Themes use shared semantic styling, focus, responsive, and contrast behavior. |
| Evidence | settings routes/templates; `static/style.css`; theme/layout/accessibility tests; Help settings assets. |
| Manual / screenshot / status | Ch. 3 and 16; a small appearance screenshot may be optional; **Verified**. |

#### AI, parsing, and lifecycle settings

| Inventory field | Verified behavior |
| --- | --- |
| Screen / reach | Settings → AI / Parsing / Lifecycle. |
| What and why | Configures external handoffs, optional parsing tools, and eligible local browser-presence shutdown behavior. |
| AI options | Helper enabled, auto-copy, named/local/custom provider URL, and editable explanation, Study Pack, Medical safety, and Law prompt templates; reset defaults. No provider credential/API storage is required. |
| Parsing options | Confidence analysis, manual regular expressions, cleanup tools including invisible/BOM handling, and related authoring toggles. |
| Lifecycle | Optional browser-presence shutdown applies only to eligible loopback use: after the final DLMS page disappears and a grace period of roughly five minutes expires, the local process may stop; reopening cancels it. In LAN/server mode it is unavailable, closing client browser windows does not stop the server, and the process/service must be stopped from the host computer. |
| Evidence | settings routes/templates/services; runtime lifecycle code/tests; Help. |
| Manual / screenshot / status | Ch. 16; UM-25; behavior **Verified**. Existing non-manual LAN shutdown prose conflicts with the authoritative behavior and should be corrected in separately approved work. |

#### Backup and Restore

| Inventory field | Verified behavior |
| --- | --- |
| Screen / reach | Settings → Backup & Restore. |
| What and why | Downloads a portable recovery snapshot and stages a validated replacement of persistent DLMS data. |
| Backup scope | Quizzes/generated artifacts and assets, database/history, settings, Study/Content Packs, PDF/Image banks and relevant drafts, Law data, background/logo. Transient temp/staging/previews and older backup files are excluded. |
| Restore safety | Upload up to 298 MiB; traversal/symlink/schema/duplicate/expanded-content checks; review summary; confirm/cancel; pre-restore safety backup; cleanup recovery; successful restore instructs reload and clears browser recovery records. |
| Distinction | A backup contains personal application state and must be protected. It is not a public Portable Quiz Bundle or Content Pack. |
| Evidence | settings/maintenance routes/templates; backup services; backup/restore/security/Firefox tests. |
| Manual / screenshot / status | Ch. 17; UM-26; **Verified**. |

#### Reset & Remove

| Inventory field | Verified behavior |
| --- | --- |
| Screen / reach | Settings → Reset & Remove. |
| What and why | Offers separate, deliberately scoped data-reset actions rather than one ambiguous reset. |
| Actions | Clear saved attempts/missed history; reset Learning Intelligence evidence; reset Quiz Library and results; clear source content; reset settings; reset active data to fresh state while preserving backups; permanently remove the entire DLMS data directory and shut down. |
| Confirmation / preservation | Destructive actions explain inclusions/exclusions and create safety backups where specified. Permanent removal requires typing `REMOVE DLMS DATA`, has no in-directory recovery backup, leaves the executable/source installation, and warns users to copy/download a backup elsewhere first. |
| Evidence | `templates/settings/reset-remove.html`; settings/maintenance services; reset scope/confirmation tests; Help. |
| Manual / screenshot / status | Ch. 17; existing reset Help assets; **Verified**. |

#### Rebuild All Quiz Pages

| Inventory field | Verified behavior |
| --- | --- |
| Screen / reach | Settings → System Tools. |
| What and why | Occasional maintenance/recovery that regenerates derived quiz HTML and playable JSON from canonical persisted quiz data when instructed or when old pages are stale/inconsistent. Users normally do not run it after an update. |
| Confirmation / result | Clear explanation plus confirmation before rebuilding all applicable quizzes; reports useful success/failure counts. |
| Explicit preservation | Does not change questions, answers/correctness, quiz/question IDs, concepts, lineage, registry identity, folders, order, attempts, scores, learning events, history, or provenance. |
| Failure | Each replacement uses safe rendering/publication behavior; failure for one quiz preserves its prior artifacts and does not corrupt canonical quiz data or prevent reporting other results. |
| Evidence | maintenance routes/templates/services; quiz artifact renderer/publication; rebuild contract/UI/tests; Help maintenance. |
| Manual / screenshot / status | Ch. 17; UM-27; **Verified**. |

#### Shutdown and permanent data removal

| Inventory field | Verified behavior |
| --- | --- |
| Screen / reach | Shutdown control in normal navigation/runtime UI; permanent removal in Reset & Remove. |
| Local behavior | In loopback desktop mode, Shutdown DLMS is the immediate recommended stop action. Optional browser presence may stop the process after the last DLMS window closes and the grace period expires. |
| LAN/server behavior | In explicit non-loopback mode, the UI disables in-app shutdown and presents an accessible explanation to stop DLMS on the host system. `POST /api/shutdown` returns 403 and does not stop the process. Automatic browser-presence shutdown is unavailable, and closing client browser windows does not stop the server. Runtime mode comes from the configured bind/runtime mode, not an individual request’s address. |
| Security warning | LAN mode has no DLMS authentication or TLS. It is for trusted/firewalled networks and must not be exposed directly to the Internet. |
| Evidence | core/runtime routes and templates; lifecycle code/settings; shutdown/LAN/accessibility tests. |
| Manual / screenshot / status | Ch. 16–18 and runtime appendix; UM-25; implementation **Verified**, existing docs **conflict**. |

### 18. Help Center, errors, confirmations, and platform behavior

#### Help Center and contextual help

| Inventory field | Verified behavior |
| --- | --- |
| Screen / reach | Help in primary navigation, contextual quiz Help, About, Advanced Features, and Regex Help. |
| What and why | Provides versioned topic navigation, step-based workflows, screenshots, callouts, troubleshooting, and links back to product actions. |
| Current scope | Thirteen main topics plus specialized pages cover the stable/core and many 3.2 workflows, but depth and terminology vary. Help footers identify 3.2.0. |
| Accessibility | Help uses semantic headings/navigation, descriptive image alternative text/captions, and responsive layout patterns; existing assets need current-screen review before manual reuse. |
| Evidence | `dlms/routes/help.py`; `static/help-*.html`; Help assets/tests/browser workflows. |
| Manual / screenshot / status | Ch. 3 and throughout; **Verified; existing docs incomplete/conflicting** as detailed below. |

#### Errors, warnings, validation, and confirmation patterns

| Inventory field | Verified behavior |
| --- | --- |
| What and why | Keeps invalid/untrusted imports out of canonical content and makes destructive/uncertain actions deliberate. |
| Visible patterns | Request-too-large and parse-failure pages; inline errors preserving entered data where supported; status/live announcements; incomplete/review badges; confirmation dialogs/forms; typed confirmation for permanent removal; explicit AI/OCR/source-rights warnings. |
| Fallback philosophy | Recoverable extraction is preserved for Review & Repair; DLMS does not invent missing correctness, terms, definitions, source data, or OCR pairings. Atomic publication/restore/install aims to preserve prior valid data on failure. |
| Evidence | shared error templates; form/routes/services; import/review/backup/publication tests; accessibility tests. |
| Manual / screenshot / status | Explain within each task and consolidate in Ch. 18/reference; screenshots only for consequential examples; **Verified**. |

#### Platform/package differences

| Inventory field | Verified behavior |
| --- | --- |
| What and why | Native packages provide a desktop-style local launch while retaining the same browser UI and data model. |
| Windows | Versioned package wrapper with stable-named `.exe`, README, and sample quiz; user data under `%APPDATA%\DLMS`; unsigned-app warnings may appear. |
| Linux | Versioned wrapper with executable permission preserved, README, and sample quiz; XDG/home data path; target-specific native packages. |
| macOS | Apple Silicon application; ZIP root contains `DLMS.app`, README, and sample quiz with no wrapper, supporting drag to `/Applications`; data under Application Support; Gatekeeper may warn for unnotarized builds. |
| OCR/source distinction | Release packages are built with validated local OCR resources. Source users must satisfy optional OCR dependencies themselves; ordinary users should not be sent through the maintainer OCR-bundle build process. |
| Evidence | root/release README; release/OCR packaging docs; package/artifact verifiers and tests. |
| Manual / screenshot / status | Ch. 2 and platform appendix; no packaging screenshot; **Verified**, native per-target UAT remains a release activity rather than a manual fact. |

## Screen and navigation map

This map groups route variants that present the same task. “Workflow-only” means
the page is reached from a prior step rather than ordinary navigation. API-only
endpoints and static assets are not pages.

| Screen or workflow surface | How the user reaches it | Purpose and major controls | Leads to / state-dependent behavior | Exposure | Manual home |
| --- | --- | --- | --- | --- | --- |
| Dashboard | Primary home / logo | Today’s Review, Quick Access, recent activity, overview | Starts/resumes study, opens authoring/library/history/packs; local Resume items vary by browser | Primary | 3, 7 |
| Quiz Library | Primary navigation | Scope, search, folders, Smart Views, quiz actions, Library Tools | Play/edit/export/hide/delete; composition/duplicates/bundles/build | Primary | 5 |
| Folder management | Quiz Library inline controls/modals | Add, rename, hide, delete, reorder folders; move/reorder quizzes | Updates registry organization only | Secondary/modal | 5 |
| Smart Views | Quiz Library row | Needs Review, Recently Added, Low Score, Unfinished, OCR Imported, Generated Practice | Filters Library; search composes; reset returns full library | Secondary | 5 |
| Mixed Quiz Builder | Library Tools → Mix Questions | Filter, preview, multi-source select, name, create | Publishes curated generated quiz; sources unchanged | Secondary | 5 |
| Duplicate Question Review | Library Tools → Find Duplicates | Scan exact/possible groups, compare context/answers, edit source | Advisory; empty state when none; no merge/delete | Secondary | 5 |
| Quiz Bundles | Library Tools → Quiz Bundles | Select/export quizzes; upload a bundle | Downloads ZIP or stages import preview | Secondary | 15 |
| Bundle import review | Valid bundle upload | Review manifest/quizzes/media/renames; confirm/cancel | Atomic import or failure summary | Workflow-only | 15 |
| Build Quiz hub | Primary navigation/Dashboard | Choose manual, file, paste, PDF/image, matching CSV, image, External AI | Opens specialized builder | Primary | 4 |
| Short Quiz Builder | Build Quiz | Add/remove choice or matching questions, title/logo/timer, publish | Creates quiz or returns validation errors | Workflow-specific | 4 |
| Text-file upload | Build Quiz | Select `.txt`, title/logo/timer, submit | Parses/publishes or opens error/recovery path | Workflow-specific | 4 |
| Paste Quiz Text | Build Quiz | Paste, cleanup options/presets/regex, preview | Opens cleanup/parse preview | Workflow-specific | 4 |
| Paste preview / parse failure | Paste workflow | Compare original/cleaned/diff, confidence/invisibles, download, continue/back | Publishes or returns for repair | Workflow-only | 4, 18 |
| Matching CSV import/edit | Build Quiz | Upload CSV, set direction/round/source metadata, edit pairs | Publishes matching quiz | Workflow-specific | 4, 11 |
| Quiz editor | Library/Edit or management source link | Edit title/timer/logo/questions/concepts/answers/pairs/explanations/order | Saves/rebuilds, deletes with confirmation | Secondary | 4–5 |
| Quiz mode chooser | Open quiz | Choose Study Mode or Exam Mode | Loads shared runtime in chosen mode | Workflow-only | 6 |
| Study Mode runtime | Mode chooser | Answer, immediate feedback/explanation, navigate, select/export cards, external help | Saves learning evidence; completes to next actions | Workflow-only | 6 |
| Exam Mode runtime | Mode chooser | Timer/pause, answer/navigation, submit | Persists attempt then opens result | Workflow-only | 6 |
| Recovery panel | Reopen interrupted quiz | Resume, Finish Saving where needed, or Start Over | Restores valid browser checkpoint or clears it | Major modal/panel | 6 |
| Result / attempt review | Exam completion or History | Score and result actions; saved missed-question detail; Retake Exam from the result panel | Durable result; missed-item follow-up/export | Workflow-only | 9 |
| History | Primary navigation | Filter/paginate attempts and open results | Attempt detail, missed review, quiz actions | Primary | 9 |
| Progress & Performance / Analytics | History/analytics navigation | Overall and per-quiz attempt metrics/trends | Informational links back to activity | Secondary | 9 |
| Missed Questions review | Completed result/History review action | Show recorded missed items and supported review/export/explanation controls | Review source material, open History/quiz, or export selected cards | Secondary | 7, 9 |
| Learning Profile | Learning Intelligence navigation | Summary cards, strongest/weakest, activity, next action | Links to topics/schedules/review | Primary family | 8 |
| Learning Intelligence topics | Learning Intelligence navigation | Concept metrics, filters, mastery explanation, Practice | Concept Review, Smart/Adaptive paths | Primary family | 8 |
| Mastery explanation dialog | Learning Intelligence | Plain-language four-factor explanation plus technical details | Closes back to concept table | Major modal | 8 |
| Learning Diagnostics | Learning Intelligence | Confusion and question-quality filters/search/detail | Advisory follow-up/edit/study | Secondary | 8 |
| Review Schedule | Learning Intelligence/navigation | Due Questions counts/states/batch; Topic Retention timing/filter/batch | Starts due or topic-level generated session | Primary family | 7–8 |
| Adaptive Study action/configuration | Today’s Review/Learning Intelligence | Choose supported size and review selection reasons | Publishes/opens generated practice | Workflow-specific | 7 |
| Smart Review action | Learning Intelligence | Choose supported size for weak-concept practice | Publishes/opens Generated Practice | Workflow-specific | 7 |
| Concept Review action | Concept row/Today’s Review | Start one-concept targeted session | Publishes/opens Generated Practice | Workflow-specific | 7–8 |
| Due Questions action | Today’s Review/Review Schedule | See total/batch, choose supported size on schedule page, start | Opens generated due batch; recalculates remainder after completion | Workflow-specific | 7 |
| Topic Retention action | Review Schedule | Filter concept timing, choose size, generate | Opens concept-level scheduled practice | Workflow-specific | 7–8 |
| PDF & Image Import | Build Quiz | Select document/image workflow, title/type/timer, confirm rights | Extraction/OCR offer/processing/review | Secondary hub | 10 |
| Low-text OCR candidate selection | PDF analysis detects candidate pages | Select pages, OCR, continue without, or cancel | Returns combined extraction to review | Major workflow dialog/page | 10 |
| Screenshot OCR submission/status | PDF & Image Import | Upload ordered images and run local OCR | Partial success/failure summary, question review | Workflow-specific | 10 |
| OCR matching submission/status | PDF & Image Import | Upload images or scanned PDF for term/definition extraction | Matching Review & Repair | Workflow-specific | 10–11 |
| Question Review & Repair | PDF/OCR extraction | Filter statuses; edit/add/remove/reorder/include; confirm correctness | Saves Question Bank or remains staged | Workflow-only | 10 |
| Glossary Review & Repair | PDF extraction | Edit/exclude/restore terms; bulk visible controls | Saves Terminology Bank | Workflow-only | 10–11 |
| OCR matching Review & Repair | OCR extraction | Edit/add/remove/reorder pairs and unassigned text; confirm all | Publishes normal matching content | Workflow-only | 10–11 |
| Question Bank | Saved Smart PDF source | Inspect active source records; random/unused/sequential/range/all generation | Creates practice; bank remains | Secondary | 10 |
| Terminology Bank | Saved glossary source | Inspect pairs; choose Matching/Choice, selection, direction, count | Creates practice; bank remains | Secondary | 10–11 |
| External AI Builder | Build Quiz | Select Choice or Matching, prompt inputs, copy/open provider, paste response | Stages validated Review & Repair | Secondary | 12 |
| External AI choice review | Valid pasted choice JSON | Edit/reorder/question correctness, confirm | Publishes quiz | Workflow-only | 12 |
| External AI matching review | Valid pasted matching JSON/OCR handoff | Edit/add/remove/reorder pairs, confirm | Publishes canonical matching quiz | Workflow-only | 12 |
| Study Packs catalog | Primary navigation/subject links | Filter/expand packs; configure matching/image/quiz activity | Generates normal playable quiz | Primary | 13 |
| AI Study Pack Builder | Study Packs/subject spaces | Configure content prompt, external handoff, upload ZIP | Content Pack validation/review/install | Secondary | 12–13 |
| Image Study Builder | Study Packs | Upload images; create choice/matching/hotspot questions; source metadata | Saves validated pack/quiz content | Secondary | 11, 13 |
| Content Packs | Management navigation | Import, list, inspect, export, delete eligible packs | Upload opens staged review; detail shows datasets/assets | Secondary/management | 13 |
| Content Pack import review | Valid uploaded ZIP | Errors/warnings/content preview; confirm/cancel | Atomic install or unchanged prior pack | Workflow-only | 13 |
| Content Pack detail | Content Packs list | Inspect manifest/content/assets/protection; export/delete | Returns to management/catalog | Secondary | 13 |
| IT Study | Optional primary navigation | Installed IT overview and AI builder entry | Concepts & Matching or Diagrams & Images | Primary optional | 13 |
| IT Concepts & Matching | IT Study | Browse/configure installed matching datasets | Generates matching practice | Secondary subject page | 11, 13 |
| IT Diagrams & Images | IT Study | Browse/configure installed image/hotspot datasets and editor links | Generates image practice or opens editor | Secondary subject page | 11, 13 |
| Medical Study | Optional primary navigation | Installed medical overview and AI builder entry | Terminology & Matching or Anatomy & Images | Primary optional | 13 |
| Medical Terminology & Matching | Medical Study | Browse/configure installed matching datasets | Generates matching practice | Secondary subject page | 11, 13 |
| Medical Anatomy & Images | Medical Study | Browse/configure image/hotspot datasets and editor links | Generates image practice or opens editor | Secondary subject page | 11, 13 |
| Other Studies | Optional primary navigation | Non-IT/Law/Medical Study Packs | Filtered Study Pack activity | Primary optional | 13 |
| Law Study landing | Optional primary navigation | Create/import/manage case packets and Case Reviews; Anki | Guided Law workflow | Primary optional | 13 |
| Create Law Case Review | Law Study | Case/course/section choices; generate external prompt | Import Case Packet | Workflow-specific | 13 |
| Import/preview saved case packet | Law Study | Paste/save raw packet, inspect recognized sections, create case | Saved Import and structured Case Review | Workflow-only | 13 |
| Law Case Review detail/editor | Law Case Reviews | Brief, Socratic, IRAC, rules, notes, export/edit/delete | Saves study work; Anki/export | Secondary | 13–14 |
| Image Study Editor | System Tools/subject images | Choose pack/dataset; Clickable Regions or Image Prep | Saves regions/derived overlays; test result | Maintenance/authoring | 11 |
| Anki Tools | Primary/secondary navigation | Choose quiz/history/Law/custom workflow | `.apkg` exports and printable cards; legacy TSV has no current guided control | Primary family | 14 |
| Custom Deck Builder | Anki Tools | Filter/select cards, name, preview | Download `.apkg` or printable view | Secondary | 14 |
| Printable cards | Custom Deck | Front/back preview and duplex flip controls | Print | Workflow-only | 14 |
| Settings overview | Primary navigation | Open Appearance, Navigation, AI, Parsing, Lifecycle, Backup, Reset, System Tools | Specialized settings pages | Primary | 16–17 |
| Appearance | Settings | Theme, portal title, background image | Applies local UI presentation | Secondary | 16 |
| Navigation | Settings | Show/hide optional subject destinations | Updates nav only | Secondary | 16 |
| AI settings | Settings | Enable/helper/provider/custom URL/prompt templates/reset | Affects external handoff only | Secondary | 12, 16 |
| Parsing settings | Settings | Confidence/regex/cleanup tool availability | Affects text-import UI/parser options | Secondary | 4, 16 |
| Lifecycle settings | Settings | Browser-presence auto-shutdown eligibility/state; LAN explanation | Local mode behavior; disabled in LAN | Secondary | 16 |
| Backup & Restore | Settings | Download backup; upload, stage, inspect, confirm/cancel restore | Restore completion/reload or failure recovery | Secondary | 17 |
| Restore complete | Successful restore | Safety-backup/cleanup status and reload links | Clears local recovery, returns to Dashboard/settings | Workflow-only | 17 |
| Reset & Remove | Settings | Scoped resets, fresh state, typed permanent removal | Safety backups or destructive shutdown as explained | Secondary/critical | 17 |
| System Tools | Settings | Rebuild All Quiz Pages; Image Study Editor | Reports rebuild success/failure | Maintenance | 17 |
| Shutdown status/control | Global/navigation | Stop eligible local process or explain LAN unavailability | Local shutdown; host-system action in LAN | Runtime control | 16, 18 |
| Help Center | Primary navigation | Topic cards/search/navigation and versioned guidance | Specialized Help topics and product routes | Primary | 3 |
| Contextual Quiz Help | Quiz/runtime Help link | Study/Exam/question interaction help | Returns to quiz/workflow | Contextual | 6 |
| Advanced Features / Regex Help / About | Help/context links | Specialized parsing/product/version reference | Return to Help/application | Secondary | 3–4, reference |
| Error/too-large/parse-failure pages | Invalid request/import | Explain failure, preserve safe return/recovery links | Back to relevant builder/help | Workflow-only | 18 |

### Technically reachable but not ordinary standalone pages

- Generated quiz HTML, playable JSON, pack assets, and media-delivery routes are
  runtime resources reached through a quiz or pack, not navigation destinations.
- JSON endpoints for attempts, learning events, scheduling, recovery-aware
  Dashboard composition, folder ordering, maintenance, and shutdown support the
  visible screens; users should not be instructed to call them directly.
- Two legacy TSV compatibility endpoints remain technically reachable but are
  not linked from the current Anki Tools, quiz runtime, History Review, or Help
  UI. The manual should emphasize current `.apkg` and versioned bundle workflows
  rather than presenting raw endpoints as ordinary procedures.
- Staging status/cancel/cleanup routes are implementation support for import,
  backup, OCR, and External AI workflows. Document the visible status and cancel
  behavior, not route mechanics.

## End-to-end user-workflow map

| Workflow | Verified user path | Important decisions, safety, and resulting state | Manual home |
| --- | --- | --- | --- |
| Install and first launch | Download target package → extract/install as documented → acknowledge platform warning if needed → launch → browser Dashboard | Package is native to its target; data is outside the executable; no account. Default is loopback. | 2 |
| Create a normal quiz | Build Quiz → Short Builder → title/timer/logo → add choice/matching content → mark correctness/pairs → publish → open/Library | Server revalidates; creates persistent canonical source quiz plus derived playable artifacts. | 4 |
| Import a text quiz | Build Quiz → Text File → choose `.txt` and options → parse/publish | Strict answer-marker contract; errors do not invent correctness. | 4 |
| Paste and clean quiz text | Build Quiz → Paste → choose cleanup/presets/optional regex → inspect preview/diff/confidence → continue/publish | Preserve input during repair; bare `Answer:` is not correctness; advanced tools depend on settings. | 4 |
| Import matching CSV | Build Quiz → Matching CSV → choose file/direction/round/source info → repair pairs → publish | At least two unique non-conflicting pairs; creates normal matching quiz. | 4, 11 |
| Edit or remove a quiz | Quiz Library → Edit → change content/order/metadata → Save, or confirmed Delete | Shared safe rebuild; identity retained. Explain recovery invalidation and deletion conservatively. | 4–5 |
| Take Study Mode | Open quiz → Study Mode → answer each question → inspect immediate feedback/explanation → continue | Each completed answer must be acknowledged; failed saves remain retryable/recoverable; generated evidence follows source lineage. | 6 |
| Take Exam Mode | Open quiz → Exam Mode → answer/navigate/pause → submit or timeout → result review | One durable attempt is saved before recovery clears; failed acknowledgement preserves exact pending attempt. | 6, 9 |
| Resume interrupted work | Open same quiz or Dashboard/Unfinished → inspect `This browser` record → Resume or Start Over | Browser-local only; 30-day/bounded/validated checkpoint; completed saved work does not remain resumable. | 6, 18 |
| Review a completed attempt | Result or History → open attempt → inspect saved missed-question answers/context → review/export as offered | Durable shared server history, distinct from recovery; Retake Exam is offered on the Exam result panel. | 9 |
| Decide what to study | Dashboard → Today’s Review → read “why” → take first appropriate action | Due first, then specific weak concept, unfinished local work as merged, broader Adaptive/pack suggestions; deterministic/deduplicated. | 7 |
| Complete a limited Due batch | Today’s Review/Review Schedule → note total and next batch → finish generated session → return/refresh | Completed batch is not Resume. Remaining source questions are recalculated and a new Due action appears only if needed. | 7 |
| Use Adaptive Study | Today’s Review/Learning Intelligence → choose supported size → review selection reasons → start generated quiz | Balanced deterministic source selection; safe fallback with little/no history; no generated-source recursion. | 7 |
| Use Smart Review | Learning Intelligence → Smart Review → choose size → start | Uses weak-concept source questions across the library. | 7 |
| Review one concept | Learning Intelligence/Today’s Review → Practice/Review weak concept | Up to 20 questions for that canonical concept; answer evidence follows source. | 7–8 |
| Use Topic Retention Schedule | Review Schedule → inspect due/upcoming topics → filter/select size → generate | Concept-level, minimum evidence; distinct from question-level Due Questions. | 7–8 |
| Review missed questions | Result/History/Anki → choose recorded misses/filter → review, explain externally, or export | Uses saved incorrect responses; “currently weak” and “recovered” filters have historical meaning. | 7, 9, 14 |
| Understand mastery/trend | Learning Intelligence → topic table → open mastery explanation → compare metrics/evidence → choose Practice | Mastery is four-factor level; Trend is recent direction; limited evidence prevents overclaiming. | 8 |
| Use diagnostics | Learning Intelligence → Diagnostics → filter repeated confusions/question signals → inspect context → edit/study if useful | Advisory only; no automatic rewrite. | 8 |
| Import selectable question PDF | PDF & Image Import → choose PDF/type/title/timer → confirm rights → extract → Review & Repair → confirm correctness → save bank → generate practice | Structural recognition and conservative incomplete/unassigned handling; no invented answer. | 10 |
| Import terminology PDF | PDF & Image Import → Glossary/Auto → extract → repair/exclude terms → save Terminology Bank → choose Matching/Choice practice | Styled text when reliable, deterministic fallback otherwise; source bank remains. | 10–11 |
| OCR scanned/low-text PDF | Import PDF → accept candidate-page offer → select pages or continue without → local OCR → Review & Repair | Up to 25 candidate pages; partial success retained; selectable text authoritative. | 10 |
| OCR screenshot questions | PDF & Image Import → upload ordered images → OCR → inspect partial failures/candidates → Review & Repair → publish bank/practice | Temporary images; 2–26 choices; selected appearance is not correctness. | 10 |
| OCR terminology/matching | PDF & Image Import → choose images or scanned PDF → OCR → inspect candidate/unassigned pairs → repair/confirm → publish | Conservative separators/columns only; ambiguous pairing not guessed; temporary source cleanup. | 10–11 |
| Build External AI choice quiz | External AI Builder → Choice → configure → copy prompt/use external tool → paste JSON → validate/review/confirm → publish | No DLMS provider API; returned JSON untrusted; explicit correctness review. | 12 |
| Build External AI matching quiz | External AI Builder → Matching/Terminology → configure → external prompt → paste JSON → validate/repair/confirm pairs → publish | Reuses canonical matching structure and Review & Repair; distinct from ZIP packs. | 12 |
| Ask an external AI for explanation | Enable/configure helper → supported question/result → copy/open provider → evaluate response yourself | User-controlled clipboard/browser handoff; response does not alter saved correctness automatically. | 12, 16 |
| Build/install AI Study Pack | Study Packs → AI Builder → choose domain/content → copy prompt/use external tool → return ZIP → upload → validation review → confirm install | Archive workflow, not structured text; strict Content Pack validation; no direct API. | 12–13 |
| Study an installed pack | Study Packs/subject space → choose pack/dataset → configure count/direction/activity → generate/start | Installed source unchanged; generated quiz records source-pack provenance. | 13 |
| Import/manage Content Pack | Content Packs → upload ZIP → inspect errors/warnings/content → confirm → detail/export/delete if allowed | Atomic install; protected packs; deleting pack preserves existing quizzes/history and required quiz-owned media. | 13 |
| Create image/hotspot study material | Image Study Builder → upload rights-cleared image → add choice/matching/hotspot → define target with pointer/keyboard → validate/save → generate quiz | Source credit; bounded files; keyboard authoring; source image retained during editor prep. | 11, 13 |
| Repair image/hotspot data | System Tools/Image Study Editor → select pack/dataset → Clickable Regions or Image Prep → undo/test/save | Derived overlays/regions only; accessible keyboard cursor; no general photo editing claim. | 11 |
| Create a Law Case Review | Law Study → Create → configure/copy external prompt → paste/save packet → preview headings → create review → brief/Socratic/IRAC/rules/notes/export | Raw Saved Import preserves source; Case Review is separate structured content; external AI remains outside DLMS. | 13 |
| Export Anki deck | Anki Tools or supported quiz/history/Law action → select/filter cards → preview → download `.apkg` | All selected cards export even if preview is limited; Anki app is external. | 14 |
| Build custom/printable deck | Anki Tools → Custom Deck → select cards/name → preview/export or printable view → choose flip/print | Quiz content supplies cards; source quiz/history unchanged. | 14 |
| Compose Mixed Quiz | Library Tools → Mix Questions → filters → select across at least two sources → preview/title → create | Duplicate source candidates collapsed; explicit lineage; source quizzes unchanged; Mixed Quiz remains curated/distinct. | 5 |
| Review duplicates | Library Tools → Find Duplicates → scan groups → compare source/answers → follow Edit link if desired | Advisory exact/possible labels; no automated merge/delete. | 5 |
| Export Portable Quiz Bundle | Quiz Bundles → select eligible source quizzes → export/download ZIP | No history/scores/schedules; source unchanged; generated quiz types excluded. | 15 |
| Import Portable Quiz Bundle | Quiz Bundles → upload → validation preview → inspect renames/media → confirm/cancel | Strict archive checks; no silent overwrite/merge; new local IDs; rollback on failure. | 15 |
| Create backup | Settings → Backup & Restore → Create/Download → store safely outside app data | Contains private persistent state; excludes transients/old backups. | 17 |
| Restore backup | Backup & Restore → upload → validate/review → confirm → safety backup/apply → reload | Existing state is replaced only after validation/confirmation; cleanup recoverable; browser recovery cleared. | 17 |
| Rebuild quiz pages | Settings → System Tools → read occasional-use guidance → confirm → inspect counts | Regenerates derived HTML/JSON only; canonical content/identity/history/organization/provenance unchanged; per-quiz failures preserve prior artifacts. | 17 |
| Reset selected data | Settings → Reset & Remove → choose exact scope → read preservation/removal details → confirm | Several scopes have different safety backups; never treat them as interchangeable. | 17 |
| Permanently remove DLMS data | Reset & Remove → export external backup if wanted → type confirmation → remove/shutdown | Deletes application-data directory including in-place backups, not executable; no automatic recovery. | 17 |
| Shut down local DLMS | Global Shutdown DLMS in loopback mode | Immediate recommended stop; optional last-browser auto shutdown may apply after grace period. | 16, 18 |
| Operate as LAN/server | Start with explicit non-loopback host → access from trusted clients → stop on host system | Shared server data but per-client recovery; no auth/TLS; browser/API shutdown and auto shutdown disabled. | 16, platform appendix |

## Documentation Audit Findings

Findings are documentation inputs, not changes to application behavior.

| ID | Finding | Evidence / impact | Phase 2 treatment |
| --- | --- | --- | --- |
| DAF-01 | Existing LAN shutdown guidance conflicts with enforced behavior; the contract is now verified. | The runtime/UI/server disable browser/API shutdown in explicit LAN mode; `POST /api/shutdown` returns 403; browser-presence shutdown is unavailable; and closing clients does not stop the server. Runtime mode comes from the configured bind, not the requesting address. `templates/settings/lifecycle.html` says “Manual shutdown remains available,” while `static/help-getting-started.html` and generic prose can imply that the in-app control still works. | State that users must stop the process/service from the host computer, such as through the terminal, service manager, or process manager that started it. Avoid the ambiguous standalone phrase “manual shutdown.” Propose the existing Help correction separately. |
| DAF-02 | Browser-local recovery versus server-shared recommendations is easy to misunderstand. | `Unfinished`/Resume comes from local storage and is marked `This browser`; due counts, concept state, history, and completed learning activity are server-derived. Two clients can correctly differ only in unfinished records. | Explain this boundary in first-use, Today’s Review, recovery, troubleshooting, and LAN sections; use one teaching screenshot. |
| DAF-03 | Review vocabulary still has historical overlap. | “Spaced Review,” native scheduling, Due Questions, Topic Retention Schedule, Smart Review, and Adaptive Study coexist in code/history. Current Help converges much of the wording but old terms remain in implementation and some route concepts. | Use Today’s Review as default; consistently define Due Questions (question level) and Topic Retention Schedule (concept level); glossary cross-links the others. |
| DAF-04 | Study Packs and Content Packs are two user-visible views of related content and are not self-explanatory. | Learners browse Study Packs; management validates/installs/exports/deletes Content Packs. The AI builder asks for a Study Pack ZIP that enters Content Pack validation. | Include a concise comparison before either procedure; never use the names interchangeably. |
| DAF-05 | External AI has three distinct handoff patterns. | Structured choice JSON, structured matching JSON, and AI Study Pack ZIP are separate; explanation/Law helpers add more external prompt handoffs. | Start with the shared “DLMS does not call the provider” model, then a decision table by expected return format and destination. |
| DAF-06 | The Law landing’s future-mode labels overlap with implemented Case Review activities; the distinction is now verified. | IRAC Practice, Socratic Prep, Rule Flashcards, and Case Compare are non-interactive future previews with no standalone routes. Saved Case Reviews already provide editable IRAC work with revealable guidance, Socratic questions/responses/progress/guidance, rule material, and Law Anki export. Case Compare is not implemented. | Document the embedded Case Review activities. State that the landing cards preview possible standalone tools and are not separate available workflows. Do not describe rule material as a full native interactive flashcard mode. |
| DAF-07 | The direct Short Quiz Builder contract is verified, with one server-validation observation. | The UI starts with four rows, supports 1–26 nonblank choices, requires at least one nonblank and one marked correct choice, ignores blank unused rows, and derives single-answer versus multi-select from the number marked correct. The browser enforces the 26-choice maximum, but the POST route does not independently enforce that upper bound. | Document only the supported 1–26 UI contract. Record the missing server-side maximum as an implementation observation; do not imply that crafted submissions beyond 26 are supported. |
| DAF-08 | Existing Help assets are broad but not automatically current enough for a 3.2 manual. | 47 assets cover core/3.1 and selected newer flows; Today’s Review, current Smart Views, matching External AI, portable bundles, and current recovery/LAN states lack clearly verified teaching captures. | Compare each candidate against current UI only when drafting its chapter; reuse materially accurate images and capture only planned gaps. |
| DAF-09 | Older `docs/screenshots/` images have unclear current manual purpose. | SS1/SS2 and Anki images exist outside the versioned Help set and predate the new manual architecture. | Do not reuse until provenance, current accuracy, and license/privacy safety are confirmed. |
| DAF-10 | Generated sessions are persistent Library records but there is no archive/automatic cleanup lifecycle. | Generated Practice Smart View and badges reduce clutter; users may hide or ignore quizzes, and Mixed Quiz stays distinct. No auto-delete is intentional. | Explain visibility and safe organization without promising archive/cleanup. Treat lifecycle enhancement as future product work, not missing manual behavior. |
| DAF-11 | Rebuild All Quiz Pages could be mistaken for routine upgrade work. | Current System Tools/Help explicitly says it is occasional and normally unnecessary after an update; its preservation contract is unusually important. | Repeat the “not normally required” guidance and exact non-effects in the maintenance procedure. |
| DAF-12 | Source-mode OCR and packaged OCR have different setup expectations. | Official packages bundle validated OCR resources; source users need local Tesseract/PDFium-compatible dependencies. Selectable text still works without OCR. | Keep ordinary installation simple; put source OCR setup in an optional note/link and defer bundle-build internals to maintainer docs. |
| DAF-13 | Platform signing status can look like a product failure. | Current packaged release instructions anticipate Windows SmartScreen and macOS Gatekeeper because artifacts are unsigned/unnotarized. | Explain the current warning and safe source/release verification without overstating trust; update if signing changes. |
| DAF-14 | Exact limits are numerous and can overwhelm workflows. | PDF, screenshots, bundles, backups, packs, text, timers, pairs, and counts each have validated bounds. | Put task-critical bounds next to the upload step; consolidate the full table in Feature/Format Reference. |
| DAF-15 | Learning Intelligence can imply more precision than sparse evidence supports unless explained. | Mastery caps, `Not enough data`, recent windows, and Trend minimums deliberately constrain claims. | Lead with plain-language four-factor Mastery, then subordinate exact formulas and explain why sparse evidence is capped. |
| DAF-16 | Generated-copy identity is important but implementation terminology is not user friendly. | Explicit lineage and generated metadata now make analytics/review/scheduling coherent; legacy fallback is conservative. | Explain the benefit (“practice answers count toward the source”) without exposing UIDs, contracts, fingerprints, or naming-prefix fallbacks. |
| DAF-17 | Export formats can be confused; TSV exposure is now verified. | Human-readable text, `.apkg`, legacy TSV, Portable Quiz Bundle, Content/Study Pack ZIP, and full Backup ZIP serve different purposes and preserve different data. The two TSV compatibility endpoints export quiz-choice or selected missed-question data, but no current guided Anki Tools, quiz runtime, History Review, or Help control links to them. The individual-quiz text export action is visible on every quiz card and writes `Import compatible: Yes`, although its serializer represents classic question text, A–Z choices, and answers rather than matching pairs, hotspots, images, concepts, or other rich quiz data. | Add a “Which export should I use?” table in Chapters 14–17. Present `.apkg` and printable cards as ordinary Anki workflows. Describe individual text export only for compatible classic choice content and direct rich quiz transfer to Portable Quiz Bundles. If TSV is mentioned, place it in an Advanced/Legacy Compatibility note; do not teach the missed-question POST endpoint as a normal workflow. |
| DAF-18 | Destructive settings require more than a generic reset explanation. | Clear history, reset intelligence, reset library/results, clear source content, fresh state, and permanent removal have materially different scopes/backups. | Give each action a preservation/removal table and keep typed confirmation prominent. |
| DAF-19 | Some advanced pages are reachable but should not dominate a beginner path. | Diagnostics, regex tools, source metadata, image masks/hotspot geometry, and Content Pack management are powerful secondary workflows. | Use progressive disclosure: quick-start links first, advanced/reference sections later. |
| DAF-20 | The stable-release boundary must remain explicit during manual drafting. | Current source/version is 3.2.0 on a development branch; repository text may still correctly refer to 3.1.0 as the latest published release or historical baseline. | Label this manual source as documenting 3.2.0 behavior without claiming publication until the release exists. Preserve historical references. |
| DAF-21 | No roadmap IDs were found in rendered user-facing copy during the audit scan. | `DLMS-###` strings under `static/` occur in CSS comments, not visible labels. Internal generation kinds and identity names likewise should not leak into manual prose. | Preserve the clean product-language boundary; use feature names from `TERMINOLOGY.md`. |
| DAF-22 | Existing Adaptive Study descriptions overstate the current signal set. | The current selector ranks weak/developing concepts, topic review timing, recent misses, low recent accuracy, recency/unseen material, prior exposure, and source/concept diversity. It does not read a confidence field, although current Help says “available confidence.” | Document only the implemented signals. Propose correcting the existing Help wording separately; do not imply a confidence-based ranking. |

## Second-pass completeness cross-check

### Blueprint/route-to-inventory reconciliation

| Route or composition family inspected | User-visible surface accounted for | Inventory location | Omission/clarification result |
| --- | --- | --- | --- |
| Application/core/dashboard/runtime | Dashboard, generated quiz/media serving, runtime configuration, shutdown | Areas 1, 6, 17–18; screen/workflow maps | Asset/API routes intentionally not separate screens |
| Quiz authoring | Build hub, file/paste/manual/CSV builders, parsing failure/preview | Areas 2–3 | User-facing choice contract resolved; server-limit observation retained in DAF-07 |
| Quiz editor/dependencies | Edit/delete/content dependencies and safe artifact regeneration | Area 3 | Destructive dependency details kept task-level, not internal |
| Quiz Library | Folders, order, visibility, search, Smart Views, generated labels | Area 4 | Browser-local Unfinished explicitly covered |
| Quiz composition | Mixed Quiz selection and source lineage | Area 5 | Generated source recursion/exact collapsing covered |
| Quiz duplicates | Advisory exact/near scan and source edit link | Area 5 | No mutation actions accurately stated |
| Quiz bundles | Export selection, safe archive, staged import/collision/rollback | Area 5 | Personal data exclusion and portability covered |
| Learning routes/services | Profile, topics, Mastery/Trend, diagnostics, review generation, schedule | Areas 7–9 | Terminology distinctions captured in glossary/DAF-03 |
| History/attempts | History, result review, Analytics, misses | Areas 6 and 10 | Server/history versus browser recovery covered |
| PDF import and banks | Selectable extraction, Smart PDF, review, banks, OCR offers | Areas 11–12 | Parser internals reduced to user-visible behavior |
| OCR matching | Image/scanned PDF input, conservative pairs, shared repair | Area 12–13 | Temporary retention and ambiguity covered |
| External AI | Choice/matching prompt/paste/staging/review/publication | Area 14 | ZIP pack and explanation paths explicitly separated |
| Study Packs | Catalog, AI builder, image builder, generated activity | Areas 13–15 | Browser-local expansion state covered |
| Content Packs | Import review/install/detail/export/delete/protection | Area 15 | Maintainer format internals omitted intentionally |
| IT and Medical | Subject aggregation, matching/images/AI entry points | Area 15 | No independent duplicated persistence implied |
| Law | Prompt/import/archive/case detail/IRAC/Socratic/rules/notes/export/Anki | Areas 15–16 | Embedded activities versus standalone future previews resolved in DAF-06 |
| Admin image editor | Clickable Regions, Image Prep, keyboard authoring | Area 13 | Spatial accessibility limitation noted |
| Anki | Quiz/missed/custom/Law package exports and printable cards | Area 16 | Legacy TSV verified as unlinked compatibility endpoints |
| Settings | Appearance, navigation, AI, parsing, lifecycle, backup, reset, tools | Area 17 | Each settings family included |
| Maintenance | Restore staging, rebuild, scoped resets/removal | Area 17 | API mechanics omitted; user outcomes included |
| Help | Topic index, contextual/specialized help, assets | Area 18/current-state section | Existing conflicts and missing 3.2 captures recorded |

### Template, JavaScript, service, form, and test reconciliation

- Every HTML template and static user-facing HTML page was grouped into the
  screen map. Shared fragments/macros were checked for navigation, labels,
  confirmation, status, and settings-shell behavior rather than listed as
  independent screens.
- JavaScript-driven behavior was explicitly accounted for in quiz runtime and
  recovery, Today’s Review client merge, Library Smart Views/local unfinished
  results, PDF/External AI repair, question review, settings navigation,
  hotspot authoring, and status/live-region behavior.
- Major services were traced to their user-visible consumers: publication and
  rendering, registry/folders, identity/generated classification, attempts and
  history, daily review, concept/adaptive/scheduling intelligence, duplicate
  analysis, composition, bundles, PDF/OCR, packs, Anki, backup/restore, and
  maintenance.
- Form limits and server validation were checked at the relevant route/service
  boundary. Limits are recorded where a user must act on them; internal storage
  constants that do not change a task are not manual features.
- Tests were used to resolve state-dependent behavior that markup alone cannot
  establish: completion/save acknowledgement, recovery isolation, identity
  attribution, exact/near duplicate separation, atomic publication/import,
  archive safety, schedule intervals, Mastery/Trend evidence bounds,
  cross-theme/responsive/accessibility contracts, and shutdown enforcement.
- Existing Help was compared with implementation rather than treated as
  authoritative. Conflicts and likely stale screenshots are recorded in
  DAF-01 through DAF-22 and `SCREENSHOT_PLAN.md`.

## Audit coverage matrix

| Product-surface category | Audited | Represented in inventory | Proposed manual location | Screenshot considered | Unresolved clarification |
| --- | --- | --- | --- | --- | --- |
| Primary navigation destinations | Yes | Dashboard, Library, Build, History, Learning, Packs, optional subjects, Anki, Settings, Help | Ch. 3 plus destination chapters | UM-01–03 and selected destinations | None affecting structure |
| Secondary navigation and Library Tools | Yes | Smart Views, folders, Mixed Quiz, duplicates, bundles, editors, management | Ch. 5, 13–17 | UM-03–06, UM-22–27 | None; future Law cards are not current workflows |
| Major user-facing routes/pages | Yes | Grouped in 81 screen-map rows rather than raw endpoints | All chapters | Selective 27-image plan | No documentation ambiguity; server-limit observation remains DAF-07 |
| Major modal/dialog workflows | Yes | Mastery, recovery, confirmations, OCR offer, import/restore reviews, status/error states | Ch. 6, 8, 10, 15, 17–18 | UM-09, 12, 16–18, 20, 26–27 | None; existing non-manual LAN copy conflict remains DAF-01 |
| Quiz-taking workflows | Yes | Study, Exam, question types, results, save failure, recovery | Ch. 6 and 9 | UM-07–09, 14, 19 | No material omission found |
| Review/study workflows | Yes | Today’s Review, Adaptive, Smart, Concept, Due, Topic Retention, misses | Ch. 7–8 | UM-01, 10–12 | Historical naming only (DAF-03) |
| Import/content-acquisition workflows | Yes | Text/paste/CSV, PDF/OCR, External AI, packs, Law packet, image builder | Ch. 4, 10–13 | UM-02, 15–23 | Optional OCR setup distinction (DAF-12) |
| Library/organization workflows | Yes | Visibility, folders/order/search, Smart Views, generated practice, mix, duplicates, bundles | Ch. 5 and 15 | UM-03–06 | Generated lifecycle is intentionally absent (DAF-10) |
| Learning/history workflows | Yes | Profile, concepts, Mastery/Trend, diagnostics, schedules, History/Analytics | Ch. 7–9 | UM-10–14 | Sparse-evidence explanation required (DAF-15) |
| Matching/image/hotspot workflows | Yes | Manual/CSV/bank/OCR/AI matching; image builder/editor; quiz keyboard operation | Ch. 10–13 | UM-18–19 | Manual assistive-tech review remains prudent |
| Study/Content Pack and subject workflows | Yes | Catalog, management, AI ZIP, images, IT/Medical/Other, Law | Ch. 12–13 | UM-21–23 | None; pack naming and the verified future-preview distinction need careful prose |
| Anki/external-study workflows | Yes | `.apkg`, custom/missed/Law decks, printable cards, legacy TSV compatibility | Ch. 14 | UM-24 | None; TSV is not linked from current guided UI |
| Maintenance/data-management workflows | Yes | Backup/restore, scoped resets, fresh state/removal, rebuild, shutdown | Ch. 17–18 | UM-26–27 | None for manual drafting; existing non-manual copy correction remains DAF-01 |
| Settings/runtime workflows | Yes | Appearance, navigation, AI, parsing, lifecycle, local/LAN modes | Ch. 16 and appendix | UM-25 | None for manual drafting; existing Help correction needs separate approval |
| Platform/runtime differences | Yes | Six target packages, data locations, signing warnings, packaged/source OCR, loopback/LAN | Ch. 2, 16, appendix | UM-25 only where instructive | Per-target release UAT remains external evidence |
| Errors/warnings/confirmations | Yes | Parse/request errors, incomplete repair, staged reviews, destructive confirmations, failure preservation | Within task chapters + Ch. 18/reference | Consequential examples only | No material omission found |
| Help and existing documentation/assets | Yes | Help topics/special pages, README/release guide, 47 assets, maintainer boundary | Ch. 3; manual maintenance architecture | All candidates assessed later | Asset currency must be checked per chapter |

**Coverage result:** all registered user-facing blueprint families, page/template
families, major JavaScript workflows, and service-backed product domains found
in the second pass map to at least one inventory entry and proposed manual
location. The four focused behavior clarifications are resolved. Remaining
findings concern known implementation observations, future screenshot currency,
or existing non-manual documentation that requires separately approved work—not
unresolved Phase 1 product behavior. This inventory is sufficiently complete to
begin Phase 2 drafting after owner review of the findings and terminology.

Related Phase 1 artifacts: [manual architecture](README.md),
[terminology audit](TERMINOLOGY.md), and
[screenshot plan](SCREENSHOT_PLAN.md).
