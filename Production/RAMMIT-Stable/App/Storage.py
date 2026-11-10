"""Loading, validating and saving everything in Config/.

The rest of the app only ever sees the PascalCase "public" shapes defined here. The on-disk
key names (max_instances, place_id, displayName, ...) are kept exactly as older RAMMIT builds
wrote them, so existing Config folders keep working. If you add a setting:
    1. add it to SettingsSchema below (disk key, default, coercer)
    2. read/write it from JS with GetSettings() / UpdateSetting("YourKey", value)
"""
import json
import os
import tempfile
import time

from App import Crypto, Paths, Themes
from App.Log import Logger

LaunchOptions = ("Home", "Config", "Game URL", "Place ID", "Place ID + Job ID", "VIP Link")
ConfigMethods = tuple(O for O in LaunchOptions if O != "Config")
Launchers = ("Roblox", "Bloxstrap", "Fishstrap")
PlayerModes = ("any", "smallest", "biggest", "min_only", "max_only", "range")
PingModes = ("any", "lowest", "highest")
TourIds = ("basics", "multi", "where", "servers", "configs", "settings", "themes")
MaxTextLength = 500


class InvalidValue(ValueError):
    pass


# ---------------------------------------------------------------- file helpers

def WriteJsonAtomic(FilePath, Data):
    """Write to a temp file in the same folder, then swap it in. A crash never leaves half a file."""
    Paths.EnsureConfigDir()
    Folder = os.path.dirname(FilePath)
    Handle, TempPath = tempfile.mkstemp(prefix=".tmp-", suffix=".json", dir=Folder)
    try:
        with os.fdopen(Handle, "w", encoding="utf-8") as TempFile:
            json.dump(Data, TempFile, indent=4)
            TempFile.flush()
            os.fsync(TempFile.fileno())
        for Attempt in range(5):  # antivirus / indexers can briefly lock the target
            try:
                os.replace(TempPath, FilePath)
                return
            except PermissionError:
                if Attempt == 4:
                    raise
                time.sleep(0.1)
    finally:
        if os.path.exists(TempPath):
            os.remove(TempPath)


def ReadJson(FilePath, Fallback):
    if not os.path.exists(FilePath):
        return Fallback
    try:
        with open(FilePath, "r", encoding="utf-8-sig") as File:
            return json.load(File)
    except (OSError, ValueError) as Error:
        Logger.warning("Could not read %s (%s); using defaults", os.path.basename(FilePath), type(Error).__name__)
        return Fallback


def CleanText(Value, Limit=MaxTextLength):
    if Value is None:
        return ""
    if isinstance(Value, (int, float)) and not isinstance(Value, bool):
        Value = str(Value)
    if not isinstance(Value, str):
        raise InvalidValue("Expected text.")
    Value = "".join(Ch for Ch in Value if Ch >= " " or Ch == "\t").strip()
    return Value[:Limit]


# ---------------------------------------------------------------- launch params

# public key -> (disk key, allowed values or None for free text)
_ParamFields = {
    "Url": ("url", None),
    "PlaceId": ("place_id", None),
    "JobId": ("job_id", None),
    "PlayerMode": ("player_mode", PlayerModes),
    "PingMode": ("ping_mode", PingModes),
    "MinPlayers": ("min_players", None),
    "MaxPlayers": ("max_players", None),
}


def CleanParams(Params):
    """Public launch params from untrusted input. Unknown keys are dropped, every value is short text."""
    if not isinstance(Params, dict):
        return {}
    Clean = {}
    for Key, (_DiskKey, Allowed) in _ParamFields.items():
        if Key not in Params:
            continue
        try:
            Value = CleanText(Params[Key])
        except InvalidValue:
            continue
        if Allowed is not None and Value not in Allowed:
            continue
        if Key in ("MinPlayers", "MaxPlayers") and Value and not Value.isdigit():
            continue
        Clean[Key] = Value
    return Clean


def ParamsToDisk(Params):
    return {_ParamFields[K][0]: V for K, V in Params.items() if K in _ParamFields}


