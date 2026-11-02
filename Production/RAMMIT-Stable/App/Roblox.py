"""Everything that talks to Roblox: web APIs, the installed client and its registry channel.

Security rules for this file:
  * Every id that ends up in a URL or in the roblox-player: launch URI is validated first
    (PlaceId digits, JobId UUID, link codes [A-Za-z0-9_-]). The launch URI uses "+" as its
    field separator, so an unvalidated value could inject extra launch arguments.
  * Every request has a timeout. Cookies are only ever sent to *.roblox.com over HTTPS.
  * Never log a cookie, auth ticket or launch URI.
"""
import os
import random
import re
import time
import urllib.parse
import winreg
from pathlib import Path

import requests

from App.Log import Logger

Timeout = 10
MaxServerPages = 10          # 10 x 100 servers is plenty to pick from; huge games have 1000s of pages
PlayerExe = "RobloxPlayerBeta.exe"

PlaceIdPattern = re.compile(r"^\d{1,20}$")
JobIdPattern = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
LinkCodePattern = re.compile(r"^[A-Za-z0-9_-]{1,100}$")
ChannelPattern = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
GameUrlPattern = re.compile(r"(?:^|//|\.)roblox\.com/games/(\d{1,20})(?:[/?#]|$)", re.I)
VipUrlPattern = re.compile(r"roblox\.com/games/(\d{1,20})/[^?#]*\?[^#]*privateServerLinkCode=([A-Za-z0-9_-]{1,100})", re.I)
ShareUrlPattern = re.compile(r"roblox\.com/share[^?#]*[?&]code=([A-Za-z0-9_-]{1,100})", re.I)

_ChannelKeys = [
    (r"Software\ROBLOX Corporation\Environments\RobloxPlayer\Channel", "www.roblox.com"),
    (r"Software\Roblox\RobloxPlayer", "Channel"),
]
_LauncherFolders = {"Roblox": ("Roblox", "Versions"), "Bloxstrap": ("Bloxstrap", "Versions"), "Fishstrap": ("Fishstrap", "Versions")}


def _CookieHeader(Cookie):
    return {"Cookie": f".ROBLOSECURITY={Cookie}"}


# ---------------------------------------------------------------- validation

def IsPlaceId(Value):
    return isinstance(Value, str) and bool(PlaceIdPattern.match(Value))


def IsJobId(Value):
    return isinstance(Value, str) and bool(JobIdPattern.match(Value))


def PlaceIdFromGameUrl(Url):
    Match = GameUrlPattern.search(Url or "")
    return Match.group(1) if Match else None


# ---------------------------------------------------------------- auth

def GetAuthenticatedUser(Cookie):
    """(Username, DisplayName) for a login cookie, or None."""
    try:
        Response = requests.get("https://users.roblox.com/v1/users/authenticated", headers=_CookieHeader(Cookie), timeout=Timeout)
        if Response.status_code != 200:
            Logger.warning("users/authenticated returned %s", Response.status_code)
            return None
        Data = Response.json()
        if isinstance(Data, dict) and isinstance(Data.get("name"), str):
            return Data["name"], Data.get("displayName") or Data["name"]
    except (requests.RequestException, ValueError) as Error:
        Logger.warning("users/authenticated failed: %s", type(Error).__name__)
    return None


def GetAuthTicket(Cookie):
    """One-time ticket the Roblox client exchanges for a session. Handles the CSRF dance and 429s."""
    Url = "https://auth.roblox.com/v1/authentication-ticket/"
    Headers = {"User-Agent": "Roblox/WinInet", "Referer": "https://www.roblox.com/develop", "RBX-For-Gameauth": "true",
               "Content-Type": "application/json", **_CookieHeader(Cookie)}
    try:
        First = requests.post(Url, headers=Headers, timeout=Timeout)
        Csrf = First.headers.get("x-csrf-token")
        if First.status_code != 403 or not Csrf:
            Logger.warning("auth ticket CSRF step returned %s", First.status_code)
            return None
        Headers["X-CSRF-TOKEN"] = Csrf
        for Attempt in range(4):
            Second = requests.post(Url, headers=Headers, timeout=Timeout)
            if Second.status_code == 200:
                return Second.headers.get("rbx-authentication-ticket") or None
            if Second.status_code != 429:
                Logger.warning("auth ticket returned %s", Second.status_code)
                return None
            time.sleep(2 ** Attempt)
    except requests.RequestException as Error:
        Logger.warning("auth ticket failed: %s", type(Error).__name__)
    return None


