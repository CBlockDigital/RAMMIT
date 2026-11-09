"""Make a preview picture (a "thumbnail sheet") of one or more RAMMIT themes.

    python Tools/RenderTheme.py Dark Light CBlock
    python Tools/RenderTheme.py --from "C:\\path\\to\\OceanBlue"       a theme folder from anywhere
    python Tools/RenderTheme.py MyTheme --out C:\\Pictures --browser chrome

Each theme becomes <Out>\\<ThemeId>.png (default Out: ThemeRenders\\ in this Source folder). The sheet
shows the main window, the open Theme list, + ADD on hover and the config wizard (at the size
RAMMIT gives it).

How: runs the real UI with fake demo accounts (Tests/UiHarness.py - never your real Config) and
drives Microsoft Edge or Google Chrome headless over the DevTools protocol. Needs only Python's
standard library, RAMMIT's runtime packages (requirements.txt) and Edge (on every Windows 10/11
PC) or Chrome. The sheet is assembled inside the browser, so no image library is needed.
"""
import argparse
import base64
import json
import os
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time
import urllib.request

SourceDir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
Browsers = {
    "edge": [r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe", r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"],
    "chrome": [r"C:\Program Files\Google\Chrome\Application\chrome.exe", r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
               os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe")],
}
Scale = 2                     # pixel density of the captures (sharp sheet)
MainWidth = 765                # 900 x 0.85 UI scale, fixed in App/Main.py
TitleBar = 36.7               # Windows title bar height (logical px) the real windows lose to it
# Stand-in for pywebview's bridge: window.pywebview.api.X(...) -> the harness's /__TestApi/X.
# Resize calls are ignored: this script sets the viewport itself.
BridgeShim = """window.pywebview = { api: new Proxy({}, { get: (_T, Name) => (...Args) =>
    (String(Name).startsWith('Resize') ? Promise.resolve(null)
        : fetch('/__TestApi/' + String(Name), { method: 'POST', body: JSON.stringify(Args) }).then(R => R.json())) }) };"""


# ---------------------------------------------------------------- minimal DevTools client (stdlib)

class DevTools:
    """Just enough of a WebSocket client to speak Chrome DevTools Protocol."""

    def __init__(self, WsUrl):
        Host, Port, Path = self._Split(WsUrl)
        self._Sock = socket.create_connection((Host, Port), timeout=30)
        Key = base64.b64encode(os.urandom(16)).decode()
        self._Sock.sendall((f"GET {Path} HTTP/1.1\r\nHost: {Host}:{Port}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                            f"Sec-WebSocket-Key: {Key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
        Reply = b""
        while b"\r\n\r\n" not in Reply:
            Reply += self._Sock.recv(4096)
        if b" 101 " not in Reply.split(b"\r\n", 1)[0]:
            raise RuntimeError("DevTools refused the connection")
        self._Buffer = Reply.split(b"\r\n\r\n", 1)[1]
        self._NextId = 0

    @staticmethod
    def _Split(WsUrl):
        Rest = WsUrl.split("://", 1)[1]
        HostPort, Path = Rest.split("/", 1)
        Host, Port = HostPort.split(":")
        return Host, int(Port), "/" + Path

    def _Read(self, Count):
        while len(self._Buffer) < Count:
            Chunk = self._Sock.recv(1 << 20)
            if not Chunk:
                raise RuntimeError("DevTools connection closed")
            self._Buffer += Chunk
        Data, self._Buffer = self._Buffer[:Count], self._Buffer[Count:]
        return Data

    def _Send(self, Text):
        Payload = Text.encode()
        Header = bytearray([0x81])
        Length = len(Payload)
        if Length < 126:
            Header.append(0x80 | Length)
        elif Length < 65536:
            Header += bytes([0x80 | 126]) + struct.pack(">H", Length)
        else:
            Header += bytes([0x80 | 127]) + struct.pack(">Q", Length)
        Mask = os.urandom(4)
        self._Sock.sendall(bytes(Header) + Mask + bytes(B ^ Mask[I % 4] for I, B in enumerate(Payload)))

    def _Receive(self):
        Message = b""
        while True:
            First, Second = self._Read(2)
            Length = Second & 0x7F
            if Length == 126:
                Length = struct.unpack(">H", self._Read(2))[0]
            elif Length == 127:
                Length = struct.unpack(">Q", self._Read(8))[0]
            Payload = self._Read(Length)
            Opcode = First & 0x0F
            if Opcode == 0x9:            # ping -> pong
                self._Sock.sendall(bytes([0x8A, 0x80]) + os.urandom(4))
                continue
            Message += Payload
            if First & 0x80:             # final fragment
                return json.loads(Message.decode())

    def Call(self, Method, **Params):
        self._NextId += 1
        CallId = self._NextId
        self._Send(json.dumps({"id": CallId, "method": Method, "params": Params}))
        while True:
            Reply = self._Receive()
            if Reply.get("id") == CallId:
                if "error" in Reply:
                    raise RuntimeError(f"{Method}: {Reply['error'].get('message')}")
                return Reply.get("result", {})

    def Eval(self, Script):
        Result = self.Call("Runtime.evaluate", expression=Script, awaitPromise=True, returnByValue=True)
        if "exceptionDetails" in Result:
            raise RuntimeError("page script failed: " + json.dumps(Result["exceptionDetails"].get("exception", {}).get("description", "")))
        return Result.get("result", {}).get("value")


# ---------------------------------------------------------------- browser + harness

def StartBrowser(Choice):
    Candidates = Browsers.get(Choice) if Choice else Browsers["edge"] + Browsers["chrome"]
    Exe = next((Path for Path in Candidates if os.path.isfile(Path)), None)
    if not Exe:
        raise SystemExit("Couldn't find Microsoft Edge or Google Chrome. Use --browser edge|chrome.")
    Profile = tempfile.mkdtemp(prefix="RenderThemeBrowser-")
    Proc = subprocess.Popen([Exe, "--headless=new", "--remote-debugging-port=0", f"--user-data-dir={Profile}", "--no-first-run",
                             "--no-default-browser-check", "--disable-gpu", "--hide-scrollbars", "about:blank"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    PortFile = os.path.join(Profile, "DevToolsActivePort")
    for _ in range(200):
        if os.path.isfile(PortFile) and open(PortFile).read().strip():
            break
        time.sleep(0.05)
    Port = int(open(PortFile).read().split()[0])
    Targets = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{Port}/json/list", timeout=10).read())
    Page = next(T for T in Targets if T.get("type") == "page")
    return Proc, Profile, DevTools(Page["webSocketDebuggerUrl"])


def StartHarness(ExtraThemes):
    Scratch = tempfile.mkdtemp(prefix="RenderThemeUi-")
    Proc = subprocess.Popen([sys.executable, os.path.join(SourceDir, "Tests", "UiHarness.py"), Scratch],
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    Line = Proc.stdout.readline()
    if not Line.startswith("PORT"):
        raise SystemExit("The UI harness didn't start (is requirements.txt installed?)")
    for Folder in ExtraThemes:   # themes from elsewhere go into the harness's own copy of Src\
        shutil.copytree(Folder, os.path.join(Scratch, "Src",os.path.basename(os.path.normpath(Folder))), dirs_exist_ok=True)
    return Proc, Scratch, f"http://127.0.0.1:{Line.split()[1]}"


def Api(Base, Name, *Args):
    Request = urllib.request.Request(f"{Base}/__TestApi/{Name}", data=json.dumps(Args).encode(), method="POST")
    return json.loads(urllib.request.urlopen(Request, timeout=30).read())


def TidyDemoData(Base):
    """The harness ships an XSS test config; swap it for normal-looking demo configs."""
    for Config in Api(Base, "GetConfigs"):
        if "<" in Config["Name"]:
            Api(Base, "RemoveConfig", Config["Name"])
    Api(Base, "OpenConfigWizard", "")
    Api(Base, "WizardConfirm", "Trade Hub", "Game URL", {"Url": "https://www.roblox.com/games/920587237", "PlayerMode": "biggest"})
    Api(Base, "UpdateSettings", {"SelectedConfig": "Grind Server", "LaunchOption": "Home", "LaunchParams": {}, "TutorialSeen": True})


# ---------------------------------------------------------------- capture

def Viewport(Tools, Width, Height, Density=Scale):
    Tools.Call("Emulation.setDeviceMetricsOverride", width=int(Width), height=int(Height), deviceScaleFactor=Density, mobile=False)
    Settle(Tools)


def Settle(Tools):
    """Wait until the browser has actually painted the current size/state (avoids stale or tiled captures)."""
    time.sleep(0.15)
    # Headless browsers sometimes stop producing animation frames, so never wait for them longer than 0.5 s
    # (Shot() still retakes a capture until two in a row match).
    Tools.Eval("new Promise(R => { requestAnimationFrame(() => requestAnimationFrame(R)); setTimeout(R, 500); })")


def Open(Tools, Url):
    Tools.Call("Page.navigate", url=Url)
    for _ in range(200):
        if Tools.Eval("document.readyState") == "complete":
            break
        time.sleep(0.05)
    time.sleep(1.3)   # let the page boot (themes, accounts, layout settle)


def Shot(Tools, Clip=None):
    """Capture (part of) the page. Headless Chrome/Edge sometimes hands back a stale or tiled frame
    right after a resize, so keep shooting until two captures in a row are identical."""
    if not Clip:
        Size = Tools.Eval("[innerWidth, innerHeight]")
        Clip = {"x": 0, "y": 0, "width": Size[0], "height": Size[1]}
    Params = {"format": "png", "captureBeyondViewport": True, "clip": {**Clip, "scale": 1}}
    Settle(Tools)
    Previous = Tools.Call("Page.captureScreenshot", **Params)["data"]
    for _ in range(6):
        Settle(Tools)
        Current = Tools.Call("Page.captureScreenshot", **Params)["data"]
        if Current == Previous:
            break
        Previous = Current
    return Current


def Box(Tools, Selector, Pad=0, Height=None):
    Rect = Tools.Eval(f"(() => {{ const B = document.querySelector({json.dumps(Selector)}).getBoundingClientRect(); "
                      f"return {{x: B.x, y: B.y, width: B.width, height: B.height}}; }})()")
    return {"x": Rect["x"] - Pad, "y": Rect["y"] - Pad, "width": Rect["width"] + Pad * 2, "height": (Height or Rect["height"]) + Pad * 2}


def Hover(Tools, Selector):
    Center = Tools.Eval(f"(() => {{ const B = document.querySelector({json.dumps(Selector)}).getBoundingClientRect(); return [B.x + B.width / 2, B.y + B.height / 2]; }})()")
    Tools.Call("Input.dispatchMouseEvent", type="mouseMoved", x=Center[0], y=Center[1])
    time.sleep(0.35)


def SelectSecondAccount(Tools):
    """Tick account 2 once the list has loaded (the page fills it in after boot)."""
    for _ in range(50):
        if Tools.Eval("""(() => { const Row = document.querySelector('#AccountList .ListItem:nth-child(2)');
                if (!Row) return false;
                if (!Row.classList.contains('Selected')) Row.querySelector('.AcctLabel').click();
                return Row.classList.contains('Selected'); })()"""):
            return
        time.sleep(0.1)
    print("  note: couldn't tick an account (list didn't load)")


def RenderTheme(Tools, Base, Theme, HeightMap):
    # A theme made for another RAMMIT version would open as Dark (App/Api.py): allow it for this render only.
    Api(Base, "AllowThemeVersion", Theme["Id"], False)
    Api(Base, "UpdateSetting", "Theme", Theme["Id"])
    # Main window: the content area of the real window at Home (HeightMap x 0.85 UI scale, minus the title bar).
    MainHeight = round(HeightMap["MainWindow"].get("Home", 716) * 0.85 - TitleBar)
    Viewport(Tools, MainWidth, MainHeight)
    Open(Tools, f"{Base}/HTML/Index.html")
    # The supported-versions note isn't part of the theme's look: leave just that sentence out of the preview.
    Tools.Eval("""(() => { const Note = document.getElementById('ThemeWarning');
        if (Note) Note.textContent = Note.textContent.replace(/Theme\\.json doesn't say which RAMMIT versions[^)]*\\)\\./, '').trim(); })()""")
    SelectSecondAccount(Tools)
    Hover(Tools, "#Row2Wrapper")          # park the mouse somewhere neutral
    Main = Shot(Tools)
    Hover(Tools, "#AddAccountBtn")
    HoverAdd = Shot(Tools, Box(Tools, "#AccountButtons", Pad=8))
    Hover(Tools, "#Row2Wrapper")
    Tools.Eval("document.querySelector('#ThemeSelect .CustomSelectTrigger').click()")
    time.sleep(0.6)
    ListBox = Box(Tools, "#SettingsPanel")
    Bottom = Tools.Eval("document.querySelector('#ThemeSelect .CustomSelectOptions').getBoundingClientRect().bottom")
    ThemeList = Shot(Tools, {**ListBox, "height": min(ListBox["height"], Bottom - ListBox["y"] + 24)})
    # Wizard at the size RAMMIT gives it: as tall as its content.
    # Every size below comes from the theme's own HeightMap.json, so themes with a different layout render at their sizes.
    WizardWidth = HeightMap["WizardWindow"].get("Width", 400)
    Api(Base, "OpenConfigWizard", "")
    Viewport(Tools, WizardWidth, 900)
    Open(Tools, f"{Base}/HTML/Wizard.html")
    Tools.Eval("""(() => { const S = document.querySelector('#MethodSelect'); S.querySelector('.CustomSelectTrigger').click();
                   [...S.querySelectorAll('.CustomSelectOption')].find(O => O.dataset.value === 'Game URL').click(); })()""")
    time.sleep(0.6)
    Tools.Eval("document.body.click()")
    # Measure in a tiny viewport (the body is 100vh tall), then size it like Wizard.js does:
    # outer window = content + ExtraPadding, minus the title bar a real window would have.
    Viewport(Tools, WizardWidth, 100)
    time.sleep(0.3)
    Content = Tools.Eval("(() => { document.body.style.overflow = 'auto'; const H = document.body.scrollHeight; document.body.style.overflow = 'hidden'; return H; })()")
    WizardHeight = round(Content + HeightMap["WizardWindow"].get("ExtraPadding", 22) - TitleBar)
    Viewport(Tools, WizardWidth, WizardHeight)
    time.sleep(0.4)
    Wizard = Shot(Tools)
    Api(Base, "WizardCancel")
    return {"Main": Main, "ThemeList": ThemeList, "HoverAdd": HoverAdd, "Wizard": Wizard,
            "MainSize": (MainWidth, MainHeight), "WizardSize": (WizardWidth, WizardHeight)}


def ComposeSheet(Tools, Theme, Parts):
    """Lay the captures out on one page and screenshot it - the browser is the image editor."""
    Swatch = Theme.get("Swatch") or ["#0a0a0a", "#141414", "#0078d4", "#ffffff"]
    Html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>
        body {{ margin: 0; width: max-content; background: #1b1724; font-family: 'Segoe UI', sans-serif; color: #e8e5f0; }}
        .Sheet {{ display: flex; gap: 30px; padding: 22px 30px 30px; }}
        h1 {{ margin: 18px 30px 0; font-size: 30px; font-weight: 700; }}
        h1 span {{ font-weight: 400; color: #a9a4bd; font-size: 22px; }}
        .Swatch {{ display: inline-block; width: 26px; height: 26px; vertical-align: -4px; margin-right: 12px; border-radius: 3px;
                  border: 1px solid #3a3548;
                  background: linear-gradient({Swatch[2]}, {Swatch[2]}) right top / 50% 50% no-repeat,
                              linear-gradient({Swatch[3]}, {Swatch[3]}) right bottom / 50% 50% no-repeat,
                              linear-gradient({Swatch[0]}, {Swatch[0]}) left bottom / 50% 50% no-repeat, {Swatch[1]}; }}
        .Label {{ font-size: 22px; color: #a98be8; margin-bottom: 8px; }}
        .Column {{ display: flex; flex-direction: column; gap: 26px; }}
        img {{ display: block; }}
        .Watermark {{ flex: 1; display: flex; flex-direction: column; justify-content: center; align-items: center; gap: 10px;
                      border: 2px dashed #3a3548; border-radius: 10px; color: #a9a4bd; font-size: 34px; text-align: center; padding: 24px; }}
        .Watermark b {{ color: #d9d4ec; font-size: 52px; letter-spacing: 0.14em; }}
        .Watermark span {{ font-size: 22px; color: #6f6a86; }}
    </style></head><body>
        <h1><i class="Swatch"></i>{Escape(Theme['Name'])} <span>by {Escape(Theme['Author'])} &middot; RAMMIT theme</span></h1>
        <div class="Sheet">
            <div class="Column"><div><div class="Label">Main window</div><img id="Main"></div>
                <div class="Watermark"><div><b>RAMMIT</b></div><div>Auto-generated by the official theme renderer</div>
                    <span>Tools/RenderTheme.py &middot; {time.strftime("%Y-%m-%d")} &middot; demo data, sizes from this theme's HeightMap.json</span></div></div>
            <div class="Column">
                <div><div class="Label">Theme list</div><img id="ThemeList"></div>
                <div><div class="Label">+ ADD on hover</div><img id="HoverAdd"></div>
                <div><div class="Label">Config wizard</div><img id="Wizard"></div>
            </div>
        </div></body></html>"""
    Viewport(Tools, 3000, 2000)
    Tools.Call("Page.navigate", url="data:text/html;base64," + base64.b64encode(Html.encode()).decode())
    time.sleep(0.4)
    # Images go in after load (keeps the navigation URL small); 1 capture pixel = 1 sheet pixel at scale 1.
    for Key in ("Main", "ThemeList", "HoverAdd", "Wizard"):
        Tools.Eval(f"new Promise(R => {{ const I = document.getElementById('{Key}'); I.onload = () => {{ I.style.width = I.naturalWidth + 'px'; R(); }}; "
                   f"I.src = 'data:image/png;base64,{Parts[Key]}'; }})")
    Size = Tools.Eval("(() => { const B = document.body.getBoundingClientRect(); return [Math.ceil(B.width), Math.ceil(B.height)]; })()")
    Viewport(Tools, Size[0], Size[1], Density=1)
    time.sleep(0.3)
    return base64.b64decode(Shot(Tools))


def Escape(Text):
    return str(Text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def OpenBrowser(Choice):
    Proc, Profile, Tools = StartBrowser(Choice)
    Tools.Call("Page.enable")
    Tools.Call("Page.addScriptToEvaluateOnNewDocument", source=BridgeShim)
    return Proc, Profile, Tools


def CloseBrowser(Proc, Profile):
    if Proc:
        Proc.kill()
        Proc.wait(10)
    if Profile:
        shutil.rmtree(Profile, ignore_errors=True)


def Main():
    Parser = argparse.ArgumentParser(description="Render preview pictures of RAMMIT themes.")
    Parser.add_argument("Themes", nargs="*", help="theme folder names in Src\\ (e.g. Dark Light CBlock)")
    Parser.add_argument("--from", dest="From", action="append", default=[], help="a theme folder somewhere else (repeatable)")
    Parser.add_argument("--out", default=os.path.join(SourceDir, "ThemeRenders"), help="output folder")
    Parser.add_argument("--browser", choices=("edge", "chrome"), help="which browser to use (default: Edge, then Chrome)")
    Args = Parser.parse_args()
    Wanted = list(Args.Themes) + [os.path.basename(os.path.normpath(F)) for F in Args.From]
    if not Wanted:
        Parser.error("name at least one theme, e.g.  python Tools/RenderTheme.py Dark")
    os.makedirs(Args.out, exist_ok=True)
    Harness, Scratch, Base = StartHarness(Args.From)
    Browser, Profile, Tools = None, None, None
    Failed = []
    try:
        Browser, Profile, Tools = OpenBrowser(Args.browser)
        TidyDemoData(Base)
        Known = {T["Id"]: T for T in Api(Base, "GetThemes")["Themes"]}
        for ThemeId in Wanted:
            if ThemeId not in Known:
                print(f"skip {ThemeId}: no such theme (needs a folder with HTML\\Index.html)")
                continue
            # Headless Edge/Chrome now and then stops answering mid-capture; a fresh browser always recovers.
            for Attempt in (1, 2, 3):
                try:
                    Api(Base, "AllowThemeVersion", ThemeId, False)  # so its own HeightMap is used even on a version mismatch
                    Api(Base, "UpdateSetting", "Theme", ThemeId)
                    Parts = RenderTheme(Tools, Base, Known[ThemeId], Api(Base, "GetHeightMap"))
                    Sheet = ComposeSheet(Tools, Known[ThemeId], Parts)   # before opening the file, so a failure leaves no empty PNG
                    break
                except (OSError, RuntimeError) as Problem:   # socket timeouts are OSErrors
                    Api(Base, "WizardCancel")
                    CloseBrowser(Browser, Profile)
                    Browser, Profile, Tools = None, None, None
                    if Attempt == 3:
                        Sheet = None
                        break
                    print(f"  {ThemeId}: browser stopped responding ({type(Problem).__name__}), restarting it")
                    Browser, Profile, Tools = OpenBrowser(Args.browser)
            if Sheet is None:
                Failed.append(ThemeId)
                print(f"{ThemeId}: FAILED after 3 tries")
                Browser, Profile, Tools = OpenBrowser(Args.browser)
                continue
            OutFile = os.path.join(Args.out, f"{ThemeId}.png")
            with open(OutFile, "wb") as File:
                File.write(Sheet)
            print(f"{ThemeId}: {OutFile}")
    finally:
        CloseBrowser(Browser, Profile)
        Harness.kill()
        shutil.rmtree(Scratch, ignore_errors=True)
    if Failed:
        sys.exit(1)


if __name__ == "__main__":
    Main()
