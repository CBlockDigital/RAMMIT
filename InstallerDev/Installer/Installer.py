"""RAMMIT-Setup: installs, updates/downgrades, repairs and uninstalls RAMMIT.

Start-up: logging -> single-instance check -> in-memory UI server -> window (+ native spinner until the page
has booted). Everything the window shows is embedded in this program (see UiServer.py), so it works on a PC
that has never had RAMMIT.

    RAMMIT-Setup.exe               the menu (install, or update/downgrade, repair, uninstall)
    RAMMIT-Setup.exe /Uninstall    opens straight at "Uninstall" (Settings > Apps runs this)

Set RAMMIT_INSTALLER_TEST=1 to run against throw-away registry keys and folders (see Locations.py).
"""
import ctypes
import json
import os
import sys

import webview

import Locations
import Paths
import Setup
from InstallerApi import InstallerApi, InstallerVersion, WindowWidth
from Log import Logger, Setup as SetupLog
from UiServer import LoadEmbeddedUi, UiServer


def _SingleInstance():
    """True if this is the only running installer (a second one would fight over the same folders)."""
    import win32api
    import win32event
    import winerror
    Name = "RAMMIT-Setup-SingleInstance" + ("-Test" if Locations.Current.TestMode else "")
    _SingleInstance.Handle = win32event.CreateMutex(None, False, Name)  # kept alive for the process lifetime
    return win32api.GetLastError() != winerror.ERROR_ALREADY_EXISTS


def _StartHeight(Screen):
    """Start size from HeightMap.json; the page measures itself and corrects it straight away."""
    try:
        with open(os.path.join(Paths.BundleDir(), "HeightMap.json"), encoding="utf-8") as File:
            Map = json.load(File)
        return int(Map.get(Screen) or Map["Loading"])
    except (OSError, ValueError, KeyError, TypeError):
        return 300


def GuardNavigation(Window, Server, Page):
    """pywebview injects the full js_api into whatever page a window shows, so the window must never stay on
    anything but the embedded UI. Send it straight back if it leaves (same as RAMMIT's Api.GuardNavigation)."""
    def OnLoaded():
        try:
            Url = Window.get_current_url() or ""
        except Exception:
            return
        if not Url.startswith(Server.Origin + "/"):
            Logger.warning("Blocked navigation away from the installer UI")
            Window.load_url(Server.Url(Page))
    Window.events.loaded += OnLoaded


def Main():
    SetupLog()
    StartScreen = "ConfirmUninstall" if any(Arg.lower() in ("/uninstall", "--uninstall") for Arg in sys.argv[1:]) else ""
    Logger.info("RAMMIT-Setup %s starting (test mode: %s)", InstallerVersion, Locations.Current.TestMode)
    if not _SingleInstance():
        ctypes.windll.user32.MessageBoxW(None, "RAMMIT Setup is already open.", "RAMMIT Setup", 0x40)
        return

    Server = UiServer(LoadEmbeddedUi(Paths.BundleDir())).Start()
    Bridge = InstallerApi(StartScreen)
    Bridge._LastHeight = _StartHeight(StartScreen or "Loading")
    Window = webview.create_window(
        "RAMMIT Installer" + (" (test mode)" if Locations.Current.TestMode else ""),
        url=Server.Url("Installer.html"),
        js_api=Bridge,
        width=WindowWidth,
        height=Bridge._LastHeight,
        resizable=False,
        background_color="#0a0a0a",
    )
    Bridge._AttachWindow(Window)
    try:
        from Splash import SplashScreen
        Bridge._Splash = SplashScreen(Foreground="#0078d4", Background="#0a0a0a")  # Test1's splash colours
        Bridge._Splash.Attach(Window)
    except Exception as Error:
        Logger.warning("No start-up spinner: %s", type(Error).__name__)
    GuardNavigation(Window, Server, "Installer.html")
    Icon = os.path.join(Paths.BundleDir(), "RAMMIT-Downloader.ico")
    webview.start(icon=Icon if os.path.isfile(Icon) else None)
    Server.Stop()
    Logger.info("RAMMIT-Setup closed")
    Setup.FinishOnExit()


if __name__ == "__main__":
    Main()
