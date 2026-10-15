# Audit evidence, coverage and limitations

Assessed source: `c2da7f2c5b7071685039e52f4938b8bb8c154b24` on
`develop/3.3.0`, version 3.3.0. Working tree initially clean. The full initial
tracked-file hash inventory is retained outside Git. Final inventory verification
is recorded below. No application, test or configuration edits are authorized.

## Evidence location and review method

Disk-backed evidence root:
`/home/drak/.cache/dlms-whole-app-audit-20261008`.
Subdirectories: `reports`, `logs`, `screenshots`, `runtime`. Only the three new
Markdown audit reports are intended repository changes. Synthetic quizzes,
profiles, databases, attachment fixtures and probe scripts remain outside Git.

One bounded independent reviewer used `gpt-6.1-sol` with High reasoning, formed
source-level findings before seeing the lead review's conclusions and did not run
duplicate full suites. After initial findings, matching/backup/advisory findings
were reconciled against source and probes; the reviewer independently agreed the
unexpected-trigger restore reproduction warrants high priority. Numeric scores
were formed from shared evidence after reconciliation. No Astra reviewer or swarm
was used. The available tools do not expose a reliable verification/setter for
the parent turn's model or Standard speed; no technical attestation of that UI
selection is claimed.

### Fresh shared gates

Existing project environment, not installed or upgraded:
`/tmp/dlms-pypdf-validation-20261005/development-env/bin/python`.
Host: Fedora 44 x86-64, Python 3.14.7, Firefox 157. Native Ubuntu/Windows binaries
were not executed during this audit.

The external `run_checks.py` sets `PYTHONDONTWRITEBYTECODE=1`, places disposable
runtime output under the evidence root, retains server/browser logs before normal
fixture cleanup and records descendant PID/UID/start-time/cwd/command plus memory
and swap observations. Cleanup verifies those identities before termination;
unrelated applications are not closed.

```sh
python run_checks.py nonbrowser -q -p no:cacheprovider -m 'not browser'
DLMS_RUN_BROWSER_TESTS=1 PYTHONDONTWRITEBYTECODE=1 \
  python run_checks.py firefox -q -p no:cacheprovider -m browser \
  tests/browser/test_critical_workflows.py --durations=10
```

`run_checks.py` is the external wrapper around `pytest.main`, not a modified test
suite. Optional capture directories were supplied through the repository's
existing `DLMS_*_CAPTURE_DIR` switches. Heavy runs do not overlap.

- **Non-browser:** 2,145 passed, 3,904 subtests passed, 328 deselected, six warnings,
  54.56 seconds. `logs/nonbrowser.log`. Warnings are upstream genanki/
  cached-property use of a deprecated asyncio API, not failed tests.
- **Firefox:** 315 passed, five failed, 1,657.53 seconds (27:37), no skips.
  `logs/firefox.log` retains every failure. Four are optional capture-directory
  FileNotFoundError failures caused by the audit setup; the fifth is the
  preset-button assertion discussed below. This is not a passing full gate.
- **Task-process cleanup:** `reports/nonbrowser-processes.json`,
  `firefox-processes.json`, `browser-focused-processes.json` and
  `matching-browser-processes.json` retain verified identities and report no
  matching task-owned processes remaining.

### Fresh focused assessment probes

`audit_probes.py` uses existing isolated test fixtures and actual app services;
`audit_trigger_probe.py` tests a disposable staged restore plus actual Study save.
No restore is promoted into an owner profile.

| Check | Actual result | Evidence |
| --- | --- | --- |
| Reduced-round matching Exam | Real `/record_attempt` returns 400 for a correct two-pair round from a five-pair newly generated bank; zero saved attempts. Actual Firefox input and native Submit confirmation reproduce 100% score with unsaved warning on ordinary HTTP | `reports/audit-probes.json`, `reports/matching-browser.json`, `logs/matching-browser.log` |
| Repeated fixed-second backup | Same final path; one ZIP; earlier synthetic file value replaced by later value | Same probe JSON/log |
| Unexpected SQLite trigger | Archive and staged current-schema preparation accepted; trigger retained; real Study save HTTP 200 but response rows fell from one to zero | `reports/unexpected-sqlite-trigger.json`, `logs/unexpected-sqlite-trigger.log` |
| Study history bounded query | 5,000 distinct one-response sessions; first page returns 20, 44 SQL statements; seven warm calls median 0.33 ms, maximum 0.56 ms | `reports/audit-probes.json` |
| Plan summary service | 1,001 source questions; seven warm calls median 49.43 ms, maximum 74.59 ms; 12 selected, 30 estimated planning minutes | Same JSON |

