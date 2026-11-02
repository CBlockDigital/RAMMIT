# Custom themes: how they work (developer view)

The end-user tutorial is [HowToMakeATheme.txt](HowToMakeATheme.txt). It ships next to RAMMIT.exe and is also the in-app tour "Making your own theme" (`Src/<Theme>/JS/TourData.js`). This page covers what happens underneath.

## Model

A theme is a complete UI folder: `Src/<ThemeId>/`. The folder name is the id stored in `Config/Settings.json` (`"theme"`).

```
Src/Dark/
  HTML/Index.html, Wizard.html     page markup (no inline scripts or handlers)
  JS/*.js                          ES modules (see README.md, "Frontend")
  CSS/Style.css                    [theme variables] [LAYOUT] [THEME EXTRAS]
  CSS/Phosphor-Bold.css, Fonts/    icon font
  RAMMIT.png, *.ico                icons
  Theme.json                       {"Name", "Author", "Description", "SupportedVersions", "Swatch"} - all optional
  HeightMap.json                   window sizes, see below
```

- `App/LocalServer.py` serves **only** the active theme folder as the web root and looks it up on every request. Switching themes saves the setting and reloads the window (`JS/Themes.js`).
- `App/Themes.py` decides what counts as a theme: a folder in `Src/` whose name matches `IdPattern` and that contains `HTML/Index.html`. The only fallback is whole-theme: if the chosen folder is missing or broken, Dark is served. Files are never mixed between themes.
- **Supported versions.** `Theme.json` › `"SupportedVersions"` lists the RAMMIT versions a theme was made for.
  - Entry formats: `"1.0"` (any 1.0.x), `"1.0.2"` (exact), `"1.2+"` (that version or newer). Parsed by `Themes.ParseSupportedVersions`, matched against `App/Version.py` by `Themes.SupportsVersion`.
  - **Picking** a theme that doesn't list this version: `JS/Themes.js` shows the version dialog first. Use it anyway → `Api.AllowThemeVersion(Id, Remember)`.
  - **Starting** with such a theme chosen (e.g. after a RAMMIT update): `Api._ActiveThemeId` serves Dark until it's allowed, because the theme's own JS may not work with this version. `GetThemes()["Blocked"]` names it, and the dialog offers *Use it anyway* or *Stay on Dark*; Stay on Dark saves Dark as the choice.
  - Allowed means "this theme with this RAMMIT version": `ThemeId@AppVersion`. It's kept for the run, or in Settings `ThemeVersionOk` when "Don't ask again" is ticked, so the next RAMMIT version asks again.
  - No field: never asks, but a note under the Theme list says so (`ThemeWarnings`).
- **Note line height.** Any note under the Theme list (`#ThemeWarning`) adds exactly its own height to the main window: `Themes.js ThemeNoteExtra()` measures how far the next row moves when the note shows, divides by the page zoom, and `Launch.js ResizeForCurrentOption` adds it on top of `HeightMap.json`. It's measured in CSS pixels, so it doesn't depend on Windows display scaling.
- The colour swatch (Theme picker) has 4 fixed slots: Background, Card, Accent, Text (`Themes._Swatch`).
  - Each slot is looked up in this order:
    1. the theme's `CSS/Style.css` variable of the same name (`--Background`, …);
    2. if that's missing or not a colour, the variable `Theme.json` links it to: `"Swatch": {"Accent": "--Brand"}`;
    3. otherwise Dark's colour for that slot.
  - Comments are stripped first, and `var(--X[, fallback])` chains are followed.
  - Accepted values: hex, `rgb()`/`rgba()`/`hsl()`/`hsla()`, and named colours.
  - Any slot that can't be read takes **Dark's** colour for that slot, and the order never shifts. A note appears under the Theme list (`ThemeWarnings`).
- **Start-up spinner** (`App/Splash.py`): a native WinForms overlay drawn before the page exists, so theme HTML/CSS can't style it. Its colours come from the swatch slots:
  - arc = slot 2 (Accent), via `Themes.AccentColor`;
  - background = slot 0 (Background), via `Themes.BackgroundColor`, which is also each window's `background_color` (no white flash on open).

  `Theme.json` › `"Swatch"` pointers therefore recolour it too. Both slots are converted to `#rrggbb` by `Themes._ToHex`, which accepts hex, `rgb()`/`rgba()`, `hsl()`/`hsla()` and CSS colour names (looked up in .NET's table, Windows system colours excluded, plus `rebeccapurple`). The swatch only accepts names that convert, so the loader always shows exactly the swatch's colours. Shape and timing (30% arc, 0.5 s per turn, 0.2 s hold + 0.3 s fade, 15 s safety timeout, about 60 fps) are fixed in `Splash.py`.

## HeightMap.json

Loaded and validated by `Themes.LoadHeightMap()`. If an entry is missing or invalid, the default is used and a warning appears under the Theme drop-down.

| Key | Used by | Meaning |
|---|---|---|
| `MainWindow.<Launch Option>` | `JS/Launch.js` → `Api.ResizeWindow` | Main window height (logical px, before the 0.85 UI scale) for `Home`, `Config`, `Game URL`, `Place ID`, `Place ID + Job ID`, `VIP Link` |
| `MainWindow.PlayerFilterExtra` | `JS/Launch.js` | Added while the Min/Max player boxes are visible |
| `WizardWindow.Width` | `Api.OpenConfigWizard`, `Api.ResizeWizard` | Width of the Add/Edit Config window |
| `WizardWindow.<Method>` | `Api.OpenConfigWizard`, `JS/Wizard.js` | Wizard height for `Home`, `Game URL`, `Place ID`, `Place ID + Job ID`, `VIP Link`: it opens at, and snaps to, this height (Test1's tuned values) |
| `WizardWindow.ExtraPadding` | `JS/Wizard.js` | Added under the content when the wizard re-measures (filters, drop-downs, help panel) |

## Shared code across the built-in themes

The built-in themes (Dark, Light, CBlock, MyCustomTheme) are full copies, so a code change has to reach all four. Make the change in `Src/Dark`, then run:

```bash
python Tools/SyncThemes.py
```

The script copies `HTML/`, `JS/`, `Fonts/`, the icons and the **LAYOUT** section of `Style.css`. Each theme's variables, its THEME EXTRAS section, `Theme.json` and `HeightMap.json` are left alone. `--check` only reports drift; the unit tests and `Build.ps1` both run it. User-made themes are never synced automatically.

## Preview pictures

`Tools/RenderTheme.py <ThemeId> [...]` (or `--from <folder>` for a theme outside `Src/`) writes `ThemeRenders/<ThemeId>.png`: main window at its Home height, the open Theme list, + ADD on hover and the wizard (Game URL) sized like `Wizard.js` does. How it works:

- It starts `Tests/UiHarness.py` in a temp folder (fake demo accounts, never the real `Config/`).
- It drives Edge or Chrome with `--headless=new` (no window) over a small stdlib DevTools client, using a `window.pywebview` fetch shim.
- It lays the sheet out as an HTML page in the same browser, so no image library is needed.

Windows lose 36.7 logical px to the title bar (measured at 150 %), and the captures subtract it.

## Security notes

- A theme can contain JavaScript, so a theme is trusted code. It runs with the same bridge access as RAMMIT's own UI. That bridge never returns cookies or tickets, and all inputs are validated in Python.
- The CSP (`LocalServer.ContentSecurityPolicy`) blocks remote scripts, styles, fonts, images and connections, so a theme cannot pull anything from the internet or send anything out.
- Theme ids are restricted by regex and resolved with `Paths.IsInside`, so `../` cannot escape `Src/`.
