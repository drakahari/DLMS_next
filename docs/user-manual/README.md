# DLMS User Manual source

This directory is the canonical source for the DLMS end-user manual. It
contains the Phase 1 product audit and manual architecture for **DLMS 3.2.0**,
plus the substantive Phase 2 chapter draft and its first integrated editorial
pass. The reproducible screenshot set has also been integrated into the
chapters. Final human review and release preparation remain.

Markdown is the editable source of truth. A PDF may later be generated as an
optional distribution artifact; it is not required to maintain or use the
canonical manual and must not replace these files.

## Phase 1 files

- [Feature inventory](FEATURE_INVENTORY.md) — code-verified screens, features,
  workflows, limits, dependencies, and documentation risks.
- [Terminology](TERMINOLOGY.md) — preferred user-facing vocabulary and terms
  that need careful distinction.
- [Screenshot plan](SCREENSHOT_PLAN.md) — a prioritized, privacy-safe capture
  plan; it does not contain or request a screenshot for every page.
- [Screenshot manifest](SCREENSHOT_MANIFEST.md) — capture status, automation
  classification, filenames, and regeneration details for the 27-shot set.

These audit artifacts should remain available after the narrative chapters are
written. They provide the traceability needed to keep later editions accurate.

## Drafted manual chapters

- [1. Introduction](01-introduction.md)
- [2. Installation and First Launch](02-installation-and-first-launch.md)
- [3. Interface and Navigation](03-interface-and-navigation.md)
- [4. Creating and Importing Content](04-creating-and-importing-content.md)
- [5. Quiz Library and Organization](05-quiz-library-and-organization.md)
- [6. Taking Quizzes](06-taking-quizzes.md)
- [7. Study and Review](07-study-and-review.md)
- [8. Learning Intelligence](08-learning-intelligence.md)
- [9. History, Results, and Progress](09-history-results-and-progress.md)
- [10. PDF, Smart PDF, and OCR](10-pdf-smart-pdf-and-ocr.md)
- [11. Matching, Terminology, and Image-Based Content](11-matching-terminology-and-image-based-content.md)
- [12. External AI Workflows](12-external-ai-workflows.md)
- [13. Study Packs and Content Packs](13-study-packs-and-content-packs.md)
- [14. Anki, Decks, and Printable Cards](14-anki-decks-and-printable-cards.md)
- [15. Import, Export, and Portability](15-import-export-and-portability.md)
- [16. Settings and Runtime](16-settings-and-runtime.md)
- [17. Maintenance, Backup, and Data Management](17-maintenance-backup-and-data-management.md)
- [18. Troubleshooting](18-troubleshooting.md)
- [19. Feature and Format Reference](19-feature-and-format-reference.md)
- [Appendix: Platform and Runtime Notes](appendix-platform-and-runtime-notes.md)
- [Appendix: Privacy and Data Handling](appendix-privacy-and-data-handling.md)
- [Appendix: Keyboard and Accessibility](appendix-keyboard-and-accessibility.md)
- [Appendix: Glossary](appendix-glossary.md)

## Intended audience and boundary

The manual is for an ordinary person installing and using DLMS as a local,
single-user learning application. It should explain tasks, decisions, safety
boundaries, and recovery—not Flask routes or Python internals.

The following subjects belong primarily in maintainer documentation and should
only be summarized or linked when an end user needs the consequence:

- PyInstaller specifications and native build commands;
- OCR bundle assembly and the strict frozen OCR probe;
- artifact/package verification and six-platform release assembly;
- CI, dependency auditing, release checksums, and repository maintenance;
- implementation audits and contributor-only test procedures.

The current maintainer sources are [OCR packaging](../OCR_PACKAGING.md),
[release verification](../RELEASE_VERIFICATION.md), the
[audit index](../audits/README.md), `CONTRIBUTING.md`, and `SECURITY.md`.
End-user installation, package contents, platform warnings, data locations, and
local-versus-LAN behavior still belong in the manual because they affect use.

## Manual chapter architecture

The substantive Phase 2 draft follows this modular chapter order. Each linked
file contains review-ready prose; no empty chapter placeholders are used.

1. **[Introduction](01-introduction.md)** — product purpose, local-first model, privacy boundary,
   supported question and study material types, and how to use the manual.
