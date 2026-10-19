# Windows native continuation — six-item repair

Status: source inspection and supplied-report diagnosis only; no Windows execution or repair in this Fedora task. Base runtime `bfdffb720f743e9d720cd07292ec7e1ec325e059`, accepted build source `4b50e2b3fb39dd478d355bf785b319805579076c`. Retained Windows report: normal EXE SHA-256 `310a2974a054dbad9a78ea7fb0a1218e23d40da85786cc9b1ce5f9a902b1e440`, 6,982-file inventory SHA-256 `2ace498781cdcc8ab5c18d60c04bef128775c9ad1876ab8febcaea3dbe16506b`, Windows 11 build 26200 x64, WebView2 155.0.4283.62. These are reported native identities, not artifacts newly verified here. Another machine's retained paths need not exist locally.

Use only an isolated task candidate/profile, task-created ordinary Documents fixtures and synthetic endpoints. Preserve original artifacts, logs and installed applications/data. Review source before any affected candidate build. No commit, push, install or production connection is authorized by this handoff.

## Avery: exact source decision remaining

`windows_webview2/Host.cs:479` handles an exact-origin Local user popup with `core.Navigate(e.Uri)`. This manufactures a GET and discards the original POST/body. The supplied Local result plus GET 405 / selected POST 200 receiver control establishes this defect. Same-origin Server popups are ignored by that branch; native Server failure has not been reproduced.

The correction must let WebView2 deliver its original new-window request into a destination WebView through `GetDeferral()` / `NewWindow`, after native policy setup. Do not reconstruct/replay the body, accept GET at the receiver or allow arbitrary popups. Confirm the pinned SDK/runtime destination requirements on Windows before implementation; the existing primary controller has already navigated and cannot be assumed to be an eligible new destination.

**Implementation decision required on Windows:** an Avery-only transient destination controller with explicit per-view security and lifetime ownership. This is more than replacing `Navigate` with one call: `DesktopRenderer` has one readonly primary `BrowserSurface`; `Cdp`, `ResolveRequest`, `Frame`, `Identity`, AI actions, generations, navigation/download/dialog/picker bookkeeping and shutdown all use that primary view. Attaching a bare second controller would bypass native request enforcement or apply decisions to the wrong controller. If isolating this destination requires a general multiwindow/renderer rewrite, stop this item for that design decision. No safe one-line Fedora source patch was identified.

Requirements for the narrow destination:

- Admit only a current, completed exact-origin main document at `/anki/custom`, deliberate user action, target `/anki/printable` without query/fragment. Require main-frame attribution (`OriginalSourceFrameInfo` matching the current source and no child-frame ambiguity); pin and recheck document identity, generation and retirement across asynchronous initialization. Refuse stale, scripted, iframe, wrong-origin and second concurrent requests.
- Initialize the destination in the owning mode's existing environment/profile; preserve Server cookies/CSRF without giving Server a Local token, Local Settings access or the Local print binding. Do not copy profiles or create an unrestricted browser environment. Retain parent selection/deck state; document whether Return closes the transient view or navigates it. Each deliberate action must cause exactly one POST.
- Before assigning `e.NewWindow`, install the same host-object/web-message/devtools/autofill/context-menu/accelerator restrictions, external-scheme/auth/certificate refusal, deny-and-do-not-save permission policy, exact-origin navigation and per-hop resource policy, blocked paths, worker/socket restrictions and request timeouts. Fetch decisions must target the destination controller, with separate frame/generation/request ownership. Preserve the existing Local preflight, main-frame-only token and origin/referer policy. Server must strip Local headers. Keep the pinned private extension/runtime integrity checks.
- Preserve guarded file chooser, downloads, script dialogs and mode-specific printing without attaching primary-view callbacks to the destination. Repeated popups, external handoffs and opener communication must not gain privileges. If unsupported in the transient view, refuse the action explicitly. Keep Local and Server print limitations truthful; no physical-printing claim.
- Complete each deferral once on success, refusal, initialization failure and shutdown. Dispose destination controllers before releasing environment/storage/policy pins or reporting full retirement. Parent close, mode transition, cancellation and process failure must retire the destination and its pending operations; no orphan window/process or stale native action.

Minimal native check after independent source review: one-card Local and synthetic Server form with a distinctive deck name and duplex selection; verify receiver POST, exact selected cards/layout/CSRF context, rendered sheet, Return selection/name, repeated deliberate action and close/cancel. Include one wrong-origin/iframe refusal and stale-document refusal. Reuse accepted shared receiver and Mac Avery results. Physical printing and duplex alignment remain unqualified.

## Save As: same-directory diagnostic, no speculative fix

Retained native **Save quiz export as** refused the full path with **“The file name is not valid.”** before publication and created no file. The later successful Documents-button/basename export saved in Documents itself; the rejected full path targeted a subdirectory. This is not an equivalent-destination control and does not establish a backend publication defect.

`desktop/windows_backup_chooser.py:configure` supplies a filename suggestion through `SetFileName`, selects an initial folder through `SetFolder`, and configures native filesystem/path checks. `choose_export` derives the suffix filter and passes the returned path to the existing output adapter. Source inspection alone does not identify which literal user input or dialog condition caused the native refusal. Preserve collision, owner/reparse/path-type and no-replace publication checks.

Create a fresh directory from the real configured Documents location on this Windows machine, before profile environment isolation. For example in ordinary PowerShell:

```powershell
$taskDocs = [Environment]::GetFolderPath('MyDocuments')
$taskRoot = Join-Path $taskDocs ('DLMS six item Windows ' + [guid]::NewGuid().ToString('N'))
$comparison = Join-Path $taskRoot 'Export space é'
New-Item -ItemType Directory -Path $comparison -ErrorAction Stop | Out-Null
$literalTarget = Join-Path $comparison 'selected-fullpath.apkg'
$literalTarget
```

1. Export the same synthetic selected card twice: first enter that displayed literal full path in File name; then navigate to that exact directory and enter a different new basename. Use single Windows separators, with no surrounding quotes or JSON escapes. Record the displayed literal input separately from its escaped log representation, current folder, filter/default extension, option flags, native message and final Show/GetResult HRESULT or cancellation. A validation error can leave Show active; do not invent an HRESULT from its message.
2. Compare produced APKG card fields and bytes when deterministic; if archive metadata changes bytes, record that and compare extracted logical contents. Confirm only the selected card and truthful saved-path feedback. Do not turn a failed full-path attempt into a pass because the other form succeeds.
3. Cancel once and verify returned focus/no success; target one task-created existing sentinel and verify refusal and unchanged hash. Preserve failed evidence. If input was invalid, correct guidance. Change splitting/normalization only after the same-directory control demonstrates the cause, then repeat that bounded control.

## Shared patch native continuation

After the reviewed shared patch, use one newly created ordinary quiz/partial Study: Rebuild twice and reopen the same session/position/answers; compare bytes/IDs/revision and complete without duplicate history. A genuine question/key edit must still refuse stale Resume. Missing/corrupt authority must preserve prior artifacts and report refusal. Test exact selected Q2+Q4 clipboard text and deliberate browser opening without submission, denial feedback, and the restored Marked questions entry/selected state/keyboard access. These remain native follow-up requirements, not results from this document.
