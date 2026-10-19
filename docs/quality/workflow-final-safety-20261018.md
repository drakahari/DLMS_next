# Final bounded Fedora safety audit — 2026-10-18

Base `bfdffb720f743e9d720cd07292ec7e1ec325e059`; branch `docs/workflow-recovery-audit-20261018`. Four documentation/evidence files only, uncommitted. No runtime repairs, new build or repeated crash test. The original audit and prior reviewed snapshots remain unchanged.

**Recommendation: the shared source can freeze for combined platform builds within this bounded audit scope.** Required normal-package Server loss/close/reopen/retry, certificate/wrong-origin refusal, outage/Retry and pending-Local/backup switch checks now have evidence. No new application defect was established. This is not full workflow parity, qualification of new platform binaries, or acceptance of the still-unchanged published downloads.

## Candidate and evidence boundaries

Reused normal one-folder executable SHA-256 `e9023fa361fc0c20ce3b21f566ef3c99ecac72cee05a08c8cb26892ef58d7f95`. Its 183/184 embedded Python modules match current main; `desktop/marked_exports.py` differs only in the disclosed Anki terminal wording. Nine inspected recovery, shell, lifecycle and certification paths match exactly. Older bundled Help/manual text remains a known difference. No claim that the candidate contains the latest wording or documentation.

Fedora 44/COSMIC Wayland. Original Local interruption evidence uses disposable `finalsafety01`; the fresh continuation uses `finalserver01`, isolated HOME/XDG/cache/temp and the real graphical-session XDG_RUNTIME_DIR. A task-owned real DLMS 3.3.0 synthetic server, source `bfdffb7`, ran at `http://127.0.0.2:48061` with separate synthetic data. Explicitly selected/output fixtures use the task-created ordinary Documents folder. No production/installed/owner data was used.

The executable is normal and unchanged. Loopback CDP and exact-PID accessibility provide application-local control and observations. Save faults replace renderer fetch responses only after the real backend returned200; backup fault injection pauses a browser request. These are **fault-injected normal-package runs**, not unmodified end-to-end network events or source-Qt substitutes. The diagnostic remote-origin allowance is disclosed and does not qualify a vanilla hostile-content launch boundary. Source-Qt Server evidence remains supporting history, separately labeled.

The owner configured/selected the synthetic Server through the native menu, invoked its window-close controls, operated outage Retry and returned Local, and attempted the two pending-work switches. Owned native dialog buttons, web answer/Resume actions and supporting readbacks were controller-operated. The known inaccessible ShowMenu action was not probed again. These checks do not establish physical keyboard or general accessibility acceptance.

## Required checks and exact outcomes

| Check | Result | Evidence and limits |
|---|---|---|
| Server Study commit, lost acknowledgment, close/reopen, same-ID retry | Passed bounded fault-injected normal-package check | Event `77b1d138-7b74-4850-9a43-e2990cb7eefd`: exact original Study response and one credit survive. Resume in a separate process retries this same ID; facts unchanged. Study History shows the synthetic quiz. |
| Server Exam commit, lost acknowledgment, close/reopen, same-ID retry | Passed bounded fault-injected normal-package check | Attempt `2c0d49f2-a0d8-485e-8419-873b63f2274a`: selected B against correct A, 0/1, answer event and missed snapshot remain exact and occur once. Separate-process Resume retries the same ID; saved status and Exam History verified. |
| Server Keep open and explicit Close DLMS Desktop | Passed bounded normal-package check | Owner invoked window close twice. Controller captured the conservative warning and focused Keep open, selected Keep open and verified pending identity survived, then selected Close DLMS Desktop. Reopen retained Server/profile identity. Server remained separately running. |
| Local unchanged by Server use | Passed records/assets comparison | All32 canonical tables and Local quiz data/pages/config hashes match the populated pre-Server sentinel after returning Local. This comparison precedes the deliberate new Local answer used below. |
| Wrong-origin navigation | Passed bounded normal-package refusal | Renderer attempted another task-owned HTTP origin. No HTTP request reached that target; original configured origin remained. Final native status was Server unavailable; no Local fallback. Do not claim the transient specific refusal text remained visible. |
| Untrusted HTTPS certificate | Passed bounded normal-package refusal | Separate preconfigured disposable certificate profile received Chromium handshake net_error -202. Server failure/identity retained; no target HTTP content or Local database opened. No trust bypass/change. This is startup refusal, not owner-operated certificate configuration. |
| Outage → Retry → recovery | Passed owner-assisted normal-package check | Exact synthetic server was stopped; owner clicked Retry and confirmed refusal. Native capture retained Server unavailable/no fallback. Restart reused the same data/port; owner clicked Retry, reported Dashboard available, then explicitly returned Local. Server logs retain successful requests. Successful rendered Retry is owner-reported, not a controller screenshot taken before the return. |
| Pending accepted Local save → switch Server | Passed bounded fault-injected normal-package check | Event `ecd9a7f5-cfc5-4ea0-8685-e99d3fdc9db9` committed before synthetic acknowledgment loss. Owner selected Server; native refusal, Local mode and original pending ID were captured. Existing Retry resolved the original event with one response. |
| Pending managed backup → switch Server | Passed bounded fault-injected normal-package check | Native Save Backup As consent preceded a paused POST before dispatch. Owner selected Server; switch refused and destination remained unpublished. Release completed a valid ZIP with a matching saved status; all canonical tables unchanged. This proves the pending native-backup guard, not every import/maintenance phase or a mid-commit crash. |
| Previously held Local Study reply, orderly close/reopen | Reused passed bounded normal-package check | Event `a4f16760-9709-43f0-b162-c3317aee9fec`: saving state, truthful unconfirmed-close logs, post-drain checkpoint, original-ID Resume retry and one response/credit. No repeat of that test. |
| Previously interrupted committed Exam before checkpoint | Committed integrity passed; browser pending state absent | Attempt `96fe8a68-29b6-439d-9fff-24f751d98f9e`, 1/2 (50%), exact answers/miss/History once; all32 canonical tables unchanged. Pending record/Resume absent after reopen. Same-ID retry was not exercised in that interruption branch. No repeat crash. |

