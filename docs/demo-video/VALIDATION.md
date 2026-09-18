# Preparation validation

Validated on develop/3.2.0 during the preparation pass, 2026-09-18.
This is not final release or final visual approval.

- `--list` and focused `--list --only 001,003,014`: pass without starting DLMS.
- Three-frame proof capture: pass, clean isolated Firefox, Purple & Gold,
  1920 × 1080 PNGs, device scale 1. Inspected all three images.
- Corrected complete **36-state `--check` run**: pass. This navigates, waits,
  selects controls and checks viewport dimensions; it writes **no PNGs**.
- The state run includes actual Study answer saves, Finish Review, verified
  lifecycle completion, released recovery ownership, Completed Library access,
  and an opening/closing Dashboard without unwanted Resume cards.
- Focused tests: **10 passed** across `tests/test_demo_video_capture.py` and
  `tests/test_manual_screenshot_capture.py`. They check frame contracts, timing,
  unique IDs, list isolation, output restrictions, original answer consistency,
  unowned-root rejection, docs coverage, proof dimensions, manual defaults and
  process cleanup on server startup failure.
- `git diff --check`: pass. New text files also checked for trailing whitespace;
  local Markdown link targets verified.
- No capture-created Firefox/server processes remained after validation.

During recipe validation, the source quiz's actual progress selector replaced a
manual-harness-specific selector. The Generated Practice Smart View was found
to retain normal folder grouping, so virtual-section frames use the unfiltered
Library instead. These were capture-recipe corrections, not product changes.

Proof findings: the Dashboard's two real recommendations are readable; the
intelligence overview fits all four concept rows; the Library detail shows
active/retained groups but clips the top of the scrolled sidebar. Reserve that
frame for teaching, with a separate overview as the visual introduction. All
proof content is original synthetic material and uses a neutral identity.

Limits: the other 33 states have functional checks, not screenshot inspection.
OCR extraction was not executed; Review & Repair is a documented staged
synthetic fixture. Bundle import, actual Anki downloads and external providers
were not exercised. Full application suites were not run for this tooling/docs
preparation. No final capture or final narration was produced.
