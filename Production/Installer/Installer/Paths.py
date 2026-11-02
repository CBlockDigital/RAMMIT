"""Path helpers shared by the installer modules (IsInside is RAMMIT's App/Paths.py check, unchanged)."""
import os
import sys


def IsInside(Root, Candidate):
    """True when Candidate resolves to Root itself or somewhere beneath it (blocks ../ escapes)."""
    RootReal = os.path.normcase(os.path.realpath(Root))
    CandReal = os.path.normcase(os.path.realpath(Candidate))
    try:
        return os.path.commonpath([RootReal, CandReal]) == RootReal
    except ValueError:  # different drives
        return False


def SamePath(First, Second):
    return os.path.normcase(os.path.realpath(First)) == os.path.normcase(os.path.realpath(Second))


def BundleDir():
    """Where the embedded files are: PyInstaller's unpack folder when frozen, else this folder."""
    return getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))


def IsFrozen():
    return bool(getattr(sys, "frozen", False))
