# DLMS browser regressions

This directory contains a deliberately small Firefox suite for workflows where
real JavaScript, DOM events, CSRF handling, and server persistence interact.
It is opt-in so the normal unit/integration suite stays fast:

```bash
DLMS_RUN_BROWSER_TESTS=1 .venv/bin/python -m pytest -q -m browser tests/browser
```

The suite uses Firefox's built-in WebDriver BiDi endpoint and the Python
standard library; Selenium, Playwright, geckodriver, network access, and external
services are not required. Each run creates a fresh DLMS data root, generated
quiz fixtures, and loopback server. Each workflow gets a fresh Firefox profile,
process, BiDi connection, and browsing context, so transport or browser state
cannot leak into the next workflow. Navigation uses BiDi's non-blocking
acknowledgement, then polls the replacement document to full readiness through
ordinary script commands instead of depending on Firefox's unstable navigation
completion response. Existing page-specific DOM, status, persistence, and
accessibility assertions remain the authority for success. The fixtures own
every process group, terminate them in `finally` cleanup on success or failure,
and remove their isolated browser-test workspaces.

Normal `pytest` runs collect these tests but skip them unless
`DLMS_RUN_BROWSER_TESTS=1` is set. This separation is intentional because a
real browser adds startup cost and may not be installed in every environment.

The focused cases cover:

- Quiz Library reorder controls through the browser, including the CSRF-protected
  persistence request and order after a reload.
- Study Mode answer feedback and learning-event persistence, followed by an Exam
  Mode submission and navigation to the persisted attempt in History.
- Quiz editing through the rendered form, including persistence after reload and
  regeneration of the playable quiz page.
- A visible Study Mode learning-event save failure followed by the user-facing
  Retry action and confirmed database persistence.
- Backup upload, validation and confirmation before mutation, followed by a
  successful restore of the expected quiz snapshot.

Lower-level tests remain the source of truth for malformed payload validation,
all supported question types, drag-and-drop edge cases, and detailed rendering.
