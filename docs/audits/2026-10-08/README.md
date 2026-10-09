# DLMS 3.3.0 whole-application quality audit

Assessment date: October 8, 2026. Source: `develop/3.3.0`,
`c2da7f2c5b7071685039e52f4938b8bb8c154b24`. Initial working tree was clean.
The revision matches the owner's accepted Ubuntu 24.04 package baseline. This
assessment changes reports only; it does not fix defects or qualify new binaries.

## Executive conclusion

DLMS provides a coherent, extensively tested local learning application. Durable
Study sessions, first-response difficulty, safe retries, scoped recommendations,
manual AI handoffs and the new certification planner have substantial positive
evidence. Actual Firefox views support the current responsive visual design.
Schema 10's three date meanings and legacy provenance are consistent in the
inspected contract and exercised tests.

However, this fresh audit found material gaps outside the recent date changes:
restoration accepts an unexpected SQLite trigger that can silently delete future
Study responses; a correct reduced-round matching Exam cannot save; same-second
backups overwrite each other; and the canonical dependency set contains a newly
reported Windows-specific Werkzeug advisory. Passing existing tests does not
negate these findings.

The unchanged historical rubric yields **8.894/10 (8.89)**, compared with
September 23's 9.792. The separate mature-product rubric yields **8.685/10
(8.69)**, compared with 9.510. These are evidence-informed judgments, not
objective guarantees. [Both scorecards](scorecards.md) retain their original
categories and weights. [Evidence and coverage](evidence.md) distinguish fresh,
reused and unavailable checks.

## Prior audits recovered

The latest paired assessments are two **different rubrics applied to the same
source**, not two independent repetitions of one audit:

- [September 23 historical product-quality audit](../2026-09-23-historical-product-quality-assessment.md)
  repeats the [September 5 twelve-category rubric](../2026-09-05-product-quality-assessment.md).
