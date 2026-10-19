# Apple Silicon Mac: pinned shared safety source and native handoff

This is a separate native build/qualification task, not permission to replace an installed application, migrate data, bypass Gatekeeper or publish a binary. Keep accepted Linux Qt/OpenURI and Windows WebView2 behavior intact. Native Mac evidence must be produced on the Mac; Fedora source/contracts and fault-injected Linux package results do not establish it.

## Source and inherited scope

- Repository: `https://github.com/drakahari/DLMS_next`.
- Shared runtime: `bfdffb720f743e9d720cd07292ec7e1ec325e059`.
- Full approved build source plus four audit documents: `4b50e2b3fb39dd478d355bf785b319805579076c`, branch `docs/workflow-recovery-audit-20261018`.
- Handoff preparation branch: `build/linux-safety-candidate-20261018`; exact documentation/fixture commit is the Git commit containing this file (record the fetched head), with no runtime changes.
- Linux comparison candidate `linux-330-safety-20261018`: AppImage SHA **af46249a70520c2f5374419ccf7760aabee230887cc4eacaee2e02e74c12b9a5**. No new native Mac artifact/hash is supplied or accepted here.
- Canonical application is root `app.py`, `dlms/`, `templates/`, `static/`, `init.sql`, `tests/`, `tools/`. Host-specific Mac code is `package_macos/`, `desktop/macos_*.py` and narrow Darwin branches in the shared Qt host. No second active application copy or original checkout is needed.

Existing Mac installed launch, Server Dashboard/Library and Cmd-Q/reopen observations are historical owner-reported evidence for their exact older build. Preserve real-file upload protection, signing/notarization, redistribution and remaining native qualification limits. The present pinned runtime contains shared hotspot marking/rebuild, attempt-subset and bundle-navigation fixes plus Qt Anki/Avery transport fixes; the affected Qt paths may run on Mac, but native chooser, browser handoff, WebEngine request and lifecycle behavior still need focused Mac verification. Older remote deployments need the shared source update; a Desktop-only update cannot repair them.

## Obtain an exact, separate source and visible fixtures

Run in a normal Mac terminal. This creates a new checkout, preserves existing checkouts and copies only tracked synthetic inputs into normal Documents. The handoff branch is used for instructions/fixtures; build from the exact full build commit afterward.

```sh
set -eu
checkout="$HOME/Documents/DLMS-safety-source-20261018"
test ! -e "$checkout"
git clone --single-branch --branch build/linux-safety-candidate-20261018 \
  https://github.com/drakahari/DLMS_next.git "$checkout"
cd "$checkout"
git merge-base --is-ancestor 4b50e2b3fb39dd478d355bf785b319805579076c HEAD
git rev-parse HEAD
visible="$HOME/Documents/DLMS safety Mac fixtures 20261018"
test ! -e "$visible"
umask 077
mkdir "$visible"
cp docs/platform-candidate-20261018/fixtures/* "$visible/"
(cd "$visible" && shasum -a 256 -c SHA256SUMS)
git switch --create feature/macos-safety-candidate-20261018 \
  4b50e2b3fb39dd478d355bf785b319805579076c
test "$(git rev-parse HEAD)" = '4b50e2b3fb39dd478d355bf785b319805579076c'
test -z "$(git status --porcelain)"
```

Do not build with an unknown moving main, pull another platform's unfinished changes, or consult owner profiles to create fixtures. Supplied TXT/PNG/PDF/hotspot ZIP files are synthetic selectable inputs, not an APKG/profile/backup/application binary. Answers are B,C,A,B; scanned PDF's reviewed HTTPS question has C/443. Generate output/backups from the new synthetic app only.

## Existing native build process and explicit prerequisites

