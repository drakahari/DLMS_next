# Windows candidate05 acceptance

This is a sanitized record of completed Windows qualification, not a new test run.
The unsigned normal candidate was built before the submission commit from the
source identity below. Binaries, profiles, databases, raw captures, credentials
and private operational records are not part of this submission.

## Source and artifact binding

| Identity | Value |
| --- | --- |
| Stacked dependency | PR #23, `fix/six-item-daily-use-20261019` |
| Exact build/submission parent | `717dd01a5efa9c6cbc8f95f463e70714ec198597` |
| Shared runtime already in that parent | `c1268daaf8a1dab2919b912c117a1ac4f86ea6c6` |
| Candidate | `windows-330-repair-20261019-candidate05` |
| Uncommitted build-input snapshot SHA-256 | `1fdd66cd9fa277d9e460df6f1509a98bfaffea76c528c75d9ccf9db13d1a3847` |
| Complete reviewed repair patch SHA-256 | `1e0e42bcdcc1a25b53ca12601f76b92db7b9ac63af2ba01470b1eb29ef1a470d` |
| Candidate04 to candidate05 patch SHA-256 | `428ab7c2eaf90850dd8345c341a2b7781f9d3f3369d6bbef45213aec53eda755` |
| Normal executable SHA-256 | `83431a4252c4c19f2c10f6ea34607f020813eb8bead07e31120b8e76e9f47aa5` |
| Native host SHA-256 | `610cc07342b0b02297a8e7e347e6e548256da49e01e2e2e742a8ba345831eade` |
| 6,982-file payload inventory SHA-256 | `33003c6ecb21229fb7e9d5dc7d2f13284af6c5b7a609ba0d5480e5dd72570529` |
| Matching source archive SHA-256 | `ddaa224874aec2e6f23e491bb98f1872b4527535e59662eeda0fa0c03d80c9bc` |
| Matching notices archive SHA-256 | `b8082656d7a54425eeb9b9fb53082011a4893ac860e7ab86a5ee71be996308ad` |

The complete patch covers the nine reviewed source/test files listed in the
[handoff](WINDOWS_CANDIDATE05_HANDOFF.md). These acceptance/handoff documents are
submission additions, not candidate build inputs. The commit does not retrospectively
replace the candidate's recorded pre-commit snapshot identity.

## Bounded owner acceptance: synthetic Server

On Windows 11 x86-64 with WebView2 Evergreen 155.0.4283.62, the owner operated the
normal candidate using a task-owned Server running the matching shared code.
Only synthetic Q2 was selected, with a distinctive deck name and Long edge duplex.

- The correct Q2 Avery sheet appeared and remained visible for at least the
  requested 20-second observation, across repeated theme refreshes.
- The owner then explicitly used Return and confirmed the purple Custom Deck page
  retained Q2 alone, the deck name and Long edge selection unchanged. An earlier
  ambiguous reply was clarified before accepting Return.
- Retained native events corroborate one admitted/opened/rendered original request,
  **75 `cover-front-preview` updates**, one `return` and one `closed` event.
  The synthetic receiver recorded `POST /anki/printable` returning HTTP 200.
- No desktop automation was used for this final owner session. The normal package
  used its supported opt-in bounded lifecycle capture; it was not an instrumented
  test build. Native events establish ordering, while the owner establishes pixels.

Candidate04's earlier sheet appeared briefly before the source page covered it.
That failure and its captures remain preserved locally. Its POST 200 and accessible
Q2 DOM were not counted as visual acceptance. Source analysis identified the
periodic Server cover refresh raising the original view; the old run did not retain
the exact callback responsible for the observed transition.

## Reused completed evidence

No Save As or broad workflow audit was repeated for the stacking correction.

| Evidence | Result and limits |
| --- | --- |
| Normal candidate03 Local Avery | Exact selected Q2 rendered; visible native header/Return; Return preserved selection, name and duplex. Reused because candidate05's extra stacking branch is Server-only. |
| Normal candidate03 Save As | Literal full path and folder/basename to the same ordinary Unicode/spaced directory both succeeded. APKG logical Q2/card contents matched. Existing destination refused without replacement; cancellation published nothing and left the page usable. No chooser code changed; historical invalid-filename input cause remains unproven. |
| Shared workflow continuation | Normal-package unchanged Rebuild preserved partial Study/reopen and artifact identity; genuine edits invalidated stale sessions; marker-only regeneration and incomplete-authority refusal retained data. Marked navigation and exact selected Q2/Q4 AI clipboard/browser checks reused. |
| Shared source regressions | 108 passed, two Windows symlink-privilege skips, 35 subtests. Only explicit UTF-8 fixture reading and actual WinError 1314 symlink fixture skips changed; assertions for ordinary paths remain active. Linux shared recovery/fault-injection evidence is reused from the dependency handoff. |
| Original-request source checks | Local/Server original POST/body and cookie/CSRF context, wrong source, script-only, stale document and frame negatives; bounded retirement checks. Source/instrumented checks are distinct from normal-package pixels. |
| Final stacking/header regressions | Four focused pytest tests; 80 assertions using the production native stacking helper with unshown controls, including repeated refresh, real cover/hidden/stale retirement and delayed supersession; 33 unchanged header-policy cases; lease/navigation wiring and bounded diagnostic filtering. No browser or visible window launched by these regressions. |

## Review and security

Independent implementation/security review approved the original-request ownership
and Server no-referrer handling. Final stacking review found an asynchronous stale
cover race; serial, generation and close/disposal guards plus a delayed-retirement
regression resolved it before the single candidate05 build.

Independent final correspondence verified 1,140 snapshot files, all 1,534 source
archive members, all 6,982 payload files without extras, seven normal host inputs,
3,582 material entries and 3,583 notices archive members. No instrumentation marker
was present. Six unchanged large source companions and their exact-input index
reuse the prior review rather than claiming a new full archive audit.

The engine-owned original POST/body is not reconstructed or replayed. Backend CSRF
validation, exact-origin/per-hop restrictions, certificate validation, genuine
native activation, one-use opener/frame/document ownership, Local token separation
and environment/storage pinning remain enforced. Missing Referer or missing/literal-null
Server Origin under `no-referrer` does not confer authority; the full native lease is
still required, and present foreign headers are refused. Local exact-header checks
remain strict. No privileged remote bridge was added.

## Remaining limits

- This is bounded synthetic acceptance, not long-duration graphical qualification.
- Physical printing, printer invocation and duplex alignment are unqualified;
  printing, downloads and file selection are deliberately unavailable in the
  closed-purpose Avery preview.
- Genuine cover/navigation invalidation and delayed races have structural/source
  regression evidence, not an additional physical normal-package interruption run.
- The broad application/Firefox suites were not rerun for this focused native
  repair. Previously completed shared evidence is reused; triggered PR CI is
  reported separately and does not establish physical Windows behavior.
- The candidate is unsigned. No installer was built, no installation or release
  occurred, and no production or personal data was used.
