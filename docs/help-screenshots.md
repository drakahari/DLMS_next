# Refreshing instructional Help and manual screenshots

## Dashboard quiz-sequence refresh

The quiz-sequence dashboard image uses baseline
`8dcae7321ce563ab527d35455f03fb8087d1a2d0` plus this reviewed change. It shows
an unfinished regular CISM review and two distinct generated Exam Plan quizzes
with equal titles, saved positions and times. All data is disposable. The
sequence and latest Exam summary share the existing Recent quiz activity
visibility choice; no new setting or stored ordering is introduced.

```sh
sequence_capture_dir="$HOME/.cache/dlms-sequence-help"
mkdir -p "$sequence_capture_dir"
DLMS_RUN_BROWSER_TESTS=1 PYTHONDONTWRITEBYTECODE=1 \
DLMS_SEQUENCE_CAPTURE_DIR="$sequence_capture_dir" \
python -m pytest -q -p no:cacheprovider -m browser \
tests/browser/test_critical_workflows.py \
-k dashboard_generated_resume_identity_and_sequence
```

Inspect the full desktop/narrow Light, Dark and Ethereal images and the
finished-review `sequence-ready` captures. Copy only the reviewed Light
`dashboard.webp` crop into `static/help_assets/` and update its dimensions in
Getting Started Help. Optional before/after comparisons replay byte-verified
baseline display scripts with the same disposable records and unchanged
dashboard template; they are labeled baseline replay, not production captures.

These five focused images show actual DLMS controls. They use the existing Help
figure, caption and keyboard-accessible image viewer conventions. The written
steps remain complete without images. The former Appearance and Navigation
screenshots were removed from the guide because they showed the five-choice
theme selector and retired separate Navigation page; current replacements now
illustrate the implemented controls.

## Capture source

Initially captured from `develop/3.3.0` at
`d09bf7ce743088e3470f9da6282ec7e5f3409a9e`, with the Light theme. The capture test
uses the normal isolated browser fixture: disposable data root, synthetic quiz
records, loopback test server and clean Firefox profile. It never uses the
running application, owner data or a desktop/browser theme preference.

IT is saved as dashboard-only and Law as sidebar-only to demonstrate independent
choices. These are sample choices, not changed application defaults.

## Refresh procedure

Run from the repository root using the activated project test environment and Firefox.
Create the disk-backed output directory under home first:

```sh
mkdir -p "$HOME/.cache/dlms-help-refresh"
DLMS_RUN_BROWSER_TESTS=1 PYTHONDONTWRITEBYTECODE=1 \
DLMS_HELP_CAPTURE_DIR="$HOME/.cache/dlms-help-refresh" \
python -m pytest -q -p no:cacheprovider \
tests/browser/test_critical_workflows.py -k help_screenshot_capture_controls
```

The fixture shuts down its own Firefox and test server in teardown. Keep any
external timeout/cleanup restricted to the exact owned run and its verified
children; never use broad browser name matching. Ordinary test runs do not
refresh assets. Capture output goes only to the explicitly supplied directory.

The manifest in `tests/browser/_help_screenshots.py` specifies the actual routes,
DOM crop selectors and viewports. The helper waits for loaded styles, fonts and
all 26 sidebar choices, captures the unmodified document, then crops its DOM
bounds with eight pixels of padding. It writes lossless WebP without rescaling,
compositing, inserting controls or changing application markup.

| Asset in `static/help_assets/` | Live controls | Viewport width |
| --- | --- | --- |
| `settings-appearance-theme.webp` | First Appearance section: Color theme | 390 |
| `settings-appearance-save.webp` | Appearance form actions | 390 |
| `sidebar-theme-selector.webp` | Lower sidebar, Settings/Help and Theme | 1440 |
| `settings-layout-study-areas.webp` | Study areas heading and IT/Law rows | 390 |
| `settings-layout-restore.webp` | Save and both scoped Restore buttons | 390 |

1. Inspect every generated crop. Confirm labels, checked states and complete
   control edges. Keep Save and Restore in separate crops from their distant
   selectors rather than inventing a combined interface.
2. Copy only these five reviewed files into `static/help_assets/`. Update the
   matching `width`/`height` attributes in `static/help-settings.html` to the
   actual image dimensions. Match the maximum widths in `static/help-docs.css`
   to the crops so desktop pages do not upscale them. Review alt text and
   captions against the live UI.
