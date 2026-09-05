# DLMS 3.0.2 Native Packaging Audit

* **Date:** September 5, 2026
* **Review type:** AI-assisted packaging investigation and release-hardening review
* **Revisions examined:** tagged commit `74b62c7` and hardening commit `813edd9`

## Purpose and outcome

This review investigated the final macOS ZIP layout published for DLMS 3.0.2,
traced the packaging and verification gap that allowed it, and assessed equivalent
protection for Windows and Linux final distributables. The defect was confined to
final archive construction and validation. It did not require an application-code
change or native rebuild.

## macOS final-package issue

The initially published ZIP used an extra versioned directory:

```text
DLMS-3.0.2-macos-arm64/
└── DLMS.app/
```

The intended macOS installation contract is app-only, with the bundle directly at
the archive root:

```text
DLMS.app/
```

The native `DLMS.app` and its arm64 executable were valid. The issue was the
transformation applied after native app verification: the final archive presented
the app under a package wrapper and added files that do not belong in the macOS
app-only contract. The correct intermediate app-only ZIP already existed, so the
fix promoted those same verified bytes as the final ZIP. No native binary was
rebuilt or changed, and the `v3.0.2` tag remained at
`74b62c7a817e2a8f53554d762cf2e6fb21915779`.

The corrected `DLMS-3.0.2-macos-arm64.zip` extracts directly to `DLMS.app`. Its
published SHA-256 is:

```text
174ff395cbd6b62b66fa99c1edc0bbfba8d1709498b0a1c2a6648ed3801fd705
```

That value was cross-checked against both the checksum printed in the public
v3.0.2 release notes and the digest reported for the published GitHub release
asset. This documentation review did not download, rebuild, or modify the asset.

## Root cause

Git history establishes the following chain:

1. Commit `74b62c7` added `tools/package_release.py` and
   `tools/verify_release_package.py`. Its macOS final-packaging path rewrote
   `DLMS.app/...` entries under `DLMS-3.0.2-macos-arm64/` and added `README.txt`
   and `sample_quiz.txt` inside that wrapper.
2. The verifier introduced in the same commit defined that versioned wrapper and
   the two documents as the expected macOS final-package contract.
3. `tests/test_release_package_verification.py` constructed and accepted the same
   wrapped layout. The final-package workflow therefore validated the generated
   ZIP against an internally consistent but incorrect contract.
4. The staged native macOS input was already the intended app-only ZIP. Packaging
   transformed that valid input into the wrapper-style ZIP that was initially
   uploaded.

The gap was not a failure to validate the app binary. It was a failure to keep the
final downloadable archive contract identical to the already-correct macOS native
input and normal Finder extraction experience.

## Windows contract and hardening

The tagged Windows final package already used the intended stable name and
layout:

```text
DLMS-3.0.2-windows11-x86_64.zip
└── DLMS-3.0.2-windows11-x86_64/
    ├── DLMS-3.0.2-windows11-x86_64.exe
    ├── README.txt
    └── sample_quiz.txt
```

Its structural verifier checked the archive members and x86-64 PE header, but the
tagged final-package path did not provide equivalent protection that cleanly
extracted the *exact final ZIP* with the native extraction tool and then ran the
application smoke test from that extracted location. That left room for a
packaging-stage error to escape checks that had been run against an earlier native
input.

Commit `813edd9` hardened the repository's release contract. The current process:

* requires the macOS ZIP to contain only root-level `DLMS.app` (with permitted
  associated macOS metadata) and promotes the verified app-only ZIP byte-for-byte;
* requires the exact Windows 11 archive, wrapper, and executable names and rejects
  stale, generic, extra, unsafe, duplicate, or case-colliding members;
* structurally validates each final Linux, Windows, and macOS distributable, then
  clean-extracts it with platform-appropriate tooling;
* revalidates the executable or app after extraction and runs the existing
  isolated start/routes/shutdown/restart smoke from that extracted final artifact;
* requires the final-package smoke on macOS, Windows, and each named Linux
  distribution in the release procedure; and
* allows checksum generation only for the exact canonical six-package set after
  each package passes structural validation, tying the manifest to the final
  distributable bytes rather than an intermediate artifact.

Regression coverage now explicitly rejects the old macOS wrapper, verifies
byte-for-byte macOS promotion, enforces stable Windows naming, exercises clean
extraction for all three platform families, confirms that smoke receives the
extracted executable, and prevents checksum creation for an invalid canonical
package.

## Disposition and limitations

The macOS final-package issue was remediated without changing application
behavior, native binaries, release identity, or the release tag. Windows retained
its intended user-facing layout while gaining an equivalent exact-final-artifact
gate. Linux, Windows, and macOS release guidance now shares the same essential
handoff: verify the native input, package once, clean-extract and smoke the exact
final archive on its native platform, then checksum and upload those unchanged
bytes.

These controls reduce packaging risk but do not constitute a security
certification and do not replace normal-user UAT. The packages remain unsigned;
the macOS app is not notarized; and native validation must still be performed on
the named target systems rather than inferred from portable structural tests.

## Primary references

* Git commits `74b62c7a817e2a8f53554d762cf2e6fb21915779` and
  `813edd9db1369a75fb128d43d91b3dcd6c7f4f2b`
* `tools/package_release.py`, `tools/verify_release_package.py`,
  `tools/verify_release_artifact.py`, and `tools/generate_sha256sums.py`
* `tests/test_release_package_verification.py`,
  `tests/test_release_artifact_verification.py`, and
  `tests/test_release_hygiene.py`
* `README.md`, `release_assets/README.txt`, and
  `docs/RELEASE_VERIFICATION.md`
* [DLMS v3.0.2 release record](https://github.com/drakahari/DLMS_next/releases/tag/v3.0.2)
