"""Every file-system location RAMMIT uses, resolved once.

Runtime layout (frozen exe and source checkout are identical):

    <BaseDir>/RAMMIT.exe      (or RAMMIT.py when running from source)
    <BaseDir>/Src/<Theme>/    one complete UI per theme (Dark, Light, MyCustomTheme, ...),
                              the active one is served by LocalServer - see App/Themes.py
    <BaseDir>/Config/         Accounts.json, Settings.json, Config.json, RAMMIT.log

Set the RAMMIT_BASE_DIR environment variable to point everything at another folder
(the test suite does this so it never touches a real Config folder).
"""
import os
import sys


def _ResolveBaseDir():
    Override = os.environ.get("RAMMIT_BASE_DIR")
    if Override:
        return os.path.abspath(Override)
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


BaseDir = _ResolveBaseDir()
SrcDir = os.path.join(BaseDir, "Src")
ConfigDir = os.path.join(BaseDir, "Config")

AccountsFile = os.path.join(ConfigDir, "Accounts.json")
SettingsFile = os.path.join(ConfigDir, "Settings.json")
ConfigsFile = os.path.join(ConfigDir, "Config.json")
LogFile = os.path.join(ConfigDir, "RAMMIT.log")


def EnsureConfigDir():
    os.makedirs(ConfigDir, exist_ok=True)


def IsInside(Root, Candidate):
    """True when Candidate resolves to Root itself or somewhere beneath it (blocks ../ escapes)."""
    RootReal = os.path.normcase(os.path.realpath(Root))
    CandReal = os.path.normcase(os.path.realpath(Candidate))
    try:
        return os.path.commonpath([RootReal, CandReal]) == RootReal
    except ValueError:  # different drives
        return False
