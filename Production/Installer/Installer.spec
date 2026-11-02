# -*- mode: python ; coding: utf-8 -*-
# PyInstaller recipe for RAMMIT-Setup.exe: ONE self-contained file (user decision 2026-11-02). The page, CSS, JS,
# icon font and icons are bundled and served from memory (Installer/UiServer.py), so it needs no RAMMIT on the PC.
#
#     python -m PyInstaller Installer.spec --noconfirm --clean
#
# Antivirus: one-file PyInstaller exes unpack Python into %TEMP% on start, which Defender's ML has flagged before
# (Behavior:Win32/DefenseEvasion.A!ml, a false positive). Mitigations kept here: no UPX, full version info, only the
# installer's own dependencies, no tkinter. Scan every build with MpCmdRun; code signing is the real fix.
#
# Version: the ONE version source is RAMMIT's App/Version.py (AppVersion). Set RAMMIT_VERSION_FILE to point at it;
# the default is the Stable tree next to this folder. It is written into Installer/BuildInfo.py for this build only.
import os
import re

from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo, StringFileInfo, StringStruct, StringTable, VarFileInfo, VarStruct, VSVersionInfo)

Here = os.path.abspath(SPECPATH)
InstallerDir = os.path.join(Here, 'Installer')
VersionFile = os.environ.get('RAMMIT_VERSION_FILE') or os.path.join(Here, '..', 'RAMMIT-Stable', 'App', 'Version.py')
with open(VersionFile, encoding='utf-8') as File:
    AppVersion = re.search(r'^AppVersion\s*=\s*"([^"]+)"', File.read(), re.M).group(1)

BuildInfo = os.path.join(InstallerDir, 'BuildInfo.py')
with open(BuildInfo, 'w', encoding='utf-8') as File:
    File.write(f'# Written by Installer.spec for one build, then deleted. Never commit.\nInstallerVersion = "{AppVersion}"\n')

VersionNumbers = (tuple(int(Part) for Part in re.findall(r'\d+', AppVersion)[:4]) + (0,) * 4)[:4]
VersionResource = VSVersionInfo(
    ffi=FixedFileInfo(filevers=VersionNumbers, prodvers=VersionNumbers),
    kids=[
        StringFileInfo([StringTable('040904B0', [
            StringStruct('CompanyName', 'CBlock Digital'),
            StringStruct('FileDescription', 'RAMMIT Setup - installs RAMMIT, the Roblox Multi-Account Launcher'),
            StringStruct('FileVersion', AppVersion),
            StringStruct('InternalName', 'RAMMIT-Setup'),
            StringStruct('LegalCopyright', 'CBlock Digital'),
            StringStruct('OriginalFilename', 'RAMMIT-Setup.exe'),
            StringStruct('ProductName', 'RAMMIT'),
            StringStruct('ProductVersion', AppVersion),
        ])]),
        VarFileInfo([VarStruct('Translation', [0x0409, 1200])]),
    ],
)

try:
    Analyzed = Analysis(
        [os.path.join(InstallerDir, 'Installer.py')],
        pathex=[InstallerDir],
        binaries=[],
        datas=[
            (os.path.join(InstallerDir, 'Ui'), 'Ui'),
            (os.path.join(InstallerDir, 'HeightMap.json'), '.'),
            (os.path.join(InstallerDir, 'RAMMIT-Downloader.ico'), '.'),
            (os.path.join(InstallerDir, 'RAMMIT-Downloader.png'), '.'),
        ],
        hiddenimports=['BuildInfo', 'win32com.shell.shell', 'win32com.shell.shellcon', 'pythoncom'],
        hookspath=[],
        hooksconfig={},
        runtime_hooks=[],
        excludes=['tkinter', 'requests', 'urllib3', 'numpy', 'PIL', 'unittest', 'pydoc'],
        noarchive=False,
        optimize=0,
    )
finally:
    os.remove(BuildInfo)

Pyz = PYZ(Analyzed.pure)

Exe = EXE(
    Pyz,
    Analyzed.scripts,
    Analyzed.binaries,
    Analyzed.datas,
    [],
    name='RAMMIT-Setup',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=[os.path.join(InstallerDir, 'RAMMIT-Downloader.ico')],
    version=VersionResource,
)
