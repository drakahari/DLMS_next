# Six-item daily-use repair — source review

Base: `bfdffb720f743e9d720cd07292ec7e1ec325e059`. Branch: `fix/six-item-daily-use-20261019`. Original review snapshot subsequently committed as `fab0fd868dd70fd78930966f96ccfd8a23786b88` in draft PR #23; no candidate build, installed change, history migration or recovery tool.

## Disposition

| Finding | Result and applicability |
|---|---|
| 1. Selected Q2+Q4 AI clipboard | A source-Qt reproduction found a definite exact-text defect: textarea normalization copied 545 rather than 556 bytes from a CRLF-containing prompt. The synchronous helper now supplies the original text through the copy event, requires that event plus successful copy command, cleans up/restores DOM focus, and gives visible copy-failure guidance. Native action/origin/browser authorization is unchanged. Local source Qt (Python 3.14.8 / Qt 6.11.2, matching the existing Qt build pin) verifies exact single443/combined556 bytes, pointer/Enter/Space, scripted dispatch refusal, simulated denial and unchanged records. The owner's separate two-byte `do` observation was **not reproduced or causally explained**. No normal-package/physical Wayland acceptance of this patch. |
| 2. Windows Avery POST/body | Confirmed Windows Local transport defect in the supplied native report and source. No Windows host repair claimed here: the current single-controller implementation needs a narrowly owned original-request destination with equivalent policy/lifetime enforcement. See WINDOWS_HANDOFF.md. Native Server remains unverified. Qt/Mac request-preserving transport stays unchanged; supplied Mac rendered-Avery pass is reused. |
| 3. No-op Rebuild/Study Resume | Shared source repair preserves the original JSON bytes only when the full ordered ordinary/matching assessment matches canonical records after filling explicit absent defaults (and absent source fields). HTML still rebuilds through existing staging/promotion. Genuine canonical edits still regenerate and refuse stale fingerprints. No fingerprint/session/revision rewrite. Existing authoritative hotspot path is retained. |
| 4. Missing Marked questions navigation | Shared normalizer now includes the existing GET destination immediately before Anki, including pre-seeded menus. The destination reuses the existing sidebar macro/normalizer and narrow toggle, with current-page state. Qt Local Settings admits only this additional exact ordinary GET route. Marks, selection and export handlers are untouched. |
| 5. Mac signature/Finder metadata | Supplied evidence identifies an external test-wrapper/procedure issue; the candidate payload itself passed strict verification. Exact wrapper generator is unavailable here. MAC_HANDOFF.md specifies fresh staging, targeted metadata handling before signing, checked verification-before-open and an intentional failure control. No native correction or payload rebuild claimed. |
| 6. Windows full-path Save As | Cause remains unresolved inside the native dialog. Successful basename saving used a different directory. No chooser/publication policy is relaxed. WINDOWS_HANDOFF.md gives the equivalent-directory diagnostic before any fix. |

## Content/recovery boundaries

Rebuild comparison includes response keys, choice/pair order, source/media metadata and question text, not titles or grading surrogates alone. For represented assessment content, it never ignores unknown question/choice/pair/source fields: an item with unprovable content is refused with prior files retained. Incomplete canonical answers/pairs, corrupt/non-object/non-JSON metadata, reserved media overrides, absent or invalid required local images and unsafe artifact types are refused before publication. Complete ordinary canonical records can still regenerate absent/broken derived JSON; this does not reconstruct missing hotspot authority or recover damaged historical quizzes. Unknown/unsupported states are kept, not deleted or migrated. Valid real edits deliberately invalidate stale current Resume.

## Focused evidence

- Source contracts: 87 passed, 34 subtests — current ordinary/matching byte identity, new HTTP-client Resume/completion/idempotence, genuine edit refusal, media/metadata/answer absence, unknown nested content, partial results, failed staging/publication, navigation, existing Study/hotspot contracts and AI sequence contracts.
- Qt/host boundary contracts: 133 passed — stale/native AI action lifetimes, exact-origin navigation, Settings path/policy, themes and shared WebView2 AI contracts. These are source-level checks, not native Windows execution.
- Real Firefox/shared UI: two focused tests pass — new quiz/acknowledged partial Study, two Rebuild actions, exact raw/record preservation, Resume, one marked question reachable through pre-seeded and generated sidebars, Enter/current state, plus real clipboard-event exact text and denial feedback. Narrow keyboard/menu checks are included in the final run.
- Source Qt Local: original real review handler reproduced the 545/556 mismatch; corrected handler copies exact 556 via pointer/Enter/Space, keeps the intended Q2+Q4 only, refuses scripted browser dispatch, exposes simulated copy denial and preserves records. Final browser adapter is intercepted; no provider is contacted or automatically pasted/submitted. Offscreen evidence does not establish physical focus, compositor clipboard behavior or full rendered appearance.
- Source Qt synthetic Server control: the single-question async clipboard write remained pending before the combined action. Waiting for the native page-exposure boundary did not resolve it. This run is **blocked/unresolved**, not a Server-copy pass or an established native-platform defect. Remote permissions were not changed; the failed traces are retained. Existing Server/save/isolation evidence is reused only for unchanged code, not to qualify this selected-copy branch.

