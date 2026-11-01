# Development and packaging reference

Ordinary users should start with the [current app downloads](../README.md#downloads).
This page is for contributors and maintainers, not an installation prerequisite.

## Run original DLMS from source

Use the supported project Python environment described in [Contributing](../CONTRIBUTING.md):

```sh
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-lock.txt
python app.py
```

On Windows activate with `.venv\Scripts\activate`. Compatible dependency ranges
are in `requirements.txt`; `requirements-lock.txt` retains the verified 3.3.0 runtime
lock reused for this maintenance baseline. Source OCR needs the local dependencies
in [OCR packaging](OCR_PACKAGING.md); packaged apps already carry their OCR runtime.

## Browser launch and process ownership

`--browser` forces a launch attempt; `--no-browser` suppresses it.
`DLMS_NO_BROWSER=1` suppresses launch and takes precedence over `--browser`.
Automatic launch is intended for an interactive desktop session. Headless/SSH
launch detection does not change the default loopback bind.

In local browser use, use **Shutdown DLMS** for an immediate, explicit stop.
In an eligible loopback-only desktop session, the optional
browser-presence shutdown feature can stop the process after the final browser
presence disappears and the grace period expires. Do not rely on it when the
feature is disabled or DLMS is running in LAN/server mode. If a process still
owns the local address, revisit it instead of starting another server copy.

Trusted-LAN hosting is explicit: the application has no built-in account login
or TLS and must not be exposed directly to the public Internet. See
[Settings and runtime](user-manual/16-settings-and-runtime.md) and
[installation/server guidance](user-manual/02-installation-and-first-launch.md).

## Build and verify native packages

Use [Native Release Verification](RELEASE_VERIFICATION.md) and
[OCR packaging](OCR_PACKAGING.md) for maintained tools and prerequisites. Historic
3.3.0 target examples there remain historical; they are not current download claims.
For a future authorized native build, select the actual platform and exact source:

```sh
python -m pip install -r requirements-build.txt
python tools/build_native_release.py --target fedora44-x86_64 --expected-commit FULL_40_CHARACTER_RELEASE_COMMIT --expected-version 3.3.1
```

Build natively in isolated paths. Current 3.3.1 packages are already published;
this documentation refresh requests no rebuild. For Mac diagnosis, the native
app executable is `DLMS.app/Contents/MacOS/DLMS`. The archive tool can use
`ditto -c -k --sequesterRsrc --keepParent dist/DLMS.app output.zip` during an authorized
build; this is not part of the normal installation. Final original Mac ZIPs also
include README.txt and sample_quiz.txt at the archive root.

## Exact source, licensing and historical evidence

Original 3.3.1: `79e42531d37b78fc806628e0ba989da13d9ed5ea`.
Desktop 3.3.1 Preview 1: `f507b64e9366cfd36a536d1112a5279ff28cb27d`, with the
platform supplements indexed in each release. [3.3.1 technical guidance](releases/3.3.1.md)
records changes, formats and acceptance limits. Public documentation commits are
separate from binary source pins. The original frozen tag retains stale
documentation assertions; the later publication PR corrected those expectations
without changing packaged source.

GitHub's automatic source archives identify tag contents; the current releases
also supply exact application exports and required platform source/notices/build-
replacement companions. Preserve the matching materials when redistributing;
source archives are not extra runtime prerequisites. See [Desktop licensing](desktop-license.md),
[LICENSE](../LICENSE) and [artwork provenance](../desktop_assets/ICON_PROVENANCE.md).

For historical 3.3.0 package/source/acceptance records, use the unchanged
[release notes](releases/3.3.0.md) and [release checklist](releases/3.3.0-RELEASE-CHECKLIST.md).
Do not interpret the old Omarchy target or browser AppImage examples as current 3.3.1 downloads.
