# RAMMIT: Roblox Multi-Account Launcher (developer guide)

A Windows desktop app that saves several Roblox logins and launches many clients at once. Python runs the backend; the UI is HTML/CSS/JS shown in a [pywebview](https://pywebview.flowrl.com/) (WebView2) window; PyInstaller freezes it into `RAMMIT.exe`.

- End-user guide: [Docs/README.txt](Docs/README.txt) (ships as `README.txt`)
- Theme tutorial: [Docs/HowToMakeATheme.txt](Docs/HowToMakeATheme.txt), with technical details in [Docs/CustomThemes.md](Docs/CustomThemes.md)
- Security audit and hardening: [SECURITY.md](SECURITY.md)
- What changed in this release: [CHANGELOG.md](CHANGELOG.md)
- Rules for AI agents editing this repo: [AGENTS.md](AGENTS.md)

## Quick start

```bash
pip install -r requirements.txt
```

```bash
python RAMMIT.py
```

Running from source uses `./Config/` next to `RAMMIT.py`. Set `RAMMIT_BASE_DIR` to use a different folder; the tests use this so they never touch real accounts.

```powershell
powershell -ExecutionPolicy Bypass -File Build.ps1
```

`Build.ps1` runs the checks, builds `RAMMIT.exe`, and writes `dist/RAMMIT/` (the app), `dist/Source/` (this tree) and `dist/RAMMIT-<version>.zip` with its `.sha256`. Builds are Stable by default (the footer reads `v1.0.0 · Stable`); add `-Channel Dev` for a test build (`v1.0.0 · Dev (a1b2c3d)`).

## Runtime layout

```
RAMMIT.exe
Runtime/         Python + libraries (PyInstaller folder build - see RAMMIT.spec for why not one-file)
Src/<Theme>/     one complete UI per theme: Dark, Light, CBlock, MyCustomTheme, ... (see Docs/CustomThemes.md)
Config/          created on first run: Accounts.json (DPAPI-encrypted logins), Settings.json,
                 Config.json (saved launch configs), RAMMIT.log
README.txt, HowToMakeATheme.txt
```

## Architecture

```
 JS module ──window.pywebview.api.X()──▶ App/Api.py ──▶ Storage / Roblox / MultiInstance / Themes
     ▲                                        │
     └──── window.RammitEvents.X() ◀──────────┘  (Api._Notify: AccountsChanged, ConfigsChanged, ShowMessage)

 WebView2 window ──HTTP──▶ App/LocalServer.py (127.0.0.1, random port) ──▶ Src/<active theme>/
```

### Backend (`App/`)

| Module | Responsibility |
|---|---|
| `Main.py` | Start-up: logging, multi-instance lock, local server, main window |
| `Api.py` | **The JS bridge.** Every public method can be called from the page. Validates inputs; never returns secrets |
| `Storage.py` | Config files: atomic writes, settings schema + validation, legacy migration, configs, accounts |
| `Crypto.py` | DPAPI encryption of saved login cookies |
| `Roblox.py` | Roblox web APIs, server picking, VIP links, the `roblox-player:` launch URI, launcher path, registry channel |
| `MultiInstance.py` | Singleton-name mutex and cookie-file lock; counts running clients (game windows only) and tracks which client is which account (`ClientTracker`: the launched process, its children, then the launch ticket) |
| `LocalServer.py` | Hardened static server for the active theme folder |
| `Themes.py` | Theme discovery, `HeightMap.json`, fallback to Dark |
| `Paths.py`, `Log.py`, `Version.py` | Locations, the log file, the version string |
| `WindowSize.py` | Resizes the main window and the config wizard; while the title bar is held, waits and applies the height once it is let go |
| `Install.py` | When the installed folder was moved by hand, points the installer's registry entries and the `RAMMIT:` shortcut protocol at the new place |

### Frontend (`Src/<Theme>/JS/`, plain ES modules, no build step)

| Module | Responsibility |
|---|---|
| `Main.js` / `Wizard.js` | Entry points of `Index.html` / `Wizard.html` |
| `Bridge.js` | `Api.X()` proxy to Python, `On(event)` for Python→JS events, `ReportError`, `OneAtATime` (calls such as resizes, one at a time) |
| `State.js` | Shared main-window state |
| `Dom.js` | `El()` element builder (always `textContent`), `Debounce`, helpers |
| `Select.js` | The custom drop-down component |
| `LaunchForm.js` | Launch-method fields + Players/Ping filters (shared by both pages) |
| `Accounts.js`, `Configs.js`, `Launch.js`, `Settings.js`, `Themes.js` | One per panel |
| `Status.js` | The two status lines |
| `Tooltip.js` | Themed tooltips for every `title` / `data-tooltip` (shown as plain text) |
| `TourData.js` / `Tours.js` | Tutorial content / tutorial engine |

## Where to change X

| I want to… | Edit |
|---|---|
| Add a setting | `Storage.SettingsSchema` (public key → disk key, default, validator), then read it from `GetSettings()` and write it with `UpdateSetting("Key", value)` in JS |
| Add a backend action for the UI | A public method on `Api` (validate every argument), then call `Api.MethodName()` from JS |
| Change launch behaviour | `Api._ParseTarget` / `Api._LaunchOne`, `Roblox.py` |
| Change the look of one theme | The variables or THEME EXTRAS in `Src/<Theme>/CSS/Style.css` |
| Change layout or code for every theme | `Src/Dark/…`, then `python Tools/SyncThemes.py` |
| Make a preview picture of a theme | `python Tools/RenderTheme.py <ThemeId> [...]` (headless Edge/Chrome, demo data; writes `ThemeRenders/<ThemeId>.png`) |
| Change window heights | `Src/<Theme>/HeightMap.json` |
| Change tutorial text | `Src/Dark/JS/TourData.js`, then sync |
| Bump the version | `App/Version.py` |

## Conventions

- **PascalCase for all identifiers**: Python, JS, CSS classes and custom properties, HTML ids, JSON keys we author.
  - Exception: on-disk keys in existing `Config/*.json` files (`max_instances`, `place_id`, `displayName`, …) keep the names older builds wrote, so users' data keeps loading. `Storage.py` maps them.
  - Exception: HTML lowercases attribute names, so the select component uses `data-value`.
  - Exception: third-party names (`ph-bold`, `status_code`, pywebview's `events.loaded`) stay as they are.
- **PascalCase for folder and file names** too (`App/`, `Src/`, `Tests/`, `Tools/`, `Docs/`, `Config/Settings.json`, `RAMMIT.log`), with lowercase extensions.
  - Exception: tool-owned names stay lowercase: `dist/`, `build/`, `__pycache__/`, `__init__.py`, `requirements.txt`.
  - Exception: third-party file names stay as they are.
- Never put data into `innerHTML`; build nodes with `El()` / `textContent`. Only `TourData.js` bodies, which are static text written in the repo, are HTML.
- No inline `<script>` or `onclick=`: the CSP forbids them.
- API results are dicts with PascalCase keys; failures are `{"Error": "message for the user"}`.
- Never log, return or store a cookie, auth ticket or launch URI outside `Storage`/`Crypto`.

## Tests

```bash
python -m unittest discover -s Tests -p "Test*.py"
```

Backend unit tests: storage, migration, DPAPI, validation, launch URI, server picking, themes, server path checks, Api guarantees and theme drift.

```powershell
node Tests/TestUi.mjs <puppeteer-core node_modules dir> "C:\Program Files\Google\Chrome\Application\chrome.exe" <ScratchDir> [ScreenshotDir]
```

End-to-end UI tests: the real HTML/JS/CSS and the real Python `Api` + `LocalServer` (`Tests/UiHarness.py`), with Roblox, process launching, the registry and windows faked, in headless Chrome.

Not covered automatically: real Roblox login and launch, and the pywebview navigation guard. Test those by hand with a spare account.
