# Standard Qt-host Avery printing — focused Fedora/Mac handoff

Base: `2107e5cffc787705dfbbb495995655ebd504dedd` plus the exact reviewed overlay
recorded in PACKAGING_SOURCE.json. The binary is not a clean unmodified build
of that base. Preserve previous candidates; no merge/publication/installation
is authorized by this task. The earlier private `c5f6da34…` candidate and its
physical-only/PDF-blocked design are superseded, not relabeled or modified.

Current status: source correction; no replacement package has been built.
Focused source guards and real rendered Local/synthetic Server selected-card
PDF contents, cancellation, simulated overwrite and Return checks pass. Those
dialog responses are simulated. A separate real Mac sheet selected a physical
printer, changed Copies and canceled; native PDF opened the system Save As sheet.
Automation could not uniquely identify its filename field after one existing
alternative, so actual native PDF save, overwrite and Server-sheet acceptance
remain pending. No physical Print was pressed or paper output accepted.
Keep these limits until separate native receipts establish narrower results.

## Accepted workflow and output authority

Print Cards must offer the standard physical-printer dialog **and its native
PDF option**, including system destination and overwrite confirmation. There is
no separate Save Avery PDF action and no PDF-menu refusal. The owner explicitly
accepts the standard OS/Qt overwrite-confirmation contract for this operation.
It replaces the earlier custom never-replace printing proposal. It does not
change source-file consent/integrity protections or Anki/backup/other exports.
There is no fundamental security requirement to block standard PDF saving:
only native UI receives a destination choice; a web page cannot command an
arbitrary native filename or automatically accept printing/overwrite dialogs.

## Mac implementation

Qt callback produces Letter/portrait/zero-native-margin selected pages privately.
PDFDocument.initWithData copies immutable bytes into PDFKit; subsequent private
file or DOM changes cannot change the native document. PDFKit creates one
NSPrintOperation with showsPrintPanel=True and public sheet completion delegates.
AppKit owns the complete printer/Preview/PDF/settings/save/overwrite workflow.
No manual NSPrintPanel/destination bridge, PDF-kind blacklist, shell command,
private Qt API or separate export action is used.

Initial settings are Letter portrait, 100%, one copy, one page per sheet and the
layout's selected duplex intent. Native user choices remain user choices.
Changing flip direction from the prepared layout can mispair Avery backs;
regenerate that layout for a different flip. Physical paper/duplex/alignment
must be recorded separately; native PDF output cannot establish paper alignment.

The consented window/document remain owned while the operation is pending:
mode/close guards, disabled view and navigation refusal keep context fixed;
objects/delegate/callback/private bytes live until actual native completion.
Only a deliberate native Print/Save decision produces output. False completion
can be cancel or failure (including cancellation after a spool attempt), so
feedback never promises 'no job sent' from that Boolean alone. Successful native
completion likewise does not prove physical output. There is no timeout that
frees a still-pending operation.
An exception after entering native printing also reports completion unconfirmed
and asks the user to check their destination/queue; it never claims no file changed.

## Shared Qt/Linux behavior

The canonical main-frame Print Cards button (including old Server no-ID markup)
retains trusted, one-use, unmodified pointer/keyboard activation, exact path and
active Local/configured Server origin checks. Scripted window.print, child
frames, duplicate/stale activation, loading/outage and retired pages stay refused.
The native operation locks navigation until completion. Server failure/outage
cannot be reenabled by a late print callback.

Linux keeps QPrintDialog/QPrinter/QWebEngineView.print for paper **and PDF**.
After dialog acceptance it checks captured mode/page/origin and a digest of the
static Avery sheet/style DOM; changed layout is refused. The QPrinter is retained
outside the page until printFinished. No new Linux PDF raster renderer, pagination
or copies engine is introduced. Qt's Unix print dialog itself validates file
writability and asks the overwrite question with No as default before accepting.
Its ordinary path-based output is not the former descriptor/no-replace publisher.
WebEngine's printer output can be rasterized, so native Linux PDF content may
need visual/OCR verification rather than extracted-text-only assertions.

Windows uses WebView2 and is not changed to Qt printing. No Windows acceptance
or native Linux package pass is inferred from Mac/source evidence.

## Focused checks and evidence reuse

Run the focused source safeguards and packaging identity tests. The source GUI
harness explicitly labels simulated dialog responses; simulations do not prove
native printer/PDF/overwrite acceptance. Separate task-owned native receipts
must distinguish selection/dialog opening, submitting a job and actual paper.

Fedora/Omarchy should reuse this shared correction, not create a competing fix:

1. Native Local and task-owned matching Server: physical printer/settings
   selection then Cancel; no automatic job.
2. Print Cards → native PDF destination: selected ALPHA/CHARLIE questions and
   answers only, BRAVO absent, Letter front/back pages. Cancel leaves output
   unchanged. Existing synthetic destination: decline preserves; explicit
   confirmation replaces only that synthetic sentinel. Do not simulate native
   confirmation in packaged acceptance.
3. Return retains selection/name/short-edge setting; old Server button markup
   still opens Print Cards. Older templates still need the already accepted
   shared Return template update to retain nondefault short-edge state.
4. Source guards: script/frame/wrong origin, duplicate/stale activation,
   document changes and loading/outage remain refused. Native-control failure
   after one attempt/one existing alternative is a gap, not an app defect.

Reuse all unaffected 2107 workflow, focus, icon and isolation evidence. No broad
application audit, full Firefox suite or recovery matrix is required here.
New package receipts, native results, hashes and exact overlay/source companions
are external so source/embedded materials do not change after the one build.

References:
https://developer.apple.com/documentation/appkit/nsprintoperation
https://developer.apple.com/documentation/pdfkit/pdfdocument/printoperation(for:scalingmode:autorotate:)
https://doc.qt.io/qt-6.11/qprintdialog.html
https://raw.githubusercontent.com/qt/qtbase/v6.11.2/src/printsupport/dialogs/qprintdialog_unix.cpp
