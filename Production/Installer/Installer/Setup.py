"""The steps behind every installer button: install, update, repair, change version, undo and uninstall.

Install pipeline (RunInstall), the same for every kind of install so none can leave half an install behind:
  1. get a verified zip: download it to %TEMP% and check its SHA-256 (Releases.py), or take the Undo copy
     from the cache (its SHA-256 is checked again)
  2. extract the zip's RAMMIT\\ folder into <Install>.Staging, refusing the whole zip if any entry would land
     outside it (../, absolute paths, drive letters, device names)
  3. write Manifest.json (every installed file and its SHA-256) into the staging folder
  4. back up Config\\ to Config.Backup\\<old version>-<time>\\ when the version changes (last 5 kept)
  5. swap folders: <Install> -> <Install>.Old, staging -> <Install>, then carry every file the OLD manifest
     doesn't list (Config\\, Config.Backup\\, custom themes, the user's own files) across and delete .Old.
     Any failure puts everything back where it was.
  6. registry values, the Apps-list entry, shortcuts pointing straight at RAMMIT.exe, the Undo cache

Uninstall deletes only the files on the manifest (plus Config\\ and Config.Backup\\ when asked), then empty
folders. Anything else in the folder is left alone and reported. What it leaves behind:
  * everything removed: nothing. Not our registry key, not an empty "CBlock Digital" key, not RAMMIT-Setup\\
    (a running RAMMIT-Setup.exe is moved to %TEMP% when the window closes, see FinishOnExit).
  * Config kept: the folder with Config\\ (+ Config.Backup\\) and ONE registry value, KeptConfigPath, so the next
    install can find those accounts again wherever they are (FindKeptConfig / RestoreKeptConfig). Test1's
    uninstall left ConfigPath + CleanupPath for the same reason; those are read too.

The installer only ever installs into a folder that is missing, empty, its own install (has Manifest.json)
or what its own uninstall left behind (only Config\\ / Config.Backup\\), so it can't wipe someone's folder.
"""
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import winreg
import zipfile

import Legacy
import Locations
import Paths
import Releases
from Log import Logger

ManifestName = "Manifest.json"
StagingSuffix, OldSuffix = ".Staging", ".Old"
StagingMarker = ".RammitStaging"
# Left in a folder our uninstall couldn't remove (kept Config, the user's own files) so a reinstall recognises it.
UninstalledMarker = "RAMMIT-Uninstalled.json"
OwnLeftovers = {"config", "config.backup"}
# Registry values that point at accounts an uninstall kept: ours, then the two Test1's uninstall wrote.
KeptValue = "KeptConfigPath"
Test1ConfigValue, Test1CleanupValue = "ConfigPath", "CleanupPath"
BackupKeep = 5
MaxZipEntries = 20000
MaxUnpackedBytes = 1024 * 1024 * 1024
ReservedNames = {"con", "prn", "aux", "nul"} | {f"com{N}" for N in range(1, 10)} | {f"lpt{N}" for N in range(1, 10)}
BackupPattern = re.compile(r"^(?P<Label>[0-9A-Za-z.\-]{1,40})-(?P<Stamp>\d{8}-\d{6})(?:-(?P<Extra>\d{1,3}))?$")


class SetupError(Exception):
    """Message is shown to the user; Details go to the error screen's "Copy details"."""

    def __init__(self, Message, Details="", Running=False):
        super().__init__(Message)
        self.Details = Details
        self.Running = Running


# Every rename goes through this, so the tests can make one fail and check the rollback.
def _MoveFile(Source, Destination):
    os.rename(Source, Destination)


# ------------------------------------------------------------ registry (HKCU only, no admin needed)

def RegRead(Name, KeyPath=None):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, KeyPath or Locations.Current.RegKeyPath) as Key:
            Value, _Type = winreg.QueryValueEx(Key, Name)
            return str(Value)
    except OSError:
        return None


def RegWrite(Name, Value):
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, Locations.Current.RegKeyPath, 0, winreg.KEY_WRITE) as Key:
        winreg.SetValueEx(Key, Name, 0, winreg.REG_SZ, str(Value))


def RegDeleteValue(Name):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, Locations.Current.RegKeyPath, 0, winreg.KEY_SET_VALUE) as Key:
            winreg.DeleteValue(Key, Name)
    except OSError:
        pass


def RegDeleteKey(KeyPath=None):
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, KeyPath or Locations.Current.RegKeyPath)
    except OSError:
        pass


