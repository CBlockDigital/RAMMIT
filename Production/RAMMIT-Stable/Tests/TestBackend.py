"""Backend unit tests. Run from the project folder:  python -m unittest discover -s Tests -v

Everything runs against a throw-away RAMMIT_BASE_DIR, so a real Config/ is never read or written.
Network, registry and process launching are mocked.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ProjectDir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TempBase = tempfile.mkdtemp(prefix="RammitTest-")
shutil.copytree(os.path.join(ProjectDir, "Src"), os.path.join(TempBase, "Src"))
os.environ["RAMMIT_BASE_DIR"] = TempBase
sys.path.insert(0, ProjectDir)

from App import Api as ApiModule, Crypto, LocalServer, Paths, Roblox, Storage, Themes, Version  # noqa: E402

JobA = "11111111-1111-1111-1111-111111111111"


def ResetConfig():
    shutil.rmtree(Paths.ConfigDir, ignore_errors=True)
    Paths.EnsureConfigDir()


def WriteJson(FilePath, Data):
    with open(FilePath, "w", encoding="utf-8") as File:
        json.dump(Data, File)


class TestPaths(unittest.TestCase):
    def test_BaseDirOverride(self):
        self.assertEqual(os.path.normcase(Paths.BaseDir), os.path.normcase(TempBase))

    def test_IsInside(self):
        self.assertTrue(Paths.IsInside(Paths.SrcDir, os.path.join(Paths.SrcDir, "Dark", "HTML")))
        self.assertFalse(Paths.IsInside(Paths.SrcDir, os.path.join(Paths.SrcDir, "..", "Config")))


class TestInstallSync(unittest.TestCase):
    """App/Install.Sync against throw-away keys (never the real HKCU\\...\\RAMMIT or RAMMIT: protocol)."""

    def setUp(self):
        import uuid
        Tag = uuid.uuid4().hex[:8]
        self.Keys = (rf"Software\CBlock Digital\RAMMIT-AppTest-{Tag}", rf"Software\Classes\RAMMIT-AppTest-{Tag}",
                     rf"Software\Microsoft\Windows\CurrentVersion\Uninstall\RAMMIT-AppTest-{Tag}")
        self.Root = tempfile.mkdtemp(prefix="RAMMIT-InstallSync-")
        self.Old, self.New = os.path.join(self.Root, "Old"), os.path.join(self.Root, "New")
        for Folder in (self.Old, self.New):
            os.makedirs(Folder)
            for Name in ("RAMMIT.exe", "Manifest.json"):  # what an installer-made folder has
                open(os.path.join(Folder, Name), "w").close()

    def tearDown(self):
        import winreg

        def Delete(Path):
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, Path) as Key:
                    Subs = [winreg.EnumKey(Key, I) for I in range(winreg.QueryInfoKey(Key)[0])]
                for Sub in Subs:
                    Delete(Path + "\\" + Sub)
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, Path)
            except OSError:
                pass
        for Path in self.Keys:
            Delete(Path)
        shutil.rmtree(self.Root, ignore_errors=True)

    def Sync(self, BaseDir):
        from App import Install
        return Install.Sync(BaseDir, *self.Keys)

    def test_MovedFolderTakesOverAndSecondCopyDoesNot(self):
        from App import Install
        RegKey, ProtocolKey, UninstallKey = self.Keys
        self.assertEqual(self.Sync(self.New), "")  # never installed: nothing written
        self.assertIsNone(Install._Read(RegKey, "InstallPath"))
        Install._Write(RegKey, "InstallPath", self.Old)
        Install._Write(UninstallKey, "UninstallString", "x")
        self.assertEqual(self.Sync(self.New), "")  # the installed copy is still there: a second copy changes nothing
        self.assertEqual(Install._Read(RegKey, "InstallPath"), self.Old)
        os.remove(os.path.join(self.Old, "RAMMIT.exe"))  # moved away
        self.assertEqual(self.Sync(self.New), "Moved")
        Exe = os.path.join(self.New, "RAMMIT.exe")
        self.assertEqual(Install._Read(RegKey, "InstallPath"), self.New)
        self.assertEqual(Install._Read(ProtocolKey + r"\shell\open\command"), f'"{Exe}"')
        self.assertEqual(Install._Read(ProtocolKey, "URL Protocol"), "")
        self.assertEqual(Install._Read(UninstallKey, "InstallLocation"), self.New)
        self.assertEqual(self.Sync(self.New), "")  # already right
        Install._Write(ProtocolKey + r"\shell\open\command", "", '"C:\\Elsewhere\\RAMMIT.exe"')
        self.assertEqual(self.Sync(self.New), "Fixed")
        self.assertNotIn("%", Install._Read(ProtocolKey + r"\shell\open\command"))  # nothing from the link is passed on

    def test_OnlyAnInstallerMadeFolderTakesOver(self):
        from App import Install
        RegKey, ProtocolKey, _UninstallKey = self.Keys
        Install._Write(RegKey, "InstallPath", self.Old)
        os.remove(os.path.join(self.Old, "RAMMIT.exe"))  # the installed RAMMIT is gone
        os.remove(os.path.join(self.New, "Manifest.json"))  # e.g. a copy unzipped from a release
        self.assertEqual(self.Sync(self.New), "")
        self.assertEqual(Install._Read(RegKey, "InstallPath"), self.Old)
        self.assertIsNone(Install._Read(ProtocolKey + r"\shell\open\command"))
        open(os.path.join(self.New, "Manifest.json"), "w").close()
        with mock.patch.object(Install, "_OnRemovableDrive", return_value=True):
            self.assertEqual(self.Sync(self.New), "")  # a USB stick: it would break again once the stick is gone
        with mock.patch.dict(os.environ, {"RAMMIT_INSTALLER_TEST": "1"}):
            self.assertEqual(self.Sync(self.New), "")  # started by the installer's test mode
        self.assertEqual(Install._Read(RegKey, "InstallPath"), self.Old)
        self.assertEqual(self.Sync(self.New), "Moved")


class TestVersion(unittest.TestCase):
    def test_VersionIsPlainNumbers(self):
        self.assertRegex(Version.AppVersion, r"^\d+\.\d+\.\d+$")

    def test_LabelShowsChannelAndDevCommitOnly(self):
        with mock.patch.object(Version, "AppChannel", "Stable"), mock.patch.object(Version, "AppCommit", "a1b2c3d"):
            self.assertEqual(Version.VersionLabel(), f"v{Version.AppVersion} · Stable")
        with mock.patch.object(Version, "AppChannel", "Dev"), mock.patch.object(Version, "AppCommit", "a1b2c3d"):
            self.assertEqual(Version.VersionLabel(), f"v{Version.AppVersion} · Dev (a1b2c3d)")
        with mock.patch.object(Version, "AppChannel", "Dev"), mock.patch.object(Version, "AppCommit", ""):
            self.assertEqual(Version.VersionLabel(), f"v{Version.AppVersion} · Dev")


class TestStorage(unittest.TestCase):
    def setUp(self):
        ResetConfig()

    def test_DefaultsWhenMissing(self):
        Settings = Storage.LoadSettings()
        self.assertEqual(Settings["Theme"], "Dark")
        self.assertFalse(Settings["TutorialSeen"])
        self.assertEqual(Storage.LoadAccounts(), [])
        self.assertEqual(Storage.LoadConfigs(), [])

    def test_CorruptFilesFallBack(self):
        with open(Paths.SettingsFile, "w") as File:
            File.write("{not json")
        self.assertEqual(Storage.LoadSettings()["MaxInstances"], 1)
        WriteJson(Paths.SettingsFile, [1, 2])
        self.assertEqual(Storage.LoadSettings()["Launcher"], "Roblox")
        with open(Paths.AccountsFile, "w") as File:
            File.write("garbage")
        self.assertEqual(Storage.LoadAccounts(), [])

    def test_InvalidSavedValuesUseDefaults(self):
        WriteJson(Paths.SettingsFile, {"max_instances": "lots", "launcher": "Voidstrap", "launch_delay": -4, "theme": "../x"})
        Settings = Storage.LoadSettings()
        self.assertEqual((Settings["MaxInstances"], Settings["Launcher"], Settings["LaunchDelay"], Settings["Theme"]), (1, "Roblox", 3, "Dark"))

    def test_LegacyMigration(self):
        WriteJson(Paths.SettingsFile, {"selected_account": "Bob", "multi_method": "pywin32", "channel": "zbeta", "theme": "roblox2016",
                                       "launch_params": {"url": "u", "selected_config": "Cfg"}})
        Settings = Storage.LoadSettings()
        self.assertEqual(Settings["SelectedAccounts"], ["Bob"])
        self.assertEqual(Settings["SelectedConfig"], "Cfg")
        self.assertEqual(Settings["Theme"], "Light")
        self.assertEqual(Settings["LaunchParams"], {"Url": "u"})
        Storage.SaveSettings(Settings)
        with open(Paths.SettingsFile) as File:
            Disk = json.load(File)
        for Gone in ("multi_method", "channel", "selected_account"):
            self.assertNotIn(Gone, Disk)
        self.assertEqual(Disk["launch_params"], {"url": "u"})

    def test_CoerceSetting(self):
        self.assertEqual(Storage.CoerceSetting("MaxInstances", "7"), 7)
        for Key, Bad in [("MaxInstances", 0), ("MaxInstances", 101), ("MaxInstances", True), ("LaunchDelay", 301),
                         ("Launcher", "x"), ("TutorialSeen", "yes"), ("Theme", "a/b"), ("Theme", ".."), ("Nope", 1)]:
            with self.assertRaises(Storage.InvalidValue, msg=(Key, Bad)):
                Storage.CoerceSetting(Key, Bad)
        self.assertEqual(Storage.CoerceSetting("ToursDone", ["basics", "evil", 3]), ["basics"])

    def test_CleanParams(self):
        Clean = Storage.CleanParams({"Url": " x ", "PlayerMode": "evil", "PingMode": "lowest", "MinPlayers": "5a", "MaxPlayers": "9", "Other": 1})
        self.assertEqual(Clean, {"Url": "x", "PingMode": "lowest", "MaxPlayers": "9"})
        self.assertEqual(Storage.CleanParams("nope"), {})
        self.assertEqual(len(Storage.CleanParams({"Url": "a" * 5000})["Url"]), Storage.MaxTextLength)

    def test_AtomicWriteLeavesNoTempFiles(self):
        Storage.WriteJsonAtomic(Paths.SettingsFile, {"a": 1})
        self.assertEqual([F for F in os.listdir(Paths.ConfigDir) if F.startswith(".tmp-")], [])

    def test_ConfigsDedupeAndValidate(self):
        WriteJson(Paths.ConfigsFile, [{"name": "A", "method": "Home", "params": {}}, {"name": "A", "method": "Home"},
                                      {"name": "", "method": "Home"}, {"name": "B", "method": "Config"}, "junk"])
        self.assertEqual([C["Name"] for C in Storage.LoadConfigs()], ["A"])


class TestAccounts(unittest.TestCase):
    def setUp(self):
        ResetConfig()

    def test_DpapiRoundTrip(self):
        Stored = Crypto.Encrypt("secret-cookie")
        self.assertTrue(Stored.startswith("dpapi1:"))
        self.assertNotIn("secret-cookie", Stored)
        self.assertEqual(Crypto.Decrypt(Stored), "secret-cookie")

    def test_PlainTextMigratedToDpapi(self):
        WriteJson(Paths.AccountsFile, [{"username": "Bob", "displayName": "B", "cookie": "plain-cookie"}])
        Accounts = Storage.LoadAccounts()
        self.assertEqual(Accounts[0]["Cookie"], "plain-cookie")
        with open(Paths.AccountsFile) as File:
            Raw = File.read()
        self.assertNotIn("plain-cookie", Raw)
        self.assertIn("dpapi1:", Raw)
        self.assertEqual(Storage.LoadAccounts()[0]["Cookie"], "plain-cookie")

    def test_UndecryptableAccountIsLockedNotLost(self):
        WriteJson(Paths.AccountsFile, [{"username": "Bob", "displayName": "B", "cookie": "dpapi1:AAAA"}])
        Accounts = Storage.LoadAccounts()
        self.assertIsNone(Accounts[0]["Cookie"])
        Storage.SaveAccounts(Accounts)
        with open(Paths.AccountsFile) as File:
            self.assertEqual(json.load(File)[0]["cookie"], "dpapi1:AAAA")


class TestRoblox(unittest.TestCase):
    def test_Validators(self):
        self.assertTrue(Roblox.IsPlaceId("606849621"))
        for Bad in ("", "12a", "1" * 21, "1/../2", None):
            self.assertFalse(Roblox.IsPlaceId(Bad))
        self.assertTrue(Roblox.IsJobId(JobA))
        self.assertFalse(Roblox.IsJobId(JobA + "+launchmode:edit"))
        self.assertEqual(Roblox.PlaceIdFromGameUrl("https://www.roblox.com/games/920587237/Adopt-Me"), "920587237")
        self.assertIsNone(Roblox.PlaceIdFromGameUrl("https://evilroblox.com/games/1"))

    def test_BuildLaunchUrlRejectsInjection(self):
        Url = Roblox.BuildLaunchUrl("TICKET", "123", JobA, None)
        self.assertIn("placeId=123", Url)
        self.assertIn("gameId=" + JobA, Url)
        for Args in [("T+x", None, None, None), ("T", "1+x", None, None), ("T", "1", "nope", None), ("T", "1", None, "a+b"), ("", None, None, None)]:
            with self.assertRaises(ValueError, msg=Args):
                Roblox.BuildLaunchUrl(*Args)

    @staticmethod
    def Reply(Status, Body=None, Headers=None):
        Response = mock.Mock(status_code=Status, headers=Headers or {})
        Response.json.side_effect = (lambda: Body) if not isinstance(Body, Exception) else Body
        return Response

    def test_CheckLoginOnlyA401MeansExpired(self):
        # Being offline, rate limited or answered oddly must never turn an account red.
        Get = "App.Roblox.requests.get"
        Valid = {"id": 7, "name": "Bob", "displayName": "Bobby"}
        with mock.patch(Get, return_value=self.Reply(200, Valid)):
            self.assertEqual(Roblox.CheckLogin("fake"), ("Valid", (7, "Bob", "Bobby")))
        with mock.patch(Get, return_value=self.Reply(401)):
            self.assertEqual(Roblox.CheckLogin("fake"), ("Expired", None))
        for Status in (403, 429, 500, 503):
            with mock.patch(Get, return_value=self.Reply(Status)):
                self.assertEqual(Roblox.CheckLogin("fake"), ("Unknown", None), Status)
        for Body in ({"id": "7", "name": "Bob"}, {"name": "Bob"}, [], ValueError("not JSON")):
            with mock.patch(Get, return_value=self.Reply(200, Body)):
                self.assertEqual(Roblox.CheckLogin("fake"), ("Unknown", None), Body)
        with mock.patch(Get, side_effect=Roblox.requests.ConnectionError):
            self.assertEqual(Roblox.CheckLogin("fake"), ("Unknown", None))

    def test_GetAuthTicketOnlyA401MeansExpired(self):
        Post = "App.Roblox.requests.post"
        Csrf = self.Reply(403, Headers={"x-csrf-token": "csrf"})
        with mock.patch(Post, side_effect=[Csrf, self.Reply(200, Headers={"rbx-authentication-ticket": "T"})]):
            self.assertEqual(Roblox.GetAuthTicket("fake"), "T")
        with mock.patch(Post, return_value=self.Reply(401)):
            self.assertIs(Roblox.GetAuthTicket("fake"), Roblox.LoginExpired)  # rejected at the CSRF step
        with mock.patch(Post, side_effect=[Csrf, self.Reply(401)]):
            self.assertIs(Roblox.GetAuthTicket("fake"), Roblox.LoginExpired)  # rejected at the ticket step
        with mock.patch(Post, return_value=self.Reply(403)):
            self.assertIsNone(Roblox.GetAuthTicket("fake"))  # no CSRF token: not "expired"
        with mock.patch(Post, side_effect=[Csrf, self.Reply(500)]):
            self.assertIsNone(Roblox.GetAuthTicket("fake"))
        with mock.patch(Post, side_effect=Roblox.requests.ConnectionError):
            self.assertIsNone(Roblox.GetAuthTicket("fake"))
        with mock.patch(Post, side_effect=[Csrf] + [self.Reply(429)] * 4), mock.patch("App.Roblox.time.sleep"):
            self.assertIsNone(Roblox.GetAuthTicket("fake"))  # still rate limited after the retries

    Servers = [{"id": "f" * 8 + JobA[8:], "playing": 10, "maxPlayers": 10, "ping": 5},
               {"id": "a" * 8 + JobA[8:], "playing": 1, "maxPlayers": 10, "ping": 200},
               {"id": "b" * 8 + JobA[8:], "playing": 5, "maxPlayers": 10, "ping": 40},
               {"id": "c" * 8 + JobA[8:], "playing": 9, "maxPlayers": 10, "ping": 120},
               {"id": "not-a-uuid", "playing": 0, "maxPlayers": 10},
               {"id": "d" * 8 + JobA[8:], "maxPlayers": 10}]  # "playing" missing must not crash

    def test_PickServer(self):
        Pick = lambda *A: (Roblox.PickServer(self.Servers, *A) or {}).get("id", "")[:1]  # noqa: E731
        self.assertEqual(Pick("smallest"), "d")
        self.assertEqual(Pick("biggest"), "c")
        self.assertEqual(Pick("any", "lowest"), "b")
        self.assertEqual(Pick("range", "lowest", 4, 9), "b")
        self.assertEqual(Pick("min_only", "highest", 6), "c")
        self.assertEqual(Pick("range", "any", 20, 30), "")
        self.assertIsNone(Roblox.PickServer([], "any"))

    def test_FetchServersCapsPagesAndEncodesCursor(self):
        Calls = []

        def FakeGet(Url, **_Kw):
            Calls.append(Url)
            return mock.Mock(status_code=200, json=lambda: {"data": [{"id": JobA}], "nextPageCursor": "a&b=c"})
        with mock.patch.object(Roblox.requests, "get", FakeGet):
            Servers = Roblox.FetchServers("123")
        self.assertEqual(len(Calls), Roblox.MaxServerPages)
        self.assertEqual(len(Servers), Roblox.MaxServerPages)
        self.assertIn("cursor=a%26b%3Dc", Calls[1])
        with mock.patch.object(Roblox.requests, "get") as Get:
            self.assertEqual(Roblox.FetchServers("1/../2"), [])
            Get.assert_not_called()

    def test_NoRequestFollowsARedirect(self):
        # 1.2.1: a saved login is only ever sent to the Roblox address RAMMIT asked for, never on to wherever an
        # answer redirects. Every request in Roblox.py must pass allow_redirects=False.
        Seen = []

        def Fake(Url, **Kw):
            Seen.append((Url, Kw.get("allow_redirects"), Kw.get("timeout")))
            return mock.Mock(status_code=302, headers={"Location": "https://evil.example/", "x-csrf-token": "c"},
                             text="", json=lambda: {})
        with mock.patch.object(Roblox.requests, "get", Fake), mock.patch.object(Roblox.requests, "post", Fake), \
                mock.patch("App.Roblox.time.sleep"):
            self.assertEqual(Roblox.CheckLogin("fake"), ("Unknown", None))
            self.assertIsNone(Roblox.GetAuthTicket("fake"))
            self.assertEqual(Roblox.FetchServers("123", "fake"), [])
            self.assertEqual(Roblox.ResolveVipLink("https://www.roblox.com/share?code=abc&type=Server", "fake"), (None, None))
        self.assertGreaterEqual(len(Seen), 4)
        for Url, Redirects, Timeout in Seen:
            self.assertIs(Redirects, False, Url)
            self.assertEqual(Timeout, Roblox.Timeout, Url)
            self.assertRegex(Url, r"^https://[a-z]+\.roblox\.com/", Url)
        with open(Roblox.__file__, encoding="utf-8") as File:  # and no new call forgets it
            Source = File.read()
        self.assertEqual(Source.count("requests.get(") + Source.count("requests.post("), Source.count("**NoRedirect)"))

    def test_CookieDomainAndValueChecks(self):
        for Domain in ("", None, "roblox.com", ".roblox.com", "www.roblox.com", ".ROBLOX.com", "auth.roblox.com"):
            self.assertTrue(Roblox.IsRobloxCookieDomain(Domain), Domain)
        for Domain in ("evil.example", "roblox.com.evil.example", "evilroblox.com", "roblox.co", 5, ["roblox.com"]):
            self.assertFalse(Roblox.IsRobloxCookieDomain(Domain), Domain)
        self.assertTrue(Roblox.IsCookieValue("_|WARNING:-DO-NOT-SHARE-THIS.--x|_ABCDEF0123"))
        for Bad in ("", None, 5, "a b", "a;b=c", "a\r\nX-Evil: 1", "a\x00", "caf\u00e9", "a" * 8193):
            self.assertFalse(Roblox.IsCookieValue(Bad), repr(Bad)[:20])

    def test_PickServerSurvivesAnOddPing(self):
        # 1.2.1: a ping that isn't a number used to raise TypeError inside the sort and fail the whole launch.
        Odd = [{"id": "a" * 8 + JobA[8:], "playing": 1, "maxPlayers": 10, "ping": "fast"},
               {"id": "b" * 8 + JobA[8:], "playing": 2, "maxPlayers": 10, "ping": None},
               {"id": "c" * 8 + JobA[8:], "playing": 3, "maxPlayers": 10, "ping": 30}]
        self.assertEqual(Roblox.PickServer(Odd, "any", "lowest")["id"][:1], "c")
        self.assertEqual(Roblox.PickServer(Odd, "any", "highest")["id"][:1], "c")

    def test_FishstrapLauncher(self):
        self.assertEqual(Storage.Launchers, ("Roblox", "Bloxstrap", "Fishstrap"))
        Root = tempfile.mkdtemp(prefix="RammitAppData-")
        try:
            # Fishstrap folders are not always "version-..." named: any folder holding the exe counts.
            Exe = os.path.join(Root, "Fishstrap", "Versions", "0.701.0.7010812", Roblox.PlayerExe)
            os.makedirs(os.path.dirname(Exe))
            open(Exe, "w").close()
            with mock.patch.dict(os.environ, {"LOCALAPPDATA": Root}):
                self.assertEqual(Roblox.FindLauncherPath("Fishstrap"), Exe)
                self.assertIsNone(Roblox.FindLauncherPath("Voidstrap"))
        finally:
            shutil.rmtree(Root, ignore_errors=True)

    def test_SetChannelValidates(self):
        with mock.patch.object(Roblox.winreg, "CreateKey") as Create:
            self.assertFalse(Roblox.SetChannel("bad channel"))
            self.assertFalse(Roblox.SetChannel("a" * 65))
            Create.assert_not_called()


class TestThemes(unittest.TestCase):
    def test_BuiltInThemes(self):
        self.assertEqual([T["Id"] for T in Themes.ListThemes()][:1], ["Dark"])
        self.assertEqual({T["Id"] for T in Themes.ListThemes()}, {"Dark", "Light", "MyCustomTheme", "CBlock"})
        for Theme in Themes.ListThemes():
            self.assertEqual(len(Theme["Swatch"]), 4, Theme)
            self.assertEqual(Themes.LoadHeightMap(Theme["Id"])[1], [], Theme["Id"])

    def test_ResolveRootFallsBackAndBlocksTraversal(self):
        for Bad in ("..", "../Config", "Dark/../..", "C:\\Windows", "Ghost", "", None):
            self.assertEqual(Themes.ResolveRoot(Bad)[0], "Dark", Bad)
        self.assertEqual(Themes.ResolveRoot("Light")[0], "Light")

    def test_HeightMapValidation(self):
        Folder = os.path.join(Paths.SrcDir, "Broken")
        os.makedirs(os.path.join(Folder, "HTML"), exist_ok=True)
        open(os.path.join(Folder, "HTML", "Index.html"), "w").close()
        WriteJson(os.path.join(Folder, "HeightMap.json"), {"MainWindow": {"Home": 9999, "VIP Link": 700, "Bogus": 1}, "WizzardWindow": {}})
        try:
            Map, Warnings = Themes.LoadHeightMap("Broken")
            self.assertEqual(Map["MainWindow"]["Home"], 716)
            self.assertEqual(Map["MainWindow"]["VIP Link"], 700)
            self.assertEqual(len(Warnings), 3)
        finally:
            shutil.rmtree(Folder)

    def test_ThemeFoldersInSync(self):
        Result = subprocess.run([sys.executable, os.path.join(ProjectDir, "Tools", "SyncThemes.py"), "--check"], capture_output=True, text=True)
        self.assertEqual(Result.returncode, 0, Result.stdout)

    def MakeTheme(self, Name, Css, Meta=None):
        Folder = os.path.join(Paths.SrcDir, Name)
        os.makedirs(os.path.join(Folder, "HTML"), exist_ok=True)
        os.makedirs(os.path.join(Folder, "CSS"), exist_ok=True)
        open(os.path.join(Folder, "HTML", "Index.html"), "w").close()
        with open(os.path.join(Folder, "CSS", "Style.css"), "w") as File:
            File.write(Css)
        if Meta is not None:
            WriteJson(os.path.join(Folder, "Theme.json"), Meta)
        self.addCleanup(shutil.rmtree, Folder, True)
        return Themes.ThemeInfo(Name)["Swatch"]

    def test_SwatchIgnoresComments(self):
        Swatch = self.MakeTheme("SwComments", "/* --Accent: #ffffff; */\n:root { --Background: #111111; --Card: #222222; --Accent: #123456; --Text: #eeeeee; }")
        self.assertEqual(Swatch, ["#111111", "#222222", "#123456", "#eeeeee"])

    def test_SwatchMissingSlotKeepsOrderAndUsesDark(self):
        Swatch = self.MakeTheme("SwMissing", ":root { --Background: #111111; --Accent: #123456; --Text: white; }")
        Dark = Themes.ThemeInfo("Dark")["Swatch"]
        self.assertEqual(Swatch, ["#111111", Dark[1], "#123456", "white"])
        self.assertTrue(any("Card" in W for W in Themes.ThemeWarnings("SwMissing")))

    def test_SwatchThemeJsonPointsAtRenamedVariables(self):
        Swatch = self.MakeTheme("SwRenamed", ":root { --BgColour: #101010; --Brand: rgb(1, 2, 3); --Panel: var(--Missing, #abcdef); }",
                                {"Name": "Renamed", "Swatch": {"Background": "--BgColour", "Card": "--Panel", "Accent": "--Brand", "Text": "NoDashes"}})
        Dark = Themes.ThemeInfo("Dark")["Swatch"]
        self.assertEqual(Swatch, ["#101010", "#abcdef", "rgb(1, 2, 3)", Dark[3]])
        self.assertEqual(Themes.AccentColor("SwRenamed"), "#010203")
        self.assertEqual(Themes.BackgroundColor("SwRenamed"), "#101010")
        self.assertTrue(any("Swatch.Text" in W for W in Themes.ThemeWarnings("SwRenamed")))

    def test_SwatchFollowsVarAliases(self):
        Swatch = self.MakeTheme("SwAlias", ":root { --Brand: navy; --Accent: var(--Brand); --Background: var(--Deep); --Deep: #0b0b0b; --Card: inherit; --Text: #fff; }")
        Dark = Themes.ThemeInfo("Dark")["Swatch"]
        self.assertEqual(Swatch, ["#0b0b0b", Dark[1], "navy", "#fff"])
        self.assertEqual(Themes.AccentColor("SwAlias"), "#000080")  # spinner arc = the swatch's accent, name converted

    def test_SwatchOrderStandardThenPointerThenDark(self):
        # --Accent wins when present; the Swatch link is used only when it isn't; otherwise Dark's.
        Swatch = self.MakeTheme("SwOrder", ":root { --Accent: #111111; --Brand: #222222; --Ink: #333333; --Card: bogus; --Panel: #444444; }",
                                {"Swatch": {"Accent": "--Brand", "Text": "--Ink", "Card": "--Panel", "Background": "--Nope"}})
        Dark = Themes.ThemeInfo("Dark")["Swatch"]
        self.assertEqual(Swatch, [Dark[0], "#444444", "#111111", "#333333"])
        self.assertEqual(Themes.AccentColor("SwOrder"), "#111111")  # spinner arc follows the same order

    def test_SpinnerColoursMatchSwatch(self):
        # The loader's colours always come from the swatch: hsl() and names convert; made-up names fall back.
        Swatch = self.MakeTheme("SwSpinner", ":root { --Background: hsl(210, 100%, 50%); --Accent: notacolour; }",
                                {"Swatch": {"Accent": "--Accent"}})
        Dark = Themes.ThemeInfo("Dark")["Swatch"]
        self.assertEqual(Swatch[0], "hsl(210, 100%, 50%)")
        self.assertEqual(Swatch[2], Dark[2])
        self.assertEqual(Themes.BackgroundColor("SwSpinner"), "#007fff")
        self.assertEqual(Themes.AccentColor("SwSpinner"), Dark[2])
        self.assertTrue(any("Accent" in W for W in Themes.ThemeWarnings("SwSpinner")))


class TestThemeColours(unittest.TestCase):
    def test_OddColoursNeverRaise(self):
        # 1.2.1: "hsl(1.2.3, 5%, 5%)" passes the swatch pattern but isn't a number; float() raised ValueError while
        # the window colour was worked out, so one line in a theme's Style.css stopped RAMMIT from starting.
        for Odd in ("hsl(1.2.3, 5%, 5%)", "hsl(..., 5%, 5%)", "hsl(1, 5.5.5%, 5%)", "rgb(999,0,0)", "#12", "", None, "nope("):
            self.assertIsNone(Themes._ToHex(Odd), Odd)
        self.assertEqual(Themes._ToHex("#abc"), "#aabbcc")
        self.assertEqual(Themes._ToHex("rgb(10, 20, 30)"), "#0a141e")
        self.assertEqual(Themes._ToHex("hsl(0, 100%, 50%)"), "#ff0000")


class TestThemeVersions(unittest.TestCase):
    def MakeTheme(self, Name, Meta):
        TestThemes.MakeTheme(self, Name, ":root { }", Meta)

    def test_ParseSupportedVersions(self):
        self.assertEqual(Themes.ParseSupportedVersions(None), (None, []))
        self.assertEqual(Themes.ParseSupportedVersions("1.0")[0], ["1.0"])
        Entries, Warnings = Themes.ParseSupportedVersions(["1.0", "1.2+", "1.0.2", "v1", "1.x", 5])
        self.assertEqual(Entries, ["1.0", "1.2+", "1.0.2"])
        self.assertTrue(Warnings and "v1" in Warnings[0])
        self.assertTrue(Themes.ParseSupportedVersions({"1": 0})[1])

    def test_SupportsVersion(self):
        Cases = {("1.0",): ["1.0.0", "1.0.7"], ("1",): ["1.0.0", "1.9.3"], ("1.0.2",): ["1.0.2"], ("1.2+",): ["1.2.0", "1.3.1", "2.0.0"]}
        for Entries, Candidates in Cases.items():
            for Candidate in Candidates:
                self.assertTrue(Themes.SupportsVersion(list(Entries), Candidate), (Entries, Candidate))
        for Entries, Candidate in ((["1.0"], "1.1.0"), (["1.0.2"], "1.0.3"), (["1.2+"], "1.1.9"), (["2"], "1.0.0"), ([], "1.0.0")):
            self.assertFalse(Themes.SupportsVersion(Entries, Candidate), (Entries, Candidate))

    def test_BuiltInThemesSupportThisVersion(self):
        for Theme in Themes.ListThemes():
            self.assertTrue(Theme["Compatible"], Theme["Id"])
            self.assertFalse(any("SupportedVersions" in W for W in Themes.ThemeWarnings(Theme["Id"])), Theme["Id"])

    def test_MissingFieldIsANoteNotABlock(self):
        self.MakeTheme("VerNone", {"Name": "No versions"})
        self.assertIsNone(Themes.VersionCheck("VerNone")["Compatible"])
        self.assertTrue(any("SupportedVersions" in W for W in Themes.ThemeWarnings("VerNone")))

    def test_MismatchServesDarkUntilAllowed(self):
        ResetConfig()
        self.MakeTheme("VerOld", {"Name": "Old one", "SupportedVersions": ["0.9"]})
        Bridge = ApiModule.Api(mock.Mock())
        NeedsOk = {Theme["Id"]: Theme["NeedsOk"] for Theme in Bridge.GetThemes()["Themes"]}
        self.assertEqual((NeedsOk["VerOld"], NeedsOk["Dark"]), (True, False))
        Bridge.UpdateSetting("Theme", "VerOld")
        Info = Bridge.GetThemes()
        self.assertEqual((Info["Active"], Info["Blocked"]["Id"], Info["Blocked"]["Supported"]), ("Dark", "VerOld", ["0.9"]))
        self.assertIn("Error", Bridge.AllowThemeVersion("Ghost", False))
        self.assertIn("Error", Bridge.AllowThemeVersion("VerOld", "yes"))
        # Allowed for this run only: served now, asked again after a restart.
        self.assertEqual(Bridge.AllowThemeVersion("VerOld", False), {"Ok": True})
        self.assertEqual((Bridge._ActiveThemeId(), Bridge.GetThemes()["Blocked"]), ("VerOld", None))
        self.assertEqual(ApiModule.Api(mock.Mock())._ActiveThemeId(), "Dark")
        # Remembered: survives a restart, but only for this RAMMIT version.
        Bridge.AllowThemeVersion("VerOld", True)
        self.assertEqual(ApiModule.Api(mock.Mock())._ActiveThemeId(), "VerOld")
        with mock.patch.object(ApiModule, "AppVersion", "9.9.9"):
            self.assertEqual(ApiModule.Api(mock.Mock())._ActiveThemeId(), "Dark")


class TestLocalServer(unittest.TestCase):
    def test_EveryResponseCarriesThePolicy(self):
        # 1.2.1: the Content-Security-Policy used to go out with pages only, so an .svg opened as a document could
        # run its own script. It is now on every answer: pages, scripts, images and errors.
        import http.client
        Server = LocalServer.LocalServer(lambda: "Dark").Start()
        try:
            def Get(Path, Host=None):
                Connection = http.client.HTTPConnection("127.0.0.1", Server.Port, timeout=10)
                Connection.putrequest("GET", Path, skip_host=True)
                Connection.putheader("Host", Host or f"127.0.0.1:{Server.Port}")
                Connection.endheaders()
                Response = Connection.getresponse()
                Response.read()
                Connection.close()
                return Response.status, dict(Response.getheaders())
            for Path, Status in (("/HTML/Index.html", 200), ("/JS/Main.js", 200), ("/RAMMIT.png", 200), ("/nope.svg", 404)):
                Got, Headers = Get(Path)
                self.assertEqual(Got, Status, Path)
                self.assertIn("script-src 'self'", Headers.get("Content-Security-Policy", ""), Path)
                self.assertEqual(Headers["X-Content-Type-Options"], "nosniff", Path)
            Got, Headers = Get("/HTML/Index.html", Host="evil.example")
            self.assertEqual(Got, 403)
            self.assertIn("default-src 'none'", Headers.get("Content-Security-Policy", ""))
        finally:
            Server.Stop()
        self.assertTrue(0 < LocalServer._Handler.timeout <= 60)  # idle connections are dropped

    def test_Resolve(self):
        Root = os.path.join(Paths.SrcDir, "Dark")
        Resolve = LocalServer._Handler._Resolve
        self.assertTrue(Resolve(Root, "/HTML/Index.html"))
        for Bad in ("/", "/HTML/", "/../Light/HTML/Index.html", "/HeightMap.json", "/Theme.json", "/HTML/..\\..\\x.html", "/C:/x.css", "/a\x00.css"):
            self.assertIsNone(Resolve(Root, Bad), Bad)


class TestApi(unittest.TestCase):
    def setUp(self):
        ResetConfig()
        WriteJson(Paths.AccountsFile, [{"username": U, "displayName": U.lower(), "cookie": "c-" + U} for U in ("A", "B", "C")])
        Server = mock.Mock(Origin="http://127.0.0.1:1", Url=lambda P: "http://127.0.0.1:1/HTML/" + P)
        self.Api = ApiModule.Api(Server)

    def test_NothingSecretOrStatefulIsExposed(self):
        # pywebview exposes every public attribute (and nested object) of the js_api object.
        Public = [N for N in dir(self.Api) if not N.startswith("_")]
        self.assertTrue(all(callable(getattr(self.Api, N)) for N in Public), Public)
        self.assertNotIn("Cookie", json.dumps(self.Api.GetAccounts()))
        self.assertNotIn("c-A", json.dumps([self.Api.GetAccounts(), self.Api.GetSettings(), self.Api.GetConfigs()]))

    def test_UpdateSettingsAllOrNothing(self):
        self.assertIn("Error", self.Api.UpdateSettings({"MaxInstances": 4, "LaunchDelay": "x"}))
        self.assertEqual(self.Api.GetSettings()["MaxInstances"], 1)
        self.assertEqual(self.Api.UpdateSettings({"MaxInstances": 4, "LaunchDelay": 2}), {"Ok": True})
        self.assertEqual(Storage.LoadSettings()["MaxInstances"], 4)

    def test_LaunchValidation(self):
        self.assertIn("Error", self.Api.LaunchAccounts([], "Home"))
        self.assertIn("Error", self.Api.LaunchAccounts(["Nobody"], "Home"))
        self.assertIn("Error", self.Api.LaunchAccounts(["A"], "Teleport"))
        self.assertIn("Invalid Job ID", self.Api.LaunchAccounts(["A"], "Place ID + Job ID", {"PlaceId": "1", "JobId": "x+y"})["Error"])
        self.assertIn("Error", self.Api.LaunchAccounts(["A"], "Config", {}, "Missing"))

    def test_LockedAccountCannotLaunch(self):
        self.Api._Accounts[0]["Cookie"] = None
        self.assertIn("can't be read", self.Api._LaunchOne("A", "Home", {})["Error"])

    def test_LaunchOneHappyPath(self):
        with mock.patch.object(ApiModule.MultiInstance, "CountRunning", return_value=0), \
             mock.patch.object(ApiModule.MultiInstance, "LockCookieFile"),              mock.patch.object(ApiModule.MultiInstance, "HoldMutex", return_value=True), \
             mock.patch.object(ApiModule.Roblox, "FindLauncherPath", return_value="C:\\R.exe"), \
             mock.patch.object(ApiModule.Roblox, "GetAuthTicket", return_value="TICKET"), \
             mock.patch.object(ApiModule.subprocess, "Popen") as Popen:
            Popen.return_value.pid = 4242
            self.assertEqual(self.Api._LaunchOne("b", "Place ID", {"PlaceId": "123"}), {"Ok": True})
        Args = Popen.call_args[0][0]
        self.assertEqual(Args[0], "C:\\R.exe")
        self.assertIn("placeId=123", Args[1])
        self.assertEqual(self.Api._Clients._Owners[4242]["User"], "B")  # the started process belongs to the account
        Entries = self.Api._Clients._Expected  # the ticket stays until the game window shows (ticket fallback)
        self.assertEqual([(E["User"], E["Pid"]) for E in Entries], [("B", 4242)])

    def test_LaunchThatCantStartIsForgotten(self):
        with mock.patch.object(ApiModule.MultiInstance, "CountRunning", return_value=0), \
                mock.patch.object(ApiModule.MultiInstance, "LockCookieFile"), \
                mock.patch.object(ApiModule.MultiInstance, "HoldMutex", return_value=True), \
                mock.patch.object(ApiModule.Roblox, "FindLauncherPath", return_value="C:\\R.exe"), \
                mock.patch.object(ApiModule.Roblox, "GetAuthTicket", return_value="TICKET"), \
                mock.patch.object(ApiModule.subprocess, "Popen", side_effect=FileNotFoundError):
            self.assertEqual(self.Api._LaunchOne("A", "Home", {}), {"Error": "Could not start Roblox."})
        self.assertEqual(self.Api._Clients._Expected, [])  # it doesn't count as "starting" for 2 minutes

    def test_ClientTrackerFollowsLaunchesToTheirGameWindows(self):
        # As seen on a real PC: the process RAMMIT starts can hand the game to a "--launch-to-tray" child that opens the
        # window; a game that closes leaves a tray child too, which must not take the account over.
        from App import MultiInstance
        Lines = {20: "RobloxPlayerBeta.exe roblox-player:1+launchmode:play+gameinfo:TICKETA+launchtime:1",
                 21: "RobloxPlayerBeta.exe --launch-to-tray", 22: "RobloxPlayerBeta.exe --launch-to-tray",
                 30: "RobloxPlayerBeta.exe roblox-player:1+launchmode:play+gameinfo:TICKETB+launchtime:2"}
        Parents = {20: 1, 21: 20, 22: 21, 30: 1}
        Players = set()

        def Scan(Running, Windows, IncludeStarting=True):
            Players.clear()
            Players.update(Running)
            with mock.patch.object(MultiInstance, "_PlayerPids", return_value=set(Running)), \
                    mock.patch.object(MultiInstance, "_GameWindowPids", return_value=set(Windows)), \
                    mock.patch.object(MultiInstance, "_CommandLine", side_effect=lambda Pid: Lines[Pid]), \
                    mock.patch.object(MultiInstance, "_ParentPid", side_effect=lambda Pid: Parents[Pid]), \
                    mock.patch.object(MultiInstance, "_CreateTime", side_effect=lambda Pid: 1000.0 + Pid), \
                    mock.patch.object(MultiInstance, "_Alive", side_effect=lambda Pid: Pid in Players):
                return Tracker.Scan(IncludeStarting), Tracker.Accounts()

        with mock.patch.object(MultiInstance, "_CreateTime", side_effect=lambda Pid: 1000.0 + Pid):
            Tracker = MultiInstance.ClientTracker()
            Tracker.Expect("TICKETA", "A")
            Tracker.Started("TICKETA", 20)  # A: RAMMIT started pid 20
            Tracker.Expect("TICKETB", "B")  # B: its process is only found by its ticket (pid 30)

        self.assertEqual(Scan([20], []), (2, {"A": "starting", "B": "starting"}))  # no windows yet: count for the limit
        self.assertEqual(Scan([20], [], IncludeStarting=False)[0], 0)  # but not on the counter label
        self.assertEqual(Scan([21], [21]), (2, {"A": "running", "B": "starting"}))  # 20 handed A to 21, which opened it
        self.assertEqual(Scan([21, 30], [21, 30]), (2, {"A": "running", "B": "running"}))  # B found by its ticket
        self.assertEqual(Scan([22, 30], [30]), (1, {"B": "running"}))  # A closed; its tray child 22 isn't A
        self.assertEqual(Scan([22], []), (0, {}))

    def TrackerScanner(self, Tracker, Lines, Parents, Created):
        """Scan(Running, Windows) with the OS probes faked. Created: pid -> process start time."""
        from App import MultiInstance
        Players = set()

        def Scan(Running, Windows, IncludeStarting=True):
            Players.clear()
            Players.update(Running)
            with mock.patch.object(MultiInstance, "_PlayerPids", return_value=set(Running)), \
                    mock.patch.object(MultiInstance, "_GameWindowPids", return_value=set(Windows)), \
                    mock.patch.object(MultiInstance, "_CommandLine", side_effect=lambda Pid: Lines.get(Pid, "")), \
                    mock.patch.object(MultiInstance, "_ParentPid", side_effect=lambda Pid: Parents.get(Pid, 1)), \
                    mock.patch.object(MultiInstance, "_CreateTime", side_effect=lambda Pid: Created.get(Pid)), \
                    mock.patch.object(MultiInstance, "_Alive", side_effect=lambda Pid: Pid in Players):
                return Tracker.Scan(IncludeStarting), Tracker.Accounts()
        return Scan

    def test_ClientTrackerFindsALaterProcessByItsTicket(self):
        # Roblox's updater can start the real client with the original link: not a child of the process RAMMIT started.
        from App import MultiInstance
        Created = {20: 1.0, 40: 2.0}
        with mock.patch.object(MultiInstance, "_CreateTime", side_effect=lambda Pid: Created.get(Pid)):
            Tracker = MultiInstance.ClientTracker()
            Tracker.Expect("TICKETA", "A")
            Tracker.Started("TICKETA", 20)
        Scan = self.TrackerScanner(Tracker, {40: "RobloxPlayerBeta.exe roblox-player:1+gameinfo:TICKETA+x"}, {40: 99}, Created)
        self.assertEqual(Scan([20], []), (1, {"A": "starting"}))
        self.assertEqual(Scan([40], []), (1, {"A": "starting"}))  # 20 exited; 40 carries A's ticket: still one launch
        self.assertEqual(Scan([40], [40]), (1, {"A": "running"}))
        self.assertEqual(Tracker._Expected, [])  # window shown: the ticket is dropped

    def test_ClientTrackerIgnoresAReusedPid(self):
        from App import MultiInstance
        Created = {20: 1.0}
        with mock.patch.object(MultiInstance, "_CreateTime", side_effect=lambda Pid: Created.get(Pid)):
            Tracker = MultiInstance.ClientTracker()
            Tracker.Expect("TICKETA", "A")
            Tracker.Started("TICKETA", 20)
        Scan = self.TrackerScanner(Tracker, {}, {}, Created)
        self.assertEqual(Scan([20], [20]), (1, {"A": "running"}))
        Created[20] = 5.0  # A's client closed and Windows gave pid 20 to an unrelated Roblox process
        self.assertEqual(Scan([20], [20]), (1, {}))  # counted as a client, but not as A's

    def test_ClientTrackerCountsEachLaunchOnce(self):
        # Relaunching an account that already has a game open counts towards the limit, and a launch that hands over to
        # a child is still one launch.
        from App import MultiInstance
        Created = {20: 1.0, 21: 2.0, 50: 3.0}
        with mock.patch.object(MultiInstance, "_CreateTime", side_effect=lambda Pid: Created.get(Pid)):
            Tracker = MultiInstance.ClientTracker()
            Tracker.Expect("T1", "A")
            Tracker.Started("T1", 20)
        Scan = self.TrackerScanner(Tracker, {}, {21: 20}, Created)
        self.assertEqual(Scan([20], [20]), (1, {"A": "running"}))
        with mock.patch.object(MultiInstance, "_CreateTime", side_effect=lambda Pid: Created.get(Pid)):
            Tracker.Expect("T2", "A")
            Tracker.Started("T2", 50)
        self.assertEqual(Scan([20, 50], [20]), (2, {"A": "starting"}))  # A's second launch counts, and isn't open yet
        Parents = {21: 20}
        Scan = self.TrackerScanner(Tracker, {}, Parents, Created)
        self.assertEqual(Scan([20, 21, 50], [20])[0], 2)  # 21 is a child of 20, whose launch is open: takes nothing
        self.assertEqual(Scan([20, 21, 50], [20, 50]), (2, {"A": "running"}))

    def test_ClientTrackerCountsTwoStartingLaunchesOfOneAccount(self):
        # e.g. a second batch started before the first one's window showed: two clients are on their way
        from App import MultiInstance
        Created = {20: 1.0, 50: 2.0}
        with mock.patch.object(MultiInstance, "_CreateTime", side_effect=lambda Pid: Created.get(Pid)):
            Tracker = MultiInstance.ClientTracker()
            for Ticket, Pid in (("T1", 20), ("T2", 50)):
                Tracker.Expect(Ticket, "A")
                Tracker.Started(Ticket, Pid)
        Scan = self.TrackerScanner(Tracker, {}, {}, Created)
        self.assertEqual(Scan([20, 50], []), (2, {"A": "starting"}))

    def test_ClientTrackerAdoptsAGonePidReusedByAHandoffChild(self):
        # Alice's client (pid 100) closed; Bob's launch hands its game to a child that Windows gives pid 100.
        from App import MultiInstance
        Created = {100: 1.0, 200: 2.0}
        with mock.patch.object(MultiInstance, "_CreateTime", side_effect=lambda Pid: Created.get(Pid)):
            Tracker = MultiInstance.ClientTracker()
            Tracker.Expect("TA", "Alice")
            Tracker.Started("TA", 100)
        Parents = {100: 1}
        Scan = self.TrackerScanner(Tracker, {}, Parents, Created)
        self.assertEqual(Scan([100], [100]), (1, {"Alice": "running"}))
        self.assertEqual(Scan([], []), (0, {}))  # Alice closed: pid 100 is remembered as Gone for a while
        with mock.patch.object(MultiInstance, "_CreateTime", side_effect=lambda Pid: Created.get(Pid)):
            Tracker.Expect("TB", "Bob")
            Tracker.Started("TB", 200)
        Created[100], Parents[100] = 3.0, 200  # Bob's child reuses pid 100, and 200 exits
        self.assertEqual(Scan([100], []), (1, {"Bob": "starting"}))  # adopted at once, not after the Gone wait
        self.assertEqual(Scan([100], [100]), (1, {"Bob": "running"}))

    def test_ClientTrackerDropsALauncherPidReusedByAnotherProgram(self):
        # A Bloxstrap launcher (not a RobloxPlayerBeta) died before any window; Windows gave its pid to notepad.
        from App import MultiInstance
        Created = {300: 1.0}
        with mock.patch.object(MultiInstance, "_CreateTime", side_effect=lambda Pid: Created.get(Pid)):
            Tracker = MultiInstance.ClientTracker()
            Tracker.Expect("TC", "Carol")
            Tracker.Started("TC", 300)
        Created[300] = 9.0  # notepad.exe now has pid 300: alive, but not a RobloxPlayerBeta
        with mock.patch.object(MultiInstance, "_PlayerPids", return_value=set()), \
                mock.patch.object(MultiInstance, "_GameWindowPids", return_value=set()), \
                mock.patch.object(MultiInstance, "_CreateTime", side_effect=lambda Pid: Created.get(Pid)), \
                mock.patch.object(MultiInstance, "_Alive", return_value=True):
            self.assertEqual(Tracker.Scan(), 0)  # no longer a launch "starting" for 10 minutes
        self.assertEqual(Tracker.Accounts(), {})
        self.assertNotIn(300, Tracker._Owners)

    def test_ClientTrackerRenameAndForget(self):
        from App import MultiInstance
        with mock.patch.object(MultiInstance, "_CreateTime", return_value=1.0):
            Tracker = MultiInstance.ClientTracker()
            Tracker.Expect("T1", "A")
            Tracker.Started("T1", 20)
            Tracker.Expect("T2", "B")
        Tracker.Forget("T2")
        Tracker.Rename("A", "A2")
        Scan = self.TrackerScanner(Tracker, {}, {}, {20: 1.0})
        self.assertEqual(Scan([20], [20]), (1, {"A2": "running"}))

    def test_OnlyGameWindowsCount(self):
        # Roblox's tray right-click menu (SystrayContextMenu) is a visible window too, and a hidden game window isn't open yet.
        from App import MultiInstance
        Windows = {1: ("WINDOWSCLIENT", True, 11), 2: ("SystrayContextMenu", True, 12), 3: ("WINDOWSCLIENT", False, 13)}
        with mock.patch.object(MultiInstance.win32gui, "EnumWindows", side_effect=lambda Fn, _X: [Fn(H, None) for H in Windows]), \
                mock.patch.object(MultiInstance.win32gui, "IsWindowVisible", side_effect=lambda H: Windows[H][1]), \
                mock.patch.object(MultiInstance.win32gui, "GetClassName", side_effect=lambda H: Windows[H][0]), \
                mock.patch.object(MultiInstance.win32process, "GetWindowThreadProcessId", side_effect=lambda H: (0, Windows[H][2])):
            self.assertEqual(MultiInstance._GameWindowPids(), {11})

    def test_RobloxAlreadyRunningGivesClearError(self):
        self.Api._Settings["MaxInstances"] = 5
        with mock.patch.object(ApiModule.MultiInstance, "CountRunning", return_value=1),              mock.patch.object(ApiModule.MultiInstance, "HoldMutex", return_value=False):
            self.assertEqual(self.Api._LaunchOne("A", "Home", {}), {"Error": ApiModule.RobloxFirstMessage})

    def test_InstanceLimit(self):
        with mock.patch.object(ApiModule.MultiInstance, "CountRunning", return_value=1):
            self.assertEqual(self.Api._LaunchOne("A", "Home", {}), {"Error": "Instance limit reached."})

    def test_LoginCheckMarksExpiredAndFillsInUserIds(self):
        Answers = {"c-A": ("Expired", None), "c-B": ("Valid", (101, "B", "b")), "c-C": ("Unknown", None)}
        with mock.patch.object(ApiModule.Roblox, "CheckLogin", side_effect=lambda Cookie: Answers[Cookie]):
            self.Api._CheckLogins(Forever=False)
            Expired = {A["Username"]: A["Expired"] for A in self.Api.GetAccounts()}
            self.assertEqual(Expired, {"A": True, "B": False, "C": False})  # unknown (offline...) never turns red
            self.assertEqual([A["UserId"] for A in Storage.LoadAccounts()], [None, 101, None])  # saved for renewing
            Answers["c-A"] = ("Valid", (100, "A", "a"))  # e.g. Roblox was briefly unhappy
            self.Api._CheckLogins(Forever=False)
            self.assertFalse(self.Api.GetAccounts()[0]["Expired"])

    def test_RenewKeepsTheSameUserAndAddsADifferentOne(self):
        self.Api._Accounts[0]["UserId"] = 7
        self.Api._Expired = {"a", "b", "c"}
        self.Api.UpdateSetting("SelectedAccounts", ["A"])
        with mock.patch.object(ApiModule.Roblox, "CheckLogin", return_value=("Valid", (7, "A2", "Renamed"))):
            Outcome = {}
            self.assertEqual(self.Api._FinishLogin("new-A", "A", Outcome), "Renewed")  # same user id: renamed on Roblox
            self.assertEqual(Outcome["Username"], "A2")  # RENEW AND LAUNCH selects it under its new name
        with mock.patch.object(ApiModule.Roblox, "CheckLogin", return_value=("Valid", (12, "C", "c"))):
            self.assertEqual(self.Api._FinishLogin("new-C", "C"), "Renewed")  # no id saved yet: same username counts
        with mock.patch.object(ApiModule.Roblox, "CheckLogin", return_value=("Valid", (9, "Other", "o"))):
            self.assertEqual(self.Api._FinishLogin("other", "B"), "Added")  # someone else signed in: a new account
        Accounts = {A["Username"]: A for A in self.Api.GetAccounts()}
        self.assertEqual(list(Accounts), ["A2", "B", "C", "Other"])
        self.assertEqual({Name: A["Expired"] for Name, A in Accounts.items()}, {"A2": False, "B": True, "C": False, "Other": False})
        self.assertEqual(self.Api.GetSettings()["SelectedAccounts"], ["A2"])
        self.assertEqual([A["UserId"] for A in Storage.LoadAccounts()], [7, None, 12, 9])
        self.assertIn("Error", self.Api.RenewAccount("Nobody"))

    def test_ExpiredLoginAtLaunchMarksTheAccount(self):
        with mock.patch.object(ApiModule.MultiInstance, "CountRunning", return_value=0), \
                mock.patch.object(ApiModule.MultiInstance, "LockCookieFile"), \
                mock.patch.object(ApiModule.MultiInstance, "HoldMutex", return_value=True), \
                mock.patch.object(ApiModule.Roblox, "FindLauncherPath", return_value="C:\\R.exe"), \
                mock.patch.object(ApiModule.Roblox, "GetAuthTicket", return_value=ApiModule.Roblox.LoginExpired):
            self.assertEqual(self.Api._LaunchOne("A", "Home", {}), {"Error": ApiModule.ExpiredMessage})
        self.assertTrue(self.Api.GetAccounts()[0]["Expired"])

    def test_ExpiredAtLaunchDoesNotMarkAJustRenewedLogin(self):
        self.Api._Expired.clear()
        Account = self.Api._Accounts[0]

        def RenewedMeanwhile(_Cookie):  # RENEW saved a new login while this launch was asking for a ticket
            Account["Cookie"] = "renewed-A"
            return ApiModule.Roblox.LoginExpired
        with mock.patch.object(ApiModule.MultiInstance, "CountRunning", return_value=0), \
                mock.patch.object(ApiModule.MultiInstance, "LockCookieFile"), \
                mock.patch.object(ApiModule.MultiInstance, "HoldMutex", return_value=True), \
                mock.patch.object(ApiModule.Roblox, "FindLauncherPath", return_value="C:\\R.exe"), \
                mock.patch.object(ApiModule.Roblox, "GetAuthTicket", side_effect=RenewedMeanwhile):
            self.assertEqual(self.Api._LaunchOne("A", "Home", {}), {"Error": ApiModule.ExpiredMessage})
        self.assertFalse(self.Api.GetAccounts()[0]["Expired"])

    def test_ExpiredAtLaunchDoesNotMarkAReaddedLogin(self):
        self.Api._Expired.clear()

        def ReaddedMeanwhile(_Cookie):  # + ADD saved a new login for the same account while this launch waited
            with mock.patch.object(ApiModule.Roblox, "CheckLogin", return_value=("Valid", (55, "A", "a"))):
                self.Api._FinishLogin("new-A")
            return ApiModule.Roblox.LoginExpired
        with mock.patch.object(ApiModule.MultiInstance, "CountRunning", return_value=0), \
                mock.patch.object(ApiModule.MultiInstance, "LockCookieFile"), \
                mock.patch.object(ApiModule.MultiInstance, "HoldMutex", return_value=True), \
                mock.patch.object(ApiModule.Roblox, "FindLauncherPath", return_value="C:\\R.exe"), \
                mock.patch.object(ApiModule.Roblox, "GetAuthTicket", side_effect=ReaddedMeanwhile):
            self.assertEqual(self.Api._LaunchOne("A", "Home", {}), {"Error": ApiModule.ExpiredMessage})
        self.assertFalse({A["Username"]: A["Expired"] for A in self.Api.GetAccounts()}["A"])

    def test_RenewAccountReturnsTheNewName(self):
        def FakeOpenLogin(_Title, RenewFor=None, Done=None, Outcome=None):
            Outcome.update({"Result": "Renewed", "Username": "A2"})
            Done.set()
            return {"Ok": True}
        with mock.patch.object(self.Api, "_OpenLogin", side_effect=FakeOpenLogin):
            self.assertEqual(self.Api.RenewAccount("A"), {"Ok": True, "Renewed": True, "Username": "A2"})

        def Closed(_Title, RenewFor=None, Done=None, Outcome=None):
            Done.set()
            return {"Ok": True}
        with mock.patch.object(self.Api, "_OpenLogin", side_effect=Closed):
            self.assertEqual(self.Api.RenewAccount("A"), {"Ok": True, "Renewed": False})

    def test_WindowSizeWiresUpTheDragEvents(self):
        from App import WindowSize

        class Event:  # what pythonnet's .NET events and pywebview's events support: += and firing
            def __init__(self):
                self.Handlers = []

            def __iadd__(self, Handler):
                self.Handlers.append(Handler)
                return self

            def Fire(self, *Args):
                for Handler in self.Handlers:
                    Handler(*Args)

        Window = mock.MagicMock()
        Window.events.shown = Event()
        Window.native = mock.Mock(Height=595, ResizeBegin=Event(), ResizeEnd=Event())
        Sizer = WindowSize.HeldWindow(Window)
        Window.events.shown.Fire()  # the window is up: ResizeBegin / ResizeEnd are watched
        Window.native.ResizeBegin.Fire(None, None)  # title bar grabbed
        Sizer.Resize(765, 800)
        Window.resize.assert_not_called()
        with mock.patch.object(WindowSize.HeldWindow, "_SetHeight") as SetHeight, \
                mock.patch.object(WindowSize.HeldWindow, "_WindowScale", return_value=1.25), \
                mock.patch.object(WindowSize.threading, "Thread", side_effect=lambda target, daemon: mock.Mock(start=target)):
            Window.native.ResizeEnd.Fire(None, None)  # let go: applied once, size only
            SetHeight.assert_called_once_with(Window.native, 1000)
        Sizer.Resize(765, 700)
        Window.resize.assert_called_once_with(765, 700)

    def test_RemoveAccountsByName(self):
        self.Api.UpdateSetting("SelectedAccounts", ["A", "B"])
        self.assertEqual(self.Api.RemoveAccounts(["a", "Zed"]), {"Removed": 1})
        self.assertEqual([A["Username"] for A in self.Api.GetAccounts()], ["B", "C"])
        self.assertEqual(self.Api.GetSettings()["SelectedAccounts"], ["B"])

    def test_WizardRenameAndOverwrite(self):
        self.Api.WizardConfirm("One", "Home", {})
        self.Api.WizardConfirm("Two", "Place ID", {"PlaceId": "5"})
        self.Api._WizardEditName = "One"
        self.Api.UpdateSetting("SelectedConfig", "One")
        self.Api.WizardConfirm("Uno", "Home", {})
        self.assertEqual([C["Name"] for C in self.Api.GetConfigs()], ["Uno", "Two"])
        self.assertEqual(self.Api.GetSettings()["SelectedConfig"], "Uno")
        self.assertIn("Error", self.Api.WizardConfirm("", "Home", {}))
        self.assertIn("Error", self.Api.WizardConfirm("X", "Config", {}))

    def test_ThemeApi(self):
        Info = self.Api.GetThemes()
        self.assertEqual(Info["Active"], "Dark")
        self.assertEqual(self.Api.GetHeightMap()["WizardWindow"]["Width"], 400)
        self.assertIn("Error", self.Api.UpdateSetting("Theme", "../../Config"))

    def test_MainWindowOpensAtHeightMapHeight(self):
        from App import Main
        Map = Themes.LoadHeightMap("Dark")[0]["MainWindow"]
        self.assertEqual(Main.StartHeight(self.Api), Map["Home"])
        self.Api.UpdateSettings({"LaunchOption": "Game URL", "LaunchParams": {"PlayerMode": "range"}})
        self.assertEqual(Main.StartHeight(self.Api), Map["Game URL"] + Map["PlayerFilterExtra"])

    def test_ResizeWaitsForLetGoWhileWindowIsHeld(self):
        from App import WindowSize
        Window = mock.MagicMock()
        Window.native = mock.Mock(Height=595, DeviceDpi=96)  # 476 logical px at 125%; DeviceDpi stays 96 (pywebview)
        self.Api._AttachMainWindow(Window)
        Sizer = self.Api._MainSizer
        Sizer._Dragging = True  # title bar held: only record the height (Windows would undo a resize now)
        self.Api.ResizeWindow(800)
        Window.resize.assert_not_called()
        with mock.patch.object(WindowSize.HeldWindow, "_SetHeight") as SetHeight, \
                mock.patch.object(WindowSize.HeldWindow, "_WindowScale", return_value=1.25):
            Sizer._Dragging = False
            Sizer._ReapplyHeight()  # what letting go runs
            SetHeight.assert_called_once_with(Window.native, round(int(800 * 0.85) * 1.25))
        self.Api.ResizeWindow(716)  # not held: straight through
        Window.resize.assert_called_once_with(int(900 * 0.85), int(716 * 0.85))

    @staticmethod
    def Jar(Value, Domain=None, Name=".ROBLOSECURITY"):
        """One cookie the way pywebview hands it over: a SimpleCookie whose morsel carries the domain."""
        from http.cookies import SimpleCookie
        Cookie = SimpleCookie()
        Cookie[Name] = Value
        if Domain is not None:
            Cookie[Name]["domain"] = Domain
        return Cookie

    def test_FindLoginCookie(self):
        Find = ApiModule.Api._FindLoginCookie
        self.assertEqual(Find([self.Jar("x", ".roblox.com", "other"), self.Jar("tok", ".roblox.com")]), "tok")
        self.assertEqual(Find([self.Jar("tok", "www.roblox.com")]), "tok")
        self.assertEqual(Find([self.Jar("tok")]), "tok")  # no domain recorded: taken as before
        self.assertIsNone(Find([]))
        self.assertIsNone(Find(None))

    def test_FindLoginCookieIgnoresOtherSites(self):
        # 1.2.1: the login window can end up on another site, which could set a cookie with Roblox's name to get
        # its own account saved here. Only Roblox's cookie counts, wherever the other one is in the list.
        Find = ApiModule.Api._FindLoginCookie
        for Domain in ("evil.example", ".notroblox.com", "roblox.com.evil.example", "evilroblox.com", "roblox.co"):
            self.assertIsNone(Find([self.Jar("theirs", Domain)]), Domain)
        self.assertEqual(Find([self.Jar("theirs", "evil.example"), self.Jar("mine", ".roblox.com")]), "mine")
        self.assertIsNone(Find([{".ROBLOSECURITY": mock.Mock(value=None)}]))  # nothing usable never raises

    def test_AppInfoCarriesTheCodeName(self):
        Info = self.Api.GetAppInfo()
        self.assertEqual(Info["CodeName"], Version.AppCodeName)
        self.assertTrue(Version.AppCodeName.strip())
        self.assertEqual(Info["Label"], Version.VersionLabel())  # the footer label itself is unchanged


def tearDownModule():
    shutil.rmtree(TempBase, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
