# DLMS 3.1.0 Product Quality Assessment

* **Date:** September 10, 2026
* **Review type:** AI-assisted repository and product-quality review
* **Readiness classification:** **READY WITH NON-BLOCKING DEBT**
* **Weighted overall score:** **9.584/10**
* **Rounded weighted score:** **9.58/10**

## Executive assessment

DLMS 3.1.0 is a professional-quality, release-ready open-source desktop
learning application for its intended local, single-user product model. It was
assessed as a Flask-backed local browser UI distributed in native packages, not
as a SaaS platform or enterprise multi-user service. Cloud infrastructure,
horizontal scaling, enterprise identity, distributed coordination, and
commercial observability were therefore not treated as missing requirements.

The application has improved materially since the September 8 assessment.
DLMS now combines mature quiz, study, analytics, content-pack, domain-study,
backup, restore, and recovery capabilities with browser-presence lifecycle
management, in-progress quiz recovery, screenshot and scanned-PDF OCR, a shared
2--26-choice Review & Repair model, application-wide semantic themes, Study
Pack domain filtering, and a provider-neutral External AI Quiz Builder. These
additions were implemented with bounded parsers, explicit correctness review,
transient staging, atomic canonical publication, and extensive regression
coverage rather than as loosely connected feature paths.

No current issue materially prevents calling DLMS professional-quality for its
intended use. It is not defect-free, formally accessibility-certified, or
validated on every planned native target. The most important current evidence
gap is target-native OCR validation for Ubuntu 26.04, Omarchy/Arch, and macOS
ARM64. The assessment also reproduced one Firefox automation-readiness race in
the scanned-PDF bulk-confirmation workflow; 54 of 55 browser workflows passed.
The failure occurs when the test acts after review markup exists but before the
shared review script has initialized, and did not demonstrate an OCR,
confirmation, save, or publication defect. It is nevertheless real
non-blocking test debt and is not excluded from the score.

## Assessment method

The application was scored independently against its current repository state
before comparison with the September 8 result. The same documented 12-part
weighted method was retained so the final comparison remains meaningful. Raw
test volume was treated as supporting evidence, not as a substitute for design,
failure-mode, usability, or maintainability analysis.

## Weighted scorecard

| Category | Weight | Score /10 | Contribution |
| --- | ---: | ---: | ---: |
| Product maturity / feature completeness | 15% | 9.6 | 1.440 |
| Core workflow reliability | 15% | 9.7 | 1.455 |
| Data integrity / failure safety | 15% | 9.8 | 1.470 |
| Security / trust-boundary quality | 10% | 9.4 | 0.940 |
| Backup / restore / recovery engineering | 10% | 9.8 | 0.980 |
| UX / usability | 10% | 9.4 | 0.940 |
| Visual consistency / polish | 5% | 9.5 | 0.475 |
| Accessibility | 5% | 9.3 | 0.465 |
| Testing / regression confidence | 5% | 9.7 | 0.485 |
| Documentation / Help quality | 5% | 9.4 | 0.470 |
| Packaging / release readiness | 3% | 9.6 | 0.288 |
| Architecture / maintainability | 2% | 8.8 | 0.176 |
| **Total** | **100%** |  | **9.584** |

The weighted calculation is **9.584/10**, rounded to **9.58/10**. The
category weights total exactly 100%.

## Separate headline scores

| Measure | Score |
| --- | ---: |
| Product Quality | **9.6/10** |
| Engineering Confidence | **9.8/10** |
| UX / Usability | **9.4/10** |
| Maintainability | **8.8/10** |

Product quality reflects the breadth and cohesion of the learning system, not
merely the number of workflows. Engineering confidence is driven by bounded
trust boundaries, atomic persistence, recovery design, failure injection, and
cross-layer tests. UX improved through recovery, coherent themes, Help
discoverability, and safer repair workflows. Maintainability remains the
lowest headline score because the back-end composition root, global stylesheet,
some template-local JavaScript, and browser regression file remain large even
though ownership boundaries are now explicit.

## Maturity classification

**Professional-quality, release-ready open-source desktop learning application
for its intended local, single-user model, with advanced import and recovery
capabilities.**

