"""Runs the REAL installer backend (InstallerApi + Setup + Releases + UiServer serving the embedded UI) for the
browser tests, in test mode, against a fake GitHub release server. Only the window and launching RAMMIT are faked.

    python Tests/UiHarness.py <ScratchDir>      prints "PORT <n>" once ready

<ScratchDir> is wiped and becomes the test root (fake Desktop, Start Menu, %LOCALAPPDATA%). Registry: only
HKCU\\Software\\CBlock Digital\\RAMMIT-InstallerTest-Ui and the Apps entry RAMMIT-InstallerTest-Ui, both deleted on
start and on POST /__TestHook/Shutdown.

Test-only routes (never part of the shipped server):
    POST /__TestApi/<Method>     body = JSON list of args -> InstallerApi.<Method>(*args)
    GET  /__TestHook/Events      pending Python->JS events (the shim in TestUi.mjs replays them; reading empties it)
    GET  /__TestHook/EventLog    every Python->JS event so far (never emptied, so checks can't race the page's replay)
    GET  /__TestHook/State       last window resize, launches, closes
    POST /__TestHook/Server      {"HoldList", "ChunkDelay", "Offline", "Forget"} -> fake release server behaviour (Forget: drop the cached list)
    POST /__TestHook/Running     {"Running": true|false} -> pretend RAMMIT is (not) running
    POST /__TestHook/SlowUninstall {"Delay": seconds per progress step}
    POST /__TestHook/Legacy      makes a fake Test1 install at <ScratchDir>\\OldRAMMIT and points the registry at it
    POST /__TestHook/Accounts    {"Path"} -> writes a dummy Config\\Accounts.json there (no cookies)
    POST /__TestHook/StartScreen {"Screen"} -> as if started with /Uninstall
    POST /__TestHook/Shutdown    removes the test registry keys and exits
"""
import json
import os
import shutil
import sys
import threading
import time
import winreg

ScratchDir = os.path.abspath(sys.argv[1])
shutil.rmtree(ScratchDir, ignore_errors=True)
os.makedirs(ScratchDir)
os.environ.update({
    "RAMMIT_INSTALLER_TEST": "1",
    "RAMMIT_INSTALLER_TEST_ROOT": ScratchDir,
    "RAMMIT_INSTALLER_REGKEY": r"Software\CBlock Digital\RAMMIT-InstallerTest-Ui",
    "RAMMIT_INSTALLER_UNINSTALL_NAME": "RAMMIT-InstallerTest-Ui",
    "RAMMIT_INSTALLER_PROTOCOL": "RAMMIT-InstallerTest-Ui",
})
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import Support  # noqa: E402  (also puts Installer\ on sys.path)

# A 2 MB incompressible file makes the download long enough to see the progress screen when ChunkDelay is set.
Filler = {"Runtime/Big.bin": os.urandom(2 * 1024 * 1024).hex()[:2 * 1024 * 1024]}
Server = Support.FakeReleaseServer([
    {"Version": "1.2.0-beta.1", "Prerelease": True, "Zip": Support.MakeAppZip("1.2.0-beta.1")},
    {"Version": "1.1.0", "Zip": Support.MakeAppZip("1.1.0", Filler)},
    {"Version": "1.0.0", "Zip": Support.MakeAppZip("1.0.0", Filler)},
    {"Version": "0.9.0", "Zip": Support.MakeAppZip("0.9.0")},
])
os.environ["RAMMIT_INSTALLER_RELEASES_URL"] = Server.ListUrl

import InstallerApi  # noqa: E402
import Locations  # noqa: E402
import Setup  # noqa: E402
import UiServer  # noqa: E402

L = Locations.Reload()


def DeleteKeys():
    for Path in (L.RegKeyPath, L.UninstallKeyPath):
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, Path)
        except OSError:
            pass
    Setup.UnregisterProtocol()
    # Creating the test key also created "Software\CBlock Digital": remove it again if nothing else is in it.
    Parent = L.RegKeyPath.rsplit("\\", 1)[0]
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, Parent) as Key:
            SubKeys, Values, _Modified = winreg.QueryInfoKey(Key)
        if SubKeys == 0 and Values == 0:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, Parent)
    except OSError:
        pass


DeleteKeys()
Fake = {"Events": [], "EventLog": [], "Lock": threading.Lock(), "LastResize": None, "Launches": 0, "Closed": 0, "Running": False, "UninstallDelay": 0.0}


