# DLMS 3.2.0 Pre-Release Product Quality Assessment

* **Date:** September 13, 2026
* **Branch:** `develop/3.2.0`
* **Commit assessed:** `fab978a62031e6a9471252b2cb2115b7ae63ef67`
* **Stable release at assessment time:** **DLMS 3.1.0**
* **Review type:** AI-assisted repository and product-quality review
* **Readiness classification:** **READY FOR RELEASE-CANDIDATE VALIDATION**
* **Historical-rubric score:** **9.747/10** (**9.75/10** rounded)
* **Mature-product score:** **9.45/10**

## Executive assessment

The assessed `develop/3.2.0` source state is the strongest audited DLMS source
state so far. It is a cohesive, professional-quality local learning application
with unusually strong automated regression coverage, defensive persistence,
bounded content intake, explicit question lineage, and mature native-release
tooling. DLMS 3.2.0 is not yet the current stable release: **3.1.0 remains the
published stable version**, and the 3.2 branch still requires its release-cut
metadata, final documentation review, and target-native artifact UAT.

DLMS was assessed according to its intended product model: a local-first,
single-user, privacy-oriented, desktop-style application with a Flask-backed
local browser interface and native packaged distribution. It is designed for
personal study and learning management, not as a SaaS, cloud collaboration, or
enterprise multi-user platform. The lack of cloud accounts, mobile clients,
telemetry, or embedded AI-provider APIs was therefore not scored as a defect.

The 3.2 work is valuable because its capabilities converge on existing quiz,
history, learning, publication, and identity boundaries instead of forming
separate products. Today’s Review provides one recommended starting point;
Learning Intelligence, Adaptive Study, Due Questions, Topic Retention,
concept-specific review, and missed-question review retain more focused roles.
Quiz Library tools now support dynamic views, mixed quiz composition, advisory
duplicate review, portable quiz bundles, and explicit generated-practice
presentation. Matching content uses the same canonical publication model across
manual, external-AI, and OCR-assisted workflows.

No code-level blocker was found in this assessment. “Ready for
release-candidate validation” means the source is appropriate for the bounded
release-cut and native-validation process. It does not pre-certify binaries that
have not yet been built from this commit, claim formal accessibility or security
certification, or guarantee defect-free behavior.

## Assessment method and score separation

Two scoring systems are retained deliberately:

1. The **historical score** uses the exact September 5 twelve-category rubric
   and weights. It answers whether DLMS improved under the established
   apples-to-apples measure.
2. The **mature-product score** applies a stricter product-sustainability rubric
   to the same commit. It gives maintainability substantial weight and judges
   workflow coherence, accessibility evidence, documentation, and release
   maturity rather than rewarding feature count alone.

The two totals are not interchangeable. In particular, architecture and
maintainability carry only 2% in the historical rubric but 15% in the stricter
rubric.

## Historical apples-to-apples assessment

### September 5 rubric applied to the current commit

| Category | Weight | September 5 | Current | Change | Current contribution |
| --- | ---: | ---: | ---: | ---: | ---: |
| Product maturity / feature completeness | 15% | 9.2 | 9.7 | +0.5 | 1.455 |
| Core workflow reliability | 15% | 9.3 | 9.9 | +0.6 | 1.485 |
| Data integrity / failure safety | 15% | 9.4 | 9.9 | +0.5 | 1.485 |
| Security / trust-boundary quality | 10% | 8.9 | 9.7 | +0.8 | 0.970 |
| Backup / restore / recovery engineering | 10% | 9.7 | 9.8 | +0.1 | 0.980 |
| UX / usability | 10% | 8.9 | 9.6 | +0.7 | 0.960 |
| Visual consistency / polish | 5% | 9.1 | 9.8 | +0.7 | 0.490 |
| Accessibility | 5% | 8.4 | 9.5 | +1.1 | 0.475 |
| Testing / regression confidence | 5% | 9.3 | 9.9 | +0.6 | 0.495 |
| Documentation / Help quality | 5% | 8.8 | 9.7 | +0.9 | 0.485 |
| Packaging / release readiness | 3% | 9.3 | 9.9 | +0.6 | 0.297 |
| Architecture / maintainability | 2% | 6.6 | 8.5 | +1.9 | 0.170 |
| **Total** | **100%** | **9.126** |  | **+0.621** | **9.747** |

The current weighted result is **9.747/10**, or **9.75/10** rounded. Under the
historical interpretation, DLMS has moved from “approaching the lower edge” of
professional production-grade quality to a **professional production-grade
open-source desktop application for its intended local, single-user model**.