2. **[Installation and First Launch](02-installation-and-first-launch.md)** — release packages, platform security
   prompts, data locations, launch behavior, Dashboard orientation, and the
   source-installation alternative.
3. **[Interface and Navigation](03-interface-and-navigation.md)** — persistent navigation, Dashboard,
   hidden subject areas, themes, Help Center, status messages, and common
   interaction patterns.
4. **[Creating and Importing Content](04-creating-and-importing-content.md)** — Build Quiz hub, manual builder, text
   file and pasted-text parsing, matching CSV, editing, validation, and
   publication.
5. **[Quiz Library and Organization](05-quiz-library-and-organization.md)** — visibility, folders, search, Smart
   Views, generated-practice labels, Mixed Quiz Builder, duplicate review, and
   safe quiz management.
6. **[Taking Quizzes](06-taking-quizzes.md)** — Study Mode, Exam Mode, choice/multi-select, matching,
   images/hotspots, results, recovery, and the browser-local checkpoint model.
7. **[Study and Review](07-study-and-review.md)** — Today’s Review as the
   default starting point, Due Questions, Adaptive Study, Smart Review,
   Concept Review, Topic Retention Schedule, and missed-question review.
8. **[Learning Intelligence](08-learning-intelligence.md)** — Learning
   Profile, concept intelligence, Mastery, Trend, limited evidence,
   diagnostics, question-quality signals, and how generated practice
   contributes to source learning evidence.
9. **[History, Results, and Progress](09-history-results-and-progress.md)** —
   attempts, missed-result review, analytics, filters, missed answers, retakes,
   and study evidence.
10. **[PDF, Smart PDF, and OCR](10-pdf-smart-pdf-and-ocr.md)** — selectable PDFs, question/glossary
    classification, saved banks, targeted/scanned OCR, screenshot OCR, Review &
    Repair, source rights, and optional OCR availability.
11. **[Matching, terminology, images, and hotspots](11-matching-terminology-and-image-based-content.md)** — canonical matching
    activities, terminology banks, CSV/OCR sources, image-study authoring,
    overlays, and keyboard use.
12. **[External AI-assisted workflows](12-external-ai-workflows.md)** — provider-neutral choice and matching
    prompt/paste flows, validation, Review & Repair, external explanation help,
    and the separate AI Study Pack ZIP flow. Emphasize that DLMS makes no
    provider API call.
13. **[Study Packs and Content Packs](13-study-packs-and-content-packs.md)** — learner catalog versus
    pack management, validation/install/export/delete, IT/Medical/Other views,
    Law Case Reviews, and image-pack creation.
14. **[Anki, Decks, and Printable Cards](14-anki-decks-and-printable-cards.md)** — guided quiz/history/Law `.apkg`
    exports, custom deck selection, and printable cards, with legacy TSV only
    as an optional advanced compatibility note.
15. **[Import, Export, and Portability](15-import-export-and-portability.md)** — text exports, Portable Quiz Bundles,
    Study Pack boundaries, collision handling, media, and what personal data is
    deliberately excluded.
16. **[Settings and Runtime](16-settings-and-runtime.md)** — themes, navigation,
    parsing, external-AI preferences, browser-presence shutdown, and the
    distinction between loopback desktop use and trusted-LAN server use,
    including the requirement to stop LAN/server processes from the host.
17. **[Maintenance, Backup, and Data Management](17-maintenance-backup-and-data-management.md)** — backup scope, staged
    restore, resets, Rebuild All Quiz Pages, safety backups, and permanent data
    removal.
18. **[Troubleshooting](18-troubleshooting.md)** — launch/browser problems, OCR
    availability, parse failures, validation states, recovery, platform
    warnings, and safe diagnostic steps.
19. **[Feature and Format Reference](19-feature-and-format-reference.md)** — supported inputs, relevant limits,
    state/persistence summary, warnings, and confirmation behavior.
20. **Appendices**
    - **[Platform and Runtime Notes](appendix-platform-and-runtime-notes.md)** — native targets,
      packaged/source differences, data locations, local desktop use, and
      trusted-LAN behavior.
    - **[Privacy and Data Handling](appendix-privacy-and-data-handling.md)** — local-first storage,
      browser-local recovery, OCR staging, external-service boundaries, and
      exported-file responsibilities.
    - **[Keyboard and Accessibility](appendix-keyboard-and-accessibility.md)** — keyboard navigation,
      matching and hotspot interaction, focus/status behavior, themes, zoom,
      and current limitations.
    - **[Glossary](appendix-glossary.md)** — concise definitions of recurring
      user-facing DLMS terms.