def _RegKeyEmpty(KeyPath):
    """True when the key has no values and no subkeys (False when it is missing or can't be read)."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, KeyPath) as Key:
            SubKeys, Values, _Modified = winreg.QueryInfoKey(Key)
        return SubKeys == 0 and Values == 0
    except OSError:
        return False


def TidyRegistry():
    """Deletes our key once it holds nothing, then "Software\\CBlock Digital" once nothing else of ours is in it.
    Test1 and the first installers always left that parent key behind."""
    KeyPath = Locations.Current.RegKeyPath
    if _RegKeyEmpty(KeyPath):
        RegDeleteKey(KeyPath)
    Parent = KeyPath.rsplit("\\", 1)[0]
    if Parent.lower().endswith("\\cblock digital") and _RegKeyEmpty(Parent):
        RegDeleteKey(Parent)


def SetupCommand():
    """How Windows starts this installer again (Apps-list Uninstall/Modify)."""
    if Paths.IsFrozen():
        return f'"{Locations.Current.SetupExePath}"'
    return f'"{sys.executable}" "{os.path.join(os.path.dirname(os.path.abspath(__file__)), "Installer.py")}"'


def WriteUninstallEntry(InstallPath, Version):
    """Per-user entry in Settings > Apps (HKCU, so no admin prompt)."""
    L = Locations.Current
    Exe = os.path.join(InstallPath, "RAMMIT.exe")
    Values = {
        "DisplayName": "RAMMIT" if not L.TestMode else "RAMMIT (installer test)",
        "DisplayVersion": Version,
        "Publisher": "CBlock Digital",
        "DisplayIcon": f'"{Exe}",0',
        "InstallLocation": InstallPath,
        "UninstallString": SetupCommand() + " /Uninstall",
        "ModifyPath": SetupCommand(),
        "InstallDate": time.strftime("%Y%m%d"),
    }
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, L.UninstallKeyPath, 0, winreg.KEY_WRITE) as Key:
        for Name, Value in Values.items():
            winreg.SetValueEx(Key, Name, 0, winreg.REG_SZ, Value)
        winreg.SetValueEx(Key, "NoRepair", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(Key, "EstimatedSize", 0, winreg.REG_DWORD, max(1, _FolderSize(InstallPath) // 1024))


def RemoveUninstallEntry():
    RegDeleteKey(Locations.Current.UninstallKeyPath)


def _FolderSize(Folder):
    Total = 0
    for Root, _Dirs, Files in os.walk(Folder):
        for Name in Files:
            try:
                Total += os.path.getsize(os.path.join(Root, Name))
            except OSError:
                pass
    return Total


# ------------------------------------------------------------ shortcuts (straight at RAMMIT.exe, never PowerShell)

ShortcutNames = ("Desktop", "StartMenu")  # the two the installer offers (tick boxes on the Version screen)
ShortcutsValue = "Shortcuts"             # registry: which ones were chosen at install, e.g. "Desktop,StartMenu" or ""


def ShortcutPath(Name):
    L = Locations.Current
    return os.path.join(L.DesktopDir if Name == "Desktop" else L.StartMenuDir, "RAMMIT.lnk")


def ShortcutPaths():
    return [ShortcutPath(Name) for Name in ShortcutNames]


def ChosenShortcuts():
    """The shortcuts chosen at install, for an update / repair / undo to recreate. Installs from before the choice
    existed have none saved: both, as they always got."""
    Saved = RegRead(ShortcutsValue)
    return list(ShortcutNames) if Saved is None else [Name for Name in Saved.split(",") if Name in ShortcutNames]


def _Shell():
    import pythoncom
    import win32com.client
    pythoncom.CoInitialize()  # worker threads need COM set up before WScript.Shell
    return win32com.client.Dispatch("WScript.Shell")


def ReadShortcut(LinkPath):
    """(TargetPath, Arguments) of a .lnk, or ("", "") when it can't be read."""
    try:
        Link = _Shell().CreateShortCut(LinkPath)
        return str(Link.TargetPath or ""), str(Link.Arguments or "")
    except Exception:
        return "", ""


def CreateShortcuts(InstallPath, Names=ShortcutNames):
    Exe = os.path.join(InstallPath, "RAMMIT.exe")
    Shell = _Shell()
    for LinkPath in [ShortcutPath(Name) for Name in ShortcutNames if Name in Names]:
        os.makedirs(os.path.dirname(LinkPath), exist_ok=True)
        Link = Shell.CreateShortCut(LinkPath)
        Link.TargetPath = Exe
        Link.Arguments = ""
        Link.WorkingDirectory = InstallPath
        Link.IconLocation = Exe + ",0"
        Link.Description = "RAMMIT - Roblox Multi-Account Launcher"
        Link.save()


def RemoveShortcuts(InstallPath):
    """Removes RAMMIT.lnk only where it points at this install's RAMMIT.exe."""
    Exe = os.path.join(InstallPath, "RAMMIT.exe")
    for LinkPath in ShortcutPaths():
        if os.path.isfile(LinkPath):
            Target, _Args = ReadShortcut(LinkPath)
            # SamePath resolves 8.3 short names (C:\Users\RUNNER~1) the .lnk may store differently from ours.
            if Target and Paths.SamePath(Target, Exe):
                try:
                    os.remove(LinkPath)
                except OSError as Error:
                    Logger.warning("Could not remove shortcut %s: %s", LinkPath, type(Error).__name__)


# ------------------------------------------------------------ folders

def NormalizeInstallPath(Raw):
    """User-typed folder -> clean absolute path on a local drive, or SetupError."""
    if not isinstance(Raw, str) or not Raw.strip():
        raise SetupError("Choose a folder to install RAMMIT into.")
    Text = Raw.strip().strip('"')
    if len(Text) > 200:
        raise SetupError("That folder path is too long. Pick a shorter one.")
    if any(Char in Text for Char in '<>"|?*') or any(ord(Char) < 32 for Char in Text):
        raise SetupError("That folder name has characters Windows doesn't allow.")
    if not re.match(r"^[A-Za-z]:[\\/]", Text):
        raise SetupError("Pick a folder on this PC, like C:\\Users\\you\\AppData\\Local\\RAMMIT.")
    Path = os.path.normpath(Text)
    if len(Path) <= 3:
        raise SetupError("RAMMIT can't be installed straight into a drive. Pick or make a folder for it.")
    if ":" in Path[2:]:
        raise SetupError("That folder name has characters Windows doesn't allow.")
    for Part in Path[3:].split("\\"):
        if Part.split(".")[0].lower() in ReservedNames or Part.endswith((" ", ".")):
            raise SetupError("That folder name isn't allowed by Windows.")
    L = Locations.Current
    WindowsDir = os.environ.get("SystemRoot", r"C:\Windows")
    if Paths.IsInside(WindowsDir, Path):
        raise SetupError("RAMMIT can't be installed inside the Windows folder.")
    if Paths.IsInside(L.SetupDir, Path) or Paths.IsInside(Path, L.SetupDir):
        raise SetupError("That folder belongs to the installer itself. Pick another one.")
    if os.path.exists(Path) and not os.path.isdir(Path):
        raise SetupError("There's a file with that name. Pick a folder instead.")
    return Path


def Classify(Folder):
    """Missing / Empty / Ours (has Manifest.json) / Leftover (what our uninstall left: only Config + Config.Backup,
    or anything with our RAMMIT-Uninstalled.json marker) / Legacy (Test1) / Foreign (never installed into)."""
    if not os.path.exists(Folder):
        return "Missing"
    if not os.path.isdir(Folder):
        return "Foreign"
    try:
        Names = {Name.lower() for Name in os.listdir(Folder)}
    except OSError:
        return "Foreign"
    if not Names:
        return "Empty"
    if ManifestName.lower() in Names:
        return "Ours"
    if Legacy.IsLegacyFolder(Folder):
        return "Legacy"
    if Names <= OwnLeftovers or UninstalledMarker.lower() in Names:
        return "Leftover"
    return "Foreign"


