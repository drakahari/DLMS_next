# DLMS quality reassessment — October 9, 2026

## Executive assessment

The six bounded remediation/documentation findings now have substantiated
current-source closure. No new serious defect was demonstrated in this focused
reassessment. This does **not** repeat the whole-app audit or certify the absence
of defects. The unchanged historical rubric yields **9.337/10 (9.34)**;
the unchanged mature-product rubric yields **9.000/10 (9.00)**.
Neither score returns to September's result, and neither was formed to target it.

Continued **controlled production testing is supported**, with trusted inputs,
a verified separate backup and a compatible rollback plan. **Unqualified public
release across supported platforms remains unready**: native target acceptance,
production-filesystem restore behavior and several populated certification
backup categories remain unverified. Current-source documentation is newer than
the tested package. A numerical score does not override those release gates.

Only this report and its [verification record](verification.json) are new.
Application code, tests, dependencies, settings, personal data, prior reports,
packages and normal services remain unchanged. No full suites, browser sessions
or exploratory adversarial tests were launched.

## 1. Scope, revisions and evidence reuse

| Evidence layer | Exact provenance | What it establishes |
| --- | --- | --- |
| Original whole-app assessment | `c2da7f2c5b7071685039e52f4938b8bb8c154b24` | Historical findings and scores, not the repaired candidate. |
| Completed remediation | `57d536f9bb20f91e8b275555e8bbfad6f0d6e83d` | Committed restore/matching/backup/dependency/test fixes and source gates. |
| Current source assessed | `develop/3.3.0`, `dcfe729be539ca6e16da621aa2089b6d48ab5969`; initially clean | Same runtime and locks, plus committed manuals, Help, screenshots and documentation tests. |
| Executed Ubuntu-targeted artifact | `DLMS-3.3.0-ubuntu24.04-x86_64-57d536f9.tar.gz`; SHA-256 `0bf6d9546a6f8faeae807e8ed54e420d337a6240a8b87edc28a7aacbaa074dcb` | Exact supplied artifact successfully executed/restored on Fedora. It reports version 3.3.0, without an embedded commit-reporting interface. |
| Build-source association | Owner-reported `57d536f9`; package identity and source/tooling records agree | Not an independently reproducible build attestation. No separate native build log was located in the supplied evidence. |

