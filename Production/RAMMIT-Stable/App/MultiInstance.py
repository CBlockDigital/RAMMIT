"""Lets several Roblox clients run at once, and counts how many are running.

Roblox detects a second client through a named kernel object, "ROBLOX_singletonEvent". If
RAMMIT creates a *mutex* with that name first, Roblox cannot create its event and every client
believes it is the only one. RAMMIT also keeps an exclusive lock on RobloxCookies.dat so each
client keeps its own session.

Catch: if Roblox is already running when RAMMIT starts, the name already belongs to Roblox's
event and Windows refuses the mutex (error 6, ERROR_INVALID_HANDLE). HoldMutex() is retried
before every launch; once every Roblox window is closed it succeeds.

Counting and tracking (ClientTracker): a client is a RobloxPlayerBeta.exe that owns a visible
WINDOWSCLIENT window (the game). Other visible windows don't count: closing a game starts a
"--launch-to-tray" RobloxPlayerBeta that only has a tray icon, and its right-click menu is a
visible window too. Each launch's one-time ticket travels in the roblox-player: link on the
game process's command line, so matching it tells which account a client belongs to (and so
which one closed). Launches still starting (no game window for ~9 s) are counted too, or a
batch launch would overshoot MaxInstances. Tickets stay in memory and are never logged.
"""
import msvcrt
import os
import threading
import time

import psutil
import win32event
import win32gui
import win32process

from App.Log import Logger

PlayerExe = "RobloxPlayerBeta.exe"
LaunchLock = threading.Lock()

_Mutex = None
_CookieLock = None
_MutexWarned = False


def Enable():
    HoldMutex()
    LockCookieFile()


def HoldMutex():
    global _Mutex, _MutexWarned
    if _Mutex:
        return True
    try:
        _Mutex = win32event.CreateMutex(None, True, "ROBLOX_singletonEvent")
        return True
    except Exception as Error:  # pywintypes.error - see module docstring
        if not _MutexWarned:
            Logger.warning("Could not take the Roblox singleton name (Roblox already running?): %s", Error)
            _MutexWarned = True
        return False


def IsReady():
    return _Mutex is not None


def LockCookieFile():
    global _CookieLock
    if _CookieLock:
        return True
    LocalAppData = os.getenv("LOCALAPPDATA")
    if not LocalAppData:
        return False
    CookiePath = os.path.join(LocalAppData, "Roblox", "LocalStorage", "RobloxCookies.dat")
    if not os.path.exists(CookiePath):
        return True
    try:
        Handle = open(CookiePath, "r+b")
        try:
            msvcrt.locking(Handle.fileno(), msvcrt.LK_NBLCK, max(os.path.getsize(CookiePath), 1))
        except OSError:
            Handle.close()
            raise
        _CookieLock = Handle
        return True
    except OSError as Error:
        Logger.warning("Could not lock Roblox cookie file: %s", type(Error).__name__)
        return False


GameWindowClass = "WINDOWSCLIENT"
StartTimeout = 120  # seconds a launch may take to show up before it stops counting as "starting"


def _PlayerPids():
    """Pids of every RobloxPlayerBeta.exe. Names only: asking every process for more is very slow."""
    Pids = set()
    for Proc in psutil.process_iter(["name"]):
        if Proc.info["name"] == PlayerExe:
            Pids.add(Proc.pid)
    return Pids


def _GameWindowPids():
    """Pids that own a visible game window."""
    Pids = set()

    def OnWindow(Hwnd, _Extra):
        try:
            if win32gui.IsWindowVisible(Hwnd) and win32gui.GetClassName(Hwnd) == GameWindowClass:
                Pids.add(win32process.GetWindowThreadProcessId(Hwnd)[1])
        except Exception:
            pass
        return True

    try:
        win32gui.EnumWindows(OnWindow, None)
    except Exception as Error:
        Logger.warning("EnumWindows failed: %s", Error)
    return Pids


def _CommandLine(Pid):
    try:
        return " ".join(psutil.Process(Pid).cmdline())
    except (psutil.Error, OSError):
        return ""


class ClientTracker:
    """Which account each running Roblox client belongs to. Keep it in a _-prefixed Api attribute: it holds tickets."""

    def __init__(self):
        self._Lock = threading.Lock()
        self._Expected = []  # (launch ticket, Username, time launched) per launch; dropped once matched or after StartTimeout
        self._Owners = {}    # player pid -> Username, or None for a client that isn't one of RAMMIT's launches
        self._Last = {}      # Username -> "starting" / "running", from the last Scan()

    def Expect(self, Ticket, Username):
        with self._Lock:
            self._Expected.append((Ticket, Username, time.monotonic()))

    def Scan(self):
        """Number of running clients (game windows + launches still starting); also refreshes Accounts()."""
        PlayerPids, WindowPids = _PlayerPids(), _GameWindowPids()
        with self._Lock:
            Now = time.monotonic()
            for Pid in list(self._Owners):
                if Pid not in PlayerPids:
                    del self._Owners[Pid]
            for Pid in PlayerPids - set(self._Owners):
                Line = _CommandLine(Pid)
                Owner = None
                for Entry in self._Expected:
                    if "gameinfo:" + Entry[0] in Line:
                        Owner = Entry[1]
                        self._Expected.remove(Entry)
                        break
                if Owner or Pid in WindowPids or not Line:  # tray and helper processes get looked at again later
                    self._Owners[Pid] = Owner
            self._Expected = [Entry for Entry in self._Expected if Now - Entry[2] <= StartTimeout]
            Accounts = {Username: "starting" for _Ticket, Username, _At in self._Expected}
            for Pid, Username in self._Owners.items():
                if Username:
                    if Pid in WindowPids:
                        Accounts[Username] = "running"
                    else:
                        Accounts.setdefault(Username, "starting")
            Starting = len(self._Expected) + sum(1 for Pid, Username in self._Owners.items() if Username and Pid not in WindowPids)
            self._Last = Accounts
            return len(WindowPids & PlayerPids) + Starting

    def Accounts(self):
        """{Username: "starting" or "running"} for RAMMIT's own launches, as of the last Scan(). Closed ones are absent."""
        with self._Lock:
            return dict(self._Last)


def CountRunning(Tracker=None):
    """Number of running Roblox clients: processes with a visible game window, plus Tracker's launches still starting."""
    return (Tracker or ClientTracker()).Scan()