def ReadManifest(Folder):
    try:
        with open(os.path.join(Folder, ManifestName), encoding="utf-8") as File:
            Data = json.load(File)
    except (OSError, ValueError):
        return None
    if not isinstance(Data, dict) or not isinstance(Data.get("Files"), dict):
        return None
    return Data


def WriteManifest(Folder, Version, Files, Branch=""):
    Data = {"App": "RAMMIT", "Version": Version, "Branch": Branch or Releases.BranchOf(Version),
            "InstalledAt": time.strftime("%Y-%m-%dT%H:%M:%S"), "Files": Files}
    with open(os.path.join(Folder, ManifestName), "w", encoding="utf-8") as File:
        json.dump(Data, File, indent=1, sort_keys=True)


def InstalledState():
    """{Installed, Version, Branch, Path}. Looks at the registry first, then the default folder."""
    L = Locations.Current
    Candidates = [P for P in (RegRead("InstallPath"), L.DefaultInstallPath) if P]
    for Folder in Candidates:
        RecoverInterruptedSwap(Folder)
        Manifest = ReadManifest(Folder)
        if Manifest:
            Version = str(Manifest.get("Version", ""))
            Branch = Manifest.get("Branch") if Manifest.get("Branch") in ("Stable", "Dev") else Releases.BranchOf(Version)
            return {"Installed": True, "Version": Version, "Branch": Branch, "Path": Folder}
    return {"Installed": False, "Version": "", "Branch": "", "Path": ""}


def _RemoveTree(Folder):
    def OnError(Function, Target, _Info):
        os.chmod(Target, stat.S_IWRITE)  # read-only files (git checkouts, some zips) can't be deleted otherwise
        Function(Target)
    shutil.rmtree(Folder, onerror=OnError)


def _RemoveStaging(Staging):
    """Deletes a staging folder, but only one this installer made (it carries the marker file)."""
    if os.path.isdir(Staging) and os.path.isfile(os.path.join(Staging, StagingMarker)):
        _RemoveTree(Staging)


def RecoverInterruptedSwap(InstallPath):
    """Finishes or undoes a swap that was cut off (power loss, killed process) so nothing is ever lost."""
    if not InstallPath:
        return
    Old = InstallPath + OldSuffix
    try:
        _RemoveStaging(InstallPath + StagingSuffix)
        if not os.path.isdir(Old) or not os.path.isfile(os.path.join(Old, ManifestName)):
            return
        if not os.path.exists(InstallPath):
            Logger.warning("Restoring %s from an interrupted swap", InstallPath)
            _MoveFile(Old, InstallPath)
        elif os.path.isfile(os.path.join(InstallPath, ManifestName)):
            Logger.warning("Finishing an interrupted swap in %s", InstallPath)
            OldManifest = ReadManifest(Old) or {"Files": {}}
            _CarryOver(Old, InstallPath, OldManifest["Files"], [])
            _RemoveTree(Old)
    except OSError as Error:
        Logger.warning("Could not recover %s: %s", InstallPath, type(Error).__name__)


# ------------------------------------------------------------ zip -> staging

def CheckMemberName(Name):
    """Zip entry name -> 'a/b/c' relative path, or SetupError if it could land outside the target folder."""
    if not Name or "\x00" in Name or ":" in Name or Name.startswith(("/", "\\")):
        raise SetupError("The download contains an unsafe file path, so it was not installed.", f"unsafe zip entry {Name!r}")
    Parts = [Part for Part in re.split(r"[\\/]", Name) if Part not in ("", ".")]
    for Part in Parts:
        if Part == ".." or Part.split(".")[0].lower() in ReservedNames or Part.endswith((" ", ".")):
            raise SetupError("The download contains an unsafe file path, so it was not installed.", f"unsafe zip entry {Name!r}")
    return "/".join(Parts)


def ExtractToStaging(ZipPath, Staging, OnProgress=None):
    """Extracts the zip's RAMMIT/ folder (or the whole zip if it has none) into Staging. Returns {RelPath: Sha256}."""
    if os.path.exists(Staging):
        _RemoveStaging(Staging)
        if os.path.exists(Staging):
            raise SetupError(f"A folder named {os.path.basename(Staging)} is in the way. Move or delete it, then try again.")
    try:
        Zip = zipfile.ZipFile(ZipPath)
    except (zipfile.BadZipFile, OSError) as Error:
        raise SetupError("The download is not a valid zip file. Try again.", f"{type(Error).__name__}: {Error}")
    with Zip:
        Infos = Zip.infolist()
        if len(Infos) > MaxZipEntries:
            raise SetupError("The download has far more files than RAMMIT should, so it was refused.", f"{len(Infos)} entries")
        Names = [CheckMemberName(Info.filename) for Info in Infos]  # one bad entry rejects the whole zip
        Prefix = "RAMMIT/" if any(N.startswith("RAMMIT/") for N in Names) else ""
        Members = [(Info, Rel[len(Prefix):]) for Info, Rel in zip(Infos, Names)
                   if not Info.is_dir() and Rel.startswith(Prefix) and Rel[len(Prefix):]]
        if not any(Rel.lower() == "rammit.exe" for _Info, Rel in Members):
            raise SetupError("The download doesn't contain RAMMIT.exe, so it was not installed.", "RAMMIT.exe missing from the zip")
        if any(Rel.lower() in (ManifestName.lower(), StagingMarker.lower()) for _Info, Rel in Members):
            raise SetupError("The download contains a file the installer reserves for itself.", "reserved name in zip")
        if sum(Info.file_size for Info, _Rel in Members) > MaxUnpackedBytes:
            raise SetupError("The download unpacks to far more than RAMMIT should, so it was refused.", "unpacked size over limit")
        os.makedirs(Staging)
        open(os.path.join(Staging, StagingMarker), "w").close()
        Files = {}
        for Index, (Info, Rel) in enumerate(Members):
            Destination = os.path.join(Staging, *Rel.split("/"))
            if not Paths.IsInside(Staging, Destination):
                raise SetupError("The download contains an unsafe file path, so it was not installed.", f"escapes staging: {Rel!r}")
            os.makedirs(os.path.dirname(Destination), exist_ok=True)
            Hash, Written = hashlib.sha256(), 0
            with Zip.open(Info) as Source, open(Destination, "wb") as Target:
                for Block in iter(lambda: Source.read(1024 * 1024), b""):
                    Written += len(Block)
                    if Written > Info.file_size:  # sizes in the zip header can lie (zip bombs)
                        raise SetupError("The download is damaged.", f"{Rel} is bigger than its zip header says")
                    Hash.update(Block)
                    Target.write(Block)
            Files[Rel] = Hash.hexdigest()
            if OnProgress:
                OnProgress(Index + 1, len(Members), Rel)
    return Files


