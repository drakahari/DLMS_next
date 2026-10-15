# DLMS whole-app audit remediation — October 8, 2026

Baseline: develop/3.3.0 at c2da7f2c5b7071685039e52f4938b8bb8c154b24.
This is a bounded remediation record. The original audit findings and two
scorecards remain historical results; no rating has been raised or whole-app
re-certification claimed. The initial three untracked audit reports were included
in the verified recovery snapshot and retained. No schema/version bump,
production profile, installed application, running owner service or existing
backup was changed.

## Findings and fixes

| Finding | Implemented correction | Durable prevention |
| --- | --- | --- |
| F1 / P1: unexpected SQLite programs survive restore | Inspect sqlite_master and metadata before integrity checks or bootstrap/migration writes. Reject unexpected triggers, views, virtual tables, generated columns, function/expression defaults, noncanonical CHECKs, expression indexes, unexpected partial predicates and custom collations. Preserve the two exact certification date guards, including literal case. Use trusted_schema=OFF. Never delete programs to accept a changed database. | Real backup-stage rejection preserves active Study rows/recovery; current staged databases accept subsequent durable saves; migration/crash recovery and byte-preserving startup rejection tests. |
| F2 / P2: reduced matching Exam displays 100% but save returns 400 | Include and validate the runtime source-pair subset/direction, score local selections against that round, retain identity in learning/missed snapshots and exact retries. Missed texts use the same canonical subset/direction. | Reduced/full, reversed/random, invalid/tampered/incomplete, restart/resume and lost-acknowledgement cases verify actual DB contents, not only HTTP status. |
| F3 / P2: same-second backups overwrite | Exclusive private temporary ZIP; validate/fsync completed bytes; publish with os.link, which atomically refuses replacement. Unique suffix plus bounded collision retry; clean temporary files on failure. | Fixed-clock sequential/concurrent creation, forced identical names, restore validation and publication failure tests assert prior bytes survive. |
| F4 / P2: Werkzeug Windows device-path advisory | Runtime minimum and canonical lock/capture pins are 3.1.9; build/test manifests retain their inclusion of the canonical runtime lock. Other pins unchanged. | Upstream Windows-branch safe_join cases fail with 3.1.8 and pass with 3.1.9; canonical resolved audits and dependency/import/pip-check preflight. |
| F5 / P3: stale theme guidance and Firefox capture/readiness gaps | Canonical manual/inventory/capture guide now explain 26 choices and actual groups. Preset test waits for the post-navigation document to finish loading; unchanged assertions/timeouts. Shared browser fixture creates optional nested screenshot directories. | Registry-derived guidance check, fresh nested directory setup check, and controlled blocked-script Firefox reproduction plus unchanged real preset assertions. |

### Independent final review

One separate Sol 6.1 High reviewer inspected the complete code/test diff without
editing files or repeating full gates. It found one P3 defect in the first F2
candidate: missed-question choices_text still described the full bank, conflicting
with reduced/reversed answer text and downstream Anki exports. The fix derives
that snapshot from the server-validated round and stores its identity in the
existing JSON column. The reviewer reran its original disposable five-pair
reproduction and confirmed exactly two reversed lines, correct persisted identity,
HTTP 200 and an identical retry. Later compatibility review identified two first-candidate gaps, rather than
previous Git regressions: new metadata on a legacy matching acknowledgement retry
was rejected, and a read-only ZIP flush handle lacked Windows write access. The
final changes acknowledge unchanged historical fields without backfilling round
identity, keep modern identities strict, and flush through r+b without truncation.
Malformed historical JSON rejects cleanly. Two browser restore fixtures now select
exactly the newly created archive instead of assuming the obsolete filename.
The reviewer inspected all final deltas and tests and reported no substantiated
remaining issue. Evidence: reports/independent-review.json.
Its final Library review checked both post-submit state identities, document
readiness, unchanged assertions/timeouts and interception cleanup. That review
also distinguishes controlled reproduction from the spontaneous run's unrecorded
pre-input timing.

## Proven history and coverage gaps

