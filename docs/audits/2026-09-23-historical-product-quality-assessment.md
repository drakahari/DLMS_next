# DLMS 3.2.1 pre-release Product Quality Assessment — September 5 rubric

Date: September 23, 2026. Branch: `develop/3.2.1`.
Evidence baseline: `1e8fe20dce0cfda9fa575009d33fd56293711324` plus the
uncommitted version-convergence and release-review documentation diff.
This identifies reviewed source, not a frozen release commit or accepted binary.

## Method

The exact twelve categories, definitions and weights of the
[September 5 assessment](2026-09-05-product-quality-assessment.md#weighted-scorecard)
are retained. That retained record supplies narrative definitions rather than
a separate numerical checklist. Scores are judgments at one-decimal category
resolution; the sum of score × weight / 100 is reported to three decimals.
This is an independent current-source reassessment, followed by comparison with
the [September 13 historical score](2026-09-13-product-quality-assessment.md#historical-apples-to-apples-assessment).
The previous total was not used as a target, floor or initial score.

DLMS is assessed as a local-first, single-user learning application. Absence of
SaaS accounts, cloud synchronization, telemetry or enterprise infrastructure
is not a deficiency. Planned work earns no credit. Native visual acceptance is
not inferred from source tests or historical packages. Screenshot version text
alone is not a quality defect. The separate maturity rubric is not mixed into
this historical score.

## Category scores and calculation

| Category | Weight | Current /10 | Contribution | September 13 | Delta |
| --- | ---: | ---: | ---: | ---: | ---: |
| Product maturity / feature completeness | 15% | 9.8 | 1.470 | 9.7 | +0.1 |
| Core workflow reliability | 15% | 9.9 | 1.485 | 9.9 | 0.0 |
| Data integrity / failure safety | 15% | 9.9 | 1.485 | 9.9 | 0.0 |
| Security / trust-boundary quality | 10% | 9.7 | 0.970 | 9.7 | 0.0 |
| Backup / restore / recovery engineering | 10% | 9.9 | 0.990 | 9.8 | +0.1 |
| UX / usability | 10% | 9.7 | 0.970 | 9.6 | +0.1 |
| Visual consistency / polish | 5% | 9.8 | 0.490 | 9.8 | 0.0 |
| Accessibility | 5% | 9.5 | 0.475 | 9.5 | 0.0 |
| Testing / regression confidence | 5% | 9.9 | 0.495 | 9.9 | 0.0 |
| Documentation / Help quality | 5% | 9.9 | 0.495 | 9.7 | +0.2 |
| Packaging / release readiness | 3% | 9.9 | 0.297 | 9.9 | 0.0 |
| Architecture / maintainability | 2% | 8.5 | 0.170 | 8.5 | 0.0 |
| **Total** | **100%** | | **9.792** | **9.747** | **+0.045** |

Calculation: 1.470 + 1.485 + 1.485 + 0.970 + 0.990 + 0.970 + 0.490 +
0.475 + 0.495 + 0.495 + 0.297 + 0.170 = **9.792/10**, rounded **9.79/10**.
The exact comparison is +0.045, not the difference between rounded totals.

## Evidence and judgment by category

1. **Product maturity — 9.8.** Verified source in
   `dlms/services/generated_practice_lifecycle.py` distinguishes durable completed
   practice from active work, checks saved Study/Exam evidence and preserves
   underlying learning data. `learning_scope.py` filters recommendations through
   source scope, with safe legacy defaults. Their regression suites cover partial
   multi-answer/matching responses, late saves, lineage, backup and legacy state.
   These close part of the prior lifecycle/coherence limitation, justifying +0.1.
   Completion is not automatic archive/deletion; OCR remains fallible.
2. **Core workflow reliability — 9.9.** Current parsing-preview, quiz publication,
   Study/Exam, review and pack flows retain server validation and regression
   coverage. `tests/test_paste_preview_hardening.py` exercises presets, retained
   repairs and escaped source; `tests/browser/test_critical_workflows.py` exercises
   real browser/server interaction. No observed core failure warrants a decrease;
   breadth of tests cannot establish the absence of every defect, so no increase.
3. **Data integrity — 9.9.** `dlms/persistence/json_files.py` retains temporary-file
   writes, fsync and promotion. `quiz_publication.py` and `restore.py` retain
   staged publication/recovery journals. Generated completion reads back durable
   metadata and refuses unsaved evidence. Atomic publication, mutation, crash
   recovery and safe-failure tests substantiate the unchanged score. Cross-store
   snapshots and arbitrary power loss still have practical limits.
4. **Security — 9.7.** `app.py` enforces CSRF and request-origin checks and sets
   restore-specific request ceilings before form/CSRF parsing. Archive validation
   retains traversal, member, expanded-size and ratio controls. Security, CSRF,
   resource-limit and backup-capacity suites pass. `SECURITY.md` accurately states
   trusted-LAN limitations. No penetration test or new live vulnerability scan
   was performed; `pip check` proves dependency consistency only. Unchanged.
5. **Backup/recovery — 9.9.** `backups.py` validates the finished ZIP against restore
   policy before publishing it. `storage_health.py` adds bounded read-only usage
   reporting and preflight headroom without deleting content. `app.py` permits a
   1 GiB restore ZIP while retaining independent resource limits. Tests cover
   insufficient space before mutation, multipart/unknown-length boundaries and
   rejection without publishing an unusable backup. This removes a concrete
   creation/restore mismatch and adds capacity protection: +0.1. The
   [capacity record](DLMS-149-backup-capacity.md) is historical benchmark evidence,
   not a benchmark rerun here; estimates are not space reservations.
6. **UX — 9.7.** Learning Scope, explicit Finish Review/completed practice grouping,
   Content Pack filtering/compact presentation and visible storage guidance make
   existing decisions clearer. Relevant lifecycle, scope, storage-visualization,
   navigation and browser tests support +0.1. Multiple review methods and complex
   authoring still require guidance; no user-study success rate is claimed.
7. **Visual polish — 9.8.** Shared theme tokens, responsive Content Pack layout and
   current multi-theme browser assertions substantiate consistency. A version-only
   text change does not invalidate existing captures. Windows Explorer/shortcut
   and macOS Finder/Dock appearance remain unverified for the final artifacts,
   so the score is unchanged and does not award native acceptance.
8. **Accessibility — 9.5.** Keyboard quiz/hotspot paths, semantic controls, focus,
   contrast and responsive coverage remain present in accessibility, keyboard,
   theme and Firefox tests. Manual screen-reader/assistive-technology validation
   is still incomplete. No formal conformance is claimed; unchanged.
9. **Testing — 9.9.** The complete current gates, focused package/documentation
   tests and tutorial validators are recorded in the linked readiness report.
   Firefox uses separate disposable data roots, profiles and process-group
   cleanup. The screenshot regression now checks recorded provenance separately
   from future capture version discovery. More passing tests strengthen evidence
   within the existing band; they are not automatic points. Unchanged.
10. **Documentation — 9.9.** The canonical Markdown manual now supplies complete
    workflow chapters and a working parsing example. Help/current release text
    converges on 3.2.1; 14 tutorial definitions validate against manual anchors and
    capture provenance. Release/readiness guidance distinguishes freeze from
    artifact acceptance. This is a product-wide improvement over the earlier
    release-cut/documentation gap: +0.2. Eight tutorial candidates still require
    owner editorial/listening review; no credit is awarded for their approval or
    publication. Historical capture metadata is preserved honestly.
11. **Packaging — 9.9.** `build_native_release.py` refuses dirty/wrong-commit source
    and rechecks it after building; fresh stage directories prevent stale artifact
    reuse. Artifact/package tests protect architecture, layouts, version and
    checksum contracts. Download acceptance checks tag-bound support assets.
    Portable icon tests verify genuine multi-size ICO generation and preserved
    macOS source selection. These are source/tooling facts, not native UAT.
    Final six-target and AppImage acceptance remains post-freeze work; unchanged.
12. **Maintainability — 8.5.** Service/route/persistence ownership and dedicated
    lifecycle/storage services retain useful seams. Current concentration remains:
    `app.py` 6,765 lines, stylesheet 15,702, critical Firefox suite 11,638, PDF
    route 2,581 and learning service 1,507. The growth has review cost, while new
    behavior follows existing boundaries; it does not establish a category-wide
    decline or improvement at one-decimal resolution. Unchanged.

## Validation, classification and limits

See [3.2.1 readiness evidence](../releases/3.2.1-READINESS.md#validation-evidence)
for exact commands/results and the inventory of remaining native obligations.
Current implementation and tests, not old totals or roadmap promises, support
the judgments above. Historical records were read for definitions and comparison
and were not modified.

Classification: professional-quality open-source desktop software for its
intended local learning scope, subject to owner source review and exact-artifact
native acceptance. This score does not certify a release or replace freeze gates.
This is an AI-assisted engineering assessment, not third-party certification,
formal security/accessibility conformance or a guarantee of defect-free software.
