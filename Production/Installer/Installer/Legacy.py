"""Old Test1 installs: find them, move their accounts and settings across, remove them.

Test1's installer was never released, but testers have it. It used the same registry key
(HKCU\\Software\\CBlock Digital\\RAMMIT, value InstallPath) and is told apart by:
  * its marker Src\\Version.json in the install folder, and
  * no Manifest.json (only the new installer writes one).
Its Desktop/Start Menu shortcuts ran hidden PowerShell; those are found by their target.

The four choices on the "Older RAMMIT found" screen map to:
  1. MoveRemove  copy Config\\ files into the new install, then Remove(IncludeConfig=True)
  2. MoveKeep    copy Config\\ files into the new install, leave the old one alone
  3. Remove      Remove(IncludeConfig=True) without copying (the UI asks to confirm first)
  4. Ignore      with "don't ask again" the registry gets LegacyInstallPath=Ignore (for good, no undo); without it,
                 LegacyInstallPath=<folder>, and later runs open the menu with an OLD VERSION button instead of this screen

Only names Test1 is known to ship are ever deleted. Account files are copied as files and never read
(they hold login cookies); "has accounts" is judged by file size alone.
"""
import json
import os
import re
import shutil

import Paths
import Setup
from Log import Logger

# What Test1's installer put in the folder: the repo tree (Src\, .gitignore) plus a copy of itself.
KnownNames = {"src", "rammit.exe", "rammit-downloader.exe", "rammit-updater.exe", "installer.exe",
              "rammit-installer.exe", "version.json", ".gitignore"}
ConfigFiles = ("Accounts.json", "Settings.json", "Config.json")


def ConfigDir(Folder):
    return os.path.join(Folder, "Config")


def IsLegacyFolder(Folder):
    return (os.path.isfile(os.path.join(Folder, "Src", "Version.json"))
            and not os.path.isfile(os.path.join(Folder, Setup.ManifestName)))


def ReadVersion(Folder):
    """Version from Test1's Src\\Version.json (a tiny public file, not a Config file)."""
    try:
        with open(os.path.join(Folder, "Src", "Version.json"), encoding="utf-8") as File:
            Data = json.load(File)
        Version = str(Data.get("Version") or Data.get("version") or "")
    except (OSError, ValueError, AttributeError):
        return ""
    return Version if re.match(r"^[0-9A-Za-z.\-]{1,20}$", Version) else ""


IgnoredForGood = "Ignore"  # LegacyInstallPath's value once the user ticked "don't ask again" and pressed Ignore
OldIgnoreValue = "IgnoreLegacyInstall"  # where installers before 1.2.0 kept that; moved over by Detect()


def Detect():
    """{Path, Version, Shortcuts, Deferred} for a Test1 install the registry points at (InstallPath, or LegacyInstallPath
    once the user pressed Ignore), unless the user said never ask again. Deferred = it was put off with Ignore."""
    if Setup.RegRead(OldIgnoreValue) == "1":  # installers before 1.2.0 kept "don't ask again" in its own value
        try:
            Ignore(True)
        except OSError as Error:  # can't move it over now: still honour it, and try again next time
            Logger.warning("Could not move the old 'don't ask again' setting: %s", type(Error).__name__)
            return None
    PutOff = Setup.RegRead("LegacyInstallPath")
    if PutOff == IgnoredForGood:
        return None
    for Folder in (Setup.RegRead("InstallPath"), PutOff):
        if Folder and os.path.isdir(Folder) and IsLegacyFolder(Folder):
            return {"Path": Folder, "Version": ReadVersion(Folder), "Shortcuts": FindShortcuts(),
                    "Deferred": bool(PutOff) and Paths.SamePath(Folder, PutOff)}
    return None


def UnknownEntries(Folder):
    """Names in a Test1 folder that Test1 didn't put there (they make the folder off limits)."""
    try:
        return sorted(Name for Name in os.listdir(Folder) if Name.lower() not in KnownNames | {"config"})
    except OSError:
        return []


def AccountsPresent(Folder):
    """True when Folder\\Accounts.json exists and isn't an empty list. Judged by size; never opened."""
    for Name in _ListLower(Folder):
        if Name.lower() == "accounts.json":
            try:
                return os.path.getsize(os.path.join(Folder, Name)) > 4
            except OSError:
                return False
    return False


def _ListLower(Folder):
    try:
        return os.listdir(Folder)
    except OSError:
        return []


def MoveConfig(LegacyFolder, InstallPath, Choice="KeepNew"):
    """Copies Test1's Accounts/Settings/Config.json into the new install's Config\\. Never silently overwrites a
    Config that already holds accounts: Choice KeepNew keeps it (and backs up the old files), UseOld replaces it
    (after backing it up). Returns notes for the result screen."""
    Source = ConfigDir(LegacyFolder)
    if os.path.islink(Source) or os.path.isjunction(Source):  # only real files come across, never what a link points at
        Logger.warning("Old Config folder is a link: nothing moved")
        return []
    Present = {Name.lower(): Name for Name in _ListLower(Source)}
    Wanted = [(Present[Name.lower()], Name) for Name in ConfigFiles if Name.lower() in Present]
    Links = [Pair for Pair in Wanted if os.path.islink(os.path.join(Source, Pair[0]))]
    if Links:  # only real files come across, never what a link points at
        Logger.warning("Skipped %d old config files that are links", len(Links))
        Wanted = [Pair for Pair in Wanted if Pair not in Links]
    if not Wanted:
        return []
    Destination = os.path.join(InstallPath, "Config")
    OldAccounts = any(Name == "Accounts.json" for _Found, Name in Wanted) and AccountsPresent(Source)
    if AccountsPresent(Destination) and OldAccounts and Choice != "UseOld":
        Setup.BackupConfig(InstallPath, "Test1", Source=Source)
        return ["Your newer accounts were kept. The old version's settings are saved in Config.Backup."]
    if os.path.isdir(Destination) and os.listdir(Destination):
        Setup.BackupConfig(InstallPath, "Replaced")
    os.makedirs(Destination, exist_ok=True)
    for SourceName, TargetName in Wanted:
        Target = os.path.join(Destination, TargetName)
        for Existing in _ListLower(Destination):  # replace any differently-cased copy too
            if Existing.lower() == TargetName.lower() and Existing != TargetName:
                os.remove(os.path.join(Destination, Existing))
        shutil.copy2(os.path.join(Source, SourceName), Target)
    Logger.info("Moved %d config files from the old version", len(Wanted))
    return []


