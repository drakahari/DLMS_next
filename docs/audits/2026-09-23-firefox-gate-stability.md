# DLMS 3.2.1 Firefox release-gate investigation

Date: September 23, 2026. Branch: `develop/3.2.1`.
Starting source: `5fe919401e4fd0dc6efe31327a5f9bcc2cb0759a`, initially clean.
Application code and APP_VERSION are unchanged by this investigation.

## Evidence and diagnosis

[GitHub run 35860650072](https://github.com/drakahari/DLMS_next/actions/runs/35860650072)
had two attempts:

- Attempt 1: 94 passed, two setup errors, 460.05 seconds. One Firefox process
  did not expose its listener within the 12-second startup budget. The other
  exposed the listener but session initialization timed out. Logs also contained
  a software-compositor warning and a missing WebDriverWorkerListener actor.
  The compositor warning also occurs in successful local runs, so it does not
  establish an application or graphics defect. These cases never reached their
  application assertions.
- Attempt 2: 95 passed, one failed, 705.52 seconds. The OCR review workflow
  reached its final save click; its six-second pathname condition expired with
  no recorded BiDi evaluation error. The old fixture deleted its browser/server
  logs and data on teardown, and this failure did not include their contents.
  The trace contains neither the final URL nor evidence that the POST was sent
  or the bank existed. Therefore the exact hosted cause cannot be reconstructed:
  delayed submission/navigation, a missed click and a server-side failure cannot
  be distinguished retrospectively from this log alone.

Nine instrumented local headless runs on the unchanged candidate passed with
all original assertions. This was a fixed test plan, not retries until green.
The test uses the existing deterministic OCR executable fixture; it exercises
the upload/review/save workflow, not Tesseract recognition performance. All runs
used disposable data and Firefox profiles. Measurements and complete synthetic
server/browser logs were recorded outside the repository during investigation.

| Pre-fix conditions | Repetitions | Final click invocation to bank pathname (ms) |
| --- | ---: | --- |
| Normal headless Fedora host | 3 | 64.2, 93.3, 67.6 |
| Firefox, server and test sharing one CPU | 3 | 96.7, 99.2, 84.8 |
| Same CPU plus two task-owned competing CPU workers | 3 | 144.5, 159.2, 156.5 |

Every run recorded a submit event, POST `/pdf-import/save/<draft>` returning
302, GET `/pdf-import/bank/<bank>` returning 200, a persisted bank JSON file,
and the expected two rendered rows. Browser submit-event to pagehide timing was
16–71 ms in those runs. The table includes the click helper overhead and polling;
it is not a server-handler benchmark. No local navigation timeout occurred, so
there is no measured real timeout case from which to infer whether the hosted
bank had already been written. CPU contention is a controlled local comparison,
not a claim to reproduce the Ubuntu GitHub runner exactly.

## Submit path and synchronous work

`templates/pdf_import/review-question-bank.html` defines `#pdfReviewForm`,
posting to `/pdf-import/save/<draft_id>`. `static/question-review.js` serializes
the reviewed cards into `review_payload` on submit. Origin/CSRF handling precedes
the registered `pdf_import_save` route in `dlms/routes/pdf_import.py`.

The route loads the draft and calls `_save_pdf_question_draft`. It validates
the title, normalizes the exam timer, decodes the payload, normalizes each
question/choice/answer set, verifies explicit correctness confirmation and
retains excluded records. It refuses invalid included content. It constructs
the bank and calls the persistence boundary in `dlms/persistence/pdf_banks.py`,
which saves through the atomic JSON writer. It then cleans screenshot staging,
deletes the draft, calculates active/excluded counts, flashes confirmation and
returns the bank redirect. The destination loads the saved bank and renders its
table. There is no OCR subprocess, PDF rendering or playable-quiz generation in
this final save operation.

The save route, bank persistence module and review JavaScript have no changes
between the published 3.2.0 tag and this candidate. The measured path provided
no evidence of a 3.2.1 publication-performance regression or broken application
behavior. This is evidence for a focused harness change, not proof that every
possible hosted application failure has been excluded.

## Bounded harness changes

- This workflow now waits up to 20 seconds for the bank pathname, complete
  document load and bank table. Twenty seconds matches its existing earlier
  OCR-review navigation budget. All subsequent source and row assertions remain.
  Other condition and command timeouts are unchanged.
- On timeout, the helper still fails and includes URL/readiness, invalid fields,
  flash messages, persisted bank filenames and server/Firefox log tails before
  fixture cleanup. A bank file alone never counts as a successful browser flow.
  The save is never automatically resubmitted.
- Firefox startup has its own 30-second budget, shared by listener connection,
  session creation and initial browsing-context discovery. Previously session
  initialization used independent eight-second command timeouts inside the
  12-second connection loop. Cold initialization can now use the remaining
  startup budget without changing normal command deadlines. Failed connected
  clients are still closed and failed/exited processes still fail setup.
- No blind sleeps, skipped tests, reduced OCR coverage, assertion weakening,
  graphics preference changes or automatic whole-test retries were added.

The final-navigation change addresses an overly narrow/default synchronization
contract and missing diagnostics. It does not establish that simply waiting
longer would have fixed the specific past GitHub run. The startup budget change
directly addresses the separate observed listener/session timeout boundaries.

## Validation

Harness regressions: **14 passed**. Added coverage uses a controlled clock to
exercise a listener appearing after 13 seconds plus nine-second session startup,
the shared session deadline, connected-client cleanup, bank readiness after eight
seconds, and continued failure with a bank file present plus retained diagnostics.
No real sleeps are used in these timing regressions.

Six post-fix instrumented OCR runs passed: three normal headless runs and three
one-CPU runs. Click invocation to fully loaded bank readiness measured
97.0 / 69.1 / 67.6 ms normally and 173.7 / 168.2 / 142.5 ms on one CPU.
This is a stronger completion boundary than the pre-fix pathname-only timing,
so their small difference is not an application performance comparison.
All six retained successful POST/redirect, bank files and two rendered rows.

Final gates used the project `.venv` and `PYTHONDONTWRITEBYTECODE=1`:

- With `DLMS_RUN_BROWSER_TESTS=1`,
  `python -m pytest -q -p no:cacheprovider -m browser tests/browser/test_critical_workflows.py`:
  **96 passed in 394.67s**, then **96 passed in 392.39s** consecutively on the
  same code. No skips, failures, test retries or edits between the two passes.
- `python -m pytest -q -p no:cacheprovider -m "not browser"`:
  **1,800 passed, 104 deselected, 2,450 subtests passed in 24.97s**.
- `git diff --check`: **passed**. Final diff review confirms only the two browser
  harness/workflow files, their two regression-test files and this new record.
- Fixture cleanup completed. Post-validation process checks found no task-owned
  Firefox, test server or competing CPU worker left running.

The local validation supports these bounded reliability changes. No application
bug or publication slowdown was reproduced. The historical hosted timeout's
underlying trigger remains unproven because its diagnostics were not retained;
the updated failure path preserves the evidence needed if it happens again.

Hosted verification of the modified tree remains a subsequent owner push/CI
step. Nothing was committed, pushed, switched to another branch or published.
