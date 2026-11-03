"""The installer's JavaScript bridge: every public method here is callable from the page as
`window.pywebview.api.<MethodName>(...)` (see Ui/JS/Bridge.js).

Rules (the same as RAMMIT's App/Api.py):
  * Treat every argument as untrusted and validate it.
  * Keep ALL state in "_"-prefixed attributes. pywebview exposes every public attribute to the page,
    including nested objects such as the window.
  * Return plain dicts with PascalCase keys; errors are {"Error": "message for the user"}, never exceptions.

Long jobs (install, update, ...) run on one worker thread at a time and report back through
window.InstallerEvents.<Event>(payload): Progress / UninstallProgress (Test1's progress fields),
Done (the result) and Failed ({Message, Details, Running}).
"""
import ctypes
import ctypes.wintypes
import json
import os
import threading
import traceback

import webview

import Legacy
import Locations
import Releases
import Setup
from Log import Logger

WindowWidth = 560
SwpNoMove, SwpNoZOrder, SwpNoActivate = 0x2, 0x4, 0x10
Events = ("Progress", "UninstallProgress", "Done", "Failed")
LegacyModes = ("", "MoveRemove", "MoveKeep")
ConfigChoices = ("", "KeepNew", "UseOld")
KeptChoices = ("", "Use", "Fresh")

try:
    from BuildInfo import InstallerVersion
except ImportError:
    InstallerVersion = "dev"