### Reasons for the historical-score improvement

* **Product and workflow maturity:** 3.2 adds persistent question identity,
  cross-quiz concept intelligence, Adaptive Study, Today’s Review, native
  question scheduling, mixed quiz composition, terminology workflows, duplicate
  review, portable bundles, and Smart Views while reusing canonical quiz and
  learning infrastructure.
* **Reliability and data integrity:** generated activity resolves to explicit
  source lineage for new records; legacy fallback remains conservative; import,
  publication, restore, and history paths retain validation, atomicity, and
  rollback protections.
* **Security:** trust boundaries for imports, archives, OCR, external-AI text,
  paths, origins, and shutdown are explicit. Browser/API shutdown is now denied
  server-side in configured LAN/server mode rather than merely hidden in the UI.
* **UX and documentation:** Today’s Review is documented as the normal answer to
  “What should I study right now?”, specialized review choices have distinct
  names, generated practice is visibly classified, and Help covers the major
  3.2 workflows without exposing roadmap identifiers.
* **Visual and accessibility quality:** responsive and four-theme regressions
  have objective browser coverage; keyboard hotspot authoring, live regions,
  named groups, table scopes, focus states, forced-colors handling, and clearer
  secondary actions improve access without a claim of formal conformance.
* **Testing and sustainability:** workflow-scoped Firefox isolation, semantic
  page readiness, live-element actions, and `pagehide` synchronization have
  replaced shared state and timing assumptions. Locked CI, scheduled/manual
  Firefox execution, dependency auditing, Dependabot, `SECURITY.md`, and
  contributor guidance now preserve those expectations.
* **Packaging:** a native host can build, verify, final-package, verify/smoke,
  and hash its own release file. The coordinated six-package checksum flow and
  platform-specific layouts remain intact.
* **Maintainability:** Blueprint/service/template ownership remains established;
  question identity and generated-session classification are centralized; and
  Today’s Review composition now has a dedicated service. Large concentration
  points remain, so this category intentionally stays below the others.

## Stricter mature-product assessment

This rubric deliberately makes sustainable ownership as important as feature
quality, engineering confidence, UX, and data protection. It is not a
recalculation of the September 5 score.

| Category | Weight | Score /10 | Contribution |
| --- | ---: | ---: | ---: |
| Product Quality | 15% | 9.7 | 1.455 |
| Engineering Confidence | 15% | 9.9 | 1.485 |
| UX / Usability | 15% | 9.2 | 1.380 |
| Maintainability | 15% | 8.5 | 1.275 |
| Security / Data Integrity | 15% | 9.8 | 1.470 |
| Accessibility | 10% | 9.3 | 0.930 |
| Release Engineering | 10% | 9.8 | 0.980 |
| Documentation / Sustainability | 5% | 9.5 | 0.475 |
| **Overall Product Maturity** | **100%** |  | **9.450** |

### What keeps each mature-product category from scoring higher

* **Product Quality — 9.7:** the product is broad and coherent, but OCR remains
  probabilistic and generated-session retention can still create library volume
  that presentation mitigates rather than manages as a lifecycle.
* **Engineering Confidence — 9.9:** local and browser suites are unusually
  strong, but one source-level test environment cannot replace final UAT on the
  exact 3.2 native packages for all six targets.
* **UX / Usability — 9.2:** Help and Today’s Review significantly reduce
  ambiguity, but the number of related review and library-management workflows
  still creates learning cost for a new user.
* **Maintainability — 8.5:** ownership is much clearer than before
  modularization, yet `app.py` (6,626 lines), `static/style.css` (15,316 lines),
  `tests/browser/test_critical_workflows.py` (9,250 lines),
  `dlms/routes/pdf_import.py` (2,581 lines), and
  `dlms/services/learning.py` (1,449 lines) remain meaningful concentration
  points. Broad decomposition immediately before release would carry more risk
  than value.
* **Security / Data Integrity — 9.8:** the local threat model and untrusted-input
  boundaries are strong. Explicit LAN mode intentionally provides neither user
  authentication nor TLS and must remain restricted to a trusted network.
* **Accessibility — 9.3:** semantic, keyboard, contrast, focus, zoom, responsive,
  and forced-colors work is substantial. A comprehensive manual screen-reader
  and assistive-technology review has not been performed, so formal WCAG
  conformance is not claimed.
