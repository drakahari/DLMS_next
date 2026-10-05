# Marked questions: implementation and compatibility assessment

## Current integration

This batch follows the owner's approved scope on `aa53bf0` (pypdf 6.19.0).
It adds review intent to the existing Study, Anki and generated-practice services.
It does not add a scheduler, change plan selection or record learning evidence
when a question is marked, exported or used to create practice.

- Study's **Mark for review** saves to the profile database. **Marked questions**
  opens the current quiz's marks; Quiz Library also links to the all-quizzes view.
  The list is paginated in groups of 25. A live selection check shows exact
  practice and Anki included/excluded counts and reasons across all selected pages.
  An action requires an eligible whole selection; it never drops excluded questions.
  Selections persist across pages in the
  same tab. Opening the list never changes marks.
- **Export to Anki** and **Start focused quiz** are independent actions. Neither
  removes marks. Individual and selected bulk unmarking are explicit and confirmed.
- `dlms/services/review_marks.py` validates source identity, question revision,
  current files, Learning Scope and eligibility. `dlms/routes/review_marks.py`
  reuses `_publish_quiz` and the existing APKG exporter through injected dependencies.
- `marked_practice` is an explicit transient generated kind. Existing Study
  sessions classify it as focused. Its completion covers its selected set;
  it never finishes a whole source quiz or replaces Last regular quiz.
- Publishing uses the existing transaction, file staging, assets, registry and
  crash-recovery journal. A separate durable request receipt prevents repeated
  clicks, simultaneous requests and lost acknowledgements from publishing twice.
  The same request ID with changed inputs is rejected. Confirmed rollback permits
  the same request to retry; uncertain work remains blocked with recovery guidance.

## Identity and eligibility

A mark belongs to a source question UID and exact question assessment revision.
For direct hotspot review, the marks-only revision also hashes the verified
playable target assessment: existing question storage does not retain hotspot
target geometry. This does not alter Study revisions or scoring. Generated
hotspots retain their own copy instead of guessing a source target revision.
Quiz title/folder changes show current context without changing the mark.
Generated marks use an unambiguous direct or canonical source with an equal revision.
If that cannot be verified, a new mark retains only the exact generated copy.
It is unavailable for source-focused practice; supported Anki export and direct
quiz review remain independent. A legacy transfer still requires verified source
lineage and is rejected without clearing its browser record when ambiguous.
There is no source guessing by question text. A legacy source receives only an
explicit question UID when directly marked; its existing canonical learning
identity is not rewritten as part of marking.

Edited/deleted questions remain visible as unavailable marks. Open the source
and mark its current question separately; no revised question is silently used.
Quiz-page fingerprints and current runtime/DB assessment checks protect browser
transfers from reordered or revised content. Unrelated identical text does not
merge learning identities. If a practice selection contains fully identical
assessments from different sources, generation asks the learner to select one
source instead of silently dropping a mark or awarding credit to both.

Supported workflows:

| Question | Durable mark | Focused practice | Anki |
| --- | --- | --- | --- |
| Text choice, including multiple answers | Yes | Yes | Yes |
| Text matching | Yes | Yes, existing round rules | No converter in this batch |
| Image or hotspot | Yes when source is verifiable | Direct source review only | No converter in this batch |
| Revised/deleted source | Existing mark retained | Unavailable | Unavailable |
| Generated copy without verified source lineage | Exact copy retained | Direct quiz review only | Text choice only, when unchanged and available |

Media questions remain outside marked generation because asset copying can
change the assessment revision. Faithful media-aware revision equivalence would
need a separate reviewed change; this batch does not weaken the Study revision
boundary. The screen explains limitations per action. Unsupported selections
are rejected as a whole, with no silent skipping or truncation. Large supported
selections are published exactly as selected. Learning Scope exclusions block
focused generation, but preserve marks, direct source access and supported Anki
export. No mark is converted into a missed-answer signal.

## Browser compatibility

Older recovery checkpoints may contain `view.ankiQuestionIndexes`. After
resuming the matching page, **Save previous browser marks to DLMS** offers an
explicit transfer. The fingerprint, ordered assessment and server revision must
match. Failed requests retain the original recovery data and a separate pending
request; acknowledged transfers do not clear Study responses.

Stale rejected requests may be retained separately while reloading current
marks. They are never automatically mapped onto a different revision. Expired
or already-cleared local records cannot be reconstructed. Older self-contained
HTML may retain its old Anki controls until manually regenerated. Shared-script
pages use the new controls when reloaded and verifiable. Personal quizzes are
never regenerated by this batch.

