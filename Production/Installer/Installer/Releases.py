"""GitHub Releases: list the versions, download a release zip, verify its SHA-256. No token, ever.

Each release (tag v<version>) carries three assets:
    RAMMIT-Setup.exe             this installer
    RAMMIT-<version>.zip         the built app (RAMMIT\\ folder) plus Source\\
    RAMMIT-<version>.zip.sha256  "<64 hex>  RAMMIT-<version>.zip" (sha256sum format, written by Build.ps1)

Branches: a normal release is Stable ("S" in the version picker), a GitHub pre-release is Dev ("D"). The same
names as RAMMIT's own footer channel (App/Version.py).

One API request lists every version (the old installer needed one request per commit and hit the
60-per-hour limit, which is why it carried a token). The zip is only trusted after its SHA-256 matches.

What is fetched, and nothing else:
    the list        https://api.github.com/repos/<ReleaseRepo>/releases
    zip + .sha256   https://github.com/<ReleaseRepo>/releases/download/...  (_CheckAssetUrl: this repo's own
                    release files only, whatever link the list names), which GitHub redirects to its file
                    hosts (AllowedDownloadHosts, checked on every redirect by _CheckUrl)
The checksum comes from the same release as the zip: it catches a damaged or swapped download, not a release
published by someone who took over the repo. Only signing the files can cover that (SECURITY.md).

Test mode can point ReleasesUrl() at a fake server (see Locations.py).
"""
import hashlib
import http.client
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

import Locations
from Log import Logger

# The repo whose GitHub Releases hold RAMMIT. It must be public: the installer never carries a token.
ReleaseRepo = "CBlockDigital/RAMMIT"
ApiUrl = "https://api.github.com/repos/{Repo}/releases?per_page=100"
# Release downloads redirect from github.com to these hosts; nothing else is fetched.
AllowedDownloadHosts = {"github.com", "objects.githubusercontent.com", "release-assets.githubusercontent.com"}

MaxListBytes = 5 * 1024 * 1024
MaxShaBytes = 4096
MaxZipBytes = 500 * 1024 * 1024
UserAgent = "RAMMIT-Setup"
VersionPattern = re.compile(r"^v?(\d{1,4})\.(\d{1,4})\.(\d{1,4})(?:-([0-9A-Za-z][0-9A-Za-z.-]{0,30}))?$")


class ReleaseError(Exception):
    """Message is shown to the user; Details go to the error screen's "Copy details"."""

    def __init__(self, Message, Details=""):
        super().__init__(Message)
        self.Details = Details


# ------------------------------------------------------------ versions

def ParseVersion(Text):
    """'v1.2.3' / '1.2.3-beta.1' -> sortable key, or None. A pre-release sorts below its release."""
    Match = VersionPattern.match(Text or "")
    if not Match:
        return None
    Major, Minor, Patch, Pre = Match.groups()
    PreKey = (1,) if not Pre else (0,) + tuple((0, int(P), "") if P.isdigit() else (1, 0, P) for P in Pre.split("."))
    return (int(Major), int(Minor), int(Patch), PreKey)


def BranchOf(Version, Prerelease=False):
    """'Dev' for a pre-release (GitHub flag or a '-' suffix like 1.2.0-beta.1), else 'Stable'."""
    return "Dev" if Prerelease or "-" in (Version or "") else "Stable"


def CleanVersion(Text):
    return (Text or "").strip().lstrip("v")


def ReleasesUrl():
    return Locations.Current.ReleasesUrlOverride or ApiUrl.format(Repo=ReleaseRepo)