* **Release Engineering — 9.8:** OCR bundle preparation, a strict frozen probe,
  artifact and final-package verification, per-host packaging, and exact final
  archive checksums form a mature process. The exact 3.2 artifacts still need
  target-native building, smoke verification, and UAT.
* **Documentation / Sustainability — 9.5:** Help, release/OCR guidance,
  contributor instructions, CI, dependency checks, and the security policy are
  strong. Stable 3.1-facing material is correctly not yet rewritten as 3.2, so
  release notes, version metadata, and final user-facing release review remain
  deliberate release-cut work.

The stricter weighted score is **9.45/10**. The appropriate classification is
**mature, professional-quality local-first software that is ready for
release-candidate validation after bounded release-cut work**.

## Effect of the latest September 13 polish

The four changes after the preceding read-only Dual Quality Assessment were
reviewed explicitly:

1. The mastery dialog now explains its four inputs in plain language before
   exposing technical thresholds, without changing the model.
2. Quiz recovery’s Start Over action now uses the shared semantic
   secondary-control tokens across all four themes and remains visually
   subordinate but actionable.
3. Configured LAN/server mode exposes an accessible shutdown explanation and
   rejects direct `POST /api/shutdown` requests server-side; loopback desktop
   and browser-presence behavior remain unchanged.
4. The sticky Learning Intelligence Practice column now paints an opaque theme
   base beneath its themed surface, preventing adjacent text from ghosting at
   constrained widths while keeping the action pinned.

These are material defect closures and strengthen the evidence behind UX,
visual consistency, accessibility, security, and browser confidence. They do
not change either aggregate score. The relevant categories were already scored
to one decimal across the whole product, and remaining product-wide limitations
still bound the next tenth: workflow density, manual assistive-technology
validation, front-end concentration, generated-session lifecycle, and exact
3.2 native UAT. Increasing a score for each localized correction would imply
precision the rubrics do not support.

## Product and learning-workflow quality

DLMS is now substantially more than a quiz runner. It supports manual and
imported choice and matching content, Study and Exam modes, History, Analytics,
Learning Intelligence, concept-aware and scheduled review, Study Packs, Content
Packs, image/hotspot study, Anki interchange, OCR/PDF ingestion, external-AI
prompt-and-paste workflows, backup/restore, and portable quiz exchange.

The best integration choice is the use of shared canonical boundaries:

* Question Identity Contract v2 separates “same learning source” from “possible
  duplicate,” preserves explicit generated-copy lineage, and keeps conservative
  normalized-text fallback for legacy records.
* Today’s Review composes existing due, concept, adaptive, unfinished, and Study
  Pack signals rather than creating another recommendation model.
* Due Questions and Topic Retention Schedule remain distinct question-level and
  concept-level scheduling tools.
* External-AI and OCR matching content converge on shared matching validation,
  Review & Repair, and publication instead of introducing new storage models.
* Mixed quizzes preserve source lineage; duplicate detection remains advisory;
  portable bundles exclude user learning history and installation-local IDs.
* Smart Views are derived filters over the Quiz Library and do not mutate folder
  placement or create another organization store.

Some conceptual load remains. Smart Review, Concept Review, Adaptive Study, Due
Questions, Topic Retention, and missed-question review have legitimate separate
purposes, but their distinctions depend on good guidance. The revised Help and
Today’s Review default make this acceptable for 3.2; further new study engines
would currently add less value than continued consolidation and observation.

## Reliability, integrity, and security

The application retains unusually strong safeguards for a local personal tool:

* canonical publication, editing, history recording, restore, and multi-store
  operations use validation, atomic writes or staged promotion, journaling,
  compensation, and startup reconciliation where the boundary requires them;
* malformed or ambiguous imported content is rejected or retained for manual
  Review & Repair rather than silently invented;
* backup/restore has structural and semantic validation, traversal and ownership
  checks, a safety backup, lock-scoped operation, rollback, and recovery;
* persistent question UIDs and nullable lineage fields are additive and retain
  safe legacy loading without an ambiguous historical backfill;
* generated review copies contribute learning evidence through canonical source
  identity without becoming independent scheduling sources;
* CSRF, same-origin checks, request and upload limits, archive/path validation,
  safe rendering, and bounded OCR subprocess behavior protect the principal
  local trust boundaries; and
* LAN/server mode is explicitly treated as trusted-network operation without
  authentication or TLS. Automatic presence shutdown and browser/API manual
  shutdown are unavailable in that mode based on runtime configuration, not an
  individual request address.

