"""Shared test helpers: an isolated test-mode environment, synthetic release zips, a fake Test1 install and a
local fake GitHub release server.

Nothing here touches the real HKCU\\Software\\CBlock Digital\\RAMMIT key, the real Apps-list entry, the real
Desktop/Start Menu or a real %LOCALAPPDATA%\\RAMMIT: every run gets its own registry key names and temp folders
(Locations.py refuses to run test mode otherwise), and Cleanup() deletes them again.
"""
import hashlib
import http.server
import io
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import uuid
import winreg
import zipfile

TestsDir = os.path.dirname(os.path.abspath(__file__))
InstallerDir = os.path.join(os.path.dirname(TestsDir), "Installer")
# A real release zip for the end-to-end test (skipped when there is none): RAMMIT_TEST_RELEASE_ZIP, or the
# Releases folder next to InstallerDev (local layout; it isn't in the repo), or the app's own build output.
RealZip = os.environ.get("RAMMIT_TEST_RELEASE_ZIP") or next(
    (Candidate for Candidate in (
        os.path.join(os.path.dirname(os.path.dirname(TestsDir)), "Releases", "RAMMIT-1.0.0.zip"),
        os.path.join(os.path.dirname(os.path.dirname(TestsDir)), "Production", "RAMMIT-Stable", "dist", "RAMMIT-1.0.0.zip"),
    ) if os.path.isfile(Candidate)), "")
if InstallerDir not in sys.path:
    sys.path.insert(0, InstallerDir)


class TestEnvironment:
    """Sets RAMMIT_INSTALLER_TEST=1 with a unique registry key, Apps-list name and temp root, then reloads Locations."""

    def __init__(self, Label="Unit"):
        Tag = f"{Label}-{os.getpid()}-{uuid.uuid4().hex[:6]}"
        self.Root = tempfile.mkdtemp(prefix=f"RAMMIT-InstallerTest-{Label}-")
        self.RegKey = rf"Software\CBlock Digital\RAMMIT-InstallerTest-{Tag}"
        self.UninstallName = f"RAMMIT-InstallerTest-{Tag}"
        os.environ.update({
            "RAMMIT_INSTALLER_TEST": "1",
            "RAMMIT_INSTALLER_TEST_ROOT": self.Root,
            "RAMMIT_INSTALLER_REGKEY": self.RegKey,
            "RAMMIT_INSTALLER_UNINSTALL_NAME": self.UninstallName,
        })
        import Locations
        self.Locations = Locations.Reload()

    def SetReleasesUrl(self, Url):
        os.environ["RAMMIT_INSTALLER_RELEASES_URL"] = Url
        import Locations
        self.Locations = Locations.Reload()

    def Cleanup(self):
        import Locations
        for Path in (self.RegKey, Locations.UninstallParentPath + "\\" + self.UninstallName):
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, Path)
            except OSError:
                pass
        DeleteEmptyParent(self.RegKey)
        shutil.rmtree(self.Root, ignore_errors=True)


def DeleteEmptyParent(KeyPath):
    """Creating the test key also created "Software\\CBlock Digital"; remove it again if the tests left it empty
    (no subkeys, no values). A real install's key under it keeps it alive."""
    Parent = KeyPath.rsplit("\\", 1)[0]
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, Parent) as Key:
            SubKeys, Values, _Modified = winreg.QueryInfoKey(Key)
        if SubKeys == 0 and Values == 0:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, Parent)
    except OSError:
        pass


