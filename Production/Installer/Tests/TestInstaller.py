"""Backend unit tests for the installer. Run from Production\\Installer\\:

    python -m unittest discover -s Tests -p "Test*.py"

Every test runs in test mode with its own registry key, Apps-list name and temp folders (Support.TestEnvironment),
so the real RAMMIT install, registry key, Desktop and Start Menu are never touched.
"""
import http.client
import os
import shutil
import subprocess
import unittest
from unittest import mock
import winreg
import zipfile

import Support

import InstallerApi  # noqa: E402  (Support put Installer\ on sys.path)
import Legacy  # noqa: E402
import Locations  # noqa: E402
import Paths  # noqa: E402
import Releases  # noqa: E402
import Setup  # noqa: E402
import UiServer  # noqa: E402
from Log import Logger  # noqa: E402

Logger.disabled = True  # expected failures would otherwise print warnings


def NoReport(**_Progress):
    pass


def Read(Path):
    with open(Path, encoding="utf-8") as File:
        return File.read()


def Write(Path, Text):
    os.makedirs(os.path.dirname(Path), exist_ok=True)
    with open(Path, "w", encoding="utf-8") as File:
        File.write(Text)


class InstallerTestCase(unittest.TestCase):
    """Fresh environment + a fake release server with 1.0.0, 1.1.0 (latest), 1.2.0-beta.1 (test) and 0.9.0."""

    ReleaseSpecs = [
        {"Version": "1.2.0-beta.1", "Prerelease": True},
        {"Version": "1.1.0"},
        {"Version": "1.0.0"},
        {"Version": "0.9.0"},
    ]

    def setUp(self):
        self.Env = Support.TestEnvironment("Unit")
        self.Server = Support.FakeReleaseServer([dict(Spec, Zip=Support.MakeAppZip(Spec["Version"])) for Spec in self.ReleaseSpecs])
        self.Env.SetReleasesUrl(self.Server.ListUrl)
        self.L = Locations.Current
        self.Target = os.path.join(self.Env.Root, "Apps", "RAMMIT")

    def tearDown(self):
        self.Server.Stop()
        self.Env.Cleanup()

    def Install(self, Version, Path=None, **Options):
        Release = Releases.FindRelease(Releases.FetchReleases(), Version)
        return Setup.RunInstall(Version, Path or self.Target, NoReport, Release=Release, **Options)


# ------------------------------------------------------------------------------------------------ zip safety

class TestZipSafety(InstallerTestCase):
    def test_member_names_that_escape_are_rejected(self):
        for Name in ("../evil.txt", "RAMMIT/../../evil.txt", "/abs.txt", "\\abs.txt", "C:/Windows/evil.dll",
                     "RAMMIT\\..\\..\\evil.txt", "RAMMIT/CON", "RAMMIT/nul.txt", "RAMMIT/a\x00b", "RAMMIT/trail. "):
            with self.subTest(Name=Name), self.assertRaises(Setup.SetupError):
                Setup.CheckMemberName(Name)
        self.assertEqual(Setup.CheckMemberName("RAMMIT/Src/./Dark/a.js"), "RAMMIT/Src/Dark/a.js")

    def MakeZip(self, Entries):
        Path = os.path.join(self.Env.Root, "Evil.zip")
        with zipfile.ZipFile(Path, "w") as Zip:
            for Name, Data in Entries:
                Info = zipfile.ZipInfo(Name)
                Zip.writestr(Info, Data)
        return Path

    def test_zip_with_escaping_entry_writes_nothing(self):
        Staging = os.path.join(self.Env.Root, "Apps", "RAMMIT.Staging")
        ZipPath = self.MakeZip([("RAMMIT/RAMMIT.exe", "x"), ("RAMMIT/../../Escaped.txt", "pwned")])
        with self.assertRaises(Setup.SetupError) as Caught:
            Setup.ExtractToStaging(ZipPath, Staging)
        self.assertIn("unsafe", str(Caught.exception))
        self.assertFalse(os.path.exists(Staging))
        self.assertFalse(os.path.exists(os.path.join(self.Env.Root, "Escaped.txt")))

    def test_zip_without_rammit_exe_is_refused(self):
        ZipPath = self.MakeZip([("RAMMIT/README.txt", "hi")])
        with self.assertRaises(Setup.SetupError):
            Setup.ExtractToStaging(ZipPath, os.path.join(self.Env.Root, "S.Staging"))

    def test_only_the_rammit_folder_is_extracted(self):
        ZipPath = os.path.join(self.Env.Root, "Good.zip")
        with open(ZipPath, "wb") as File:
            File.write(Support.MakeAppZip("1.0.0"))
        Staging = os.path.join(self.Env.Root, "Out.Staging")
        Files = Setup.ExtractToStaging(ZipPath, Staging)
        self.assertIn("RAMMIT.exe", Files)
        self.assertIn("Src/Dark/HTML/Index.html", Files)
        self.assertFalse(any(Rel.startswith("Source") for Rel in Files))
        self.assertTrue(os.path.isfile(os.path.join(Staging, "Runtime", "python313.dll")))


# ------------------------------------------------------------------------------------------------ downloads

class TestDownloads(InstallerTestCase):
    ReleaseSpecs = InstallerTestCase.ReleaseSpecs + [{"Version": "2.0.0", "BadSha": True}]

    def test_sha_mismatch_is_rejected_and_nothing_installed(self):
        with self.assertRaises(Releases.ReleaseError) as Caught:
            self.Install("2.0.0")
        self.assertIn("checksum", str(Caught.exception))
        self.assertIn("mismatch", Caught.exception.Details)
        self.assertFalse(os.path.exists(self.Target))
        self.assertFalse(os.path.exists(self.Target + Setup.StagingSuffix))

    def test_sha_file_parsing(self):
        Hex = "ab" * 32
        self.assertEqual(Releases.ParseShaFile(f"{Hex}  RAMMIT-1.0.0.zip\n", "RAMMIT-1.0.0.zip"), Hex)
        self.assertEqual(Releases.ParseShaFile(Hex.upper(), "RAMMIT-1.0.0.zip"), Hex)
        with self.assertRaises(Releases.ReleaseError):
            Releases.ParseShaFile(f"{Hex}  RAMMIT-9.9.9.zip", "RAMMIT-1.0.0.zip")
        with self.assertRaises(Releases.ReleaseError):
            Releases.ParseShaFile("not a hash", "RAMMIT-1.0.0.zip")

    def test_download_links_to_other_hosts_are_refused(self):
        os.environ.pop("RAMMIT_INSTALLER_RELEASES_URL")
        Locations.Reload()
        with self.assertRaises(Releases.ReleaseError):
            Releases._CheckUrl("http://github.com/x.zip")
        with self.assertRaises(Releases.ReleaseError):
            Releases._CheckUrl("https://evil.example/x.zip")
        Releases._CheckUrl("https://github.com/OWNER/RAMMIT/releases/download/v1.0.0/RAMMIT-1.0.0.zip")
        Releases._CheckUrl("https://objects.githubusercontent.com/abc")

    def test_offline_gives_a_friendly_error(self):
        self.Server.Offline = True
        with self.assertRaises(Releases.ReleaseError) as Caught:
            Releases.FetchReleases()
        self.assertIn("Couldn't reach GitHub", str(Caught.exception))


# ------------------------------------------------------------------------------------------------ versions

