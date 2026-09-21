# DLMS Codex Instructions

## Project

This repository contains DLMS, a local-first learning, quiz, study, analytics, and content-import application.

Treat the existing application behavior, user data compatibility, and current tests as important unless the requested task explicitly changes them.

## General Working Rules

1. Read and understand the relevant existing code before making changes.
2. Keep changes narrowly scoped to the requested task or DLMS roadmap item.
3. Do not refactor unrelated code merely because it could be cleaner.
4. Do not remove existing functionality unless the task explicitly requires it.
5. Preserve backward compatibility where reasonably possible.
6. Prefer extending existing patterns over introducing parallel implementations.
7. Avoid unnecessary dependencies.
8. Do not change application version numbers unless explicitly instructed.
9. Do not commit, push, merge, tag, or create releases unless explicitly instructed.
10. Never discard or overwrite unrelated uncommitted user changes.

## Before Editing

Before implementing a change:

* Inspect the relevant routes, functions, templates, styles, JavaScript, models, persistence code, and tests.
* Trace the existing workflow far enough to understand its inputs, outputs, validation, persistence, and downstream consumers.
* Check whether the requested behavior already exists partially elsewhere in DLMS and can be reused.
* Identify likely regression risks before editing.

For bug fixes, reproduce or establish the failure mode when practical before changing code.

## Scope Discipline

A roadmap item should remain its own change unless another modification is necessary for correctness.

If you discover unrelated problems:

* Do not silently fix them.
* Report them separately.
* Explain whether they are defects, cleanup opportunities, test gaps, or possible future roadmap items.

Do not expand the requested scope just because adjacent code could also be improved.

## GitHub Roadmap Workflow