def RegValues(KeyPath):
    """All values of an HKCU key as a dict, or None when the key doesn't exist."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, KeyPath) as Key:
            Values, Index = {}, 0
            while True:
                try:
                    Name, Value, _Type = winreg.EnumValue(Key, Index)
                except OSError:
                    return Values
                Values[Name] = Value
                Index += 1
    except OSError:
        return None


def MakeAppZip(Version, Extra=None, Prefix="RAMMIT/"):
    """Bytes of a small release zip shaped like the real one (RAMMIT\\ + Source\\)."""
    Files = {
        "RAMMIT.exe": f"fake RAMMIT exe {Version}",
        "README.txt": f"RAMMIT {Version}",
        "Runtime/python313.dll": "fake runtime " + Version,
        "Src/Dark/HTML/Index.html": f"<html>{Version}</html>",
        "Src/Dark/Theme.json": '{"Name": "Dark"}',
    }
    Files.update(Extra or {})
    Buffer = io.BytesIO()
    with zipfile.ZipFile(Buffer, "w", zipfile.ZIP_DEFLATED) as Zip:
        for Name, Text in Files.items():
            Zip.writestr(Prefix + Name, Text)
        Zip.writestr("Source/README.md", "source tree")
    return Buffer.getvalue()


def ShaLine(Data, Name):
    return f"{hashlib.sha256(Data).hexdigest()}  {Name}\n".encode()


def MakeLegacyInstall(Folder, Version="1.0.0", Accounts=True, Extra=()):
    """A fake Test1 install: Src\\Version.json marker, RAMMIT-Downloader.exe, .gitignore, Config\\. The accounts file
    holds a dummy username only (never a cookie)."""
    os.makedirs(os.path.join(Folder, "Src", "HTML"))
    with open(os.path.join(Folder, "Src", "Version.json"), "w") as File:
        json.dump({"Version": Version}, File)
    for Name in ("Src/HTML/Index.html", "RAMMIT-Downloader.exe", ".gitignore"):
        with open(os.path.join(Folder, *Name.split("/")), "w") as File:
            File.write("test1 " + Name)
    os.makedirs(os.path.join(Folder, "Config"))
    if Accounts:
        with open(os.path.join(Folder, "Config", "accounts.json"), "w") as File:
            json.dump([{"username": "OldTester", "displayName": "Old"}], File)
    with open(os.path.join(Folder, "Config", "settings.json"), "w") as File:
        json.dump({"theme": "dark"}, File)
    for Name in Extra:
        with open(os.path.join(Folder, Name), "w") as File:
            File.write("someone else's file")


def MakeLegacyShortcut(LinkPath):
    """Test1's shortcut: hidden PowerShell reading the registry."""
    import win32com.client
    os.makedirs(os.path.dirname(LinkPath), exist_ok=True)
    Link = win32com.client.Dispatch("WScript.Shell").CreateShortCut(LinkPath)
    Link.TargetPath = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
    Link.Arguments = '-WindowStyle Hidden -Command "& (Join-Path (Get-ItemPropertyValue \'HKCU:\\Software\\CBlock Digital\\RAMMIT\' \'InstallPath\') \'RAMMIT.exe\')"'
    Link.save()