class TestVersions(unittest.TestCase):
    def test_version_ordering(self):
        P = Releases.ParseVersion
        self.assertGreater(P("1.10.0"), P("1.9.0"))
        self.assertGreater(P("v1.1.0"), P("1.1.0-beta.2"))
        self.assertGreater(P("1.1.0-beta.10"), P("1.1.0-beta.2"))
        self.assertGreater(P("1.1.0-rc.1"), P("1.1.0-beta.9"))
        for Bad in ("", "1.0", "latest", "1.0.0.0", "v1.0.0 ", "1.0.0-", "../1.0.0"):
            self.assertIsNone(P(Bad), Bad)

    def test_release_list_parsing(self):
        def Rel(Tag, **Extra):
            Version = Tag.lstrip("v")
            Assets = [{"name": f"RAMMIT-{Version}.zip", "browser_download_url": f"https://github.com/o/r/releases/download/{Tag}/RAMMIT-{Version}.zip", "size": 10},
                      {"name": f"RAMMIT-{Version}.zip.sha256", "browser_download_url": "https://github.com/x.sha256"}]
            return dict({"tag_name": Tag, "draft": False, "prerelease": False, "assets": Assets, "published_at": "2026-11-02T00:00:00Z"}, **Extra)
        Data = [Rel("v1.0.0"), Rel("v1.2.0-beta.1", prerelease=True), Rel("v1.1.0"), Rel("v1.3.0", draft=True),
                Rel("nightly"), Rel("v0.9.0", assets=[]), Rel("v1.1.1-rc.1"), "junk"]
        Parsed = Releases.ParseReleases(Data)
        self.assertEqual([R["Version"] for R in Parsed], ["1.2.0-beta.1", "1.1.1-rc.1", "1.1.0", "1.0.0"])
        self.assertEqual([R["Prerelease"] for R in Parsed], [True, True, False, False])  # "-rc" counts as a test build
        self.assertEqual(Releases.LatestStable(Parsed)["Version"], "1.1.0")
        self.assertEqual(Parsed[2]["Published"], "2026-11-02")
        with self.assertRaises(Releases.ReleaseError):
            Releases.ParseReleases({"message": "Not Found"})


class TestListVersionsApi(InstallerTestCase):
    def test_prereleases_hidden_unless_asked(self):
        Api = InstallerApi.InstallerApi()
        Normal = Api.ListVersions(False)
        self.assertEqual([V["Version"] for V in Normal["Versions"]], ["1.1.0", "1.0.0", "0.9.0"])
        self.assertEqual(Normal["Latest"], "1.1.0")
        self.assertTrue(Normal["Versions"][0]["Latest"])
        WithTest = Api.ListVersions(True)
        self.assertEqual(WithTest["Versions"][0], {"Version": "1.2.0-beta.1", "Branch": "Dev", "Prerelease": True, "Latest": False,
                                                   "Installed": False, "Published": "2026-11-02"})
        self.assertEqual({V["Branch"] for V in Normal["Versions"]}, {"Stable"})
        self.assertEqual(Api.ListVersions("yes"), {"Error": "Bad request."})

    def test_update_available_flag(self):
        Api = InstallerApi.InstallerApi()
        self.Install("1.0.0", self.L.DefaultInstallPath)
        self.assertTrue(Api.ListVersions(False)["UpdateAvailable"])
        self.Install("1.1.0", self.L.DefaultInstallPath)
        self.assertFalse(Api.ListVersions(False)["UpdateAvailable"])


# ------------------------------------------------------------------------------------------------ install + swap

class TestInstallAndSwap(InstallerTestCase):
    def test_fresh_install_writes_manifest_registry_entry_and_shortcuts(self):
        Result = self.Install("1.0.0")
        self.assertEqual(Result["Warnings"], [])
        Manifest = Setup.ReadManifest(self.Target)
        self.assertEqual(Manifest["Version"], "1.0.0")
        self.assertIn("RAMMIT.exe", Manifest["Files"])
        self.assertEqual(Read(os.path.join(self.Target, "RAMMIT.exe")), "fake RAMMIT exe 1.0.0")
        self.assertEqual(Setup.RegRead("InstallPath"), self.Target)
        self.assertEqual(Setup.RegRead("Version"), "1.0.0")
        Entry = Support.RegValues(self.L.UninstallKeyPath)
        self.assertEqual(Entry["DisplayVersion"], "1.0.0")
        self.assertIn("/Uninstall", Entry["UninstallString"])
        self.assertEqual(Entry["InstallLocation"], self.Target)
        for LinkPath in Setup.ShortcutPaths():  # open RAMMIT:, which starts this install's RAMMIT.exe
            self.assertEqual(Setup.ReadUrlShortcut(LinkPath), self.L.ProtocolName + ":")
        self.assertTrue(Paths.SamePath(Setup.ProtocolTarget(), os.path.join(self.Target, "RAMMIT.exe")), Setup.ProtocolTarget())
        self.assertFalse(os.path.exists(self.Target + Setup.StagingSuffix))
        self.assertFalse(os.path.exists(os.path.join(self.Target, Setup.StagingMarker)))
        self.assertEqual(Setup.CachedRelease("Installed")["Version"], "1.0.0")

    def test_update_keeps_config_and_user_files(self):
        self.Install("1.0.0")
        Write(os.path.join(self.Target, "Config", "Settings.json"), '{"Theme": "Dark"}')
        Write(os.path.join(self.Target, "Src", "MyTheme", "Style.css"), "body{}")
        Write(os.path.join(self.Target, "Notes.txt"), "mine")
        self.Install("1.1.0")
        self.assertEqual(Read(os.path.join(self.Target, "RAMMIT.exe")), "fake RAMMIT exe 1.1.0")
        self.assertEqual(Read(os.path.join(self.Target, "Config", "Settings.json")), '{"Theme": "Dark"}')
        self.assertEqual(Read(os.path.join(self.Target, "Src", "MyTheme", "Style.css")), "body{}")
        self.assertEqual(Read(os.path.join(self.Target, "Notes.txt")), "mine")
        self.assertFalse(os.path.exists(self.Target + Setup.OldSuffix))
        Backups = os.listdir(os.path.join(self.Target, "Config.Backup"))
        self.assertEqual(len(Backups), 1)
        self.assertTrue(Backups[0].startswith("1.0.0-"))

    def test_file_removed_from_the_new_build_disappears(self):
        self.Server.Releases.append({"Version": "1.5.0", "Zip": Support.MakeAppZip("1.5.0", Extra={"Old.dll": "x"})})
        self.Install("1.5.0")
        self.Install("1.1.0")
        self.assertFalse(os.path.exists(os.path.join(self.Target, "Old.dll")))

    def test_swap_failure_during_carry_over_rolls_back(self):
        self.Install("1.0.0")
        Write(os.path.join(self.Target, "Config", "Accounts.json"), '[{"username": "Fake"}]')
        Write(os.path.join(self.Target, "Config", "Settings.json"), "{}")
        Before = {Rel: Read(os.path.join(self.Target, *Rel.split("/"))) for Rel in
                  ("RAMMIT.exe", "Config/Accounts.json", "Config/Settings.json")}
        Original, Calls = Setup._MoveFile, []

        def FailingMove(Source, Destination):
            Calls.append(Source)
            if len(Calls) == 4:  # Install->Old, Staging->Install, first carried file, then fail
                raise OSError("simulated: file in use")
            Original(Source, Destination)
        Setup._MoveFile = FailingMove
        try:
            with self.assertRaises(Setup.SetupError) as Caught:
                self.Install("1.1.0")
        finally:
            Setup._MoveFile = Original
        self.assertIn("put back", str(Caught.exception))
        After = {Rel: Read(os.path.join(self.Target, *Rel.split("/"))) for Rel in Before}
        self.assertEqual(After, Before)
        self.assertEqual(Setup.ReadManifest(self.Target)["Version"], "1.0.0")
        self.assertFalse(os.path.exists(self.Target + Setup.OldSuffix))
        self.assertFalse(os.path.exists(self.Target + Setup.StagingSuffix))

    def test_swap_failure_when_folder_in_use_changes_nothing(self):
        self.Install("1.0.0")
        Original = Setup._MoveFile

        def Locked(Source, Destination):
            if os.path.normcase(Source) == os.path.normcase(self.Target):
                raise PermissionError("simulated: folder in use")
            Original(Source, Destination)
        Setup._MoveFile = Locked
        try:
            with self.assertRaises(Setup.SetupError) as Caught:
                self.Install("1.1.0")
        finally:
            Setup._MoveFile = Original
        self.assertIn("in use", str(Caught.exception))
        self.assertEqual(Setup.ReadManifest(self.Target)["Version"], "1.0.0")
        self.assertFalse(os.path.exists(self.Target + Setup.StagingSuffix))

    def test_interrupted_swap_is_recovered(self):
        self.Install("1.0.0")
        Write(os.path.join(self.Target, "Config", "Settings.json"), "keep")
        os.rename(self.Target, self.Target + Setup.OldSuffix)  # as if power went off mid-swap
        self.assertEqual(Setup.InstalledState()["Version"], "1.0.0")
        self.assertEqual(Read(os.path.join(self.Target, "Config", "Settings.json")), "keep")

    def test_foreign_folder_is_refused_and_leftover_config_accepted(self):
        Write(os.path.join(self.Target, "Homework.docx"), "not RAMMIT")
        with self.assertRaises(Setup.SetupError):
            self.Install("1.0.0")
        self.assertEqual(os.listdir(self.Target), ["Homework.docx"])
        shutil.rmtree(self.Target)
        Write(os.path.join(self.Target, "Config", "Settings.json"), "from last time")
        self.Install("1.0.0")
        self.assertEqual(Read(os.path.join(self.Target, "Config", "Settings.json")), "from last time")

    def test_install_paths_are_validated(self):
        Bad = ["", "relative\\RAMMIT", "\\\\server\\share\\RAMMIT", "C:\\", "C:\\Windows\\RAMMIT", "C:\\Apps\\RAM|MIT",
               "C:\\Apps\\CON\\RAMMIT", "C:\\Apps\\RAMMIT.", self.L.SetupDir, os.path.join(self.L.SetupDir, "X"), 42]
        for Path in Bad:
            with self.subTest(Path=Path), self.assertRaises(Setup.SetupError):
                Setup.NormalizeInstallPath(Path)
        self.assertEqual(Setup.NormalizeInstallPath(' "C:/Apps/RAMMIT" '), "C:\\Apps\\RAMMIT")


