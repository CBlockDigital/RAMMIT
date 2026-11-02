"""Copy shared UI code from Src/Dark into the other built-in theme folders.

Every theme folder is a complete, independent copy of the UI (see App/Themes.py). That is great
for theme authors but means a code change (new button, bug fix) has to reach every folder.
Make the change in Src/Dark, then run:

    python Tools/SyncThemes.py            copy Dark's shared files into Light and MyCustomTheme
    python Tools/SyncThemes.py --check    only report what differs (the test suite runs this)

What is shared (overwritten):  HTML/, JS/, Fonts/, CSS/Phosphor-Bold.css, the icons, and the
LAYOUT section of CSS/Style.css.
What stays per theme:          the colour variables at the top of Style.css, its THEME EXTRAS
section, Theme.json and HeightMap.json.

User-made themes are never touched - pass their folder names explicitly if you want them synced.
"""
import filecmp
import os
import shutil
import sys

Root = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Src")
Source = "Dark"
DefaultTargets = ["Light", "MyCustomTheme", "CBlock"]
SharedDirs = ["HTML", "JS", "Fonts"]
SharedFiles = ["CSS/Phosphor-Bold.css", "RAMMIT.png", "RAMMIT.ico", "RAMMIT-Downloader.png", "RAMMIT-Downloader.ico"]
LayoutStart = "   LAYOUT - everything below is ordinary CSS using the variables above."
ExtrasStart = "/* =====================================================================\n   THEME EXTRAS"


def SplitStyle(Css):
    """(Variables, Layout, Extras) sections of a Style.css."""
    LayoutAt = Css.index(LayoutStart)
    LayoutAt = Css.rindex("/* ====", 0, LayoutAt)
    ExtrasAt = Css.index(ExtrasStart)
    return Css[:LayoutAt], Css[LayoutAt:ExtrasAt], Css[ExtrasAt:]


def RelativeFiles(Folder):
    for Dir, _Subdirs, Files in os.walk(Folder):
        for Name in Files:
            yield os.path.relpath(os.path.join(Dir, Name), Folder)


def Sync(Target, CheckOnly):
    Differences = []
    SourceDir, TargetDir = os.path.join(Root, Source), os.path.join(Root, Target)
    for Shared in SharedDirs:
        SrcSub, DstSub = os.path.join(SourceDir, Shared), os.path.join(TargetDir, Shared)
        Wanted = set(RelativeFiles(SrcSub))
        for Rel in sorted(Wanted):
            SrcFile, DstFile = os.path.join(SrcSub, Rel), os.path.join(DstSub, Rel)
            if not os.path.exists(DstFile) or not filecmp.cmp(SrcFile, DstFile, shallow=False):
                Differences.append(os.path.join(Shared, Rel))
                if not CheckOnly:
                    os.makedirs(os.path.dirname(DstFile), exist_ok=True)
                    shutil.copy2(SrcFile, DstFile)
        for Rel in sorted(set(RelativeFiles(DstSub)) - Wanted if os.path.isdir(DstSub) else []):
            Differences.append(os.path.join(Shared, Rel) + " (extra)")
            if not CheckOnly:
                os.remove(os.path.join(DstSub, Rel))
    for Rel in SharedFiles:
        SrcFile, DstFile = os.path.join(SourceDir, Rel), os.path.join(TargetDir, Rel)
        if not os.path.exists(DstFile) or not filecmp.cmp(SrcFile, DstFile, shallow=False):
            Differences.append(Rel)
            if not CheckOnly:
                shutil.copy2(SrcFile, DstFile)
    StylePath = os.path.join(TargetDir, "CSS", "Style.css")
    with open(os.path.join(SourceDir, "CSS", "Style.css"), encoding="utf-8") as File:
        _V, SourceLayout, _E = SplitStyle(File.read())
    with open(StylePath, encoding="utf-8") as File:
        Variables, Layout, Extras = SplitStyle(File.read())
    if Layout != SourceLayout:
        Differences.append("CSS/Style.css (LAYOUT section)")
        if not CheckOnly:
            with open(StylePath, "w", encoding="utf-8") as File:
                File.write(Variables + SourceLayout + Extras)
    return Differences


def Main(Args):
    CheckOnly = "--check" in Args
    Targets = [A for A in Args if not A.startswith("--")] or DefaultTargets
    Total = 0
    for Target in Targets:
        Differences = Sync(Target, CheckOnly)
        Total += len(Differences)
        Verb = "differs from Dark" if CheckOnly else "updated from Dark"
        for Item in Differences:
            print(f"{Target}: {Item} {Verb}")
    print(f"{Total} difference(s)" if CheckOnly else f"Synced {Total} file(s)/section(s)")
    return 1 if CheckOnly and Total else 0


if __name__ == "__main__":
    sys.exit(Main(sys.argv[1:]))