# ---------------------------------------------------------------- servers

def FetchServers(PlaceId, Cookie=None, MaxPages=MaxServerPages):
    """Public servers for a place (up to MaxPages x 100). Empty list on any failure."""
    if not IsPlaceId(PlaceId):
        return []
    Servers, Cursor = [], None
    Headers = _CookieHeader(Cookie) if Cookie else {}
    for _Page in range(MaxPages):
        Query = {"sortOrder": "Asc", "limit": 100}
        if Cursor:
            Query["cursor"] = Cursor
        Url = f"https://games.roblox.com/v1/games/{PlaceId}/servers/Public?" + urllib.parse.urlencode(Query)
        try:
            Response = requests.get(Url, headers=Headers, timeout=Timeout)
            if Response.status_code == 429 and Servers:
                break  # rate limited mid-way: use what we have
            if Response.status_code != 200:
                break
            Data = Response.json()
        except (requests.RequestException, ValueError):
            break
        Page = Data.get("data") if isinstance(Data, dict) else None
        if isinstance(Page, list):
            Servers.extend(S for S in Page if isinstance(S, dict) and isinstance(S.get("id"), str))
        Cursor = Data.get("nextPageCursor") if isinstance(Data, dict) else None
        if not Cursor:
            break
    return Servers


def GetGameMaxPlayers(PlaceId):
    Servers = FetchServers(PlaceId, MaxPages=1)
    for Server in Servers:
        Max = Server.get("maxPlayers")
        if isinstance(Max, int) and Max > 0:
            return Max
    return 0


def PickServer(Servers, PlayerMode="any", PingMode="any", MinPlayers=0, MaxPlayers=999):
    """Choose a non-full server: filter by player count, then order by ping, then apply the player mode."""
    def Playing(S):
        return S.get("playing") if isinstance(S.get("playing"), int) else 0

    Open = [S for S in Servers if isinstance(S.get("maxPlayers"), int) and Playing(S) < S["maxPlayers"] and IsJobId(S.get("id", ""))]
    if PlayerMode == "range":
        Open = [S for S in Open if MinPlayers <= Playing(S) <= MaxPlayers]
    elif PlayerMode == "min_only":
        Open = [S for S in Open if Playing(S) >= MinPlayers]
    elif PlayerMode == "max_only":
        Open = [S for S in Open if Playing(S) <= MaxPlayers]
    if not Open:
        return None
    # Ping order first, so it breaks ties for smallest/biggest and picks the winner otherwise.
    if PingMode == "lowest":
        Open.sort(key=lambda S: S.get("ping", 9999))
    elif PingMode == "highest":
        Open.sort(key=lambda S: -S.get("ping", 0))
    if PlayerMode == "smallest":
        return min(Open, key=Playing)
    if PlayerMode == "biggest":
        return max(Open, key=Playing)
    if PingMode in ("lowest", "highest"):
        return Open[0]
    return random.choice(Open)