Residual risks are proportionate to the product model. Backups are not a
distributed point-in-time snapshot, hard power failure cannot be eliminated at
every filesystem boundary, OCR can require human correction, and a process with
access to the user’s operating-system account can generally read DLMS data.

## Firefox and automated-test reliability

Browser confidence is now strong. Each Firefox workflow owns a separate data
root, Flask server, Firefox process/profile, and BiDi context. The harness uses
live element origins for actions, explicit page readiness, and a `pagehide`
checkpoint where browser-local recovery must be observed across contexts.
Structural tests protect those synchronization and cleanup contracts.

At the assessed commit, the complete opt-in Firefox suite passed **68/68** in
**211.41 seconds**. This resolves the September 10 audit’s 54/55 result and the
later full-suite-only backup/recovery flakes without retries, blanket sleeps, or
weakened assertions. The suite covers the latest mastery, shutdown, four-theme
secondary-action, and sticky Practice-column contracts in addition to the main
product workflows.

The normal GitHub CI job uses locked Python 3.14 runtime, test, and build-tool
requirements; runs `pip check`, release-tooling tests, the full non-browser
suite, diff hygiene, and checkout-cleanliness checks; and runs on pushes and pull
requests. The complete Firefox gate is scheduled weekly and can be dispatched
manually, which gives release evidence without making every pull request depend
on a long hosted browser job. A weekly/manual dependency audit and Dependabot
provide a proportionate open-source security baseline.

## Accessibility status

DLMS has meaningful accessibility engineering rather than only aspirational
copy. Current evidence covers explicit form naming, table header scopes, named
and stateful control groups, `aria-pressed` synchronization, live status and
alert regions, keyboard-operable quiz and matching interactions, visible focus,
color-independent state, all-theme contrast checks, responsive geometry,
forced-colors behavior, and keyboard hotspot authoring. The latest mastery
dialog includes a focusable disclosure inside its focus trap, and LAN-mode
shutdown unavailability is persistent text associated with the disabled action
rather than a hover-only tooltip.

This assessment does **not** claim formal WCAG conformance. Automated semantic,
contrast, and Firefox checks do not replace sustained manual testing with major
screen readers, operating-system high-contrast combinations, alternate input
devices, and a broader range of real user content. Image/hotspot authoring is
keyboard-capable but remains inherently more spatial than ordinary forms.

## Architecture and maintainability

The post-modularization architecture remains sound: route-family ownership,
external templates, service and persistence boundaries, canonical publication,
and structural closure tests substantially reduce the risk that once existed in
the monolithic application. Identity and generated-quiz classification now have
central services. Extracting deterministic daily-review composition from
`learning.py` created a meaningful ownership seam without altering scoring.

The remaining large files are real but bounded maintenance costs. The stylesheet
has accumulated many feature-owned component rules; the browser suite is
deterministic but difficult to navigate; `app.py` remains the composition and
runtime-policy root; and PDF import and learning services still carry multiple
related responsibilities. These concentrations can slow review and make cascade
or synchronization regressions harder to diagnose. They have not produced an
unreliable core, and a pre-release broad split would endanger more behavior than
it would protect. Future decomposition should follow a concrete feature or
defect seam and preserve current contract tests.

## Release-engineering maturity

The release toolchain covers deterministic local OCR-bundle discovery and
validation, a strict frozen OCR probe, PyInstaller resource requirements,
artifact structure and architecture checks, runtime-data exclusion, version
checks, smoke launch, final package creation, final-package verification, and
checksums. Single-target packaging leaves each native build host with the exact
verified final archive that will be transferred. The combined release machine
can validate those exact bytes and generate the authoritative six-package
`SHA256SUMS` without the intermediate build artifacts.

Platform layouts remain explicit:

* macOS places `DLMS.app`, `README.txt`, and `sample_quiz.txt` at the ZIP root
  without a wrapper directory;
* Windows and Linux use their established versioned wrapper with the stable
  executable name and the two authoritative text assets; and
* Linux executable permissions and macOS bundle-root behavior are verified.

All six 3.1.0 targets have project-reported native build and smoke-verification
evidence: Fedora 44, Ubuntu 24.04, Ubuntu 26.04, Omarchy/Arch, Windows 11, and
macOS Apple Silicon. That evidence demonstrates the process but does not replace
building and testing the exact future 3.2.0 packages on their native hosts.

## Objective strengths

