# Changelog

## 1.2.1 "Blessed Frank" (2026-11)

A security release: a second audit of the app, the installer, the release workflow and the website. Nothing changes in how RAMMIT is used. Details and what was checked: [SECURITY.md](SECURITY.md) › "1.2.1 audit".

- **Login window:** only a login cookie set by Roblox itself is saved. Before, a cookie with Roblox's name from any site the login window ended up on (a link on the page, a redirect) was accepted, so another site could get its own account saved in RAMMIT in place of yours.
- **Saved logins never follow a redirect.** Every request RAMMIT makes to Roblox now stops at the address it asked for, so a login can't travel on to wherever an answer points.
- **Installer:** the zip and its checksum are only downloaded from this repo's own releases (`github.com/CBlockDigital/RAMMIT/releases/download/...`). Before, any `github.com` link in the release list was accepted, so a list naming a file in someone else's repo, with a checksum that matched it, would have been installed. Links with a port or a user name in them are refused too.
- **Installer:** test mode's fake release server must be on this PC (`127.0.0.1` / `localhost`). Test mode is switched on with environment variables, which the released `RAMMIT-Setup.exe` reads as well; they can no longer point a download at a server on the network.
- **Local UI servers (app and installer):** the Content-Security-Policy is sent with every response, not only pages (an `.svg` opened on its own could run its own script), and idle connections are dropped after 15 seconds.
- **Themes:** a colour like `hsl(1.2.3, 5%, 5%)` in a theme's `Style.css` no longer stops RAMMIT from starting; that slot falls back to the default colour.
- A server list with a ping that isn't a number no longer fails the launch.
- **Installer:** a release list with odd contents (assets that aren't a list, a size that isn't a number) is skipped over instead of raising an error, and messages the page sends to `Setup.log` are always one line.
- **Release workflow draft** (`Production/Installer/Workflow/Release.yml`): the tag name is read from the environment instead of being pasted into the scripts, where a tag named like a command would have run with the job's write token.
- **Website:** a Content-Security-Policy (only the site's own files and the Google font load), and the version shown is 1.2.1.
- The version's code name is in `App/Version.py` (`AppCodeName`), the first line of `RAMMIT.log`, and the tooltip of the version line in Settings. The line itself still reads `RAMMIT v1.2.1 · Stable`.
- Custom themes: nothing to change. To get the code-name tooltip in a theme of your own, copy Dark's `JS\Main.js` into it.

## 1.2.0 (2026-11)

- **Installer:** the window no longer stays at the Loading screen's height. Grabbing or dragging the title bar while the screen changed undid the resize; a resize that arrives while the window is held now waits and is applied once when you let go. Two resizes sent close together could also finish in the wrong order and leave the window at the older height; they are now sent one at a time, and only the newest waiting one is sent, so the newest height always wins (#8).
- **Installer:** the window opens at the Loading screen's real height (`HeightMap.json` Loading 327 → 323), so it no longer shrinks a few pixels right after opening, and the space above and below the card is even.
- **Installer:** pressing **Ignore** on the "older test version" screen without ticking "Don't ask again" now puts it off instead of asking every time: the menu opens as normal, with an **OLD VERSION** button and a line saying where the old version is. It stays reachable after installing the new RAMMIT, and goes away once the old version is moved or removed.
- **Installer:** with RAMMIT already installed, the old version's screen keeps all four choices. The two "move my accounts" choices then copy its accounts and settings into the installed RAMMIT without reinstalling it, and the first one removes the old version afterwards.
- **Installer:** the "Uninstall Config/ folder too" tick box no longer shows its check mark while unticked (#2, fixed in #5 by ShahadatTest).
- **Installer:** you choose whether to get a **Desktop shortcut** and a **Start Menu shortcut** (both ticked by default), and the done screen says which were added. Updates, repairs and undo keep that choice instead of always recreating both.
- **Installer:** the update / repair / undo done screen has **LAUNCH RAMMIT** next to **CLOSE**, like the install done screen.
- **Shortcuts survive moving RAMMIT:** the installer's shortcuts (`RAMMIT.url`) now open the `RAMMIT:` protocol instead of naming RAMMIT's folder. If you move the RAMMIT folder by hand, open `RAMMIT.exe` from its new place once: it points the protocol, the installer's registry entry and the Settings > Apps entry at the new folder, and every RAMMIT shortcut works again, wherever you put it. A second copy started while the installed one is still in place changes nothing. Old `RAMMIT.lnk` shortcuts are replaced on the next install or update. Only a folder the installer made can take over (it has the installer's `Manifest.json`): a copy unzipped from a release, one on a USB stick and one started by the installer's test mode change nothing. Windows doesn't offer **Pin to taskbar** for these `.url` shortcuts as it did for the old `.lnk` ones: pin RAMMIT from its taskbar button while it runs instead. If the icon's path can't be written in the shortcut (a Windows user name with characters outside its code page), the shortcut shows the default icon.
- **Installer:** "don't ask again" for an old version is now stored as `LegacyInstallPath=Ignore` instead of a separate `IgnoreLegacyInstall` value (the old value is carried over).
- **Launch tracking:** RAMMIT now knows which Roblox client belongs to which account. It follows the process it started, including when Roblox hands the game to a child process that opens the window, and falls back to matching each launch's one-time ticket on the client's command line. An account shows "•••" while Roblox starts, "✓" only once its game window is open, and its mark clears when that window closes, so you can see which account closed. The running counter only counts open game windows: launches still starting count only towards Max Instances, and Roblox's tray process (started when a game closes) and its right-click menu no longer count at all. The status line under the launch button only says "Launched" once the accounts' windows are open (it stops waiting after 30 seconds). Each launch counts once towards Max Instances, also when the account already has a game open (its row shows "•••" until the new window is open); a launch whose window never shows stops counting after 10 minutes. If Roblox can't be started at all, the row shows the error instead of "•••". A client is still found by its ticket when it isn't a child of the process RAMMIT started (for example after a Roblox update), and a process number Windows reuses for another program is never taken for an account's client.
- **Expired logins** (back from the Test1 build): saved logins are checked at start-up and every 5 minutes, and an account whose login Roblox rejects turns red. With exactly that account selected, **+ ADD** becomes **RENEW** and **LAUNCH** becomes **RENEW AND LAUNCH**, which signs you in again first. Renewing keeps the account if the same Roblox user signs in (checked by user ID, so a renamed account still counts); a different user is added as a new account instead. A launch that Roblox rejects also marks the account. A check that can't reach Roblox never marks anything. The check sends each saved login only to Roblox (`users.roblox.com`), as a launch already does. Renewing an account that was renamed on Roblox keeps it selected under its new name, so **RENEW AND LAUNCH** launches it. An expired row stays readable in every theme, selected or not (a theme sets its text colour with `--OnExpired`).
- **Tooltips:** every button and setting has a tooltip, drawn in the theme's own colours instead of the plain Windows one. It follows the cursor and flips to the other side near the window's edges. CBlock's are rounded; a custom theme can set `--TooltipRadius`. A button that shows only an icon keeps its tooltip text as its name for screen readers, and a tooltip that is showing updates when its text changes (for example **+ ADD** turning into **RENEW**).
- The main window opens at its `HeightMap.json` height for the saved launch option, instead of opening shorter and resizing once the page has loaded.
- The main window and the config window keep the right height when you grab or drag their title bar while they resize: the resize waits and is applied when you let go (the same fix as the installer's). They also send their resizes one at a time, like the installer.
- The theme colour swatch next to the Theme drop-down has straight edges instead of jagged ones. `Tools/RenderTheme.py` draws its swatch the same way.
- **Themes:** the built-in themes list `"1.2"` in `SupportedVersions`. A theme you made for 1.0 or 1.1 opens in Dark after this update until you allow it, or add `"1.2"` to its `Theme.json`. To get the red expired rows, RENEW and the tooltips in it, copy Dark's `HTML\`, `JS\` and the LAYOUT part of `CSS\Style.css` into it. New colour variables: `--OnExpired`, and `--TooltipRadius` (optional).

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
