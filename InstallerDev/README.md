# RAMMIT-Setup (installer prototype)

The installer for RAMMIT, built outside `Production/` until it is ready. The design is `../Docs/InstallerPlan.md`; the look is Test1's installer (same screens, CSS, wording and slide transitions), with new screens built from the same components.

`RAMMIT-Setup.exe` is one self-contained file: the page, CSS, JS, icon font and icons are embedded and served from memory, so it works on a PC that has never had RAMMIT.

## Layout

```
Installer/
  Installer.py        entry: single instance, in-memory UI server, window, native spinner, /Uninstall
  InstallerApi.py     the JS bridge (validated inputs, {"Error": ...} results, all state _private)
  Releases.py         GitHub Releases: list, download, SHA-256 check (no token). ReleaseRepo = "OWNER/RAMMIT" (TODO)
  Setup.py            install/update/downgrade/repair/undo/uninstall: staging, manifest, swap + rollback,
                      Config backups, kept accounts, registry, Apps entry, shortcuts, Undo cache, "RAMMIT is running"
  Legacy.py           old Test1 installs: detect, move accounts, remove, ignore
  Locations.py        every folder and registry key; test mode
  UiServer.py         127.0.0.1 server for the embedded UI (Host check, allowlist, CSP)
  Splash.py, Log.py, Paths.py   copied/adapted from RAMMIT's App/
  HeightMap.json      start heights only (the page measures itself after that)
  Ui/HTML/Installer.html, Ui/CSS/Installer.css (Test1's CSS + additions), Ui/CSS/Phosphor-Bold.css,
  Ui/Fonts/Phosphor-Bold.woff2, Ui/JS/{Installer,Screens,VersionPicker,Bridge,Dom}.js
  RAMMIT-Downloader.ico/.png    the exe + window icon
Installer.spec        PyInstaller one-file build -> dist/RAMMIT-Setup.exe
Tests/                TestInstaller.py (unit), TestEndToEnd.py, UiHarness.py + TestUi.mjs (every screen), SmokeExe.py
Workflow/Release.yml  GitHub Actions draft (moves to .github/workflows/ later)
Screenshots/          written by TestUi.mjs and SmokeExe.py
```

## Test mode (use it for every manual run)

```powershell
$env:RAMMIT_INSTALLER_TEST = "1"     # registry: HKCU\Software\CBlock Digital\RAMMIT-InstallerTest
                                     # Apps list: ...\Uninstall\RAMMIT-InstallerTest
                                     # folders:   %TEMP%\RAMMIT-InstallerTest\{Desktop,StartMenu,LocalAppData}
$env:RAMMIT_INSTALLER_RELEASES_URL = "http://127.0.0.1:<port>/repos/OWNER/RAMMIT/releases"   # fake server (test mode only)
python Installer\Installer.py
```

Optional overrides: `RAMMIT_INSTALLER_REGKEY`, `RAMMIT_INSTALLER_UNINSTALL_NAME`, `RAMMIT_INSTALLER_TEST_ROOT`. Test mode refuses to start if any of them points at the real names. Remove the test keys afterwards (`Remove-Item "HKCU:\Software\CBlock Digital\RAMMIT-InstallerTest"`, and the matching Uninstall key).

## Tests and build

```powershell
python -m pyflakes Installer Tests
python -m unittest discover -s Tests -p "Test*.py"
node Tests\TestUi.mjs <puppeteer-core node_modules dir> "C:\Program Files\Google\Chrome\Application\chrome.exe" <ScratchDir> <ScreenshotDir>
python -m PyInstaller Installer.spec --noconfirm --clean --distpath dist --workpath "$env:TEMP\RammitSetupBuild"
python Tests\SmokeExe.py dist\RAMMIT-Setup.exe Screenshots\00-RealExeWindow.png
& "C:\Program Files\Windows Defender\MpCmdRun.exe" -Scan -ScanType 3 -File dist\RAMMIT-Setup.exe -DisableRemediation
```

The UI harness wipes `<ScratchDir>`, so keep the screenshot folder elsewhere. The installer version comes from RAMMIT's `App/Version.py` (`RAMMIT_VERSION_FILE`, default `../Production/RAMMIT-Stable/App/Version.py`).

## Behaviour worth knowing

- Installs only into a folder that is missing, empty, its own install (`Manifest.json`), what its own uninstall left (`Config`, `Config.Backup`, or a `RAMMIT-Uninstalled.json` marker), or the Test1 folder when "move + remove" was chosen. Anything else: "pick an empty folder".
- Every install, update, repair, version change and undo uses the same path: verified zip -> `<Install>.Staging` -> swap with rollback. Files the old manifest doesn't list (Config, backups, custom themes) are carried across.
- Uninstall deletes manifest files only (+ `Config` and `Config.Backup` when ticked).
- The setup copy and Undo cache live in `%LOCALAPPDATA%\RAMMIT-Setup\`, outside the install folder.
- **Update / Downgrade** is one screen: every release newest first, the installed one greyed out, the button says UPDATE or DOWNGRADE for the pick (UP TO DATE, disabled, when nothing newer is picked). Undo last change sits on the same screen.
- **Branches:** a normal GitHub release is Stable (`S` in the picker), a pre-release is Dev (`D`, amber; shown with "Show dev versions"). Hover a letter for the name. The installed branch is stored in `Manifest.json` (`Branch`).
- **What an uninstall leaves behind.** Everything removed: nothing (no registry key, no empty `HKCU\Software\CBlock Digital`, no `RAMMIT-Setup\`; a running `RAMMIT-Setup.exe` can't be deleted, so it is renamed into `%TEMP%` after the window closes). Config kept: the folder with `Config\` (+ `Config.Backup\`) and one registry value, `KeptConfigPath`.
- **Installing again after Config was kept** (anywhere, any time): the menu says where the accounts are, the install folder defaults to that folder, and "Bring back my saved accounts" (ticked) moves them into whichever folder is picked; unticked puts them aside in `Config.Backup\Earlier-<time>\` (same folder) or leaves them where they are (other folder). A clash with accounts already in the target asks which set to keep; the other goes to `Config.Backup\`. Test1's own kept-Config values (`ConfigPath`, `CleanupPath`) are found and cleaned the same way. A pointer to a folder deleted by hand is forgotten.