# ------------------------------------------------------------ the swap

def _CarryOver(OldFolder, NewFolder, OldFiles, Moved):
    """Moves every file in OldFolder that the old manifest doesn't list into NewFolder (the new build wins on
    a clash). Moved collects (From, To) pairs so a failure can be rolled back."""
    Owned = {Rel.lower() for Rel in OldFiles} | {ManifestName.lower(), UninstalledMarker.lower()}
    for Root, _Dirs, FileNames in os.walk(OldFolder):
        for Name in FileNames:
            Source = os.path.join(Root, Name)
            Rel = os.path.relpath(Source, OldFolder).replace("\\", "/")
            if Rel.lower() in Owned:
                continue
            Destination = os.path.join(NewFolder, *Rel.split("/"))
            if os.path.exists(Destination):
                continue
            os.makedirs(os.path.dirname(Destination), exist_ok=True)
            _MoveFile(Source, Destination)
            Moved.append((Source, Destination))


def SwapIn(Staging, InstallPath):
    """Puts the staged build in place. On any failure the old install is restored exactly."""
    State = Classify(InstallPath)
    Marker = os.path.join(Staging, StagingMarker)
    if State in ("Missing", "Empty"):
        os.makedirs(os.path.dirname(InstallPath), exist_ok=True)
        if State == "Empty":
            os.rmdir(InstallPath)
        os.remove(Marker)
        try:
            _MoveFile(Staging, InstallPath)
        except OSError as Error:
            open(Marker, "w").close()
            raise SetupError("Couldn't move the new files into place.", f"{type(Error).__name__}: {Error}")
        return
    if State not in ("Ours", "Leftover"):
        raise SetupError("That folder has other files in it. Pick an empty folder or a new one.", f"folder state {State}")
    Old = InstallPath + OldSuffix
    if os.path.exists(Old):
        raise SetupError(f"A folder named {os.path.basename(Old)} is in the way. Move or delete it, then try again.")
    OldManifest = ReadManifest(InstallPath) or {"Files": {}}
    try:
        _MoveFile(InstallPath, Old)
    except OSError as Error:
        raise SetupError("RAMMIT's folder is in use. Close RAMMIT and any window showing that folder, then try again.",
                         f"{type(Error).__name__}: {Error}")
    os.remove(Marker)
    Moved = []
    try:
        _MoveFile(Staging, InstallPath)
        _CarryOver(Old, InstallPath, OldManifest["Files"], Moved)
    except Exception as Error:
        _RollBack(Staging, InstallPath, Old, Moved)
        raise SetupError("Couldn't swap in the new files, so the old version was put back.", f"{type(Error).__name__}: {Error}")
    try:
        _RemoveTree(Old)
    except OSError as Error:
        Logger.warning("Could not delete %s (%s); it is retried next time", Old, type(Error).__name__)


def _RollBack(Staging, InstallPath, Old, Moved):
    for Source, Destination in reversed(Moved):
        try:
            os.makedirs(os.path.dirname(Source), exist_ok=True)
            _MoveFile(Destination, Source)
        except OSError:
            Logger.error("Rollback could not return %s", Source)
    if os.path.isdir(InstallPath) and not os.path.exists(Staging):
        try:
            _MoveFile(InstallPath, Staging)
            open(os.path.join(Staging, StagingMarker), "w").close()
        except OSError:
            Logger.error("Rollback could not move the new build away")
    if not os.path.exists(InstallPath):
        _MoveFile(Old, InstallPath)


# ------------------------------------------------------------ Config backups

def BackupConfig(InstallPath, Label, Source=None, Keep=BackupKeep):
    """Copies Config\\ (or Source) to Config.Backup\\<Label>-<YYYYMMDD-HHMMSS>\\ and keeps the newest Keep backups."""
    Source = Source or os.path.join(InstallPath, "Config")
    if not os.path.isdir(Source) or not os.listdir(Source):
        return None
    Root = os.path.join(InstallPath, "Config.Backup")
    SafeLabel = re.sub(r"[^0-9A-Za-z.\-]", "", Label)[:40] or "Unknown"
    Base = f"{SafeLabel}-{time.strftime('%Y%m%d-%H%M%S')}"
    Target, Extra = os.path.join(Root, Base), 1
    while os.path.exists(Target):
        Extra += 1
        Target = os.path.join(Root, f"{Base}-{Extra}")
    shutil.copytree(Source, Target)
    PruneBackups(Root, Keep)
    return Target


def PruneBackups(Root, Keep=BackupKeep):
    """Deletes all but the newest Keep backup folders. Folders that don't look like backups are never touched."""
    Found = []
    for Name in os.listdir(Root) if os.path.isdir(Root) else []:
        Match = BackupPattern.match(Name)
        if Match and os.path.isdir(os.path.join(Root, Name)):
            Found.append(((Match.group("Stamp"), int(Match.group("Extra") or 1)), Name))
    for _Key, Name in sorted(Found, reverse=True)[Keep:]:
        _RemoveTree(os.path.join(Root, Name))


def _MoveAside(ConfigFolder, InstallPath, Label):
    """Moves a whole Config folder into InstallPath\\Config.Backup\\<Label>-<time>\\ (nothing is deleted)."""
    Root = os.path.join(InstallPath, "Config.Backup")
    os.makedirs(Root, exist_ok=True)
    Target = os.path.join(Root, f"{Label}-{time.strftime('%Y%m%d-%H%M%S')}")
    Extra = 1
    while os.path.exists(Target):
        Extra += 1
        Target = os.path.join(Root, f"{Label}-{time.strftime('%Y%m%d-%H%M%S')}-{Extra}")
    shutil.move(ConfigFolder, Target)
    PruneBackups(Root)
    return Target


# ------------------------------------------------------------ accounts an earlier uninstall kept