| Finding | Proven introducing/history evidence | Classification and previous gap |
| --- | --- | --- |
| F1 | 74212a6d810d883303eaad6183f5c627045d6277 (Aug 27) introduced whole-profile restore without executable-schema rejection. 7835f493c268b22eed4335ad298405a4caba0153 (Aug 29) added integrity/table checks, still without a program inventory. 2f2cde12b43531ea69f4c18236a8eca70d8e925f is a later extraction. | Longstanding restore trust-boundary gap, not introduced by schema 10. The inspected restore fixtures/audit evidence exercised malformed structure, migrations and rollback, but lacked the intact-core-database destructive-trigger negative case. Triggers were tested for other failure and date-guard workflows. The Study-specific impact becomes possible after durable Study tables exist; no claim that Study data existed in August. |
| F2 | 11ce27dcb941beda3f11300c0dc2785accd17887 (Aug 22) provided randomized reduced matching rounds. 2ac51b04f29f4c9c26517192ad0131b2205972e1 (Sep 2) introduced strict full-bank server recomputation despite those smaller client rounds. bb1d9c5 is extraction, not origin. | Proven regression at validation hardening. Existing API fixtures used the complete two-pair bank; browser matching coverage emphasized Study/recovery while scored Exam saves used choices. The inspected pre-remediation suite had no case combining reduced matching with successful Exam-result persistence. |
| F3 | The original 74212a6 backup implementation uses a second-resolution fixed label/name, shared .tmp path and replacing publication. | Longstanding behavior; the backup-size fixture even codified replacement. Prior audits checked validation/rollback but not nonreplacement under fixed-time concurrent requests. The revised fixture preserves every successful snapshot, rather than merely the last successful replacement. |
| F4 | c128ada4a34f7f7fbc707e65d1e8ccf5e229addd (Aug 30) locked Werkzeug 3.1.8. The official advisory and 3.1.9 fix were published Sep 27. | Newly disclosed upstream dependency issue relative to the Sep 23 audits, not a new DLMS algorithm regression. Historical clean dependency scans are snapshots; we cannot establish when advisory feeds became current from those logs alone. Native Windows exploitability is not claimed as reproduced. |
| F5 themes | 7e65bd2e added accurate five-theme guidance on Oct 2; 6aa8c6c543ac71becdc4021acf15af1505fea5d8 expanded the registry on Oct 4 without updating that canonical manual. | Recent documentation regression. Theme tests checked application registry/rendering, not consistency with this separate manual. A registry/count assertion now covers the canonical guidance without another hard-coded 26-name list. |
| F5 readiness | 7019e2b1 introduced the post-link DOM-only wait; 71057385 added synthetic select/change plus immediate enabled assertion. | Recent test synchronization gap. The controlled test holds certifications.js: the button/form exist while the document is not complete and the handler is absent. The old assertion would fail in this demonstrated state. The correct boundary is document readiness, already used by real pointer input. No application defect or arbitrary-delay fix is claimed. |
| F5 capture setup | 493031c9 introduced action screenshot writes without making the configured directory; 872543ac did the same for certification captures. | Test-environment/setup gap, not application behavior. The earlier audit retained four FileNotFoundError cases and one readiness failure; isolated passes did not resolve them. Central setup now supports fresh nested paths. |
| F5 Library readiness | 40fa4a3e (Sep 4) introduced CSS-only post-submit waits before synthetic search/reorder input. | Longstanding test synchronization gap. The controlled script hold reproduces the original line 2446 timeout; the corrected identity-and-complete waits pass unchanged assertions. Inspected prior gates lacked controlled loading at this boundary. The spontaneous failed run did not capture pre-input timing, so its precise event order is not claimed. |

Exact git show/log/blame evidence is retained in reports/history-evidence.txt.
Commit origins above are proven from diffs; explanations of why audits missed them
are limited to inspected fixture/scope omissions, not claims about an auditor's
intent or exhaustive knowledge of every historical run.

## Validation and failure history

The pre-fix source is a disposable extraction of the verified recovery archive,
not a switched/reset branch. Final regression fixtures against that copy and the
prior Werkzeug environment produced 20 expected failures and one legitimate
restore pass. This includes eight unexpected-program cases, unchanged-byte
startup rejection, matching save, backup collision, Windows device filtering and
guidance/setup contracts. The old capture-setup helper/pin contracts are absent;
those failures demonstrate infrastructure absence rather than an app exception.
The deferred-handler test establishes the precise pre-fix browser assertion
state. An external AST replay then ran the exact historical test: its original
line 16107 assertion fails while the deliberately held script leaves the document
interactive; the corrected function passes every original assertion at complete.
Both expectations passed in the corrected replay (2 cases). The first replay had
one external harness flag error on a later click; that failed log remains retained
and is not counted as an application failure. Initial restore fixtures contained two setup mistakes (duplicate
DB inventory/out-of-root staging); those results are retained but not counted as
defect proof. The corrected pre-fix restore run has eight failures and one pass.

First focused candidate: 30 passed plus 42 subtests, two failures from an overly
strict partial-index allowlist. That allowlist was corrected, and the concurrent
restore fixture was also adjusted to its appropriate service boundary; canonical current and legacy restore checks pass. Subsequent focused
runs include 95 tests + 56 subtests and five real Firefox cases. A later matching
snapshot regression exposed missing JSON/snapshot storage; the independent
review confirmed the related mismatch and the fix was verified. Final focused
set: 97 passed + 63 subtests.

