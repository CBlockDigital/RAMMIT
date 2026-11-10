"""Themes = complete UI folders inside Src/.

    Src/Dark/            default, shipped
    Src/Light/           2016 Roblox look, shipped
    Src/MyCustomTheme/   example custom theme, shipped
    Src/<YourTheme>/     any folder you add

Each theme folder is the whole web root the windows load - HTML, JS, CSS, Fonts, icons -
plus two small files:

    Theme.json      {"Name", "Author", "Description", "SupportedVersions", "Swatch"}  (all optional)
    HeightMap.json  {"MainWindow": {...}, "WizardWindow": {...}}  window sizes, see below

"SupportedVersions" lists the RAMMIT versions a theme was made for: "1.0" = any 1.0.x, "1.0.2" = exactly
that one, "1.2+" = 1.2.0 or newer. Picking a theme that doesn't list this RAMMIT asks first, and a chosen
theme that stops matching (after a RAMMIT update) opens Dark until the user says to use it anyway.

Nothing is mixed between themes. The only fallback: if the chosen theme folder is missing or
has no HTML/Index.html, RAMMIT serves Dark so the window is never blank.

A theme folder can contain HTML and JavaScript, so a theme is trusted code - only install
themes from people you trust (the page's Content-Security-Policy still blocks anything from
outside RAMMIT). Author guide: HowToMakeATheme.txt / Docs/CustomThemes.md.
"""
import colorsys
import json
import os
import re

from App import Paths
from App.Version import AppVersion

DefaultThemeId = "Dark"
_VersionPattern = re.compile(r"^(\d{1,4})(?:\.(\d{1,4}))?(?:\.(\d{1,4}))?(\+?)$")
IdPattern = re.compile(r"^[A-Za-z0-9_()-][A-Za-z0-9 _().-]{0,39}$")
RequiredFile = os.path.join("HTML", "Index.html")
MaxJsonBytes = 64 * 1024
_ColorPattern = re.compile(r"^(#[0-9a-fA-F]{3,8}|(rgb|rgba|hsl|hsla)\([0-9.%\s,/deg+-]{1,60}\))$")

# HeightMap.json defaults (logical px). MainWindow: window height per launch option, before the
# 0.85 UI scale, plus PlayerFilterExtra added when Min/Max player boxes show.
DefaultHeightMap = {
    # Tuned (measured at 150%) so the Settings card is the same height for every option: SAVE SETTINGS ->
    # version line is 25.5 px everywhere and version line -> card bottom stays within 4.4-5.1 px.
    "MainWindow": {"Home": 716, "Config": 716, "Game URL": 897, "Place ID": 897,
                   "Place ID + Job ID": 801, "VIP Link": 759, "PlayerFilterExtra": 50},
    # Started from Test1's tuned values; Home/VIP +1 and ExtraPadding +2 so every method leaves the same
    # ~4.4-5 px under the error line (measured at 150%).
    "WizardWindow": {"Width": 400, "Home": 288, "Game URL": 495, "Place ID": 495, "Place ID + Job ID": 428,
                     "VIP Link": 354, "ExtraPadding": 22},
}
_HeightLimits = {"MainWindow": (0, 1400), "WizardWindow": (0, 1200)}


def IsValidId(ThemeId):
    return isinstance(ThemeId, str) and bool(IdPattern.match(ThemeId)) and ".." not in ThemeId


def ThemeDir(ThemeId):
    """Folder of a usable theme, or None."""
    if not IsValidId(ThemeId):
        return None
    Folder = os.path.join(Paths.SrcDir, ThemeId)
    if os.path.isfile(os.path.join(Folder, RequiredFile)) and Paths.IsInside(Paths.SrcDir, Folder):
        return Folder
    return None


def ResolveRoot(ThemeId):
    """(ThemeId, Folder) actually served for a requested theme - Dark if it is unusable."""
    Folder = ThemeDir(ThemeId)
    if Folder:
        return ThemeId, Folder
    return DefaultThemeId, os.path.join(Paths.SrcDir, DefaultThemeId)


def _ReadJson(FilePath):
    if not os.path.isfile(FilePath):
        return None, None
    try:
        if os.path.getsize(FilePath) > MaxJsonBytes:
            return None, f"{os.path.basename(FilePath)} is too big"
        with open(FilePath, "r", encoding="utf-8-sig") as File:
            Data = json.load(File)
        return (Data, None) if isinstance(Data, dict) else (None, f"{os.path.basename(FilePath)} must be a {{ ... }} object")
    except (OSError, ValueError) as Error:
        return None, f"{os.path.basename(FilePath)} could not be read ({type(Error).__name__})"


