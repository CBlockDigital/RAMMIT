# -*- mode: python ; coding: utf-8 -*-
# PyInstaller recipe. Use Build.ps1 rather than calling this directly: it runs the tests first
# and assembles the finished folder + zip. The web UI (Src/) is NOT bundled into the exe - it ships
# next to it so themes can be added and edited.
#
# Antivirus false positives: Defender's ML flagged the old one-file build
# (Behavior:Win32/DefenseEvasion.A!ml). One-file exes unpack Python into %TEMP% on every start,
# which looks like a malware dropper. So this builds a FOLDER app (RAMMIT.exe + Runtime\),
# never UPX-packs, and carries full version info. Code-signing is the only real guarantee.
import os
import re
import sys

from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo, StringFileInfo, StringStruct, StringTable, VarFileInfo, VarStruct, VSVersionInfo)

sys.path.insert(0, os.path.abspath('.'))
from App.Version import AppName, AppVersion  # noqa: E402

VersionNumbers = tuple(int(Part) for Part in re.findall(r'\d+', AppVersion)[:4]) + (0,) * 4
VersionNumbers = VersionNumbers[:4]
VersionResource = VSVersionInfo(
    ffi=FixedFileInfo(filevers=VersionNumbers, prodvers=VersionNumbers),
    kids=[
        StringFileInfo([StringTable('040904B0', [
            StringStruct('CompanyName', 'RAMMIT'),
            StringStruct('FileDescription', 'RAMMIT - Roblox Multi-Account Launcher'),
            StringStruct('FileVersion', AppVersion),
            StringStruct('InternalName', AppName),
            StringStruct('OriginalFilename', 'RAMMIT.exe'),
            StringStruct('ProductName', 'RAMMIT'),
            StringStruct('ProductVersion', AppVersion),
        ])]),
        VarFileInfo([VarStruct('Translation', [0x0409, 1200])]),
    ],
)

Analyzed = Analysis(
    ['RAMMIT.py'],
    pathex=['.'],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter'],
    noarchive=False,
    optimize=0,
)
Pyz = PYZ(Analyzed.pure)

Exe = EXE(
    Pyz,
    Analyzed.scripts,
    [],
    exclude_binaries=True,
    name='RAMMIT',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['Src/Dark/RAMMIT.ico'],
    version=VersionResource,
    contents_directory='Runtime',
)

Bundle = COLLECT(
    Exe,
    Analyzed.binaries,
    Analyzed.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='RAMMIT',
)