Performance numbers apply only to these warm local SQLite service fixtures. They
do not measure learner time, cold disks, browser/network latency, real OCR, very
large per-session corrections or multi-user load. No performance defect was
demonstrated, and no extrapolated throughput guarantee is scored.

### Fresh dependency evidence

Existing auditor: `/tmp/dlms-validation-audit-20261005/auditor/bin/python`,
pip-audit 2.10.1. No dependency installations or changes.

```sh
python -m pip_audit -r requirements-lock.txt --disable-pip --no-deps \
  --progress-spinner off --format json --output runtime-pinned-advisories.json
```

The same read-only command was run for `requirements-build.txt` and
`requirements-test.txt`. Important coverage limitation: this mode reports direct
pins and does not expand the nested `-r` files. The runtime scan covers 18 pins
and exits 1 for Werkzeug 3.1.8; the build scan covers two explicit tools and the
test scan one explicit tool, with no reported advisories. These together inspect
21 explicitly pinned packages; they are **not fresh resolved transitive build/test
audits**. Logs and JSON are retained, including the nonzero runtime result.

Official fixed range verified against
[Werkzeug GHSA-g6x2-hccm-hh4m](https://github.com/pallets/werkzeug/security/advisories/GHSA-g6x2-hccm-hh4m)
and [upstream release notes](https://github.com/pallets/werkzeug/releases).
Earlier clean temporary resolved audits are historical snapshots and cannot
override this fresh advisory. The Windows failure is not reproduced natively.

## Application-wide coverage map

All rows feed the unchanged category rubrics. A passing count is not completeness.

| Area | Inspected / meaningfully exercised | Negative paths and limits |
| --- | --- | --- |
| Study, Exam, History | Session/attempt services, generated HTML/runtime, full gates; correct/wrong/corrections, partial/matching/hotspot, Finish acknowledgement, timestamps and independent History | Ordered idempotency, late saves, lost acknowledgements, competing tabs, abandoned work, reset boundary; F2 matching variant and hotspot authority limitation remain |
| Learning Intelligence / Exam Plans | Learning scope, first-response recommendations, lineage, daily target/dedup/capacity services and real UI | Fixed clocks, work today, paused/hidden/no-plan/excluded/unavailable/past dates, DST/local dates, stale snapshots and publishing retries; planning estimates are not pass probability |
| Quiz/content management | Publication/editing/identities, Library, folders, bundles/packs, Law/Medical/IT, structured text/PDF/OCR and matching import | Failed publication/repair, changed/deleted source, duplicate identity, malformed PDF/archive, escaped input; synthetic OCR does not prove real-document recognition accuracy |
| Marks / Anki | Durable marks, supported-type boundaries, browser selection/download/practice and current/all-quiz routes | Ordinary non-secure LAN HTTP, retries, legacy adoption, stale sources, mixed types; generation/export do not clear marks or replace regular continuity |
| Dashboard / settings / themes | Real action controls, independent visibility and scoped defaults, all-hidden Settings reachability, history/sequence/recovery and 26-ID registry tests | Sparse/empty/error states, long labels, keyboard/focus/disclosures, narrow/zoom; image/gradient and screen-reader limitations remain |
| AI handoffs | Study launcher plus certification preview, copy/open provider and independent Settings prompts | Exact edited text, clipboard/popup fallback, no personal text in provider URL or auto-transmission; no provider/API calls or issuer acceptance inferred |
| Certifications / training | Schema-10 date service, scoped patch writers, progress, period order, attachments, routes/templates/Help and fresh tests | Different/equal/absent/cleared dates, preserved provenance/classification conflicts, stale receipts, exact 562-minute activity vs 540-minute allocation, partial credits, custom issuer/unknown goals, early renewals and retained historical evidence |
| Storage / backup / restore | JSON atomicity, SQL migration/bootstrap, semantic archive validation, staged replacement/journal, resource bounds and rollback tests | Interruption/failure injection, unsafe paths/expansion, old/new schema, attachments/settings; F1/F3 newly expose important missing cases |
| Security / runtime | Origin/session CSRF issuance and bounded renewal, upload content checks, safe serving and request limits | Cross-origin rejection, token expiry, original-request retry identity, authorization failures and LAN recovery; no exhaustive penetration/DNS-rebinding/native Windows test |
| Release / operations | Spec resources, clean exact-source preflight, immutable-source/fresh-stage/package verifier and CI/tooling tests | Platform-mismatch/dirty-source/unsafe-package negatives; native target acceptance stays separate |

Certification rules are treated as user-recorded goals or explicitly qualified
presets. The audit does not independently certify every issuer's current policy.
Unknown requirements do not earn compliance credit, and a full estimated bar is
not issuer approval or renewal. Source and tests preserve independent badge/PDF
roles; View certificate does not use a logo or old-period document as current.

## Critical evidence quality

- `tests/test_certifications.py:1063–1211` verifies independent dates, clear versus
  omit, classification conflict, transaction failure, process exit during migration,
  repeat startup, old-writer guards and old/new backup staging. The interruption
  test checks durable version/state afterward, rather than only mocking success.
- `:1236–1267` checks partial period edits preserve omitted attachments/requirements/
  allocations and failed receipt writes roll back. Exact duration fixtures keep
  562-minute activity and older 540-minute contribution/submitted/accepted values
  separate. Displayed estimates are not summed workflow-stage credits.
- Real Firefox expiry/recovery integration uses a controlled signer clock across
  the unchanged one-hour token lifetime on ordinary HTTP `dlms-http.test`. A
  50-question wrong-first/correction flow retains 75 ordered responses and first
  misses, handles save/finish acknowledgement loss and proves acknowledged Finish.
  This is substantially stronger than a mocked HTTP-success-only assertion.
- Restore and publication suites have real disposable data and injected failures.
  Nonetheless, trigger inventory and reduced matching variants escaped them;
  those gaps limit regression-confidence scores despite the breadth of tests.

## Reused evidence and platform boundaries

The earlier date safety review under
`/home/drak/.cache/dlms-certification-dates-review-20261008` demonstrated
compatible old source refusing schema 10 and rollback through a disposable
pre-upgrade copy. Those critical source-level results are reused; current fresh
non-browser tests also exercise refusal/interruption/restore contracts. No old
native Windows binary is tested. Prior full-gate totals are not substituted for
the fresh current-source run.

GitHub CI for this exact revision is successful:
[run 37858825041](https://github.com/drakahari/DLMS_next/actions/runs/37858825041),
created October 8, 23:19:54 UTC. Its Ubuntu/Python source CI is not hosted Firefox
or multi-platform native acceptance. No workflow state was changed.

The owner reports accepting an Ubuntu 24.04 package built from the assessed
revision. The existing archive was independently checked read-only with:

```sh
python tools/verify_release_package.py \
  /home/drak/DLMS-3.3.0-ubuntu24.04-x86_64.tar.gz --source-root .
```

Result: **Verified release package** (structure/support-asset verification only;
no `--smoke`, extraction, rebuild or runtime launch). SHA-256:
`4b6bf36503cca7a59c0fd339eaf0216f0ad49f6251647f2f04e5cdcd6c6bb4be`.
Evidence: `logs/ubuntu-package-structure.log`,
`reports/ubuntu-package-sha256.txt`. Source provenance is owner-reported; this
structural check does not independently bind executable bytes to the Git hash.
An exact native acceptance log was not located. Windows/macOS/other Linux targets,
signing/notarization, icons in native shells and downloaded final assets are
unqualified. Existing fake-package tests verify tools, not actual platform UAT.

## Actual UI evidence

Representative fresh actual-app images were inspected, not treated as design
mockups. Captures use isolated sample data. Paths below are relative to the audit
evidence root:

- `screenshots/study/study-dashboard-light-1440.png`
- `screenshots/study/study-dashboard-dark-1440.png`
- `screenshots/study/study-dashboard-ethereal-360.png`
- `screenshots/study/study-history-light-360.png`
- `screenshots/csrf/pending-refresh_failed.png`
- `screenshots/plans/state-ready-dark-1440.png`
- `screenshots/certifications/detail-light-1440.png`
- `screenshots/certifications/detail-ethereal-390.png`

Additional inspected images:

- `screenshots/certifications/dates-summary-390-light.png`: three distinct dates,
  unclassified legacy warning, exact 9 h 22 min and estimated credit label.
- `screenshots/certifications/native200-detail-dark.png`: native 200% (`dpr=2`,
  viewport width 683), wrapped actions, visible focus and unknown-goal state.
- `reports/firefox/test_dashboard_and_study_history_action_controls[light].png`:
  live focus tooltip and long active-plan title.
- `screenshots/matching-correct-exam-save-rejected.png`: confirmed failure, not a
  proposed design or successful-save screenshot.

Observed strengths: readable wrapping, visually dominant study action, separate
regular continuity and generated practice, honest finished/undated states,
non-color feedback and retained failed-save actions. Native-200% and additional
date-flow captures are inspected and listed in the final validation addendum.
Not every screenshot, every theme/state combination or uploaded image was visually
accepted. Automated all-theme contrast/focus tests complement representative
inspection, not full accessibility certification. Manual screen-reader,
physical touch/alternate input, native Windows Firefox, Safari and other browser
engines remain untested.

## Final validation addendum

The full gate's four capture failures occur at `test_critical_workflows.py:15534`
and `:15837`, attempting to write into missing optional `actions`/`certifications`
folders. The folders were subsequently prepared without changing repository
tests. The fifth fails at `:16107`: after setting `lpic-membership` and dispatching
change, `#applyCertPreset.disabled` is still true. The retained image shows the
selected LPIC route and new requirements document. A DOM-presence check before
deferred-script readiness is a plausible timing seam; the original observation
does not prove that explanation or a stable application defect.

One affected-only rerun ran the three Dashboard/Study History themes, dark trophy
workspace and preset case: **all five repository cases passed** in a combined
37.16-second probe run. It does not resolve the intermittent assertion or replace
the failed complete gate. No full-suite repetition was performed, consistent with
the shared-run instruction. Tests/assertions/timeouts were not changed.

That combined run also contained a new external matching reproduction which timed
out because the audit probe supplied its Firefox native-prompt capability outside
the required `alwaysMatch` envelope; the confirmation was dismissed and no Exam
request left the browser. Its failure log/image remain in `logs/browser-focused.log`
and `reports/browser-focused`. Correcting **only the external probe** and requiring
an observed accepted native prompt produced **one passed negative-path check in
2.30 seconds**. Two unknown-browser-marker warnings arose because the external
test is outside the repository pytest root. The expected HTTP 400 is a reproduced
application defect, not a successful Exam save. `logs/matching-browser.log` and
`reports/matching-browser.json` retain the actual response without tokens/cookies.

The full Firefox resource observer recorded 331 samples; minimum MemAvailable was
13,691,388 KiB (about 13.1 GiB). Swap was nearly full throughout; pswpin grew by
2,533 pages and pswpout did not grow. These observations do not establish resource
pressure as the cause of any failure. No heavy runs overlapped, no host settings
were altered and no unrelated application was terminated. Every completed runner
reports zero verified descendants remaining.

Final tracked-source hash verification, whitespace and report inventory are
recorded in the audit-root `reports/final-inventory.json` and `report-sha256.txt`.
Those manifests include only evidence, not modifications to the assessed code.

## Subsequent remediation evidence

The authorized source fixes and new regression evidence are recorded in
[the remediation report](remediation.md). Original findings, scores and failed-run
evidence above remain historical; this is not whole-app re-certification or
acceptance of rebuilt binaries. Final candidate validation is recorded there.