This classification does not imply enterprise tenancy, high availability,
formal security certification, formal WCAG conformance, signed/notarized
distribution, or current native validation on every proposed target. Those are
separate product or release-process concerns.

## Current product quality and usability

DLMS has a broad but coherent product surface: manual and imported quizzes,
Study and Exam modes, History and Analytics, Learning Intelligence and Smart
Review, Quiz Library organization, IT/Medical/Law study areas, Study Packs,
Content Packs, image and hotspot study, Anki interchange, settings, backup and
restore, and guided Help. Recent work closes several practical usability gaps:

* Quiz Library folder identity, filtering, ordering, collapsed-state cleanup,
  long-content containment, and semantic hierarchy are now explicitly tested.
* Browser presence can automatically stop a loopback desktop-style session
  after its browser disappears, while LAN/server mode deliberately suppresses
  automatic shutdown.
* In-progress quiz recovery is bounded, fingerprinted, time-limited, and
  user-controlled. It preserves Study/Exam distinctions and avoids clearing
  unrelated browser storage.
* Light, Dark, Purple & Gold, and Maroon & Gold share semantic component tokens
  while retaining their identities. Recent work covers content details,
  library hierarchy, builders, Review & Repair, contrast, focus, disabled
  states, and narrow layouts.
* Help now exposes substantive topics through its main contents and shared
  navigation, including PDF & Image Import and External AI Quiz Builder, while
  retaining compatibility links.

The local browser presentation remains an appropriate desktop interface for
the product. It is not penalized for lacking a cloud account or synchronized
multi-device state. The principal UX limitation is inherent in OCR and
AI-assisted authoring: users must still inspect uncertain source material and
confirm correctness. DLMS presents that as an explicit workflow responsibility
rather than hiding uncertainty, which is a product strength rather than a
defect.

## OCR and Review & Repair maturity

DLMS-119 is a substantial quality gain, not a superficial file-picker feature.
It supports screenshot batches and selective scanned-PDF pages, preserves the
normal selectable-text PDF path, and uses Tesseract TSV observations plus
bounded layout inference. Review & Repair supports 2--26 A--Z choices,
single- and multiple-answer questions, choice editing and ordering,
explanations, exclusion, individual and selected-question confirmation, source
previews, OCR confidence/provenance, and explicit issue reporting.

Correctness safety is appropriately conservative:

* radio/checkbox selection, row color, and highlighting are not correctness
  evidence;
* an X marker is negative evidence only;
* marker association is gated by recovered sequence integrity;
* proposed correct answers do not bypass user confirmation; and
* server-side validation remains authoritative at save/publication boundaries.

The OCR service bounds files, aggregate upload size, dimensions, pixels,
subprocess duration, cancellation, staging, and abandoned-draft cleanup. The
25-image batch limit remains subordinate to the unchanged 64 MiB aggregate cap
and sequential processing contract. OCR is necessarily probabilistic across
fonts, vendors, crops, and image quality. Keeping low-confidence cases in
Review & Repair is the correct product boundary; pursuing automatic recovery
at the expense of correctness integrity would reduce quality.

## External AI workflow quality

DLMS-122 adds an external conversational-AI workflow without coupling DLMS to
providers, APIs, credentials, or cloud availability. The existing AI Study
Pack archive workflow remains separate and protected. The new path asks for
one structured quiz envelope, accepts bounded bare or singly fenced JSON,
rejects duplicate keys and ambiguous mixed responses, and stages normalized
review data under opaque transient identifiers.

Its parser and shared review boundary enforce schema version and content type,
1 MiB paste size, bounded nesting and strings, at most 100 questions, 2--26
distinct choices, real JSON booleans, answer-mode/correct-set agreement, source
URL safety, unknown-field diagnostics, duplicate visibility, and no automatic
URL fetching or AI-provided paths. Choice order is randomized before review,
with correctness and choice-associated metadata moving together; positional
A--Z labels are assigned by DLMS. Every active question still requires the user
to confirm the complete displayed correct-answer set.

After review, External AI converges at the existing atomic quiz-publication
service. It does not create a second persistence model, enter installed Content
Packs, or retain raw AI text in durable quiz data. Publication failure preserves
the draft; successful publication and explicit cancellation remove it. This is
a well-bounded additive design.