# ---------------------------------------------------------------- colour swatch
# Four fixed slots, always in this order (Themes.js, BackgroundColor and AccentColor rely on it).
# Each slot reads the theme's CSS variable of the same name, or the variable Theme.json points it
# at:  "Swatch": {"Accent": "--Brand"}.  var() references are followed, comments are ignored, and
# any slot that can't be read falls back to Dark's colour for that slot.
SwatchSlots = ("Background", "Card", "Accent", "Text")
_LastResortSwatch = ("#0a0a0a", "#141414", "#0078d4", "#ffffff")  # Dark's values, if even Dark is unreadable
_VarNamePattern = re.compile(r"^--[A-Za-z0-9_-]{1,60}$")
_NamedColorPattern = re.compile(r"^[a-zA-Z]{3,20}$")
_NotColors = {"inherit", "initial", "unset", "revert", "none", "auto", "currentcolor", "transparent"}
MaxCssBytes = 1024 * 1024


def _CssVariables(Folder):
    """{"--Name": "value"} from CSS/Style.css with comments removed. The first definition wins."""
    try:
        with open(os.path.join(Folder, "CSS", "Style.css"), "r", encoding="utf-8-sig") as File:
            Css = File.read(MaxCssBytes)
    except OSError:
        return {}
    Css = re.sub(r"/\*.*?\*/", "", Css, flags=re.S)
    Variables = {}
    for Name, Value in re.findall(r"(--[A-Za-z0-9_-]+)\s*:\s*([^;{}]+?)\s*;", Css):
        Variables.setdefault(Name, Value)
    return Variables


def _ResolveColor(Value, Variables, Depth=0):
    """A usable colour for a CSS value, following var(--X[, fallback]) chains, or None."""
    Value = (Value or "").strip()
    if Depth > 10:
        return None
    Reference = re.fullmatch(r"var\(\s*(--[A-Za-z0-9_-]+)\s*(?:,\s*(.+))?\)", Value)
    if Reference:
        Name, Fallback = Reference.groups()
        if Name in Variables:
            return _ResolveColor(Variables[Name], Variables, Depth + 1)
        return _ResolveColor(Fallback, Variables, Depth + 1) if Fallback else None
    if _ColorPattern.match(Value):
        return Value
    # A name counts only if it is a real CSS colour, so swatch, window and spinner always agree.
    if _NamedColorPattern.match(Value) and Value.lower() not in _NotColors and _NamedColorHex(Value):
        return Value.lower()
    return None


def _ReadSwatch(Folder, Meta):
    """([colour or None] x 4, warnings) for a theme folder."""
    Variables = _CssVariables(Folder)
    Pointers = Meta.get("Swatch") if isinstance(Meta.get("Swatch"), dict) else {}
    Colors, Warnings = [], []
    for Slot in SwatchSlots:
        # Order (user rule): the standard --Slot variable first, then the Theme.json "Swatch" link,
        # then Dark's colour (filled in by _Swatch).
        Candidates = ["--" + Slot]
        Pointer = Pointers.get(Slot)
        if Pointer is not None:
            if isinstance(Pointer, str) and _VarNamePattern.match(Pointer):
                Candidates.append(Pointer)
            else:
                Warnings.append(f'Theme.json Swatch.{Slot} must be a CSS variable name like "--MyColour".')
        Color = next((Found for Found in (_ResolveColor(Variables[Name], Variables) for Name in Candidates if Name in Variables) if Found), None)
        if Color is None:
            Tried = " or ".join(dict.fromkeys(Candidates))
            Warnings.append(f"Swatch {Slot}: {Tried} is missing or not a colour in CSS\\Style.css - using Dark's.")
        Colors.append(Color)
    return Colors, Warnings


def _Swatch(Folder, Meta):
    """Exactly 4 colours: the theme's own, with Dark's colour in any slot it doesn't define."""
    Colors, _Warnings = _ReadSwatch(Folder, Meta)
    if None in Colors:
        DarkFolder = os.path.join(Paths.SrcDir, DefaultThemeId)
        DarkMeta = _ReadJson(os.path.join(DarkFolder, "Theme.json"))[0] or {}
        DarkColors = _ReadSwatch(DarkFolder, DarkMeta)[0] if os.path.normcase(DarkFolder) != os.path.normcase(Folder) else [None] * 4
        Colors = [Own or Dark or Last for Own, Dark, Last in zip(Colors, DarkColors, _LastResortSwatch)]
    return Colors