Failures and test-controller corrections are retained separately. The first low-level fixture omitted the playable `correct` field and created a directory at the portal-file path; the new fixture now matches actual authoring. Browser iterations corrected an initial in-memory-versus-durable assertion, native-confirmation session configuration, an incorrect seed-failure expectation and headless initial-tab focus. The final narrow test uses actual Tab traversal rather than programmatic focus racing the existing delayed first-focus callback. A later failure identified the genuinely absent destination sidebar, which is repaired here. An attempted existing Xvfb runner was unavailable (exit127); nothing was installed. No assertion was removed to hide a runtime failure.

## Reproduction commands

Run from the reviewed source tree using existing pinned environments; no new dependencies:

```sh
python -m pytest -q -p no:cacheprovider tests/test_rebuild_current_identity.py tests/test_navigation_layout.py tests/test_study_sessions.py tests/test_hotspot_preservation.py tests/test_rebuild_safe_diagnostics.py tests/test_ai_combined_launch.py
QT_QPA_PLATFORM=offscreen python -m pytest -q -p no:cacheprovider tests/linux_windows/test_action_lifetime.py tests/settings/test_sidebar_palette.py tests/settings/test_desktop_policy.py tests/server_mode/test_navigation_surface.py tests/webview2/test_ai_contract.py
DLMS_RUN_BROWSER_TESTS=1 python -m pytest -q -p no:cacheprovider tests/browser/test_critical_workflows.py -k 'current_study_rebuild_and_marked_sidebar or selected_ai_exact_copy_event'
QT_QPA_PLATFORM=offscreen python -m tests.six_item.gui_clipboard --profile sixclip_unique --output /absolute/new/task-evidence
```

The last command uses a fresh disposable profile and the existing QtChecks controller, with final browser dispatch intercepted. It refuses an existing profile/output. Optional `--server` starts only a task-owned real shared WSGI server and uses guarded mode switching, preserving failures rather than treating blocked writes as passes.

## Minimal platform continuation after source review

1. Fedora: one affected normal candidate, original physical selected-Q2+Q4 clipboard/readback check without submission, new partial Study → Rebuild twice → close/reopen/Resume, and shared/natively captured Marked navigation. Qualify Server combined copying separately; investigate its pending clipboard write before changing permissions. No broad audit restart.
2. Windows: implement/review Avery-only original-request transport in the native host with policy/lifetime ownership; run its Local/synthetic Server control and the same-directory Save As diagnosis. Then qualify the shared patch on that host. Do not infer this from Fedora.
3. Mac: apply/test only the external wrapper procedure, preserve the accepted payload, and qualify the shared patch on an authorized native candidate. Reuse the accepted Mac Avery result. Overwrite refusal, omitted Rebuild/new Server-save checks, exact clipboard bytes, signing/notarization, upload protection and other native limits remain as recorded in MAC_HANDOFF.md.

These are batched native handoffs, not a request for continuous owner UAT. Historical recovery, physical printing/duplex, full accessibility, external provider submission and distribution qualification remain outside this patch. No replacement candidate is ready to claim all six findings resolved.

## Narrow follow-up: CI-discovered derived stub refusal

Runtime correction: `c1268daaf8a1dab2919b912c117a1ac4f86ea6c6`. Prior push/PR application CI failed the existing `test_rebuild_all_regenerates_choice_matching_and_generated_quiz_pages_only`: its intentionally unusable `[{"stale":true}]` derived file was refused despite complete canonical records. This was an overbroad runtime refusal, not an obsolete assertion; the assertion remains unchanged. Prior failed runs and the original review snapshot are retained.

The correction regenerates only wholly flat marker-only derived arrays with no assessment-bearing keys, after existing canonical readiness, metadata/image and hotspot-authority checks. Mixed represented/stub content and unknown nested content retain conservative refusal. Existing comparison, exact-byte preservation, staged publication/rollback and real-edit stale-Study checks remain in force. No schema, fingerprint or history rewriting.

Focused validation (synthetic source only): the exact failing test passes unchanged; the five affected test files pass **73 tests and 12 subtests**. Boundaries cover choice/matching stub regeneration, missing canonical answers/pairs, unknown/mixed/nested/spatial authority, hotspot marker-only refusal, unchanged bytes/current Resume, genuine edits, partial results and failed publication. The rollback test now asserts the intended publication fault actually occurred. Independent read-only design/final review found no blocker. No new browser/native/package claim or rebuilt candidate; handoff source pins above are updated separately from old artifact identities.

```sh
python -m pytest -q -p no:cacheprovider tests/test_quiz_mutation_atomicity.py::QuizMutationAtomicityTests::test_rebuild_all_regenerates_choice_matching_and_generated_quiz_pages_only
python -m pytest -q -p no:cacheprovider tests/test_quiz_mutation_atomicity.py tests/test_rebuild_current_identity.py tests/test_hotspot_preservation.py tests/test_rebuild_safe_diagnostics.py tests/test_study_sessions.py
```