The first complete non-browser gate passed 2,170 tests plus 3,911 subtests.
The first complete Firefox gate finished with 322 passed and two failed, both at
line 5036: backup creation returned 200 but max(*-manual.zip) had no entries under
the new naming contract. These failures occurred before restore or profile
mutation. Their screenshots/server logs remain retained. After the reviewed late
compatibility deltas, the focused set passed 113 tests plus 68 subtests and the
seven affected Firefox cases all passed. One preceding focused invocation selected
a nonexistent test filename and collected no tests; its setup error is retained.
The final-candidate non-browser run passed 2,173 tests plus 3,916 subtests, with six
existing cached_property/asyncio deprecation warnings, and no skipped tests.
The second full Firefox run had 323 passed and one failed: Library search timed out
at line 2446 after a CSS-only post-submit wait. The new document's search listener
is attached at DOMContentLoaded. Controlled replay holds local-time.js and reproduces
that exact old assertion with movedQuizPresent=true and ready=interactive; the
corrected waits pass all original assertions (two expected checks pass). A newly
retained regression deliberately fails when its workflow is replaced with the
exact old wait (one expected failure), and passes on the correction. The spontaneous
run's final screenshot alone does not prove its pre-input timing; the failure mode
and missing synchronization boundary are independently reproduced. No application
or template behavior changed. All previous failed runs/logs are retained.
A third complete gate pair ran on the final application, tests, dependencies and
manual/alt-text candidate: 2,173 non-browser tests plus 3,916 subtests passed
(333 deselected, six existing deprecation warnings, 56.31 seconds); all 325
enabled Firefox tests passed (1,698.66 seconds). No skipped browser coverage is
counted as passing. The final gates ran sequentially, using one
shared canonical environment and isolated data. No assertion was weakened,
security lifetime changed, test skipped to obtain a pass or timeout inflated.

### Final commands, integrity and cleanup

The canonical gate commands were executed through the retained `run_checks.py`
wrapper, which calls pytest.main with these arguments and records process
identities/resources without changing assertions:

```sh
python -m pytest -q -p no:cacheprovider -m "not browser"
DLMS_RUN_BROWSER_TESTS=1 PYTHONDONTWRITEBYTECODE=1 python -m pytest -q -p no:cacheprovider -m browser tests/browser/test_critical_workflows.py
```

Python is the isolated evidence-directory venv (3.14.7); Firefox is 157.0 on
Fedora 44 x86_64. Temporary profiles, optional screenshot directories and pytest
runtime artifacts are disk-backed under the home evidence directory. Full-gate
logs are `logs/non-browser-final-3.log` and `logs/browser-final-3.log`.
All 838 source candidate hashes matched `reports/gate-source-sha256-final-3.json`
after both gates. Only this result report was finalized afterward; application,
test, dependency and manual files remain the gated candidate.

The final Firefox resource log contains 339 observations, minimum available RAM
13.36 GiB, 16 swap-in pages and no swap-out pages during the run. These are
observations, not a diagnosis of earlier failures. Both final process reports
record zero remaining task-owned descendants and no forced cleanup. UID, process
start, command and working-directory evidence is retained; unrelated applications
and owner services were untouched. Final file hashes, recovery re-verification,
whitespace and Git inventory are recorded in `reports/final-inventory.json` and
`reports/candidate-sha256.txt`.

### Actual screenshot review

Before: the original audit's `screenshots/matching-correct-exam-save-rejected.png`
shows 100% with save rejection. After: the final gate's
`screenshots/browser-final-3/test_matching_exam_round_identity_resume_and_lost_acknowledgement[2-definition_to_term-browser_stack0].png`
shows the real reduced/reversed Exam saved successfully. The normal reduced and
full/random cases also saved and resumed with the same round identity.

Representative final screenshots inspected for unchanged date/duration layout:

- `screenshots/final-3/certification/dates-summary-1440-light.png`
- `screenshots/final-3/certification/dates-summary-native200-dark.png`
- `screenshots/final-3/certification/dates-summary-390-ethereal.png`

These show separate expiration/planning/renewal dates, preserved unclassified
legacy date, 9 h 22 min course, readable wrapped controls and visible focus.
The existing Appearance Help crop was inspected and its alt text accurately
describes the selector/readability guidance, not an absent Save button. The full
gate retains all-theme, LAN HTTP, CSRF renewal, Study recovery/completion and
native 200% coverage. Representative visual inspection is not a claim of complete
WCAG or native Windows acceptance.

