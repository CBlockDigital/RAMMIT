# Notes for AI agents (and humans) editing RAMMIT

Read [README.md](README.md) first: it has the module map and a "where to change X" table.

## Must-follow rules

1. **Secrets.** `.ROBLOSECURITY` cookies live only in `Storage` (in memory) and `Config/Accounts.json` (DPAPI-encrypted).
   - Never return them from `Api`, never log them, never put them in test fixtures, docs or commits.
   - Never read a real `Config/Accounts.json` (or a legacy `Config/accounts.json`).
2. **`Api.py` is an attack surface.** pywebview exposes every public attribute of the `Api` object to the page, including nested objects such as windows.
   - Keep state in `_`-prefixed attributes.
   - Validate every argument.
   - Return `{"Error": ...}` rather than raising.
3. **No HTML injection.** Build DOM with `El()` / `textContent`; never interpolate data into `innerHTML` or into CSS selectors.
4. **CSP stays strict** (`LocalServer.ContentSecurityPolicy`). No inline scripts or `onclick=`, no remote resources.
5. **Themes are full copies.** Edit shared UI code in `Src/Dark`, then run `python Tools/SyncThemes.py`. `--check` must report 0 differences before a build.
6. **Naming:** PascalCase identifiers everywhere. The exceptions are listed in README.md › Conventions; on-disk Config keys are one of them.
7. **Launch URI:** anything placed in the `roblox-player:` URI must pass `Roblox.BuildLaunchUrl`'s validation, because `+` separates its fields.
8. Run both test suites (README.md › Tests) after any change. Add a test when you fix a bug.

## Known limits

- Multi-instance only works if RAMMIT starts before any Roblox client (see `App/MultiInstance.py`).
- Real Roblox login and launch are not covered by automated tests.
- The exe is unsigned, so SmartScreen shows a warning on first run.
- Keep the PyInstaller **folder** build (RAMMIT.spec). The one-file build was quarantined by Defender's ML (false positive).
