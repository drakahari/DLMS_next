# Mark for review: integration proposal (not implemented)

## Feasibility and current behavior

A bounded enhancement is feasible using the existing quiz publisher, explicit
question lineage, Study sessions, Learning Scope and Anki exporter. It needs a
small durable marks store; renaming the button alone would not preserve marks
across completion, devices using the same host, or backups.

Current evidence:

- `static/script.js`: `studyAnkiSelections` stores runtime question indexes.
  `toggleCurrentQuestionForAnki` changes that set and checkpoints browser recovery;
  it emits no learning event. Export appears on the last question and calls
  `/export/anki/study`. Successful export does **not** clear the selection.
- `static/quiz-recovery.js`: `view.ankiQuestionIndexes` lives in the browser's
  versioned recovery record, with a 30-day rolling expiry and an exact quiz
  fingerprint. Start Over/new review clears selections; confirmed Finish removes
  the checkpoint. Server Study resume has no durable marks to restore. These
  browser-local marks are not included in DLMS database backups.
- `dlms/routes/anki.py:export_anki_study` and
  `app.py:_load_anki_study_export_selection` validate positive ordinal selections
  against one current quiz, load choices/correct choices and export an APKG.
  They do not validate a client's assessment revision. This selected-question
  exporter is choice-oriented; it does not assemble matching pairs or hotspot
  media/targets into faithful cards. Preserve the existing endpoint and choice
  behavior; the new screen must not silently promise equivalent export for every
  question type.
- `dlms/routes/quiz/library.py:create_mixed_quiz` and
  `dlms/services/quiz_composition.py` already provide a selectable cross-quiz
  catalog, provenance, duplicate presentation and normal publishing. Their route
  requires at least two questions from two source quizzes, so it cannot serve a
  one-question/current-quiz focused action unchanged. Its duplicate grouping uses
  normalized type/text and must not become a new learning-identity rule.
- `dlms/routes/learning.py` generation routes reuse
  `dlms/services/learning.py:_question_payload_from_db` and `_publish_quiz`, with
  asset snapshots and explicit `_lineage`. `question_identity.py` gives generated
  copies source/canonical UIDs; generated quizzes do not become source banks.
- `study_sessions.py` distinguishes focused transient practice from regular
  sessions and keeps Last regular quiz separate. `learning_scope.py` resolves
  included sources and unambiguous generated lineage from one registry/DB view.
  `restore.py` supplies existing backup/reset safeguards.

## Recommended interaction

1. Rename **Mark for Anki** / **Marked for Anki** to **Mark for review** /
   **Marked for review**, keeping a keyboard-operable pressed-state button.
   Marking is intent to revisit, never wrong-answer evidence or assistance.
2. Add one **Marked questions** screen, linked from Study and Quiz Library.
   Default to the current quiz when opened from Study; offer **All quizzes**,
   source/folder context, selection counts and concise unavailable explanations.
3. Offer independent **Export to Anki** and **Start focused quiz** actions on the
   same selection. Either or both can be used; neither clears marks. Provide
   explicit unmark controls and a separate confirmed bulk clear.
4. Publish the exact eligible selected questions as focused generated practice,
   including a one-question selection. Show an eligibility preview and excluded
   counts; never silently fill with related or unmarked questions. Zero eligible
   questions disables generation with reasons. Do not alter the existing mixed
   builder's two-source policy.
5. Use existing completion/recommendation services. Only responses create learning
   evidence. Finish covers the generated set, never the entire source quiz;
   generated practice never replaces Last regular quiz. No competing scheduler or
   automatic nagging dashboard recommendation is needed.

## Minimum persistence and identity rules

- Add one marks table via the normal additive migration: mark ID, durable source
  question UID (when resolvable), source quiz ID, marked question revision,
  creation/update UTC instants, and origin quiz/question context. Use explicit
  idempotent mark/unmark operations with CSRF and transactional uniqueness; do not
  use a non-idempotent toggle API. Preserve a tombstone/unavailable representation
  when content is deleted rather than silently repointing an ordinal.