def _HasFiles(Folder):
    if not os.path.isdir(Folder):
        return False
    try:
        with os.scandir(Folder) as Entries:  # closed at once: an open handle would stop the folder being deleted
            return any(Entries)
    except OSError:
        return False


def FindKeptConfig():
    """The Config folder an earlier uninstall kept, so a reinstall can bring those accounts back:
    {Path (its folder), Config, Accounts (bool, judged by size), Test1 (bool), Installable (bool: the folder may be
    installed into again)} or None. Looked for in this order:
      1. our KeptConfigPath value (written by RunUninstall when Config was kept)
      2. Test1's ConfigPath value (its uninstall wrote it, with CleanupPath, when Config was kept)
      3. the default install folder, when it holds only what our uninstall leaves (registry cleaners, older builds)
    A value whose Config folder is gone (deleted by hand) is removed from the registry."""
    L = Locations.Current
    Candidates = []
    Ours = RegRead(KeptValue)
    if Ours:
        Candidates.append((Ours, os.path.join(Ours, "Config"), False, KeptValue))
    Test1 = RegRead(Test1ConfigValue)
    if Test1:
        Candidates.append((os.path.dirname(os.path.normpath(Test1)), os.path.normpath(Test1), True, Test1ConfigValue))
    if Classify(L.DefaultInstallPath) == "Leftover":
        Candidates.append((L.DefaultInstallPath, os.path.join(L.DefaultInstallPath, "Config"), False, ""))
    for Folder, Config, IsTest1, Value in Candidates:
        if _HasFiles(Config):
            return {"Path": Folder, "Config": Config, "Accounts": Legacy.AccountsPresent(Config), "Test1": IsTest1,
                    "Installable": Classify(Folder) in ("Missing", "Empty", "Leftover")}
        if Value:
            Logger.info("Forgetting kept accounts in %s (the folder is gone)", Folder)
            ForgetKeptConfig(Value)
    return None


def ForgetKeptConfig(*Values):
    """Removes the kept-accounts pointers (all of them by default), then tidies the registry."""
    for Name in Values or (KeptValue, Test1ConfigValue, Test1CleanupValue):
        RegDeleteValue(Name)
        if Name == Test1ConfigValue:
            RegDeleteValue(Test1CleanupValue)
    TidyRegistry()


def KeptConfigNeedsChoice(Kept, InstallPath):
    """True when the kept accounts would land in a folder that already has accounts of its own."""
    return bool(Kept and Kept["Accounts"] and not Paths.SamePath(Kept["Path"], InstallPath)
                and Legacy.AccountsPresent(os.path.join(InstallPath, "Config")))


def RestoreKeptConfig(Kept, InstallPath, Use, Choice="KeepNew"):
    """Runs after a new install is in place. Use=True brings the kept Config\\ (and Config.Backup\\) into
    InstallPath; Use=False starts fresh. Nothing is ever deleted: accounts that lose out go to Config.Backup\\.
    The old folder is removed only when nothing else is left in it. Returns a line for the result screen."""
    Same = Paths.SamePath(Kept["Path"], InstallPath)
    Target = os.path.join(InstallPath, "Config")
    Line = ""
    if Same:
        # The swap already carried Config\\ across; starting fresh just puts it aside.
        if not Use and _HasFiles(Target):
            _MoveAside(Target, InstallPath, "Earlier")
            Line = "Your earlier accounts were put aside in Config.Backup."
        elif Use:
            Line = "Your saved accounts and settings came back."
    elif Use and _HasFiles(Kept["Config"]):
        if Legacy.AccountsPresent(Target) and Choice != "UseOld":
            _MoveAside(Kept["Config"], InstallPath, "Earlier")
            Line = "The accounts already in that folder were kept. The earlier ones are in Config.Backup."
        else:
            if _HasFiles(Target):
                _MoveAside(Target, InstallPath, "Replaced")
            elif os.path.isdir(Target):
                os.rmdir(Target)
            shutil.move(Kept["Config"], Target)
            Line = "Your saved accounts and settings came back from " + Kept["Path"] + "."
        OldBackups = os.path.join(Kept["Path"], "Config.Backup")
        if os.path.isdir(OldBackups):
            Root = os.path.join(InstallPath, "Config.Backup")
            os.makedirs(Root, exist_ok=True)
            for Name in os.listdir(OldBackups):
                if not os.path.exists(os.path.join(Root, Name)):
                    shutil.move(os.path.join(OldBackups, Name), os.path.join(Root, Name))
            PruneBackups(Root)
        _RemoveLeftoverFolder(Kept)
    elif not Use:
        Line = "Your earlier accounts were left in " + Kept["Path"] + "."
    ForgetKeptConfig()
    return Line


def _RemoveLeftoverFolder(Kept):
    """After its Config moved out: deletes what our (or Test1's) uninstall left in the old folder, and the folder
    itself if it is then empty. Anything else stays."""
    Folder = Kept["Path"]
    if Kept["Test1"]:
        Legacy.Remove(Folder, IncludeConfig=False)  # only names Test1 shipped
        return
    for Name in (UninstalledMarker, "Config.Backup", "Config"):
        Full = os.path.join(Folder, Name)
        try:
            if os.path.isfile(Full):
                os.remove(Full)
            elif os.path.isdir(Full) and not _HasFiles(Full):
                os.rmdir(Full)
        except OSError:
            pass
    try:
        os.rmdir(Folder)
    except OSError:
        pass


# ------------------------------------------------------------ Undo cache (Setup\Cache\Installed + Previous)

def _Slot(Name):
    return os.path.join(Locations.Current.CacheDir, Name)


def CachedRelease(Slot):
    """{Version, Branch, ZipPath, Sha256} stored in a cache slot, or None."""
    try:
        with open(os.path.join(_Slot(Slot), "Info.json"), encoding="utf-8") as File:
            Info = json.load(File)
        ZipPath = os.path.join(_Slot(Slot), os.path.basename(str(Info["ZipName"])))
        if Releases.ParseVersion(str(Info["Version"])) is None or not os.path.isfile(ZipPath):
            return None
        Branch = Info.get("Branch") if Info.get("Branch") in ("Stable", "Dev") else Releases.BranchOf(str(Info["Version"]))
        return {"Version": str(Info["Version"]), "Branch": Branch, "ZipPath": ZipPath, "Sha256": str(Info["Sha256"]).lower()}
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _StoreInSlot(Slot, ZipPath, Version, Sha, Branch):
    Folder = _Slot(Slot)
    if os.path.isdir(Folder):
        _RemoveTree(Folder)
    os.makedirs(Folder)
    shutil.copy2(ZipPath, os.path.join(Folder, os.path.basename(ZipPath)))
    with open(os.path.join(Folder, "Info.json"), "w", encoding="utf-8") as File:
        json.dump({"Version": Version, "Branch": Branch, "ZipName": os.path.basename(ZipPath), "Sha256": Sha}, File)


