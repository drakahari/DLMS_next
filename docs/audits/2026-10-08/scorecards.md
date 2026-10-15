# Two retained audit scopes and scorecards

Revision: `c2da7f2c5b7071685039e52f4938b8bb8c154b24`, DLMS 3.3.0.
Read with [findings](README.md) and [evidence/coverage](evidence.md).

The recovered rubrics use narrative category definitions, not a separate objective
point checklist. Scores remain judgments on a /10 scale, one decimal per category;
each contribution is score × percentage / 100. Three-decimal totals expose the
arithmetic, not three-decimal certainty. Rounded headline ratings use two decimals.
No previous score was used as a target. Planned fixes earn no credit. The intended
model remains a local-first single-user learning application, not a SaaS service.

## Audit A: historical product-quality rubric

These are the exact twelve categories and weights of September 5, repeated in the
September 23 historical assessment. Confidence describes supporting coverage, not
a statistical confidence interval.

| Category | Weight | Now /10 | Contribution | Sept 23 | Reason and confidence |
| --- | ---: | ---: | ---: | ---: | --- |
| Product maturity / feature completeness | 15% | 9.5 | 1.425 | 9.8 | Broad coherent learning, planning and portfolio flows; matching variant gap prevents near-complete workflow confidence. High source, moderate product-acceptance confidence. |
| Core workflow reliability | 15% | 9.0 | 1.350 | 9.9 | Durable Study and ordinary Exam paths have strong retry/browser evidence; F2 is an actual supported-path failure. High for exercised paths, moderate overall. |
| Data integrity / failure safety | 15% | 8.6 | 1.290 | 9.9 | Ordered Study facts, date ownership and transactional migrations are strong; F1 breaks acknowledged-data assumptions after a valid-looking import. High for finding, moderate assurance. |
| Security / trust-boundary quality | 10% | 8.1 | 0.810 | 9.7 | CSRF/origin/upload bounds are meaningfully tested; unexpected database programs and F4 expose incomplete boundaries. No penetration/Windows exploit test. Moderate. |
| Backup / restore / recovery engineering | 10% | 8.4 | 0.840 | 9.9 | Staging, journaling, resource limits and rollback are substantive; F1 and F3 undermine valid-backup and snapshot guarantees. High finding confidence. |
| UX / usability | 10% | 9.3 | 0.930 | 9.7 | Clear Study priority, independent history, optional advanced planning and estimates; rich authoring/reporting still has learning cost. Moderate; no independent learner study. |
| Visual consistency / polish | 5% | 9.6 | 0.480 | 9.8 | Actual responsive shared-control/theme screenshots are consistent. Uninspected combinations and native shells limit acceptance. Moderate/high browser confidence. |
| Accessibility | 5% | 8.8 | 0.440 | 9.5 | Semantic links/buttons/disclosures, keyboard/focus/zoom checks are meaningful; original gradient contrast and missing screen-reader acceptance limit assurance. Moderate. |
| Testing / regression confidence | 5% | 9.3 | 0.465 | 9.9 | Broad negative paths and real Firefox integration; new restore/matching seams demonstrate blind spots despite counts. Moderate/high source confidence. |
| Documentation / Help quality | 5% | 9.0 | 0.450 | 9.9 | Current Help and schema/rollback contracts are useful; canonical manual contradiction F5 and new-feature lag reduce coherence. High on inspected texts. |
| Packaging / release readiness | 3% | 8.4 | 0.252 | 9.9 | Exact-source tooling and Ubuntu archive structure are sound; known blockers plus unavailable multi-platform acceptance prevent broad release assurance. Moderate tooling, low cross-platform. |
| Architecture / maintainability | 2% | 8.1 | 0.162 | 8.5 | Useful domain services coexist with large composition/CSS/browser files and dense certification code. Moderate source judgment. |
| **Total** | **100%** | | **8.894** | **9.792** | **8.89/10 rounded; change −0.898.** |

Arithmetic: 1.425 + 1.350 + 1.290 + 0.810 + 0.840 + 0.930 + 0.480 +
0.440 + 0.465 + 0.450 + 0.252 + 0.162 = **8.894**.

## Audit B: mature-product rubric

The exact eight-category September 13 definition, repeated September 23, gives
sustainable ownership and maintainability 15%, rather than Audit A's 2%.

