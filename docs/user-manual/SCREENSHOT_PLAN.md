# DLMS 3.2.0 user-manual screenshot plan

This is a selective teaching plan, not a screenshot checklist for every route.
No images were captured or modified during Phase 1. Before reuse, every existing
Help asset must be compared with the current 3.2.0 screen at the target viewport.

## Capture standard

- Use neutral, repository-safe demonstration data created for documentation.
  Never show personal documents, real study history, local paths, hostnames,
  network addresses, usernames, browser profiles, or third-party account data.
- Prefer a consistent desktop viewport that includes enough navigation for
  orientation. Use a focused crop only when it makes a dense workflow legible.
- Capture the Light theme by default. Add a second theme only when the theme or
  contrast behavior is itself being taught; four-theme duplication has little
  teaching value.
- Use callouts sparingly and keep an unannotated source capture. Annotations
  should identify decisions or sequences, not restate every visible label.
- Avoid transient dates, exact attempt counts, and rapidly changing status data
  unless the screenshot teaches that state.
- Record the DLMS version, viewport, theme, fixture version, and capture route in
  image metadata or a sidecar manifest when capture begins.
- Recheck every planned image at release time. A screenshot is retained when it
  remains materially accurate even if cosmetic details changed.

## Priority screenshots

| ID | Manual chapter / section | Screen or workflow and required state | Exact teaching focus / suggested callouts | Safe demo data and privacy controls | Framing / themes | Existing Help asset candidate | Teaching value / staleness |
| --- | --- | --- | --- | --- | --- | --- | --- |
| UM-01 | 2. Installation; 3. Navigation | Dashboard after first meaningful use, with Today’s Review populated | Primary navigation; “start here” Today’s Review; server-derived action versus a `This browser` Resume item; Quick Access | Three neutral quizzes, one due source question, one weak concept, one deliberately interrupted local checkpoint; no real history | Full window; Light only | `dashboard.webp` may provide orientation but must be checked for the 3.2 Today’s Review panel | Essential mental model; high staleness because recommendations evolve |
| UM-02 | 4. Creating/importing | Build Quiz hub | Distinguish manual, text/paste, PDF/Image, matching CSV, and External AI paths | No uploads or local filenames visible | Focused full content area; Light | `build_quiz.webp` is a likely reusable candidate | High value, moderate staleness |
| UM-03 | 5. Library organization | Quiz Library with one folder, active Generated Practice Smart View, badges, search, and Library Tools | Folder versus Smart View; active filter; Generated Practice badge; Mixed Quiz distinction; return to full library | Neutral quizzes and generated sessions only; use non-branded topics | Full window; Light, with narrow layout separately tested but not necessarily published | No verified current asset; `dashboard.webp` is not a substitute | Essential for 3.2; high staleness |
| UM-04 | 5. Mixed Quiz | Mixed Quiz Builder after filters are applied and questions from two sources selected | Source/folder/concept/missed filters; provenance; selected total; title and create action | Two small synthetic source quizzes with repeated neutral concepts | Focused content area; Light | None | High value; moderate staleness |
| UM-05 | 5. Duplicate review | Duplicate Question Review containing one exact pair and one possible pair | Exact versus possible; source quiz/question context; advisory-only nature; Edit source link | Purpose-written synthetic questions; no copied material | Focused content area; Light | None | Useful for a non-obvious workflow; low-to-moderate staleness |
| UM-06 | 5/15. Portable bundles | Quiz Bundles screen with export selection and a validated import preview | Selected source quizzes; bundle scope; preview, rename notice, confirm/cancel; distinction from Study Packs/backups | Two neutral quizzes, one harmless local image, one intentional title collision | Two focused captures may be clearer than one; Light | None | High value; moderate staleness |
| UM-07 | 6. Taking quizzes | Choice quiz in Study Mode after an incorrect response has been saved | Immediate feedback, correct-answer indication, explanation, question navigation, Anki selection if visible | Four neutral questions; no vendor material | Focused quiz area; Light | `quiz_study_mode_incorrect.webp` and `quiz_study_mode_correct.webp` are candidates | Essential; medium staleness |
| UM-08 | 6. Taking quizzes | Exam Mode with timer, several answered/unanswered states, and submit action | Timer/pause; previous/next; completion status; final submission; no immediate correctness | Neutral quiz; timer set to an obvious demo value | Focused quiz area; Light | `quiz_exam_mode.webp` is a candidate | Essential; medium staleness |
| UM-09 | 6. Recovery | Recovery panel for a genuinely interrupted quiz | Resume primary action; Start Over secondary action; browser-local explanation; saved progress summary | Synthetic quiz interrupted before completion | Focused panel; Light; optionally Dark to demonstrate action clarity only if needed | No dedicated candidate | High value for safety; moderate staleness |
| UM-10 | 7. Review choices | Learning Intelligence/Help summary or a composed visual showing the existing review entry points | Today’s Review default; concise differentiation of Adaptive, Smart, Concept, Due Questions, Topic Retention, and missed-question review | Neutral learning history with just enough evidence for each action | Prefer one focused existing UI region plus prose rather than a collage; Light | None alone covers the relationship | Very high value; should avoid UI collage that ages quickly |
| UM-11 | 7. Review Schedule | Review Schedule with Due Questions and Topic Retention sections both populated | Question-level due states and batch selector; concept-level retention timing; direct start actions | Synthetic history creating overdue, due, upcoming, and retained topics | Full content area; Light | `learning-review-schedule.webp` is a likely candidate | Essential distinction; medium staleness |
| UM-12 | 8. Learning Intelligence | Topic table plus open “How DLMS calculates mastery” dialog | Mastery versus Trend; recent accuracy; evidence; `Not enough data`; Practice action | Concepts representing insufficient, weak, improving, stable, and strong states without sensitive scores | Focused table/dialog; Light | `learning-topics.webp` may cover table but current dialog needs a new capture | Essential; high staleness |
| UM-13 | 8. Diagnostics | Learning Diagnostics with one repeated confusion and one question-quality signal | Advisory status, filters, evidence/context, follow-up action | Synthetic repeated wrong choice; no medical/legal/personal subject content | Focused content area; Light | `learning-diagnostics-confusions.webp` and `learning-question-quality.webp` are candidates | Useful advanced explanation; medium staleness |
| UM-14 | 9. History | History list and one attempt-review result | Filters, score/time, opening a completed result, missed-question and Anki actions | Several synthetic attempts with varied outcomes | Two focused captures if needed; Light | `history.webp` and `analytics.webp` are candidates | High value; low-to-medium staleness |
| UM-15 | 10. Smart PDF | PDF & Image Import start screen with a selectable-text question-bank PDF chosen | Source-rights confirmation; type choice/auto-detect; title/timer; OCR availability note | Generate a public-safe neutral documentation PDF; never use private manuals/test PDFs | Full content area; Light | `pdf_import.webp` and public-safe cloud sample assets are candidates | Essential; medium staleness |
| UM-16 | 10. Review & Repair | Question-bank Review & Repair containing complete, review, incomplete, and unassigned records | Status filters; editable choices/mode/correctness; exclude; unassigned diagnostic text; confirmation | Synthetic parser fixture with invented neutral text, including a fill-in/incomplete record | Focused content area; Light | `sample_cloud_questions_smart_pdf_review-repair.webp` is a candidate | Essential safety workflow; high staleness |
| UM-17 | 10. Screenshot/scanned OCR | OCR source selection or low-text PDF candidate-page offer | Image count/page selection; local OCR; continue-without-OCR/cancel; limits and temporary processing | Synthetic screenshots with neutral A–D questions; no screen capture of third-party content | Focused dialog/page; Light | No single verified asset | High value for optional path; high staleness |
| UM-18 | 10/11. OCR terminology | OCR-assisted matching Review & Repair with paired and unassigned material | Pair editing/reordering; ambiguous text retained; confirm every final pairing; publication | Two synthetic terminology images using em dash/colon/two-column examples | Focused content area; Light | Existing terminology PDF review asset may not represent OCR-specific state | High value; moderate staleness |
| UM-19 | 11. Images/hotspots | Image Study Editor in Clickable Regions mode with keyboard cursor and a polygon under construction | Mode choice; accessible image focus; arrow keys; Enter/Space; undo/clear/test/save | Original diagram created solely for documentation, with no logos or private data | Focused editor; Light; optional forced-colors capture belongs in accessibility docs, not main manual | `image_study_editor.webp` is a candidate but keyboard state likely needs recapture | High teaching value; high staleness |
| UM-20 | 12. External AI | External AI Builder with Matching/Terminology selected, followed by validated Review & Repair | Provider-neutral prompt generation; copy/open provider; paste JSON; untrusted validation; no API | Neutral topic and entirely synthetic response; redact browser/provider identity | Two focused captures; Light | No current matching-specific candidate; `ai_study_pack_builder.webp` is a different workflow | Essential distinction; moderate staleness |
| UM-21 | 12/13. AI Study Pack | AI Study Pack Builder showing selected content options and ZIP-return instruction | Explicitly distinguish this ZIP workflow from the structured-text External AI Builder; validation/install handoff | Neutral general-study topic; no live provider account | Focused content area; Light | `ai_study_pack_builder.webp` and `ai-builder-zip-return.webp` are candidates | High value because workflows are easy to confuse; moderate staleness |
| UM-22 | 13. Packs | Study Packs catalog plus Content Pack import-validation review | Learner catalog/filter/configure/generate versus management/validate/install; warning confirmation | One public-safe synthetic pack with matching and image datasets | Two focused captures; Light | `study_packs.webp`, `study-pack-validation.webp`, and `content-packs_management.webp` are candidates | Essential distinction; medium staleness |
| UM-23 | 13. Law Study | Saved Case Review detail with brief, Socratic, IRAC, flashcards, notes, and export navigation | Guided case workflow and embedded tools; distinguish Saved Imports from Case Reviews | A public-domain or completely fictional case clearly labeled as a demo; avoid personal course data | Focused content area; Light | `law_study_main.webp`, `law-create-case.webp`, and `law-import-packet.webp` cover earlier steps, not necessarily detail | Useful specialized chapter; medium staleness |
| UM-24 | 14. Anki/decks | Custom Deck selection and printable-card preview | Quiz/missed filters; card selection; `.apkg` export; printable front/back and flip controls | Neutral question cards and a non-identifying deck name | Two focused captures; Light | `anki_tools.webp`, `anki-print-front.webp`, `anki-print-back.webp`, `anki-print-controls.webp` are candidates | High value; medium staleness |
| UM-25 | 16. Settings/runtime | Settings overview plus Lifecycle page in explicit LAN/server mode | Settings categories; disabled in-app shutdown; accessible explanation to stop on host; no authentication/TLS warning | Bind only to a safe test fixture; show no real LAN IP/hostname | Full window and focused warning; Light; optional Dark only if contrast itself is documented | Settings appearance/navigation assets exist; no verified LAN-state asset | High safety value; high staleness |
| UM-26 | 17. Backup/restore | Backup & Restore with a successfully validated restore staged for confirmation | Backup scope; choose file; review; safety backup; confirm/cancel; reload notice | Fixture backup containing synthetic data only; hide local filename/path | Focused content area; Light | `settings-backup_restore.webp` is a candidate but may not show staged review | Essential safety flow; moderate staleness |
| UM-27 | 17. Maintenance | System Tools Rebuild All Quiz Pages card and confirmation | Occasional-use guidance; derived artifacts only; exact preservation contract; success/failure counts | Synthetic library; no need to execute in the capture | Focused card/dialog; Light | `system-tools.webp` is a candidate and must be checked for current guidance | High value for avoiding misuse; low staleness |

## Screenshots deliberately not proposed

- Every error page, empty state, folder operation, theme choice, and minor modal:
  prose and focused callouts are easier to maintain.
- All four themes for every workflow: this would multiply maintenance without
  teaching the task. Theme coverage belongs in product testing, while one
  representative appearance screenshot may support the settings chapter.
- Native build, OCR bundle, frozen probe, package verifier, and release assembly
  screens: these are maintainer procedures, not end-user manual content.
- Real PDFs, personal quiz libraries, actual attempt histories, or live AI
  conversations: they create privacy, copyright, and reproducibility risk.
- Version-number-only screenshot refreshes: retain a materially accurate image
  and describe the current version in text.

## Capture sequencing

Capture only after the relevant Phase 2 chapter is stable. Establish one
versioned synthetic documentation dataset first, then capture UM-01 through
UM-27 in workflow order so later states arise naturally from earlier actions.
Record which existing Help assets were reused, replaced, or rejected. The
manual source should reference images by stable semantic names rather than by
screen order.