The [original findings](../2026-10-08/README.md),
[scorecards](../2026-10-08/scorecards.md),
[evidence](../2026-10-08/evidence.md) and
[remediation](../2026-10-08/remediation.md) are retained unchanged.
The two audits are **different rubrics**, not independent repeated scores to
average. Narrative category definitions, weights and /10 scales are preserved:
the September 5 twelve-category [historical rubric](../2026-09-05-product-quality-assessment.md#weighted-scorecard),
and September 13 eight-category [mature rubric](../2026-09-13-product-quality-assessment.md#stricter-mature-product-assessment).

Verified historical totals: October 8 **8.894 → 8.89** and **8.685 → 8.69**;
September 23 **9.792 → 9.79** and **9.510 → 9.51**, in the
[historical](../2026-09-23-historical-product-quality-assessment.md) and
[mature](../2026-09-23-mature-product-assessment.md) reports.

### Hash/provenance checks performed now

- Read the 838-file final remediation gate manifest. At `57d536f9`, 837 hashes
  match; the sole difference is the finalized remediation report, explicitly
  documented after the gates. At current HEAD, runtime/dependency/regression
  files still match. Differences are documentation/Help/assets and the browser
  file's 56-line appended documentation check.
- Verified the old browser suite is an **unchanged byte prefix** of the current
  file; no previous assertion was edited by the later documentation commit.
- Verified all **57/57 documentation candidate hashes** match current files.
  Runtime/build/test locks are unchanged since `57d536f9`.
- Recomputed the package SHA-256. Its extracted executable matches the archive
  member. Read its PyInstaller archive metadata without running the application:
  bundled `werkzeug-3.1.9.dist-info/METADATA` reports version 3.1.9.
- Read three bundled Help files: maintenance, Learning Intelligence and Getting
  Started exactly match `57d536f9`, not current source. Thus later Help corrections
  and screenshots are **not retroactively credited to the package**.
- Inspected actual fixed code, regression assertions, retained final logs,
  independent remediation review and both acceptance verification records.
  Rechecked the specific official Werkzeug advisory; did not perform a new
  all-dependency scan, issuer-policy review or native-platform test.

This reuse establishes applicable evidence, not a fresh full-gate pass at HEAD.
The requested Sol 6.1 High/Standard setting is not independently attestable
through these execution tools; no model/speed technical attestation is claimed.

## 2. Finding-by-finding closure

| Finding | Closure and direct evidence | Residual risk / packaged boundary |
| --- | --- | --- |
| **F1 / P1: unexpected SQLite programs can delete acknowledged Study facts after restore** | **Closed for the demonstrated source defect.** [Catalog validator](../../../dlms/persistence/schema_programs.py) accepts only canonical date guards and supported ordinary schema constructs; rejects unexpected triggers/views/virtual tables/generated columns/CHECK/default/index programs. [Read-only validation](../../../dlms/services/backups.py) checks programs before integrity/semantic work; [bootstrap](../../../dlms/persistence/database.py) checks before migrations or queue-invalidation writes. `trusted_schema=OFF`; programs are rejected, not stripped. [Regressions](../../../tests/test_restore_schema_programs.py) verify unchanged bytes before staged writes, active Study/recovery preservation on rejected upload, literal-sensitive guards, startup rejection and durable post-restore saves. Pre-fix fixture failed; final full gates include the unchanged tests. | It does not authenticate backup records, prove every possible table/FK alteration safe or protect against SQLite implementation vulnerabilities. Both packaged tests prove legitimate backups/Study persistence, **not malicious-program rejection in the executable**. No OS code-execution claim. |
| **F2 / P2: correct reduced matching Exam displays 100% but save returns 400** | **Closed for supported round construction/save.** [Attempt validation](../../../dlms/services/attempts.py) validates unique source indexes, configured size/direction and local selections, recomputes correctness, persists variant and uses the same round in missed text. [API regressions](../../../tests/test_attempt_validation.py) cover tampering, incomplete answers, reversed rounds and legacy acknowledgement compatibility. [Firefox regression](../../../tests/browser/test_critical_workflows.py) covers reduced/full/random rounds, resume, original payload on lost acknowledgement and exactly one saved 100% attempt. The earlier package acceptance independently saved a two-pair reversed round from five stored pairs, then restarted and round-tripped it. | Old reduced self-contained pages lacking identity require owner-controlled updating; no historical identity is guessed. Exam hotspot authority remains a separate documented limitation, not repaired by matching changes. |
| **F3 / P2: same-second backups overwrite snapshots** | **Closed for nonreplacement/concurrent creation on supported filesystems.** [Backup service](../../../dlms/services/backups.py) uses exclusive private temporary files, validates/fsyncs completed ZIPs, and atomically publishes with `os.link`; an existing name causes bounded retry, never replacement. [Regressions](../../../tests/test_backup_collision_safety.py) check changed contents under fixed time, four simultaneous complete/restorable archives, forced repeated names and publication failure preserving earlier bytes. Package-created backups were restored through the UI in both acceptance tasks. | Hard links are required; unsupported filesystems fail safely. Fedora fixture/package results do not establish NTFS/FAT/network/production-volume behavior, every cross-store concurrency condition or power-loss atomicity. |
| **F4 / P2: Werkzeug GHSA-g6x2-hccm-hh4m** | **Closed for this specific pinned dependency issue.** The [official advisory](https://github.com/pallets/werkzeug/security/advisories/GHSA-g6x2-hccm-hh4m) still identifies affected <3.1.9, fixed 3.1.9: Windows/NTFS special-device empty-stream reads can hang. Runtime minimum, canonical lock and capture pin agree; nested build/test sets resolve 3.1.9. Retained resolved scans cover 21 build and 22 test dependencies with zero findings. [Regression](../../../tests/test_remediation_dependencies_and_docs.py) tests the Windows path branch without opening a device. The verified executable contains 3.1.9 metadata. | No native Windows/NTFS exploitation or binary acceptance was run. Old Windows binaries are not cured by source pins. Resolved audits are dated snapshots, not a claim that all current/future advisories are absent. |
| **F5 / P3: stale five-theme manual and broader manual lag** | **Closed for current-source coverage.** [Coverage checklist](../../user-manual/UPDATE-COVERAGE-3.3.0.md) maps user tasks to actual code. Manuals/Help cover 26 registry-derived themes, dashboard/history, Study days, plans/profile, certifications/training/AI, three dates and backup/reset scopes. Fifteen changed/new actual sample-profile images, image enlargement, link/anchor checks and independent documentation review support the refresh. All 57 candidate hashes match HEAD. | The `57d536f9` package retains pre-refresh Help/README. Use current source manuals for corrected restore/reset guidance during controlled testing. Package F5 closure is **partial**, not complete. Historical screenshots remain labeled, no canonical PDF/export pipeline exists, and learner-task success is not measured. |
| **G1 / validation gap: preset readiness and capture failures; later Library race** | **Closed for reproduced test boundaries.** Controlled script interception demonstrates DOM presence before handler readiness. Corrected waits use post-navigation identity/document completion with original assertions/timeouts; shared setup creates nested capture directories. Library synthetic-input readiness was similarly reproduced, not presumed from a screenshot. Retained final pair passed **2,173 tests + 3,916 subtests and all 325 enabled Firefox cases**. | The original spontaneous pre-input timing was not captured; controlled reproduction proves the missing boundary, not every detail of that occurrence. One full pass after a demonstrated synchronization fix closes this specific issue, not all possible future flakiness. The later documentation-only append has focused coverage, not a new complete gate. |

Source closure was independently examined here through code/test/hash inspection.
The separate retained remediation reviewer found and verified correction of the
missed-snapshot mismatch, legacy retry compatibility and writable ZIP flush
access. Its [review record](/home/drak/.cache/dlms-audit-remediation-20261008/reports/independent-review.json)
reports no substantiated remaining issue within that batch; it is supporting
evidence, not a substitute for this reassessment.

## 3. Validation evidence and its limits

| Retained check | Observed result | Applicability |
| --- | --- | --- |
| Final remediation non-browser gate | 2,173 passed; 3,916 subtests; 333 deselected; six existing deprecation warnings | Exact final runtime/locks/regressions in `57d536f9`; unchanged in current source. |
| Final remediation enabled Firefox gate | 325 passed; 1,698.66 seconds; no skipped coverage counted | Same runtime and original browser checks; retains all-theme, LAN HTTP, expired CSRF, recovery, 50-question wrong-first/correction, narrow/native-200% and date tests. |
| Documentation final targeted checks | 44 passed; 1,380 subtests | All 57 current documentation files verified; local links/anchors/images, navigation/labels. |
| Documentation final Help Firefox | 12 passed | Actual Help rendering, representative themes, keyboard/enlargement, lazy images, desktop/narrow widths. |
| Documentation workflow captures | 14 passed | Current UI samples for dashboard/history/plans/profile/certifications/date/duration; application logic unchanged. |
| Original package restore acceptance | 31 scripted groups passed | Actual supplied executable, two fresh isolated profiles, legitimate restore, Study/Exam save and restart/round-trip on Fedora. |
| Certification package restore acceptance | 41 scripted groups passed | Same exact executable, two NEW profiles, nine certifications, nineteen attachments, exact course/contribution values and settings/restart/round-trip. |

Counts summarize specific evidence; they do not measure completeness.

### Packaged restore substance

The [first acceptance](/home/drak/.cache/dlms-package-restore-20261009-dg77n26s/reports/acceptance.md)
preserved 214 quizzes, 7,642 questions, nine Study sessions, 623 responses and
809 legacy responses; no certifications/PDFs existed there. Two separately
labeled disposable quizzes then proved wrong → correct Study facts and Finish
acknowledgement, plus reduced reversed matching Exam persistence. Subsequent
refresh/restart and second-profile restore retained them. Original owner-copy
rows remained present; no production record was answered or edited.

The [certification acceptance](/home/drak/.cache/dlms-package-cert-restore-20261009-5tor34c7/reports/acceptance.md)
and [final verification](/home/drak/.cache/dlms-package-cert-restore-20261009-5tor34c7/reports/final-verification.json)
compare all 28 table counts and full digests for 24 non-runtime-state tables.
Runtime restore generations intentionally change. Nine badges, nine current
certificate references and one training-evidence reference retained their roles:
nine PNGs and ten PDFs. Representative PNG/PDF rendered locally. The course
remained **562 minutes (9 h 22 min)**; its older contribution remained **540
minutes / nine hours**, with separate proposed, submitted and accepted values of
nine. Portal settings, visibility/count/sort and AI templates survived exactly.
Both original backup hashes were unchanged; nothing was sent to AI.

**Absent packaged categories:** historical renewals, populated planning/renewal
deadlines, unclassified legacy dates, credential versions, relationships,
non-expiring credentials and configured annual/cycle goals. Empty/unknown
values persisted, but that is not populated-fixture acceptance.
Applicable unchanged [source certification tests](../../../tests/test_certifications.py)
cover date separation/clear-vs-omit, legacy classification/migration interruption,
old-writer refusal, partial period patching, history/attachments, exact duration,
allocations/annual rules and relationships. Their passing source gate is separate
from the missing executable fixtures. No issuer acceptance is inferred.

### Failure history retained, not overwritten by the final pass

- Original audit: 315 Firefox passed / five failed (four capture setup errors,
  one readiness assertion); isolated passes were insufficient.
- Remediation first full Firefox: 322 / two failed obsolete archive glob
  fixtures. Second: 323 / one Library synthetic-input readiness failure.
  Corrected controlled reproductions and unchanged assertions preceded the
  final complete 325 pass. Early allowlist/fixture/snapshot issues and pre-fix
  expected failures remain in the [remediation record](../2026-10-08/remediation.md).
- Documentation failures exposed broken anchors, lazy-image observation before
  scrolling, wrong/missing image dimensions and a wrong dashboard anchor;
  corrected docs/observers preceded the final targeted passes.
- Package harness failures were mount/port/position-observer mistakes, then
  certification CRLF-vs-LF observation. Each was retained; fresh final runs
  passed. No app fix/security relaxation was inferred from those harness errors.

No new pytest/browser gate was run in this reassessment. Verified matching
hashes and retained logs resolved the evidence-reuse question without repeated
heavy tests. No test count from the owner’s working quizzes is inferred.

## 4. Updated scorecards

Category judgments use one decimal on /10, unchanged weights. Three-decimal
totals expose arithmetic, not certainty. “Before” is the October 8 pre-remediation
assessment; September 23 is a historical comparison only. Confidence is coverage
confidence, not a statistical interval. The scores describe **current source**;
there is no separately invented numerical certification of the older package.

### Audit A — historical product-quality rubric

| Category | Weight | Before /10 | Reassessed /10 | Before contribution | New contribution | Change reason / confidence |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| Product maturity / feature completeness | 15% | 9.5 | 9.6 | 1.425 | 1.440 | F2 restores an advertised matching workflow; no feature breadth bonus. Complex edge paths remain. Moderate/high. |
| Core workflow reliability | 15% | 9.0 | 9.5 | 1.350 | 1.425 | Actual saved reduced Exams, Study corrections/Finish and restart/restore evidence remove demonstrated failure. Not every production path. High for exercised paths, moderate overall. |
| Data integrity / failure safety | 15% | 8.6 | 9.3 | 1.290 | 1.395 | F1 pre-write rejection and exact packaged record/attachment round-trips strengthen durable-fact safety. Restore/save race and populated package gaps remain. High closure, moderate assurance. |
| Security / trust-boundary quality | 10% | 8.1 | 9.0 | 0.810 | 0.900 | Executable-schema rejection and the specific 3.1.9 fix close confirmed boundaries. No native exploit/penetration or all-schema authenticity proof. Moderate. |
| Backup / restore / recovery engineering | 10% | 8.4 | 9.4 | 0.840 | 0.940 | F1/F3 regressions plus two independent packaged round-trips/restarts replace demonstrated risks with positive evidence. Hard-link/native-volume and populated categories limit credit. High fixtures, moderate breadth. |
| UX / usability | 10% | 9.3 | 9.3 | 0.930 | 0.930 | Unchanged: clearer manuals support use, but no app redesign or measured learner task-success evidence. Moderate. |
| Visual consistency / polish | 5% | 9.6 | 9.6 | 0.480 | 0.480 | Unchanged: new real screenshots confirm existing accepted design, not a new native/all-state visual acceptance. Moderate/high browser. |
| Accessibility | 5% | 8.8 | 8.8 | 0.440 | 0.440 | Unchanged: Help keyboard/links/images add local coverage; original gradient and assistive-technology gaps remain. Moderate. |
| Testing / regression confidence | 5% | 9.3 | 9.5 | 0.465 | 0.475 | Pre-fix failures, meaningful durable assertions, controlled readiness repro and final clean full gates address actual blind spots. They cannot eliminate unseen seams. Moderate/high. |
| Documentation / Help quality | 5% | 9.0 | 9.6 | 0.450 | 0.480 | Broad current-source task/backup/date/reset correction, 15 actual images, checked links and independent review. No new PDF pipeline or universal external-link/platform acceptance. High current text. |
| Packaging / release readiness | 3% | 8.4 | 9.0 | 0.252 | 0.270 | Confirmed source blockers removed; actual hashed executable saves/restores/restarts on Fedora. Native target/storage gaps and pre-refresh bundled Help still prevent unqualified release. Moderate artifact, low native breadth. |
| Architecture / maintainability | 2% | 8.1 | 8.1 | 0.162 | 0.162 | Unchanged: narrowly scoped services are preferable to a rewrite, but concentration/dense code and ownership cost have not changed. Moderate. |

Weighted calculation: 1.440 + 1.425 + 1.395 + 0.900 + 0.940 + 0.930 + 0.480 + 0.440 + 0.475 + 0.480 + 0.270 + 0.162 = **9.337**.
Before **8.894**; change **+0.443**. September 23 **9.792**; difference **−0.455**.
Headline: **9.34/10**.

### Audit B — mature-product rubric

| Category | Weight | Before /10 | Reassessed /10 | Before contribution | New contribution | Change reason / confidence |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| Product Quality | 15% | 9.4 | 9.5 | 1.410 | 1.425 | F2 closure restores coherent learning support; no claim all edge workflows or issuer compliance are proven. Moderate/high. |
| Engineering Confidence | 15% | 8.8 | 9.3 | 1.320 | 1.395 | Pre-write schema boundary, concurrent snapshot assertions and restored/saved actual records substantiate improvement; final readiness races reproduced and gated. Moderate/high. |
| UX / Usability | 15% | 9.1 | 9.1 | 1.365 | 1.365 | Unchanged: guidance is better, but actual UI and complex recovery/reporting tasks were not newly redesigned or learner-tested. Moderate. |
| Maintainability | 15% | 8.1 | 8.1 | 1.215 | 1.215 | Unchanged: bounded fixes and manuals do not remove dense mixed files/test ownership burden. No unrelated refactor credit. Moderate. |
| Security / Data Integrity | 15% | 8.2 | 9.1 | 1.230 | 1.365 | F1/F4 closure and independent role/duration/record persistence evidence remove concrete penalties. Authenticity, Host/restore race and native-negative coverage remain limited. Moderate overall. |
| Accessibility | 10% | 8.6 | 8.6 | 0.860 | 0.860 | Unchanged: keyboard/theme/zoom evidence retained; screen-reader and original-gradient acceptance remain incomplete. Moderate. |
| Release Engineering | 10% | 8.4 | 9.0 | 0.840 | 0.900 | Actual exact-artifact two-profile restores/restarts add operational evidence beyond source tests. Native matrix/storage, populated fixtures and documentation alignment remain release holds. Moderate tooling/artifact, low native breadth. |
| Documentation / Sustainability | 5% | 8.9 | 9.5 | 0.445 | 0.475 | Current manuals and Help cover accumulated workflows with source mapping, refresh conventions and safety corrections. Historic images labeled; no new export/long-term drift guarantee. High text, moderate sustainability. |

Weighted calculation: 1.425 + 1.395 + 1.365 + 1.215 + 1.365 + 0.860 + 0.900 + 0.475 = **9.000**.
Before **8.685**; change **+0.315**. September 23 **9.510**; difference **−0.510**.
Headline: **9.00/10**. Do not average Audit A and Audit B.

The different totals primarily reflect maintained **15% sustainable ownership**
weight in B versus **2% architecture/maintainability** in A. No unrelated
refactoring or measured learner study occurred. Thus UX, visual, accessibility
and maintainability judgments remain unchanged at their prior current bands.
New functionality is mapped into existing categories, with no added weight or
issuer-compliance score; see the original scorecard’s coverage extension.

## 5. Confidence, retained concerns and readiness

**High confidence** in demonstrated finding closure and evidence/file identity;
**moderate confidence** in overall workflow judgments beyond exercised paths;
**low confidence** in untested native-target/production-volume qualification.
No security, WCAG, issuer-compliance or objective-quality certification is claimed.

Retained concerns are classified, not manufactured:

- **Source-confirmed limitation:** Exam hotspot scoring still accepts a submitted
  correctness flag without authoritative DB geometry. No normal-user wrong score
  was demonstrated; matching remediation does not resolve it.
- **Untested risks:** restore/save connection races and host-header/DNS-rebinding
  behavior were not proven exploits/data losses. Keep them in the later bounded
  adversarial plan, not the confirmed-closure table.
- **Acceptance gaps:** original gradient contrast, assistive-technology use,
  native shells and arbitrary OCR documents remain incompletely verified.
  No new performance regression or benchmark improvement is claimed.
- Owner-reported working quizzes support practical continued testing, but do
  not establish every production path, recovery/refresh/restart or restore.
- Safe LAN operation remains local/trusted-network use without internet exposure.
  Backup validation is not authenticity; trusted inputs and OS access matter.
- Source date/credit integrity is substantially supported, but populated
  executable backup categories listed above remain missing.

### Continued controlled production testing

**Reasonable to continue**, within the established trusted local/LAN product
boundary and with owner control. The earlier confirmed source blockers are fixed;
actual packaged restores/save/restart evidence is stronger than smoke alone.
Keep an independently verified backup outside the active directory. A rollback
requires a compatible older application **and pre-upgrade backup**, preserving
the upgraded profile first. Replacing a binary does not reverse schema 10;
restoring an older backup loses later unrelated Study/quiz/portfolio changes.
Use the [current manual](../../user-manual/17-maintenance-backup-and-data-management.md)
rather than assuming the old packaged Help includes those corrections.
This is not a recommendation to deploy, restore over live data or expose the
server publicly; no such action was performed or authorized.

### Public release across supported platforms

**Not yet supported by the available evidence.** No remaining demonstrated F1–F4
source defect is being called an unfixed release blocker. Instead, the release
holds are **qualification gaps**: native exact-artifact Ubuntu restore/storage
acceptance; native Windows/macOS and other claimed target checks; populated
certification backup cases; and exact-release documentation/artifact alignment.
The package is owner-accepted for its supplied scope, not requalified here.
The older `c2da7f2c` artifact remains pre-fix and gains no acceptance credit.

### Smallest remaining work, in priority order

1. **Release qualification:** test the exact intended Ubuntu artifact on native
   Ubuntu 24.04 and its actual supported storage configuration using disposable
   data, backup/restore/restart and rollback. Do not substitute this Fedora run.
2. **Release qualification:** run the absent populated certification cases
   against the intended package; verify exact date ownership/history/relationships
   and allocations, then perform native Windows/macOS/other advertised target
   acceptance. Windows must include device-path and filesystem behavior.
3. **Release alignment:** ship the accepted current manuals/Help/screenshots with
   the eventual exact release candidate; preserve clean-source/build/hash records.
   Current fixes are not patched into existing binaries by this reassessment.
4. **Bounded integrity/security follow-up:** owner-disposition and testing of
   hotspot authority, restore/save concurrency and host/origin boundary concerns.
   These are existing limitations/risks, not newly confirmed exploits.
5. **Optional polish/assurance:** assistive-technology/gradient checks and actual
   learner task trials; no redesign, compliance engine or broad refactor implied.

## 6. Proposed later adversarial-review scope — planning only

Run once against an owner-selected frozen candidate and designated disposable
native profiles. Share validation; no reviewer repeats full gates. Preserve
before/after durable record digests, request identities, filesystem snapshots,
controlled clocks, process/resource logs and failed evidence. Stop only verified
task processes. Bound archive expansion, disk quota, time, RAM and concurrent
workers; do not stress the owner’s host/services. No live-data/production tests.

| Boundary / risk | Proposed narrow cases | Evidence required |
| --- | --- | --- |
| Imported SQLite and archive → staged writable state | Alternate SQL spelling and legitimate legacy guards; malicious programs/constraints, malformed catalogs/FKs, future schema, traversal/symlinks and excessive expansion. | Rejection before executable statements/mutation; active facts/recovery unchanged; accepted legitimate backup still saves. Separate authenticity/SQLite limits. |
| Backup/restore → filesystem and active requests | Forced name collisions, unsupported links, capacity exhaustion, interrupted snapshot/publication/promotion/recovery; Study save during restore/replace. | Every successful snapshot complete and distinct; no lost acknowledged work; deterministic recovery or explicit refusal. Native production-like disposable filesystem. |
| Browser → Study/Exam evidence | Duplicate/delayed/out-of-order/lost ACK, stale revision/takeover/restore generations, matching variants and hotspot geometry authority. | Server-authoritative selections, preserved first outcomes/corrections, no duplicate interval credit, Finish only after durable ACK. |
| Certification forms → periods, goals and allocations | Omitted/cleared/stale date patches, legacy classification, early/historical renewals, reused courses, partial credits, annual boundaries and failed receipts. | Independent dates/roles, exact 562/540 minutes and credits; no implicit new cycle/accepted credit or double-counted hours; full packaged round-trip. |
| Upload/attachment serving → parser/OS | Malformed/polyglot/oversized raster/PDF, decompression/page limits, filename/path collisions and native Windows device handling. | No unsupported inline execution/path escape; safe missing evidence; bounded resources; original records and shared attachments intact. |
| LAN HTTP/session → origin/CSRF/recovery | Trusted-host aliases, origin/Host inconsistencies, DNS-rebinding assumptions, expired token/concurrent renewal/session switch, unrelated authorization failure. | No cross-origin usable token or unsafe writes; original request body/identity retained for one explicit CSRF retry; no private token logs. |
| Selected-context UI → manual AI handoff | Empty/stale selections, malicious user text/URLs, clipboard denial/popups and edited preview. | Exact reviewed text only, privacy exclusions, no hidden transmission/provider-URL prompt, no credit or date mutations. |

Acceptance: confirmed defects receive a separate owner-authorized remediation
decision; unverified risks stay labeled. A source test or Fedora run must not
be reported as native-platform or issuer-policy acceptance. This plan was not
executed during the present task.

## 7. Evidence paths and report checks

- [Original/remediation evidence and failure history](../2026-10-08/remediation.md)
- [Current change-to-documentation checklist](../../user-manual/UPDATE-COVERAGE-3.3.0.md)
- [Documentation completion](/home/drak/.cache/dlms-documentation-20261009-rjfygunb/reports/completion.md)
- [Remediation final inventory](/home/drak/.cache/dlms-audit-remediation-20261008/reports/final-inventory.json)
- [Full non-browser log](/home/drak/.cache/dlms-audit-remediation-20261008/logs/non-browser-final-3.log)
- [Full Firefox log](/home/drak/.cache/dlms-audit-remediation-20261008/logs/browser-final-3.log)
- [Package learning restore acceptance](/home/drak/.cache/dlms-package-restore-20261009-dg77n26s/reports/acceptance.md)
- [Package certification restore acceptance](/home/drak/.cache/dlms-package-cert-restore-20261009-5tor34c7/reports/acceptance.md)
- [Current dashboard image](../../../static/help_assets/dashboard.webp)
- [Training image](../../../static/help_assets/certifications-training-library.webp)
- [Expanded Study history image](../../../static/help_assets/study-history-expanded.webp)

The documentation capture manifest retains actual Light/Dark/Ethereal narrow and
native-200% application views and the original date review covers the three-date
summary; no mockups are counted. Screenshot provenance/hash checks support
reuse, not a new visual audit. Private package screenshots/documents remain local
and are not copied into this report.

Read-only commands included Git branch/HEAD/status/log/diff, SHA-256 comparisons
against retained manifests, `git show` comparison to the gated revision, retained
log/JSON inspection, official-advisory reading and existing PyInstaller
CArchiveReader inspection of metadata/three Help members. No dependency installed,
code imported as an application, package launched or process terminated.

The [verification record](verification.json) checks category order/weights against
the original table, exact Decimal arithmetic, local file/anchor destinations,
source/evidence hashes and Git scope. Only the two new files below are intended:
`docs/audits/2026-10-09/README.md` and `verification.json`. They remain unstaged;
original reports and all other files are preserved. No tasks/processes were
started that require cleanup.

