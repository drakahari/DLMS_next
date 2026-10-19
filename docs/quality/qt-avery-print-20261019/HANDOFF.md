# Shared Qt Avery Print Cards correction — Fedora/Windows coordination

Base: `a8cd5182b6870e8bfdc1fca569b2cda9f191a1be` plus the exact reviewed source
overlay distributed as `PACKAGING_CHANGES.patch`. No commit or publication is
authorized by this handoff. Read `SOURCE_ACCEPTANCE.md` for scoped Mac evidence.

## Established failure and correction

The Avery layout loading successfully was not printing acceptance. A deliberate
Print Cards click in a real synthetic Qt Server emitted main-frame
`QWebEnginePage.printRequested`, but `_show_server` connected no handler: no PDF,
chooser or feedback. Local connected `_print_pdf`, which wrote a random private
PDF only. This is shared Qt code, not evidence that Fedora/Omarchy are unaffected.

`desktop/shell.py` now installs `desktop/qt_printing.py` on both Qt pages. It
consumes a one-use, isolated-world trusted main-document Print Cards click from
the completed exact `/anki/printable` document at the active Local/configured
Server origin. Scripted, child-frame, wrong/stale/loading/outage/retired requests
cannot open Save As. No new JavaScript native-command or filesystem API exists.
Existing Server HTML is supported: the exact canonical toolbar Print Cards button
may have no ID/status node, as in the pinned old template. Its type, parent toolbar,
text, `window.print()` handler and deliberate action still must match. Native
feedback remains visible without a page status element; no Server update is needed
to use this compatibility path.

Qt generates a US Letter/zero-native-margin PDF through its callback API. Native
code writes exclusive private staging in the correct mode and reuses unchanged
`desktop/exports.py` and `desktop/export_output.py` for explicit Save As, no-replace
publication and descriptor/path protections. The user destination is never passed
directly to Qt's overwriting filepath API. Native feedback plus fixed page status
report success, cancellation, refusal and failure without leaking native paths
into a Server document. Page generation/mode/lifetime are rechecked asynchronously.

`templates/anki/printable.html` retains `onclick="window.print()"` and the original
POST/body-preserving internal navigation. It adds `#printCards`, an accessible
print-hidden status, and the duplex value on Return. `templates/anki/custom.html`
restores that submitted duplex setting alongside existing selected IDs/name.
No route was relaxed to GET. No physical printer/duplex alignment claim is made.

## Smallest Fedora/Omarchy check requested

1. Run focused `tests/outputs/test_qt_printing.py`; retain existing output-boundary
   and Anki-template regressions where unchanged.
2. On the actual Qt session, use a fresh disposable Local profile and a task-owned
   synthetic Server. Select two of three synthetic cards, open the internal Avery
   layout, click Print Cards and save a PDF in ordinary Documents. Confirm the
   two fronts/answers only, two Letter pages, visible outcome, cancellation and
   existing-name refusal. Return must retain IDs/name/short-edge selection.
3. One scripted/iframe refusal must open no chooser; retain the unit lifetime/
   origin/close/loading/outage checks. Do not repeat broad workflows/recovery.

`tests/outputs/gui_qt_printing.py --work <new-private-task-folder> --output
<new-Documents-folder>` is an existing-QTest source journey: real Qt generation
and app-local input, but simulated native chooser answers. Its output is not
normal-package/native-sheet acceptance. Qualify the affected packaged print
surface separately on Linux before claiming Linux acceptance. Mac evidence does
not prove Linux native printing, focus, dialogs, portals or physical alignment.

## Windows boundary

Windows uses WebView2 and its own `_show_webview`/`_show_server`; no Qt print
controller is installed there. The retained candidate05 repair covered Avery POST
preview/stacking and disabled printing there; it was not printing acceptance.
No newer public printing PR was available during this task's read-only check.
The current separate Windows printing repair must validate its own deliberate
print action, output, cancellation and refusal. Do not port its native host code
to Qt or claim it passed from these results. Shared template IDs/Return fields
above are the only coordination surface; preserve `window.print()` and the
POST-only layout contract when integrating. No Windows native code was changed.

## Post-build commit/artifact and native-attempt record

See [COMMIT_ARTIFACT_ACCEPTANCE.md](COMMIT_ARTIFACT_ACCEPTANCE.md) for the exact
reviewed overlay commit/hash, immutable DMG/source correspondence, bounded genuine
native-dialog attempt and pending acceptance. This is a documentation addendum;
the packaged runtime and original prebuild evidence are unchanged. Desktop saves
a PDF for external printing. Older Server templates can print; nondefault
short-edge Return restoration still requires the shared template update.