def ParamsFromDisk(DiskParams):
    if not isinstance(DiskParams, dict):
        return {}
    Public = {Key: DiskParams[DiskKey] for Key, (DiskKey, _A) in _ParamFields.items() if DiskKey in DiskParams}
    return CleanParams(Public)


# ---------------------------------------------------------------- settings

def _Enum(Choices):
    def Coerce(Value):
        if Value not in Choices:
            raise InvalidValue("Unknown choice.")
        return Value
    return Coerce


def _IntRange(Low, High):
    def Coerce(Value):
        if isinstance(Value, bool):
            raise InvalidValue("Expected a whole number.")
        try:
            Number = int(str(Value).strip())
        except (TypeError, ValueError):
            raise InvalidValue("Expected a whole number.") from None
        if not Low <= Number <= High:
            raise InvalidValue(f"Must be between {Low} and {High}.")
        return Number
    return Coerce


def _Bool(Value):
    if not isinstance(Value, bool):
        raise InvalidValue("Expected true or false.")
    return Value


def _TextList(Value):
    if not isinstance(Value, list):
        raise InvalidValue("Expected a list.")
    return [CleanText(V, 100) for V in Value if isinstance(V, str)][:500]


def _TourList(Value):
    return [V for V in _TextList(Value) if V in TourIds]


def _ThemeId(Value):
    if not Themes.IsValidId(Value):
        raise InvalidValue("Invalid theme name.")
    return Value


# public key -> (disk key, default, coercer)
SettingsSchema = {
    "SelectedAccounts": ("selected_accounts", [], _TextList),
    "Launcher": ("launcher", "Roblox", _Enum(Launchers)),
    "MaxInstances": ("max_instances", 1, _IntRange(1, 100)),
    "LaunchDelay": ("launch_delay", 3, _IntRange(0, 300)),
    "LaunchOption": ("launch_option", "Home", _Enum(LaunchOptions)),
    "LaunchParams": ("launch_params", {}, CleanParams),
    "SelectedConfig": ("selected_config", "", lambda V: CleanText(V, 100)),
    "SettingsCollapsed": ("settings_collapsed", False, _Bool),
    "Theme": ("theme", "Dark", _ThemeId),
    "TutorialSeen": ("tutorial_seen", False, _Bool),
    "ToursDone": ("tutorials_done", [], _TourList),
    # "ThemeId@AppVersion" entries: themes the user said to use although they don't list that RAMMIT version.
    "ThemeVersionOk": ("ThemeVersionOk", [], _TextList),
}

# Older builds stored these theme ids.
_LegacyThemes = {"dark": "Dark", "roblox2016": "Light"}


def DefaultSettings():
    return {Key: (list(D) if isinstance(D, list) else dict(D) if isinstance(D, dict) else D)
            for Key, (_Disk, D, _C) in SettingsSchema.items()}


def CoerceSetting(Key, Value):
    """Validated value for a public setting key, or InvalidValue."""
    if Key not in SettingsSchema:
        raise InvalidValue("Unknown setting.")
    return SettingsSchema[Key][2](Value)


def LoadSettings():
    Settings = DefaultSettings()
    Disk = ReadJson(Paths.SettingsFile, {})
    if not isinstance(Disk, dict):
        return Settings
    Disk = dict(Disk)
    # --- migrations from older builds ---
    if not Disk.get("selected_accounts") and isinstance(Disk.get("selected_account"), str) and Disk["selected_account"]:
        Disk["selected_accounts"] = [Disk["selected_account"]]
    OldParams = Disk.get("launch_params")
    if isinstance(OldParams, dict) and "selected_config" in OldParams and not Disk.get("selected_config"):
        Disk["selected_config"] = OldParams.get("selected_config") or ""
    if isinstance(Disk.get("theme"), str):
        Disk["theme"] = _LegacyThemes.get(Disk["theme"], Disk["theme"])
    # --- load each known key, falling back to its default when invalid ---
    for Key, (DiskKey, _Default, Coerce) in SettingsSchema.items():
        if DiskKey not in Disk:
            continue
        Raw = Disk[DiskKey]
        if Key == "LaunchParams":
            Settings[Key] = ParamsFromDisk(Raw)
            continue
        try:
            Settings[Key] = Coerce(Raw)
        except InvalidValue:
            Logger.warning("Ignoring invalid saved setting %s", DiskKey)
    return Settings


