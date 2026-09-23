# DLMS 3.2.1 hosted Firefox virtual-display investigation

Date: September 23, 2026. Branch: `develop/3.2.1`.
Starting candidate: `c7c93927ca8d1210c890f33a9cfcfee733552bad`, initially clean.
This is a follow-up to the earlier Firefox gate investigation, not a replacement
for its historical evidence. No application code or APP_VERSION changes.

## Hosted evidence

[Run 35871335024](https://github.com/drakahari/DLMS_next/actions/runs/35871335024)
finished with **95 passed, one setup error in 707.89 seconds**. The affected
`test_storage_health_themes_and_narrow_layout` never reached its assertions.
Firefox exposed its BiDi listener and accepted a WebSocket upgrade, but startup
did not complete within the existing 30-second deadline. The log includes
`RenderCompositorSWGL failed mapping default framebuffer, no dt` at 29.4939s.

Verified hosted environment:

- Ubuntu 24.04.5 LTS, `ubuntu-24.04` image **20260920.314.1**;
  runner version **2.337.0**, Azure eastus2.
- `firefox --version` reported **Mozilla Firefox 156.0**.
- The [exact image manifest](https://github.com/actions/runner-images/blob/ubuntu24/20260920.314/images/ubuntu/Ubuntu2404-Readme.md)
  lists Firefox 156.0 and `xvfb` **2:21.1.12-1ubuntu1.6**.
- The [image installation script](https://github.com/actions/runner-images/blob/ubuntu24/20260920.314/images/ubuntu/scripts/build/install-firefox.sh)
  installs Firefox through `ppa:mozillateam/ppa`, not Snap or a DLMS download.
- The old workflow did not record `DISPLAY`, executable paths, xauth availability,
  or inherited graphics variables. Their exact runtime values cannot be recovered
  from that log. The image includes xvfb; the new workflow checks all required
  commands rather than assuming their availability.
- All five critical-workflow launch sites explicitly passed `--headless`,
  `--no-remote`, an isolated `--profile`, `--remote-debugging-port`, and
  `about:blank`. No graphics preferences or graphics environment overrides were
  set by this harness. Crash-reporting/auto-safe-mode controls remain unchanged.

The evidence identifies a Firefox initialization failure, not a failed DLMS
operation. A compositor warning alone does **not** prove the cause of the hung
session: the same warning occurs in successful local headless launches.

## Controlled local comparison

Local host: Fedora 44 Workstation, RPM `firefox-156.0-1.fc44.x86_64`.
Existing desktop `DISPLAY=:0` was not used for headful testing. No existing
MOZ_HEADLESS, MOZ_WEBRENDER or LIBGL_ALWAYS_SOFTWARE override was present.
Xvfb was absent; Fedora's `xorg-x11-server-Xvfb-21.1.24-1.fc44.x86_64` RPM
was downloaded and extracted under `/tmp`, without a system installation.
Installed xauth was `1.1.5-1.fc44`. Private Xvfb screens were 1920x1080x24
with TCP listening disabled.

A temporary probe used the real `_connect_firefox`, `FirefoxBidi.navigate`,
`evaluate`, and `_terminate_process_tree` helpers. Every cycle created an
isolated profile/port, connected the listener, initialized a session, navigated
to a synthetic data document, asserted its title, closed the BiDi connection,
terminated the process group and removed the profile. No failed cycle was retried.
Times below start at Firefox process launch, not at the first socket connection.

| Mode | Successful cycles | Session ready | First navigation/evaluation ready | SWGL warning |
| --- | ---: | --- | --- | ---: |
| Original native headless | 20/20 | 0.903–1.013s | 0.949–1.064s | 20/20 |
| Headful on private Xvfb | 20/20 | 1.321–1.460s | 1.369–1.501s | 0/20 |
| Xvfb through final mode-selection helper | 20/20 | 1.336–1.426s | 1.387–1.476s | 0/20 |

Every cycle exposed a listener and cleaned up its Firefox process. Neither mode
reproduced the hosted hang. Xvfb demonstrably eliminated this warning locally,
but these samples do not establish a statistically better hang rate or prove
the exact Ubuntu failure's graphics causality. The display-path change is a
bounded mitigation that still needs hosted confirmation, not a timeout workaround.

## Implementation and boundaries

- The Firefox workflow explicitly sets `DLMS_FIREFOX_MODE=xvfb` and wraps the
  unchanged full gate in `xvfb-run --auto-servernum` with a private 24-bit screen.
  The wrapper owns X-server/auth-file cleanup and propagates the test exit code.
- `_firefox_command` is shared by all five critical-workflow Firefox launches,
  including restart and multi-client tests. Its default remains native headless,
  even if a developer already has DISPLAY. Xvfb mode requires DISPLAY and rejects
  a conflicting nonempty MOZ_HEADLESS or an unknown mode before launch.
- Workflow diagnostics record OS, executable paths, package versions, selected
  graphics variables, and the actual display/mode inside the wrapper. Only missing
  Xvfb/xauth tooling triggers a minimal apt install. Firefox is not pinned,
  downgraded or reinstalled.
- Startup failures retain the Firefox log tail and now also identify the stage,
  launch command and unchanged 30-second budget. Previous publication-readiness
  diagnostics and all application assertions remain intact.
- No new sleeps, startup retries, graphics preferences, MOZ_WEBRENDER override,
  skipped coverage, or release/application behavior changes were introduced.

### Headful comparison exposed a separate pointer-readiness race

The first full Xvfb run had **95 passed, one failed in 357.93s**, with no startup
errors. `test_generated_practice_study_completion_retry_library_and_retake`
failed its existing immediate assertion after clicking a Library folder toggle.
Two instrumented focused runs reproduced the miss. Captured pointerdown,
pointerup and click events all targeted `#dashboardSidebar` at (53, 500), not
the intended button. `static/style.css` defines the narrow-screen sidebar's
200 ms transform transition. After the test's rapid viewport changes, this
transition still temporarily covered the button. In the second probe, hit
testing found the button unobstructed 103.7 ms later, but `aria-expanded` was
still false: waiting longer after the missed click would not fix it.

`FirefoxBidi.click` now waits, after scrolling, for its target to contain the
topmost hit-tested element at the visible center. It uses the existing six-second
condition budget and then sends the same real element-origin pointer action.
It neither sends JavaScript clicks nor retries a click. Persistent occlusion
still fails before input is sent. The original theme, responsive-layout,
keyboard-focus and toggle-state assertions are unchanged. This is harness
actionability synchronization required by the headful comparison, not an
application change or a disabled animation.

## Validation

- Focused harness/BiDi/workflow tests: **28 passed, 21 subtests passed**.
  Coverage includes local headless selection despite DISPLAY, Xvfb argument
  selection, invalid/conflicting environment rejection, startup diagnostics,
  failed-startup process/profile cleanup, pointer actionability and continued
  failure without input when a target remains covered.
- After the pointer-readiness fix, the previously failing workflow passed five
  independent uninstrumented Xvfb runs: **4.32, 4.27, 4.25, 4.27, 4.30 seconds**.
- Two consecutive final full Firefox gates, with no edits or retries between
  runs: **96 passed in 358.27s**, then **96 passed in 359.38s**. Both used the
  project `.venv`, `DLMS_RUN_BROWSER_TESTS=1`, `DLMS_FIREFOX_MODE=xvfb`,
  `PYTHONDONTWRITEBYTECODE=1`, and the private Xvfb screen described above:
  `python -m pytest -q -p no:cacheprovider -m browser tests/browser/test_critical_workflows.py`.
- Full non-browser gate:
  `python -m pytest -q -p no:cacheprovider -m "not browser"`:
  **1,808 passed, 104 deselected, 2,457 subtests passed in 24.90s**.
- Workflow validation: **actionlint 1.7.12 passed**; YAML/configuration regression
  tests and `bash -n` for every workflow run block passed. The official actionlint
  download was checksum-verified and kept outside the repository.
- Xvfb wrapper cleanup checks with child exit codes **0 and 7** preserved each
  exit status and removed the private display socket/authentication file.
  Post-gate process checks found no task-owned Firefox, test server or Xvfb
  process; the existing unrelated user Firefox session was left untouched.
- Final diff review confirms only workflow, test harness/tests, browser test
  guidance and this new evidence record changed. No application, APP_VERSION,
  screenshot, generated binary or release-artifact changes.
- `git diff --check`: **passed**; the new untracked audit was also checked
  explicitly against `/dev/null` for whitespace errors.

## Remaining hosted acceptance

The owner must commit/push the reviewed change and run the hosted Firefox gate
against that new candidate, preferably twice consecutively. Verify the logged
Xvfb mode/display, all 96 tests passing without setup errors, and no startup
graphics error preventing readiness. Local Fedora/Xvfb evidence cannot certify
the exact Ubuntu hosted environment. No commit, push or hosted dispatch was
performed during this investigation.
