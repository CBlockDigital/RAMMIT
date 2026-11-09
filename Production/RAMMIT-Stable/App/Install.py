"""Keeps the installer's registry entries right when the RAMMIT folder was moved by hand.

The installer (Production/Installer) records where RAMMIT is (HKCU\\Software\\CBlock Digital\\RAMMIT, InstallPath) and
registers the RAMMIT: protocol that its shortcuts open (HKCU\\Software\\Classes\\RAMMIT). When RAMMIT starts from another
folder and the recorded one no longer has a RAMMIT.exe, the folder was moved: both are pointed here (plus the Settings >
Apps entry), so every RAMMIT: shortcut works again, wherever it is, and the installer finds RAMMIT for updates.

Only a folder the installer made can take over: it holds the installer's Manifest.json, which a copy unzipped from a
release (or opened straight from the zip) doesn't. A second copy started while the installed one is still in place changes
nothing, and neither does a copy that was never installed (no InstallPath), one on a removable drive (it would break again
once the drive is gone), or one started by the installer's test mode (RAMMIT_INSTALLER_TEST=1, inherited from the test
installer, which must never touch the real entries). Main.py only calls this from the frozen exe, so running from source
never touches the registry.
"""
import ctypes
import os
import winreg

RegKeyPath = r"Software\CBlock Digital\RAMMIT"
ProtocolKeyPath = r"Software\Classes\RAMMIT"
UninstallKeyPath = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\RAMMIT"
ManifestName = "Manifest.json"  # what the installer writes into every folder it installs (Installer/Setup.py)
DriveRemovable = 2  # GetDriveTypeW


def _Read(KeyPath, Name=""):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, KeyPath) as Key:
            return str(winreg.QueryValueEx(Key, Name)[0])
    except OSError:
        return None


def _Write(KeyPath, Name, Value):
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, KeyPath, 0, winreg.KEY_WRITE) as Key:
        winreg.SetValueEx(Key, Name, 0, winreg.REG_SZ, Value)


def _SamePath(First, Second):
    return os.path.normcase(os.path.realpath(First)) == os.path.normcase(os.path.realpath(Second))


def _OnRemovableDrive(Folder):
    Drive = os.path.splitdrive(os.path.abspath(Folder))[0]
    if not Drive or Drive.startswith("\\\\"):
        return False  # a network share is fixed enough
    try:
        return ctypes.windll.kernel32.GetDriveTypeW(Drive + "\\") == DriveRemovable
    except (AttributeError, OSError):
        return False


def _RegisterProtocol(ProtocolKey, Exe):
    """Same entries as the installer's Setup.RegisterProtocol: RAMMIT: starts Exe, with nothing from the link."""
    _Write(ProtocolKey, "", "URL:RAMMIT")
    _Write(ProtocolKey, "URL Protocol", "")
    _Write(ProtocolKey + r"\DefaultIcon", "", f'"{Exe}",0')
    _Write(ProtocolKey + r"\shell\open\command", "", f'"{Exe}"')


def Sync(BaseDir, RegKey=RegKeyPath, ProtocolKey=ProtocolKeyPath, UninstallKey=UninstallKeyPath):
    """Returns "Moved" (InstallPath and RAMMIT: now point at BaseDir), "Fixed" (only RAMMIT: was re-pointed), or ""."""
    if os.environ.get("RAMMIT_INSTALLER_TEST") == "1":
        return ""  # started by the installer's test mode
    Recorded = _Read(RegKey, "InstallPath")
    Exe = os.path.join(BaseDir, "RAMMIT.exe")
    if not Recorded or not os.path.isfile(Exe):
        return ""  # never installed with the installer (or uninstalled)
    if not os.path.isfile(os.path.join(BaseDir, ManifestName)) or _OnRemovableDrive(BaseDir):
        return ""  # not a folder the installer made (e.g. a release zip's copy), or on a removable drive
    Result = ""
    if not _SamePath(Recorded, BaseDir):
        if os.path.isfile(os.path.join(Recorded, "RAMMIT.exe")):
            return ""  # the installed RAMMIT is still there: this is another copy, leave its entries alone
        _Write(RegKey, "InstallPath", BaseDir)
        if _Read(UninstallKey, "UninstallString") is not None:
            _Write(UninstallKey, "InstallLocation", BaseDir)
            _Write(UninstallKey, "DisplayIcon", f'"{Exe}",0')
        Result = "Moved"
    if _Read(ProtocolKey + r"\shell\open\command") != f'"{Exe}"':
        _RegisterProtocol(ProtocolKey, Exe)
        Result = Result or "Fixed"
    return Result