def UpdateCache(NewVersion, ZipPath, Sha, OldVersion, FromSlot="", Branch=""):
    """After a successful install: the version just left moves to Previous (for Undo), the new one to Installed."""
    try:
        Installed = CachedRelease("Installed")
        if FromSlot == "Previous":
            # Undo: the two slots simply trade places, so Undo can be undone too.
            Temp = _Slot("Swap")
            if os.path.isdir(Temp):
                _RemoveTree(Temp)
            os.rename(_Slot("Previous"), Temp)
            if os.path.isdir(_Slot("Installed")):
                os.rename(_Slot("Installed"), _Slot("Previous"))
            os.rename(Temp, _Slot("Installed"))
            return
        if OldVersion and OldVersion != NewVersion and Installed and Installed["Version"] == OldVersion:
            if os.path.isdir(_Slot("Previous")):
                _RemoveTree(_Slot("Previous"))
            os.rename(_Slot("Installed"), _Slot("Previous"))
        _StoreInSlot("Installed", ZipPath, NewVersion, Sha, Branch or Releases.BranchOf(NewVersion))
    except OSError as Error:
        Logger.warning("Undo cache not updated: %s", type(Error).__name__)


def UndoVersion(InstalledVersion):
    Previous = CachedRelease("Previous")
    return Previous["Version"] if Previous and Previous["Version"] != InstalledVersion else ""


def ClearCache():
    if os.path.isdir(Locations.Current.CacheDir):
        _RemoveTree(Locations.Current.CacheDir)


def CopySetupExe():
    """Keeps one copy of this installer for the Apps-list entry (frozen builds only)."""
    if not Paths.IsFrozen():
        return
    Target = Locations.Current.SetupExePath
    if Paths.SamePath(sys.executable, Target) if os.path.exists(Target) else False:
        return
    os.makedirs(os.path.dirname(Target), exist_ok=True)
    shutil.copy2(sys.executable, Target)


# ------------------------------------------------------------ running RAMMIT

def FindRunning(Folders):
    """RAMMIT.exe processes started from any of these folders."""
    import psutil
    Folders = [F for F in Folders if F]
    Found = []
    for Process in psutil.process_iter(["name", "exe", "pid"]):
        try:
            if (Process.info["name"] or "").lower() != "rammit.exe":
                continue
            Exe = Process.info["exe"]
            if Exe and any(Paths.IsInside(Folder, Exe) for Folder in Folders):
                Found.append(Process)
        except Exception:
            continue
    return Found


def CloseRunning(Folders, Timeout=8):
    """Asks RAMMIT to close (WM_CLOSE to its windows), then ends what is left. Returns how many still run."""
    import psutil
    import win32con
    import win32gui
    import win32process
    Processes = FindRunning(Folders)
    Pids = {P.pid for P in Processes}

    def OnWindow(Hwnd, _Extra):
        try:
            if win32process.GetWindowThreadProcessId(Hwnd)[1] in Pids and win32gui.IsWindowVisible(Hwnd):
                win32gui.PostMessage(Hwnd, win32con.WM_CLOSE, 0, 0)
        except Exception:
            pass
        return True
    try:
        win32gui.EnumWindows(OnWindow, None)
    except Exception:
        pass
    _Gone, Alive = psutil.wait_procs(Processes, timeout=Timeout)
    for Process in Alive:
        try:
            Process.terminate()
        except psutil.Error:
            pass
    psutil.wait_procs(Alive, timeout=3)
    return len(FindRunning(Folders))


def LaunchApp(InstallPath):
    Exe = os.path.join(InstallPath, "RAMMIT.exe")
    if not os.path.isfile(Exe):
        raise SetupError("RAMMIT.exe wasn't found in the install folder. Try Repair.")
    Flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    subprocess.Popen([Exe], cwd=InstallPath, close_fds=True, creationflags=Flags)


# ------------------------------------------------------------ install

def CheckTarget(InstallPath, LegacyMode="", LegacyPath=""):
    """Pre-flight for the Install button: {Ok, Path, State, NeedsConfigChoice} or SetupError."""
    Path = NormalizeInstallPath(InstallPath)
    RecoverInterruptedSwap(Path)
    State = Classify(Path)
    SameAsLegacy = bool(LegacyPath) and Paths.SamePath(Path, LegacyPath) if os.path.exists(Path) else False
    if State == "Legacy" or SameAsLegacy:
        if LegacyMode == "MoveKeep":
            raise SetupError("The old version is in that folder. To keep it, install the new one somewhere else.")
        if LegacyMode != "MoveRemove" or not SameAsLegacy:
            raise SetupError("That folder has an older RAMMIT in it. Pick another folder, or go back and remove the old version.")
        Extra = Legacy.UnknownEntries(Path)
        if Extra:
            raise SetupError("The old version's folder also holds other files (" + ", ".join(Extra[:3]) + "). Pick another folder.")
    elif State == "Foreign":
        raise SetupError("That folder already has other files in it. Pick an empty folder or a new one.")
    NeedsChoice = bool(LegacyMode in ("MoveRemove", "MoveKeep") and LegacyPath and not SameAsLegacy
                       and Legacy.AccountsPresent(os.path.join(Path, "Config"))
                       and Legacy.AccountsPresent(Legacy.ConfigDir(LegacyPath)))
    return {"Ok": True, "Path": Path, "State": State, "NeedsConfigChoice": NeedsChoice}