## Architecture and maintainability

The DLMS-061 and DLMS-062 gains remain intact. The current application has 16
Blueprint families and a frozen 199-rule explicit URL-map contract: 198 rules
are Blueprint-owned and only `POST /api/shutdown` remains intentionally owned
by `app.py`. The 21 route modules use frozen family-specific dependency objects
and do not import the top-level application module. All 64 Jinja templates are
external files with closure coverage.

Dedicated parsing, persistence, service, rendering, and route modules now own
OCR, External AI, question review, publication, content packs, backup/restore,
domain study, and other feature boundaries. Source-neutral question-review
helpers allow OCR/PDF and External AI to reuse 2--26-choice validation and bulk
confirmation without exposing OCR-only fields in the AI workflow. This is a
good example of convergence at a stable domain boundary rather than premature
generalization.

The remaining concentration is visible and should not be minimized:

* `app.py` is 6,271 lines and still carries application construction,
  configured adapters, global policy, process lifecycle, locks, and service
  composition.
* `static/style.css` is 14,395 lines. Semantic tokens improve consistency, but
  cascade and selector interaction still carry maintenance cost.
* `tests/browser/test_critical_workflows.py` is 7,412 lines and 55 workflows in
  one file, making navigation and synchronization conventions harder to review.
* Some substantial page behavior remains template-local JavaScript.

These are non-blocking maintainability costs, not evidence that the DLMS-061
architecture failed. Further extraction should be feature- or defect-driven
and preserve the explicit closure contracts; line-count reduction alone is not
a sufficient goal.

## Persistence, recovery, and failure safety

DLMS continues to provide unusually strong local-data safety:

* JSON/text persistence uses validated same-directory temporary files,
  flushing, `fsync`, atomic replacement, cleanup, and best-effort directory
  synchronization.
* Malformed user data is preserved for recovery instead of silently replaced.
* Quiz publication stages artifacts and uses a validated operation journal,
  compensation, and startup reconciliation across SQLite, generated files,
  registry state, and optional assets.
* Restore uses semantic validation, safe-path and ownership checks, a safety
  backup, a process-wide lock, journaling, rollback, and startup recovery.
* Image Study Pack creation now stages, validates, and promotes a complete pack
  before canonical quiz publication, resolving the September 8 partial-folder
  crash-consistency debt.
* Quiz Library folder mutations use canonical identity and coordinated,
  lock-scoped updates; stale client state is reconciled without destructive
  browser-storage clearing.
* External AI and OCR drafts are bounded transient stores excluded from normal
  durable content and backup behavior.
* DLMS-118 recovery is deliberately browser-local, bounded, and opt-in at the
  restore point, which suits in-progress single-user quiz state.

Single-process locking and multi-store compensation remain appropriate to this
desktop model. Backups are not a distributed global snapshot, and hard power
loss at every possible filesystem boundary cannot be made impossible. Those
limitations are proportionate and do not undermine the professional-quality
classification.

## Security and accessibility

Security boundaries are appropriate and increasingly explicit. DLMS defaults
to loopback, protects unsafe requests with CSRF and same-origin checks, bounds
HTTP bodies and workflow-specific uploads, validates archive/raster/JSON
content, constrains filesystem targets beneath owned roots, avoids AI URL
fetching, and escapes untrusted text through Jinja. Shutdown is session-bound
and protected. OCR subprocesses have explicit executable/data discovery,
timeouts, cancellation, output bounds, and frozen-resource rules. LAN binding
remains an intentionally documented trusted-network mode without authentication;
it should not be presented as an Internet-facing security model.

Accessibility has improved through explicit labels, keyboard-operable controls,
focus-visible states, disclosure semantics, status/alert announcements,
non-color-only state communication, responsive Review & Repair controls, and
contrast coverage for all four themes. Automated contrast and browser checks
provide meaningful evidence, but they are not a substitute for a full manual
screen-reader and assistive-technology review. Image/hotspot authoring also
remains more pointer-oriented than the learner-facing quiz experience.

## Packaging and release maturity

