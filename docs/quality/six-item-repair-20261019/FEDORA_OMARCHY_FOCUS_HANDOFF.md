# Fedora/Omarchy: focused shared Qt Server keyboard check

This handoff is self-contained for the changed Qt focus behavior. Reuse accepted
shared workflow, recovery, isolation and fault evidence. Do not repeat the six-item
audit, full Firefox suite, recovery matrix or unchanged Mac wrapper tests.

## Source and merge order

This branch is stacked on [PR #23](https://github.com/drakahari/DLMS_next/pull/23),
whose pinned head is `717dd01a5efa9c6cbc8f95f463e70714ec198597`. Its shared runtime
ancestor is `c1268daaf8a1dab2919b912c117a1ac4f86ea6c6`. The Study/Rebuild, Marked
navigation and clipboard repairs are already in that dependency. Do not duplicate
or rewrite them. Merge #23 first, then review/retarget the dependent Mac/focus PR
and let its required checks pass before any separately approved merge.

Use the exact commit containing this record in a preserved isolated checkout.
The acceptance record is [MAC_ACCEPTANCE.md](MAC_ACCEPTANCE.md). For a branch with
different later shared code, inspect the delta before applying; do not silently
replace an existing repair. Mac wrapper/build changes are separate from Linux.

## Only runtime change to assess

In `desktop/shell.py`, `DesktopWindow._show_server`, after `ServerPage` is installed
and before `_server_view_focus_policy` is saved:

```python
self.view.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
```

The other three inserted lines are explanation. On Mac the outer WebEngine view
defaulted to NoFocus(0), its proxy initially StrongFocus(11). Saving zero before
the Server loading cover caused the subsequent restore to propagate NoFocus to
the proxy. Local worked while Server Tab could not reach page controls.

Explicit interactive policy before capture corrects that. The existing cover must
still disable the view and apply NoFocus during loading, failed/outage states and
stale completions. Only the existing ready/exposure path may restore keyboard input.
Origin/readiness checks, action tickets/lifetimes and deliberate AI authorization
are unchanged. Do not change desktop keyboard settings or make outage pages interactive.

## Focused source checks

Use your existing pinned environment and fresh disposable paths. These checks use
synthetic fixtures already in Git; no production or personal profiles are needed.

```sh
python -B -m pytest -q -p no:cacheprovider \
  tests/server_mode/test_focus_policy.py \
  tests/server_mode/test_loading_overlay.py \
  tests/server_mode/test_readiness.py
```

The four new tests replace transport with inert HTML and exercise real production
view/proxy, constructor/load/exposure paths. They do not qualify actual endpoint
authorization, a packaged app or physical keyboard use. Keep their assertion that
the focus proxy becomes interactive only after readiness and remains protected
after failure/retry or a stale completion.

For one source GUI journey in the normal graphical session, choose a genuinely new
profile beginning `sixfocus` and a nonexistent task evidence directory:

```sh
python -B -m tests.server_mode.gui_focus_navigation \
  --profile sixfocuslinuxcheck01 \
  --output "$HOME/Documents/DLMS-focus-source-check-20261019"
```

The helper refuses existing profiles/output, starts only a loopback synthetic WSGI
service from this checkout, and intercepts the final external-browser adapter. It
uses existing `.gate1` isolation (the root must be private/owned, without changing
unrelated existing directories). If a required path already exists, choose a new
name; do not delete it. Run GUI acceptance in a real graphical session; an offscreen
result is not physical/native desktop acceptance.

The helper covers loading→ready, real outage→protected state→retry→ready,
Local→Server→Local→Server, Tab/Return to the exact `/marked-questions` sidebar link
and to the selected AI action, exact selected Q2/Q4 clipboard, and rejection of
scripted AI dispatch. Its fixture comes from `tests/six_item/gui_clipboard.py`.
Expected copied prompt: 556 UTF-8 bytes including CRLF, SHA-256
`deedcd67b95a8584fdfc801e21912395e44b8e282216afcc5374abc3d7dd19ff`.
It must exclude Q1/Q3. No automatic paste or provider submission is allowed.

## Packaged acceptance is a separate result

If separately authorized and an exact-source package is available, perform only
the changed-focus journey in one disposable Local/configured synthetic Server
profile: Tab reaches page controls after ready; exact Marked link activates with
Enter; selected AI keyboard action copies only selected questions and respects
the normal browser confirmation; outage/loading remains protected and retry
restores navigation; return Local remains usable. Reuse existing launch/shutdown
and broad Server safety evidence except where a concrete regression requires more.
Use a task-owned endpoint with matching code and stop test processes afterward.
This handoff itself does not authorize a rebuild, installation or production access.

Report **source tests**, **source GUI**, **packaged native behavior** and any
**owner observation** separately as pass/fail/pending with exact source/package
identity. Source QTest or renderer-script success is not packaged acceptance.
If a native control blocks automation, use one existing alternative and queue the
minimal owner action rather than developing new automation or claiming a pass.

## Existing Mac evidence and platform boundary

Mac source tests and actual Qt transitions passed. The accepted packaged candidate
also passed PID-targeted native Tab/Return to the exact Marked link and selected AI
in Local and synthetic Server, with exact clipboard content. CDP was setup/read
instrumentation only; owner accepted the expected Server browser Yes prompt.
Normal no-debug wrapper launch was verified separately after Documents permission.
This is Mac evidence, not a Fedora/Omarchy pass; see the acceptance record for limits.

Windows uses WebView2. Do not prescribe these Qt tests or a Qt rebuild there.
Portable/native WebView2 and accepted shared-repair evidence retain their original
scope; this patch does not establish a new Windows result. Mac Finder metadata,
ad hoc signing and explicit-root test-wrapper handling are Mac-only concerns.