## Persistence and recovery contract

Schema 6 additively creates `review_marks`, `review_mark_state` and
`review_mark_actions`. Marks retain source context without cascading deletion.
An optimistic list revision prevents stale unmark/selection writes. Durable
request hashes and acknowledgements make retries idempotent. Stored times are
UTC and displayed through the existing browser-local formatter.

SQLite portable backups include marks and receipts. Old backups acquire empty
additive tables; historical intent, completion or assistance is not invented.
Restore follows the backup snapshot and rotates the mark generation so old
browser queues cannot replay into restored data. Imported state is validated
before replacing live data. Older binaries reject the newer database schema;
use an appropriate pre-upgrade backup if reverting to an older binary.

Learning Intelligence reset and explicit Study-history deletion retain marks.
Library deletion leaves unavailable marks and rotates mark request credentials.
Full-data removal retains the existing ownership/backup safeguards. All migration,
restore, deletion and failure tests use disposable copies.

## Practical rollback to the previous build

Changing the executable alone does **not** downgrade the database. Schema 6 is
refused by a schema-5 build before it can use or migrate the database.

1. Before upgrading, use **Settings → Backup & Restore → Create & Download Backup** and
   save the portable ZIP outside the active data directory. Record the build
   that created it. A schema-6 backup is not a rollback backup for schema 5.
2. If rollback is needed, stop DLMS normally. Keep the upgraded data directory
   intact and retain a complete offline copy, including its configuration,
   quiz files/assets and database. New marks and work since the older backup
   remain in that archive; they will not appear in the older restored snapshot.
3. Start the previous trusted build with a **new, empty data directory**, using
   its supported `QUIZAPP_DATA_DIR` setting. Do not point it at the upgraded
   directory. For example on Linux, set `QUIZAPP_DATA_DIR` to an absolute empty
   recovery-folder path when launching the previous executable. Preserve that
   setting for subsequent launches of the recovered installation.
4. In that separate installation, open **Settings → Backup & Restore**, choose
   the verified pre-upgrade ZIP, select **Validate Backup & Continue**, review
   its date/content report, then **Restore This Backup**. Use a backup compatible
   with that older build; do not restore a schema-6 ZIP into it.
5. Reload tabs as instructed and verify your quizzes, settings and Study history
   in the recovered installation. Keep the upgraded archive and both backups
   until satisfied. Retain any newer work separately; rollback is snapshot
   recovery, not an automatic merge.

Do not edit `schema_meta`, delete new tables to force compatibility, or replace
only `results.db` while leaving a different registry/assets set. If a previous
build cannot start even against a separate empty directory, stop and diagnose
that failure; do not overwrite the upgraded workspace. These are owner-operated
recovery instructions. This review exercises only disposable copies.

## Plan presentation integration

Study-material changes are grouped by quiz ID, including same-title quizzes.
At most 10 groups and 20 question changes per group are rendered per page;
every change remains reachable. Exact summary counts remain visible beside
**Mark these changes as seen**. The submitted snapshot digest is checked under
the registry lock and database write transaction. Concurrent changes reject the
acknowledgement; no review credit is ever awarded for acknowledging a summary.

The learner guide and forms use **Study days** and **Minutes you plan to study on
each selected day**. Scheduling, evidence ranking, reset boundaries and selected
plan behavior are unchanged.

## Validation and screenshots

Focused tests live in `tests/test_review_marks.py`, `tests/test_exam_plans.py`
and the enabled Firefox critical workflows. They cover identity, actual package
contents, exact large selections, source changes, retries, migration rollback,
reset boundaries, pagination, stale acknowledgement and the existing Study rules.
See the batch's retained validation report for final gate counts and hashes.

To refresh affected Help screenshots, use isolated browser fixtures and set
`DLMS_PREBUILD_CAPTURE_DIR`, `DLMS_EXAM_PLAN_CAPTURE_DIR` and
`DLMS_PRESENTATION_CAPTURE_DIR` to a temporary output directory. Run the marked
questions, plan setup, no-work and selected-breakdown Firefox cases. Inspect the
Light captures and copy only the reviewed WebP crops into `static/help_assets`.
Full desktop/narrow Light, Dark and Ethereal captures remain review evidence.
Use existing `capture_control` crops, concise captions, meaningful alt text and
Help's keyboard-accessible enlargement; do not replace written steps with images.
