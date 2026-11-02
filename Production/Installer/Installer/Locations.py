"""Every folder and registry key the installer touches, resolved in one place.

Normal mode (what users get):
    registry      HKCU\\Software\\CBlock Digital\\RAMMIT                         InstallPath, Version, IgnoreLegacyInstall
    Apps list     HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\RAMMIT
    shortcuts     <Desktop>\\RAMMIT.lnk and <Start Menu>\\Programs\\RAMMIT.lnk
    install       %LOCALAPPDATA%\\RAMMIT (default, the user can pick another folder)
    setup copy    %LOCALAPPDATA%\\RAMMIT-Setup\\RAMMIT-Setup.exe, Cache\\ (zips for Undo), Setup.log

Test mode (environment variable RAMMIT_INSTALLER_TEST=1) moves ALL of it somewhere harmless, so tests and
manual try-outs can never touch a real install:
    registry      HKCU\\Software\\CBlock Digital\\RAMMIT-InstallerTest         (override: RAMMIT_INSTALLER_REGKEY)
    Apps list     ...\\Uninstall\\RAMMIT-InstallerTest                          (override: RAMMIT_INSTALLER_UNINSTALL_NAME)
    folders       %TEMP%\\RAMMIT-InstallerTest\\{Desktop, StartMenu, LocalAppData}  (override: RAMMIT_INSTALLER_TEST_ROOT)
    releases      RAMMIT_INSTALLER_RELEASES_URL may point at a fake release server (ignored outside test mode)

Call Reload() after changing those environment variables (the tests do); everything else reads Current.
"""
import os
import tempfile

RealRegKeyPath = r"Software\CBlock Digital\RAMMIT"
UninstallParentPath = r"Software\Microsoft\Windows\CurrentVersion\Uninstall"
RealUninstallName = "RAMMIT"
SetupExeName = "RAMMIT-Setup.exe"


class _Locations:
    def __init__(self):
        self.TestMode = os.environ.get("RAMMIT_INSTALLER_TEST") == "1"
        if self.TestMode:
            Root = os.path.abspath(os.environ.get("RAMMIT_INSTALLER_TEST_ROOT")
                                   or os.path.join(tempfile.gettempdir(), "RAMMIT-InstallerTest"))
            self.TestRoot = Root
            self.RegKeyPath = os.environ.get("RAMMIT_INSTALLER_REGKEY") or r"Software\CBlock Digital\RAMMIT-InstallerTest"
            self.UninstallName = os.environ.get("RAMMIT_INSTALLER_UNINSTALL_NAME") or "RAMMIT-InstallerTest"
            self.DesktopDir = os.path.join(Root, "Desktop")
            self.StartMenuDir = os.path.join(Root, "StartMenu")
            LocalAppData = os.path.join(Root, "LocalAppData")
            self.ReleasesUrlOverride = os.environ.get("RAMMIT_INSTALLER_RELEASES_URL", "")
        else:
            self.TestRoot = ""
            self.RegKeyPath = RealRegKeyPath
            self.UninstallName = RealUninstallName
            self.DesktopDir = _KnownFolder("Desktop", os.path.join(os.environ.get("USERPROFILE", ""), "Desktop"))
            self.StartMenuDir = os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Windows", "Start Menu", "Programs")
            LocalAppData = os.environ.get("LOCALAPPDATA", "")
            self.ReleasesUrlOverride = ""
        self.UninstallKeyPath = UninstallParentPath + "\\" + self.UninstallName
        self.DefaultInstallPath = os.path.join(LocalAppData, "RAMMIT")
        # Kept OUTSIDE the install folder: the folder swap and the manifest-only uninstall never touch it.
        self.SetupDir = os.path.join(LocalAppData, "RAMMIT-Setup")
        self.CacheDir = os.path.join(self.SetupDir, "Cache")
        self.LogFile = os.path.join(self.SetupDir, "Setup.log")
        self.SetupExePath = os.path.join(self.SetupDir, SetupExeName)
        self._CheckTestModeIsolated()

    def _CheckTestModeIsolated(self):
        """Refuse to run a test-mode installer that would still point at the real key or folders."""
        if not self.TestMode:
            return
        Problems = []
        if self.RegKeyPath.lower() == RealRegKeyPath.lower() or "test" not in self.RegKeyPath.lower():
            Problems.append("registry key")
        if self.UninstallName.lower() == RealUninstallName.lower() or "test" not in self.UninstallName.lower():
            Problems.append("uninstall entry")
        RealLocal = os.path.normcase(os.path.join(os.environ.get("LOCALAPPDATA", "?"), "RAMMIT"))
        if os.path.normcase(self.DefaultInstallPath) == RealLocal:
            Problems.append("install folder")
        if Problems:
            raise RuntimeError("Test mode would touch the real " + ", ".join(Problems))


def _KnownFolder(Name, Fallback):
    """The user's real Desktop (it may be redirected to OneDrive), via the shell."""
    try:
        from win32com.shell import shell, shellcon
        Folder = {"Desktop": shellcon.CSIDL_DESKTOPDIRECTORY}[Name]
        return shell.SHGetFolderPath(0, Folder, None, 0)
    except Exception:
        return Fallback


Current = _Locations()


def Reload():
    global Current
    Current = _Locations()
    return Current