def SaveSettings(Settings):
    # Keys not in the schema (multi_method, selected_account, channel from old builds) are dropped here.
    Disk = {}
    for Key, (DiskKey, Default, _C) in SettingsSchema.items():
        Value = Settings.get(Key, Default)
        Disk[DiskKey] = ParamsToDisk(Value) if Key == "LaunchParams" else Value
    WriteJsonAtomic(Paths.SettingsFile, Disk)


# ---------------------------------------------------------------- launch configs

def CleanConfig(Name, Method, Params):
    Name = CleanText(Name, 60)
    if not Name:
        raise InvalidValue("Name is required.")
    if Method not in ConfigMethods:
        raise InvalidValue("Unknown method.")
    return {"Name": Name, "Method": Method, "Params": CleanParams(Params)}


def LoadConfigs():
    Disk = ReadJson(Paths.ConfigsFile, [])
    Configs = []
    if not isinstance(Disk, list):
        return Configs
    for Entry in Disk:
        if not isinstance(Entry, dict):
            continue
        try:
            Config = CleanConfig(Entry.get("name"), Entry.get("method"), {})
        except InvalidValue:
            continue
        Config["Params"] = ParamsFromDisk(Entry.get("params"))
        if all(C["Name"] != Config["Name"] for C in Configs):
            Configs.append(Config)
    return Configs


def SaveConfigs(Configs):
    WriteJsonAtomic(Paths.ConfigsFile, [
        {"name": C["Name"], "method": C["Method"], "params": ParamsToDisk(C["Params"])} for C in Configs])


# ---------------------------------------------------------------- accounts
# In memory: {"Username", "DisplayName", "UserId" (Roblox's numeric id, or None until known), "Cookie" (plain text or
# None), "Stored" (on-disk cookie string)}. Cookie is None when the saved login cannot be decrypted (folder copied from
# another PC/user). UserId tells a renewed login apart from a different account (usernames can change).

def LoadAccounts():
    Disk = ReadJson(Paths.AccountsFile, [])
    Accounts = []
    NeedsMigration = False
    if not isinstance(Disk, list):
        return Accounts
    for Entry in Disk:
        if not isinstance(Entry, dict) or not isinstance(Entry.get("username"), str):
            continue
        Stored = Entry.get("cookie")
        if not isinstance(Stored, str) or not Stored:
            continue
        if Crypto.IsEncrypted(Stored):
            try:
                Cookie = Crypto.Decrypt(Stored)
            except Crypto.DecryptError:
                Logger.warning("Saved login for %s cannot be decrypted on this PC/user", CleanText(Entry["username"], 50))
                Cookie = None
        else:
            Cookie = Stored
            Stored = None
            NeedsMigration = True
        UserId = Entry.get("userId")
        Accounts.append({
            "Username": CleanText(Entry["username"], 50),
            "DisplayName": CleanText(Entry.get("displayName") or Entry["username"], 50),
            "UserId": UserId if isinstance(UserId, int) and not isinstance(UserId, bool) and UserId > 0 else None,
            "Cookie": Cookie,
            "Stored": Stored,
        })
    if NeedsMigration:
        SaveAccounts(Accounts)
        Logger.info("Encrypted %d plain-text saved login(s) with DPAPI", len(Accounts))
    return Accounts


def SaveAccounts(Accounts):
    Disk = []
    for Account in Accounts:
        if not Account.get("Stored"):
            Account["Stored"] = Crypto.Encrypt(Account["Cookie"])
        Entry = {"username": Account["Username"], "displayName": Account["DisplayName"], "cookie": Account["Stored"]}
        if Account.get("UserId"):
            Entry["userId"] = Account["UserId"]
        Disk.append(Entry)
    WriteJsonAtomic(Paths.AccountsFile, Disk)