Use native Apple Silicon arm64, Xcode Command Line Tools and isolated Python **3.14.7**, with current unmodified `package_macos/requirements-lock.txt` and `requirements-resolved.txt`. Existing [Mac BUILD_AND_REPLACEMENT.md](../macos-preview/BUILD_AND_REPLACEMENT.md) describes the supported offline entry point, corresponding sources, ad hoc signing and system-security boundaries. Its original source IDs and macOS26.6.2 host qualification describe earlier artifacts.

The supported builder is `python -m package_macos.build --app-only --inputs /absolute/BUILD_INPUTS.json`. A recipient-local verified inputs file must already bind the exact interpreter, wheelhouse and hashes; historical producer paths are not portable. Exact native/wheel source indexes and reviewed source/notice companions must be present as required by `package_macos/native_materials.py` and `preview_materials.py`. The current producer also expects verified Tesseract/Leptonica/tessdata under its documented Homebrew producer prefix. Do not silently install missing tools or substitute unrelated current formulas. Report absent matching inputs before proposing acquisition. Existing official source/wheel archives can be reused only with verified hashes, not assumed from a similarly named file.

After setting explicit actual verified local interpreter/input paths:

```sh
set -eu
build_python='/ABSOLUTE/verified-isolated-environment/bin/python'
inputs='/ABSOLUTE/verified-native-inputs/BUILD_INPUTS.json'
test -x "$build_python"
test -f "$inputs"
"$build_python" -m pip check
"$build_python" -B tools/check_release_dependencies.py
"$build_python" -m package_macos.build --app-only --inputs "$inputs"
```

The builder writes a fresh private stage and `.gate1/macos/CANDIDATE.json`; never build inside an installed app or modify the protected payload to make a test pass. Preserve every failed stage.

**Known metadata prerequisite:** the pinned Mac builder currently embeds literal release `macos-arm64-preview1`, target `Apple Silicon macOS 26.6.2 (current host only)` and a historical `PROVENANCE.baseline`, while its `head`, runtime snapshot and file inventories are calculated from the actual source. These historical constants do not identify this new candidate. A final distinctly labeled Mac safety artifact needs a narrow separately reviewed packaging-metadata adaptation and host-qualification update; do not mislabel an unmodified run as a new `macos-330-safety-20261018` build or claim support for an untested OS. Record any such packaging-only diff separately from shared runtime bfdffb7 and exact build tree 4b50e2b. No such adaptation is implemented by this handoff.

The current builder ad hoc signs and verifies its output; this is integrity evidence, not Developer ID publisher trust or notarization. Stop for security warnings requiring a new decision. Do not disable Gatekeeper, remove quarantine, globally change permissions/security flags or request broad desktop-control access. A new DMG, source/notice kit and native manifest must be generated on the Mac only after source/input/identity correspondence is verified.

## Explicit synthetic launch and reopen

Set `candidate_app` to the exact freshly inventoried build output recorded by CANDIDATE.json, not an installed app. The target data root must be absent; the normal Mac entry creates its own private marker for a new root. Changing HOME does not redirect its real-home default, so always pass the explicit root. The package remains untouched.

```sh
set -eu
candidate_app='/ABSOLUTE/fresh-build-stage/dist/DLMS Desktop.app'
test -d "$candidate_app"
/usr/bin/codesign --verify --deep --strict "$candidate_app"
review="$HOME/Documents/DLMS safety Mac data 20261018"
test ! -e "$review"
"$candidate_app/Contents/MacOS/DLMS-Desktop" --data-root "$review" --profile safetymac01
```

Confirm the executable basename against `package_macos/DLMS-Desktop.spec` and exact app manifest before execution; do not substitute an arbitrary inner helper if a producer changes it. Later reopen, preserving same profile/origin:

```sh
set -eu
candidate_app='/ABSOLUTE/fresh-build-stage/dist/DLMS Desktop.app'
review="$HOME/Documents/DLMS safety Mac data 20261018"
test -f "$review/.dlms-macos-preview.json"
"$candidate_app/Contents/MacOS/DLMS-Desktop" --data-root "$review" --profile safetymac01
```

