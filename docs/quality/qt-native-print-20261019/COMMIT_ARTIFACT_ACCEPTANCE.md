# Standard printing — exact committed source and retained Mac artifact

## Commit-to-artifact binding

- Original build base / first parent: `2107e5cffc787705dfbbb495995655ebd504dedd`.
- Exact nine-file reviewed source commit: `acf00838973037f25721f9a13961e76e1916f947`.
- Literal `git diff --binary <base> <source-commit>` SHA-256:
  `449182ad6507af54989a70ea22ba616513e8b74f52c73f293ee0b3b1835ae449`.
- Shared Qt subset SHA-256: `9699b58ba67541ea016362a425766d12d12661b9c8be544e2d8f874b98373afa`.
- Retained DMG: `DLMS-Desktop-3.3.0-macos-arm64-preview.dmg`, 257609565 bytes.
- DMG SHA-256: `d33144a6a5946b63086364ca324a228a02b850bd6808bb1ef59faa4c413a4fe4`.
- Main executable SHA-256: `8f62053baaf5ffe044d52b6c8d1c141e3fc3eff207a3bf9978e686b57d8a5324`.
- Canonical application inventory SHA-256: `1ef3f5200f5e28ab158ecb12e0970dc3c88199170c3e89035c548eb2ee91c702`.
- Embedded runtime snapshot SHA-256: `5c6f23b5273c598041b7e3290dabe44949a46137f2a1354a65ed479c3b7dce89`.
- Original round blue icon SHA-256: `78a9be61a62521fe05e70df70572ea76e608b1c03457f5f815ab815aa38447fe`.

The source commit is exactly the independently reviewed, owner-tested overlay;
its complete binary diff equals the literal PACKAGING_CHANGES.patch preserved
inside application source/notices and as a separate companion. The subsequent
commit adds only MAC_ACCEPTANCE.md, this binding and FEDORA_HANDOFF.md. These
post-build documentation addenda are not represented as original build inputs
and do not change the application/runtime or immutable distribution materials.

The retained app was built **before these commits**, from the actual pinned base
plus that overlay. Its embedded application_base/source_state/patch identity and
clean_unmodified_build=false remain unchanged. It is not relabeled as a pristine
build of either later commit. The source guard intentionally expects the pinned
base plus overlay; reproduce that exact input arrangement instead of bypassing
it to claim a new build from the committed head. Build-time HANDOFF.md's pending
owner status is historical; [MAC_ACCEPTANCE.md](MAC_ACCEPTANCE.md) records the
later owner native checks explicitly without modifying the frozen source.

## Correspondence and retained qualification

Independent review verified the five frozen printing/page/export modules against
compiled source, all 88 templates and 143 static files, original icon, complete
source/notices archives, signatures and the one direct self-contained
DLMS Desktop.app. All 1,590 application-archive members matched the exact manifest
(including two generated provenance/patch records). Reconstructing the full
pinned Git tree, including tracked export-ignored files, and applying the literal
overlay reproduced the distributed source bytes. That verification-helper
correction did not change source, the build or the DMG. The read-only mounted DMG
contained only DLMS Desktop.app and matched the signed build inventory; it was
detached normally. Matching source/notices and the 17-file manifest remain local,
prepared for separate publication authorization; no binary or raw evidence is
committed here.

Owner-tested **source** native PDF saves passed in Local/synthetic Server;
Local cancellation and system overwrite decline/confirmation passed. Agent PDF
content and both modes' Return checks passed. The replacement **package** only
repeated the minimal Local standard-dialog/PDF-option/Cancel smoke and normal
Quit, passing the first bounded native attempt. It reused exact-source evidence
for PDF saving/overwrite/Server rather than repeating the owner walkthrough.
Physical paper output/alignment/duplex and Linux native qualification remain
unqualified. Downloaded/quarantined and cold Finder/default-profile opening were
not newly qualified. Ad hoc signatures are not Developer ID or notarization.
See [MAC_ACCEPTANCE.md](MAC_ACCEPTANCE.md) for precise attribution and limits.