# ------------------------------------------------------------------------------------------------ uninstall

class TestUninstall(InstallerTestCase):
    def test_manifest_only_uninstall_never_deletes_unknown_files(self):
        self.Install("1.0.0")
        Write(os.path.join(self.Target, "Config", "Accounts.json"), '[{"username": "Fake"}]')
        Write(os.path.join(self.Target, "Notes.txt"), "mine")
        Write(os.path.join(self.Target, "Src", "MyTheme", "Style.css"), "body{}")
        Result = Setup.RunUninstall(self.Target, False, NoReport)
        self.assertTrue(Result["ConfigKept"])
        self.assertEqual(Result["Left"], ["Notes.txt", "Src"])
        self.assertTrue(os.path.isfile(os.path.join(self.Target, "Notes.txt")))
        self.assertTrue(os.path.isfile(os.path.join(self.Target, "Src", "MyTheme", "Style.css")))
        self.assertTrue(os.path.isfile(os.path.join(self.Target, "Config", "Accounts.json")))
        self.assertFalse(os.path.exists(os.path.join(self.Target, "RAMMIT.exe")))
        self.assertFalse(os.path.exists(os.path.join(self.Target, "Src", "Dark")))
        self.assertFalse(os.path.exists(os.path.join(self.Target, Setup.ManifestName)))
        # Config kept: the key holds ONLY the pointer back to it, so a reinstall can find the accounts
        self.assertEqual(Support.RegValues(self.L.RegKeyPath), {Setup.KeptValue: self.Target})
        self.assertIsNone(Support.RegValues(self.L.UninstallKeyPath))
        self.assertFalse(any(os.path.exists(P) for P in Setup.ShortcutPaths()))
        self.assertIsNone(Support.RegValues(self.L.ProtocolKeyPath))  # RAMMIT: goes too
        self.assertFalse(os.path.exists(self.L.CacheDir))

    def test_shortcuts_removed_when_paths_differ_only_by_short_names(self):
        # GitHub's runner has TEMP = C:\Users\RUNNER~1\...; an old .lnk stores the long form. Same folder, so remove.
        import ctypes
        Long = os.path.join(os.path.dirname(self.Target), "RAMMIT Long Folder Name")
        os.makedirs(Long, exist_ok=True)
        Buffer = ctypes.create_unicode_buffer(1024)
        ctypes.windll.kernel32.GetShortPathNameW(Long, Buffer, 1024)
        Short = Buffer.value
        if not Short or os.path.normcase(Short) == os.path.normcase(Long):
            self.skipTest("this drive doesn't make 8.3 short names")
        for LinkPath in Setup.LinkPaths():
            Support.MakeOldShortcut(LinkPath, os.path.join(Long, "RAMMIT.exe"))
        Setup.RemoveShortcuts(Short)
        self.assertFalse(any(os.path.exists(P) for P in Setup.LinkPaths()))

    def test_ShortcutsOpenTheProtocolAndReplaceOldLinks(self):
        Old = Setup.LinkPaths()
        for LinkPath in Old:  # an install from before 1.2.0: .lnk files straight at RAMMIT.exe
            Support.MakeOldShortcut(LinkPath, os.path.join(self.Target, "RAMMIT.exe"))
        Elsewhere = os.path.join(self.Env.Root, "Mine", "RAMMIT.lnk")  # one the user made: never touched
        Support.MakeOldShortcut(Elsewhere, os.path.join(self.Target, "RAMMIT.exe"))
        self.Install("1.0.0")
        self.assertFalse(any(os.path.exists(P) for P in Old))
        self.assertTrue(os.path.isfile(Elsewhere))
        self.assertTrue(all(Setup.IsOurShortcut(P) for P in Setup.ShortcutPaths()))
        Values = Support.RegValues(self.L.ProtocolKeyPath)
        self.assertEqual((Values[""], Values["URL Protocol"]), ("URL:" + self.L.ProtocolName, ""))
        Command = Support.RegValues(self.L.ProtocolKeyPath + r"\shell\open\command")[""]
        self.assertEqual(Command, '"' + os.path.join(self.Target, "RAMMIT.exe") + '"')  # nothing from the link (no %1)
        self.assertTrue(os.path.isfile(self.L.IconPath))  # the icon is a copy in RAMMIT-Setup\, which never moves
        with open(Setup.ShortcutPath("Desktop"), encoding="mbcs") as File:
            self.assertIn("IconFile=" + self.L.IconPath + "\n", File.read())
        Somebody = os.path.join(self.L.DesktopDir, "Other.url")  # not ours: uninstall leaves it alone
        with open(Somebody, "w") as File:
            File.write("[InternetShortcut]\nURL=https://example.com/\n")
        Setup.RunUninstall(self.Target, True, NoReport)
        self.assertTrue(os.path.isfile(Somebody))
        self.assertFalse(any(os.path.exists(P) for P in Setup.ShortcutPaths()))
        self.assertIsNone(Support.RegValues(self.L.ProtocolKeyPath))
        self.assertFalse(os.path.exists(self.L.IconPath))

    def test_ShortcutIconPathOutsideTheAnsiCodePageFallsBackToTheDefaultIcon(self):
        # An emoji: no Windows ANSI code page can write it, whatever language this PC is set to
        with mock.patch.object(Setup, "_ShortcutIcon", return_value="C:\\Users\\\U0001F600\\RAMMIT.ico"):
            Setup.CreateShortcuts(self.Target, ["Desktop"])
        with open(Setup.ShortcutPath("Desktop"), encoding="mbcs") as File:
            Text = File.read()
        self.assertTrue(Setup.IsOurShortcut(Setup.ShortcutPath("Desktop")))  # it still opens RAMMIT
        self.assertNotIn("IconFile", Text)  # a "?"-mangled icon path would be worse than the default icon

    def test_ShortcutsAreTheTickedOnesAndUpdatesKeepTheChoice(self):
        Desktop, StartMenu = Setup.ShortcutPath("Desktop"), Setup.ShortcutPath("StartMenu")
        self.assertEqual(self.Install("1.0.0", Shortcuts=["StartMenu"])["Shortcuts"], ["StartMenu"])
        self.assertEqual((os.path.isfile(Desktop), os.path.isfile(StartMenu)), (False, True))
        self.assertEqual(Setup.RegRead(Setup.ShortcutsValue), "StartMenu")
        self.Install("1.1.0", Kind="Update")  # no choice passed: the one made at install
        self.assertEqual((os.path.isfile(Desktop), os.path.isfile(StartMenu)), (False, True))
        os.remove(StartMenu)
        self.assertEqual(self.Install("1.1.0", Shortcuts=[])["Shortcuts"], [])  # neither ticked
        self.assertEqual((os.path.isfile(Desktop), os.path.isfile(StartMenu)), (False, False))
        Setup.RegDeleteValue(Setup.ShortcutsValue)  # an install from before the choice existed: both, as always
        self.assertEqual(Setup.ChosenShortcuts(), ["Desktop", "StartMenu"])

    def test_uninstall_with_config_removes_config_and_backups_only(self):
        self.Install("1.0.0")
        Write(os.path.join(self.Target, "Config", "Settings.json"), "{}")
        self.Install("1.1.0")  # makes a Config.Backup
        Write(os.path.join(self.Target, "Notes.txt"), "mine")
        Result = Setup.RunUninstall(self.Target, True, NoReport)
        self.assertFalse(Result["ConfigKept"])
        self.assertEqual(sorted(os.listdir(self.Target)), ["Notes.txt", Setup.UninstalledMarker])
        self.assertEqual(Setup.Classify(self.Target), "Leftover")  # so a reinstall may use it again
        self.Install("1.1.0")
        self.assertEqual(Read(os.path.join(self.Target, "Notes.txt")), "mine")
        self.assertFalse(os.path.exists(os.path.join(self.Target, Setup.UninstalledMarker)))

    def test_clean_uninstall_removes_the_folder(self):
        self.Install("1.0.0")
        Setup.RunUninstall(self.Target, True, NoReport)
        self.assertFalse(os.path.exists(self.Target))

    def test_full_uninstall_leaves_no_registry_key_and_no_setup_folder(self):
        self.Install("1.0.0")
        Legacy.Ignore(True)
        Write(self.L.LogFile, "old log")
        Write(self.L.LogFile + ".1", "older log")
        Setup.RunUninstall(self.Target, True, NoReport)
        self.assertIsNone(Support.RegValues(self.L.RegKeyPath))
        self.assertFalse(os.path.exists(self.L.SetupDir))
        self.assertIsNone(Setup.FindKeptConfig())

    def test_tidy_registry_removes_empty_parent_but_never_a_used_one(self):
        Parent = self.L.RegKeyPath.rsplit("\\", 1)[0]
        Sibling = Parent + "\\RAMMIT-InstallerTest-Sibling"
        Setup.RegWrite("Version", "1.0.0")
        Setup.RegDeleteValue("Version")
        winreg.CreateKey(winreg.HKEY_CURRENT_USER, Sibling).Close()
        try:
            Setup.TidyRegistry()
            self.assertIsNone(Support.RegValues(self.L.RegKeyPath))
            self.assertIsNotNone(Support.RegValues(Parent))  # someone else's key lives under it
        finally:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, Sibling)

    def test_shortcut_to_something_else_is_left_alone(self):
        self.Install("1.0.0")
        Other = Setup.ShortcutPaths()[0]  # a RAMMIT.url that opens something else
        Write(Other, "[InternetShortcut]\nURL=https://example.com/\n")
        Lnk = Setup.LinkPaths()[0]  # and a RAMMIT.lnk that isn't straight at this RAMMIT.exe
        Support.MakeLegacyShortcut(Lnk)
        Setup.RunUninstall(self.Target, True, NoReport)
        self.assertTrue(os.path.isfile(Other))
        self.assertTrue(os.path.isfile(Lnk))