def Remove(Folder, IncludeConfig):
    """Deletes only what Test1 shipped (plus Config\\ if asked). The folder itself goes only if nothing else is in it."""
    Removed, Left = [], []
    for Name in sorted(_ListLower(Folder)):
        Lower, Full = Name.lower(), os.path.join(Folder, Name)
        if Lower in KnownNames or (IncludeConfig and Lower == "config"):
            try:
                if os.path.isdir(Full) and not os.path.islink(Full):
                    Setup._RemoveTree(Full)
                else:
                    os.remove(Full)
                Removed.append(Name)
            except OSError as Error:
                Logger.warning("Could not remove old %s: %s", Name, type(Error).__name__)
                Left.append(Name)
        else:
            Left.append(Name)
    if not Left:
        try:
            os.rmdir(Folder)
        except OSError:
            pass
    return {"Removed": Removed, "Left": Left}


def FindShortcuts():
    """Test1's RAMMIT.lnk files: they start PowerShell, which reads the registry and runs RAMMIT.exe."""
    Found = []
    for LinkPath in Setup.LinkPaths():
        if os.path.isfile(LinkPath):
            Target, Arguments = Setup.ReadShortcut(LinkPath)
            if Target.lower().endswith("powershell.exe") and "cblock digital" in Arguments.lower():
                Found.append(LinkPath)
    return Found


def RemoveShortcuts():
    for LinkPath in FindShortcuts():
        try:
            os.remove(LinkPath)
        except OSError:
            pass


def ClearRegistry(Folder):
    """Test1's values: ConfigPath, CleanupPath, and InstallPath and Version while InstallPath still points at the old
    folder (once a new RAMMIT is installed they are its own); plus LegacyInstallPath (the old version is dealt with)."""
    for Name in ("ConfigPath", "CleanupPath", "LegacyInstallPath"):
        Setup.RegDeleteValue(Name)
    Current = Setup.RegRead("InstallPath")
    if not Current or (Folder and Paths.SamePath(Current, Folder)):
        Setup.RegDeleteValue("Version")
        if Current:
            Setup.RegDeleteValue("InstallPath")
    Setup.TidyRegistry()


def Ignore(DontAskAgain, Folder=""):
    """Ticked: never ask again. Unticked: remember the folder, so it stays reachable from the menu (even after a new
    install takes over InstallPath) without blocking the way in."""
    if DontAskAgain:
        Setup.RegWrite("LegacyInstallPath", IgnoredForGood)
        Setup.RegDeleteValue(OldIgnoreValue)
    elif Folder:
        Setup.RegWrite("LegacyInstallPath", Folder)


def RunRemove(Folder, Report):
    """Choice 3: remove the old version and its Config without moving anything."""
    if Setup.FindRunning([Folder]):
        raise Setup.SetupError("The old RAMMIT is running. Close it first.", Running=True)
    Report(Label="Deleting files", Pct=10, ActiveStage=0)
    Result = Remove(Folder, IncludeConfig=True)
    Report(Pct=100, ActiveStage=1)
    Report(Label="Cleaning up")
    RemoveShortcuts()
    ClearRegistry(Folder)
    Report(Pct=100)
    Logger.info("Old version removed from %s (left: %d)", Folder, len(Result["Left"]))
    return {"Path": Folder, "Left": Result["Left"]}


def RunMove(Folder, InstallPath, Mode, Choice, Report):
    """Choices 1 and 2 when RAMMIT is already installed: nothing is reinstalled, only the old version's accounts and
    settings come across (MoveConfig, same rules as an install). MoveRemove then removes the old version like choice 3.
    The registry's InstallPath and Version belong to the installed RAMMIT, so only Test1's own values go."""
    if Setup.FindRunning([Folder, InstallPath]):
        raise Setup.SetupError("RAMMIT is running. Close it first.", Running=True)
    Report(Label="Moving accounts and settings", Pct=10, ActiveStage=0)
    Warnings = MoveConfig(Folder, InstallPath, Choice)
    Left = []
    if Mode == "MoveRemove":
        Report(Label="Removing the old version", Pct=50)
        Left = Remove(Folder, IncludeConfig=True)["Left"]
        RemoveShortcuts()
    Report(Pct=100, ActiveStage=1)
    Report(Label="Cleaning up")
    for Name in ("ConfigPath", "CleanupPath", "LegacyInstallPath"):
        Setup.RegDeleteValue(Name)
    Report(Pct=100)
    Logger.info("Old version's config moved into %s (%s)", InstallPath, Mode)
    return {"Path": Folder, "InstallPath": InstallPath, "Mode": Mode, "Left": Left, "Warnings": Warnings}