- Store a question-level assessment digest alongside identity, reusing existing
  revision normalization. Quiz title/folder changes keep marks and current context;
  changed wording/answers require an explicit **Use current question** confirmation.
  Replaced/new UIDs stay distinct. Do not build historical question snapshots or
  claim that current content is the historical version.
- Generated marks resolve through explicit, unique, revision-compatible source
  lineage. Deduplicate repeated marks of the same source revision for practice.
  Never guess a source by matching text. Unknown/orphaned generated lineage remains
  visible but unavailable for source-focused generation until explicitly resolved.
  Do not silently map generated copies edited away from their source.
- Prevent duplicate curriculum questions in a generated selection. Reuse catalog
  presentation/provenance, but validate full assessment equivalence before grouping
  independently authored duplicates; equal text with different answers is not an
  equivalent question. Grouping a display/practice copy must not merge independent
  learning identities or silently credit multiple sources.
- Preserve recoverable old local marks through an explicit one-time adoption path:
  validate the existing fingerprint and ordered source mapping, post idempotently,
  retain the local record until acknowledgement. Do not clear responses/recovery
  as part of adoption. Expired, changed or already-cleared local selections cannot
  be reconstructed; explain that limit. Do not fabricate historical marks.

## Eligibility, compatibility and security

- Respect Learning Scope for focused generation. Show excluded marks without
  deleting them and link to scope settings. Direct source access and independent
  Anki export remain available where valid; no silent scope change. Hidden folders
  and excluded learning folders remain different concepts.
- Validate artifacts, revision, supported type, assets and lineage again on the
  server at action time. Choice/multiple-answer and matching can reuse current
  payload/publishing paths after round-size tests. Image/hotspot questions need a
  faithful artifact-aware payload check: existing DB choice surrogates are not
  automatically proof of faithful generated hotspot support. Keep unsupported
  selections marked, with per-action reasons; never invent answers/media.
- For the first batch preserve current choice Anki output. Present matching/image
  export limitations explicitly unless faithful converters are included and tested.
  Cross-quiz choice export can assemble validated rows into one package through the
  existing exporter. Fixing every historical Anki format is a separate scope choice.
- SQLite backups include durable marks. Old backups get an empty additive table;
  restore follows its saved snapshot, not a guessed merge. Rotate/reuse the restore
  generation to reject pre-restore mark queues. Validate imported tables/UIDs.
- Learning Intelligence reset and Study-history deletion retain marks: intent is
  separate from both evidence and Study facts. Explicit mark clearing is separate;
  full-data removal follows established safeguards. Source deletion leaves
  unavailable marks with safe actions until explicit clearing. Test this boundary
  with disposable pre-operation backups and restores.
- Regeneration/reordering must resolve marks by stable identity and revision, not
  displayed ordinal. Use current registry context for renamed/moved sources;
  validate links and display deleted sources as unavailable. Existing old clients
  may keep their browser-local Anki flow until reloaded/adopted.

## Coherent implementation batches and acceptance

1. **Durable intent and compatibility:** additive table, validated/idempotent API,
   stable identity/revision resolution, legacy-local adoption, backup/reset/delete
   tests. No learning events from mark/unmark/export.
2. **One readable selection screen and actions:** renamed controls, current/all
   quizzes, preserved choices, independent Anki and focused generation, supported
   type checks and provenance. Extend the generated-kind allowlist with an explicit
   marked-practice kind and corresponding transient/focused classification; use
   existing publisher, asset safety and completion APIs.
3. **Integrated validation:** repeat clicks/lost acknowledgements, concurrent tabs,
   duplicate source/generated marks, edits/moves/deletions, scope exclusions,
   partial/empty/unsupported selections, both actions in either order without
   clearing marks, old backups, restore generations and unrelated reset boundaries.
   Firefox must verify regular continuity, focused-only completion, Anki download,
   keyboard/narrow/theme readability and errors. Run both full AGENTS.md gates.

Before implementation, confirm the scope of faithful non-choice Anki export and
whether the proposed explicit handling of changed/unresolvable legacy marks is
acceptable. Recommended defaults are choice export first, no implicit remapping,
Learning Scope respected for practice, and marks retained until explicit unmark.
No Mark for review labels, storage, routes or generation behavior are changed by
this completion fix.
