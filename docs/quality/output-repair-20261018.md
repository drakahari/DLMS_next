# Marked Anki and Avery output repair — review candidate

Status: uncommitted, awaiting Astra High review. Base: public main merge `5784e7bbe372ffe6cf6a241d934081815f7edd8c` (PR #17, exact approved hotspot head `17d9313617d4000627fb7b6c9cbfaa13adf13cf1`). Branch: `fix/marked-anki-avery-output-20261018`. No output-repair commit, push, release, installed replacement or published warning is included.

## Scope and applicability

F3's download refusal is **Qt Desktop-specific**, observed in Local and addressed for Local/Server. The shared browser application already produces usable initial/fallback APKG downloads. Its premature “exported” message was shared and is corrected to describe a request/prepared package without claiming publication. Normal Windows/Mac native adapters are separate qualification work.

F4's lost POST is **Qt Desktop-specific**. The exact base Local new-window method was replayed under the real source Qt stack: the original deliberate form action generated **GET /anki/printable →405**. With the request-preserving handoff it generated **POST →200**, retaining the chosen card, deck name and short-edge setting. Source inspection shows Server previously sent this same-origin popup through its generic URL-only external handoff/refusal path rather than into its own view; the old Server outcome was not separately GUI-reproduced. The new exception is restricted to the current configured-origin `/anki/custom` document and exact `/anki/printable` target without query/fragment. Real Firefox target=_blank POST/new-tab behavior passed independently. The endpoint remains POST-only.

Both F1/F2 shared-application repairs remain intact in merged history. Their preserved-runtime, stale marking and grading tests are included in the focused selection. Historical recovery/migrations remain out of scope.

## Implementation boundaries

- `desktop/marked_exports.py`: download-only APKG Blob eligibility requires the active page, verified Local/configured Server origin, exact `/marked-questions` document and expected filename/UUID URL. A top-document, isolated-world observer remembers a trusted Export to Anki click or explicit fallback click. Native host consumes that single URL-bound permission before offering Save As. A private transfer alone does not authorize publication. Programmatic source actions and iframe actions cannot mint the top-document permission. There is no native command channel, file-reading API or remote header rewrite.
- `desktop/shell.py`, `server_browser.py`: reuse existing private download staging and page/dataset checks; use Qt `QWebEngineNewWindowRequest.openIn()` for the original request instead of reducing it to a URL/GET. Same-profile/current-page, retirement and origin checks stay active. Local's previously allowed same-origin popup boundary is retained; Server's new exception is limited to Avery. No new popup window/profile ownership is introduced.
- `desktop/exports.py`: existing native Save As, no-replace destination publication and focus/cancel behavior are reused. Terminal outcome text is also presented on the current matching export page, guarded by its document/dataset and feedback ticket. Only fixed messages enter the page; native paths and private exception text are not disclosed to Server content. Old callbacks cannot replace newer feedback.
- `static/review-marks.js`: web-only feedback accurately describes preparation/request; a browser cannot confirm that a native Save As completed. Native saved/canceled/refused/unconfirmed states appear only after their corresponding outcome. Marks and action/recovery logic are unchanged.
- `templates/anki/printable.html`: Qt's request transfer replaces WebContents and resets its history. A narrow, CSRF-protected Return to Custom Deck form retains the submitted card tokens/deck name via the existing POST preview route, avoiding a stranded print page. It grants no additional route access and changes no card content or print geometry.

The observer's two-minute bound accommodates package generation; only one permission is consumed, it is bound to the same document and exact link, and unrelated trusted clicks/page changes retire it. This is permission for a native chooser, never an automatic destination write.

Qt API reference: [newWindowRequested/openIn](https://doc.qt.io/qt-6/qwebenginenewwindowrequest.html). Method/body preservation on the pinned engine is supported by the retained runtime trace, not inferred from a URL or screenshot.

## Focused evidence

| Layer | Result / qualification |
|---|---|
| Exact base Qt handler | Actual method trace: GET and405. Original audit also records marked Blob refusal before Save As. |
| Final source selection, nine files | **175 passed,15 subtests,4 skipped**, six existing cached_property deprecation warnings. Covers output origin/current-page boundaries, stale callbacks, native export publication and lifetime, ordinary attachment controls, mark content/identity, printable escaping/layout and merged hotspot preservation. Conditional skips are not platform passes. |
| Final real Firefox | **2 passed,380 deselected**. Initial/fallback APKG downloads have the same one-note content; real new-tab Avery POST retains card/deck/duplex values; Return restores the chosen card/deck. Existing mixed-type mark/eligibility control also passes. |
| Final source Qt, Local + synthetic real DLMS Server | Initial/fallback/repeated initial export; APKG note/choice content; cancellation; existing-file refusal with original hash unchanged; programmatic and trusted iframe actions refused without Save As; exact POST/body/layout; return form retains selection/deck; explicit return to Local. Native chooser answers are simulated in this source driver. |
| Final normal frozen Fedora candidate | Actual native TXT chooser/import → Marked Questions → native initial/fallback Save As; identical APKG bytes and correct original answer; actual Cancel; actual collision refusal/original hash unchanged; full DB dump unchanged by exports; rendered Avery card with submitted deck/short-edge setting; actual return preserves selection/deck; Dashboard shutdown/final alert and exit0. Diagnostic-assisted application-local input and owned accessibility, not physical input. |
| Provenance | Separate normal one-folder candidate, not an instrumented/released artifact. Pinned offline Ubuntu24.04 build image;184 embedded source modules and247 assets match final source; tests absent;458 ELF files and0 Ubuntu ABI import blockers. Documentation-only additions after build do not change embedded inputs. |
| Preservation | Original workflow-audit reports/evidence hashes pass. Original hotspot evidence and reviewed patch remain unchanged. Installed apps, profiles and public artifacts untouched. |

Final local executable SHA-256: `c5fcaa0a8b352399a51733978bb60f7aeff7894d5a3300f931a3232ae2491184`.

Embedded PYZ SHA-256: `2aec4590f10e0ddbc7742c1dfa409ea75ee2a62b1b42fce6c2fb4853fadc78e1`.

Uncommitted build-input tree SHA-256: `27f297df71e85a6424189f8ae51d49cb9e26b09f4c05373a4139fc8ac3588cd1`. Build identity names the merged commit as its base, not falsely as the entire source snapshot.

Normal-package evidence is Fedora44/COSMIC Wayland with loopback diagnostic connections and exact-process native accessibility. Diagnostic connections add Qt's remote-debugging origin allowance; this is not vanilla hostile-content/security or physical-keyboard acceptance. Normal frozen Server operation was not repeated: Server evidence is source Qt plus the actual browser server; no normal-package Server pass is inferred. Physical printing, printer duplex alignment, native Windows/Mac, native Ubuntu/Omarchy and full accessibility remain unverified.

## Retained corrections and prevention limits

Retain failed source-controller starts caused by the Unix socket path length and an inconsistent temporary-root override; the corrected source driver shortens only its test IPC name while preserving backend profile isolation. A controller method-name typo and wrong synthetic-card selection were corrected. The first normal launch refused a task-created data root lacking private permissions; the fixture was corrected, without weakening the check. Native controllers initially assumed an upload opened the quiz rather than Library, guessed absent Anki links and used rectangles from collapsed content. They then followed the actual Library/Anki/group controls without re-importing. `openIn()` also closes the old diagnostic connection; controllers reconnect after the actual POST rather than replaying it. One final Library click preceded full document/font readiness; a subsequent explicit click after readiness succeeded. That timing's precise compositor cause is not established. These are retained limitations/corrections, not erased failures or native acceptance of instantaneous early clicks.

The initial local candidate exposed the reset-history consequence; the final candidate was rebuilt only because the new return form and terminal-transfer feedback changed runtime inputs. A private build script's overbroad cached-OCR path substitution failed before build and was corrected. No application assertions were weakened, dependencies changed, broad local suite repeated, or released package rebuilt.

This batch prevents the confirmed F3/F4 paths going forward; it does not repair historical content or implement migrations. Whole-quiz/custom-deck APKG successes are reused where unchanged. Documentation gaps and remaining workflow-audit variations remain open. The hotspot temporary warning remains a draft. Public/release/installed changes require separate approval.

## Reproduce focused checks

```sh
python -m pytest -q -p no:cacheprovider \
  tests/outputs/test_output_boundaries.py tests/daily_use/test_download_states.py \
  tests/linux_windows/test_contracts.py tests/linux_windows/test_action_lifetime.py \
  tests/server_mode/test_boundary.py tests/server_mode/test_attachment_surface.py \
  tests/test_review_marks.py tests/test_law_anki_template_characterization.py \
  tests/test_hotspot_preservation.py

DLMS_RUN_BROWSER_TESTS=1 python -m pytest -q -p no:cacheprovider \
  tests/browser/test_critical_workflows.py \
  -k 'marked_export_fallback_and_original_avery_post or marked_selection_type_counts_and_preview_retry'

QT_QPA_PLATFORM=offscreen python -m tests.outputs.gui_output_paths \
  --profile outputcheck01 --output /tmp/dlms-output-check-new-directory
```

The last source-Qt command requires a new output directory, task-owned loopback sockets, the supported Qt environment and disposable data only. Offscreen captures establish no final on-screen appearance. For an exact-base method trace, add `--baseline-print` on a fresh profile/output directory; it loads only the pinned base method from local Git history. No original checkout or production server is used.