class InstallerApi:
    def __init__(self, StartScreen=""):
        self._Window = None
        self._Splash = None
        self._StartScreen = StartScreen
        self._JobLock = threading.Lock()
        self._Busy = False
        self._Releases = None
        self._LastHeight = 0  # Installer.py sets the start height
        self._Frame = None
        self._Resized = False
        self._Dragging = False
        self._LastPath = ""

    # ------------------------------------------------------------ wiring (Installer.py)

    def _AttachWindow(self, Window):
        self._Window = Window
        if hasattr(Window, "events"):  # the tests' stand-in window has none
            Window.events.shown += self._WatchDrags

    def _WatchDrags(self):
        """Grabbing or dragging the title bar starts Windows' move loop, which keeps the size the window had when it
        began: a resize sent meanwhile is undone (it only flickers). So while the window is held, ResizeInstaller just
        records the height, and when the loop ends (ResizeEnd fires for moves too) it is applied once."""
        try:
            Native = self._Window.native
            Native.ResizeBegin += lambda _Sender, _Args: setattr(self, "_Dragging", True)
            Native.ResizeEnd += self._OnLetGo
        except Exception as Error:
            Logger.warning("Can't watch window drags: %s", type(Error).__name__)

    def _OnLetGo(self, _Sender, _Args):
        self._Dragging = False
        threading.Thread(target=self._ReapplyHeight, daemon=True).start()

    def _ReapplyHeight(self):
        Window, Target = self._Window, self._LastHeight
        if not Window or not Target:
            return
        try:
            Native = Window.native
            Scale = self._WindowScale(Native)
            if abs(Native.Height / Scale - Target) >= 2:
                self._SetHeight(Native, round(Target * Scale))
        except Exception:
            pass

    @staticmethod
    def _WindowScale(Native):
        """The window's real DPI scale. Not Form.DeviceDpi: pywebview's SetProcessDPIAware leaves that at 96."""
        return max(1.0, ctypes.windll.user32.GetDpiForWindow(ctypes.wintypes.HWND(Native.Handle.ToInt64())) / 96.0)

    @staticmethod
    def _SetHeight(Native, PhysicalHeight):
        """Size only (SWP_NOMOVE): pywebview's resize also writes a position read a moment ago, which drags the
        window back if it is still moving."""
        Hwnd = ctypes.wintypes.HWND(Native.Handle.ToInt64())
        Rect = ctypes.wintypes.RECT()
        ctypes.windll.user32.GetWindowRect(Hwnd, ctypes.byref(Rect))
        ctypes.windll.user32.SetWindowPos(Hwnd, None, 0, 0, Rect.right - Rect.left, PhysicalHeight, SwpNoMove | SwpNoZOrder | SwpNoActivate)

    def _Emit(self, Event, Payload):
        """window.InstallerEvents.<Event>(Payload). Payload is JSON-encoded, never spliced raw."""
        Window = self._Window
        if not Window or Event not in Events:
            return
        try:
            Window.evaluate_js(f"window.InstallerEvents && window.InstallerEvents.{Event}({json.dumps(Payload)})")
        except Exception as Error:
            Logger.warning("Could not notify the page (%s): %s", Event, type(Error).__name__)

    def _Progress(self, StageLabel=None, StagePct=None, StageDetail=None, OverallPct=None, ActiveStage=None):
        Data = {}
        if StageLabel is not None:
            Data["StageLabel"] = StageLabel
        if StagePct is not None:
            Data["StagePct"] = max(0, min(100, int(StagePct)))
        if StageDetail is not None:
            Data["StageDetail"] = StageDetail
        if OverallPct is not None:
            Data["OverallPct"] = max(0, min(100, int(OverallPct)))
        if ActiveStage is not None:
            Data["Stages"] = {"Active": int(ActiveStage)}
        self._Emit("Progress", Data)

    def _UninstallProgress(self, Label=None, Pct=None, ActiveStage=None):
        Data = {}
        if Label is not None:
            Data["Label"] = Label
        if Pct is not None:
            Data["Pct"] = max(0, min(100, int(Pct)))
        if ActiveStage is not None:
            Data["Stages"] = {"Active": int(ActiveStage)}
        self._Emit("UninstallProgress", Data)

    def _StartJob(self, Action, Job):
        """Runs Job() on a worker thread; its dict result goes to Done, a failure to Failed."""
        with self._JobLock:
            if self._Busy:
                return {"Error": "The installer is already busy. Wait for it to finish."}
            self._Busy = True

        def Worker():
            try:
                Result = Job()
                Result["Action"] = Action
                self._Emit("Done", Result)
            except (Setup.SetupError, Releases.ReleaseError) as Error:
                Logger.warning("%s failed: %s | %s", Action, Error, getattr(Error, "Details", ""))
                self._Emit("Failed", {"Action": Action, "Message": str(Error), "Details": getattr(Error, "Details", ""),
                                      "Running": bool(getattr(Error, "Running", False))})
            except Exception as Error:
                Logger.error("%s crashed: %s", Action, traceback.format_exc(limit=6))
                self._Emit("Failed", {"Action": Action, "Message": "Something unexpected went wrong. Nothing was left half-installed.",
                                      "Details": f"{type(Error).__name__}: {Error}", "Running": False})
            finally:
                with self._JobLock:
                    self._Busy = False
        threading.Thread(target=Worker, name="InstallerJob", daemon=True).start()
        return {"Ok": True}

    # ------------------------------------------------------------ state

    def BootFinished(self):
        """Called by the page once it has drawn its first screen: fades out the start-up spinner."""
        if self._Splash:
            self._Splash.Dismiss()

    def GetState(self):
        State = Setup.InstalledState()
        LegacyInfo = Legacy.Detect()  # also when installed: an old version put off with Ignore stays on the menu
        Kept = None if State["Installed"] or LegacyInfo else Setup.FindKeptConfig()
        DefaultPath = State["Path"] or (Kept["Path"] if Kept and Kept["Installable"] else Locations.Current.DefaultInstallPath)
        return {
            "Installed": State["Installed"],
            "Version": State["Version"],
            "Branch": State["Branch"],
            "Path": State["Path"],
            "DefaultPath": DefaultPath,
            "Legacy": {"Path": LegacyInfo["Path"], "Version": LegacyInfo["Version"], "Deferred": LegacyInfo["Deferred"]}
                      if LegacyInfo else None,
            "KeptConfig": {"Path": Kept["Path"], "Accounts": Kept["Accounts"], "Test1": Kept["Test1"]} if Kept else None,
            "UndoVersion": Setup.UndoVersion(State["Version"]) if State["Installed"] else "",
            "StartScreen": "ConfirmUninstall" if self._StartScreen == "ConfirmUninstall" and State["Installed"] else "",
            "TestMode": Locations.Current.TestMode,
            "InstallerVersion": InstallerVersion,
        }

    def ListVersions(self, IncludeTest=False, Refresh=False):
        """{Versions: [{Version, Branch, Prerelease, Latest, Installed, Published}], Latest, UpdateAvailable} or {Error, Details}."""
        if not isinstance(IncludeTest, bool) or not isinstance(Refresh, bool):
            return {"Error": "Bad request."}
        try:
            if self._Releases is None or Refresh:
                self._Releases = Releases.FetchReleases()
        except Releases.ReleaseError as Error:
            return {"Error": str(Error), "Details": Error.Details}
        Latest = Releases.LatestStable(self._Releases)
        LatestVersion = Latest["Version"] if Latest else ""
        Shown = [R for R in self._Releases if IncludeTest or not R["Prerelease"]]
        Installed = Setup.InstalledState()
        Key = Releases.ParseVersion(Installed["Version"]) if Installed["Installed"] else None
        return {
            "Versions": [{"Version": R["Version"], "Branch": R["Branch"], "Prerelease": R["Prerelease"],
                          "Latest": R["Version"] == LatestVersion,
                          "Installed": Installed["Installed"] and R["Version"] == Installed["Version"],
                          "Published": R["Published"]} for R in Shown],
            "Latest": LatestVersion,
            "UpdateAvailable": bool(Latest and Key is not None and Releases.ParseVersion(LatestVersion) > Key),
        }

    def _Release(self, Version):
        if not isinstance(Version, str) or Releases.ParseVersion(Version) is None:
            raise Setup.SetupError("Pick a version from the list.")
        if self._Releases is None:
            self._Releases = Releases.FetchReleases()
        Release = Releases.FindRelease(self._Releases, Version)
        if not Release:
            raise Setup.SetupError(f"Version {Version} isn't available any more. Pick another one.")
        return Release

    # ------------------------------------------------------------ checks before a job

    def BrowseFolder(self):
        Window = self._Window
        if not Window:
            return None
        try:
            Result = Window.create_file_dialog(webview.FileDialog.FOLDER)
        except Exception:
            return None
        if Result and len(Result) > 0:
            Chosen = str(Result[0])
            # Test1's rule: a folder not already named RAMMIT gets a RAMMIT subfolder.
            if not Chosen.rstrip("\\/").lower().endswith("rammit"):
                Chosen = os.path.join(Chosen, "RAMMIT")
            return Chosen
        return None

    def CheckInstall(self, InstallPath, LegacyMode="", KeptChoice=""):
        """{Ok, Path, NeedsConfigChoice} or {Error} / {Error, Running}. NeedsConfigChoice: both the folder and the
        accounts being brought in (old Test1 install, or kept by an earlier uninstall) have accounts."""
        if LegacyMode not in LegacyModes or KeptChoice not in KeptChoices:
            return {"Error": "Bad request."}
        LegacyInfo = Legacy.Detect() if LegacyMode else None
        try:
            Check = Setup.CheckTarget(InstallPath, LegacyMode, LegacyInfo["Path"] if LegacyInfo else "")
        except Setup.SetupError as Error:
            return {"Error": str(Error)}
        if Setup.FindRunning([Check["Path"], LegacyInfo["Path"] if LegacyInfo else ""]):
            return {"Error": "RAMMIT is running.", "Running": True}
        Kept = Setup.FindKeptConfig() if KeptChoice == "Use" and not LegacyMode else None
        return {"Ok": True, "Path": Check["Path"],
                "NeedsConfigChoice": Check["NeedsConfigChoice"] or Setup.KeptConfigNeedsChoice(Kept, Check["Path"])}

    def _RunningFolders(self):
        State = Setup.InstalledState()
        LegacyInfo = None if State["Installed"] else Legacy.Detect()
        return [P for P in (State["Path"], LegacyInfo["Path"] if LegacyInfo else "", self._LastPath) if P]

    def CheckRunning(self):
        return {"Running": bool(Setup.FindRunning(self._RunningFolders()))}

    def CloseRunning(self):
        try:
            Left = Setup.CloseRunning(self._RunningFolders())
        except Exception as Error:
            return {"Error": f"Couldn't close RAMMIT ({type(Error).__name__}). Close it yourself, then press Try again."}
        return {"Ok": Left == 0, "StillRunning": Left}

    # ------------------------------------------------------------ jobs

    def StartInstall(self, Version, InstallPath, Options=None):
        Options = Options if isinstance(Options, dict) else {}
        LegacyMode, ConfigChoice = Options.get("Legacy", ""), Options.get("ConfigChoice", "")
        KeptChoice = Options.get("KeptConfig", "")
        if (LegacyMode not in LegacyModes or ConfigChoice not in ConfigChoices or KeptChoice not in KeptChoices
                or not isinstance(InstallPath, str)):
            return {"Error": "Bad request."}
        LegacyInfo = Legacy.Detect() if LegacyMode else None
        if LegacyMode and not LegacyInfo:
            return {"Error": "The old version can't be found any more."}

        def Job():
            Release = self._Release(Version)
            self._LastPath = InstallPath
            Kept = Setup.FindKeptConfig() if KeptChoice and not LegacyMode else None
            return Setup.RunInstall(Release["Version"], InstallPath, self._Progress, Release=Release, Kind="Install",
                                    LegacyMode=LegacyMode, LegacyPath=LegacyInfo["Path"] if LegacyInfo else "",
                                    ConfigChoice=ConfigChoice or "KeepNew", Kept=Kept, UseKept=KeptChoice == "Use")
        return self._StartJob("Install", Job)

    def _InstalledOrError(self):
        State = Setup.InstalledState()
        if not State["Installed"]:
            raise Setup.SetupError("RAMMIT isn't installed any more. Restart the installer.")
        return State

    def StartRepair(self):
        def Job():
            State = self._InstalledOrError()
            return self._Install(State, self._Release(State["Version"]), "Repair")
        return self._StartJob("Repair", Job)

    def StartChangeVersion(self, Version):
        """Update / Downgrade: installs any listed version over the installed one (not the same one: that's Repair)."""
        if not isinstance(Version, str) or Releases.ParseVersion(Version) is None:
            return {"Error": "Pick a version from the list."}

        def Job():
            State = self._InstalledOrError()
            Release = self._Release(Version)
            if Release["Version"] == State["Version"]:
                raise Setup.SetupError("That's the version you have. Use Repair to reinstall it.")
            Newer = Releases.ParseVersion(Release["Version"]) > (Releases.ParseVersion(State["Version"]) or (0,))
            return self._Install(State, Release, "Update" if Newer else "Downgrade")
        return self._StartJob("ChangeVersion", Job)

    def StartUndo(self):
        def Job():
            State = self._InstalledOrError()
            Version = Setup.UndoVersion(State["Version"])
            if not Version:
                raise Setup.SetupError("There's no earlier version to go back to.")
            Result = Setup.RunInstall(Version, State["Path"], self._Progress, CachedSlot="Previous", Kind="Undo")
            Result["UndoVersion"] = Setup.UndoVersion(Version)
            return Result
        return self._StartJob("Undo", Job)

    def _Install(self, State, Release, Kind):
        Result = Setup.RunInstall(Release["Version"], State["Path"], self._Progress, Release=Release, Kind=Kind)
        Result["UndoVersion"] = Setup.UndoVersion(Release["Version"])
        Result["Kind"] = Kind
        return Result

    def StartUninstall(self, RemoveConfig):
        if not isinstance(RemoveConfig, bool):
            return {"Error": "Bad request."}

        def Job():
            State = self._InstalledOrError()
            return Setup.RunUninstall(State["Path"], RemoveConfig, self._UninstallProgress)
        return self._StartJob("Uninstall", Job)

    def StartLegacyRemove(self):
        def Job():
            LegacyInfo = Legacy.Detect()
            if not LegacyInfo:
                raise Setup.SetupError("The old version can't be found any more.")
            return Legacy.RunRemove(LegacyInfo["Path"], self._UninstallProgress)
        return self._StartJob("LegacyRemove", Job)

    def _LegacyAndInstalled(self):
        State = Setup.InstalledState()
        LegacyInfo = Legacy.Detect()
        if not State["Installed"] or not LegacyInfo:
            raise Setup.SetupError("The old version can't be found any more." if State["Installed"] else "RAMMIT isn't installed.")
        return LegacyInfo["Path"], State["Path"]

    def CheckLegacyMove(self):
        """Choices 1/2 with RAMMIT already installed (no reinstall): asks which accounts to keep when both have some."""
        try:
            Folder, InstallPath = self._LegacyAndInstalled()
        except Setup.SetupError as Error:
            return {"Error": str(Error)}
        if Setup.FindRunning([Folder, InstallPath]):
            return {"Error": "RAMMIT is running.", "Running": True}
        return {"Ok": True, "NeedsConfigChoice": Legacy.AccountsPresent(os.path.join(InstallPath, "Config"))
                and Legacy.AccountsPresent(Legacy.ConfigDir(Folder))}

    def StartLegacyMove(self, Mode, ConfigChoice=""):
        if Mode not in ("MoveRemove", "MoveKeep") or ConfigChoice not in ConfigChoices:
            return {"Error": "Bad request."}

        def Job():
            Folder, InstallPath = self._LegacyAndInstalled()
            return Legacy.RunMove(Folder, InstallPath, Mode, ConfigChoice or "KeepNew", self._UninstallProgress)
        return self._StartJob("LegacyMove", Job)

    def IgnoreLegacy(self, DontAskAgain):
        if not isinstance(DontAskAgain, bool):
            return {"Error": "Bad request."}
        try:
            LegacyInfo = Legacy.Detect()  # the folder comes from the registry, never from the page
            Legacy.Ignore(DontAskAgain, LegacyInfo["Path"] if LegacyInfo else "")
        except OSError:
            return {"Error": "Couldn't save that choice."}
        return {"Ok": True}

    # ------------------------------------------------------------ window

    def Launch(self):
        State = Setup.InstalledState()
        if not State["Installed"]:
            return {"Error": "RAMMIT isn't installed."}
        try:
            Setup.LaunchApp(State["Path"])
        except (Setup.SetupError, OSError) as Error:
            return {"Error": str(Error) if isinstance(Error, Setup.SetupError) else f"RAMMIT couldn't start ({type(Error).__name__})."}
        return {"Ok": True}

    def ResizeInstaller(self, Height, ViewportHeight=None):
        """Height = the page's measured content height in CSS px; ViewportHeight = the page's window.innerHeight.
        pywebview 6 takes logical pixels and applies the monitor DPI itself, so nothing is multiplied here; only the
        title bar + borders are added. Their size is learnt once, while the window is still at its start size:
        start height - viewport height (exact on any scaling and Windows version)."""
        try:
            Height = max(200, min(int(Height), 1000))
            Viewport = int(ViewportHeight) if ViewportHeight is not None else 0
        except (TypeError, ValueError):
            return
        Window = self._Window
        if not Window:
            return
        if self._Frame is None and self._LastHeight and not self._Resized and 0 < Viewport < self._LastHeight:
            self._Frame = self._LastHeight - Viewport
        Target = Height + (self._Frame if self._Frame is not None else self._FrameHeight())
        self._Resized = True
        if abs(Target - self._LastHeight) < 2:
            return
        self._LastHeight = Target
        if self._Dragging:
            return  # held: Windows would undo it (flicker); _OnLetGo applies it
        try:
            Window.resize(WindowWidth, Target)
        except Exception:
            pass

    def _FrameHeight(self):
        """Fallback when the page didn't send its viewport height: title bar + borders read from the native form."""
        try:
            Native = self._Window.native
            Scale = max(1.0, Native.DeviceDpi / 96.0)
            return int(round((Native.Height - Native.ClientSize.Height) / Scale))
        except Exception:
            return 39

    def CloseWindow(self):
        Window = self._Window
        if Window:
            try:
                Window.destroy()
            except Exception:
                pass

    def LogClientError(self, Message):
        if isinstance(Message, str):
            Logger.warning("UI: %s", Message[:300].replace("\n", " "))
