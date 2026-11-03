"""Starts RAMMIT: logging -> multi-instance lock -> local UI server -> main window."""
import os

import webview

from App import MultiInstance, Paths, Themes
from App.Splash import SplashScreen
from App.Api import Api, GuardNavigation
from App.LocalServer import LocalServer
from App.Log import Logger, Setup as SetupLog
from App.Version import VersionLabel

WindowWidth, WindowScale = 900, 0.85


def StartHeight(Bridge):
    """Opening height from this theme's HeightMap.json for the saved launch option, so the window opens at
    the right size. The page still resizes on boot (it alone can measure a theme note)."""
    Map = Themes.LoadHeightMap(Bridge._ActiveThemeId())[0]["MainWindow"]
    Settings = Bridge._Settings
    Height = Map.get(Settings.get("LaunchOption"), Map["Home"])
    if (Settings.get("LaunchParams") or {}).get("PlayerMode") in ("min_only", "max_only", "range"):
        Height += Map["PlayerFilterExtra"]
    return max(400, min(Height, 1400))  # same limits as Api.ResizeWindow


def Run():
    SetupLog()
    Logger.info("RAMMIT %s starting from %s", VersionLabel(), Paths.BaseDir)
    os.chdir(Paths.BaseDir)
    Paths.EnsureConfigDir()
    MultiInstance.Enable()

    Bridge = None
    Server = LocalServer(lambda: Bridge._ActiveThemeId() if Bridge else "Dark").Start()
    Bridge = Api(Server)

    Window = webview.create_window(
        "Roblox Account Manager and Multi Instance Tool",
        url=Server.Url("Index.html"),
        js_api=Bridge,
        width=int(WindowWidth * WindowScale),
        height=int(StartHeight(Bridge) * WindowScale),
        resizable=False,
        background_color=Themes.BackgroundColor(Bridge._ActiveThemeId()),
    )
    Bridge._AttachMainWindow(Window)
    # "RAMMIT is starting" spinner over the window until the page reports it has booted (Api.BootFinished).
    Theme = Bridge._ActiveThemeId()
    Bridge._Splash = SplashScreen(Foreground=Themes.AccentColor(Theme), Background=Themes.BackgroundColor(Theme))
    Bridge._Splash.Attach(Window)
    GuardNavigation(Window, Server, "Index.html")

    def OnMainClosed():
        # Closing the main window closes the login / config windows too, so nothing lingers.
        for Other in list(webview.windows):
            if Other is not Window:
                Bridge._DestroyQuietly(Other)
    Window.events.closed += OnMainClosed

    Bridge._StartLoginChecks()  # expired saved logins turn red (first check now, then every few minutes)
    webview.start()
    Server.Stop()
    Logger.info("RAMMIT closed")