3. Update this capture-source note with the checkout HEAD used for the refresh.
   Preserve the independent sample choices unless the UI itself changes.
4. Run documentation tests and the focused Firefox checks:

```sh
PYTHONDONTWRITEBYTECODE=1 python -m pytest -q -p no:cacheprovider \
tests/test_help_documentation.py
DLMS_RUN_BROWSER_TESTS=1 PYTHONDONTWRITEBYTECODE=1 \
python -m pytest -q -p no:cacheprovider \
tests/browser/test_critical_workflows.py \
-k 'help_instruction_images or help_screenshot_capture or appearance_help or navigation_help'
```

5. Inspect Help at desktop and 360px widths in Light, Dark and White, including
   image enlargement with Enter, focus on Close, Escape and focus return. Check
   captions, body text and horizontal overflow. Optional existing screenshot
   outputs are `DLMS_APPEARANCE_HELP_REVIEW_DIR` and
   `DLMS_NAVIGATION_HELP_REVIEW_DIR`; set them to temporary directories.
   `DLMS_HELP_IMAGE_REVIEW_DIR` captures the focused images within the rendered
   Help page at both widths and all three themes.
6. Run both final gates required by `AGENTS.md` on the finished tree.

`DLMS.spec` includes the entire `static` tree for native packages, so these assets
need no separate resource entry. Regression coverage checks that specification,
HTTP image paths/types, dimensions, captions/alt text, rendered mobile sizing
and keyboard image-viewer operation. No package build is needed for a Help-only
refresh. Existing manual screenshot assets and application behavior are unchanged.


## Exam Plan screenshots

The Exam Plan setup, availability and dashboard images use the current isolated
Firefox form and a synthetic CISM plan. Refresh them with:

```sh
DLMS_RUN_BROWSER_TESTS=1 PYTHONDONTWRITEBYTECODE=1 \
DLMS_EXAM_PLAN_CAPTURE_DIR=/tmp/dlms-exam-plan-refresh \
python -m pytest -q -p no:cacheprovider \
tests/browser/test_critical_workflows.py -k "exam_plan_setup or exam_plan_no_work"
```

`test_exam_plan_setup_dashboard_practice_and_help` creates the plan through the
actual form; `capture_control` crops DOM bounds from unmodified screenshots.
The setup/availability crops use a 390px viewport. The dashboard crop also uses
390px. The same test checks light, dark and Ethereal at desktop/narrow widths
and can save whole-page detail screenshots for review. Only the five WebP
instructional crops belong in `static/help_assets`; full-page QA captures stay
outside the repository. After inspecting new crops, copy those WebP files and
update their width/height attributes in `static/help-learning-intelligence.html`.
The exact sample date advances with the capture date; Help's arithmetic example
is explicitly hypothetical. No personal plans or running app are used.

Usability refresh: baseline HEAD `b9763a05cdba94cae03a42b8215c3520f20ef4a7`
plus this working-tree revision. `exam-plan-selection.webp` crops the form's
`#planDashboardChoice`; `exam-plan-excluded.webp` crops `#planMaterial` with an
isolated excluded folder. The state test also captures complete ready, future,
allowance-used, paused, missing/excluded/unavailable and exam-date states. Keep
those QA PNGs outside the repository. Recheck the image dimensions and Help text
when refreshing; selecting a plan must not silently resume or override layout.


## Compact Study History and planner presentation

Baseline: `6327b738c049522ad15ba5ed4be9a85aa19619cc`. Refresh disposable captures with:

```sh
DLMS_RUN_BROWSER_TESTS=1 PYTHONDONTWRITEBYTECODE=1 \
DLMS_PRESENTATION_CAPTURE_DIR=/tmp/dlms-history-plan-captures \
DLMS_EXAM_PLAN_CAPTURE_DIR=/tmp/dlms-history-plan-captures \
python -m pytest -q -p no:cacheprovider -m browser \
tests/browser/test_critical_workflows.py \
-k "compact_study_history or plan_selected_breakdown or exam_plan_setup"
```

Inspect the actual screenshots, including responsive transitions settling. Copy
`study-history-row.webp`, `exam-plan-workload.webp` and the refreshed
`exam-plan-dashboard.webp` into `static/help_assets`; update their Help image
width/height attributes. The expanded-history and complete-page QA captures stay
outside Git. Fixtures create repeated titles, separate sessions, known UTC dates,
missing-save warnings, excluded/unavailable material and a real practice launch.
No personal history or running server is used. Retain captions, alt text and the
existing keyboard image enlargement.

