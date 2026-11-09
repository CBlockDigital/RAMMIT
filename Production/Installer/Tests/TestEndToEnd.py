"""End-to-end: the real InstallerApi (as the page drives it) against a local fake GitHub release server, into temp
folders, in test mode. One long story, in order:

    install 1.0.0 (the REAL release zip) -> update to 1.1.0 -> downgrade back to 1.0.0 -> undo (offline)
    -> repair (a deleted file comes back) -> uninstall keeping Config -> reinstall finds Config -> uninstall all

Run from Production\\Installer\\:  python -m unittest Tests.TestEndToEnd   (part of the normal discover run too)
"""
import os
import unittest

import Support

import InstallerApi  # noqa: E402
import Locations  # noqa: E402
import Setup  # noqa: E402
from Log import Logger  # noqa: E402

Logger.disabled = True


@unittest.skipUnless(os.path.isfile(Support.RealZip), "real RAMMIT-1.0.0.zip not found")
class TestEndToEnd(unittest.TestCase):
    def setUp(self):
        self.Env = Support.TestEnvironment("E2E")
        self.Server = Support.FakeReleaseServer([
            {"Version": "1.2.0-beta.1", "Prerelease": True, "Zip": Support.MakeAppZip("1.2.0-beta.1")},
            {"Version": "1.1.0", "Zip": Support.MakeAppZip("1.1.0")},
            {"Version": "1.0.0", "ZipFile": Support.RealZip},
        ])
        self.Env.SetReleasesUrl(self.Server.ListUrl)
        self.L = Locations.Current
        self.Window = Support.EventWindow()
        self.Api = InstallerApi.InstallerApi()
        self.Api._AttachWindow(self.Window)
        self.Path = self.L.DefaultInstallPath

    def tearDown(self):
        self.Server.Stop()
        self.Env.Cleanup()

    def Run(self, Start):
        """Calls a Start* method and waits (polling) for its Done/Failed event."""
        Since = len(self.Window.Events)
        Accepted = Start()
        self.assertEqual(Accepted, {"Ok": True})
        Final = Support.WaitUntil(lambda: self.Window.Final(Since), Timeout=180)
        self.assertIsNotNone(Final, "no Done/Failed event")
        Name, Payload = Final
        self.assertEqual(Name, "Done", Payload)
        Progress = [P for N, P in self.Window.Events[Since:] if N in ("Progress", "UninstallProgress")]
        return Payload, Progress

    def File(self, *Parts):
        return os.path.join(self.Path, *Parts)

    def test_full_story(self):
        State = self.Api.GetState()
        self.assertFalse(State["Installed"])
        self.assertIsNone(State["Legacy"])
        self.assertEqual(State["DefaultPath"], self.Path)
        Versions = self.Api.ListVersions(False)
        self.assertEqual([V["Version"] for V in Versions["Versions"]], ["1.1.0", "1.0.0"])

        # ---- install the real 1.0.0 release
        self.assertTrue(self.Api.CheckInstall(self.Path)["Ok"])
        Done, Progress = self.Run(lambda: self.Api.StartInstall("1.0.0", self.Path))
        self.assertEqual((Done["Action"], Done["Version"], Done["Path"], Done["Warnings"]), ("Install", "1.0.0", self.Path, []))
        self.assertEqual([P["Stages"]["Active"] for P in Progress if "Stages" in P], [0, 1, 2, 3])
        self.assertTrue(any("MB /" in P.get("StageDetail", "") for P in Progress), "byte progress shown")
        self.assertEqual(Progress[-1]["OverallPct"], 100)
        Manifest = Setup.ReadManifest(self.Path)
        self.assertEqual(Manifest["Version"], "1.0.0")
        self.assertGreater(len(Manifest["Files"]), 100)
        self.assertTrue(os.path.isfile(self.File("RAMMIT.exe")))
        self.assertTrue(os.path.isdir(self.File("Runtime")))
        self.assertTrue(os.path.isfile(self.File("Src", "Dark", "HTML", "Index.html")))
        self.assertFalse(os.path.exists(self.File("Source")))
        self.assertFalse(os.path.exists(self.File("Config")))
        Reg = Support.RegValues(self.L.RegKeyPath)
        self.assertEqual((Reg["InstallPath"], Reg["Version"]), (self.Path, "1.0.0"))
        Entry = Support.RegValues(self.L.UninstallKeyPath)
        self.assertEqual((Entry["DisplayName"], Entry["DisplayVersion"], Entry["Publisher"]), ("RAMMIT (installer test)", "1.0.0", "CBlock Digital"))
        self.assertGreater(Entry["EstimatedSize"], 10000)
        for LinkPath in Setup.ShortcutPaths():
            self.assertTrue(LinkPath.startswith(self.Env.Root))
            self.assertEqual(Setup.ReadUrlShortcut(LinkPath), self.L.ProtocolName + ":")
        self.assertEqual(os.path.normcase(Setup.ProtocolTarget()), os.path.normcase(self.File("RAMMIT.exe")))
        State = self.Api.GetState()
        self.assertEqual((State["Installed"], State["Version"], State["UndoVersion"]), (True, "1.0.0", ""))
        self.assertTrue(self.Api.ListVersions(False)["UpdateAvailable"])

        # the app's own data from here on: fake account file (no cookie), a custom theme, a stray file
        os.makedirs(self.File("Config"))
        with open(self.File("Config", "Accounts.json"), "w") as File:
            File.write('[{"Username": "E2ETester"}]')
        os.makedirs(self.File("Src", "MyCustomThemeE2E"))
        with open(self.File("Src", "MyCustomThemeE2E", "Theme.json"), "w") as File:
            File.write("{}")

        # ---- update -> 1.1.0 (Update / Downgrade screen, a newer version picked)
        Done, _ = self.Run(lambda: self.Api.StartChangeVersion("1.1.0"))
        self.assertEqual((Done["Kind"], Done["Version"], Done["OldVersion"], Done["UndoVersion"]), ("Update", "1.1.0", "1.0.0", "1.0.0"))
        with open(self.File("RAMMIT.exe")) as File:
            self.assertEqual(File.read(), "fake RAMMIT exe 1.1.0")
        self.assertTrue(os.path.isfile(self.File("Config", "Accounts.json")))
        self.assertTrue(os.path.isfile(self.File("Src", "MyCustomThemeE2E", "Theme.json")))
        self.assertEqual(len(os.listdir(self.File("Config.Backup"))), 1)
        self.assertEqual(Support.RegValues(self.L.UninstallKeyPath)["DisplayVersion"], "1.1.0")
        Listed = {V["Version"]: V for V in self.Api.ListVersions(True)["Versions"]}
        self.assertTrue(Listed["1.1.0"]["Installed"])  # greyed out in the picker
        self.assertEqual((Listed["1.2.0-beta.1"]["Branch"], Listed["1.0.0"]["Branch"]), ("Dev", "Stable"))
        Since = len(self.Window.Events)
        self.Api.StartChangeVersion("1.1.0")  # the installed one: refused
        Name, Payload = Support.WaitUntil(lambda: self.Window.Final(Since), Timeout=60)
        self.assertEqual(Name, "Failed")
        self.assertIn("Use Repair", Payload["Message"])

        # ---- downgrade back to 1.0.0
        Done, _ = self.Run(lambda: self.Api.StartChangeVersion("1.0.0"))
        self.assertEqual((Done["Kind"], Done["Version"], Done["UndoVersion"]), ("Downgrade", "1.0.0", "1.1.0"))
        self.assertEqual(Setup.ReadManifest(self.Path)["Version"], "1.0.0")
        self.assertEqual(len(os.listdir(self.File("Config.Backup"))), 2)
        self.assertTrue(os.path.isfile(self.File("Config", "Accounts.json")))

        # ---- undo, with GitHub unreachable
        self.Server.Offline = True
        self.Api._Releases = None
        Done, Progress = self.Run(self.Api.StartUndo)
        self.assertEqual((Done["Action"], Done["Version"], Done["UndoVersion"]), ("Undo", "1.1.0", "1.0.0"))
        self.assertTrue(any("saved copy" in P.get("StageDetail", "") for P in Progress))
        self.assertIn("Error", self.Api.ListVersions(False, True))
        self.Server.Offline = False

        # ---- repair brings back a deleted file
        os.remove(self.File("Runtime", "python313.dll"))
        Done, _ = self.Run(self.Api.StartRepair)
        self.assertEqual((Done["Action"], Done["Version"]), ("Repair", "1.1.0"))
        self.assertTrue(os.path.isfile(self.File("Runtime", "python313.dll")))

        # ---- uninstall, keeping Config
        Done, _ = self.Run(lambda: self.Api.StartUninstall(False))
        self.assertTrue(Done["ConfigKept"])
        self.assertEqual(Done["Left"], ["Src"])  # only the user's custom theme folder
        self.assertEqual(sorted(os.listdir(self.Path)), ["Config", "Config.Backup", Setup.UninstalledMarker, "Src"])
        self.assertEqual(os.listdir(self.File("Src")), ["MyCustomThemeE2E"])
        self.assertEqual(Support.RegValues(self.L.RegKeyPath), {Setup.KeptValue: self.Path})
        self.assertIsNone(Support.RegValues(self.L.UninstallKeyPath))
        self.assertFalse(any(os.path.exists(P) for P in Setup.ShortcutPaths()))
        self.assertFalse(os.path.exists(self.L.CacheDir))
        State = self.Api.GetState()
        self.assertFalse(State["Installed"])
        self.assertEqual(State["KeptConfig"]["Path"], self.Path)

        # ---- reinstalling into the same folder finds Config and the custom theme again
        self.assertTrue(self.Api.CheckInstall(self.Path, "", "Use")["Ok"])
        Done, _ = self.Run(lambda: self.Api.StartInstall("1.1.0", self.Path, {"KeptConfig": "Use"}))
        self.assertEqual(set(Support.RegValues(self.L.RegKeyPath)), {"InstallPath", "Version"})
        self.assertTrue(os.path.isfile(self.File("Config", "Accounts.json")))
        self.assertTrue(os.path.isfile(self.File("Src", "MyCustomThemeE2E", "Theme.json")))
        self.assertFalse(os.path.exists(self.File(Setup.UninstalledMarker)))

        # ---- uninstall everything: only the user's theme (never installed by RAMMIT) stays
        Done, _ = self.Run(lambda: self.Api.StartUninstall(True))
        self.assertEqual(Done["Left"], ["Src"])
        self.assertEqual(sorted(os.listdir(self.Path)), [Setup.UninstalledMarker, "Src"])
        self.assertIsNone(Support.RegValues(self.L.RegKeyPath))
        self.assertFalse(os.path.exists(self.L.SetupDir))
        os.remove(self.File("Src", "MyCustomThemeE2E", "Theme.json"))
        os.rmdir(self.File("Src", "MyCustomThemeE2E"))
        os.rmdir(self.File("Src"))
        os.remove(self.File(Setup.UninstalledMarker))
        Done, _ = self.Run(lambda: self.Api.StartInstall("1.0.0", self.Path))
        Done, _ = self.Run(lambda: self.Api.StartUninstall(True))
        self.assertFalse(os.path.exists(self.Path))
        self.assertEqual(Done["Left"], [])

        # the window was sized from measured content, never DPI-multiplied
        self.Api.ResizeInstaller(400)
        self.assertEqual(self.Window.LastResize, [560, 400 + 39])  # fake window has no native frame -> 39 px fallback


if __name__ == "__main__":
    unittest.main()