## Reviewed interruption diagnosis

The retained timeline is: backend commit → accepted journal cleanup → real HTTP200 → renderer deliberately withholds the acknowledgment → application-requested shutdown reaches pending quiescence → exact task PID receives SIGKILL before the new browser checkpoint completes → separate-process reopen retains the result, with no pending/Resume record.

The accepted Block A contract allows the durable committed result to be resolved by same-ID retry **or History** after journal cleanup. Chromium storage is a convenience, not the crash-durability boundary; the normal-close checkpoint is not a preexisting crash guarantee. The database already held the durable attempt identity and answers. History resolved this saved result under that contract. The disappearance mechanism of the browser pending state remains unresolved; this is **not a confirmed recovery-contract blocker**, automatic Exam reconciliation, or proof of a Chromium flush cause. A read-only review check found the retained snapshot structurally valid and matching its quiz fingerprint. The controller's expectation that Resume must always survive was stronger than the contract.

Preserve the discoverability observation: after that abrupt boundary, the player offered Select Mode without a pending warning; History still exposed the saved result. No lost-answer, duplicate-grading, universal crash-resume or power-loss claim is made. A future discoverability improvement would be separately scoped; no recovery tools or historical migrations were added.

## Evidence and retained failures

Private original evidence root: `.gate1/workflow-final-safety-20261018/`; continuation root: `.gate1/workflow-final-safety-20261018/server-completion/`.

- `normal/evidence/SERVER_{STUDY,EXAM}_{CREATE,REOPEN}.json`, `SERVER_CLOSE_SESSION.json`, server pending/retry/History captures: real committed facts, original IDs, truthfulness, Keep open/Close and separate processes.
- `normal/evidence/LOCAL_SERVER_PRESERVATION.json`, `LOCAL_BEFORE.json`, `LOCAL_FILES_BEFORE.json`: exact Local preservation across Server use.
- `normal/evidence/WRONG_ORIGIN.json`, `outage-retry-refused-native.json`, server restart logs; `certificate/evidence/CERTIFICATE_RESULT.json`: endpoint/failure boundaries.
- `normal/evidence/LOCAL_PENDING_{BEFORE_SWITCH,SWITCH_RESULT}.json`, `MANAGED_BACKUP_HELD.json`, `MANAGED_SWITCH_RESULT.json`: pending guards and backup outcome.
- `normal/controller/`: actual renderer faults, request pause/release, native-dialog actions, answer/Resume paths and readbacks. No runtime hooks shipped or modified.
- `RUNTIME_MATCH.json`, `PRESERVATION_ORIGINALS.json`, `CLEANUP.json`, `EVIDENCE_SHA256SUMS.txt`: source match, retained originals, exact-owned cleanup and evidence integrity.
- `pre-correction-snapshot/` preserves the original four-report patch `a0e390c9c584ff3d6c7070aca70d2e534ce99af29fbdab4ed0f05798cba42c5f`; the earlier three-report review and original interrupted fixture remain unchanged.

Harness failures are retained in the continuation notes and relevant readbacks: missing disposable-root setup/private directory permissions refused safely before useful launch; early mode assertion raced the owner's selection; an Exam retry observer initially accepted a transient null state before restored submission; wrong-origin observation expected transient/inaccessible text; backup completion expected “saved to” rather than actual “saved:”; the quiz has no direct Settings link and required Dashboard navigation. Existing committed actions were read back, not resubmitted to repair controller results. Not every transient terminal error has a separate archived log.

Task candidates are closed, both fixture servers stopped with exact identity checks, and no task candidate groups remain. The empty certificate fixture received exact-PID SIGTERM for cleanup; that is not orderly-close evidence. Main Local close used Dashboard confirmations; Server close used the owner's window control and native confirmation. Installed apps, owner profiles and unrelated processes were untouched.

## Stopping criterion and remaining qualification

The approved bounded safety batch is complete. Recommend source freeze for combined platform builds with the evidence limits above and unchanged regression evidence. No new full parent-row pass is inferred: the original129-row audit remains historical; its prior19 accounting stays16 bounded successes/three partials. Residual entries remain branches, not confirmed defects or mandatory freeze gates.

Still open: invalid endpoint/configuration Cancel/HTTP-consent decline; decline return Local; pending import, maintenance and download variants beyond the tested backup guard; timeout-specific loss and stale/token conflicts beyond inherited evidence; natural OCR/draft failures; external provider/Anki interaction; remaining lower-risk parser/settings/certification variants. Physical keyboard/accessibility/scaling, printer/duplex, power loss/real disk exhaustion and native Windows/Mac/Ubuntu/Omarchy qualification remain unconfirmed where previously listed. Existing source CI39164980036 is reused; no broad rerun, package/release build, push, merge, installation or publication occurred.
