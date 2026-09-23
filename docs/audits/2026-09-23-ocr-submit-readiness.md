# DLMS 3.2.1 OCR review submit readiness

Date: September 23, 2026. Branch: `develop/3.2.1`.
Starting commit: `749ccd40b6ae1f350425f1e64aa5b751d9731767`, initially clean.
No application code or APP_VERSION changes; no commit or push.

## Hosted failure and local reproduction

[Hosted run 35880531823](https://github.com/drakahari/DLMS_next/actions/runs/35880531823)
finished with 95 passed and one failed in 769.57s. Firefox/Xvfb initialized
successfully. The OCR review test's final click produced neither a save POST nor
a persisted bank. The document stayed on the review route, fully loaded, with
no invalid fields or flash messages. This was not a slow redirect or OCR delay.

The actual OCR workflow was instrumented on the unchanged interaction using
Firefox 156.0 on Fedora 44, the real DLMS BiDi helper, isolated synthetic data,
and private 1920x1080x24 Xvfb displays:

| Baseline configuration | Fixed repetitions | Result |
| --- | ---: | --- |
| Native headless | 3 | 3 passed, 4.65 / 5.15 / 4.72s |
| Headful under Xvfb | 3 | 2 passed, **1 reproduced no-POST failure** |
| Xvfb, Firefox/server/harness sharing one CPU | 3 | 3 passed, 7.83 / 7.89 / 7.78s |

These were fixed sample counts, not retries until green. The failed local Xvfb
run took 24.78s; its other two runs took 4.79s and 4.62s. No artificial delay,
injected layout mutation, canceled event, or modified server response was needed
to reproduce the miss. Local platform timings are not hosted-runner benchmarks.

## Root cause: a late lazy-image layout shift during pointer delivery

The captured failing sequence was:

| Event | Time in review document | Target | Save button top | Second preview |
| --- | ---: | --- | ---: | --- |
| pointermove | 198ms | Save button | 847.63px | naturalWidth 0, height 0 |
| pointerdown | 199ms | Save button | 846.47px | naturalWidth 0, height 0 |
| pointerup | 202ms | Surrounding create-bar section | 889.18px | naturalWidth 1536, height 212.53px |
| click | 202ms | Surrounding create-bar section | 889.18px | intrinsic dimensions now available |

The pointer remained at (1153, 886). When the image acquired its intrinsic
dimensions, the Save button moved below that point between press and release.
No submit event occurred. Native Firefox click targeting therefore never
activated the submit control, and the server correctly received no save request.

The button remained connected, enabled (including `:disabled`), displayed and
visible, with opacity 1 and pointer-events auto. There was no open overlay.
The form action was `/pdf-import/save/<token>`, method POST. The initial focus
was an input; pointer-down moved focus to Save. The ordinary button hover/press
transform was recorded, but the significant layout change coincided with the
second preview acquiring its dimensions. All recorded pointer/click events were
uncanceled. The existing center hit-test correctly found Save **before** input;
it could not guarantee that later image loading would not move it during input.

`templates/pdf_import/review-question-bank.html` renders the source images with
`loading="lazy"`. `static/style.css` gives their frames a minimum height, not
their eventual intrinsic dimensions. `document.readyState === 'complete'` does
not mean off-screen lazy previews have loaded. `static/question-review.js`'s
submit handler only serializes the review payload; it neither prevents submission
nor disables Save. The save route in `dlms/routes/pdf_import.py` validates and
persists only after receiving the POST. No submit/persistence product defect was
found. This is test readiness versus a real late-image layout change, not evidence
that application JavaScript swallowed a correctly delivered Save click.

The local event trace proves this mechanism and reproduces the hosted symptoms.
The old hosted run lacked event geometry, so its exact press/release sequence
cannot be retrospectively verified; the same root cause there remains an
evidence-backed inference, not a recovered hosted trace.

## Narrow fix and permanent diagnostics

`_submit_reviewed_pdf_bank` now scrolls each OCR preview into view, waits for
`complete && naturalWidth > 0`, and awaits image decoding before the existing
real Save click. It neither changes lazy-loading behavior nor reserves artificial
space. The existing pointer hit-test, 20-second bank-readiness timeout, source,
row, theme, responsive, and confirmation assertions remain unchanged. There are
no sleeps, click retries, navigation-timeout increases, or programmatic submission
in the OCR workflow. Unavailable/broken previews fail before Save is clicked.

The test-only `_form_submit_probe.js` records initial/current geometry, computed
visibility/pointer-events, disabled state, center hit stack, form action/method,
focus, active animations/overlays, image readiness, button attribute changes,
pointer/click/submit/invalid events, cancellation and explicit form-method calls.
Failure reports include this trace alongside existing browser/server/bank evidence.
Snapshots survive navigation in the isolated sessionStorage namespace. No form
field payloads are recorded.

A real-Firefox diagnostic fixture verifies native clicks, canceled click and
submit events, requestSubmit observation and disabled-state mutations. Its
deliberately canceled requestSubmit call tests the observer only; it is not used
to bypass the OCR workflow. Cancellation is read after bubbling and at snapshot
collection because Firefox can run microtasks between event listeners. The
observer never calls preventDefault or changes a control's state.

## Validation

- Focused harness/BiDi regressions: **24 passed, 7 subtests passed**. New tests
  enforce scroll/load/decode ordering before the single click, no click after
  failed image readiness, and retained submit/bank diagnostics without retries.
- Post-fix OCR runs under Xvfb: **10/10 passed**, 4.49–4.65s each. Three additional
  one-CPU Xvfb runs passed in **8.06 / 7.83 / 8.14s**. Three native-headless runs
  passed in **4.54 / 4.59 / 4.69s**.
- After finalizing cancellation diagnostics, three paired Xvfb runs of the OCR
  workflow plus the new diagnostic regression passed: **2 passed in 6.51s**,
  **2 passed in 6.47s**, **2 passed in 6.42s**.
- Two complete consecutive final Firefox gates, without edits or retries between
  runs: **97 passed in 361.73s**, then **97 passed in 359.61s**. Both used the
  project `.venv`, `DLMS_RUN_BROWSER_TESTS=1`, `DLMS_FIREFOX_MODE=xvfb`,
  `PYTHONDONTWRITEBYTECODE=1` and a private Xvfb screen:
  `python -m pytest -q -p no:cacheprovider -m browser tests/browser/test_critical_workflows.py`.
- Full non-browser gate:
  `python -m pytest -q -p no:cacheprovider -m "not browser"`:
  **1,811 passed, 105 deselected, 2,457 subtests passed in 24.75s**.
- `git diff --check`: **passed**. Both new untracked files were also checked
  explicitly against `/dev/null`; no whitespace errors were found. Final diff
  review confirmed only the critical-workflow harness/regression, its unit tests,
  the test-only JavaScript probe and this new audit record changed.
- Browser cleanup completed; no task-owned Firefox, Xvfb or browser-test server
  remained after the full gates. The unrelated existing user Firefox process
  was left untouched.

## Remaining hosted confirmation

The owner should review/push these changes and rerun the hosted gate on that
candidate. The new diagnostic regression raises the complete Firefox gate from
96 to 97 tests; no existing test was removed or skipped. This investigation did
not commit, push, dispatch a hosted run, or change release/application behavior.