For ordinary Finder/dock identity testing, use the native app bundle in a newly approved separate test location, with explicit test-root launch design first. Do not install/replace the owner's launcher to perform it. Terminal execution alone is not Finder double-click acceptance.

## Bounded checks, not a new broad audit

1. Native import of neutral TXT from visible Documents, Study all correct, Exam first two wrong, Cmd-Q/reopen and window-close/reopen: exact answers, grading, saved histories and same Local identity. Verify About/build/support identity. Duplicate launch and helpers stop only for this test root.
2. Synthetic pack: circle/polygon hotspots retain representation/geometry/image, grading and saved history through marking, Rebuild All and reopen. Invalid authoritative content refuses safely; historical damaged-quiz recovery and migrations remain excluded.
3. Marked Anki initial/fallback where offered, repeat, native Save As/Cancel/collision and truthful outcomes. Exam attempt misses: select only second missed question and verify exported APKG includes only that item. Keep history-wide/marked semantics separate. Do not relax document/origin, trusted-action, file-consent or snapshot checks for Mac.
4. Avery Open Print Layout preserves POST/body, renders intended cards and retains selected cards/deck name on return. This is rendered output, not physical printer/duplex acceptance. Quiz Bundles narrow hamburger open/close, keyboard, aria-expanded and reachable links without data/selection mutation.
5. Revised Help, coherent Local Settings, backup creation/second synthetic-profile import where allowed, PNG/PDF OCR review, TXT Save As, repeated/cancel focus and explicit browser AI/clipboard. No automatic paste or submit. Test at narrow width/native200% with representative light/dark themes. Native input is owner-operated unless explicitly authorized application-local methods exist; no host-wide input injection.
6. Task-owned same-source synthetic server: distinctly different quiz/history, explicit loopback/private-HTTP opt-in, Study/Exam save and separate-process reopen, Server close Keep open/default and explicit close, outage without Local fallback, return Local unchanged. Never configure the owner's endpoint. Shared source fixes must also be present on the test server.

The existing `tools/macos_walkthrough_server.py` is bounded but tied to an older candidate cache/interpreter contract. Do not run it assuming it selects this new app. A platform agent should launch `tests/browser/_server.py` directly from the verified native source environment with a fresh `QUIZAPP_DATA_DIR`, `DLMS_BROWSER_TEST_BIND_HOST=127.0.0.1`, explicit free `DLMS_BROWSER_TEST_PORT` and `DLMS_NO_BROWSER=1`, retaining exact child identity. Do not terminate another service to reuse a port. Ctrl-C/cleanup must stop only that task-owned child.

Relevant focused test families are `tests/macos/`, shared hotspot/Anki/bundle regressions and the existing Qt consent/request tests; choose those affected, retaining native prerequisite failures. No broad suite, recovery fault matrix or original audit restart is requested. `tests/macos/normal_package.py` is supporting automation with its own marked-root/fixture requirements, not an ordinary owner walkthrough; keep those evidence layers distinct.

## Evidence and unresolved limits

Reuse [final safety report](../quality/workflow-final-safety-20261018.md), [recovery follow-up](../quality/workflow-recovery-followup-20261018.md) and [findings](../quality/workflow-findings-20261018.md). Linux normal executable with injected response faults and owner-operated mode menus is explicit inherited evidence. Exact Mac artifact behavior remains pending. The interrupted Exam result survived exactly once and History resolved it; pending Resume disappearance mechanism is unresolved and no same-ID retry occurred in that interrupted branch. No crash-durability/power-loss assertion follows.

Return exact commits and any packaging-only diff, dependency/source/notice inventories, artifact/hash, host OS/architecture, normal-vs-instrumented results and unresolved native checks. Preserve synthetic-only upload guarantee limitations, signing/notarization, redistribution and external-provider/physical accessibility/printing boundaries. No current task grants personal-data adoption, production upload, installed replacement or public release. An old executable alone cannot undo incompatible schemas or later data writes.
