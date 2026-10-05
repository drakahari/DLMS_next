# Refreshing the Appearance and Layout Help screenshots

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

Run from the repository root using the project environment and Firefox:

```sh
DLMS_RUN_BROWSER_TESTS=1 PYTHONDONTWRITEBYTECODE=1 \
DLMS_HELP_CAPTURE_DIR=/tmp/dlms-help-refresh \
.venv/bin/python -m pytest -q -p no:cacheprovider \
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
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider \
tests/test_help_documentation.py
DLMS_RUN_BROWSER_TESTS=1 PYTHONDONTWRITEBYTECODE=1 \
.venv/bin/python -m pytest -q -p no:cacheprovider \
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
.venv/bin/python -m pytest -q -p no:cacheprovider \
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