class FakeReleaseServer:
    """A local stand-in for api.github.com + the release downloads.

    Releases: list of dicts {Version, Zip (bytes) or ZipFile (path), Prerelease, BadSha, Draft, NoSha}.
    Hooks for UI tests: HoldList (list request waits until released), ChunkDelay (slow downloads), Offline.
    """

    def __init__(self, Releases):
        self.Releases = Releases
        self.HoldList = threading.Event()
        self.HoldList.set()
        self.HoldDownload = threading.Event()
        self.HoldDownload.set()
        self.ChunkDelay = 0.0
        self.Offline = False
        self.Requests = []
        Outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *_Args):
                pass

            def do_GET(self):
                Outer.Requests.append(self.path)
                if Outer.Offline:
                    self.close_connection = True
                    self.connection.close()
                    return
                if self.path.startswith("/repos/"):
                    Outer.HoldList.wait(60)
                    return self._Send(json.dumps(Outer._List()).encode(), "application/json")
                if self.path.startswith("/download/"):
                    Name = self.path.rsplit("/", 1)[1]
                    Data = Outer._Asset(Name)
                    if Data is None:
                        return self._Send(b"not found", "text/plain", 404)
                    if Name.endswith(".zip"):
                        Outer.HoldDownload.wait(60)
                    return self._Send(Data, "application/octet-stream", Chunked=Name.endswith(".zip"))
                self._Send(b"not found", "text/plain", 404)

            def _Send(self, Data, Type, Status=200, Chunked=False):
                self.send_response(Status)
                self.send_header("Content-Type", Type)
                self.send_header("Content-Length", str(len(Data)))
                self.end_headers()
                try:
                    if not Chunked or not Outer.ChunkDelay:
                        self.wfile.write(Data)
                        return
                    for Start in range(0, len(Data), 64 * 1024):
                        self.wfile.write(Data[Start:Start + 64 * 1024])
                        time.sleep(Outer.ChunkDelay)
                except OSError:
                    pass

        self._Httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._Httpd.daemon_threads = True
        self.Base = f"http://127.0.0.1:{self._Httpd.server_address[1]}"
        self.ListUrl = self.Base + "/repos/OWNER/RAMMIT/releases"
        threading.Thread(target=self._Httpd.serve_forever, daemon=True).start()

    def Stop(self):
        self._Httpd.shutdown()
        self._Httpd.server_close()

    def _ZipBytes(self, Release):
        if "ZipFile" in Release:
            with open(Release["ZipFile"], "rb") as File:
                Release["Zip"] = File.read()
            del Release["ZipFile"]
        return Release["Zip"]

    def _Asset(self, Name):
        for Release in self.Releases:
            ZipName = f"RAMMIT-{Release['Version']}.zip"
            if Name == ZipName:
                return self._ZipBytes(Release)
            if Name == ZipName + ".sha256":
                Data = self._ZipBytes(Release)
                return ShaLine(Data + (b"x" if Release.get("BadSha") else b""), ZipName)
        return None

    def _List(self):
        Out = []
        for Release in self.Releases:
            ZipName = f"RAMMIT-{Release['Version']}.zip"
            Assets = [{"name": "RAMMIT-Setup.exe", "browser_download_url": f"{self.Base}/download/v{Release['Version']}/RAMMIT-Setup.exe", "size": 1},
                      {"name": ZipName, "browser_download_url": f"{self.Base}/download/v{Release['Version']}/{ZipName}",
                       "size": len(self._ZipBytes(Release))}]
            if not Release.get("NoSha"):
                Assets.append({"name": ZipName + ".sha256", "browser_download_url": f"{self.Base}/download/v{Release['Version']}/{ZipName}.sha256", "size": 84})
            Out.append({"tag_name": "v" + Release["Version"], "name": "RAMMIT " + Release["Version"], "draft": bool(Release.get("Draft")),
                        "prerelease": bool(Release.get("Prerelease")), "published_at": "2026-11-02T10:00:00Z", "assets": Assets})
        return Out


def WaitUntil(Test, Timeout=60, Interval=0.05):
    """Polls Test() until it returns something truthy (no fixed sleeps: the PC may be busy)."""
    End = time.monotonic() + Timeout
    while time.monotonic() < End:
        Value = Test()
        if Value:
            return Value
        time.sleep(Interval)
    return Test()


class EventWindow:
    """Stands in for the pywebview window: records the events InstallerApi sends to the page."""

    def __init__(self):
        self.Events = []
        self.Lock = threading.Lock()
        self.LastResize = None

    def evaluate_js(self, Script):
        Prefix = "window.InstallerEvents && window.InstallerEvents."
        if Script.startswith(Prefix):
            Name, Rest = Script[len(Prefix):].split("(", 1)
            with self.Lock:
                self.Events.append((Name, json.loads(Rest[:-1])))

    def resize(self, *Size):
        self.LastResize = list(Size)

    def destroy(self):
        pass

    def Final(self, Since=0):
        """The first Done/Failed event after index Since, or None."""
        with self.Lock:
            for Name, Payload in self.Events[Since:]:
                if Name in ("Done", "Failed"):
                    return Name, Payload
        return None
