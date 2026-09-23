# DLMS 3.2.1 pre-release mature-product assessment

Date: September 23, 2026. Branch: `develop/3.2.1`.
Evidence baseline: `1e8fe20dce0cfda9fa575009d33fd56293711324` plus the
uncommitted version-convergence and release-review documentation diff.

## Unchanged method

This uses the exact eight-category mature-product rubric retained in the
[September 13 assessment](2026-09-13-product-quality-assessment.md#stricter-mature-product-assessment):
feature quality, engineering confidence, UX, sustainable ownership, security/data
protection, accessibility, release engineering and documentation/sustainability.
The retained narrative definitions and category weights are unchanged. Scores
are independent current-source judgments at one decimal; contributions are
score × weight / 100. The prior 9.45 total is only a comparison after scoring.
This is separate from the September 5 historical rubric, especially its 2%
maintainability weight: maintainability remains 15% here.

The intended product is local-first and single-user; absent SaaS capabilities
are not penalized. Planned features, unpublished tutorial approval and unperformed
Windows/macOS visual checks earn no credit. A source test is not native acceptance.

## Category scores

| Category | Weight | Current /10 | Contribution | Prior | Delta |
| --- | ---: | ---: | ---: | ---: | ---: |
| Product Quality | 15% | 9.8 | 1.470 | 9.7 | +0.1 |
| Engineering Confidence | 15% | 9.9 | 1.485 | 9.9 | 0.0 |
| UX / Usability | 15% | 9.4 | 1.410 | 9.2 | +0.2 |
| Maintainability | 15% | 8.5 | 1.275 | 8.5 | 0.0 |
| Security / Data Integrity | 15% | 9.8 | 1.470 | 9.8 | 0.0 |
| Accessibility | 10% | 9.3 | 0.930 | 9.3 | 0.0 |
| Release Engineering | 10% | 9.8 | 0.980 | 9.8 | 0.0 |
| Documentation / Sustainability | 5% | 9.8 | 0.490 | 9.5 | +0.3 |
| **Overall Product Maturity** | **100%** | | **9.510** | **9.450** | **+0.060** |

Calculation: 1.470 + 1.485 + 1.410 + 1.275 + 1.470 + 0.930 + 0.980 +
0.490 = **9.510/10**, rounded **9.51/10**. Delta from **9.45** is **+0.06**.

## Category evidence and limits

1. **Product Quality — 9.8 (+0.1).** Current `generated_practice_lifecycle.py`
   verifies saved completion and separates completed generated work without
   changing learning evidence; `learning_scope.py` makes recommendation inclusion
   explicit. Current storage/backup safeguards and retained quiz/import/review
   integration add product coherence. Their focused regression suites and the
   complete source gates substantiate implemented behavior. These address a
   material part of the old generated-session lifecycle limitation. Content is
   still persisted, no automatic archive/deletion is provided, and OCR still
   needs human Review & Repair. No score assumes those limits were eliminated.
2. **Engineering Confidence — 9.9 (unchanged).** Complete non-browser and Firefox
   gates cover current source; atomic writes, restore crash recovery, partial
   multi-answer state and failed persistence have failure-injection tests.
   `tests/browser/test_critical_workflows.py` owns isolated browser/server roots
   and cleanup; its structural tests protect that harness. The original sandbox
   socket failure was an environment limitation, not a skipped passing gate.
   Exact native artifacts still need UAT, and tests cannot prove no defects.
3. **UX / Usability — 9.4 (+0.2).** Source scope controls, durable Finish Review,
   completed-practice grouping, Content Pack filters/compact presentation,
   mobile Library navigation and Storage Health reduce recurring ambiguity.
   See `tests/test_learning_scope.py`, `test_generated_practice_lifecycle.py`,
   `test_storage_visualization.py`, navigation tests and the Firefox workflows.
   The canonical manual gives users task sequences and distinguishes review
   choices. These are broader than isolated cosmetic fixes, supporting two
   tenths under this stricter rubric. Workflow density and spatial authoring
   remain learning costs; no usability study was conducted.
4. **Maintainability — 8.5 (unchanged).** Current routes, services, persistence
   modules and external templates retain domain ownership. Dedicated lifecycle
   and storage modules avoid new parallel stores. Large files remain material:
   application composition 6,765 lines, CSS 15,702, critical browser tests 11,638,
   PDF route 2,581, learning service 1,507. Extra test and UI code increases
   navigation cost, but observed boundaries and regression contracts support
   the same band. No speculative refactor or planned cleanup receives credit.
5. **Security / Data Integrity — 9.8 (unchanged).** `app.py` applies origin/CSRF
   validation and bounded request handling; `backups.py` validates before backup
   publication, while `restore.py` retains staged recovery and safety checks.
   The 1 GiB ZIP allowance does not raise independent expansion/member/ratio
   limits. `storage_health.py` reports partial/unknown readings and avoids
   deletion. Capacity, security, semantic-backup and crash-recovery tests pass.
   These strengthen the existing band; space checks cannot reserve storage,
   snapshots are not distributed transactions, and trusted-LAN mode still has
   no authentication/TLS. No fresh advisory scan or penetration test is claimed.
6. **Accessibility — 9.3 (unchanged).** Keyboard controls, focus handling, live
   status, semantic groups and multi-theme/viewport assertions are present in
   accessibility, quiz-keyboard, theme and browser tests. These are meaningful
   evidence within the product's browser interface. Comprehensive screen-reader
   and alternate-input validation remains unperformed, limiting this category
   under the stricter definition. Historical screenshots do not establish such
   acceptance, and this is not a WCAG conformance claim.
7. **Release Engineering — 9.8 (unchanged).** `tools/build_native_release.py`
   enforces clean exact-commit/version preflight and fresh build stages;
   artifact/package verifiers protect layouts, architecture, version, OCR,
   smoke and checksum contracts. `accept_downloaded_release.py` binds verification
   to the trusted release tag and exact assets. Tests verify ICO sizes and
   preserved macOS icon selection, not Explorer/Finder rendering. DLMS-144 is
   complete per issue #4; its previous images do not qualify final 3.2.1 bytes.
   Native builds, icon UAT, transfer/download hashes and publication appropriately
   follow source freeze. Their timing is not a failed source gate or new penalty.
8. **Documentation / Sustainability — 9.8 (+0.3).** The canonical manual now has
   workflow-specific chapters and an executable parsing example; all 14 tutorial
   definitions and 93 capture references validate. Active Help, package support
   text and release instructions agree on 3.2.1. Historical records and captured
   versions remain intact. `AGENTS.md` and GitHub Project #1 establish issue scope,
   status and explicit owner acceptance; CI, dependency scheduling, contributor
   and security guidance remain present. This resolves the old release-cut and
   guide-depth gap enough for +0.3. Six phase-one tutorials are recorded approved;
   seven phase-two candidates plus Parsing still need editorial/listening review.
   This score credits existing documentation and validated definitions, not
   approval/publication, a manual PDF or unperformed listening checks.

## Evidence, comparison and readiness boundary

The three increases contribute +0.015 (product), +0.030 (UX) and +0.015
(documentation), totaling +0.060. No decrease is justified by a demonstrated
category-wide regression. Unchanged categories were reassessed from current
source and tests; their old limitations still bound the next tenth.

See [current validation and release readiness](../releases/3.2.1-READINESS.md)
for exact gate results, source identity, roadmap reconciliation and post-freeze
obligations. The accompanying [historical-rubric assessment](2026-09-23-historical-product-quality-assessment.md)
provides additional file/test evidence without substituting its weights here.

Classification: mature, professional-quality local-first software prepared for
owner source review and subsequent native release acceptance. A product-quality
score is separate from permission to freeze, build or publish. This AI-assisted
assessment is not an independent certification, exhaustive security/accessibility
audit or guarantee; no Windows/macOS runtime or final package acceptance was
performed on this Fedora host.
