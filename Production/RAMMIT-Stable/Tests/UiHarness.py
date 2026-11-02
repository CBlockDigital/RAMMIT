"""Runs the REAL backend (App/Api.py + App/LocalServer.py) for browser tests, with everything
that would touch the outside world faked: Roblox web APIs, launching the client, the registry,
the multi-instance mutex and pywebview windows.

    python Tests/UiHarness.py <ScratchDir>      prints "PORT <n>" once ready

The scratch dir gets a copy of Src/ and a throw-away Config/, so real accounts are never read.
Test-only routes (never part of the shipped server):
    POST /__TestApi/<Method>   body = JSON list of args -> calls Api.<Method>(*args)
    GET  /__TestHook/Events    pending Python->JS notifications
    POST /__TestHook/Login     body = ["Username"] -> simulates a finished Roblox login
    GET  /__TestHook/State     launches so far, fake running count, last main-window resize
"""
import json
import os
import shutil
import sys
import threading
import types

ProjectDir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ScratchDir = os.path.abspath(sys.argv[1])
shutil.rmtree(ScratchDir, ignore_errors=True)
shutil.copytree(os.path.join(ProjectDir, "Src"), os.path.join(ScratchDir, "Src"))
os.makedirs(os.path.join(ScratchDir, "Config"))
os.environ["RAMMIT_BASE_DIR"] = ScratchDir
sys.path.insert(0, ProjectDir)

# Plain-text accounts like an old build wrote them: exercises the DPAPI migration on start.
with open(os.path.join(ScratchDir, "Config", "Accounts.json"), "w") as File:
    json.dump([{"username": U, "displayName": D, "cookie": "FakeCookie-" + U} for U, D in
               [("NovaBuilds", "Nova"), ("PixelRanger_07", "Ranger"), ("ObbyQueen", "Queenie"), ("TycoonTheo", "Theo")]], File)
with open(os.path.join(ScratchDir, "Config", "Config.json"), "w") as File:
    json.dump([{"name": "Grind Server", "method": "Place ID", "params": {"place_id": "2753915549", "player_mode": "smallest", "ping_mode": "lowest"}},
               {"name": "<img src=x onerror=alert(1)>", "method": "Game URL", "params": {"url": "https://www.roblox.com/games/920587237\"><b>x</b>"}}], File)
with open(os.path.join(ScratchDir, "Config", "Settings.json"), "w") as File:
    json.dump({"theme": "dark", "multi_method": "pywin32", "selected_account": "ObbyQueen", "tutorial_seen": True,
               "launch_option": "Game URL", "launch_params": {"url": "https://www.roblox.com/games/920587237", "selected_config": "Grind Server"},
               "max_instances": 3, "launch_delay": 0}, File)

import webview  # noqa: E402
from App import Api as ApiModule, LocalServer as ServerModule, MultiInstance, Roblox, Themes  # noqa: E402

Fake = {"Launches": [], "Running": 0, "Channel": "production", "Events": [], "Lock": threading.Lock()}
FakeServers = [{"id": "11111111-1111-1111-1111-111111111111", "playing": 3, "maxPlayers": 20, "ping": 80},
               {"id": "22222222-2222-2222-2222-222222222222", "playing": 15, "maxPlayers": 20, "ping": 30},
               {"id": "33333333-3333-3333-3333-333333333333", "playing": 20, "maxPlayers": 20, "ping": 10}]


class FakeEvent:
    def __iadd__(self, _Handler):
        return self


class FakeWindow:
    def __init__(self, *Args, **Kwargs):
        self.events = types.SimpleNamespace(closed=FakeEvent(), loaded=FakeEvent())
        self.Url = Kwargs.get("url")

    def evaluate_js(self, Script):
        with Fake["Lock"]:
            Fake["Events"].append(Script)

    def resize(self, *Size):
        with Fake["Lock"]:
            Fake["LastResize"] = list(Size)

    def destroy(self):
        pass

    def get_cookies(self):
        return []

    def clear_cookies(self):
        pass


class FakeProc:
    pid = 999999


def FakePopen(Args, **_Kw):
    Fake["Launches"].append(Args[1])
    Fake["Running"] += 1
    return FakeProc()


webview.create_window = FakeWindow
ApiModule.webview.create_window = FakeWindow
ApiModule.subprocess = types.SimpleNamespace(Popen=FakePopen, CREATE_NO_WINDOW=0)
MultiInstance.Enable = MultiInstance.LockCookieFile = MultiInstance.HoldMutex = MultiInstance.IsReady = lambda: True
MultiInstance.CountRunning = lambda _Pids=None: Fake["Running"]
Roblox.GetAuthTicket = lambda _Cookie: "FAKETICKET0123"
Roblox.FindLauncherPath = lambda _L: r"C:\Fake\RobloxPlayerBeta.exe"
Roblox.FetchServers = lambda _P, _C=None, MaxPages=10: [dict(S) for S in FakeServers]
Roblox.GetGameMaxPlayers = lambda _P: 20
Roblox.ResolveVipLink = lambda Url, _C=None: ("606849621", "AbC123") if "share" in Url or "privateServerLinkCode" in Url else (None, None)
Roblox.GetAuthenticatedUser = lambda Cookie: (Cookie.split("-", 1)[1], "New " + Cookie.split("-", 1)[1])
Roblox.GetChannel = lambda: Fake["Channel"]
Roblox.SetChannel = lambda C: bool(Roblox.ChannelPattern.match(C)) and (Fake.__setitem__("Channel", C) or True)
Themes.OpenThemesFolder = lambda: None


class TestHandler(ServerModule._Handler):
    def do_POST(self):
        Body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"[]")
        if self.path.startswith("/__TestApi/"):
            Name = self.path[len("/__TestApi/"):]
            Method = getattr(Bridge, Name, None) if not Name.startswith("_") else None
            Result = Method(*Body) if callable(Method) else {"HarnessError": "no such method " + Name}
        elif self.path == "/__TestHook/Login":
            Bridge._FinishLogin("FakeCookie-" + Body[0])
            Result = {"Ok": True}
        else:
            Result = {"HarnessError": "unknown"}
        self._Json(Result)

    def do_GET(self):
        if self.path == "/__TestHook/Events":
            with Fake["Lock"]:
                Events, Fake["Events"] = Fake["Events"], []
            return self._Json(Events)
        if self.path == "/__TestHook/State":
            return self._Json({"Launches": Fake["Launches"], "Running": Fake["Running"], "LastResize": Fake.get("LastResize"),
                               "AccountsFile": open(os.path.join(ScratchDir, "Config", "Accounts.json")).read()})
        return super().do_GET()

    def _Json(self, Value):
        Data = json.dumps(Value).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(Data)))
        self.end_headers()
        self.wfile.write(Data)


Bridge = None
Server = ServerModule.LocalServer(lambda: Bridge._ActiveThemeId())
Server._Httpd.RequestHandlerClass = TestHandler
Bridge = ApiModule.Api(Server)
Bridge._AttachMainWindow(FakeWindow())
Server.Start()
print("PORT", Server.Port, flush=True)
threading.Event().wait()