def ResolveVipLink(UrlOrCode, Cookie=None):
    """(PlaceId, LinkCode) from a privateServerLinkCode URL or a roblox.com/share link."""
    Text = UrlOrCode or ""
    Match = VipUrlPattern.search(Text)
    if Match:
        return Match.group(1), Match.group(2)
    Share = ShareUrlPattern.search(Text)
    if not Share or not Cookie:
        return None, None
    Code = Share.group(1)
    Url = "https://apis.roblox.com/sharelinks/v1/resolve-link"
    Headers = {"Content-Type": "application/json", **_CookieHeader(Cookie)}
    for Payload in ({"linkId": Code, "linkType": "Server"}, {"code": Code, "type": "Server"}):
        try:
            Response = requests.post(Url, headers=Headers, json=Payload, timeout=Timeout)
            if Response.status_code == 403 and Response.headers.get("x-csrf-token"):
                Headers["X-CSRF-TOKEN"] = Response.headers["x-csrf-token"]
                Response = requests.post(Url, headers=Headers, json=Payload, timeout=Timeout)
            if Response.status_code != 200:
                continue
            Raw = Response.text
            PlaceMatch = re.search(r'"placeId"\s*:\s*(\d{1,20})', Raw)
            CodeMatch = re.search(r'"(?:linkCode|privateServerLinkCode|accessCode|linkcode)"\s*:\s*"([A-Za-z0-9_-]{1,100})"', Raw)
            if PlaceMatch and CodeMatch:
                return PlaceMatch.group(1), CodeMatch.group(1)
        except requests.RequestException:
            continue
    return None, None


# ---------------------------------------------------------------- launching

def BuildLaunchUrl(Ticket, PlaceId=None, JobId=None, LinkCode=None):
    """roblox-player: URI. Raises ValueError if any piece could break out of its field."""
    if not isinstance(Ticket, str) or not Ticket or any(Ch in Ticket for Ch in "+ \t\r\n\"'"):
        raise ValueError("Unexpected auth ticket format.")
    if PlaceId is not None and not IsPlaceId(PlaceId):
        raise ValueError("Invalid Place ID.")
    if JobId is not None and not IsJobId(JobId):
        raise ValueError("Invalid Job ID.")
    if LinkCode is not None and not LinkCodePattern.match(LinkCode):
        raise ValueError("Invalid link code.")
    TrackerId = random.randint(55393295400, 55393295500)
    Url = f"roblox-player:1+launchmode:play+gameinfo:{Ticket}+launchtime:{int(time.time() * 1000)}"
    if PlaceId:
        Launcher = (f"https://assetgame.roblox.com/game/PlaceLauncher.ashx?request=RequestGameJob"
                    f"&browserTrackerId={TrackerId}&placeId={PlaceId}&isPlayTogetherGame=false")
        if JobId:
            Launcher += f"&gameId={JobId}"
        if LinkCode:
            Launcher += f"&linkCode={LinkCode}"
        Url += f"+placelauncherurl:{Launcher}"
    return Url + f"+browsertrackerid:{TrackerId}+robloxLocale:en_us+gameLocale:en_us"


def FindLauncherPath(Launcher):
    LocalAppData = os.getenv("LOCALAPPDATA")
    if not LocalAppData or Launcher not in _LauncherFolders:
        return None
    Root = Path(LocalAppData).joinpath(*_LauncherFolders[Launcher])
    if not Root.is_dir():
        return None
    # Any sub-folder holding the player exe, newest first (Test1 / claude FINAL logic). Fishstrap's
    # version folders are not always named "version-...", so no name filter.
    Folders = sorted((D for D in Root.iterdir() if D.is_dir()), key=lambda D: D.stat().st_mtime, reverse=True)
    for Folder in Folders:
        Exe = Folder / PlayerExe
        if Exe.is_file():
            return str(Exe)
    return None


# ---------------------------------------------------------------- channel (registry)

def GetChannel():
    for KeyPath, ValueName in _ChannelKeys:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, KeyPath, 0, winreg.KEY_READ) as Key:
                Value, _Type = winreg.QueryValueEx(Key, ValueName)
                if isinstance(Value, str) and Value:
                    return Value
        except OSError:
            continue
    return "production"


def SetChannel(Channel):
    if not isinstance(Channel, str) or not ChannelPattern.match(Channel):
        return False
    Success = False
    for KeyPath, ValueName in _ChannelKeys:
        try:
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, KeyPath) as Key:
                winreg.SetValueEx(Key, ValueName, 0, winreg.REG_SZ, Channel)
                Success = True
        except OSError:
            continue
    return Success
