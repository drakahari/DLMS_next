# Exam Plans v1 contract

Plans organize existing Study/Exam evidence; they do not change scoring, due intervals,
Study completion, Last regular quiz, or the Learning Intelligence reset boundary.
Folders are exact flat names intersected with Learning Scope. Renames require explicit
remapping; membership changes remain visible until acknowledged. Current coverage
requires a matching assessment revision (and generated source revision). Historical
coverage is separate and never repopulates reset learning events.

## Daily target

Calendar dates use the saved IANA timezone, today inclusive and exam day exclusive.
Event instants display in the browser's local zone. Pace and review allowance are
editable assumptions, not time telemetry. Daily slots = floor(minutes / (pace ×
(1 + allowance))). Distinct eligible questions answered today reduce remaining slots;
repeating a question does not spend another estimated slot. The deduction from
remaining calendar capacity is capped at today’s minutes; optional extra practice
cannot consume a future study date’s allowance. Only current learning
projection records establish this daily credit, so reset facts cannot recreate it.

Reconstruct the first-pass/fresh-evidence need at the start of today from remaining
needs plus those satisfied today. Divide by remaining selected study dates, rounding
up, then subtract today's first-pass work. Cap this coverage target by remaining daily
slots. Fill spare slots with ranked mistakes/due questions (one slot for overlapping
reasons), then other unique adaptive candidates. No fixed thirds. Non-study days,
pause, past dates and zero capacity have no automatic quota; optional additional
practice remains available. Refreshing does not reset credited work. The 50-question
publication limit bounds each batch, not the day's total target.

Shortfalls and excluded/unavailable work are explicit. Independent plan budgets are
not reserved time and overlapping plans do not duplicate learning records. No pass
probability, active-duration inference, automatic exam rescheduling or notifications.

## Persistence and retry boundaries

Schema 5 adds plans (validated configuration JSON, revision, acknowledged scope),
a singleton active pointer/restore generation, and publication request identities.
JSON holds the small atomic form; no second response/history store is introduced.
Writes are transactional, CSRF protected, optimistic and server validated. Publication
reserves a unique request before work and records the generated quiz in its existing
insert transaction. Concurrent pending requests report retry, never publish twice.
Retries validate the input hash and restore generation before returning the same
validated artifact. Interrupted publication with uncertain outcome reports recovery
required rather than blindly creating another quiz.

Old backups migrate with no plans. Restore rotates plan tokens. LI reset retains
plans/history and clears only estimates. Study-history deletion retains plans and its
existing recovery safeguards. Full data reset removes plan configuration. Plan deletion
never deletes content or learning records. Existing legacy identities remain uncertain;
no completion, assistance, or question-version history is backfilled.


## Recovery and portable calendars

A failed publication is retryable with the same request ID only after the existing
publisher confirms complete rollback and journal removal. Pending or uncertain
publication is never duplicated by a retry. A missing/deleted artifact is not
silently regenerated: the learner reloads after recovery and explicitly starts new
work. Source revisions and plan/restore tokens are rechecked in the quiz insert
transaction. Portable builds include the tzdata package so the saved IANA timezone
can be resolved without relying on a host-specific database.

Known compatibility limit: regular historical Study manifests validate the whole
quiz assessment revision, so editing one question conservatively removes that
session's current coverage. Facts remain historical. Legacy learning identities
retain the existing evidence interpretation; they are not proof of independent
first success or unobserved assistance. No historical snapshots are invented.

## Review evidence and corrections

Current-revision factual coverage exposes distinct question counts for first graded
mistakes and later same-session corrections. Observable answer feedback may also
make that work assisted; these are overlapping descriptions, not additive totals.
They survive Learning Intelligence reset, while recommendations still use only the
resettable evidence projection. Fifty reviewed questions do not finish a review
until the existing Finish Review acknowledgement. Suggested publication preserves
the planner's coverage-first ordering even if the requested batch size shrinks.

Fixed-clock example (2026-10-16, America/Chicago, Monday/Wednesday/Friday):
80 unseen questions, 30 minutes/day, 2 minutes/question plus 25% allowance.
Exam October 30: 6 dates, target 14, 12 slots, 20-minute base shortfall.
Exam October 20: 2 dates, target 40, 12 slots, 140-minute base shortfall.
After 5 distinct first-pass responses today: remaining targets 9/35 and 7 slots.
Generating or refreshing alone changes none of these credits. Autumn's repeated
hour is one calendar date; repeated answers to the same source consume one slot.

## Usability and selection contract

Use this plan on my dashboard is an explicit positive action: one transaction
makes the plan selected and visible, preserving pause. Unchecked on create saves
an unselected plan. Unchecked on edit leaves the existing selection and visibility
unchanged. Hide changes only visibility; pause changes only recommendations.
Ordinary saves cannot implicitly hide or steal the dashboard selection. Old forms
with the former active/visible controls are rejected with reload guidance.

A compare token combines restore generation, current selected ID and that plan's
revision. Selection checks it under BEGIN IMMEDIATE as well as the target revision;
concurrent switches and A→B→A changes cannot silently overwrite the reviewed choice.
No schema or backup format change is needed. All old active/visible/paused values
remain readable. The Today’s Review visibility preference is never overridden.

One work-state explanation is shared by detail, list, preview and dashboard.
Precedence: no material / fully excluded / unavailable, exam today or past, pause,
no remaining study dates, non-study day, pace cannot fit one question, allowance
used, ready work, future reviews after today's answers, other material answered
today. Additional restrictions remain warnings. Explanation code never selects
questions or changes native intervals. Future reviews remain in workload estimates;
after all four included questions have responses today, four future reviews can
mean ten estimated minutes of outstanding work and zero new suggestions, even
with eight daily slots unused. Dates use the saved plan calendar, not the browser
zone. Unknown review dates are not invented.

The dashboard has one View plan link. Its optional primary button starts practice
through the existing retry-safe publisher, or links to distinct setup/settings.
Detailed evidence and estimate assumptions remain available through disclosures.
Empty/excluded/unavailable plans show an unavailable workload estimate, not a
reassuring zero-work fit claim. This is presentation; the underlying budget,
evidence, completion, source lineage, scope and reset contracts are unchanged.
