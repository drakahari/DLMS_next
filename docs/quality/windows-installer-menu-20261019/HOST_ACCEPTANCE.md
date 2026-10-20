# Preview 2.1 actual-host installation acceptance

Date: 2026-10-19. The owner separately authorized the actual unsigned shipping
installer on Windows 11 and explicitly allowed a fresh Local profile. This
supersedes the earlier lack-of-isolated-environment blocker in PR #31.

## Exact source and artifacts

- Installer correction: `d8571c54d08ee61d1b9be698147d5a0374c71bbb`.
- Test-only follow-up: `8169a716639431f61595b55614565562f0777be6`.
- Unchanged application source: `2107e5cffc787705dfbbb495995655ebd504dedd`.
- Installed shipping installer SHA-256: `823ac0f4bc0d57f6cda15edad490ff478d2c849dad7ca90e2237c7f7a5978940`.
- Installer script SHA-256: `fee044e283c86e249936699bccf1b80b6e4249e8adcfa1a01ff0604951bfa4c1`.
- Installed application executable SHA-256: `b1c03e66e4fa505e00d2ec4cdb7374da114439334666081f1e0aba0c37e69b04`.
- Payload inventory SHA-256: `6aec99e6ac9220f55b0cc238395a9f7435a90ebb309eb7dbf338200c52802165`.

The installer and application were not rebuilt or modified. This documentation
records acceptance of those existing bytes; it does not claim they embed the
later documentation commit. The prepared 19-asset publication packet is retained
unchanged, pending separate publication authorization.

## Actual host results

| Check | Result |
|---|---|
| Exact approved installer | SHA-256 verified before execution |
| Shipping setup | Succeeded under the ordinary user, HKCU registration; no restart, elevation or security warning reported |
| No-menu/profile UI | Owner selected the explicit no-Start-menu option and confirmed `local-preview21-01`, then completed Finish |
| Optional actions | Desktop shortcut and automatic launch left unchecked; no Start menu integration created |
| Fresh Local profile | Profile absent before first launch; new owned loopback backend served Dashboard successfully |
| Installed payload | All 6,987 files match the retained complete payload inventory |
| Existing permissions | All four captured directory owners and complete security descriptors unchanged, including the unsafe Start menu parent |
| Supported launcher | Exact installed target, version working directory and `--profile local-preview21-01` verified |
| Close/reopen | Launcher opened twice through the Windows shell; Dashboard HTTP 200 after 2.134 s and 1.618 s; identical profile UUID after reopening |
| Shutdown/cleanup | Both runs closed through the existing authenticated application shutdown endpoint; no observed owned descendants remained; app left closed |

Supported launch location:

```text
%LOCALAPPDATA%\Programs\DLMS Desktop WebView2 Candidate\Launch DLMS Desktop.lnk
```

The shortcut targets
`versions\windows-330-preview2-merged-20261019\DLMS-Desktop-WebView2.exe`, uses
that version folder as its working directory and passes exactly
`--profile local-preview21-01`. It does not use the unsafe Start menu location.
Profile data remains outside the payload at
`%LOCALAPPDATA%\DLMSDesktop\WebView2Candidate\profiles\local-preview21-01`.
No existing data was deleted merely to install; no production Server was used.
No ACL, inheritance, ownership or security-setting correction was performed.

## Evidence boundaries

This was the actual shipping installer and normal installed application, not a
TestScope/inert payload. Native wizard operation was owner-performed because the
computer-use helper could not acquire the foreground window. Installer log,
resulting shortcut, payload hashes and process/profile observations corroborate
the selected installation. The ordinary existing-folder warning was accepted;
it was not an elevation or security warning.

Startup/reopen checks establish installed launch, Local backend readiness and
profile identity. They do not independently establish correct displayed pixels,
keyboard focus or physical workflow acceptance. The normal shutdown API was used;
this session did not exercise a window-close button. Existing inert fresh/upgrade/
reinstall/safe-menu results and unchanged application workflow/printing evidence
remain distinct and are reused; no broad workflow tests were repeated.

Private setup log, before/after ACL snapshots, launcher metadata, full installed
payload verification and two-run launch receipt remain locally preserved. They
are deliberately excluded from Git along with profiles, databases, credentials,
backups and binaries. No machine/user identifiers, profile UUID or raw ACLs are
included here. No further installation, rebuild, tests or publication is part of
this documentation-only update; only automatically triggered CI is to be checked.