1. **A coherent local learning loop.** Creation and import lead through normal
   quizzes, history, intelligence, targeted practice, scheduling, and portable
   study tools without requiring a cloud account.
2. **Data and assessment integrity.** Explicit lineage, server-side validation,
   atomic publication, durable acknowledgement, recovery, and conservative
   legacy behavior protect user work and analytics.
3. **Safe content intake.** PDF, OCR, image, archive, restore, portable-bundle,
   and external-AI inputs have bounded, testable trust boundaries and manual
   repair where inference is uncertain.
4. **Regression depth.** A large non-browser suite, 68 isolated real-Firefox
   workflows, structural contracts, failure injection, CI, and repository
   hygiene checks provide strong change confidence.
5. **Release discipline.** Native OCR resources, licenses, app/package layouts,
   smoke behavior, final bytes, and checksums have authoritative tooling rather
   than informal shell conventions.
6. **Product-model clarity.** Privacy, single-user operation, local data,
   provider-neutral external AI, and trusted-LAN limits are stated consistently.

## Remaining limitations and release/UAT work

### Required before 3.2 release publication

1. Set the release version only through the normal approved release-cut process;
   update 3.2 release notes and user-facing stable-version references together.
2. Build the exact release commit natively on each supported target, prepare and
   validate its OCR bundle, run the strict frozen probe, and complete artifact
   smoke and platform UAT.
3. Produce and verify each final package locally, transfer the exact verified
   bytes, compare hashes, generate/validate the combined `SHA256SUMS`, and check
   the final published assets.
4. Perform focused manual exploratory UAT across a fresh installation and an
   upgraded representative data set, including keyboard/zoom/theme review and
   critical backup/restore, import, quiz, and shutdown paths.

### Non-blocking limitations

1. Generated practice remains persisted quiz material. Badges and the Generated
   Practice Smart View improve recognition, but there is no archive/cleanup
   lifecycle. Automatic deletion would risk history and should not be added
   immediately before release.
2. The breadth of review options still requires Help and sensible defaults;
   adding another study engine would currently reduce coherence.
3. Manual screen-reader and broader assistive-technology validation has not
   reached the depth of automated coverage.
4. Large CSS, browser-test, application-composition, learning, and PDF-import
   files remain maintainability concentration points.
5. Hosted Firefox and dependency auditing are scheduled/manual rather than hard
   pull-request gates. This is a reasonable speed/reliability tradeoff for the
   project, but maintainers must run the release gate deliberately.
6. OCR and AI-assisted structured text are untrusted and sometimes ambiguous;
   Review & Repair remains a necessary user responsibility.

## Score stability since the Dual Quality Assessment

The prior read-only Dual Quality Assessment measured **9.747/10** on the
September 5 rubric and **9.45/10** on the stricter rubric. Both remain
appropriate at this commit. The intervening fixes close specific known defects
and make the assessment more defensible, but do not erase the broader limitations
that cap UX, accessibility, maintainability, documentation, and pre-release
validation scores.

The unchanged result is not a judgment that the latest work lacked value. It is
evidence that these rubrics measure durable product characteristics at
one-decimal category resolution rather than counting patches. The branch is
safer and more polished within the same score band.

## Validation performed

* Complete Firefox release gate: **68 passed** in **211.41 seconds**.
* Full non-browser suite: **1,388 passed**, **68 browser tests deselected**, and
  **2,346 subtests passed** in **13.72 seconds**.
* Focused audit, Help, repository-quality, release-hygiene, browser-harness,
  theme, and layout tests: **136 passed** and **1,038 subtests passed** in
  **1.46 seconds**.
* Dependency consistency: `pip check` reported no broken requirements.
* Markdown targets in the audit index and this record were checked locally.
* `git diff --check` passed. Repository status contained only this new audit and
  its intended index update.
* Current branch, commit, Git history, September 3/5/8/10 audits, current Help,
  identity and learning services, browser harness, CI/security/contributor
  files, release/OCR tooling, packaging documentation, and the latest polish
  changes were inspected directly.
* No binaries or release packages were rebuilt.

## Limitations of this assessment

This is a curated, evidence-based repository and product assessment, not an
independent third-party audit, penetration test, accessibility certification,
compliance attestation, OpenAI/Codex certification, endorsement, or guarantee of
defect-free software. Automated tests and code review cannot establish the
absence of every defect. Native release claims apply only to exact artifacts
that pass the documented per-target gates.

Earlier audit records remain unchanged. Their scores describe their historical
repository states; this assessment neither rewrites them nor averages their
results.
