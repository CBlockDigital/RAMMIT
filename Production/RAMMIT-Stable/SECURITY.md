# Security audit: RAMMIT 1.0.0 (audited as QA Beta, 2026-11)

**Subject:** the shipping `RAMMIT.exe`, built from `RAMMIT Flagship/src/web.py` with `src/HTML`, `src/CSS` (RAMMIT.zip, 2026-10-21).
**Method:** line-by-line review of the backend, both pages and the pywebview 6.2.1 internals they rely on. Every fix below is covered by `Tests/TestBackend.py` or `Tests/TestUi.mjs` unless marked otherwise.

## Findings and fixes

| # | Severity | Finding (old build) | Fix (1.0.0) |
|---|---|---|---|
| S1 | High | Roblox login cookies (`.ROBLOSECURITY`) were stored in **plain text** in `Config/accounts.json`. Anyone who got the file could take over every saved account. | Encrypted with Windows DPAPI, tied to the Windows user (`App/Crypto.py`). Existing plain-text files are migrated on first start. A file copied to another PC or user cannot be decrypted; those accounts show ⚠ and ask to be re-added. |
| S2 | High | **Stored XSS** in the privileged window. Config names, methods and params were inserted with `innerHTML` unescaped. A config named `<img src=x onerror=…>` ran script with full bridge access. | All dynamic UI is built with `textContent` (`Dom.El`). Drop-down values are looked up by comparison, not by building a CSS selector. A strict CSP blocks inline and remote script. |
| S3 | High | pywebview re-injects the full JS API into **any** page the main window navigates to (`edgechromium.on_navigation_completed`). An off-site navigation would hand that site the API. | `GuardNavigation` sends privileged windows straight back to the local UI. CSP `form-action 'none'` and `base-uri 'none'`, and no external links in the UI. *(Guard not exercised by automated tests: needs a real WebView2.)* |
| S4 | Medium | **Unvalidated bridge inputs:**<br>• `update_settings(key, value)` accepted any key and type; a string `max_instances` crashed every launch.<br>• `save_channel` wrote any string to `HKCU\Software\ROBLOX Corporation\…`.<br>• `place_id` and `cursor` were pasted into Roblox URLs.<br>• `job_id` could inject `+launchmode:…` fields into the `roblox-player:` URI. | Settings schema with per-key validators, all-or-nothing updates. Channel limited to `[A-Za-z0-9._-]{1,64}`. Place IDs are digits only, Job IDs must be UUIDs, link codes match a strict pattern, the cursor is URL-encoded, and `BuildLaunchUrl` refuses any field that could break out. |
| S5 | Medium | **Binary planting:** the console Ctrl handler ran `Popen(['python', …])`. Windows searches the exe's own folder first, so a `python.exe` dropped next to RAMMIT.exe would run. | Handler removed (the exe has no console). |
| S6 | Medium | Local web server: directory listings, any file type, no security headers, any `Host` accepted (DNS rebinding). | GET/HEAD only. `Host` must be `127.0.0.1:<port>`. Extension allowlist, no listings, paths confined to the active theme folder. CSP (`script-src 'self'`, no `unsafe-eval`, no remote origins), `nosniff`, `no-store`, `no-referrer`, CORP same-origin. |
| S7 | Low | Non-atomic JSON writes (a crash could corrupt accounts or settings); bare `except:` everywhere; a `users/authenticated` request with no timeout; unbounded server-list paging (thousands of requests for big games); the registry channel leaked into `settings.json`. | Atomic temp-file + `os.replace` writes, specific exceptions, 10 s timeouts, a 10-page cap, and the channel is no longer saved. |
| S8 | Info | The log could have recorded secrets if someone added a careless print. | `Config/RAMMIT.log` rule: usernames and status codes only (documented in `App/Log.py`, `AGENTS.md`). |

## Functional bugs fixed along the way