def ParseReleases(Data):
    """GitHub's release list -> [{Version, Tag, Prerelease, Branch, Published, ZipUrl, ZipName, ZipSize, ShaUrl}], newest first.
    Drafts, odd tags and releases without both assets are skipped."""
    if not isinstance(Data, list):
        raise ReleaseError("GitHub sent an unexpected answer.", "release list is not a JSON array")
    Found = {}
    for Item in Data:
        if not isinstance(Item, dict) or Item.get("draft"):
            continue
        Version = CleanVersion(str(Item.get("tag_name", "")))
        if ParseVersion(Version) is None:
            continue
        RawAssets = Item.get("assets")
        Assets = {A.get("name"): A for A in (RawAssets if isinstance(RawAssets, list) else [])
                  if isinstance(A, dict) and isinstance(A.get("name"), str)}
        ZipName = f"RAMMIT-{Version}.zip"
        Zip, Sha = Assets.get(ZipName), Assets.get(ZipName + ".sha256")
        if not Zip or not Sha:
            Logger.info("Release %s skipped: zip or .sha256 asset missing", Version)
            continue
        Prerelease = bool(Item.get("prerelease")) or "-" in Version
        Found[Version] = {
            "Version": Version,
            "Tag": str(Item.get("tag_name")),
            "Prerelease": Prerelease,
            "Branch": BranchOf(Version, Prerelease),
            "Published": str(Item.get("published_at") or "")[:10],
            "ZipName": ZipName,
            "ZipUrl": str(Zip.get("browser_download_url", "")),
            "ZipSize": _Size(Zip.get("size")),
            "ShaUrl": str(Sha.get("browser_download_url", "")),
        }
    return sorted(Found.values(), key=lambda R: ParseVersion(R["Version"]), reverse=True)


def _Size(Value):
    """An asset's size from the list, or 0 when it isn't a sensible whole number (only used for the progress bar)."""
    return Value if isinstance(Value, int) and not isinstance(Value, bool) and 0 <= Value <= MaxZipBytes else 0


def LatestStable(ReleaseList):
    return next((R for R in ReleaseList if not R["Prerelease"]), None)


def FindRelease(ReleaseList, Version):
    Version = CleanVersion(Version)
    return next((R for R in ReleaseList if R["Version"] == Version), None)


# ------------------------------------------------------------ network

def _CheckUrl(Url):
    """Only https GitHub hosts, or the test override's own server."""
    Parts = urllib.parse.urlsplit(Url)
    Override = Locations.Current.ReleasesUrlOverride
    if Override:
        Base = urllib.parse.urlsplit(Override)
        if (Parts.scheme, Parts.netloc) == (Base.scheme, Base.netloc):
            return
    try:
        Port = Parts.port
    except ValueError:
        Port = -1
    if (Parts.scheme != "https" or (Parts.hostname or "") not in AllowedDownloadHosts | {"api.github.com"}
            or Port not in (None, 443) or Parts.username is not None or Parts.password is not None):
        raise ReleaseError("A download link pointed somewhere unexpected, so it was not used.", f"refused URL host {Parts.hostname!r}")


def _CheckAssetUrl(Url):
    """A release file's link (zip or .sha256) as the release list names it: only a download from this repo's own
    releases on github.com (or the test override's server). The list is the only thing that says where the files
    are, so without this any file on GitHub, in anyone's repo, could be named as "the RAMMIT zip" together with a
    checksum that matches it."""
    _CheckUrl(Url)
    Parts = urllib.parse.urlsplit(Url)
    Override = Locations.Current.ReleasesUrlOverride
    if Override:
        Base = urllib.parse.urlsplit(Override)
        if (Parts.scheme, Parts.netloc) == (Base.scheme, Base.netloc):
            return
    Wanted = f"/{ReleaseRepo}/releases/download/".lower()
    Path = urllib.parse.unquote(Parts.path)
    if ((Parts.hostname or "") != "github.com" or Parts.port is not None or Parts.username is not None
            or not Path.lower().startswith(Wanted) or ".." in Path or "\\" in Path):
        raise ReleaseError("A download link pointed somewhere unexpected, so it was not used.",
                           f"release file is not from {ReleaseRepo}'s releases: {Url[:200]!r}")


class _CheckedRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, Req, Fp, Code, Msg, Headers, NewUrl):
        _CheckUrl(NewUrl)
        return super().redirect_request(Req, Fp, Code, Msg, Headers, NewUrl)


_Opener = urllib.request.build_opener(_CheckedRedirects)


def _Open(Url, Accept, Timeout=30):
    _CheckUrl(Url)
    Request = urllib.request.Request(Url, headers={"User-Agent": UserAgent, "Accept": Accept})
    try:
        return _Opener.open(Request, timeout=Timeout)
    except urllib.error.HTTPError as Error:
        if Error.code == 403 and "rate limit" in str(Error.read(2000)).lower():
            raise ReleaseError("GitHub is limiting requests from this network. Try again in an hour.", f"HTTP 403 rate limit for {Url}")
        if Error.code == 404:
            raise ReleaseError("The RAMMIT releases could not be found on GitHub.", f"HTTP 404 for {Url}")
        raise ReleaseError(f"GitHub answered with an error (HTTP {Error.code}).", f"HTTP {Error.code} for {Url}")
    except ReleaseError:
        raise
    except (urllib.error.URLError, OSError, ValueError, http.client.HTTPException) as Error:
        raise ReleaseError("Couldn't reach GitHub. Check your internet connection and try again.",
                           f"{type(Error).__name__}: {Error} ({Url})")