## Preserved 17 public-asset manifest

These are retained companion filenames/hashes, not downloads uploaded by this PR.
The release proposal is proposed body text, not an eighteenth public asset.
SHA256SUMS covers the other 16 files; its own digest is recorded below.

| Filename | Bytes | SHA-256 |
| --- | ---: | --- |
| APPLICATION_SOURCE_MANIFEST.json | 176513 | `a676f11440aa0ad8ea8ed8dbc0b39fc4c92bba2e34c5e36ba452ac306a6a86c2` |
| APP_MANIFEST.json | 1794229 | `dfea466b91f1df4c9b19324baad09ab54b8481e3a73b2273e4828b4af09a4dda` |
| BUILD_PROVENANCE.json | 181727 | `a2a3e8c7ebc8b3611784d7a0458f5e8f1f02d3cf18e4fada7f134cb4acfde3ed` |
| DLMS-Desktop-3.3.0-macos-arm64-preview.dmg | 257609565 | `d33144a6a5946b63086364ca324a228a02b850bd6808bb1ef59faa4c413a4fe4` |
| DLMS-Desktop-3.3.0-macos-preview-notices.tar.zst | 1840185 | `570318694fd97d7b20cc225151235b4e9c0596775990717c1d1c06ca206b2a21` |
| DLMS-Desktop-3.3.0-macos-preview-source-application.tar.zst | 52899253 | `b4270e228055b4629ca3f5b3039793617699ab51550e0330205535d68e586e49` |
| DLMS-Desktop-3.3.0-macos-preview-source-native.tar.zst | 134880517 | `35fdd342bb0bc254904dce85814784b17754a9fbb42ed4cf86b8dcfe5856edd6` |
| DLMS-Desktop-3.3.0-macos-preview-source-wheel-native.tar.zst | 11092500 | `b4aaeda3da7bae923d898d718cbed190eea24945fce4832fa268d6c748e83010` |
| DLMS-Desktop-3.3.0-preview1-source-python.tar.zst | 100114172 | `40d78ccaad2cb0aadcca96f7f9cfeff06cba11e2de794ec45146954190b141f1` |
| DLMS-Desktop-3.3.0-preview1-source-qt-pyside.tar | 1037721600 | `2d5f30392243200188b7df70563ba9d40e9847d695c979f628e38543d9d6ff73` |
| ICON_RESOURCES.json | 2939 | `4c49a89263dc79110cadf89dc1cdf5e954c365d3f04c29313ba34c33609b68c6` |
| PACKAGING_CHANGES.patch | 59544 | `449182ad6507af54989a70ea22ba616513e8b74f52c73f293ee0b3b1835ae449` |
| QUALIFICATION.json | 4187 | `c961c208e9a33228bb5257f0562269a199f9e4e77beef070266a5adfa8011d4c` |
| RELEASE_NOTES.md | 4965 | `24871789608de036b6edf22ab38f20930ed038deaf625c91af4f5affa281391c` |
| SHA256SUMS | 1621 | `d4a7392dfa4d9c6e5133adb1408b11110cca24e66da05d2a31cd4fd7ae26decc` |
| SOURCE_CORRESPONDENCE.json | 2852 | `7fe295405ab18a893e29d170898575d5879dece0427d1d6ed789fe10ab9bb7a5` |
| SOURCE_INDEX.json | 2619 | `0b9f13fa20c4a40e046cf9af79e5ae55e6bae8d81677332c0498a389132d7a7b` |

The unchanged preview1 Python/Qt source archive labels identify reused upstream
third-party materials, not this application build. Exact Mac/native/wheel-native
producer/source obligations are indexed separately in notices and SOURCE_INDEX.
No asset, installed app, profile, release setting or server is changed by commit,
push or draft PR creation. CI results belong to the PR checks and are separate
from native/paper acceptance; assertions must not be weakened for a failed job.