The narrative should link across chapters instead of repeating complete
procedures. For example, the PDF chapter should link to the shared Review &
Repair explanation, and the settings chapter should link to the full backup
safety procedure.

## Writing and structure rules

- Write for a new user first. Introduce the purpose before naming controls.
- Use the preferred terms in [TERMINOLOGY.md](TERMINOLOGY.md); mention an
  alternate label only where the interface still displays it.
- Teach end-to-end tasks. A control reference may supplement but must not
  replace workflows.
- State whether data is persistent, generated, temporary, browser-local, or
  server-shared whenever that distinction changes user expectations.
- Separate Study Mode, Exam Mode, generated practice, and source quizzes
  carefully. Do not imply that generated practice replaces or mutates sources.
- Explain confirmation gates and destructive consequences before the action.
- Treat imported, OCR-produced, and AI-produced material as requiring user
  review. Never imply that DLMS invents or guarantees correctness.
- Avoid roadmap IDs, database fields, route names, and release-engineering
  language in narrative prose.
- Use accessible headings, descriptive link text, meaningful image alternative
  text, captions, and tables with simple headers.
- Keep exact size/count limits in the reference chapter unless they are needed
  to complete a task safely.
- Identify the documented DLMS version in the manual metadata and generated
  output. Do not present an unreleased version as the currently published
  stable release.

## Documentation maintenance policy

1. Markdown in this directory is canonical.
2. The manual version tracks the DLMS release whose behavior it documents.
3. Every user-facing release change must assess its documentation impact.
4. A user-visible feature change updates the relevant chapter in the same
   release work.
5. A UI change triggers a screenshot-impact check; screenshots are replaced
   only when materially misleading.
6. Removed behavior is removed from the current manual. Released historical
   manuals and PDFs are immutable records and must not silently change.
7. Generated PDFs and intermediate combined files are build artifacts, not
   hand-edited sources.
8. Product wording follows the UI-facing terminology, not internal class,
   schema, or roadmap names.
9. A new feature is incomplete until its chapter, terminology, screenshot, and
   troubleshooting impact have been considered.

### Release documentation-impact checklist

- [ ] No user-facing documentation change
- [ ] Manual text update required
- [ ] Screenshot update required
- [ ] Root/release README update required
- [ ] Installation or platform instructions changed
- [ ] Troubleshooting update required
- [ ] Terminology/glossary update required
- [ ] Accessibility or keyboard instructions changed
- [ ] Local/LAN or browser-local/server-shared behavior changed
- [ ] Historical manual/PDF must be archived with the release

## Optional future PDF build path

No PDF tooling is installed or configured by the manual drafting work. If the
project elects to distribute a PDF, a later phase should use a small, pinned
documentation toolchain rather than manually editing a PDF.

The recommended design is:

1. Maintain an explicit chapter-order manifest.
2. Assemble the chapters into a generated combined Markdown file, preserving
   stable heading IDs and image paths.
3. Use Pandoc to create a table of contents, numbered headings, captions, and
   cross-references, then render either print-oriented HTML/CSS with WeasyPrint
   or a pinned PDF engine selected after a prototype comparison.
4. Keep page-break directives and print-only header/footer metadata in a small
   shared template/style layer rather than scattering renderer-specific markup
   through the prose.
5. Inject the application/manual version and build date from authoritative
   release metadata.
6. Produce `DLMS-User-Manual-<version>.pdf`; keep the combined Markdown/HTML,
   logs, and PDF in a generated build directory.

The prototype must verify a clickable table of contents, heading numbering,
page breaks, image scaling, captions, cross-references, accessible document
metadata, page headers/footers, and stable output on the supported build host.
Pin tool versions (or a reproducible container) only after that evaluation.
The repository should decide separately whether released PDFs are attached to
GitHub releases or retained in a versioned documentation archive.

## Phase boundaries

Phase 1 inventories and designs. The substantive Phase 2 draft now covers all
planned chapters and appendices, and the first integrated editorial pass is
complete. The first reproducible screenshot set is integrated into the
chapters. Final human review, an optional renderer prototype and PDF, and
publication are later approved phases. They must not be inferred from the
presence of this directory.
