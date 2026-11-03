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
visible window too. Which account a client belongs to comes from the process RAMMIT started and
its children (Roblox may hand a launch to a child that opens the window), or the launch's
one-time ticket on the command line; so RAMMIT also knows which account closed. Launches still
starting (no game window for ~9 s) count towards MaxInstances, or a batch launch would
overshoot it. Tickets stay in memory and are never logged.
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


def _ParentPid(Pid):
    try:
        return psutil.Process(Pid).ppid()
    except (psutil.Error, OSError):
        return None


def _Alive(Pid):
    return psutil.pid_exists(Pid)


GoneKeep = 60  # seconds a finished launch process is remembered, so a client it started can still take over its account


class ClientTracker:
    """Which account each running Roblox client belongs to. Keep it in a _-prefixed Api attribute: it holds tickets.

    The process RAMMIT starts belongs to the account (Started). A Roblox process whose parent belongs to an account that
    hasn't shown its game window yet takes that account over: Roblox can hand a launch to a "--launch-to-tray" child
    that opens the window, and Bloxstrap / Fishstrap start Roblox as a child. Failing that, the launch ticket on the
    command line. A child started after the window was shown (the tray process a closed game leaves) takes nothing."""

    def __init__(self):
        self._Lock = threading.Lock()
        self._Expected = []  # (launch ticket, Username, time launched) per launch whose process isn't known yet
        self._Owners = {}    # pid -> {"User": Username or None, "Since", "Shown": had a game window, "Gone": time or None}
        self._Last = {}      # Username -> "starting" / "running", from the last Scan()

    def Expect(self, Ticket, Username):
        with self._Lock:
            self._Expected.append((Ticket, Username, time.monotonic()))

    def Started(self, Ticket, Pid):
        """The process RAMMIT started for the launch Expect()ed with Ticket."""
        with self._Lock:
            for Entry in self._Expected:
                if Entry[0] == Ticket:
                    self._Expected.remove(Entry)
                    self._Owners[Pid] = {"User": Entry[1], "Since": Entry[2], "Shown": False, "Gone": None}
                    break

    def Scan(self, IncludeStarting=True):
        """Number of running clients: game windows, plus launches still starting unless IncludeStarting is False (the
        instance limit counts them, so a batch can't overshoot; the counter label doesn't). Also refreshes Accounts()."""
        PlayerPids, WindowPids = _PlayerPids(), _GameWindowPids()
        with self._Lock:
            Now = time.monotonic()
            for Pid, Info in list(self._Owners.items()):
                if Info["Gone"] is None and Pid not in PlayerPids and not _Alive(Pid):
                    Info["Gone"] = Now
                if Info["Gone"] is not None and Now - Info["Gone"] > GoneKeep:
                    del self._Owners[Pid]
                elif Pid in WindowPids:
                    Info["Shown"] = True
            for Pid in PlayerPids - set(self._Owners):
                Owner, Since = None, Now
                Parent = self._Owners.get(_ParentPid(Pid))
                if Parent and Parent["User"] and not Parent["Shown"]:
                    Owner, Since = Parent["User"], Parent["Since"]
                else:
                    Line = _CommandLine(Pid)
                    for Entry in self._Expected:
                        if "gameinfo:" + Entry[0] in Line:
                            Owner, Since = Entry[1], Entry[2]
                            self._Expected.remove(Entry)
                            break
                self._Owners[Pid] = {"User": Owner, "Since": Since, "Shown": Pid in WindowPids, "Gone": None}
            self._Expected = [Entry for Entry in self._Expected if Now - Entry[2] <= StartTimeout]
            Accounts = {Username: "starting" for _Ticket, Username, _At in self._Expected}
            for Pid, Info in self._Owners.items():
                if not Info["User"] or Info["Gone"] is not None:
                    continue
                if Pid in WindowPids:
                    Accounts[Info["User"]] = "running"
                elif not Info["Shown"] and Now - Info["Since"] <= StartTimeout:
                    Accounts.setdefault(Info["User"], "starting")
            self._Last = Accounts
            Starting = sum(1 for State in Accounts.values() if State == "starting")
            return len(WindowPids & PlayerPids) + (Starting if IncludeStarting else 0)

    def Accounts(self):
        """{Username: "starting" or "running"} for RAMMIT's own launches, as of the last Scan(). Closed ones are absent."""
        with self._Lock:
            return dict(self._Last)


def CountRunning(Tracker=None, IncludeStarting=True):
    """Number of running Roblox clients: processes with a visible game window, plus (unless IncludeStarting is False)
    Tracker's launches still starting."""
    return (Tracker or ClientTracker()).Scan(IncludeStarting)