## Marked questions and learner-oriented plans (pre-build batch)

Checkpoint: `aa53bf0eb185c62bd21c557a51c2aea2a288789f`. The current fixtures create
synthetic CISM questions and exercise real controls before taking screenshots.
Use a disposable test environment with the canonical requirements, then run:

```sh
DLMS_RUN_BROWSER_TESTS=1 PYTHONDONTWRITEBYTECODE=1 \
DLMS_PREBUILD_CAPTURE_DIR=/tmp/dlms-prebuild-captures \
DLMS_EXAM_PLAN_CAPTURE_DIR=/tmp/dlms-prebuild-captures \
DLMS_PRESENTATION_CAPTURE_DIR=/tmp/dlms-prebuild-captures \
python -m pytest -q -p no:cacheprovider -m browser \
tests/browser/test_critical_workflows.py \
-k "marked_questions_practice_export_and_compact_changes or exam_plan_setup or exam_plan_no_work or plan_selected_breakdown"
```

The marked-question capture selects two eligible questions and waits for the live
selection check so both action counts are visible. The mixed-type regression
`test_marked_selection_type_counts_and_preview_retry` also retains a separate
QA capture of image/hotspot exclusions when the capture directory is set.

Inspect all three themes at desktop/narrow widths. Copy only the reviewed Light
WebP crops: `marked-questions`, `exam-plan-changes`, `quiz_study_mode_correct`,
`quiz_study_mode_incorrect`, and the six existing `exam-plan-*` instructional
images. Update dimensions in Help, retain concise captions/alt text, and test
keyboard enlargement. Keep full-page QA PNGs and baseline images outside Git.
The old Study screenshots contained the obsolete Mark for Anki label; their
replacements show the current actual app, with no personal data or desktop chrome.
`DLMS.spec` already includes all static assets and templates. No production
package is built by this documentation/capture workflow.

### Marked-question HTTP checks and visible selection controls

The current marked-question screenshot shows **Select all on this page**,
**Deselect all (across pages)** and the exact action counts. Basic selection is
always visible; support details and action-specific helpers stay collapsed.
The existing three-theme capture test uses synthetic CISM material and refreshes
`marked-questions.webp`; copy the inspected crop and update its Help dimensions.

`test_marked_http_*` adds ordinary non-localhost HTTP coverage, actual APKG
downloads and request traces. Its `.test` name resolves to the isolated loopback
server only inside the disposable Firefox profile. This changes test DNS, not
secure-context rules. Captured packages and full-page QA screenshots belong
in the temporary evidence directory, not in Help or the release assets.
For an explicit LAN test only, set `DLMS_BROWSER_TEST_BIND_HOST=0.0.0.0` and
`DLMS_MARKS_TEST_ORIGIN_HOST` to the test machine's own LAN address. The harness
chooses an ephemeral port and disposable data; never point it at the owner's
running application. Restore the default loopback test configuration afterward
by omitting those environment variables.

## Calmer dashboard and separate histories

### Focus desk refresh

Source baseline: `92ac6997a3c75b00c75ddf46809bd9f16473b18d`, plus the
Focus desk wording and presentation polish. Capture actual application controls with
disposable data; the design-explorer illustrations are not Help screenshots.

```sh
focus_review_dir="$HOME/.cache/dlms-focus-desk-review"
mkdir -p "$focus_review_dir/runtime" "$focus_review_dir/captures"
TMPDIR="$focus_review_dir/runtime" DLMS_RUN_BROWSER_TESTS=1 PYTHONDONTWRITEBYTECODE=1 \
DLMS_PRESENTATION_CAPTURE_DIR="$focus_review_dir/captures" \
python -m pytest -q -p no:cacheprovider -m browser \
--basetemp="$focus_review_dir/runtime/pytest" \
tests/browser/test_critical_workflows.py \
-k 'calm_dashboard_identity or plan_selected_breakdown_risk'
```

This retains whole-dashboard desktop/narrow PNGs outside the repository and
produces `dashboard.webp`, `exam-plan-dashboard.webp` and
`exam-plan-workload.webp` crops from Light at 1440 and 390 pixels. Inspect them before copying only those three crops into
`static/help_assets/`; update their Help dimensions, captions and alt text.
Keep the existing image links for keyboard-accessible enlargement.
The test also checks 1024/320 pixels and 200% text resizing. Confirm that matching
current-quiz destinations share an action while retaining the saved-response time
and expandable historical context. A finished review should say **Last regular
quiz**, **Review finished** and **Open current quiz**; pending saves keep their
warning and recovery action visible. Check Settings → Layout & navigation from
the sidebar, including after hiding every optional card. The dashboard heading
no longer contains a Customize link. The History screenshot is unchanged.

