# DLMS 3.2.1 final Firefox cleanup

Date: September 23, 2026. Branch: `develop/3.2.1`.
Starting candidate: `0cd5fbe`, initially clean. No commit or push.

## Accessibility correction

[Hosted run 35886175915](https://github.com/drakahari/DLMS_next/actions/runs/35886175915)
reported 4.296315961190739:1 for Light-theme disabled Start Over, below the
unchanged 4.5:1 requirement. The production change is one color declaration in
`static/style.css`: the disabled recovery action now mixes 75% theme muted text
with 25% heading text instead of 95% muted / 5% heading. It uses existing tokens
and does not alter normal, hover, active or focus selectors. Disabled surface,
border, no shadow, opacity 1 and `not-allowed` cursor remain distinct.

Measured disabled contrast in Firefox 156.0 on Fedora 44 was identical in the
focused private-Xvfb and default-headless checks:

| Theme | Contrast |
| --- | ---: |
| Light | 6.786523:1 |
| Dark | 11.227732:1 |
| Purple-Gold | 10.554143:1 |
| Maroon-Gold | 10.302020:1 |

The browser test retains its >=4.5 assertion and additionally requires >=4.8
for Light disabled Start Over. Measurements are runtime samples, not a claim
to enumerate every animation frame; the changed text mix provides headroom.

## Physical-desktop exposure: cause and correction

The owner's session exports `DISPLAY=:0`, `WAYLAND_DISPLAY=wayland-1`,
`XDG_SESSION_TYPE=wayland`, `GDK_BACKEND=wayland,x11`, and
`MOZ_ENABLE_WAYLAND=1`. Earlier agent commands used `xvfb-run` but retained the
Wayland controls. The harness only checked that DISPLAY existed. Consequently,
headful Firefox could select the physical Wayland compositor instead of the Xvfb
display. This explains the owner's observed windows; changing DISPLAY was not
sufficient isolation. Earlier audit claims of guaranteed private-Xvfb rendering
were too strong: those runs did not verify or exclude the Wayland backend.
Their functional test results remain recorded, but must not be treated as proof
of physical-desktop isolation. Historical records were not rewritten.

Audit of launch paths:

- All five critical-workflow launch sites call `_firefox_command` with the same
  dedicated environment subsequently passed to Popen: primary fixture, profile
  reopen, presence/server restart, runtime-mode server, and multi-client flow.
- The startup diagnostic in `/tmp/dlms-xvfb-Cjqi1Q/probe.py` uses that same helper
  and environment. It is protected by the corrected helper without modification.
- The OCR timing/click probes wrap shared harness methods; they do not launch an
  independent browser. Their Xvfb shell invocations had the same inherited
  Wayland exposure. This was agent/harness environment handling, not DLMS's
  production browser-launch behavior.
- `tools/capture_user_manual_screenshots.py::_start_firefox` always supplies
  `--headless` and `--no-remote`. Demo/documentation captures delegate to it.
  None of these helpers defaults to visible Firefox. No screenshots were rebuilt.

Final policy, without adding a browser mode:

1. Missing mode means **headless**. DISPLAY alone never changes mode. The
   dedicated Firefox child environment drops DISPLAY, XAUTHORITY,
   WAYLAND_DISPLAY and WAYLAND_SOCKET; `--headless` remains mandatory.
2. Explicit `xvfb` requires a local DISPLAY and authentication file. The harness
   verifies the display's X lock PID, live `/proc` process identity (`Xvfb`), and
   matching display argument. Physical Xorg/Xwayland, missing/stale servers and
   mismatched displays are rejected before Firefox launches. Local use must
   start its own `xvfb-run` as documented in the browser README.
3. Both modes force `GDK_BACKEND=x11` and `MOZ_ENABLE_WAYLAND=0` and remove Wayland
   display/socket access. Xvfb mode retains only its validated virtual X display;
   it cannot silently fall back to the physical Wayland compositor.
4. GitHub keeps explicit `DLMS_FIREFOX_MODE=xvfb` and private `xvfb-run`, with
   the X11 backend settings also explicit in the workflow. Its existing wrapper
   owns X server/authentication cleanup. No startup retries or timeout increases.
5. There is no visible/debug mode. Unknown modes fail, rather than opening a
   desktop window. The helper sanitizes the existing dedicated child dictionary
   so direct probe callers cannot omit a separate environment-preparation step;
   it does not modify the owner's `os.environ` or desktop session.

## Final validation

- Focused private-Xvfb accessibility plus OCR: **2 passed in 10.34s**.
- Final focused default-headless accessibility/OCR, harness/BiDi/configuration
  and recovery-runtime tests: **51 passed, 25 subtests passed in 9.87s**.
- Regression coverage checks default headless arguments, inherited desktop
  removal, Wayland exclusion, private-Xvfb identity/display matching, rejection
  of physical/stale displays, all five guarded launch sites, screenshot-helper
  headless default and explicit workflow Xvfb/X11 configuration.
- Workflow validation: **actionlint 1.7.12 passed**, YAML/configuration tests
  passed, and every workflow run block passed `bash -n`.
- Exactly one final full local validation cycle was run after the focused checks:
  - Default local mode (DLMS_FIREFOX_MODE unset), DLMS_RUN_BROWSER_TESTS=1,
    PYTHONDONTWRITEBYTECODE=1, project `.venv`:
    `python -m pytest -q -p no:cacheprovider -m browser tests/browser/test_critical_workflows.py`:
    **97 passed in 383.81s**; no skipped browser coverage.
  - `python -m pytest -q -p no:cacheprovider -m "not browser"`:
    **1,815 passed, 105 deselected, 2,461 subtests passed in 24.65s**.
  - `git diff --check`: **passed**, with an additional explicit whitespace check
    of this new untracked audit against `/dev/null`.
- No repeated full suites were run to accumulate passes. Final process checks
  found no task-owned Firefox, browser-test server or Xvfb left running. The
  unrelated owner Firefox process was preserved.
- No further application-level release blocker was identified by this task.
  The only production change is the disabled foreground declaration; the rest
  is narrowly scoped test isolation, regression coverage, workflow configuration
  and documentation. Final branch/HEAD remain `develop/3.2.1` / `0cd5fbe`.

APP_VERSION remains 3.2.1. No persistence, submission, scoring, OCR or other
application behavior changed; only the disabled CSS foreground is a production
change. No release artifacts were built or published. Hosted confirmation of
the owner-pushed candidate remains external acceptance, not another proposed
round of general browser experimentation.