# ---------------------------------------------------------------- supported RAMMIT versions

def ParseSupportedVersions(Value):
    """(Entries, Warnings) from Theme.json "SupportedVersions". Entries is None when the field is absent."""
    if Value is None:
        return None, []
    if isinstance(Value, str):
        Value = [Value]
    if not isinstance(Value, list):
        return [], ['Theme.json "SupportedVersions" must be a list like ["1.0"].']
    Entries, Bad = [], []
    for Entry in Value[:20]:
        Text = Entry.strip() if isinstance(Entry, str) else ""
        (Entries if _VersionPattern.match(Text) else Bad).append(Text or str(Entry)[:20])
    Warnings = [f'Theme.json "SupportedVersions" has entries RAMMIT can\'t read: {", ".join(Bad[:3])} '
                '(use "1.0", "1.0.2" or "1.2+").'] if Bad else []
    return Entries, Warnings


def _VersionTuple(Text):
    return tuple(int(Part) for Part in Text.split(".")[:3]) + (0,) * (3 - len(Text.split(".")[:3]))


def SupportsVersion(Entries, Version=AppVersion):
    """True if any entry matches: "1.0" = 1.0.x, "1.0.2" exact, "1.2+" = 1.2.0 or newer."""
    Current = _VersionTuple(Version)
    for Entry in Entries:
        Match = _VersionPattern.match(Entry)
        if not Match:
            continue
        Parts = tuple(int(Part) for Part in Match.groups()[:3] if Part is not None)
        if Match.group(4):
            if Current >= Parts + (0,) * (3 - len(Parts)):
                return True
        elif Current[:len(Parts)] == Parts:
            return True
    return False


def VersionCheck(ThemeId):
    """{"Supported": [...] or None, "Compatible": True / False / None (theme doesn't say)} from Theme.json only."""
    Folder = ThemeDir(ThemeId)
    Meta = (_ReadJson(os.path.join(Folder, "Theme.json"))[0] or {}) if Folder else {}
    Entries, _Warnings = ParseSupportedVersions(Meta.get("SupportedVersions"))
    if Entries is None:
        return {"Supported": None, "Compatible": None}
    return {"Supported": Entries, "Compatible": SupportsVersion(Entries)}


def ThemeInfo(ThemeId):
    Folder = ThemeDir(ThemeId)
    if not Folder:
        return None
    Meta, _Error = _ReadJson(os.path.join(Folder, "Theme.json"))
    Meta = Meta or {}

    def Text(Key, Default):
        Value = Meta.get(Key)
        return Value.strip()[:60] if isinstance(Value, str) and Value.strip() else Default
    return {"Id": ThemeId, "Name": Text("Name", ThemeId), "Author": Text("Author", "Unknown"),
            "Description": Text("Description", ""), "Swatch": _Swatch(Folder, Meta), **VersionCheck(ThemeId)}


def ListThemes():
    """Every usable theme folder in Src/, Dark first."""
    try:
        Names = sorted(os.listdir(Paths.SrcDir), key=str.lower)
    except OSError:
        Names = []
    Ids = [DefaultThemeId] + [N for N in Names if N != DefaultThemeId]
    return [Info for Info in (ThemeInfo(Id) for Id in Ids) if Info]


def ThemeWarnings(ThemeId):
    """Problems worth showing under the Theme drop-down."""
    Served, _Folder = ResolveRoot(ThemeId)
    Warnings = [] if Served == ThemeId else [f"Theme '{ThemeId}' is missing or has no HTML\\Index.html - showing Dark."]
    _Map, MapWarnings = LoadHeightMap(Served)
    ServedFolder = ThemeDir(Served)
    Meta = (_ReadJson(os.path.join(ServedFolder, "Theme.json"))[0] or {}) if ServedFolder else {}
    SwatchWarnings = _ReadSwatch(ServedFolder, Meta)[1] if ServedFolder else []
    Entries, VersionWarnings = ParseSupportedVersions(Meta.get("SupportedVersions"))
    if Entries is None and ServedFolder:
        VersionWarnings = ['Theme.json doesn\'t say which RAMMIT versions this theme supports (add "SupportedVersions").']
    return Warnings + MapWarnings + SwatchWarnings + VersionWarnings


