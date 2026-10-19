# Windows Avery Print Cards: acceptance and integration handoff

Public base: `a8cd5182b6870e8bfdc1fca569b2cda9f191a1be`.
Reviewed runtime/tests commit: `968709d0cd15210d35d3561d513bfbf559b088ad`.
The follow-up commit containing this record is documentation only.

Complete reviewed patch SHA-256:
`01f271cda4f4724d601abc49e37290d654b79695648959cdfe3e34092875f76d`.
Its generated patch formatting differs from Git's staged new-file index headers;
the committed three-file change was checked against the exact retained patch
before commit. No runtime edits were made after independent review or packaging.

## Change and boundaries

Only `windows_webview2/Host.cs` changes runtime behavior. An isolated-world
listener intercepts the supported Avery child's trusted Print Cards click,
including a keyboard-generated click, with active user activation. It requires
the exact button type, inline handler and label; arbitrary buttons, direct
`window.print()` calls and synthetic clicks receive no print authority.

Native dispatch validates the private execution context, nonce and next one-use
sequence, completed exact-origin printable document, exact active child, and
current opener/navigation/ownership lease. No await separates the final check
from **that child's** `ShowPrintUI(Browser)` call. Close, navigation or context
loss invalidates the permit. A native UI request is never reported as proof
that printing or saving completed.

The engine-owned original POST/body, CSRF/header policy, Local authentication,
exact-origin navigation/resource restrictions, source selection and Return
lifecycle are unchanged. Ordinary child downloads, file selection, frames,
context menus, unrelated navigation and unsolicited printing remain restricted.
The native print UI owns printer/PDF destination selection and overwrite/cancel
consent; the page receives no chosen path or generic native bridge. Its native
Save as PDF may show the browser-owned download bubble. This does not enable
page downloads. The print PDF chooser starts in the isolated process Downloads;
it does not use the quiz-export remembered-directory adapter.

## What was actually exercised

All data and endpoints were disposable synthetic fixtures. No production or
personal profile was used. This is scoped qualification evidence, not a new
owner walkthrough or broad physical acceptance.

| Path | New evidence and precise limit |
| --- | --- |
| Local startup | Two starts of the normal frozen executable, authenticated normal shutdown and reopen, same synthetic identity, exit 0 and no observed owned survivors. |
| Local Avery printing | **Not newly exercised.** Earlier accepted Local original-request/render/Return evidence is reused only for unchanged transport/lifecycle. No new Local Print Cards, Local cancellation or Local printed PDF is claimed. The new native dispatch is shared by Local and Server. |
| Server Avery opening | Normal frozen executable, task-owned matching-code Server. Selected only Q2 of four synthetic questions. Exactly one original `/anki/printable` POST returned 200 with the selected Q2 token, CSRF and cookie; no Local token. |
| Existing Server button | Actual rendered legacy markup was `<button type="button" onclick="window.print()">Print Cards</button>` with **no ID**. A genuine mouse activation opened native browser print preview. No production server update is required for this markup. |
| Cancellation | First native print preview was canceled before any printer/PDF submission. Avery remained usable. This was native preview cancellation; cancellation of the later PDF Save As chooser was not separately exercised. |
| PDF save | A second deliberate Print Cards activation, native Save as PDF, native destination dialog. Task destination did not exist. Native value-setting and Alt+S completed the save after coordinate/UIA offset failures. No physical printer job was sent. |
| Selected-card contents | Independently inspected generated PDF: two US Letter pages (612 x 792 points); selected Q2 and its choices on the front, its correct answer on the back, and no Q1/Q3/Q4 content. PDF SHA-256 `038ab53d790f4bcecb26d98ed7d033c4972022d3a44c91f95c7b66c62221717c`. The synthetic PDF itself is retained privately, not committed. |
| Return | The **native header Return** closed Avery and revealed the existing source page: only Q2 visibly checked; Q1/Q3/Q4 unchecked; one selected card; original deck name and long-edge setting retained. No source reload/POST was needed. The web Return button was not separately repeated. |
| Server cleanup | Main-window close inputs had no verified effect. After the bounded attempts, the prepared task-owned Job was stopped once; Server session exit 1 is **technical cleanup, not normal shutdown acceptance**. Owned descendants were gone and the synthetic Server thread stopped. No unrelated process was terminated. |

The selector does not inspect a button ID. Adding an ID to the exact markup
above leaves it matched; a separately deployed ID-added Server was not rerun.
If shared/Mac changes remove the inline handler, button type or label, reconcile
that changed markup explicitly; do not replace the deployed-Server fallback
with an ID-only requirement.

## Focused regressions and review

The completed focused invocation was:

```text
python -B -X utf8 -m pytest -q -p no:cacheprovider
  --basetemp=.gate1/windows-native/pytest-print-01
  tests/webview2/test_avery_print.py
  tests/webview2/test_avery_stack.py
  tests/webview2/test_avery_headers.py
```

Seven pytest cases passed: actual compiled permit checks (12), production
isolated-listener harness checks (11), retained native stacking checks (80),
header checks (33), and wiring/bounded-diagnostic assertions. These are separate
from normal-package UI/PDF evidence. Foreign/stale/replayed authority and
script-only activation are source/permit/observer regressions, not newly claimed
normal-package fault injection. Existing unrelated workflow and installer/runtime
regressions were reused; no broad workflow or Firefox audit was repeated.

Initial attempts encountered a sandbox pytest-temp ACL error and a fixture
test-import/isolation ordering error before application launch. Evidence was
retained; the task-local focused run and corrected synthetic fixture passed.
Cleanup errors were not used to infer passing test bodies.

Independent review preceded the one replacement build and found no blocker.
Final read-only review independently checked all 1,152 recorded build-input
entries, all 1,578 source-archive entries, patch, embedded identity/native host,
PDF hash, installer binding and the 18-file distribution manifest. The native
Cancel/Return observations are the primary operator's record, not an independent
second physical reproduction. No review logs or private operational evidence are
included here.

## Retained artifacts and remaining limits

[SOURCE_BINDING.json](SOURCE_BINDING.json) binds the retained executable and
unsigned installer to the exact code commit, reviewed patch and original
snapshot. No rebuild was performed to insert a Git SHA. Original embedded
metadata truthfully remains the pre-commit base plus uncommitted snapshot.
This later documentation record is not present in the retained source archive;
it changes no payload/build input. Original artifacts and earlier evidence are
preserved locally; binaries, profiles, logs and databases are not in this PR.

Native keyboard focus/Print Cards activation remains **unqualified**: the
production observer's keyboard-click/repeat regressions passed, but one native
Shift+Tab attempt did not establish button focus. No repeated probing or owner
walkthrough was requested. Physical printer alignment, media handling and duplex
output are also unqualified; the PDF check proves selected content and page size,
not physical stock alignment. The Server technical-close limitation above remains
distinct from the two passing normal Local shutdown/reopen runs.

This is a Windows/WebView2-only repair. No shared template, Qt/Mac host,
dependency, schema, installer behavior or canonical icon is changed. Integrate
the separate shared/Qt correction deliberately, retaining legacy Server markup
compatibility and these evidence limits. Triggered CI results belong to the
draft PR; local native results do not substitute for CI. No merge, release,
publication, installation or additional UAT is authorized by this submission.