# ------------------------------------------------------------------------------------------------ kept accounts

class TestKeptConfig(InstallerTestCase):
    """Uninstall keeping Config, then install again (any folder, bring back or start fresh), plus Test1's leftovers."""

    def setUp(self):
        super().setUp()
        self.Other = os.path.join(self.Env.Root, "Elsewhere", "RAMMIT")

    def KeepAndUninstall(self):
        self.Install("1.0.0")
        Write(os.path.join(self.Target, "Config", "Accounts.json"), '[{"Username": "KeptTester"}]')
        self.Install("1.1.0")  # makes a Config.Backup too
        Setup.RunUninstall(self.Target, False, NoReport)
        return Setup.FindKeptConfig()

    def test_found_and_offered_after_uninstall(self):
        Kept = self.KeepAndUninstall()
        self.assertEqual((Kept["Path"], Kept["Accounts"], Kept["Test1"], Kept["Installable"]), (self.Target, True, False, True))
        State = InstallerApi.InstallerApi().GetState()
        self.assertEqual(State["KeptConfig"], {"Path": self.Target, "Accounts": True, "Test1": False})
        self.assertEqual(State["DefaultPath"], self.Target)  # not the default folder: the accounts are here

    def test_reinstall_elsewhere_brings_accounts_and_backups_and_removes_the_old_folder(self):
        Kept = self.KeepAndUninstall()
        Result = self.Install("1.1.0", Path=self.Other, Kept=Kept, UseKept=True)
        self.assertIn("came back", Result["KeptLine"])
        self.assertIn("KeptTester", Read(os.path.join(self.Other, "Config", "Accounts.json")))
        self.assertEqual(len(os.listdir(os.path.join(self.Other, "Config.Backup"))), 1)
        self.assertFalse(os.path.exists(self.Target))
        self.assertEqual(set(Support.RegValues(self.L.RegKeyPath)), {"InstallPath", "Version", "Shortcuts"})
        self.assertIsNone(Setup.FindKeptConfig())

    def test_reinstall_same_folder_fresh_puts_accounts_aside(self):
        Kept = self.KeepAndUninstall()
        Result = self.Install("1.1.0", Kept=Kept, UseKept=False)
        self.assertIn("put aside", Result["KeptLine"])
        self.assertFalse(os.path.exists(os.path.join(self.Target, "Config")))
        Aside = [N for N in os.listdir(os.path.join(self.Target, "Config.Backup")) if N.startswith("Earlier-")]
        self.assertEqual(len(Aside), 1)
        self.assertIn("KeptTester", Read(os.path.join(self.Target, "Config.Backup", Aside[0], "Accounts.json")))
        self.assertIsNone(Setup.RegRead(Setup.KeptValue))

    def test_reinstall_elsewhere_fresh_leaves_the_old_folder(self):
        Kept = self.KeepAndUninstall()
        Result = self.Install("1.1.0", Path=self.Other, Kept=Kept, UseKept=False)
        self.assertIn(self.Target, Result["KeptLine"])
        self.assertTrue(os.path.isfile(os.path.join(self.Target, "Config", "Accounts.json")))
        self.assertFalse(os.path.exists(os.path.join(self.Other, "Config")))
        self.assertIsNone(Setup.RegRead(Setup.KeptValue))

    def test_clash_with_accounts_already_in_the_target(self):
        Kept = self.KeepAndUninstall()
        Write(os.path.join(self.Other, "Config", "Accounts.json"), '[{"Username": "AlreadyThere"}]')
        self.assertTrue(Setup.KeptConfigNeedsChoice(Kept, self.Other))
        self.assertFalse(Setup.KeptConfigNeedsChoice(Kept, self.Target))
        self.assertTrue(InstallerApi.InstallerApi().CheckInstall(self.Other, "", "Use")["NeedsConfigChoice"])
        self.Install("1.1.0", Path=self.Other, Kept=Kept, UseKept=True, ConfigChoice="KeepNew")
        self.assertIn("AlreadyThere", Read(os.path.join(self.Other, "Config", "Accounts.json")))
        Aside = [N for N in os.listdir(os.path.join(self.Other, "Config.Backup")) if N.startswith("Earlier-")]
        self.assertIn("KeptTester", Read(os.path.join(self.Other, "Config.Backup", Aside[0], "Accounts.json")))

    def test_folder_deleted_by_hand_forgets_the_pointer(self):
        self.KeepAndUninstall()
        shutil.rmtree(self.Target)
        self.assertIsNone(Setup.FindKeptConfig())
        self.assertIsNone(Support.RegValues(self.L.RegKeyPath))

    def test_test1_uninstall_leftovers_are_found_and_cleaned(self):
        Old = os.path.join(self.Env.Root, "Test1Left")
        Write(os.path.join(Old, "Config", "Accounts.json"), '[{"Username": "Test1Kept"}]')
        Setup.RegWrite(Setup.Test1ConfigValue, os.path.join(Old, "Config"))
        Setup.RegWrite(Setup.Test1CleanupValue, Old)
        Kept = Setup.FindKeptConfig()
        self.assertEqual((Kept["Path"], Kept["Test1"], Kept["Accounts"]), (Old, True, True))
        self.Install("1.1.0", Kept=Kept, UseKept=True)
        self.assertIn("Test1Kept", Read(os.path.join(self.Target, "Config", "Accounts.json")))
        self.assertFalse(os.path.exists(Old))
        self.assertIsNone(Setup.RegRead(Setup.Test1ConfigValue))
        self.assertIsNone(Setup.RegRead(Setup.Test1CleanupValue))

    def test_branch_recorded(self):
        self.Install("1.2.0-beta.1")
        self.assertEqual(Setup.ReadManifest(self.Target)["Branch"], "Dev")
        self.assertEqual(Setup.InstalledState()["Branch"], "Dev")
        self.Install("1.1.0")
        self.assertEqual(Setup.ReadManifest(self.Target)["Branch"], "Stable")
        self.assertEqual(Setup.CachedRelease("Previous")["Branch"], "Dev")


