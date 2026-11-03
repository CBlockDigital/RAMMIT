# Changelog

## 1.1.2 (2026-11)

- **Installer:** the window no longer stays at the Loading screen's height. Grabbing or dragging the title bar while the screen changed undid the resize; a resize that arrives while the window is held now waits and is applied once when you let go.
- **Installer:** the window opens at the Loading screen's real height (`HeightMap.json` Loading 327 → 323), so it no longer shrinks a few pixels right after opening, and the space above and below the card is even.
- **Installer:** pressing **Ignore** on the "older test version" screen without ticking "Don't ask again" now puts it off instead of asking every time: the menu opens as normal, with an **OLD VERSION** button and a line saying where the old version is. It stays reachable after installing the new RAMMIT, and goes away once the old version is moved or removed.
- **Installer:** with RAMMIT already installed, the old version's screen keeps all four choices. The two "move my accounts" choices then copy its accounts and settings into the installed RAMMIT without reinstalling it, and the first one removes the old version afterwards.
- **Installer:** the "Uninstall Config/ folder too" tick box no longer shows its check mark while unticked (#2).
- **Tooltips:** every button and setting has a tooltip, drawn in the theme's own colours instead of the plain Windows one. It follows the cursor and flips to the other side near the window's edges. CBlock's are rounded; a custom theme can set `--TooltipRadius`.
- The main window opens at its `HeightMap.json` height for the saved launch option, instead of opening shorter and resizing once the page has loaded.
- The main window and the config window keep the right height when you grab or drag their title bar while they resize: the resize waits and is applied when you let go (the same fix as the installer's).
- The theme colour swatch next to the Theme drop-down has straight edges instead of jagged ones.

## 1.1.1 (2026-11)

- **Installer:** uninstalling now removes the Desktop and Start Menu shortcuts even when Windows writes the folder with its short name (e.g. `C:\Users\JOHNSM~1\...` instead of `C:\Users\John Smith\...`). Before, the shortcuts were left behind in that case.
- The project is open source under the GPL-3.0, with CI, a contributing guide and issue templates on GitHub.

## 1.1.0 (2026-11)

- **Installer:** `RAMMIT-Setup.exe`, one file you download and run. It can:
  - install, update, repair and uninstall RAMMIT from this repo's releases;
  - switch to any version and undo the last change;
  - move accounts over from an old test install.
  - It lives in `Production/Installer`.
- The built-in themes list `"1.1"` in `SupportedVersions`.
- `Build.ps1` writes the `.sha256` file with an LF line ending, so `sha256sum -c` works on Linux and macOS too.

## 1.0.0 (2026-11)

First release on the new main line. It was tested as "QA Beta" (2026.11-QABeta) before release.

- Version numbers are now `x.y.z`, defined only in `App/Version.py`.
- The footer under Settings shows the version and channel: `RAMMIT v1.0.0 · Stable`. Test builds (`Build.ps1 -Channel Dev`) show `· Dev` plus the git commit.
- `Build.ps1` writes `RAMMIT-<version>.zip` and a `.sha256` file next to it.

### Security
Full audit; details in [SECURITY.md](SECURITY.md).
- Saved logins encrypted with DPAPI, with automatic migration.
- XSS fixed and a strict CSP added.
- Navigation guard for privileged windows.
- Validated bridge inputs and a hardened local server.
- Binary-planting fix, atomic config writes, request timeouts.

### New
- **Custom themes.** Every theme is a complete UI folder in `Src/` (`Dark`, `Light` = 2016 Roblox, `MyCustomTheme` example).
  - Each folder has its own `HeightMap.json` (`MainWindow`, `WizardWindow`).
  - The theme picker shows colour swatches and has reload and open-folder buttons.
  - Problems with a theme appear as warnings under the picker.
- Tutorial "Making your own theme" (in-app) plus `HowToMakeATheme.txt`.
- `Tools/RenderTheme.py`: headless preview picture (thumbnail sheet) of any theme.
- Confirmation before removing accounts.
- Clear message when Roblox was opened before RAMMIT (multi-instance unavailable).
- Version shown in Settings; log file `Config/RAMMIT.log`.

### Packaging
- Folder build (`RAMMIT.exe` + `Runtime\`) instead of one self-extracting exe, with version info and no UPX:
  the one-file build was quarantined by Defender as `Behavior:Win32/DefenseEvasion.A!ml` (false positive).
- Window heights tuned per launch option so the Settings card (and version line) is identical on every option.
- Config wizard uses Test1's tuned per-method heights and sizing logic (`HeightMap.json` › `WizardWindow`).

### Added
- **CBlock theme** (`Src\CBlock`): the CBlock website look. It has the same layout as Dark, with black and near-black panels, one violet accent (`#5d1fa9`) and thin indigo rings. Fields use the site's `.Field` style. Buttons follow the site: `.Btn.Filled` for the main actions (LAUNCH, CONFIRM) and outlined `.Btn` for the secondary ones (ADD, EDIT, REMOVE, CANCEL), each inverting on hover. Panel titles are uppercase and use a lighter violet for readability. Sizes are unchanged, so the height map holds.

### Changed
- Launchers: **Fishstrap** replaces Voidstrap (Roblox / Bloxstrap / Fishstrap, as in Test1). A saved "Voidstrap" setting falls back to Roblox.
- Theme picker: one colour swatch next to the drop-down (a square split into 4: panel, accent, background, text), as tall as the picker; the open list keeps the full width and every row's swatch and name line up under the active ones. Colours are read from each theme's own Style.css.
- Swatch colours: 4 fixed slots that never shift; comments ignored; `var()` references followed; named colours accepted; any unreadable slot shows Dark's colour (with a note under the Theme list). Themes with renamed variables can point at them in `Theme.json` › `"Swatch"`.
- Config wizard heights evened out: every method leaves the same ~4.4-5 px under the error line (Home 288, VIP Link 354, ExtraPadding 22).

### Removed
- "Multi Instance Method" drop-down and its `multi_method` setting. RAMMIT always uses pywin32 and psutil together.

### Fixed
See "Functional bugs fixed" in SECURITY.md.

### Internal
- `web.py` (736 lines) split into the `App/` package.
- The inline scripts in both pages (about 1,400 lines) split into ES modules; the launch form is shared by both windows.
- PascalCase naming throughout.
- `Tools/SyncThemes.py` added.
- Test suites added: 34 backend unit tests and 66 end-to-end UI checks.
- `Build.ps1` one-step build and package.
