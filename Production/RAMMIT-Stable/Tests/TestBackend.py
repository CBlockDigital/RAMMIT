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
        self.assertIn(4242, self.Api._TrackedPids)

    def test_RobloxAlreadyRunningGivesClearError(self):
        self.Api._Settings["MaxInstances"] = 5
        with mock.patch.object(ApiModule.MultiInstance, "CountRunning", return_value=1),              mock.patch.object(ApiModule.MultiInstance, "HoldMutex", return_value=False):
            self.assertEqual(self.Api._LaunchOne("A", "Home", {}), {"Error": ApiModule.RobloxFirstMessage})

    def test_InstanceLimit(self):
        with mock.patch.object(ApiModule.MultiInstance, "CountRunning", return_value=1):
            self.assertEqual(self.Api._LaunchOne("A", "Home", {}), {"Error": "Instance limit reached."})

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

    def test_FindLoginCookie(self):
        Morsel = mock.Mock(value="tok")
        self.assertEqual(ApiModule.Api._FindLoginCookie([{"other": mock.Mock(value="x"), ".ROBLOSECURITY": Morsel}]), "tok")
        self.assertIsNone(ApiModule.Api._FindLoginCookie([]))


def tearDownModule():
    shutil.rmtree(TempBase, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