# ------------------------------------------------------------------------------------------------ backups + undo

class TestBackupsAndVersions(InstallerTestCase):
    def test_backup_rotation_keeps_five(self):
        os.makedirs(self.Target)
        Write(os.path.join(self.Target, "Config", "Settings.json"), "{}")
        Write(os.path.join(self.Target, "Config.Backup", "MyOwnFolder", "x.txt"), "not a backup")
        Made = [os.path.basename(Setup.BackupConfig(self.Target, f"1.0.{N}")) for N in range(7)]
        Left = sorted(os.listdir(os.path.join(self.Target, "Config.Backup")))
        self.assertIn("MyOwnFolder", Left)
        Left.remove("MyOwnFolder")
        self.assertEqual(sorted(Left), sorted(Made[-5:]))

    def test_downgrade_backs_up_and_undo_works_offline(self):
        self.Install("1.1.0")
        Write(os.path.join(self.Target, "Config", "Settings.json"), "made on 1.1.0")
        self.Install("1.0.0")
        self.assertEqual(Setup.ReadManifest(self.Target)["Version"], "1.0.0")
        self.assertEqual(Read(os.path.join(self.Target, "Config", "Settings.json")), "made on 1.1.0")
        Backup = os.listdir(os.path.join(self.Target, "Config.Backup"))[0]
        self.assertTrue(Backup.startswith("1.1.0-"))
        self.assertEqual(Setup.UndoVersion("1.0.0"), "1.1.0")
        self.Server.Offline = True
        Setup.RunInstall("1.1.0", self.Target, NoReport, CachedSlot="Previous", Kind="Undo")
        self.assertEqual(Setup.ReadManifest(self.Target)["Version"], "1.1.0")
        self.assertEqual(Setup.UndoVersion("1.1.0"), "1.0.0")  # undo can be undone

    def test_tampered_cache_is_refused(self):
        self.Install("1.0.0")
        self.Install("1.1.0")
        Cached = Setup.CachedRelease("Previous")
        with open(Cached["ZipPath"], "ab") as File:
            File.write(b"tampered")
        with self.assertRaises(Releases.ReleaseError):
            Setup.RunInstall("1.0.0", self.Target, NoReport, CachedSlot="Previous", Kind="Undo")
        self.assertEqual(Setup.ReadManifest(self.Target)["Version"], "1.1.0")


# ------------------------------------------------------------------------------------------------ Test1 installs

