# Study evidence batch: implementation and validation

Checkout: DLMS_next, `develop/3.3.0`, based on
`16dc85961605e50c40ad7f71a0ab9daf76a6b07a`. The implementation started from a clean tree. This follow-up review began with the complete 47-file uncommitted batch; it preserved that work and added two compatibility-notice files.
All changes remain unstaged and uncommitted. No personal data, running service,
application settings, release version or remote branch was changed.

## User-facing behavior

- Registered Study quizzes save a durable session, answers and position. Returning
  offers **Resume and take over**; a competing tab must explicitly reclaim the
  session. Failed saves retain a visible **Retry** action and browser queue.
- First graded outcome, later corrections, partial responses and observable tool
  actions are separate facts. A partial multiple-answer or matching selection has
  unknown correctness. Feedback already exposed can make a later correct response
  assisted. An AI-open request is not evidence that an outside answer was read.
- **Finish Review** requires complete saved coverage and a gap-free event sequence.
  Wrong or assisted answers count as reviewed. Generated focused practice covers
  its selected questions. Repeat reviews create separate sessions. Answer changes
  wait while finishing; completed sessions are immutable.
- **Study History** shows partial/finished reviews, first/latest outcomes, observable
  actions and raw legacy responses. **Last regular quiz** stays separate from
  generated practice in Today's Review. Existing recommendation reasons and actions
  remain the source of suggested work; this batch adds no separate planner.
- Learning Intelligence keeps initial difficulty. Accuracy retains actual first
  correctness; mastery performance terms and native intervals distinguish independent
  success. New independent correct Study results advance intervals only after the
  preceding interval has elapsed (1, 3, 7, 14, 30 days). Early successes neither
  advance nor postpone that schedule. Existing Exam scoring is unchanged.
- Known timestamps display in the viewing browser's timezone. Date-only and
  timezone-unknown legacy values are explicitly distinguished. Hotspot arrow keys
  move a real cursor; Enter/Space submits its position. Keyboard use is not assistance.

The rules written before implementation are in [the evidence contract](study-evidence-contract.md).
Updated in-app Help explains save/resume, completion, intervals, resets, changed
questions, local times and hotspot keyboard controls.

## Data, migration and recovery

- Schema 4 adds factual Study state, session and response tables plus a raw legacy
  response archive. Migration uses the existing transactional bootstrap. Legacy
  facts are copied verbatim; sessions, first attempts, assistance and completions
  are never inferred from them.
- Immutable event IDs and per-session sequence numbers make exact retries safe.
  Conflicting reuse is rejected. Logical order governs first/latest answers even
  when requests arrive out of order. Missing earlier responses prevent completion
  and first-outcome estimates until those saves arrive.
- Assessment digests and exact artifact fingerprints reject stale pages. Lineage
  metadata assignment alone does not change an assessment. Question edits invalidate
  current estimates for the affected assessment; generated source revisions are
  checked separately. Unrelated identical wording never creates lineage.
- **Reset Learning Intelligence** retains factual Study history/completions. It
  removes the learning-event projection; retained facts do not repopulate it.
  **Delete Study History** is separate, confirmed and protected by the existing
  owned-root checks and automatic safety backup. Backup failure prevents deletion.
  Exam records/evidence, content, settings and backups are retained.
- Reset and staged restore rotate a generation token, rejecting old browser queues.
  Normal restart does not rotate it. Old backups migrate in staging before apply.
  Existing backup/restore transaction and rollback protections remain in use.
- Portable-backup validation on disposable data checks exact wrong/correct events,
  completion retention and generation rotation. Other tests cover schema-3 migration,
  old-backup migration, reset preservation, retry after reset, write rollback, and
  content-deletion cascades. No destructive path was exercised on personal data.
- Source/library deletion retains the existing cascade semantics. This is not a
  historical question-content snapshot system. Keep a pre-upgrade backup when a
  downgrade may be needed: older code cannot open the newer schema safely.

## Validation

Tests use the project venv,
`PYTHONDONTWRITEBYTECODE=1`, disabled pytest cache and isolated fixture data.
Firefox uses disposable servers/profiles and a bounded owned-process wrapper.
Cleanup verifies PID, UID/owner, start time, working directory and command before
signalling any remaining descendant; it never uses system-wide process matching.