Packaging is mature for an open-source native desktop project. `APP_VERSION`
is the authoritative version source; PyInstaller metadata and release tooling
derive or validate against it. Canonical artifact/package names, architectures,
contents, checksums, executable modes, macOS bundle metadata, resource
exclusions, clean extraction, controlled data roots, launch, routes, protected
shutdown, and restart have dedicated verification tools and tests.

The frozen OCR contract is unusually explicit. Native builders supply a
platform-specific Tesseract bundle through `DLMS_TESSERACT_BUNDLE_ROOT` with the
executable, dependent native libraries, English trained data, TSV config, and
Tesseract/tessdata/Leptonica licenses. PyInstaller also includes
`pypdfium2`/PDFium and license metadata. Frozen DLMS accepts only bundled OCR
resources and cannot silently fall back to a host Tesseract installation.

Current target evidence is:

* Fedora x86-64 OCR-enabled frozen builds were validated during DLMS-119;
* Ubuntu 24.04 x86-64 DLMS 3.1.0 was built and exercised on a clean/production
  Ubuntu system without system Tesseract;
* Windows 11 x86-64 DLMS 3.1.0 was built and exercised on a clean Windows
  system without system Tesseract; and
* Ubuntu 26.04, Omarchy/Arch x86-64, and macOS ARM64 still require current
  3.1.0 target-native OCR validation.

Pending target validation is release work, not a code defect. It does mean an
artifact for one of those targets should not be advertised as OCR-validated
until its documented native gate passes.

## Meaningful weaknesses, debt, and opportunities

### Demonstrated issue

1. **Firefox scanned-PDF review readiness race.** The current audit's full
   browser run passed 54 workflows and reproducibly failed one scanned-PDF bulk
   confirmation workflow because the test dispatched selection immediately
   after review markup appeared, before the shared review JavaScript had
   initialized the action. The empty status and disabled confirmation state
   distinguish this from a parser or server-side confirmation failure. The
   browser test should wait for an explicit editor-ready condition. If that
   condition does not exist, adding a small semantic readiness signal would
   improve both testability and failure diagnosis.

### Non-blocking technical debt

1. **Front-end and composition concentration.** The large stylesheet, browser
   file, template-local scripts, and application composition root raise change
   review cost despite sound module ownership.
2. **OCR variability.** The parser is well-defended, but unusual vendor layouts,
   degraded scans, dense cards, or ambiguous markers will continue to require
   manual repair. This is controlled residual risk, not fully removable debt.
3. **Accessibility verification depth.** Manual screen-reader, zoom/reflow,
   high-contrast, and assistive-technology validation has not reached the same
   depth as automated semantic and browser checks.
4. **Exact structural closures.** Route/template/resource signatures are
   powerful regression gates but create deliberate maintenance overhead when
   adding legitimate resources.

### Future product opportunities

1. External AI could eventually support additional canonical content types,
   but quiz-only scope is a strong MVP and expansion should not weaken the
   current archive workflow or parser boundaries.
2. OCR could gain more neutral-layout corpus coverage and clearer per-field
   diagnostics. A background queue is not presently required for the bounded,
   sequential local workflow.
3. More granular browser-test organization and shared page objects could reduce
   maintenance cost if browser coverage continues to grow.

### Release-process validation work

1. Complete the documented 3.1.0 OCR-native gate on Ubuntu 26.04,
   Omarchy/Arch, and macOS ARM64 before publishing those targets as validated.
2. Perform final clean-extract smoke and native UAT on each exact distributable,
   not merely on an intermediate PyInstaller output.
3. Continue treating signing/notarization as a documented distribution choice,
   not as an unacknowledged capability.

## Highest-value remaining improvements

1. **Close target-native OCR validation.** This gives the highest immediate
   release-confidence return without changing application behavior.
2. **Harden the shared-review browser readiness contract.** Fix the single
   reproducible test synchronization gap and keep the full Firefox suite green.
3. **Conduct a manual accessibility pass.** Prioritize screen-reader flow,
   200%/400% zoom and reflow, and image/hotspot authoring keyboard use.
4. **Modularize front-end code only at demonstrated seams.** When a relevant
   feature next changes the library, builders, or review editor, extract shared
   scripts/styles and split browser coverage by domain rather than undertaking
   a broad rewrite.
