# Missed Anki and bundle navigation repair — review candidate

Base public main: `384780bc246f7cb99cef7086f1810e159d6b5640`. Branch `fix/missed-anki-bundle-navigation-20261018`; Astra approved the reviewed 12-file repair for its assessed scope; source submission is authorized after the narrow message correction below. Documentation is a separate draft PR [#19](https://github.com/drakahari/DLMS_next/pull/19), original head `79071a4bba5cd2caa57727b48d824ad3a2385ffc`, Help-contract follow-up `b2dddcbbad348a6cc15ec53dc11e38346e7bed0d`. No merge, installation, production access or published-package replacement.

## F5: attempt-specific missed-question Anki

The existing Qt exception recognized only the marked-question page. Attempt review generated a Blob that was refused before native Save As. Original normal-candidate failure is retained; source policy and actual new normal Local/Server checks establish the path. A separate Firefox baseline found that the shared `/export/anki` receiver ignored explicit selected question numbers and returned all misses for the requested attempt. Thus browser transport worked, but selected-content fidelity also needed this bounded correction.

The repair reuses the existing isolated-world action observer and native export queue. Only the exact active `/review?attempt=<identifier>` document on the recorded Local/Server origin can request this path. The observer consumes one trusted top-document Anki button/link action bound to full document URL, exact canonical Blob URL, exact safe APKG filename and attempt-specific link. Script-only actions and trusted iframe actions cannot create the permission. Existing current-page/generation/dataset/feedback guards remain; no page receives a native command or filesystem API.

The page retains a labeled fallback link and reports preparation/request rather than saved success. Native completion, cancellation, refusal and unconfirmed outcomes use fixed strings; native paths/errors are not injected into remote content. The existing private download, native Save As, no-replace destination publication and focus behavior are reused.

The shared receiver filters an explicitly supplied nonempty integer subset against that attempt's saved missed rows before generation. Invalid or unavailable numbers refuse; duplicates do not duplicate notes and source order remains. An omitted subset preserves the existing attempt-only API behavior. Database records, grading, saved answer identities and historical state are untouched. This is not a migration or recovery tool.

## F6: Quiz Bundles narrow navigation

The shared template had a menu button but no applicable toggle handler. Actual Firefox and source Qt against the exact merged-base synthetic Server template reproduce the closed drawer after activation. The prior normal Qt Local reproduction remains retained.

One `data-settings-menu` attribute connects the existing button to the existing `nav-normalize.js` behavior. It restores toggle, aria-expanded synchronization, keyboard focus and Escape handling. No new navigation system, bundle filter, selected-ID or data logic is introduced.

## Focused evidence

| Layer | Result and limits |
|---|---|
| Original evidence | Original 129-row audit, 630 evidence files, 18 report files and both reviewed repair patches remain unchanged. Published Preview 1 still lacks later source repairs. |
| Baseline source | Selection regressions initially fail: explicit subset ignored. Baseline Firefox: attempt export returns two notes instead of the one selected; bundle hamburger fails to open. |
| Final source tests | 167 passed, 26 subtests, 4 skipped. The skips are Windows-only path cases on Linux, not Windows passes. Covers explicit subset validation/order, exact document/origin and stale-context policy, destination publication/lifetime and Server isolation controls. |
| Focused Firefox | 3 passed, 381 deselected: exact selected APKG/repeat, narrow bundle pointer/Enter/Space/Escape/focus/aria/wide navigation with selected IDs retained, and the existing marked initial/fallback/Avery browser control. Fresh-tab activation and actual document focus follow the existing browser harness pattern. |
| Final source Qt | Local and synthetic Server: initial, fallback, repeat, Cancel, collision/original hash unchanged, script-only fallback/button and trusted iframe refusal without Save As; explicit nonempty selected IDs retained through bundle pointer/Space/Escape/focus controls. Native chooser answers are simulated; offscreen images are not visual acceptance. |
| Normal frozen Fedora candidate | Actual native TXT import and Save As in new synthetic data; Local/Server initial/fallback/repeat each contain only selected question 2 and its saved correct answer. A distinct unrelated Server attempt is excluded. Actual Cancel and existing-name refusal leave the original destination unchanged; page remains usable. |
| Normal control workflows | History-wide missed deck and marked deck save successfully in both modes. Bundle drawer opens; Enter/Space/Escape, aria and focus work through complete app-local CDP input; selected IDs survive and wide navigation works. Widths 711/1280 use explicitly labeled renderer emulation. Physical keyboard/native scaling acceptance remains open. |
| Preservation/reopen | Entire Server database unchanged across attempt exports. Quiz/choice/attempt/missed records remain unchanged by the Local export paths; intentional later Study-mark setup is recorded separately. Entire Local database and original profile UUID/origin remain exact across Server-mode operation and separate-process Local reopen. |

Normal executable SHA-256: `e9023fa361fc0c20ce3b21f566ef3c99ecac72cee05a08c8cb26892ef58d7f95`. One task-only one-folder candidate, built once from pinned offline Ubuntu24-compatible inputs. Build-input manifest digest `81525b238b494c21977bcc61672ed60446f94e480ab9e6a0738874a0851c74c3`. Embedded verification:184 modules,247 assets, no test modules;458 ELF files and no Ubuntu24 glibc import blockers. This is Fedora/COSMIC Wayland acceptance within its stated diagnostics, not native Ubuntu/Omarchy qualification.

Loopback CDP/readback and exact PID/start-time accessibility exercise the normal unchanged executable; Qt adds diagnostic remote-origin allowance. Native mode configuration was prepared as an explicit synthetic fixture while the app was stopped, not claimed as fresh owner/menu interaction. Unchanged earlier owner-operated menu/ordinary Server-close evidence is reused. Normal Local closes through Dashboard confirmation/alert; the final task-only Server process group is verified and terminated for cleanup after settled tests, not counted as orderly Server-close acceptance.

The synthetic Server serves this repaired shared page/receiver/template. Existing older deployments need that shared update; Desktop never rewrites remote pages or headers to conceal the defect. Windows WebView2 has a different transport adapter; native Windows/Mac qualification is not inferred from Qt results.

## Retained failures and qualifications

- Qt normalizes unreserved URL escapes before native policy inspection. The first unit expectation that `%6f` remained encoded was incorrect. Corrected tests retain genuine encoded-separator/extra-query refusal and explicitly test canonical same-identifier behavior; isolated-world full-URL/action binding remains enforced.
- Initial Firefox input targeted an unfocused original context, delivering key events without the expected activation. A fresh activated tab with `document.hasFocus()` fixes the harness; Enter/Space assertions remain.
- Offscreen source Qt cannot return arbitrary JS objects/arrays directly through this evaluator. Final controller serializes them and asserts an actual nonempty selected-ID list. Earlier decode failures remain retained; normal CDP checks independently compare real arrays.
- Open drawers can cover the original pointer trigger. Source checks use the existing Escape close path rather than pretending an obscured trigger was clicked.
- The normal fixture initially omitted completion dates; history-wide export correctly found no completed attempts. Only those task-created rows were corrected, original fixture SQL retained. A second controller acted before quiz/marked eligibility readiness; waits were corrected without weakening application guards. Completed exports were not blindly repeated.
- Normal CDP Enter/Space initially omitted character fields; the private controller now sends complete app-local key events. This is not a runtime fix or physical keyboard acceptance.
- Offscreen GPU/context warnings are retained. No sandbox, acceleration, security header or global logging workaround was added.

The separate documentation PR's original Linux/shared CI jobs failed on ten obsolete wording assertions in two Help contract methods; Windows adapters passed. Its original reviewed submission is preserved. The authorized follow-up scopes those methods to edition-specific lifecycle/download/network sections, including the masked public Internet capitalization mismatch. Local Help validation:31 tests and755 subtests passed. Triggered CI for that separate follow-up is tracked independently; no protection bypass or assertion weakening.

## Remaining work

Astra approved the exact reviewed repair patch `0c1c254c28e82caf3490615cf7214916a694aecc728f8998c488070aba9a3045`; the owner separately authorized the narrow post-review message correction and source submission. Keep historical recovery, migrations, other audit branches, external applications, physical printing/duplex, full accessibility, native Windows/Mac/Ubuntu/Omarchy and published-download qualification open. No new runtime repair outside F5/F6 was included.


## Post-review correction and evidence boundary

The only post-review runtime change corrects attempt-review reassurance for all terminal outcomes, including lowercase refusal/unconfirmed text: **Your saved Exam result and history are unchanged.** Marked-question wording remains unchanged. A fixed-message helper supplies those strings; action consent, origin/document checks, export queue, publication and shared selection/navigation behavior are unchanged.

Focused revalidation:50 tests passed in `test_output_boundaries.py` and `test_attempt_exports.py`, including two new refusal/unconfirmed cases. The accepted167-test/26-subtest result, three Firefox tests and normal Fedora Local/Server records above are reused for unchanged behavior. The executable hash above belongs to the earlier reviewed candidate: **it does not contain the corrected terminal wording**. No package was rebuilt for this source submission.

Astra independently verified the12-file inventory, candidate/source correspondence, explicit subset/invalid/empty/omitted selection behavior, six normal exported APKGs, both export controls and shared menu behavior. The original18 audit reports,630 audit evidence files,149 repair evidence files and both earlier repair patches remain preserved. Original reviewed snapshots stay local; only this portable summary, findings ledger, implementation and synthetic tests are submitted.