class TestLegacy(InstallerTestCase):
    def setUp(self):
        super().setUp()
        self.Old = os.path.join(self.Env.Root, "OldRAMMIT")
        Support.MakeLegacyInstall(self.Old)
        Setup.RegWrite("InstallPath", self.Old)
        Setup.RegWrite("Version", "1.0.0")
        Setup.RegWrite("ConfigPath", "x")
        for LinkPath in Setup.LinkPaths():
            Support.MakeLegacyShortcut(LinkPath)

    def test_detection(self):
        Found = Legacy.Detect()
        self.assertEqual(Found["Path"], self.Old)
        self.assertEqual(Found["Version"], "1.0.0")
        self.assertEqual(len(Found["Shortcuts"]), 2)
        self.assertEqual(Setup.Classify(self.Old), "Legacy")
        State = InstallerApi.InstallerApi().GetState()
        self.assertFalse(State["Installed"])
        self.assertEqual(State["Legacy"], {"Path": self.Old, "Version": "1.0.0", "Deferred": False})

    def test_choice1_move_and_remove_into_another_folder(self):
        Result = self.Install("1.1.0", LegacyMode="MoveRemove", LegacyPath=self.Old)
        self.assertTrue(Result["MovedLegacy"])
        Config = os.path.join(self.Target, "Config")
        self.assertEqual(sorted(os.listdir(Config)), ["Accounts.json", "Settings.json"])
        self.assertIn("OldTester", Read(os.path.join(Config, "Accounts.json")))
        self.assertFalse(os.path.exists(self.Old))
        self.assertEqual(Setup.RegRead("InstallPath"), self.Target)
        self.assertIsNone(Setup.RegRead("ConfigPath"))
        self.assertFalse(any(os.path.exists(P) for P in Setup.LinkPaths()))  # PowerShell shortcuts replaced by RAMMIT: ones
        self.assertTrue(all(Setup.IsOurShortcut(P) for P in Setup.ShortcutPaths()))
        self.assertIsNone(Legacy.Detect())

    def test_choice1_into_the_old_folder_itself(self):
        Check = Setup.CheckTarget(self.Old, "MoveRemove", self.Old)
        self.assertEqual(Check["State"], "Legacy")
        self.Install("1.1.0", Path=self.Old, LegacyMode="MoveRemove", LegacyPath=self.Old)
        self.assertEqual(sorted(os.listdir(self.Old)), sorted(["Config", "Manifest.json", "RAMMIT.exe", "README.txt", "Runtime", "Src"]))
        self.assertFalse(os.path.exists(os.path.join(self.Old, "Src", "Version.json")))
        self.assertFalse(os.path.exists(os.path.join(self.Old, "RAMMIT-Downloader.exe")))
        self.assertIn("OldTester", Read(os.path.join(self.Old, "Config", "Accounts.json")))
        self.assertFalse(os.path.exists(self.Old + Setup.OldSuffix))

    def test_choice1_old_folder_with_other_files_is_refused(self):
        Write(os.path.join(self.Old, "MyStuff.txt"), "mine")
        with self.assertRaises(Setup.SetupError) as Caught:
            Setup.CheckTarget(self.Old, "MoveRemove", self.Old)
        self.assertIn("MyStuff.txt", str(Caught.exception))

    def test_choice2_move_and_keep(self):
        with self.assertRaises(Setup.SetupError):
            Setup.CheckTarget(self.Old, "MoveKeep", self.Old)
        self.Install("1.1.0", LegacyMode="MoveKeep", LegacyPath=self.Old)
        self.assertIn("OldTester", Read(os.path.join(self.Target, "Config", "Accounts.json")))
        self.assertTrue(os.path.isfile(os.path.join(self.Old, "Src", "Version.json")))
        self.assertTrue(os.path.isfile(os.path.join(self.Old, "Config", "accounts.json")))

    def test_choice3_remove_without_moving(self):
        Write(os.path.join(self.Old, "MyStuff.txt"), "mine")
        Result = Legacy.RunRemove(self.Old, lambda **_P: None)
        self.assertEqual(Result["Left"], ["MyStuff.txt"])
        self.assertEqual(os.listdir(self.Old), ["MyStuff.txt"])
        self.assertIsNone(Setup.RegRead("InstallPath"))
        self.assertIsNone(Setup.RegRead("Version"))
        self.assertFalse(any(os.path.exists(P) for P in Setup.LinkPaths()))  # Test1's PowerShell shortcuts
        os.remove(os.path.join(self.Old, "MyStuff.txt"))
        Support.MakeLegacyInstall(self.Old)
        Legacy.RunRemove(self.Old, lambda **_P: None)
        self.assertFalse(os.path.exists(self.Old))

    def test_choice4_ignore(self):
        Legacy.Ignore(False)
        self.assertIsNotNone(Legacy.Detect())
        Legacy.Ignore(True)
        self.assertIsNone(Legacy.Detect())
        with self.assertRaises(Setup.SetupError):  # and its folder still can't be installed over
            Setup.CheckTarget(self.Old)

    def test_Choice4IgnoreWithoutDontAskPutsItOff(self):
        InstallerApi.InstallerApi().IgnoreLegacy(False)
        self.assertEqual(Setup.RegRead("LegacyInstallPath"), self.Old)
        self.assertTrue(Legacy.Detect()["Deferred"])  # the menu opens, with OLD VERSION
        self.Install("1.1.0")  # a new install takes over InstallPath: the old one is still remembered
        State = InstallerApi.InstallerApi().GetState()
        self.assertTrue(State["Installed"])
        self.assertEqual(State["Legacy"], {"Path": self.Old, "Version": "1.0.0", "Deferred": True})
        Legacy.RunRemove(self.Old, lambda **_P: None)  # dealt with: forgotten
        self.assertIsNone(Setup.RegRead("LegacyInstallPath"))
        self.assertIsNone(Legacy.Detect())
        self.assertEqual((Setup.RegRead("InstallPath"), Setup.RegRead("Version")), (self.Target, "1.1.0"))  # the new one's

    def test_OldDontAskAgainStillHonouredWhenItCantBeMoved(self):
        Setup.RegWrite(Legacy.OldIgnoreValue, "1")
        with mock.patch.object(Setup, "RegWrite", side_effect=OSError):
            self.assertIsNone(Legacy.Detect())  # no error on the way into the installer
        self.assertEqual(Setup.RegRead(Legacy.OldIgnoreValue), "1")  # moved over next time instead

    def test_MoveConfigSkipsLinkedFiles(self):
        # Making a real symbolic link needs Developer Mode or admin, so the old accounts file only reports being one.
        Accounts = os.path.join(self.Old, "Config", "accounts.json")
        RealIsLink = os.path.islink
        Destination = os.path.join(self.Env.Root, "NewRAMMIT")
        os.makedirs(Destination)
        with mock.patch.object(Legacy.os.path, "islink", side_effect=lambda P: Paths.SamePath(P, Accounts) or RealIsLink(P)):
            Legacy.MoveConfig(self.Old, Destination)
        self.assertFalse(os.path.exists(os.path.join(Destination, "Config", "Accounts.json")))
        self.assertTrue(os.path.isfile(os.path.join(Destination, "Config", "Settings.json")))  # real files still come

    def test_MoveConfigLeavesALinkedConfigFolderAlone(self):
        import _winapi  # a junction needs no admin rights, unlike a symbolic link
        Outside = os.path.join(self.Env.Root, "Outside")
        os.makedirs(Outside)
        Write(os.path.join(Outside, "accounts.json"), '[{"Username": "NotTheirs"}]')
        shutil.rmtree(os.path.join(self.Old, "Config"))
        _winapi.CreateJunction(Outside, os.path.join(self.Old, "Config"))
        Destination = os.path.join(self.Env.Root, "NewRAMMIT")
        os.makedirs(Destination)
        self.assertEqual(Legacy.MoveConfig(self.Old, Destination), [])
        self.assertFalse(os.path.exists(os.path.join(Destination, "Config")))
        os.rmdir(os.path.join(self.Old, "Config"))  # removes the junction only

    def test_ConfigBackupNeverCopiesWhatALinkPointsAt(self):
        import _winapi
        Outside = os.path.join(self.Env.Root, "Outside")
        os.makedirs(Outside)
        Write(os.path.join(Outside, "Secret.txt"), "not part of the config")
        Config = os.path.join(self.Env.Root, "NewRAMMIT", "Config")
        os.makedirs(Config)
        Write(os.path.join(Config, "Accounts.json"), '[{"Username": "Mine"}]')
        _winapi.CreateJunction(Outside, os.path.join(Config, "Linked"))
        try:
            Backup = Setup.BackupConfig(os.path.dirname(Config), "Test")
            self.assertTrue(os.path.isfile(os.path.join(Backup, "Accounts.json")))
            self.assertFalse(os.path.exists(os.path.join(Backup, "Linked")))
        finally:
            os.rmdir(os.path.join(Config, "Linked"))

    def test_Choice4DontAskAgainForgetsAPutOffOne(self):
        Legacy.Ignore(False, self.Old)
        Legacy.Ignore(True)
        self.assertEqual(Setup.RegRead("LegacyInstallPath"), Legacy.IgnoredForGood)
        self.assertIsNone(Legacy.Detect())

    def test_OldDontAskAgainValueIsCarriedOver(self):
        Setup.RegWrite(Legacy.OldIgnoreValue, "1")  # what installers before 1.2.0 wrote
        self.assertIsNone(Legacy.Detect())
        self.assertIsNone(Setup.RegRead(Legacy.OldIgnoreValue))
        self.assertEqual(Setup.RegRead("LegacyInstallPath"), Legacy.IgnoredForGood)

    def test_Choice2MoveAndKeepForgetsAPutOffOne(self):
        Legacy.Ignore(False, self.Old)
        self.Install("1.1.0", LegacyMode="MoveKeep", LegacyPath=self.Old)
        self.assertIsNone(Setup.RegRead("LegacyInstallPath"))
        self.assertIsNone(Legacy.Detect())
        self.assertTrue(os.path.isfile(os.path.join(self.Old, "Src", "Version.json")))

    def test_MoveIntoInstalledRammitKeepsTheOldOneAndDoesNotReinstall(self):
        self.Install("1.1.0")  # RAMMIT installed, the old version put off with Ignore
        Legacy.Ignore(False, self.Old)
        Api = InstallerApi.InstallerApi()
        self.assertEqual(Api.CheckLegacyMove(), {"Ok": True, "NeedsConfigChoice": False})
        self.assertEqual(Api.StartLegacyMove("Reinstall"), {"Error": "Bad request."})
        Manifest = Setup.ReadManifest(self.Target)
        Result = Legacy.RunMove(self.Old, self.Target, "MoveKeep", "KeepNew", NoReport)
        self.assertEqual((Result["Mode"], Result["InstallPath"]), ("MoveKeep", self.Target))
        self.assertIn("OldTester", Read(os.path.join(self.Target, "Config", "Accounts.json")))
        self.assertEqual(Setup.ReadManifest(self.Target), Manifest)  # nothing reinstalled
        self.assertTrue(os.path.isfile(os.path.join(self.Old, "Src", "Version.json")))  # old one kept
        self.assertEqual((Setup.RegRead("InstallPath"), Setup.RegRead("Version")), (self.Target, "1.1.0"))
        self.assertIsNone(Setup.RegRead("LegacyInstallPath"))
        self.assertIsNone(Legacy.Detect())

    def test_MoveIntoInstalledRammitThenRemoveTheOldOne(self):
        self.Install("1.1.0")
        Legacy.Ignore(False, self.Old)
        Legacy.RunMove(self.Old, self.Target, "MoveRemove", "KeepNew", NoReport)
        self.assertIn("OldTester", Read(os.path.join(self.Target, "Config", "Accounts.json")))
        self.assertFalse(os.path.exists(self.Old))
        self.assertFalse(any(os.path.exists(P) for P in Setup.LinkPaths()))  # Test1's PowerShell shortcuts
        self.assertEqual((Setup.RegRead("InstallPath"), Setup.RegRead("Version")), (self.Target, "1.1.0"))
        self.assertIsNone(Legacy.Detect())

    def test_config_clash_keep_new_or_use_old(self):
        self.Install("1.0.0")
        Write(os.path.join(self.Target, "Config", "Accounts.json"), '[{"username": "NewTester"}]')
        self.assertTrue(Setup.CheckTarget(self.Target, "MoveKeep", self.Old)["NeedsConfigChoice"])
        self.Install("1.1.0", LegacyMode="MoveKeep", LegacyPath=self.Old, ConfigChoice="KeepNew")
        self.assertIn("NewTester", Read(os.path.join(self.Target, "Config", "Accounts.json")))
        Backups = os.listdir(os.path.join(self.Target, "Config.Backup"))
        self.assertTrue(any(B.startswith("Test1-") for B in Backups))
        self.Install("1.0.0", LegacyMode="MoveKeep", LegacyPath=self.Old, ConfigChoice="UseOld")
        self.assertIn("OldTester", Read(os.path.join(self.Target, "Config", "Accounts.json")))
        self.assertTrue(any(B.startswith("Replaced-") for B in os.listdir(os.path.join(self.Target, "Config.Backup"))))


