# Windows candidate05 integration handoff

Stack this PR on PR #23 branch `fix/six-item-daily-use-20261019`, verified at
`717dd01a5efa9c6cbc8f95f463e70714ec198597`. Its shared runtime is
`c1268daaf8a1dab2919b912c117a1ac4f86ea6c6`. Do not substitute moving main or
duplicate the shared repair in this Windows diff. Integrate the shared dependency
deliberately before retargeting this Windows PR. No history rewrite is required.

The [acceptance record](WINDOWS_CANDIDATE05_ACCEPTANCE.md) binds the exact reviewed
patch to the normal candidate05 executable and distinguishes owner observations,
structural tests, reused evidence and remaining limits.

## Files in the reviewed repair

- `windows_webview2/Host.cs`: Avery-only child renderer, engine-owned original
  new-window POST handoff, per-controller security/lifetime ownership, embedded
  native layout, Server no-referrer compatibility and current-preview stacking.
  Real covers or owner/navigation invalidation retire the preview; asynchronous
  cover completion cannot overwrite a newer presentation decision.
- `desktop/webview2_browser.py`: forwarding of bounded, timestamped Avery state
  categories into the existing opt-in lifecycle collector. No content, URLs,
  credentials, page messages or privileged commands are introduced.
- `tests/webview2/host_popup_requests.py`: existing source probe extensions for
  original-request transport, embedded host, real no-referrer response and bounded
  lifetime checks. Diagnostic builds remain distinct from the normal package.
- `tests/webview2/AveryHeaderTests.cs` and `test_avery_headers.py`: compile and test
  the actual native Local/Server header admission helper.
- `tests/webview2/AveryStackTests.cs` and `test_avery_stack.py`: actual production
  native stacking helper with unshown controls, retirement/supersession, existing
  navigation/lease wiring and bounded opt-in event filtering.
- `tests/test_hotspot_preservation.py` and `tests/test_rebuild_current_identity.py`:
  Windows-compatible fixtures only: explicit UTF-8 and narrowly skipped symlink
  creation only when Windows returns missing-privilege WinError 1314. Ordinary
  path assertions remain enabled. No runtime recovery semantics changed here.

## Platform boundary

This diff changes the Windows WebView2 host, not the shared backend, schema,
dependencies or shared web UI. It does not change `desktop/shell.py`, the Linux/Qt popup host
or the Mac Qt focus correction. The two shared test-file fixture adaptations are
the only cross-platform file overlap requiring reconciliation.

Linux/macOS should retain their own engine-owned popup, deliberate-action,
origin/CSRF and selection-preserving return implementations. They should assess
applicable semantics rather than copy this WinForms/WebView2 child-controller
implementation or the Windows-only header/stacking helper.

## Submission and evidence boundaries

Only the reviewed nine-file repair and these two sanitized documents are submitted.
All source profiles, synthetic databases, raw traces, local review/operation files,
source/notices archives and executables remain local. The candidate was built from
the recorded uncommitted snapshot; the later submission commit adds documentation
without rebuilding or changing those reviewed runtime inputs.

No new local validation is needed for submission. Let triggered CI complete and
report a specific failure before modifying reviewed source or rerunning an unchanged
job. Hosted CI does not replace the accepted native owner walkthrough. This draft
PR authorizes neither merge nor installer/release/publication work.