| Final-tree gate | Result |
| --- | --- |
| Full non-browser | 1,986 passed; 3,771 subtests passed; 190 browser cases deselected (34.76 s) |
| Enabled Firefox critical workflows | 182 passed; no skips (746.59 s) |

The 44 implementation/test files have SHA-256 hashes recorded before the final
review gates; the complete final manifest also includes documentation and screenshots. `git diff --check` and new-file whitespace checks pass. Git has no staged
changes; branch and HEAD remain unchanged. The final owned-process check found
no live validation processes. No unexpected data/build artifacts or recognizable
secret patterns were found in the changed files. The complete reviewed batch has 49 files,
including the contract, this report and three review screenshots. `DLMS.spec`
already includes the static/templates directories and `init.sql`; the new Python
modules are explicit imports. No packaging files or built packages were changed.

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider -m "not browser"
DLMS_RUN_BROWSER_TESTS=1 PYTHONDONTWRITEBYTECODE=1 \
  .venv/bin/python -m pytest -q -p no:cacheprovider -m browser tests/browser/test_critical_workflows.py
```

Focused coverage includes wrong→correct, first correct, partial multi-answer and
matching feedback, actions before answers, delayed/duplicate saves, lost acknowledgements,
competing tabs, completion retry, browser/server restart, stale assessments, generated
lineage, resets, backup/restore and hotspot keyboard submission. Firefox checks UTC,
America/New_York (both DST transitions) and Asia/Kolkata, plus ambiguous/date-only values.
The full browser suite includes existing generated pages, newly built fixtures, existing
question types, all theme regressions and hidden-panel request suppression.

### Intermediate runs and corrections

An early Firefox run was interrupted after repeated preview failures (20 failed,
15 passed). Only the verified owned pytest PID 2224810 and its verified descendants
were stopped. The next complete run had 164 passes and 12 failures. These exposed
outdated async waits, a test variable error, preview fixtures borrowing an unrelated
registered quiz ID, the new observable-copy event and a selector that included the
new regular-quiz reference. Focused reruns verified the corrections. These intermediate
runs are not counted as passing final gates.

A later run was stopped after 88 passes to correct a delayed clipboard-action
attribution edge case found during review. PID 2352142 was verified against its
recorded owner, start time, working directory and command before SIGINT. Cleanup
reported no owned descendants left. A four-case Firefox rerun verifies that a
copy finishing after navigation stays attached to the original question, preserves
action order, and leaves the other question's independent success unchanged.
The completion-boundary follow-up interrupted verified PID 2399900 after 32 passes;
its verified cleanup also left no descendants. Three focused Firefox cases then
passed, including a clipboard promise resolving during an in-flight Finish request.

The preview fixtures now use explicit preview identities. They still test rendered
controls, feedback, keyboard behavior and layout. Registered session validation was
not relaxed to accept mismatched artifacts. Copy tests still check answer/focus
preservation and now also check the durable observable action.

## Screenshots and visual review

Actual isolated Firefox captures, with sample data:

- [Complete dashboard, desktop Light](validation/study-evidence/dashboard-desktop.webp)
- [Study History, narrow Dark](validation/study-evidence/history-narrow.webp)
- [Study review and Finish Review, narrow Ethereal](validation/study-evidence/study-narrow.webp)

Browser coverage exercises Light, Dark and Ethereal at 1440 and 360 pixels for the
new flow, including Help and History, with overflow checks and keyboard completion.
Screenshots are inspected for readable text, wrapping, feedback labels and visible
controls; automated contrast checks alone do not establish accessibility conformance.

To refresh, run `test_durable_study_resume_takeover_history_and_dashboard` in the enabled
Firefox suite with `DLMS_STUDY_CAPTURE_DIR=/tmp/dlms-study-screenshots`. It captures
complete documents at both widths for all three themes. Copy the selected captures
(`study-dashboard-light-1440.png`, `study-history-dark-360.png`,
`study-finish-ethereal-360.png`) to the three paths above using lossless WebP conversion.
Keep test data isolated and inspect the resulting images before replacing them.

## Limits and deferred work

- Exam Plan dates, workload, scheduling and notifications are deferred.
- New verified sessions require registered quizzes using the shared script. Current
  registered shared-script pages receive controls on reload when identity/artifact
  checks pass. Self-contained HTML requires owner-chosen rebuilding through System
  Tools → Rebuild All Quiz Pages and gets a served Legacy quiz page notice. No
  personal artifacts were regenerated. Files opened outside DLMS cannot receive
  that notice or tracking service. Shared-script previews without a registered ID
  remain explicitly untracked. Legacy acknowledgements save only legacy responses;
  the new APIs require current contract, ownership, revision and generation tokens.
- There is no historical content snapshot or inferred assistance/completion backfill.
  Historical coverage is not a certification readiness prediction.
- Resume restores acknowledged server facts. Failed local queues remain browser-local;
  takeover does not merge conflicting unsaved answers. After reset/restore, stale local
  queues must be discarded with Start Over before resuming retained server progress.
- Incremental matching/multiple-answer feedback can make their later correct Study
  answer assisted. Correctness remains visible; independent success is deliberately
  conservative. New graded evidence uses the time the server saved it.
- Last regular quiz currently means a regular quiz with durable Study responses.
  Starting or resuming without answering does not move that reference or its saved
  timestamp. Browser-local unfinished work may still offer Resume; that is not
  learning evidence. Once a response is durable, generated focused practice does
  not displace the regular reference. A mixed quiz retains the existing
  regular classification; targeted generated review is focused.

## Changed files

The following list is the complete batch diff, grouped by responsibility.

- Wiring/persistence: `app.py`, `init.sql`, `dlms/persistence/database.py`,
  `dlms/persistence/study_schema.py`, `dlms/routes/study.py`, `dlms/routes/learning.py`,
  `dlms/routes/quiz/editor.py`.
- Services: `dlms/services/study_sessions.py`, `attempts.py`, `dashboard_activity.py`,
  `generated_practice_lifecycle.py`, `learning.py`, `restore.py` (all under `dlms/services/`).
- Client code/styles: `static/script.js`, `quiz-recovery.js`, `local-time.js`,
  `daily-review.js`, `dashboard-activity.js`, `style.css` (all under `static/`).
- Pages: `static/dashboard.html`, `history.html`, `review.html`, `review-schedule.html`,
  `learning-intelligence.html`, `learning-profile.html`, `learning-diagnostics.html`
  (all under `static/`); `templates/dashboard/index.html`, `templates/quiz/library.html`,
  `templates/settings/reset-remove.html`, `templates/study/history.html`,
  `templates/quiz/_legacy-study-notice.html`.
- Help/evidence: `static/help-quizzes.html`, `static/help-learning-intelligence.html`,
  `docs/study-evidence-contract.md`, this report, and the three screenshots above.
- Tests: `tests/test_study_sessions.py`, `tests/browser/test_critical_workflows.py`,
  `tests/test_blueprint_closure.py`, `tests/test_browser_harness.py`,
  `tests/test_database_bootstrap.py`, `tests/test_dlms_062_template_closure.py`,
  `tests/test_quiz_keyboard_accessibility.py`, `tests/test_quiz_recovery_runtime.py`,
  `tests/test_reset_remove_settings_template.py`, `tests/test_restore_migration.py`,
  `tests/test_study_learning_event_client.py`.

## Follow-up evidence-contract review

### Findings fixed

1. **Resume position could move backward.** A delayed response overwrote an already
   acknowledged Next/Previous position. Response persistence now updates the saved
   response time only; client navigation writes are serialized in their original
   order. The regression was reproduced before correction.
2. **Browser-local Resume could display stale answers.** It now claims ownership,
   retries pending immutable events, fetches current server answers and position,
   then displays the review. Lost acknowledgements are harmless duplicates.
   Conflicting queues remain visible with the original unsaved events intact;
   no successful resume is claimed. The recovery panel waits for that operation. Pending work is labelled **Resume
   and retry saves**; opening the page alone sends no retries. The original event
   identity and exactly-once storage assertions remain covered.
3. **Self-contained quiz pages lacked a tracking-compatibility notice.** DLMS now
   detects the absence of its shared script in served HTML and inserts a template
   notice with Help and System Tools links. Original files, including non-UTF-8 legacy bytes, remain byte-for-byte
   unchanged. This required two additional files in the batch: the quiz-serving
   route and its notice template. Shared-script pages keep their existing output.
4. **Timestamp validation and ordering needed tightening.** Impossible date-only
   dates and `24:00` are rejected instead of normalized. The new Study elapsed-time
   calculation orders known instants rather than ISO/SQLite text. Unknown native
   Study times leave an explicitly uncertain schedule instead of advancing it.

### Concrete acceptance evidence

- `test_first_difficulty_reaches_real_recommendations_and_generated_lineage`
  saves wrong→correct, checks the real adaptive candidate's 35-point recent-miss
  reason and 0% first-response accuracy, publishes actual adaptive practice,
  repeats wrong→correct there, and checks the source question and daily plan.
  Independent identical wording remains a separate question with no evidence.
- `test_elapsed_rule_through_saved_sessions_and_actual_schedule` uses actual new
  sessions and duplicate saves at 0, 1, 86,399, 86,400, 345,599 and 345,600 seconds.
  Streaks remain 1/1/1/2/2/3, with intervals 1/1/1/3/3/7 days. A separate test uses
  offset timestamps spanning DST and rejects unknown/invalid native times.
  **Exact rule:** qualify at `previous qualifying saved instant + interval × 86,400`
  seconds, inclusive; early successes change neither anchor nor interval. The
  anchor is the first graded learning event’s `occurred_at`, normally SQLite UTC
  at whole-second precision; factual history retains its separate `saved_at`. Wrong
  or assisted reviews reset to one day. Later corrections do not replace the
  first graded outcome. Existing Exam and legacy interpretation is retained.
- `test_reset_then_restart_and_portable_restore_does_not_replay_history` finishes
  a wrong→correct review, resets LI, bootstraps again and restores a real post-reset
  portable backup. Completion survives; actual adaptive candidates have no evidence
  and the native schedule is unscheduled. Restoring a **pre-reset** backup restores
  its older snapshot, including older estimates; it is not a global reset tombstone.
- `test_old_portable_backup_preserves_legacy_and_exam_without_claims` restores a
  schema-3 portable backup with actual legacy Study and Exam records. Raw facts and
  content remain; no durable sessions/completions/assistance are invented.
  `test_explicit_delete_route_has_recoverable_backup_and_preserves_boundaries`
  verifies the confirmed endpoint, recovers completed facts from its real safety
  backup, and checks unchanged content/settings plus preserved Exam records/evidence.
  Other tests cover backup failure, transactional rollback and content cascades.
- Firefox tests exercise two-tab takeover, local/server reconciliation, dropped
  acknowledgements, conflicting sequences and serialized navigation. Service tests
  cover reversed arrival, gaps, duplicate/conflicting event IDs, stale questions,
  completion retries and immutable finished sessions. Existing Firefox Finish tests
  also cover interrupted saves and delayed clipboard actions.
- Firefox runs UTC, America/New_York and Asia/Kolkata, both DST transitions, invalid
  dates, date-only values and ambiguous legacy times. Hotspot testing tabs into the
  control, moves from the centre to x≈0.8 with arrow keys, submits with Enter and
  verifies that the actual wrong position is saved; movement alone submits nothing.
- `test_regular_continuity_requires_response_and_resume_does_not_advance_it` checks
  that claim/open alone gives no regular reference; a durable response creates it;
  takeover alone changes neither coverage nor saved time; generated practice leaves
  it in place. The in-app Help explains the separate browser-local Resume card.

### Review runs and boundaries

The initial reproduction produced 22 passes and the expected resume-position failure.
The focused Firefox run passed all 12 cases with no skips. Final focused service,
contract and template checks passed 69 tests and 106 subtests.

The first full non-browser review gate found the route's embedded-HTML rule
(1 failed, 1,986 passed, 3,770 subtests passed). The notice moved into a template;
the inventory assertion increased accordingly without weakening the rule. The
concurrent Firefox run was interrupted after 17 passes. Before SIGINT, pytest PID
2527512 matched its recorded owner `drak`, start ticks 87242091 (2026-10-05
02:12:20.910 UTC), checkout working directory and exact command. Its owned-process
wrapper reported no remaining verified descendants. Both full gates were restarted.

Only disposable owned fixtures were migrated, restored or deleted. No personal
quizzes, settings or running service were changed. The native specification already
bundles static files, templates and init.sql; new Python modules use explicit imports.
No package was built. Hashes and the final Git/index check are recorded after the
final gates; Git publication remains entirely with the owner.

The next full Firefox attempt was deliberately stopped after 81 passes when review
identified an older test that expected a second Retry click after Resume. The
new safety flow reconciles only after its pending writes are acknowledged. Its
button now explicitly says **Resume and retry saves**. The revised test still
checks no retry on page load, unchanged event/session identity, and exactly one
persisted event after the explicit action; it no longer requires the obsolete
second click. Verified PID 2535658 matched owner `drak`, start ticks 87250614
(2026-10-05 02:13:46.140 UTC), checkout directory and command before SIGINT.
Cleanup left no verified live descendants. Nine focused Firefox recovery/Finish
cases then passed; both full gates were restarted on the frozen final code/tests.

Three supplemental executable checks used fresh disposable fixtures:

- `/tmp/dlms-study-fresh-process-check.py` launched new Python interpreters after
  reset and after post-reset portable restore. Both retained two factual responses
  and the completion, with zero learning events/candidate evidence and an
  unscheduled native review. This supplements bootstrap-only regression coverage.
- `/tmp/dlms-study-generated-interval-check.py` saved independent success on a
  regular question, generated actual adaptive practice, then saved independent
  success and an exact retry on its copy. The source showed two independent
  sessions but still a one-day interval, one qualifying success and the identical
  next-review instant. This checks the elapsed rule through actual lineage.

The review changed 16 files relative to its starting 47-file batch: the quiz route,
Study/learning services, shared Study and recovery scripts, local-time formatter,
quiz Help, compatibility notice template, browser/service/template tests, the two
evidence documents and three refreshed screenshots. The full 49-file list above
also includes the prior implementation files preserved during review.

- `/tmp/dlms-study-compatibility-check.py` verifies that a missing contract on a
  new session and an obsolete contract return HTTP 400; missing ownership and a
  stale page return HTTP 409. A valid legacy response is archived without creating
  a durable response/completion. Reset rejects the old new-contract queue, while
  a legacy retry acknowledges its archived event without replaying estimates.
  Already-open old tabs retain their old controls until reload; their legacy save
  acknowledgement is not a new-contract completion claim.

A subsequent complete Firefox run finished with 181 passes and one failure in
`test_today_review_clear_protects_failed_study_and_submitted_exam_saves`. Its
parameterized Study/Exam launch clicked an answer before async Study ownership
had been acknowledged and controls rendered. The test now waits for the active
quiz. Equivalent checkpoint-creation launches also wait before navigation; no
save-preservation assertion was removed. The three Clear workflows passed on
focused rerun; the complete related Today’s Review subset was also selected for
verification before the final gates and passed all five cases (20.52 s). Cleanup
for the complete run and focused rerun reported no remaining owned descendants.
Both required full gates are rerun after this test correction.

## Final reviewed state

Both required final gates passed on the final implementation/test files:
**1,986 non-browser tests + 3,771 subtests (34.76 s)** and **182 enabled Firefox
cases, no skips (746.59 s)**. The 44 implementation/test SHA-256 values captured
before those gates still match. The final eight-run owned-process audit found no
live processes with any recorded owner/start identity. No running DLMS service
or personal content was touched. The index is empty; branch and HEAD are unchanged.

The complete 49-file SHA-256 manifest is `/tmp/dlms-study-reviewed-files.sha256`;
verify from the checkout with `sha256sum --check /tmp/dlms-study-reviewed-files.sha256`.
It includes both evidence documents and the three refreshed final-run screenshots.
The gate-only hash JSON is `/tmp/dlms-study-review-gate-hashes.json`.
Its SHA-256 is `108dda809c1c73ea52092379eedff478be0a45ebc285a8fe8610d201baef7299`.
The final response records the complete manifest's digest, avoiding a circular
hash inside this report. No files have been staged, committed or pushed.
