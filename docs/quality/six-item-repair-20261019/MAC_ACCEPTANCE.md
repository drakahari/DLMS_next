# Mac wrapper and Qt focus candidate: acceptance and source correspondence

This record covers the independently reviewed Apple Silicon candidate qualified on
2026-10-19. It adds Mac test-wrapper/build identity and the shared Qt Server focus
correction on top of [PR #23](https://github.com/drakahari/DLMS_next/pull/23).
It does not reimplement the shared Study/Rebuild, navigation or clipboard repairs.

## Stack and exact source

- Accepted source/handoff: `717dd01a5efa9c6cbc8f95f463e70714ec198597`.
- Shared repair ancestor: `c1268daaf8a1dab2919b912c117a1ac4f86ea6c6`, already in #23.
- PR base: `fix/six-item-daily-use-20261019`, the #23 head at preparation time.
- Merge #23 first using normal protections. Then verify/retarget this draft to
  `main` as necessary, review the resulting diff and required checks, and obtain
  separate merge approval. Do not merge this stack's dependency into this branch
  or copy/rewrite its shared repair commits to make a standalone PR.

The accepted build used that exact source plus the reviewed eleven-file overlay.
Those eleven files are byte-for-byte unchanged here. This commit additionally
contains only this sanitized record and [the Linux handoff](FEDORA_OMARCHY_FOCUS_HANDOFF.md).
The new records were not in the previously built source archive. The artifact was
not rebuilt to embed this later commit; its embedded identity remains the accepted
source plus runtime snapshot, not this commit's SHA.

| Identity | Exact value |
| --- | --- |
| Application/release | `3.3.0` / `macos-focus-fix-20261019` |
| Bundle | `DLMS Desktop Focus Candidate.app` |
| DMG | `DLMS-Desktop-3.3.0-macos-arm64-focus-fix-20261019.dmg` |
| DMG SHA-256 | `65092a153bb1f4cd22e4dfb5a8b68b47af2ac86876786d625b839d1fd81c1def` |
| Reviewed eleven-file overlay SHA-256 | `b06721b8b94512e51a8e40008ba83b8ef3d18e69975a53c3dec561c4c90e0920` |
| Runtime snapshot SHA-256 | `a79b3fc7a9d1e32f73d02c490782a9a9fa44a92af1716dd6bc3ea7c0df67e858` |
| Canonical app manifest SHA-256 | `34d16019c497451436a825b8720dc0538bbb2e719fb8d9d542c19df69a5c6ddf` |
| Application source archive SHA-256 | `a40edaf3b72176f8f578e218a8a06285315efc83e7fc1cc67a86bf1328851faf` |

Independent review matched all 1,535 application-source members, 434 runtime-source
entries and 8,638 app inventory entries, and inspected the embedded StrongFocus
assignment. The read-only mounted DMG matched the manifest and passed deep strict
signature verification; it was detached without installation. Unchanged pinned
dependency source/notices materials and companion hashes were verified offline.
Original artifacts, full evidence, failed-controller logs and checksum receipts
remain locally preserved. They are not included in Git or uploaded with this PR.

## Reviewed changes

The only new application-behavior delta is four inserted lines in
`desktop/shell.py`: establish `Qt.FocusPolicy.StrongFocus` after installing the
Server page, before saving its interactive focus policy. The old outer view could
default to NoFocus while its proxy accepted keys; restoring the saved zero then
made Server Tab navigation unusable. Loading, failure and outage remain disabled
and NoFocus; only the existing readiness/exposure path restores interaction.
Origin, action-lifetime, consent and AI deliberate-action protections are unchanged.

`tools/macos_test_wrapper.py`, `tools/macos_verified_test_launcher.m` and
`tests/macos/test_verified_wrapper.py` implement the reviewed test-only wrapper.
Originals are inventoried read-only. Only confirmed FinderInfo/ResourceFork on
fresh private staged output may be removed before signing; quarantine and other
attributes are preserved. Both the checked opener and native Finder wrapper
strictly verify the pinned wrapper/payload and explicit marked root/profile.
Failed verification prevents opening, with no default-root or security fallback.
This is test tooling, not a production signing/trust mechanism.

The five remaining reviewed files set distinct build identity/source provenance
and qualify historical preview documentation. The two new focus tests/helpers
are `tests/server_mode/test_focus_policy.py` and `gui_focus_navigation.py`.
No dependency pins or application version were changed.

## Focused results reused for this publication

Environment: macOS 26.6.2 arm64, Python 3.14.7, Qt 6.11.2. One focus-correction
rebuild followed independent source/test review. No rebuild or broad local tests
were performed to prepare this PR; triggered CI is reported separately on the PR.

| Check | Result and scope |
| --- | --- |
| Wrapper controls | PASS 6 regressions; both verification failures, changed/wrong identities and metadata failure prevent opener calls; quarantine preserved |
| Actual Finder-metadata provider control | PASS failure control: delayed FinderInfo caused strict verification failure; corrected gate made zero opener calls and preserved originals |
| Focus state tests | PASS 4 new real-WebEngine tests: loading to ready, failure/retry, repeated failure and stale completion protection |
| Existing focused regressions | PASS 93 loading/readiness/action-lifetime checks; retained from initial combined run, not repeated after test-fixture corrections |
| Source Qt journey | PASS actual Local/Server transitions, real synthetic outage/retry, return Local and second Server transition; app-local QTest input, final browser adapter intercepted |
| Deliberate AI action | PASS scripted dispatch refused; keyboard action copied only selected Q2/Q4 |
| Packaged Local and Server keyboard | PASS PID-targeted native CGEvent Tab/Return reaches the exact Marked link and selected AI action through Qt; CDP used only for setup/observation |
| Clipboard content | PASS both modes: selected Q2/Q4 only, 556 UTF-8 bytes including CRLF; SHA-256 `deedcd67b95a8584fdfc801e21912395e44b8e282216afcc5374abc3d7dd19ff` |
| Server browser confirmation | PASS owner selected Yes at the expected app-owned default-browser prompt; observation resumed and native handoff feedback was verified, without repeating the AI action |
| Normal wrapper launch | PASS separate no-debug LaunchServices launch after owner approved Documents access; exact explicit synthetic root/profile verified |
| Close and isolation | PASS normal Local AppKit terminate; exact app/backend exited. Server launched no Local worker; Local/Server records unchanged by AI |
| Independent review | PASS before rebuild and for artifact/source correspondence; final review verified all 35 then-existing checksum entries; its receipt was then added to the local checksum list |
| Cleanup | PASS captured task app/backend/helpers/wrapper/server stopped and loopback port closed; ordinary browser untouched |

The Server diagnostic observer timed out while the expected native browser modal
was open. One read-only accessibility alternative identified that modal; after the
owner chose Yes, the existing channel resumed and exact selection/clipboard and
handoff status were verified. This was not relabeled as an application defect or
silently passed by clicking through a security prompt. No AI paste or submission
occurred. Normal browser/profile identity uses the prior owner evidence; personal
browser contents were not inspected.

Prior owner Rebuild/current Study Resume, genuine-edit stale refusal, saved Marked
content, normal Server Cmd-Q/reopen, browser/profile and separation passes are
preserved at their original artifact/scope. Historical uncertain keyboard reports
are not rewritten; the current direct keyboard evidence above is separately scoped.
Accepted shared-code, recovery, isolation and fault evidence is reused from #23 and
the prior Fedora/Omarchy qualification. No full Mac walkthrough, full Firefox gate
or recovery matrix was repeated. Initial fixture/controller failures and their
corrections remain in local evidence; no assertion was weakened to produce a pass.

## Remaining qualification limits

- Source QTest, packaged native-event automation and physical owner observations
  are distinct. This is not a new full physical-keyboard/accessibility walkthrough.
- Fedora/Omarchy native Qt focus qualification remains pending; Mac results do not
  establish Linux passes. Windows uses WebView2 and is not qualified by Qt tests.
- Original two-byte clipboard and earlier source Server asynchronous single
  Copy Explain Prompt causes remain unresolved. The combined selected action
  passed; those different causes were not repaired or claimed resolved.
- Ad hoc signing only; no Developer ID/notarization. Downloaded/quarantined opening
  is unqualified for this candidate. No quarantine removal or Gatekeeper change.
- Selected-file snapshots do not defend against a malicious native process already
  running as the same user. Consent/origin/path/descriptor/content checks remain;
  no Linux-equivalent sealing is claimed.
- No new full scaling/printing, native destination-overwrite refusal or Server
  Study/Exam answer/save journey. Broader unchanged evidence retains its original
  limits. The process scan could not read unrelated host processes; exact captured
  task identities and closed loopback port, not a complete host census, prove cleanup.

All data was synthetic and task-owned. Installed apps, personal profiles and
production were untouched. The candidate's normal test launch uses a verified
explicit-root wrapper; the bare app must not be opened against an existing default
Preview profile. This record does not authorize installation, merging or release.