Source baseline: `ce44530cc843f360b507d36055abb05ceaa99b88` plus the reviewed
calmer-dashboard working tree. Use disposable data; never capture personal quizzes.

```sh
DLMS_RUN_BROWSER_TESTS=1 PYTHONDONTWRITEBYTECODE=1 \
DLMS_PRESENTATION_CAPTURE_DIR=/tmp/dlms-calm-help \
python -m pytest -q -p no:cacheprovider -m browser \
tests/browser/test_critical_workflows.py \
-k 'calm_dashboard or plan_selected_breakdown_risk'
```

The first test saves an actual wrong Study response, creates an active sample
Exam Plan, and checks that the durable session and its exact browser checkpoint
share one compact continuation. It captures the entire dashboard in Light, Dark
and Ethereal at desktop and narrow widths, plus sparse states. The workload test
captures the visible shortfall warning. Capture files remain outside the repo.
Inspect the actual images before replacing `dashboard.webp`,
`exam-plan-dashboard.webp`, `exam-plan-workload.webp`, and `history.webp` in
`static/help_assets/`. Update image dimensions if needed. The History capture
shows the real Exam History page and its Study History link; it must not suggest
that legacy saved Study results prove a completed durable review.

Keep Help links around images for the existing keyboard-accessible enlargement.
No separate gallery or synthetic control labels are needed. The normal gates
validate links and UI behavior; they do not automatically overwrite Help assets.


## Current 3.3.0 documentation refresh

Application revision: `57d536f9bb20f91e8b275555e8bbfad6f0d6e83d`; source UI on
Fedora 44/Firefox 157.0. Documentation-only edits do not alter the controls.
The [manual screenshot manifest](user-manual/SCREENSHOT_MANIFEST.md#330-refresh-current-instructional-assets)
lists the current shared assets and their capture tests. Historical provenance
above remains historical rather than being rewritten as a fresh capture claim.

For a refresh, create a new directory under home, activate the project test
environment, and supply only the relevant optional capture variable:

```sh
dlms_doc_evidence_dir="$HOME/.cache/dlms-documentation-refresh"
mkdir -p "$dlms_doc_evidence_dir"
DLMS_RUN_BROWSER_TESTS=1 PYTHONDONTWRITEBYTECODE=1 \
DLMS_HELP_CAPTURE_DIR="$dlms_doc_evidence_dir" \
python -m pytest -q -p no:cacheprovider -m browser \
tests/browser/test_critical_workflows.py::test_help_screenshot_capture_controls \
tests/browser/test_critical_workflows.py::test_documentation_refresh_help_and_safety_navigation
```

Other families use `DLMS_SEQUENCE_CAPTURE_DIR`, `DLMS_PRESENTATION_CAPTURE_DIR`,
`DLMS_EXAM_PLAN_CAPTURE_DIR` or `DLMS_CERTIFICATION_CAPTURE_DIR` with the focused
tests listed in the manifest. Run sequentially to avoid overlapping heavy browsers.
Never point fixtures at a normal profile or the production server. Capture tests
create their own data and ports; they do not require running the owner’s app.

1. Inspect source images at desktop/narrow widths. Use current controls and labels;
   do not replace screenshots with mockups. No owner data, accounts, tokens or
   machine-specific paths belong in published images.
2. Review crops for complete useful controls. Reset & Remove is cropped before its
   data-path field; written confirmation/removal steps remain authoritative. Do not
   run a destructive action merely to photograph it.
3. Copy only reviewed assets. Read actual dimensions, update Help image attributes,
   captions and alt text, and verify Markdown links. Keep uncropped QA evidence local.
4. Check native image enlargement with Enter, Tab and Escape. Help lazy-loads
   images: scroll them into view before asserting that they loaded.
5. Run the documentation tests and focused Help browser checks. Record source HEAD,
   environment, fixture, dimensions, hashes and commands in a new report. Preserve
   failures and terminate only verified task-owned processes.

No canonical manual PDF build is configured. Optional task-local HTML reading
previews may help QA, but do not represent them as an official exported manual.