5. **Continue evidence-led OCR hardening.** Use private real inputs only for
   local validation and permanent neutral/generated fixtures for regression;
   preserve the current correctness-integrity rules.

None of these items materially prevents the professional-quality classification.

## Comparison with September 8

| Measure | September 8 | September 10 | Change |
| --- | ---: | ---: | ---: |
| Product Quality | 9.4 | 9.6 | +0.2 |
| Engineering Confidence | 9.7 | 9.8 | +0.1 |
| UX / Usability | 9.1 | 9.4 | +0.3 |
| Maintainability | 8.5 | 8.8 | +0.3 |
| Weighted overall score | 9.398 | 9.584 | +0.186 |
| Rounded overall score | 9.40 | 9.58 | +0.18 |

The largest improvements are DLMS-118 recovery, DLMS-119 screenshot and
scanned-PDF OCR with shared Review & Repair, DLMS-120 semantic theme coverage,
DLMS-122 bounded External AI quiz creation, and native OCR packaging evidence
on Ubuntu and Windows. The September 8 DLMS-115/116 folder findings, Law
canonicalization decision, and Image Study Pack partial-folder risk were also
addressed through canonical folder identity, client-state reconciliation,
strict Law identities, and staged pack promotion.

Architecture grew from 15 to 16 Blueprint families, 178 to 199 explicit URL
rules, and 58 to 64 external templates while retaining explicit closure gates.
The new breadth increased `app.py` and front-end/test concentration, so the
maintainability improvement is meaningful but intentionally modest.

## Stable-release readiness

**READY WITH NON-BLOCKING DEBT.** No code-level release blocker was identified.
The current repository is suitable for normal release preparation and for
publishing exact native targets after each target's required verification and
UAT. “Ready” applies to the application and the targets that pass their gates;
it does not pre-certify the still-unvalidated Ubuntu 26.04, Omarchy/Arch, or
macOS ARM64 OCR artifacts.

## Validation performed

* Full non-browser suite: **1,203 passed, 55 browser tests deselected, 2,133
  subtests passed** in 11.27 seconds.
* Full Firefox suite: **54 passed, 1 failed** in 147.07 seconds. The single
  scanned-PDF review failure was rerun alone and reproduced in 2.91 seconds.
* Dependency consistency: `pip check` reported no broken requirements.
* Static Python compilation: **198 Python source files** compiled in memory.
* Route-closure inspection confirmed **199 explicit rules**, **198
  Blueprint-owned rules**, and **16 Blueprint families**.
* Template inventory confirmed **64 external Jinja templates**.
* Packaging/OCR contracts, release-verification documentation, parser bounds,
  transient-draft safety, atomic publication, restore/recovery, themes,
  accessibility, and Help/navigation coverage were inspected directly.
* Browser-process cleanup check found no lingering Firefox or geckodriver
  process from the assessment.
* `git diff --check` and repository status were clean before documentation was
  added.

No binaries were rebuilt. The Ubuntu and Windows clean-machine results stated
above are validated project evidence supplied for the current 3.1.0 state, not
tests rerun by this repository assessment.

## Limitations

This is an evidence-based repository and product assessment, not a formal
third-party audit. It did not perform a dependency vulnerability scan, manual
screen-reader certification, exhaustive exploratory UX session, power-loss
hardware test, or native build on every target. Automated tests and source
inspection cannot establish the absence of all defects.

The one Firefox failure is included transparently. Its observed mechanism
supports the automation-readiness diagnosis, but that diagnosis should be
confirmed when the test is hardened. No application code was changed during
this assessment to prove or mask it.

This document does not overwrite earlier assessments or retroactively alter
their scores. It is not an OpenAI/Codex certification, endorsement, compliance
attestation, security guarantee, or guarantee of defect-free software.

## Evidence basis

The September 10 repository state, `AGENTS.md`, the retained September 8
assessment and its documented weighting method, current route/template closure
tests, persistence and recovery services, OCR and External AI boundaries,
theme/accessibility tests, release tooling and documentation, current native
validation facts, the full non-browser suite, and the full Firefox suite are
the basis for this assessment. The September 10 scores were assigned from the
current evidence before comparison with the historical scores.