def _ReadCapped(Response, Limit):
    Data = Response.read(Limit + 1)
    if len(Data) > Limit:
        raise ReleaseError("GitHub sent more data than expected.", f"response over {Limit} bytes")
    return Data


def FetchReleases():
    with _Open(ReleasesUrl(), "application/vnd.github+json") as Response:
        Raw = _ReadCapped(Response, MaxListBytes)
    try:
        Data = json.loads(Raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as Error:
        raise ReleaseError("GitHub sent an unexpected answer.", f"release list is not JSON: {type(Error).__name__}")
    return ParseReleases(Data)


def FetchExpectedSha(Release):
    _CheckAssetUrl(Release["ShaUrl"])
    with _Open(Release["ShaUrl"], "application/octet-stream") as Response:
        Text = _ReadCapped(Response, MaxShaBytes).decode("ascii", "replace")
    return ParseShaFile(Text, Release["ZipName"])


def ParseShaFile(Text, ZipName):
    """'<64 hex>  RAMMIT-1.0.0.zip' -> hex. The file name, when present, must be this zip's."""
    Match = re.match(r"^\s*([0-9a-fA-F]{64})(?:\s+\*?(\S+))?\s*$", Text or "")
    if not Match:
        raise ReleaseError("The release's checksum file is damaged, so the download can't be checked.", "bad .sha256 format")
    if Match.group(2) and Match.group(2) != ZipName:
        raise ReleaseError("The release's checksum file is for a different download.", f".sha256 names {Match.group(2)!r}")
    return Match.group(1).lower()


def FileSha256(FilePath):
    Hash = hashlib.sha256()
    with open(FilePath, "rb") as File:
        for Block in iter(lambda: File.read(1024 * 1024), b""):
            Hash.update(Block)
    return Hash.hexdigest()


def VerifySha(FilePath, Expected):
    Actual = FileSha256(FilePath)
    if Actual != Expected.lower():
        raise ReleaseError("The download doesn't match its checksum, so it was not installed. Try again.",
                           f"SHA-256 mismatch: expected {Expected.lower()}, got {Actual}")
    return Actual


def DownloadRelease(Release, DestDir, OnProgress=None):
    """Downloads the zip into DestDir and verifies it. Returns (ZipPath, Sha256). OnProgress(Done, Total)."""
    Expected = FetchExpectedSha(Release)
    ZipPath = os.path.join(DestDir, Release["ZipName"])
    try:
        return _Download(Release, ZipPath, Expected, OnProgress)
    except (OSError, http.client.HTTPException) as Error:
        raise ReleaseError("The download was cut off. Check your connection and try again.", f"{type(Error).__name__}: {Error}")


def _Download(Release, ZipPath, Expected, OnProgress):
    Done, LastReport = 0, 0.0
    _CheckAssetUrl(Release["ZipUrl"])
    with _Open(Release["ZipUrl"], "application/octet-stream", Timeout=60) as Response:
        Total = int(Response.headers.get("Content-Length") or Release.get("ZipSize") or 0)
        if Total > MaxZipBytes:
            raise ReleaseError("The download is far bigger than RAMMIT should be, so it was refused.", f"{Total} bytes")
        with open(ZipPath, "wb") as File:
            while True:
                Block = Response.read(256 * 1024)
                if not Block:
                    break
                Done += len(Block)
                if Done > MaxZipBytes:
                    raise ReleaseError("The download is far bigger than RAMMIT should be, so it was refused.", f"over {MaxZipBytes} bytes")
                File.write(Block)
                if OnProgress and time.monotonic() - LastReport > 0.1:
                    LastReport = time.monotonic()
                    OnProgress(Done, Total)
    if Total and Done != Total:
        raise ReleaseError("The download was cut off. Try again.", f"got {Done} of {Total} bytes")
    if OnProgress:
        OnProgress(Done, Total or Done)
    return ZipPath, VerifySha(ZipPath, Expected)
