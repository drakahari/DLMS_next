# DLMS 3.0.2 Stable Release Audit

* **Date:** September 5, 2026
* **Review type:** AI-assisted release-readiness review
* **Disposition:** **READY FOR STABLE**

## Purpose and reviewed revision

This review assessed whether DLMS 3.0.2 was ready to move from release-candidate
status to a stable public release. The reviewed release ref was the annotated Git
tag `v3.0.2`, which resolves to commit
`74b62c7a817e2a8f53554d762cf2e6fb21915779` (`Add final DLMS 3.0.2 release
packaging`). The tag-to-commit relationship was rechecked from Git while preparing
this summary.

The audit phase was read-only: it evaluated the tagged repository, release
documentation, test evidence, native validation records, package contracts, and
release metadata. It did not rebuild or alter native binaries, published assets,
or the tag.

## Scope

The review covered the areas that could materially block a stable release:

* release identity, version consistency, tag state, and removal of prerelease
  labels;
* dependency locking, the canonical PyInstaller specification, and release
  hygiene;
* application startup, browser-launch controls, loopback binding, core routes,
  shutdown, and restart;
* quiz, study, analytics, learning-intelligence, import, and accessibility
  regressions represented by the test suite;
* backup, restore, atomic persistence, publication recovery, validation of
  imported content, and safeguards around destructive data operations;
* Windows, Linux, and Apple Silicon macOS native artifact structure and
  architecture;
* final package names, contents, executable permissions, excluded development or
  runtime data, and checksum-manifest membership; and
* README, Help Center, installation, removal, and native UAT guidance.

## Evidence reviewed

The public v3.0.2 release record reports the following final source-validation
results: 571 pytest tests passed, 17 skipped, 1,000 subtests passed, and 543
unittest tests passed. It also records successful Python compilation,
`git diff --check`, focused release/package checks, and package-structure
validation.

Native artifacts were recorded as built and tested on Fedora 44 x86-64, Ubuntu
24.04 x86-64, Ubuntu 26.04 x86-64, Windows 11 x86-64, Apple Silicon macOS, and
Omarchy Quattro x86-64. The native checks covered architecture, controlled data
initialization, application launch, local-server availability, core and user-help
routes, shutdown, and restart. Repository evidence for these controls includes
`DLMS.spec`, `tools/verify_release_artifact.py`,
`tools/verify_release_package.py`, the release verification tests, and
`docs/RELEASE_VERIFICATION.md`.

## Findings and disposition

The review found no release-blocking application, data-integrity, versioning, or
native-binary defect in the reviewed evidence. The stable identity was coherent,
the application remained local-first by default, the regression suite exercised
the release's main workflows and failure paths, and every named native target had
recorded platform validation. The final disposition was therefore **READY FOR
STABLE**.

## Limitations and subsequent evidence

This was an engineering review of the project and its release evidence, not an
independent security assessment or certification. Automated tests and native
smoke checks do not prove the absence of defects, and normal-user desktop UAT
remains necessary for platform security prompts and interaction behavior.

A later review on the same date found that the initially published macOS *final
ZIP* added an unnecessary versioned wrapper around an otherwise valid
`DLMS.app`. That final-archive presentation issue had been accepted because the
tagged verifier and its tests encoded the same incorrect contract. The app binary
did not require rebuilding; the archive was corrected and the repository's final
package gates were subsequently hardened. See the
[Native Packaging Audit](2026-09-05-native-packaging-audit.md). This later finding
qualifies the point-in-time package-layout evidence but does not change the
recorded stable-readiness disposition or move the `v3.0.2` tag.

## Primary references

* Git tag `v3.0.2` and commit `74b62c7a817e2a8f53554d762cf2e6fb21915779`
* [DLMS v3.0.2 release record](https://github.com/drakahari/DLMS_next/releases/tag/v3.0.2)
* `README.md` and `docs/RELEASE_VERIFICATION.md`
* `DLMS.spec`, `requirements-lock.txt`, and `requirements-build.txt`
* `tests/test_release_hygiene.py`,
  `tests/test_release_artifact_verification.py`, and
  `tests/test_release_package_verification.py`
