# Study completion correction

## Verified baseline and reproduction

Reviewed checkout: DLMS_next, `develop/3.3.0`, owner commit
`7d88b1ac160cbc0f7574b2e85585400bdd5d1174` (Add durable Study tracking and improve learning recommendations).
The working tree was clean before this correction. No personal data or running
owner server was used. Firefox runs use disposable databases and newly generated
HTML from the actual four-question manual quiz builder.

The reported click path is reproducible when `crypto.randomUUID` is unavailable:
choose one incorrect answer on each of four single-choice questions, then Finish
Review. All four response requests return HTTP 200 with matching event IDs. The
stored sequences are **2, 4, 6, 8**; Finish submits 8 and correctly returns HTTP 409.
The dashboard shows all four questions reviewed but no completion. With native
`randomUUID`, the same wrong answers have sequences **1, 2, 3, 4** and finish.
The reproduction disables that browser capability, not persistence or scoring.
The owner's browser origin/capabilities were not inspected, so the exact trigger
in that browser is not independently established.

Root cause: `createStudyLearningEventId` incremented the response sequence in its
fallback, and `recordStudyLearningEvent` incremented it again when creating the
payload. An opaque ID factory must not allocate response sequence numbers.
Incorrectness was never the server's completion condition. The old warning
incorrectly suggested retrying missing saves even when every actual save had
been acknowledged.

## Correction and safeguards

- Allocate each response sequence exactly once, independently of UUID support.
- Preserve gap detection, immutable event IDs, ordering, assessment checks and
  explicit complete-answer coverage. Complete wrong answers count as reviewed.
- Finish still waits for in-flight saves, blocks failed/incomplete saves, and
  reports success only after acknowledgement. Repeating Finish is idempotent.
- An indexed exact-session status lookup reconciles a completed browser checkpoint
  after a lost Finish acknowledgement. Quiz startup and Today’s Review use it;
  neither infers completion from answer counts. Failed lookups and unacknowledged
  response queues remain recoverable. Another tab's changed checkpoint is retained.
- Clear only the exact unchanged checkpoint. A completed older session cannot
  erase a newer review or an unrelated quiz's recovery record. For focused
  generated practice, preserve the separate Library-marker retry path until its
  status is also confirmed. No GET performs a completion write.
- Dashboard wording distinguishes **questions reviewed**, **Last response saved**,
  and **Review finished**. Help explains retry versus a persistent sequence gap.
- First-response evidence, source lineage, reset boundaries and interval rules
  are unchanged. An independent correct Study outcome advances only at/after the
  prior qualifying response plus its current 1/3/7/14/30-day interval; a day is
  86,400 elapsed UTC seconds. Immediate retries/restarts cannot advance it.

There is no schema migration. Existing supported shared-script pages receive the
fix on reload, including newly generated pages. No personal quiz is regenerated.
Older self-contained pages retain the documented rebuilding boundary.

## Already-affected sessions

This correction does not renumber old events, invent gap fillers, mark an old
session finished, or clear its recovery automatically. Without the missing
sequence facts DLMS cannot prove acknowledged coverage of the event stream.
If Retry has no pending saves and the sequence warning remains, start a new review;
the original factual responses remain in Study History. Gap protection also
withholds first-response learning estimates for those affected sessions. Completing
a new review normally retains its first mistakes in recommendations. No attempt
was made to repair the owner's existing test session.

## Regression evidence

`test_new_regular_study_answers_complete` exercises the actual builder and Firefox
click path for all-wrong, all-correct, mixed and wrong→correct answers, with both
UUID implementations. It checks requests/acknowledgements, ordered SQLite facts,
recommendations, repeated Finish, dashboard state, reopening and a distinct new
session. Set `DLMS_COMPLETION_CAPTURE_DIR` to an outside-repository directory to
save request/ACK/session JSON and full-page screenshots.

Additional browser regressions cover delayed first saves (2–4 arriving first),
immediate Finish, failed saves, lost answer/Finish acknowledgements, Retry,
completion reconciliation on either dashboard or quiz reopen, genuine sequence
gaps, unrelated checkpoints and a checkpoint replaced during lookup. Existing
competing-tab, generated-practice, multi-answer/matching and reset coverage remains;
the hotspot keyboard test now also finishes a genuinely incorrect position.
Service regressions verify wrong complete multiple-answer/matching completion and
exact-session lookup without substituting the latest session.

Final gate logs, screenshots, captured traces and SHA-256 manifest are reported
with this change. Browser processes are tracked by owner/PID/start identity and
cleaned up only within each owned validation run. No commits, pushes, deployment,
settings changes on personal data, or owner-server changes are part of this work.

## Additional UI finding from the required gate

The first full Firefox run was interrupted after two theme cases found unreadable
hovered answer feedback (94 other cases had passed). A generic `.choice:hover`
background outranked `.wrong-choice` / `.correct-choice`, leaving dark feedback
text on the theme's dark hover background. Intermediate animation frames had
initially obscured this cause. A computed-style/animation diagnostic showed that
the failure persisted after the transition ended.

The correction gives graded feedback selectors equal specificity to hover;
existing correct/incorrect colors and labels are unchanged. The rendered-state
contrast helper now waits for initial rendering and CSS transitions, making this
hover-state regression reproducible. No contrast threshold was relaxed. Temporary
diagnostic code was removed. An early test-only SQL query in the gap regression
was also corrected and rerun. Interrupted/failed runs do not count as passing
validation; both full gates must pass on the final tree.