def RunInstall(Version, InstallPath, Report, Release=None, CachedSlot="", Kind="Install",
               LegacyMode="", LegacyPath="", ConfigChoice="KeepNew", Kept=None, UseKept=True, Shortcuts=None):
    """The whole pipeline (module docstring). Report(**Progress) gets Test1's progress fields.
    Kept = FindKeptConfig() for a fresh install (UseKept: bring those accounts back or start fresh).
    Shortcuts = the shortcut names ticked for an install; None (update / repair / undo) = the ones chosen at install.
    Returns {Version, Branch, Path, Warnings, MovedLegacy, KeptLine, OldVersion, Shortcuts}."""
    Shortcuts = ChosenShortcuts() if Shortcuts is None else [Name for Name in ShortcutNames if Name in Shortcuts]
    Warnings = []
    KeptLine = ""
    Check = CheckTarget(InstallPath, LegacyMode, LegacyPath)
    InstallPath = Check["Path"]
    LegacyHere = Check["State"] == "Legacy"
    if FindRunning([InstallPath, LegacyPath]):
        raise SetupError("RAMMIT is running. Close it first.", Running=True)
    OldVersion = (ReadManifest(InstallPath) or {}).get("Version", "")
    Staging = InstallPath + StagingSuffix
    TempDir = tempfile.mkdtemp(prefix="RAMMIT-Setup-")
    LegacyMoved = InstallPath + OldSuffix if LegacyHere else LegacyPath
    try:
        # ---- 1. a verified zip
        Report(StageLabel="Downloading", StagePct=0, StageDetail="", OverallPct=0, ActiveStage=0)
        if CachedSlot:
            Cached = CachedRelease(CachedSlot)
            if not Cached or Cached["Version"] != Version:
                raise SetupError("The saved copy for Undo is gone. Use Change version instead.")
            Report(StageDetail=f"Using the saved copy of v{Version}", StagePct=50, OverallPct=20)
            ZipPath, Sha = Cached["ZipPath"], Releases.VerifySha(Cached["ZipPath"], Cached["Sha256"])
            Branch = Cached["Branch"]
        else:
            Branch = Release.get("Branch") or Releases.BranchOf(Version, Release.get("Prerelease"))
            def OnBytes(Done, Total):
                Pct = int(Done * 100 / Total) if Total else 0
                Report(StagePct=Pct, OverallPct=int(Pct * 0.55),
                       StageDetail=f"{Release['ZipName']} - {_Size(Done)} / {_Size(Total)}" if Total else f"{Release['ZipName']} - {_Size(Done)}")
            ZipPath, Sha = Releases.DownloadRelease(Release, TempDir, OnBytes)
        Report(StagePct=100, StageDetail="SHA-256 checked", OverallPct=60, ActiveStage=1)

        # ---- 2. extract + manifest
        Report(StageLabel="Unzipping", StagePct=0, StageDetail="", OverallPct=60)
        Files = ExtractToStaging(ZipPath, Staging, lambda Done, Total, Rel: Report(
            StagePct=int(Done * 100 / Total), StageDetail=Rel, OverallPct=60 + int(Done * 20 / Total)))
        WriteManifest(Staging, Version, Files, Branch)
        Report(StagePct=100, OverallPct=80, ActiveStage=2)

        # ---- 3. backup + swap
        Report(StageLabel="Installing", StagePct=0, StageDetail="", OverallPct=80)
        if OldVersion and OldVersion != Version:
            Report(StageDetail="Backing up Config")
            BackupConfig(InstallPath, OldVersion)
        if LegacyHere:
            # The old Test1 install is in this very folder: move it aside whole (nothing is deleted yet).
            if os.path.exists(LegacyMoved):
                raise SetupError(f"A folder named {os.path.basename(LegacyMoved)} is in the way. Move or delete it, then try again.")
            try:
                _MoveFile(InstallPath, LegacyMoved)
            except OSError as Error:
                raise SetupError("The old version's folder is in use. Close it and try again.", f"{type(Error).__name__}: {Error}")
        Report(StageDetail="Swapping folders", StagePct=50, OverallPct=85)
        try:
            SwapIn(Staging, InstallPath)
        except Exception:
            if LegacyHere and not os.path.exists(InstallPath):
                _MoveFile(LegacyMoved, InstallPath)
            raise
        Report(StagePct=100, OverallPct=90, ActiveStage=3)

        # ---- 4. finishing up (the new version is in place; problems from here on are warnings)
        Report(StageLabel="Finishing up", StagePct=0, StageDetail="", OverallPct=90)
        if LegacyMode in ("MoveRemove", "MoveKeep") and LegacyMoved:
            Report(StageDetail="Moving accounts and settings")
            Warnings += Legacy.MoveConfig(LegacyMoved, InstallPath, ConfigChoice)
            RegDeleteValue("LegacyInstallPath")  # dealt with: no OLD VERSION button any more
        if LegacyMode == "MoveRemove" and LegacyMoved:
            Report(StageDetail="Removing the old version")
            Result = Legacy.Remove(LegacyMoved, IncludeConfig=True)
            Legacy.RemoveShortcuts()
            Legacy.ClearRegistry(LegacyPath or InstallPath)
            if Result["Left"]:
                Warnings.append("The old version's folder still holds: " + ", ".join(Result["Left"][:5]))
        if Kept:
            Report(StageDetail="Bringing back your accounts" if UseKept else "Putting earlier accounts aside")
            try:
                KeptLine = RestoreKeptConfig(Kept, InstallPath, UseKept, ConfigChoice)
            except OSError as Error:
                Warnings.append("Your earlier accounts couldn't be brought back. They are still in " + Kept["Path"] + ".")
                Logger.warning("Kept accounts not restored: %s", type(Error).__name__)
        elif RegRead(KeptValue) and Paths.SamePath(RegRead(KeptValue), InstallPath):
            RegDeleteValue(KeptValue)  # installed over the kept folder another way (old Test1 flow): Config is in use again
        Report(StageDetail="Writing registry", StagePct=25, OverallPct=93)
        RegWrite("InstallPath", InstallPath)
        RegWrite("Version", Version)
        RegWrite(ShortcutsValue, ",".join(Shortcuts))
        try:
            CopySetupExe()
            WriteUninstallEntry(InstallPath, Version)
        except OSError as Error:
            Warnings.append("RAMMIT couldn't be added to Settings > Apps.")
            Logger.warning("Apps entry failed: %s", Error)
        Report(StageDetail="Creating shortcuts", StagePct=60, OverallPct=96)
        try:
            CreateShortcuts(InstallPath, Shortcuts)
        except Exception as Error:
            Warnings.append("The shortcuts couldn't be created.")
            Logger.warning("Shortcuts failed: %s", type(Error).__name__)
            Shortcuts = []
        Report(StageDetail="Saving a copy for Undo", StagePct=85, OverallPct=98)
        UpdateCache(Version, ZipPath, Sha, OldVersion, FromSlot=CachedSlot, Branch=Branch)
        Report(StagePct=100, StageDetail="", OverallPct=100)
        Logger.info("%s finished: v%s in %s (was %s)", Kind, Version, InstallPath, OldVersion or "not installed")
        return {"Version": Version, "Branch": Branch, "Path": InstallPath, "Warnings": Warnings, "OldVersion": OldVersion,
                "MovedLegacy": LegacyMode in ("MoveRemove", "MoveKeep"), "KeptLine": KeptLine, "Shortcuts": Shortcuts}
    finally:
        _RemoveStaging(Staging)
        shutil.rmtree(TempDir, ignore_errors=True)