# ------------------------------------------------------------------------------------------------ running RAMMIT

class TestRunning(InstallerTestCase):
    def test_running_rammit_blocks_and_can_be_closed(self):
        self.Install("1.0.0")
        Fake = os.path.join(self.Target, "RAMMIT.exe")
        shutil.copy2(os.path.join(os.environ["SystemRoot"], "System32", "PING.EXE"), Fake)  # a harmless stand-in
        Process = subprocess.Popen([Fake, "-n", "120", "127.0.0.1"], stdout=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            self.assertTrue(Support.WaitUntil(lambda: Setup.FindRunning([self.Target]), 20))
            with self.assertRaises(Setup.SetupError) as Caught:
                self.Install("1.1.0")
            self.assertTrue(Caught.exception.Running)
            self.assertFalse(Setup.FindRunning([os.path.join(self.Env.Root, "Elsewhere")]))
            self.assertEqual(Setup.CloseRunning([self.Target], Timeout=2), 0)
            self.assertIsNotNone(Support.WaitUntil(lambda: Process.poll() is not None, 20))
        finally:
            if Process.poll() is None:
                Process.kill()
        self.Install("1.1.0")


# ------------------------------------------------------------------------------------------------ safety rails

class TestSafetyRails(unittest.TestCase):
    def setUp(self):
        self.Saved = {K: V for K, V in os.environ.items() if K.startswith("RAMMIT_INSTALLER")}

    def tearDown(self):
        for Key in [K for K in os.environ if K.startswith("RAMMIT_INSTALLER")]:
            del os.environ[Key]
        os.environ.update(self.Saved)
        Locations.Reload()

    def test_test_mode_refuses_real_names(self):
        os.environ["RAMMIT_INSTALLER_TEST"] = "1"
        os.environ["RAMMIT_INSTALLER_REGKEY"] = r"Software\CBlock Digital\RAMMIT"
        with self.assertRaises(RuntimeError):
            Locations.Reload()
        os.environ["RAMMIT_INSTALLER_REGKEY"] = r"Software\CBlock Digital\RAMMIT-InstallerTest-X"
        os.environ["RAMMIT_INSTALLER_UNINSTALL_NAME"] = "RAMMIT"
        with self.assertRaises(RuntimeError):
            Locations.Reload()
        os.environ["RAMMIT_INSTALLER_UNINSTALL_NAME"] = "RAMMIT-InstallerTest-X"
        os.environ["RAMMIT_INSTALLER_PROTOCOL"] = "RAMMIT"  # the real RAMMIT: protocol
        with self.assertRaises(RuntimeError):
            Locations.Reload()

    def test_release_override_ignored_outside_test_mode(self):
        os.environ.pop("RAMMIT_INSTALLER_TEST", None)
        os.environ["RAMMIT_INSTALLER_RELEASES_URL"] = "http://127.0.0.1:1/evil"
        Current = Locations.Reload()
        self.assertEqual(Current.ReleasesUrlOverride, "")
        self.assertEqual(Current.RegKeyPath, r"Software\CBlock Digital\RAMMIT")
        self.assertTrue(Releases.ReleasesUrl().startswith("https://api.github.com/repos/"))


class TestApiSurface(InstallerTestCase):
    def test_no_public_state_and_bad_arguments_return_errors(self):
        Api = InstallerApi.InstallerApi()
        Api._AttachWindow(Support.EventWindow())
        Public = [Name for Name in dir(Api) if not Name.startswith("_")]
        self.assertTrue(all(callable(getattr(Api, Name)) for Name in Public), Public)
        self.assertEqual(Api.StartUninstall("yes"), {"Error": "Bad request."})
        self.assertEqual(Api.StartInstall("1.0.0", self.Target, {"Legacy": "Everything"}), {"Error": "Bad request."})
        self.assertEqual(Api.StartInstall("1.0.0", 5), {"Error": "Bad request."})
        self.assertIn("Error", Api.StartChangeVersion("../../1.0.0"))
        self.assertIn("Error", Api.CheckInstall("relative"))
        self.assertEqual(Api.CheckInstall(self.Target, "Nope"), {"Error": "Bad request."})
        self.assertEqual(Api.IgnoreLegacy("1"), {"Error": "Bad request."})
        self.assertIsNone(Api.ResizeInstaller("tall"))
        self.assertIn("Error", Api.Launch())

    def test_ResizeWaitsForLetGoWhileHeld(self):
        Window = Support.EventWindow()
        Window.native = mock.Mock(Height=409, DeviceDpi=96)  # 327 logical px at 125%; DeviceDpi stays 96 (pywebview)
        Api = InstallerApi.InstallerApi()
        Api._AttachWindow(Window)
        Api._LastHeight, Api._Frame = 327, 39
        Api._Dragging = True  # title bar held: only record the height (a resize now would just flicker)
        Api.ResizeInstaller(411, 288)
        self.assertIsNone(Window.LastResize)
        self.assertEqual(Api._LastHeight, 450)
        with mock.patch.object(InstallerApi.InstallerApi, "_SetHeight") as SetHeight, \
                mock.patch.object(InstallerApi.InstallerApi, "_WindowScale", return_value=1.25):
            Api._Dragging = False
            Api._ReapplyHeight()  # what letting go runs
            SetHeight.assert_called_once_with(Window.native, round(450 * 1.25))
            SetHeight.reset_mock()
            Window.native.Height = round(450 * 1.25)  # already right: nothing to do
            Api._ReapplyHeight()
            SetHeight.assert_not_called()

    def test_ResizeWatchesTheTitleBarOnceTheWindowIsUp(self):
        class Event:  # what pythonnet's .NET events and pywebview's events support: += and firing
            def __init__(self):
                self.Handlers = []

            def __iadd__(self, Handler):
                self.Handlers.append(Handler)
                return self

            def Fire(self, *Args):
                for Handler in self.Handlers:
                    Handler(*Args)

        Window = Support.EventWindow()
        Window.events = mock.Mock(shown=Event())
        Window.native = mock.Mock(Height=409, ResizeBegin=Event(), ResizeEnd=Event())
        Api = InstallerApi.InstallerApi()
        Api._AttachWindow(Window)
        Api._LastHeight, Api._Frame = 327, 39
        Window.events.shown.Fire()  # ResizeBegin / ResizeEnd are watched from now on
        Window.native.ResizeBegin.Fire(None, None)  # title bar grabbed
        Api.ResizeInstaller(411, 288)
        self.assertIsNone(Window.LastResize)
        with mock.patch.object(InstallerApi.InstallerApi, "_SetHeight") as SetHeight, \
                mock.patch.object(InstallerApi.InstallerApi, "_WindowScale", return_value=1.25), \
                mock.patch.object(InstallerApi.threading, "Thread", side_effect=lambda target, daemon: mock.Mock(start=target)):
            Window.native.ResizeEnd.Fire(None, None)  # let go: applied once, size only
            SetHeight.assert_called_once_with(Window.native, round(450 * 1.25))
        self.assertFalse(Api._Dragging)
        Api.ResizeInstaller(361, 288)  # not held: straight through
        self.assertEqual(Window.LastResize, [InstallerApi.WindowWidth, 400])


class TestUiServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.Server = UiServer.UiServer(UiServer.LoadEmbeddedUi(Support.InstallerDir)).Start()

    @classmethod
    def tearDownClass(cls):
        cls.Server.Stop()

    def Get(self, Path, Host=None, Method="GET"):
        Connection = http.client.HTTPConnection("127.0.0.1", self.Server.Port, timeout=10)
        Connection.putrequest(Method, Path, skip_host=True)
        Connection.putheader("Host", Host or f"127.0.0.1:{self.Server.Port}")
        Connection.endheaders()
        Response = Connection.getresponse()
        Body = Response.read()
        Connection.close()
        return Response.status, dict(Response.getheaders()), Body

    def test_hardening(self):
        Status, Headers, Body = self.Get("/HTML/Installer.html")
        self.assertEqual(Status, 200)
        self.assertIn("script-src 'self'", Headers["Content-Security-Policy"])
        self.assertEqual(Headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(self.Get("/HTML/Installer.html", Host="evil.example")[0], 403)
        for Path in ("/", "/HTML/", "/../Installer.py", "/%2e%2e/Installer.py", "/HeightMap.json", "/Installer.py", "/HTML\\Installer.html"):
            self.assertEqual(self.Get(Path)[0], 404, Path)
        self.assertGreaterEqual(self.Get("/HTML/Installer.html", Method="PUT")[0], 400)
        for Path in ("/CSS/Installer.css", "/JS/Installer.js", "/Fonts/Phosphor-Bold.woff2", "/RAMMIT-Downloader.png"):
            self.assertEqual(self.Get(Path)[0], 200, Path)

    def test_page_has_no_inline_script_or_handlers(self):
        Html = self.Get("/HTML/Installer.html")[2].decode()
        self.assertNotIn("onclick", Html.lower())
        self.assertEqual(Html.count("<script"), 1)
        self.assertIn('<script type="module" src="../JS/Installer.js"></script>', Html)
        for Name in os.listdir(os.path.join(Support.InstallerDir, "Ui", "JS")):
            self.assertNotRegex(Read(os.path.join(Support.InstallerDir, "Ui", "JS", Name)),
                                r"\.(innerHTML|outerHTML)\s*\+?=|insertAdjacentHTML|eval\(", Name)


if __name__ == "__main__":
    unittest.main()
