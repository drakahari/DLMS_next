# Study evidence contract

This batch adds reliable Study records, not an Exam Plan or a readiness prediction.

## Facts and learning estimates

- A session has a stable ID, an assessment revision, a question manifest and a purpose (regular or focused generated review). Opening a page is not progress. Only saved responses establish activity.
- Responses and observable actions have immutable event IDs and increasing session sequence numbers. Identical retries acknowledge the existing record; conflicting reuse is rejected. Arrival order cannot replace logical order. Partial answers have unknown correctness.
- The first graded response, subsequent corrections, and feedback or external-tool actions remain distinguishable. Feedback exposed by partial selections counts as prior assistance. Opening AI or copying a prompt records the action, not proof that an external answer was read. Legacy evidence retains its old interpretation with unknown first-answer/assistance/completion status.
- Migration copies legacy Study responses verbatim into factual storage, without constructing sessions or claims about assistance/first outcomes. Legacy API retries remain factual acknowledgements after an estimates reset.
- Factual Study records survive Reset Learning Intelligence. Learning estimates consume only the existing resettable learning-event stream. A reset never rebuilds that stream from factual history.
- New Study estimates use the first graded outcome and observed assistance, preserving initial difficulty. Accuracy retains actual first correctness; mastery performance terms and native scheduling use independent success. Adaptive practice labels assisted correct responses separately from mistakes. Independent correct Study outcomes advance the native schedule only when the preceding scheduled interval has elapsed (initial interval one day; then 3, 7, 14, 30 days). Early correct reviews do not postpone or advance that schedule. Incorrect/assisted reviews retain a short review interval. Legacy and Exam scoring are unchanged.

## Completion, resume and ownership

- Full review means complete acknowledged answer coverage of the session's entire manifest plus an explicit Finish Review. Wrong or assisted complete answers count as reviewed, not independent success. Focused generated sessions cover only their own question set.
- Finish is idempotent and requires a gap-free response sequence. Each repeat review creates a new session; resume continues the existing session. Completed sessions are immutable.
- Selecting Finish freezes new answers/tool events until the request resolves. A clipboard promise that resolves after that boundary does not append evidence to the closing session. Pending answer saves still must be acknowledged; failed Finish reopens the session for corrections and retry.
- Durable saved answers, variants and position support resume. Unsaved browser queues remain visibly pending. Only the tab holding the current session claim may write; another tab must explicitly take over. Takeover invalidates the previous claim.

## Versions, reset and deletion

- Verify the current playable artifact fingerprint and database assessment digest; reject stale pages explicitly. No historical question-content snapshot system is introduced. Content changes invalidate resume/completion for the old revision; factual old records remain history until explicit deletion. Title/folder changes do not infer a new question identity. Generated lineage continues to use existing UIDs; text equality never merges new records.
- Add schema tables transactionally without fabricating legacy sessions. Backups include them through the existing SQLite backup. Old backups migrate in staging. Restore rotates a database queue generation, invalidating pre-restore writes; reset rotates it too. A fresh claim is required to resume retained sessions after reset/restore.
- Delete Study history is a separate confirmed operation using the existing automatic pre-reset backup and owned-data-root safeguards. It removes factual Study sessions/responses and Study learning evidence, including legacy Study events, but preserves Exam attempts/evidence, content, settings and backups. Learning Intelligence reset preserves factual Study history/completions; source/library/full-data deletion keeps its established content-deletion semantics.

## Presentation

- Keep last regular Study activity separate from targeted generated practice. Show partial versus finished state without claiming progress from opening a quiz. Suggested actions continue to come from existing Learning Intelligence.
- Store UTC instants; display known instants in the viewing browser's timezone with a timezone indication. Do not interpret date-only or ambiguous legacy timestamps as UTC instants.
- Hotspot keyboard operation moves an actual cursor and explicitly submits that position. It never selects the answer target automatically; keyboard use itself is not assistance.

## Review clarifications

- An interval day is exactly 86,400 elapsed UTC seconds. Scheduling uses the first graded learning event’s `occurred_at` (the
  existing SQLite UTC column, normally whole seconds); factual `saved_at` remains
  separate for history. The first independent
  success establishes a one-day interval; the next qualifies at `anchor + interval`
  (inclusive), then uses 3, 7, 14 and at most 30 days. Early successes leave both
  anchor and interval unchanged. An incorrect/assisted review sets a one-day
  interval from its own saved time. Retry IDs, session restarts and generated
  copies cannot bypass this per-source-question rule. Unknown native Study times
  cannot establish an elapsed interval; the schedule explains that uncertainty.
- Navigation saves are ordered separately from concurrent answer saves. Delayed
  answers never move acknowledged navigation backward. Browser-local **Resume and retry saves** must
  claim the session, retry its pending events and reconcile with current server
  answers before showing the quiz. Conflicting queues stay visible and block that
  resume; they are not silently merged or discarded.
- Starting/resuming without a new response does not change Last regular quiz or
  its last-response timestamp. Browser-local unfinished work can still offer a
  Resume action; that is continuity, not evidence of learning. Once the first
  response is durable, the regular reference survives focused generated practice.
- A post-reset backup retains history and the cleared estimates state. Restoring a
  pre-reset backup intentionally restores that older snapshot, including its old
  estimates; reset is not a global tombstone outside the restored backup.
- Existing registered shared-script pages receive the contract on reload when
  their identity/artifact remains valid. Self-contained pages require owner-chosen
  rebuilding and receive a served compatibility notice. Preview pages remain
  explicitly untracked. Files opened outside DLMS cannot receive that notice.
  Legacy API acknowledgements refer only to legacy response storage. New sessions
  reject missing/obsolete contracts, stale revisions and invalid ownership/generation.