def LoadHeightMap(ThemeId):
    """(HeightMap, Warnings) for a theme. Missing or invalid entries use the defaults."""
    _Id, Folder = ResolveRoot(ThemeId)
    Raw, Error = _ReadJson(os.path.join(Folder, "HeightMap.json"))
    Warnings = [Error] if Error else []
    Result = {Section: dict(Values) for Section, Values in DefaultHeightMap.items()}
    for Section, Values in (Raw or {}).items():
        if Section not in Result or not isinstance(Values, dict):
            Warnings.append(f"HeightMap.json: unknown section '{Section}' ignored.")
            continue
        Low, High = _HeightLimits[Section]
        for Key, Value in Values.items():
            if Key not in Result[Section]:
                Warnings.append(f"HeightMap.json: unknown key '{Section}.{Key}' ignored.")
            elif isinstance(Value, bool) or not isinstance(Value, (int, float)) or not Low <= Value <= High:
                Warnings.append(f"HeightMap.json: '{Section}.{Key}' must be a number from {Low} to {High}.")
            else:
                Result[Section][Key] = int(Value)
    return Result, Warnings


def _ToHex(Color):
    """#rrggbb for any colour the swatch accepts (hex, rgb(a), hsl(a), CSS colour names), else None.
    The window background and the start-up spinner need plain hex, and converting every swatch
    colour keeps them identical to the swatch the user sees."""
    try:
        return _ToHexUnchecked(Color)
    except (ValueError, OverflowError):  # e.g. hsl(1.2.3, ...): a theme's odd colour must never stop RAMMIT starting
        return None


def _ToHexUnchecked(Color):
    Color = (Color or "").strip()
    if re.fullmatch(r"#[0-9a-fA-F]{3,4}", Color):
        return "#" + "".join(Ch * 2 for Ch in Color[1:4])
    if re.fullmatch(r"#[0-9a-fA-F]{6}([0-9a-fA-F]{2})?", Color):
        return Color[:7]
    Match = re.fullmatch(r"rgba?\(\s*(\d{1,3})\s*[, ]\s*(\d{1,3})\s*[, ]\s*(\d{1,3})\s*([,/][^)]*)?\)", Color)
    if Match and all(int(Part) <= 255 for Part in Match.groups()[:3]):
        return "#" + "".join(f"{int(Part):02x}" for Part in Match.groups()[:3])
    Match = re.fullmatch(r"hsla?\(\s*([\d.]+)(?:deg)?\s*[, ]\s*([\d.]+)%\s*[, ]\s*([\d.]+)%\s*([,/][^)]*)?\)", Color)
    if Match:
        Hue, Saturation, Lightness = float(Match.group(1)) % 360 / 360, float(Match.group(2)) / 100, float(Match.group(3)) / 100
        if Saturation <= 1 and Lightness <= 1:
            return "#" + "".join(f"{round(Part * 255):02x}" for Part in colorsys.hls_to_rgb(Hue, Lightness, Saturation))
    if _NamedColorPattern.match(Color):
        return _NamedColorHex(Color)
    return None


def _NamedColorHex(Name):
    """CSS colour name -> #rrggbb via .NET's colour table (Windows system colours excluded)."""
    if Name.lower() == "rebeccapurple":  # CSS-only name .NET doesn't know
        return "#663399"
    try:
        import clr
        clr.AddReference("System.Drawing")
        from System.Drawing import Color as NetColor
        Known = NetColor.FromName(Name)
        if Known.IsKnownColor and not Known.IsSystemColor and Name.lower() != "transparent":
            return f"#{Known.R:02x}{Known.G:02x}{Known.B:02x}"
    except Exception:
        pass
    return None


def _SwatchHex(ThemeId, Index, Default):
    """A swatch slot (0 Background, 1 Card, 2 Accent, 3 Text) as #rrggbb, or Default."""
    Info = ThemeInfo(ResolveRoot(ThemeId)[0])
    return (_ToHex(Info["Swatch"][Index]) if Info else None) or Default


def BackgroundColor(ThemeId):
    """The theme's --Background, used as the window colour so it never flashes white on open."""
    return _SwatchHex(ThemeId, 0, "#0a0a0a")


def AccentColor(ThemeId):
    """The theme's --Accent, used for the start-up spinner (App/Splash.py)."""
    return _SwatchHex(ThemeId, 2, "#0078d4")


def OpenThemesFolder():
    os.startfile(Paths.SrcDir)  # fixed path, never user-supplied
