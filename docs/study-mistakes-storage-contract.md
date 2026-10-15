# Study mistakes and saved Mixed Quizzes

## Evidence and identity

The additive Study mistakes source uses durable Study responses whose recorded
outcome is wrong. A complete graded wrong response qualifies even in an
unfinished session, after assistance, or before a correction/later success.
Unanswered, partial ungraded selections, assistance alone and browser-only
pending answers do not qualify. No old response is regraded against a new key.
The existing manual **Missed before** filter retains its separate meaning.

Evidence must match the current session assessment revision and manifest
question identity. A quiz-wide edit can make old evidence unverifiable even if
one particular question appears unchanged. Legacy responses without that
revision remain saved but cannot supply this source. Generated copies require
explicit source lineage and matching grading content (including media bytes).
Orphans are not attached by wording; identical prompts from independent source
questions remain independent. Unsafe/incomplete questions and unavailable media
are reported rather than repaired or substituted. Hotspots remain unsupported
by this composition source. Text/image choice and matching content use the
existing saved-quiz renderer and grading workflows.

Folder and quiz choices form a union. Overlaps count once by verified source
identity. This is an explicit manual builder selection, including Library-hidden
and Learning Scope-excluded sources; it does not change either setting. It does
not change automatic review eligibility or an active Exam Plan.

## Schema 12 and publication

Schema 11 → 12 adds four tables: `study_mistake_state`,
`study_mistake_passes`, `study_mistake_members`, `study_mistake_actions`.
The transaction adds no question, answer, history or scheduling changes.
Validation checks canonical scopes, hashes, requests, destinations, member
revisions and reservation/consumption consistency before accepting a database.
Older incompatible applications refuse schema 12.

Without repeats stores a randomized snapshot for the exact normalized selection.
Only one current pass per selection is offered; previous passes remain recorded.
New mistakes wait for an explicit new pass. Edited/deleted sources or deleted
Study evidence make members unavailable, with no substitute. A saved mix uses
1–100 questions, including a single-source/one-question batch. The manual builder
retains its two-question/two-source minimum. Pools above 10,000 recorded source
questions are rejected explicitly; previews and unavailable lists page by 20.

SQLite reservations serialize concurrent requests. A request ID binds the entire
immutable input and selected source revisions. Same-ID replay returns the same
published destination; changed inputs are rejected. The existing publication
journal covers files, quiz rows and registry. A transaction callback revalidates
Study evidence and revisions before committing the quiz and action together.
Consumption is finalized only after publication. Confirmed rollback releases
members but retains the original retry selection. Startup first reconciles owned
publication journals, then finalizes verified destinations or releases proven
missing publications. Unsafe/unresolved journals hold uncertain reservations.
An unavailable committed destination is not treated as permission to create a
replacement quiz. Output deletion never returns used members to the pass.

Random selects unique questions per output and permits reuse across outputs. It
uses the same retry ledger, without creating, consuming or resetting a pass.
Creating a mix is composition usage, never Study credit/mastery/completion. Its
own completion does not finish a source quiz or replace Last regular quiz.

## Backup, reset and rollback

Full profile backups contain the four tables and generated quiz/media artifacts.
Restore validates and migrates staging before activation, preserving passes and
consumption, but changes the feature generation token. Pre-restore requests
cannot mutate restored data. Compatible older backups acquire empty new tables;
no pass or wrong answer is invented. Full profile replacement follows the
existing restore journal/recovery rules.

Learning Intelligence reset leaves factual Study evidence and passes intact;
this feature never rebuilds cleared estimates. Explicit Study-history deletion
removes eligibility and invalidates stale requests, but leaves saved quizzes.
Full quiz-data reset clears pass/membership/action records and changes the token
alongside its existing destructive scope. Settings resets do not erase passes.

Before upgrading, keep a verified pre-upgrade full backup outside the data root.
Rollback requires a compatible older application and restoration of that backup
into a separate supported profile. Preserve the upgraded profile separately.
Switching binaries alone does not reverse schema 12. Restoring an older backup
loses changes after that backup, including new mixes and pass progress. Never
edit schema numbers or remove tables to force an older writer to open the data.

## Browser recovery

The builder retains one immutable creation request in session storage before
sending it. Retry preserves its identity/content; lost acknowledgements do not
create another quiz. A successful page disables further creation until refreshed
counts and a new server-generated ID arrive. A definitively rejected request
has an explicit **Change request** action. It clears only that creation record,
not answers, quiz recovery, passes or saved quizzes. Uncertain outcomes retain
the request; restart only the affected DLMS instance to run normal recovery,
then retry. Browser request retention is tab/session-local; durable pass state
is server-side and survives restarts. No cross-browser request adoption is implied.
