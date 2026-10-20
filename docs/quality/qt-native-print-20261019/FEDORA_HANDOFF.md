# Fedora/Omarchy handoff — standard Avery printer and PDF dialog

Read [sanitized Mac acceptance](MAC_ACCEPTANCE.md) and
[exact committed artifact binding](COMMIT_ARTIFACT_ACCEPTANCE.md).

## Exact source and shared correction

- Public base: `2107e5cffc787705dfbbb495995655ebd504dedd`.
- Reviewed source commit: `acf00838973037f25721f9a13961e76e1916f947` (its sole parent is the base).
- Complete nine-file overlay SHA-256: `449182ad6507af54989a70ea22ba616513e8b74f52c73f293ee0b3b1835ae449`.
- Shared-only patch SHA-256: `9699b58ba67541ea016362a425766d12d12661b9c8be544e2d8f874b98373afa`.
- Retained Mac DMG SHA-256: `d33144a6a5946b63086364ca324a228a02b850bd6808bb1ef59faa4c413a4fe4`.

Fetch the dedicated branch and verify the source commit. Use an isolated clean
checkout/worktree at the exact base, preserving other work. The exact shared
subset can be derived from the committed source without copying private files:

```sh
git fetch origin feature/qt-standard-print-dialog-20261019
git diff --binary 2107e5cffc787705dfbbb495995655ebd504dedd acf00838973037f25721f9a13961e76e1916f947 -- desktop/macos_printing.py desktop/qt_printing.py desktop/server_browser.py desktop/shell.py tests/outputs/test_qt_printing.py tests/outputs/gui_qt_printing.py docs/quality/qt-native-print-20261019/HANDOFF.md > /tmp/dlms-shared-standard-print.patch
sha256sum /tmp/dlms-shared-standard-print.patch
```

The digest must equal the shared-only value above. In the isolated base checkout:

```sh
git apply --check /tmp/dlms-shared-standard-print.patch
git apply /tmp/dlms-shared-standard-print.patch
```

This is a seven-file subset of the exact reviewed overlay, excluding Mac packaging
metadata and Mac release text. It includes the conditional Mac adapter because
cross-platform source tests import it; Linux does not run AppKit. Reuse this
implementation, not a competing fix. If integrating onto a different source or
encountering conflicts, compare the actual changed paths and stop before changing
runtime behavior. No merge, release build or installation is authorized here.

## Intended workflow and safeguards

Linux retains **QPrintDialog → accepted QPrinter → QWebEngineView.print** for
physical printers **and the dialog's ordinary PDF option**. Do not block PDF or
add a separate Save Avery PDF action. Qt owns destination/writability and ordinary
overwrite confirmation (No default in the pinned Unix implementation); this is
the revised output contract for printing, not the custom no-replace export
publisher. Other export/file-selection protections are unchanged. Mac instead
uses immutable NSData/PDFKit and one standard NSPrintOperation. Windows uses
WebView2; do not prescribe unrelated Qt tests or port its renderer code.

The main-frame Print Cards grant remains deliberate, one-use and bound to exact
path/origin/current page/mode, including existing Server markup without an ID or
status node. Scripted/window.print/frame, duplicate/stale context, loading/outage
stay refused. Native ownership locks navigation and retains objects until actual
completion; late callbacks cannot reenable unavailable Server pages. Linux
rechecks selected .avery-sheet card contents plus static CSS after dialog
acceptance. This is a static-layout mutation check, **not immutable sealing**.
No new renderer, pagination or copies implementation is introduced. Failed or
uncertain native completion shows feedback without promising no output changed.

## Focused Linux qualification only

Reuse unrelated source/recovery/focus/isolation evidence. Do not repeat the broad
audit, full Firefox walkthrough or recovery matrix.

1. In the existing pinned environment, run the changed printing/output contracts:
   `python -m pytest -q -p no:cacheprovider tests/outputs/test_qt_printing.py tests/outputs/test_output_boundaries.py`.
   tests/outputs/gui_qt_printing.py can check synthetic content/refusal/Return/
   separation, but its print responses are explicitly simulated. That is not
   native acceptance; Qt printer PDFs may rasterize, so its extracted-text-only
   assertions may need visual/rendered/OCR evidence on Linux rather than treating
   missing PDF text extraction alone as a printing defect.
2. Real native Local and task-owned matching synthetic Server: Print Cards opens
   the normal printer/settings dialog; select an available printer/settings and
   Cancel. Do not automatically submit a job. Use its ordinary PDF destination,
   save synthetic selected cards, and verify ALPHA/CHARLIE questions/answers only,
   BRAVO absent, two US Letter front/back pages. Distinguish dialog opening,
   accepted/spooled job and verified physical paper.
3. Native cancel and disposable existing target decline/explicit overwrite;
   Return exact selected IDs, deck name and short-edge setting. Keep all personal
   destinations untouched. Existing old Server button markup must print without
   a production update; the already accepted shared template update is still
   required for nondefault short-edge Return on older templates. Never make the
   POST-only Avery route accept GET as a workaround.
4. Retain source guards for wrong origin, script/frame, duplicate/stale action,
   loading/outage and changed selected-card DOM with unchanged CSS. Use existing
   harnesses where possible; stop inaccessible native controls after one bounded
   attempt and report the exact gap, not an inferred app defect. No new native
   automation framework or unrelated refactor.

Mac source validation retained 87 tests/59 subtests; owner real native PDF saves
in Local/Server, Local cancellation/overwrite, and agent content/Return checks
passed. New Mac packaged Local standard-dialog/PDF-option/Cancel smoke and normal
Quit passed once; its frozen code/source/notices correspondence is verified.
No physical paper output, alignment/duplex or Linux native/package pass is inferred.
Source simulations and portable CI must remain separate from native packaged
acceptance. Preserve pins; request separate release-build authorization only
when focused Linux integration/qualification is complete.