class FakeWindow:
    def evaluate_js(self, Script):
        with Fake["Lock"]:
            Fake["Events"].append(Script)
            Fake["EventLog"].append(Script)

    def resize(self, *Size):
        Fake["LastResize"] = list(Size)

    def destroy(self):
        Fake["Closed"] += 1

    def create_file_dialog(self, _Kind):
        return [os.path.join(ScratchDir, "Picked")]


class FakeProcess:
    pid = 424242


RealFindRunning = Setup.FindRunning
Setup.FindRunning = lambda Folders: [FakeProcess()] if Fake["Running"] else []
Setup.CloseRunning = lambda Folders, Timeout=8: Fake.__setitem__("Running", False) or 0
Setup.LaunchApp = lambda Path: Fake.__setitem__("Launches", Fake["Launches"] + 1)

Bridge = InstallerApi.InstallerApi()
Bridge._AttachWindow(FakeWindow())
RealUninstallProgress = Bridge._UninstallProgress


def SlowUninstallProgress(**Data):
    RealUninstallProgress(**Data)
    if Fake["UninstallDelay"]:
        time.sleep(Fake["UninstallDelay"])


Bridge._UninstallProgress = SlowUninstallProgress


class TestHandler(UiServer._Handler):
    def do_POST(self):
        Body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"[]")
        if self.path.startswith("/__TestApi/"):
            Name = self.path[len("/__TestApi/"):]
            Method = getattr(Bridge, Name, None) if not Name.startswith("_") else None
            Result = Method(*Body) if callable(Method) else {"HarnessError": "no such method " + Name}
        elif self.path == "/__TestHook/Server":
            if "HoldList" in Body:
                (Server.HoldList.clear if Body["HoldList"] else Server.HoldList.set)()
            Server.ChunkDelay = float(Body.get("ChunkDelay", Server.ChunkDelay))
            Server.Offline = bool(Body.get("Offline", Server.Offline))
            if Body.get("Forget"):
                Bridge._Releases = None
            Result = {"Ok": True}
        elif self.path == "/__TestHook/Running":
            Fake["Running"] = bool(Body["Running"])
            Result = {"Ok": True}
        elif self.path == "/__TestHook/SlowUninstall":
            Fake["UninstallDelay"] = float(Body["Delay"])
            Result = {"Ok": True}
        elif self.path == "/__TestHook/Legacy":
            Old = os.path.join(ScratchDir, "OldRAMMIT")
            if not os.path.isdir(Old):
                Support.MakeLegacyInstall(Old)
            Setup.RegWrite("InstallPath", Old)
            Result = {"Path": Old}
        elif self.path == "/__TestHook/Accounts":
            Folder = os.path.join(Body["Path"], "Config")
            os.makedirs(Folder, exist_ok=True)
            with open(os.path.join(Folder, "Accounts.json"), "w") as File:
                File.write('[{"Username": "UiTester"}]')
            Result = {"Ok": True}
        elif self.path == "/__TestHook/StartScreen":
            Bridge._StartScreen = Body["Screen"]
            Result = {"Ok": True}
        elif self.path == "/__TestHook/Shutdown":
            DeleteKeys()
            self._Json({"Ok": True})
            threading.Timer(0.2, lambda: os._exit(0)).start()
            return
        else:
            Result = {"HarnessError": "unknown"}
        self._Json(Result)

    def do_GET(self):
        if self.path == "/__TestHook/Events":
            with Fake["Lock"]:
                Events, Fake["Events"] = Fake["Events"], []
            return self._Json(Events)
        if self.path == "/__TestHook/EventLog":
            with Fake["Lock"]:
                return self._Json(list(Fake["EventLog"]))
        if self.path == "/__TestHook/State":
            return self._Json({"LastResize": Fake["LastResize"], "Launches": Fake["Launches"], "Closed": Fake["Closed"],
                               "Registry": Support.RegValues(L.RegKeyPath), "Apps": Support.RegValues(L.UninstallKeyPath)})
        return super().do_GET()

    def _Json(self, Value):
        Data = json.dumps(Value).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(Data)))
        self.end_headers()
        self.wfile.write(Data)


Ui = UiServer.UiServer(UiServer.LoadEmbeddedUi(Support.InstallerDir), HandlerClass=TestHandler).Start()
print("PORT", Ui.Port, flush=True)
threading.Event().wait()