def _Size(Bytes):
    if Bytes < 1024:
        return f"{Bytes} B"
    if Bytes < 1024 * 1024:
        return f"{Bytes / 1024:.1f} KB"
    return f"{Bytes / (1024 * 1024):.1f} MB"


# ------------------------------------------------------------ uninstall

def RunUninstall(InstallPath, RemoveConfig, Report):
    """Deletes the manifest's files (and Config + Config.Backup if asked). Returns {Left, ConfigKept, Path}."""
    Manifest = ReadManifest(InstallPath)
    if FindRunning([InstallPath]):
        raise SetupError("RAMMIT is running. Close it first.", Running=True)
    Failed = []
    Report(Label="Deleting files", Pct=0, ActiveStage=0)
    if Manifest:
        Files = list(Manifest["Files"])
        for Index, Rel in enumerate(Files):
            Target = os.path.join(InstallPath, *str(Rel).replace("\\", "/").split("/"))
            if Paths.IsInside(InstallPath, Target) and not Paths.SamePath(InstallPath, Target) and os.path.isfile(Target):
                try:
                    os.remove(Target)
                except OSError:
                    Failed.append(Rel)
            if Index % 20 == 0:
                Report(Pct=int(Index * 90 / max(1, len(Files))))
        if Failed:
            raise SetupError("Some of RAMMIT's files are in use and couldn't be deleted. Close RAMMIT and try again.",
                             "in use: " + ", ".join(Failed[:10]))
        os.remove(os.path.join(InstallPath, ManifestName))
        if RemoveConfig:
            for Name in ("Config", "Config.Backup"):
                if os.path.isdir(os.path.join(InstallPath, Name)):
                    _RemoveTree(os.path.join(InstallPath, Name))
    Report(Pct=100, ActiveStage=1)
    Report(Label="Cleaning up")
    Left = []
    if os.path.isdir(InstallPath):
        for Root, _Dirs, _Files in os.walk(InstallPath, topdown=False):  # empty folders only
            if Root != InstallPath:
                try:
                    os.rmdir(Root)
                except OSError:
                    pass
        try:
            os.rmdir(InstallPath)
        except OSError:
            Left = sorted(Name for Name in os.listdir(InstallPath) if Name != UninstalledMarker)
            try:
                with open(os.path.join(InstallPath, UninstalledMarker), "w", encoding="utf-8") as File:
                    json.dump({"App": "RAMMIT", "UninstalledAt": time.strftime("%Y-%m-%dT%H:%M:%S"), "Left": Left}, File, indent=1)
            except OSError:
                pass
    ConfigKept = _HasFiles(os.path.join(InstallPath, "Config"))
    # Registry: the whole key goes (InstallPath, Version, LegacyInstallPath, any old Test1 values). When Config
    # stays, one value remembers where, so the next install can offer those accounts again (FindKeptConfig).
    RegDeleteKey()
    if ConfigKept:
        RegWrite(KeptValue, InstallPath)
    TidyRegistry()
    RemoveUninstallEntry()
    RemoveShortcuts(InstallPath)
    Report(Pct=100)
    Logger.info("Uninstalled %s (config removed: %s, kept: %s, left: %d)", InstallPath, RemoveConfig, ConfigKept, len(Left))
    RemoveSetupFolder()
    Others = [Name for Name in Left if Name.lower() not in OwnLeftovers]
    return {"Path": InstallPath, "ConfigKept": ConfigKept, "Left": Others, "HadManifest": bool(Manifest)}


# ------------------------------------------------------------ the installer's own folder (RAMMIT-Setup\)

_RemoveOnExit = []  # set by RemoveSetupFolder when the running program is the setup copy itself


def RemoveSetupFolder():
    """Deletes %LOCALAPPDATA%\\RAMMIT-Setup\\ (setup copy, Undo cache, log) after an uninstall. The log is closed
    first; the copy that is running right now can't be deleted, so FinishOnExit moves it out when the window closes."""
    L = Locations.Current
    ClearCache()
    import Log
    Log.Close()
    for Name in ("Setup.log", "Setup.log.1"):
        try:
            os.remove(os.path.join(L.SetupDir, Name))
        except OSError:
            pass
    if os.path.isfile(L.SetupExePath):
        if Paths.IsFrozen() and Paths.SamePath(sys.executable, L.SetupExePath):
            _RemoveOnExit.append(L.SetupExePath)
        else:
            try:
                os.remove(L.SetupExePath)
            except OSError:
                pass
    try:
        os.rmdir(L.SetupDir)
    except OSError:
        pass


def FinishOnExit():
    """Called by Installer.py after the window has closed. A running .exe can't be deleted on Windows, but it can
    be renamed on the same drive: the setup copy moves to %TEMP% (cleaned by Windows' Storage Sense / Disk Cleanup)
    and RAMMIT-Setup\\ is removed. Nothing is started and nothing is written to the registry for this."""
    for Exe in _RemoveOnExit:
        Target = os.path.join(tempfile.gettempdir(), f"RAMMIT-Setup-Removed-{os.getpid()}.exe")
        try:
            os.replace(Exe, Target)
            os.rmdir(os.path.dirname(Exe))
        except OSError:
            pass