The [DLMS Development Roadmap](https://github.com/users/drakahari/projects/1) is authoritative for current and future planning. GitHub Issues contain task scope, acceptance criteria, decisions, dependencies, and completion evidence. Project fields contain the current Status, Area, Release, Work Type, and Priority. Repository code, tests, and artifacts remain authoritative for actual behavior and implementation evidence. Historical completed DLMS work remains in repository documentation and history rather than being bulk-created as GitHub issues.

The normal issue lifecycle is:

`Backlog` → `Planned` → `In Progress` → `Ready for Review` → `Done`

`Blocked` may temporarily interrupt active work. `Not Planned` is a terminal disposition for rejected or superseded work. `Ready for Review` means agent implementation is complete and required validation passed, but owner review is still required. Only explicit owner acceptance authorizes moving an item from `Ready for Review` to `Done` or closing its issue.

When working on an approved roadmap issue:

1. Before beginning, read the issue, its Project fields and dependencies, and the latest owner comments. Inspect the actual branch and working tree.
2. When implementation actually begins, move the item from `Planned` to `In Progress`.
3. Implement only the approved scope. Do not silently expand it; report separate defects and follow-up work separately.
4. Run the focused and broader validation required by this file and the issue.
5. When implementation and required validation are complete, post a concise completion report to the issue and move it from `In Progress` to `Ready for Review`.

Agents may update GitHub Issue and Project workflow state under these standing lifecycle rules. This permission is distinct from repository publication permission. Agents may edit the local working tree when authorized, but must not commit, push, merge branches or pull requests, create release tags, or publish releases. The owner performs repository commits and pushes after review unless a future task explicitly overrides this policy.

Agents must not allocate DLMS IDs independently. Do not infer a new ID by incrementing the highest existing ID, and do not recycle historical IDs. Preserve suffix IDs such as `DLMS-145A` only when the owner explicitly assigns them. When new work is discovered, report a proposed follow-up rather than expanding the active issue, and do not automatically create an official roadmap issue for every observation.

Project automation is intended to set newly added items to `Backlog`; a pull request linked to an issue may move the item to `In Progress`. Issue closure or pull-request merge must not automatically imply `Done`. Human acceptance remains the `Done` gate.

If GitHub or Project access is unavailable, do not invent the current roadmap status or overwrite it using stale assumptions. Report the limitation and continue only when the repository-local scope is independently clear.

## Safety and Data Preservation

DLMS stores user-created educational content and learning history. Treat user data as important.

When modifying persistence, import/export, backup/restore, quiz storage, study-pack storage, analytics, history, learning intelligence, or settings:

* Preserve existing saved data formats whenever possible.
* Do not introduce destructive migrations without explicit approval.
* Handle older or incomplete records defensively.
* Prefer additive schema evolution and safe defaults.
* Never silently delete user data because a record is malformed.
* Validate imported/untrusted data before trusting it.

## Parsing and Import Behavior

DLMS supports Smart PDF and other educational-content import workflows.

When changing parsers:

* Do not optimize only for one sample document.
* Preserve existing supported formats.
* Add structural validation where ambiguity exists.
* Favor tolerant recovery over hard failure when content can safely be presented for manual Review & Repair.
* Clearly distinguish low-confidence/recovered content from confidently parsed content.
* Do not invent missing answers, explanations, terms, definitions, citations, or source information.
* Add regression tests for newly supported formats and important previously supported formats.

## UI and Accessibility

When modifying UI:

* Maintain both light-theme and dark-theme readability.
* Preserve usable contrast for primary text, secondary text, muted/helper text, status indicators, warnings, controls, cards, tables, and form fields.
* Avoid cramped layouts and text touching card or viewport edges.
* Reuse existing design-system patterns and CSS variables where possible.
* Do not solve a global design problem with numerous isolated hard-coded colors unless necessary.
* Preserve keyboard accessibility and semantic controls.
* Ensure important actions and validation states remain understandable without relying only on color.
* Consider responsive layouts and smaller screens.

## Forms and Validation

Validation must be enforced at the appropriate server-side boundary even when client-side validation also exists.

When changing forms:

* Preserve entered data after validation errors where practical.
* Provide understandable validation messages.
* Do not allow malformed client requests to bypass required server-side validation.
* Keep recovery/manual-edit workflows usable when automatic inference is uncertain.

## Learning and Assessment Integrity

For quizzes, Study Mode, Exam Mode, matching activities, analytics, and Learning Intelligence:

* Preserve the distinction between correct answers, distractors, explanations, tags, concepts, and user responses.
* Avoid altering scoring semantics unintentionally.
* Ensure changes do not silently corrupt historical analytics.
* Test multi-answer questions and other non-default question structures when the affected code supports them.
* Preserve deterministic behavior where reproducibility matters.

## Testing

After editing:

1. Run the most relevant targeted tests first.
2. Add or update regression tests for bugs and new behavior when practical.
3. Run the broader/full test suite when feasible before declaring the task complete.
4. Investigate failures rather than assuming they are unrelated.

Do not weaken, delete, or bypass a legitimate test merely to make the suite pass.

If an existing test is incorrect because requirements changed, explain why before updating it.

For substantive UI/browser changes, focused tests are the first check, not the
completion gate. Before reporting the change complete or ready to push, run both
full gates against the final working tree using the project test environment:

```sh
python -m pytest -q -p no:cacheprovider -m "not browser"
export DLMS_RUN_BROWSER_TESTS=1 PYTHONDONTWRITEBYTECODE=1
python -m pytest -q -p no:cacheprovider -m browser tests/browser/test_critical_workflows.py
```

Both must pass; skipped/disabled browser coverage does not count as a passing
Firefox gate. If either gate cannot run, report the limitation and leave validation
incomplete. This validation rule does not authorize committing or pushing.

### Browser / Screenshot Test Cleanup

When using Firefox, Chromium, Chrome, or another browser in headless mode for runtime validation, screenshots, or visual inspection:

* Do not leave browser processes or background terminals running after the validation step completes.
* Explicitly terminate any browser process started for the test, whether the test succeeds, fails, or times out.
* After browser-based validation, check for lingering background processes when practical and clean up only the processes created by the validation task.
* Do not broadly kill unrelated browser sessions belonging to the user.
* Prefer commands or scripts with bounded timeouts so failed screenshot or browser checks cannot remain running indefinitely.

## Completion Standard

Do not report a task as complete merely because code was edited.

A completed implementation should normally include:

* Requested behavior implemented.
* Relevant regression coverage added or updated.
* Targeted tests passing.
* Broader tests passing when feasible.
* Diff reviewed for accidental scope expansion.
* No known requested requirement left unfinished.

If anything remains uncertain or untested, state that clearly.

## Final Report

At the end of each coding task, provide a concise summary containing:

* What changed.
* Files changed.
* Tests run and their results.
* Any important implementation decisions.
* Anything intentionally left unchanged.
* Any remaining risks, limitations, or recommended manual testing.

If you found unrelated issues, list them separately rather than incorporating them into the completed scope.

## Repository Hygiene

* Do not modify generated build artifacts unless required.
* Do not add temporary debug output, test files, logs, caches, or local environment files to the repository.
* Do not expose credentials, tokens, private keys, account information, or local secrets.
* Respect `.gitignore`.
* Review `git diff` before concluding work.
* Check `git status` so existing user modifications are not mistaken for Codex changes.

## Development Approach

Prefer clear, maintainable, conventional code over clever solutions.

When multiple approaches are viable:

1. Prefer the smallest change that correctly solves the problem.
2. Prefer existing DLMS architecture and conventions.
3. Prefer behavior that can be tested.
4. Prefer defensive handling of malformed or legacy data.
5. Explain significant tradeoffs when they affect future maintenance.

## User Collaboration

The repository owner is actively learning and reviewing Codex-assisted development.

Therefore:

* Explain meaningful changes in plain language.
* Identify exactly which files were modified.
* Do not imply that a test proves more than it actually proves.
* Call out assumptions.
* Ask for approval before performing destructive or unusually broad changes when approval is available.
* When given numbered findings, preserve those finding numbers in the completion report so implementation can be checked against the request.
