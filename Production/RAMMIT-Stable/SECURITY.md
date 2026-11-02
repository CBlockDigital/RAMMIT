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