| Category | Weight | Now /10 | Contribution | Sept 23 | Reason and confidence |
| --- | ---: | ---: | ---: | ---: | --- |
| Product Quality | 15% | 9.4 | 1.410 | 9.8 | Complete local learning loop plus useful earned-credential planner, tempered by matching failure and complex edge workflows. Moderate/high. |
| Engineering Confidence | 15% | 8.8 | 1.320 | 9.9 | Strong transactions/receipts/real-browser failures coverage; missing trigger and reduced-round contracts are concrete assurance gaps. Moderate. |
| UX / Usability | 15% | 9.1 | 1.365 | 9.4 | Calmer dashboard and short task-specific forms; authoring, reporting and recovery remain sophisticated. Moderate, no measured learner task-success study. |
| Maintainability | 15% | 8.1 | 1.215 | 8.5 | Domain ownership remains useful; increasing browser suite and dense mixed presentation raise future review cost. Moderate. |
| Security / Data Integrity | 15% | 8.2 | 1.230 | 9.8 | Fresh F1/F4 findings materially limit protection claims despite upload/CSRF/date/receipt safeguards. Moderate overall; high finding confidence. |
| Accessibility | 10% | 8.6 | 0.860 | 9.3 | Keyboard, contrast, themes and zoom evidence; incomplete assistive-technology acceptance and preserved gradients remain limitations. Moderate. |
| Release Engineering | 10% | 8.4 | 0.840 | 9.8 | Good exact-source/fresh-output validation tools and owner-accepted Ubuntu package; app blockers and other platform gaps remain separate. Moderate tooling, low native breadth. |
| Documentation / Sustainability | 5% | 8.9 | 0.445 | 9.8 | Current in-app guidance/contracts and contributor/CI practices are positive; canonical manual has fallen behind. Moderate/high. |
| **Total** | **100%** | | **8.685** | **9.510** | **8.69/10 rounded; change −0.825.** |

Arithmetic: 1.410 + 1.320 + 1.365 + 1.215 + 1.230 + 0.860 + 0.840 +
0.445 = **8.685**. Do not average the two rubric totals.

## Interpretation of the historical change

The prior reports observed no comparable core blocker and explicitly did not run
a fresh advisory scan. This audit independently demonstrated previously uncovered
restore, matching and backup boundaries. That justifies lower reliability,
security and recovery judgments even though passing coverage and product breadth
have increased. It does **not** establish when each defect was introduced, that
all workflows regressed, or that the old scores were objective measurements.

The canonical manual was described as current in September; it now contradicts
the registry and lags newer task flows. That is concrete documentation change.
Architecture still has services, but current concentration is `app.py` 6,892
lines, stylesheet 16,164 and critical browser suite 16,602, versus 6,765, 15,702
and 11,638 in the prior report. Line count alone is not a defect or a refactoring
mandate; dense certification implementation and growing shared test navigation
cost explain the maintainability judgment. Performance measurements did not show
a new latency defect in the bounded warm fixtures.

Native Windows/macOS and formal screen-reader acceptance were already limited
in September. They are not invented new requirements or proven regressions.
Current package/platform evidence is reported separately, and known source or
platform blockers matter regardless of the numerical score.

## New-functionality coverage extension (no weight changes)

Certification/training was not a separate prior category. Its extension is a
coverage mapping, not a new bonus, penalty scale or policy-compliance rating:

| New area | Existing categories | Evidence / limit |
| --- | --- | --- |
| Three date meanings, legacy preservation, migration/old-writer refusal | Data integrity; recovery; engineering confidence | Independent source review and fresh transaction/interruption/date tests; reused compatible-old-source probe, not an old native binary. |
| Exact durations, historical contribution and credits | Core reliability; product quality | 562-minute activity distinct from 540-minute allocation; estimate/submitted/accepted stages tested, not summed as independent courses. |
| Badge/certificate roles, uploads, evidence round-trip | Security; recovery; product quality | Content validation, safe serving and attachment persistence tests; F1 applies to whole-profile restoration. |
| Portfolio AI and custom issuers | UX; security/privacy; documentation | Editable exact preview, manual provider launch, no prompt in URL, privacy exclusions; no issuer acceptance inferred. |
| Renewal goals, unknown rules, annual/cycle labels | Product; usability; documentation | Approximate planning labels and missing-goal states; no pass probability or certified issuer-compliance claim. Current issuer policies were not re-audited exhaustively. |
| Trophy case, settings visibility/count/sort, responsive forms | Visual; accessibility; usability | Actual Light/Dark/Ethereal screenshots and registry-wide checks; no formal accessibility conformance. |
