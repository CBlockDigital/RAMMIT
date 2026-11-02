"""Starts RAMMIT: logging -> multi-instance lock -> local UI server -> main window."""
import os

import webview

from App import MultiInstance, Paths, Themes
from App.Splash import SplashScreen
from App.Api import Api, GuardNavigation
from App.LocalServer import LocalServer
from App.Log import Logger, Setup as SetupLog
from App.Version import VersionLabel

WindowWidth, WindowHeight, WindowScale = 900, 700, 0.85


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
        height=int(WindowHeight * WindowScale),
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

    webview.start()
    Server.Stop()
    Logger.info("RAMMIT closed")