- [September 23 mature-product audit](../2026-09-23-mature-product-assessment.md)
  repeats the stricter eight-category rubric introduced in
  [September 13's assessment](../2026-09-13-product-quality-assessment.md).

Both assessed `1e8fe20dce0cfda9fa575009d33fd56293711324` on `develop/3.2.1`
plus an uncommitted version-convergence/documentation diff. Their shared
[acceptance evidence](../../releases/3.2.1-READINESS.md) records 1,794 non-browser
tests plus 2,450 subtests and 96 enabled Firefox cases, alongside package/tooling
checks and explicit remaining native obligations. That evidence is historical,
not a current test run or final binary acceptance. The two numerical totals must
not be averaged. Earlier stable-release and packaging reviews are additional
audit types, not substitutes for these scorecards.

## Ranked findings

Severity here means P1: high data-integrity/release concern; P2: material affected
workflow or platform defect; P3: lower-impact documentation/polish. Confidence
and reproduction limits are stated separately.

### F1 — P1: unexpected SQLite triggers survive restore validation

**Confirmed, high confidence.** A disposable schema-10 database with an extra
trigger passed structural ZIP validation, read-only semantic validation and the
actual staged restore preparation/current-schema validation. The trigger remained
installed. In an equivalent disposable source fixture, the real Study-response
route acknowledged HTTP 200 while that trigger removed all responses for the
session: one saved fact before the request, zero afterward, two learning events.
The stage was never promoted, and no owner data was accessed. This establishes
an accepted database-program integrity problem; it is not a claim of OS code
execution or a demonstrated remote browser exploit.

Sources: `dlms/persistence/database.py:331`,
`dlms/persistence/certification_schema.py:123`,
`dlms/services/backups.py:453`, `dlms/services/restore.py:176`.
Required tables, indexes and the two known deadline guards are checked, but the
validator does not reject additional triggers. Unexpected trigger behavior may
also execute during preparation writes, before promotion.

**Impact:** an imported backup can appear valid yet corrupt future acknowledged
learning records. A pre-restore safety backup cannot preserve work created later.
**Recommended minimum fix:** schema-version-specific trigger inventory and
definition validation before any staged migration/write; reject unexpected
triggers while accepting exact legitimate historical/current guards. Add tests
for early rejection, unchanged live data and legitimate old/new restoration.
Evidence: `reports/unexpected-sqlite-trigger.json` in the private audit directory.
Do not publish the synthetic destructive SQL as routine user instructions.

### F2 — P2: a correct reduced matching round is rejected in Exam Mode

**Confirmed, high confidence.** Freshly published content with five stored pairs
and `round_size=2` produces a two-pair client round. The client reports a complete
correct round using round-local indexes. The server evaluates it against all five
stored pairs and returns HTTP 400: `wasCorrect is inconsistent with selected`.
The actual route probe saved zero attempts. This affects supported random/reduced
matching rounds; it does not imply ordinary choice Exams or durable Study matching
are broken.

Sources: `static/script.js:593`, `static/script.js:2207`,
`dlms/rendering/quiz_artifacts.py:81`, `dlms/services/attempts.py:158` and `:268`.
Existing attempt tests exercise complete stored matching sets, leaving this
variant boundary uncovered.

**Impact:** a correct score is calculated but cannot enter Exam History or learning
evidence; retrying the same invalid contract cannot repair it.
**Recommended minimum fix:** carry and validate the actual matching variant/source
pair identities, then recompute correctness for that authorized round. Reuse the
existing Study variant pattern rather than trusting a client correctness flag.
Cover smaller/full/reversed/random rounds, incomplete answers and retries.
Evidence: `reports/audit-probes.json`, `reports/matching-browser.json` and
`screenshots/matching-correct-exam-save-rejected.png`. An actual Firefox click
path on ordinary non-secure LAN-equivalent HTTP confirms the 100% calculated
score, HTTP 400, visible unsaved warning and Retry action.

### F3 — P2: two backups in the same second replace the first snapshot

**Confirmed sequentially, high confidence.** Two actual backup-service calls with
the same second and label returned the same path. Changing a synthetic file
between them left one archive containing the later value; the earlier recovery
point was gone. `tests/test_backup_size_contract.py:76` explicitly permits
fixed-clock replacement, so the passing suite is not evidence against this issue.

Sources: `dlms/services/backups.py:216–220`, `:265–277`,
`dlms/routes/maintenance.py:148`. Concurrent calls also share a temporary path;
that collision is a source-derived risk, not separately reproduced corruption.

**Impact:** rapid/repeated backup actions lose an intended recovery snapshot.
**Recommended minimum fix:** unique final and temporary names, exclusive/non-
replacement publication, sequential fixed-clock and concurrent creation tests.
Evidence: `reports/audit-probes.json`.

### F4 — P2: vulnerable Werkzeug pin blocks unqualified Windows release readiness

**Confirmed dependency finding; Windows exploitation not tested.** The canonical
lock pins Werkzeug 3.1.8. A fresh advisory query identifies CVE-2026-102598 /
GHSA-g6x2-hccm-hh4m, affecting versions before 3.1.9. On Windows/NTFS,
`safe_join` accepts device names with an empty alternate-data-stream marker and
`send_from_directory` can hang reading the device. Flask's static-file service
uses this dependency. The official fixed version is 3.1.9.
[Upstream advisory](https://github.com/pallets/werkzeug/security/advisories/GHSA-g6x2-hccm-hh4m).

**Impact:** a known platform-specific denial-of-service exposure; this is not
evidence that the NTFS issue executes on the assessed Fedora or Ubuntu host.
**Recommended minimum fix:** a narrow compatible pin/lock update, canonical
resolved audits and Windows device-path regression/native verification. No pins
were changed during this audit. Fresh pinned-package scans found no advisory for
pypdf 6.19.0; that does not constitute an exhaustive dependency guarantee.

### F5 — P3: the canonical manual's theme guidance is stale

**Confirmed documentation defect.** `docs/user-manual/16-settings-and-runtime.md:33`
still says five themes, as does
`docs/user-manual/appendix-keyboard-and-accessibility.md:106`;
`FEATURE_INVENTORY.md:712` retains an older list. The registry and current in-app
Help provide 26. Canonical chapter coverage of durable Study, Exam Plans and
certifications also trails the more current in-app Help.

**Impact:** beginners using the canonical manual receive contradictory selection
guidance. **Recommended minimum fix:** synchronize the relevant manual chapters
with actual task flows and link to the accurate Help; retain historical audit text.

## Confirmed limitations and suspected risks

- **G1 — P2 validation gap, not a confirmed application defect:** the full Firefox
  gate failed the preset-selection assertion at
  `tests/browser/test_critical_workflows.py:16107`. All five affected repository
  cases passed once on the focused rerun, but that isolated pass does not resolve
  this intermittent assertion. The test checks DOM presence after link navigation
  before programmatically dispatching a selection event; a deferred-script
  readiness race is plausible, not proven. Preserve the trace and investigate
  initialization/readiness before declaring a clean complete Firefox gate.
  Four other full-run failures were the audit's missing optional capture folders,
  confirmed by FileNotFoundError, rather than application defects.
- **Exam hotspot authority limitation:** `dlms/services/attempts.py:261–266`
  accepts the submitted correctness flag for a selected hotspot point because its
  database representation lacks geometry. Durable Study instead validates the
  artifact-backed target. This is a source-confirmed evidence-integrity limitation,
  not an observed wrong score from normal browser interaction. Reuse authoritative
  geometry/revision validation in a separately scoped improvement.
- **Baseline contrast limitation:** documentation explicitly retains some original
  theme mode-button gradients with sub-4.5 text contrast. New palettes use derived
  semantic adjustments. Automated contrast passing elsewhere is not WCAG
  conformance; gradients, images and chart distinctions need broader acceptance.
- **Unverified restore/save concurrency risk:** Study routes open connections
  outside the shared restore lock, unlike certification mutations. A write during
  database replacement deserves a bounded race test. No data loss from this race
  was reproduced; it is not an additional confirmed P1.
- **Unverified host-header/DNS-rebinding risk:** origin comparison depends on
  HTTP_HOST and no trusted-host allowlist was found. Browser exploitability was
  not demonstrated. Trusted LAN without authentication/TLS is a documented product
  boundary, not scored as missing SaaS functionality. Do not expose it publicly.
- OCR still requires human validation; scripted OCR tests are not a benchmark of
  all real documents. Legacy self-contained quiz pages require explicit owner-
  controlled regeneration for newer shared-CSS/tracking support.

## Readiness and smallest improvement order

1. **Controlled testing:** suitable only as a bounded, known-risk test candidate
   with a verified complete backup kept separately, a compatible pre-schema-10
   rollback copy and trusted inputs. Do not treat this as unconditional production
   promotion. Avoid relying on affected matching Exams or same-second snapshots.
2. **Public supported-platform release:** **not ready for unqualified acceptance**.
   F1 is a release-blocking restore/data-integrity defect; F2 blocks an advertised
   Exam workflow. Resolve F3 and the Windows advisory before a release decision.
   Native Windows/macOS/other-target acceptance is unavailable. The accepted
   Ubuntu smoke claim and fresh archive structure check do not grant that credit.
   The current complete Firefox run is also not clean (315 passed, five failed;
   five affected cases subsequently passed), with G1 still unresolved.

Prioritize F1, then F2 and F3, then the narrow F4 dependency/platform verification,
then F5 manual synchronization. Re-run affected negative paths and shared gates
after separately authorized fixes. Do not begin a broad architecture rewrite to
address these bounded defects.

Rollback requires a complete verified **pre-upgrade** backup and the compatible
old application in a separate profile, preserving the upgraded profile first.
Switching binaries does not reverse schema 10. Restoring an older backup loses
all subsequent changes, including unrelated quiz/Study work. See the existing
[storage/rollback contract](../../certifications-storage-contract.md#practical-rollback).

## Report inventory

- This report: findings and readiness.
- [Scorecards](scorecards.md): both unchanged rubrics, reasoning and comparison.
- [Evidence](evidence.md): fresh/reused checks, commands, UI evidence and limits.

All large artifacts are outside Git at
`/home/drak/.cache/dlms-whole-app-audit-20261008`. No code, tests, configuration,
previous reports, personal data or owner services are modified by this assessment.

## Subsequent bounded remediation

The authorized source fixes and new regression evidence are recorded in
[the remediation report](remediation.md). Original findings, scores and failed-run
evidence above remain historical; this is not whole-app re-certification or
acceptance of rebuilt binaries. Final candidate validation is recorded there.