### Final changed-file inventory

There are 25 unstaged candidate files: 17 previously tracked implementation,
test/dependency/manual files; four new implementation/tests; the three preserved
original audit reports; and this new remediation report. Exact paths and SHA-256
values are in the external candidate manifest. No generated screenshots/logs,
temporary environments or build artifacts were added to the repository.

## Dependency and compatibility evidence

Official source: https://github.com/pallets/werkzeug/security/advisories/GHSA-g6x2-hccm-hh4m
and https://werkzeug.palletsprojects.com/en/stable/changes/.
Affected <3.1.9; fixed 3.1.9. This is Windows/NTFS special-device empty-stream
handling causing indefinite reads through send_from_directory, not OS code
execution. Linux tests simulate the Windows safe_join branch without opening a
device. DLMS's Flask/static/file serving uses the affected dependency boundary.
3.1.9 remains compatible with the current Python/build line. Upstream request
parsing changes are covered by the existing request-size/form and security
regressions; they are not a blanket certification of every upstream change.

Canonical pip-audit -r requirements-build.txt: 21 resolved packages, no findings.
Canonical pip-audit -r requirements-test.txt: 22 resolved packages, no findings.
These expand the nested runtime lock; unlike the original audit's --no-deps scan,
they are actual resolved canonical audits. Dependency preflight: 20 locked build
distributions, exact metadata/imports and pip check pass. Existing owner/system
Python and installed DLMS were untouched; the new environment is under home.

No database schema/version or archive format changes. Ordinary legacy/current
backups remain usable and migration/restore tests pass. Unsafe custom schema
programs are rejected with the original external backup retained; they are not
silently stripped. This boundary does not authenticate records or validate all
possible modified table/FK semantics, nor shield vulnerabilities in SQLite itself.
Backup publication needs filesystem hard-link support; unsupported filesystems
fail safely without replacing prior snapshots. Native NTFS/FAT/network-filesystem
acceptance is not established by the Linux tests.

New shared-CSS quiz pages carry matching round metadata. Full-bank old matching
submissions without it retain compatibility, including lost-acknowledgement retries
that now supply validated metadata: original durable JSON is never rewritten; reduced rounds without identity are
explicitly rejected instead of guessed. Older self-contained quiz HTML must be
updated/regenerated by the owner if it cannot send the current contract. No
personal pages or past attempt records were regenerated or repaired.

Schema 10, distinct date meanings, unresolved legacy dates, 562-minute course vs
older 540-minute contribution, attachments and estimate/submitted/accepted values
remain unchanged. Applicable certification/date/backup regressions run in the
complete gates; this remediation does not introduce issuer policy rules.

## Release and operational limits

After passing source gates and owner review, the candidate may be manually
committed, then used for a fresh Ubuntu 24.04 build and packaged acceptance.
This task builds no package. The existing c2da7f2c Ubuntu artifact is pre-fix,
and source-level results do not qualify it or any existing Windows binary.
Native Windows and packaged-platform acceptance remain outstanding.
A verified pre-upgrade data backup and compatible earlier application are still
required for schema rollback; swapping binaries alone does not undo schema 10.
Restoring an older backup loses subsequent changes. Never restore an untrusted
or rejected backup to bypass validation.

Evidence directory: /home/drak/.cache/dlms-audit-remediation-20261008.
Initial audit and its failed-run evidence remain separately preserved under
/home/drak/.cache/dlms-whole-app-audit-20261008.

Exact paths (the three original audit files are retained, not three new findings):

- `app.py`
- `dlms/persistence/database.py`
- `dlms/persistence/schema_programs.py`
- `dlms/services/attempts.py`
- `dlms/services/backups.py`
- `docs/audits/2026-10-08/README.md`
- `docs/audits/2026-10-08/evidence.md`
- `docs/audits/2026-10-08/remediation.md`
- `docs/audits/2026-10-08/scorecards.md`
- `docs/screenshots/requirements.txt`
- `docs/user-manual/16-settings-and-runtime.md`
- `docs/user-manual/FEATURE_INVENTORY.md`
- `docs/user-manual/SCREENSHOT_PLAN.md`
- `docs/user-manual/appendix-keyboard-and-accessibility.md`
- `requirements-lock.txt`
- `requirements.txt`
- `static/script.js`
- `tests/browser/README.md`
- `tests/browser/test_critical_workflows.py`
- `tests/test_attempt_validation.py`
- `tests/test_backup_collision_safety.py`
- `tests/test_backup_semantic_validation.py`
- `tests/test_backup_size_contract.py`
- `tests/test_remediation_dependencies_and_docs.py`
- `tests/test_restore_schema_programs.py`
