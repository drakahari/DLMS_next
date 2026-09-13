# Contributing to DLMS

DLMS is a local-first, single-user learning application. Keep changes focused,
preserve existing user data, and prefer established services and persistence
paths over parallel implementations.

## Development setup

DLMS currently validates its locked environment with Python 3.14. Create a
virtual environment and install the runtime plus test runner:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-test.txt
python -m pip check
```

On Windows, activate with `.venv\Scripts\activate`. Normal selectable-text PDF
development does not require Tesseract. Follow
[`docs/OCR_PACKAGING.md`](docs/OCR_PACKAGING.md) when changing local OCR or
frozen OCR packaging.

## Testing changes

Run focused tests for the code you changed, then run the complete non-browser
suite before submitting a pull request:

```bash
python -m pytest -q -p no:cacheprovider -m "not browser"
git diff --check
python -m pip check
```

The release-verifier tests are part of that suite. Packaging-related changes
should also run these focused files for quicker feedback:

```bash
python -m pytest -q -p no:cacheprovider \
  tests/test_ocr_packaging.py \
  tests/test_prepare_ocr_bundle.py \
  tests/test_release_artifact_verification.py \
  tests/test_release_hygiene.py \
  tests/test_release_package_verification.py
```

Changes involving rendered workflows, JavaScript, browser recovery, themes,
responsive layout, or navigation should run the relevant isolated Firefox
workflow locally. Before release consideration, run the complete gate:

```bash
DLMS_RUN_BROWSER_TESTS=1 python -m pytest -q -p no:cacheprovider \
  -m browser tests/browser/test_critical_workflows.py
```

Each browser test owns its data root, server, Firefox profile, process, and BiDi
context. Do not replace deterministic readiness checks with retries or fixed
sleeps. Ensure task-owned Firefox and test-server processes are stopped after a
failed or interrupted run. See [`tests/browser/README.md`](tests/browser/README.md)
for the harness contract. The hosted Firefox gate runs weekly and on demand;
ordinary pull requests use the faster non-browser gate by default.

The scheduled dependency audit checks the locked runtime, build, and test
inputs. To reproduce it locally, install `requirements-audit.txt` in an
isolated environment and run `python -m pip_audit --requirement` against
`requirements-build.txt` and `requirements-test.txt`.

## Test-data privacy

Use neutral, self-created synthetic fixtures. Never commit real personal data,
private PDFs or screenshots, production databases, credentials, access tokens,
or extracts derived from private source material. Keep manual local inputs in
ignored locations and confirm they are unstaged and absent from `git status`.

Do not commit generated application data, OCR bundles, traineddata, native
binaries, build directories, test caches, logs, or temporary diagnostics.

## High-impact changes

Exercise additional care when changing schemas, migrations, persistence,
backup/restore, imports, OCR, parsing, security boundaries, native packaging,
or release verification:

- Preserve backward compatibility and add upgrade/rollback coverage for data
  format changes.
- Validate untrusted content at the server boundary and retain Review & Repair
  behavior when parsing is uncertain.
- Do not weaken packaging or release checks to accommodate one artifact.
- Build and smoke-test native artifacts only on their supported native target;
  follow [`docs/RELEASE_VERIFICATION.md`](docs/RELEASE_VERIFICATION.md).
- Do not change `APP_VERSION` unless the change explicitly requires a version
  update.

Before submitting, review the complete diff and `git status`, explain any
remaining risk or untested platform behavior, and keep unrelated changes out of
the pull request.