- **Second "+ ADD" re-saved the same account.** The WebView2 cookie store is shared by RAMMIT's windows, so the login page was already signed in. Cookies are now cleared after each capture.
- **Multi-instance silently failed if Roblox was already running.** `CreateMutex("ROBLOX_singletonEvent")` fails with error 6 because Roblox owns that name as an *event*; the old bare `except` hid it. RAMMIT now retries before each launch, shows a clear error, and marks the RUNNING counter with ⚠.
- The instance-limit check ran outside the launch lock (race).
- `pick_server` crashed when Roblox omitted `playing`.
- Clicking a config wiped the typed Game URL / Place ID (both were saved in one `launch_params` field).
- Accounts were removed by list index, so the wrong account could go; they are now removed by username, after a confirmation.
- Several login windows could be opened at once.
- Renaming a config in the wizard left a duplicate.
- The wizard could never reopen if pywebview missed the `closed` event.
- `max_instances` had no upper bound.
- Settings were written twice per click, and on every keystroke.
- The "Multi Instance Method" setting did nothing. It has been removed and old settings files are cleaned.

## Residual risks / accepted

- **Themes are trusted code.** A theme folder can include JavaScript that runs with bridge access. It still cannot read cookies or reach the network. Users are told to install themes only from people they trust.
- The exe is **unsigned** (SmartScreen warning). Code-signing needs a certificate.
- **Antivirus false positive (fixed in packaging, 2026-11-02):** Defender's ML model quarantined the first
  one-file build on extraction as `Behavior:Win32/DefenseEvasion.A!ml` (it never ran). One-file PyInstaller exes
  unpack Python into `%TEMP%` at every start, which resembles a dropper. The release is now a folder build
  (`RAMMIT.exe` + `Runtime\`), never UPX-packed, with full version info. Verified: extraction, a Defender scan
  and running it produced no detection, and nothing is unpacked to `%TEMP%`. ML verdicts can change, so signing
  is still the only guarantee.
- `requests` talks to `*.roblox.com` only; certificate validation is left at its secure default.
- DPAPI protects against file theft, not against malware already running as the same Windows user.

---

# 1.2.1 audit ("Blessed Frank", 2026-11-10)

**Subject:** `Production/RAMMIT-Stable` (app), `Production/Installer` (RAMMIT-Setup, the update path), `.github/workflows/CI.yml`, the release workflow draft and `Web/Website`, at 1.2.0 (commit `5988b8d`).
**Method:** line-by-line review of every Python module, the bridge-facing JavaScript, both workflows and the website. Each fix has a test in `Tests/TestBackend.py` or `Production/Installer/Tests/TestInstaller.py`. The tests were written and run on Linux with stand-ins for the Windows-only modules; **the full Windows suites and the real exe have not been run for this release yet** (CI runs them on the pull request).

## Findings and fixes

| # | Severity | Finding (1.2.0) | Fix (1.2.1) |
|---|---|---|---|
| F1 | Medium | **Installer: release files accepted from any GitHub repo.** The release list says where the zip and its `.sha256` are; any `https://github.com/...` link passed `_CheckUrl`. A list naming a file in someone else's repo, plus a checksum matching it, would have been downloaded, "verified" and installed. Needs a forged list (a broken TLS connection, or control of the list in some other way). | `Releases._CheckAssetUrl`: the zip and checksum must be under `github.com/CBlockDigital/RAMMIT/releases/download/`, checked before any request. Redirects are still limited to GitHub's file hosts. URLs with a port or user name are refused. |
| F2 | Medium | **Login window: a cookie from any site counted as the Roblox login.** `_FindLoginCookie` took the first `.ROBLOSECURITY` cookie whatever its domain. The login window is an ordinary browser window, so a site it ended up on could set that cookie and have *its* account saved (the user then plays, buys or trades on an account someone else controls). | Only a cookie whose domain is `roblox.com` or a subdomain counts, and its value must be printable with no `;` or line break (`Roblox.IsRobloxCookieDomain`, `IsCookieValue`). |
| F3 | Low | **Installer test mode could download from the network.** `RAMMIT_INSTALLER_TEST=1` + `RAMMIT_INSTALLER_RELEASES_URL` work in the released exe too and allowed any host over plain `http`. Needs control of the user's environment variables; installs go to the test folders, but the downloaded `RAMMIT.exe` can be launched from the done screen. | The override must be `127.0.0.1`, `localhost` or `[::1]`; test mode refuses to start otherwise. |
| F4 | Low | **Release workflow draft: script injection through the tag name.** `${{ github.ref_name }}` was pasted into `run:` scripts in a job holding `contents: write`. A tag such as `v1";<command>;"` would have run `<command>`. Needs push access; the file is a draft, not yet under `.github/workflows/`. | The tag and ref are passed through `env:` and the version is read from `App/Version.py`. |
| F5 | Low | **Local UI servers:** the CSP was only sent with `.html`. An `.svg` in a theme folder, opened as a document, ran its script without it. No idle timeout, so a local program could hold the server's threads open. | CSP on every response (also errors); 15 s idle timeout. App and installer. |
| F6 | Low | **A theme colour could stop RAMMIT starting.** `hsl(1.2.3, 5%, 5%)` passed the swatch pattern, then `float()` raised while the window colour was worked out, before the window existed. | `Themes._ToHex` returns no colour for it; the default is used. |
| F7 | Low | **Defence in depth: requests followed redirects.** `requests` drops a hand-set `Cookie` header on a redirect, so no login leaked, but the CSRF token and the rest travelled on, and it relied on a library detail. | Every request passes `allow_redirects=False`; a test counts the calls so a new one can't forget it. |
| F8 | Info | A non-numeric `ping` raised inside the server sort (launch failed with "Launch failed (TypeError)"). An odd release list (`assets` not a list, `size` not a number) raised out of `ListVersions`. `LogClientError` in the installer let `\r` and other control characters into `Setup.log`; a user name read from `Accounts.json` was logged unchecked. | All handled; log lines are single lines. |
| F9 | Info | The website had no Content-Security-Policy and showed v1.1.1. | CSP `<meta>` (own files + the Google font; the one inline script by hash), checked in headless Chrome with a deliberately wrong hash as the control. |

## Checked and found sound

- Zip extraction (`Setup.ExtractToStaging`): path escapes, device names, zip bombs, reserved names, staging marker.
- Swap, rollback, manifest-only uninstall, backups never following links.
- Bridge inputs in `Api.py` and `InstallerApi.py`: validated, state private, errors returned.
- `roblox-player:` URI building, registry channel, DPAPI storage, atomic writes, the log rule.
- DOM building in every theme and the installer page (`El` / `textContent`; the one `innerHTML` is static tour text).
- `RAMMIT:` protocol: nothing from the link reaches RAMMIT.
- CI: actions pinned to commit SHAs, `contents: read`, no credentials kept.
- Pinned packages against published advisories on 2026-11-10 (web search, not `pip-audit`: package installs were unavailable where the audit ran): requests 2.33.1 is past CVE-2026-25645 (fixed in 2.33.0) and CVE-2024-47081; PyInstaller 6.22.3 is past CVE-2025-59042; nothing found for pywebview 6.2.1, pywin32 312 or psutil 7.2.2. Run `pip-audit -r requirements.txt` before the release.

## Still open (not fixable in code alone)

- **The checksum is not a signature.** The `.sha256` sits next to the zip in the same release, so it catches a damaged or swapped download but not a release published from a taken-over GitHub account. Protect the account (2FA, no long-lived tokens), keep releases as drafts until checked, and sign the exe and zip when a certificate is available. The exe is still **unsigned**.
- **`requirements.txt` has no hashes** and CI installs without `--require-hashes`. Generate them on Windows (`pip-compile --generate-hashes`) before the release workflow is switched on.
- **Install folder outside the user profile.** `%LOCALAPPDATA%\RAMMIT` is private to the Windows user. A folder such as `D:\RAMMIT` is usually writable by every user of the PC, who could then change `RAMMIT.exe` or a theme's JavaScript there. Saved logins stay unreadable to them (DPAPI). On a shared PC, keep the default folder.
- **`GuardNavigation` acts after the page has loaded**, so a page the main window reached would have the bridge for a moment. Nothing in the UI can navigate away (CSP, no links, no forms); stopping it earlier needs WebView2's `NavigationStarting`, which needs testing on Windows.
- **The launch ticket is on Roblox's command line** (that is how Roblox takes it), readable by other programs of the same Windows user for the seconds it is valid.
- Unchanged from the first audit: themes are trusted code; DPAPI doesn't protect against malware already running as the same Windows user.
