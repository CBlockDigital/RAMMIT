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
StartTimeout = 120  # seconds a launch whose process RAMMIT never saw start keeps counting as "starting"
StartingCap = 600   # a launch process that is still alive counts as "starting" until its game window shows, at most this long


def _PlayerPids():
    """Pids of every RobloxPlayerBeta.exe. Names only: asking every process for more is very slow."""
    Pids = set()
    try:
        for Proc in psutil.process_iter(["name"]):
            if Proc.info["name"] == PlayerExe:
                Pids.add(Proc.pid)
    except (psutil.Error, OSError) as Error:
        Logger.warning("Could not list processes: %s", type(Error).__name__)
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


def _CreateTime(Pid):
    """When the process with this pid started, or None. Tells a reused pid from the process RAMMIT tracked."""
    try:
        return psutil.Process(Pid).create_time()
    except (psutil.Error, OSError):
        return None


def _Alive(Pid):
    return psutil.pid_exists(Pid)


GoneKeep = 60  # seconds a finished launch process is remembered, so a client it started can still take over its account


class ClientTracker:
    """Which account each running Roblox client belongs to. Keep it in a _-prefixed Api attribute: it holds tickets.

    Every launch gets an id. The process RAMMIT starts belongs to the launch (Started). A Roblox process whose parent
    belongs to a launch that hasn't shown its game window yet takes that launch over: Roblox can hand a launch to a
    "--launch-to-tray" child that opens the window, and Bloxstrap / Fishstrap start Roblox as a child. Failing that, the
    launch ticket on the command line (kept until the launch's window shows, so a process that isn't a child, such as
    one Roblox's updater starts, is still found). A child started after the window was shown (the tray process a closed
    game leaves) takes nothing. A launch counts as "starting" once, however many of its processes are alive."""

    def __init__(self):
        self._Lock = threading.Lock()
        self._NextLaunch = 1
        # per launch until its game window shows (or it times out): {"Ticket", "User", "At", "Launch", "Pid": started pid}
        self._Expected = []
        # pid -> {"User": Username or None, "Since", "Launch": id or None, "Shown": had a game window,
        #         "Gone": time or None, "Created": the process's start time (a reused pid is a different process)}
        self._Owners = {}
        self._ShownLaunches = set()   # launches whose game window has shown: they never count as "starting" again
        self._CappedLaunches = set()  # launches that passed StartingCap without a game window (logged once)
        self._Last = {}               # Username -> "starting" / "running", from the last Scan()

    def Expect(self, Ticket, Username):
        with self._Lock:
            self._Expected.append({"Ticket": Ticket, "User": Username, "At": time.monotonic(), "Launch": self._NextLaunch,
                                   "Pid": None})
            self._NextLaunch += 1

    def Started(self, Ticket, Pid):
        """The process RAMMIT started for the launch Expect()ed with Ticket."""
        Created = _CreateTime(Pid)
        with self._Lock:
            for Entry in self._Expected:
                if Entry["Ticket"] == Ticket and Entry["Pid"] is None:
                    Entry["Pid"] = Pid
                    self._Owners[Pid] = {"User": Entry["User"], "Since": Entry["At"], "Launch": Entry["Launch"],
                                         "Shown": False, "Gone": None, "Created": Created}
                    break

    def Forget(self, Ticket):
        """The launch Expect()ed with Ticket never started (starting its process failed)."""
        with self._Lock:
            self._Expected = [Entry for Entry in self._Expected if Entry["Ticket"] != Ticket]

    def Rename(self, OldName, NewName):
        """An account was renamed on Roblox (renewed under its new name): its launches and clients stay its own."""
        with self._Lock:
            for Item in self._Expected + list(self._Owners.values()):
                if Item["User"] == OldName:
                    Item["User"] = NewName
            if OldName in self._Last:
                self._Last[NewName] = self._Last.pop(OldName)

    def Scan(self, IncludeStarting=True):
        """Number of running clients: game windows, plus launches still starting unless IncludeStarting is False (the
        instance limit counts them, so a batch can't overshoot; the counter label doesn't). Also refreshes Accounts()."""
        PlayerPids, WindowPids = _PlayerPids(), _GameWindowPids()
        with self._Lock:
            Now = time.monotonic()
            for Pid, Info in list(self._Owners.items()):
                # The pid now belongs to another process (any program, also after the tracked one was marked Gone):
                # the tracked one is gone. Dropping it lets the loop below look at the new process in this same Scan.
                Reused = Info["Created"] is not None and _CreateTime(Pid) not in (None, Info["Created"])
                if Reused or (Info["Gone"] is not None and Info["Created"] is None and Pid in PlayerPids):
                    del self._Owners[Pid]
                    continue
                if Info["Gone"] is None and Pid not in PlayerPids and not _Alive(Pid):
                    Info["Gone"] = Now
                if Info["Gone"] is not None and Now - Info["Gone"] > GoneKeep:
                    del self._Owners[Pid]
                elif Info["Gone"] is None and Pid in WindowPids:
                    Info["Shown"] = True
                    if Info["Launch"]:
                        self._ShownLaunches.add(Info["Launch"])
            for Pid in PlayerPids - set(self._Owners):
                Owner, Since, Launch = None, Now, None
                Parent = self._Owners.get(_ParentPid(Pid))
                if Parent and Parent["User"] and not Parent["Shown"] and Parent["Launch"] not in self._ShownLaunches:
                    Owner, Since, Launch = Parent["User"], Parent["Since"], Parent["Launch"]
                else:
                    Line = _CommandLine(Pid)
                    for Entry in self._Expected:
                        if "gameinfo:" + Entry["Ticket"] in Line:
                            Owner, Since, Launch = Entry["User"], Entry["At"], Entry["Launch"]
                            Entry["Pid"] = Entry["Pid"] or Pid
                            break
                Shown = Pid in WindowPids
                self._Owners[Pid] = {"User": Owner, "Since": Since, "Launch": Launch, "Shown": Shown, "Gone": None,
                                     "Created": _CreateTime(Pid)}
                if Shown and Launch:
                    self._ShownLaunches.add(Launch)
            # A launch is done once its window shows. One whose process was never seen gives up after StartTimeout.
            self._Expected = [Entry for Entry in self._Expected if Entry["Launch"] not in self._ShownLaunches
                              and Now - Entry["At"] <= (StartingCap if Entry["Pid"] else StartTimeout)]
            Accounts, Starting = {}, {}  # Starting: launch id -> Username
            for Pid, Info in self._Owners.items():
                if Info["User"] and Info["Gone"] is None and Pid in WindowPids:
                    Accounts[Info["User"]] = "running"
            for Info in self._Owners.values():
                Launch = Info["Launch"]
                if not Info["User"] or Info["Gone"] is not None or not Launch or Launch in self._ShownLaunches:
                    continue
                if Now - Info["Since"] <= StartingCap:
                    Starting[Launch] = Info["User"]
                elif Launch not in self._CappedLaunches:
                    self._CappedLaunches.add(Launch)
                    Logger.warning("A Roblox launch has shown no game window for %d s; it no longer counts as starting", StartingCap)
            for Entry in self._Expected:
                if Entry["Pid"] is None:  # its process isn't known yet
                    Starting.setdefault(Entry["Launch"], Entry["User"])
            for Username in Starting.values():  # also over "running": a relaunch isn't open until its own window is
                Accounts[Username] = "starting"
            Live = {Info["Launch"] for Info in self._Owners.values()} | {Entry["Launch"] for Entry in self._Expected}
            self._ShownLaunches &= Live
            self._CappedLaunches &= Live
            self._Last = Accounts
            return len(WindowPids & PlayerPids) + (len(Starting) if IncludeStarting else 0)

    def Accounts(self):
        """{Username: "starting" or "running"} for RAMMIT's own launches, as of the last Scan(). Closed ones are absent.
        "starting" while any launch of the account is still starting, also when it already has another game open."""
        with self._Lock:
            return dict(self._Last)


def CountRunning(Tracker=None, IncludeStarting=True):
    """Number of running Roblox clients: processes with a visible game window, plus (unless IncludeStarting is False)
    Tracker's launches still starting."""
    return (Tracker or ClientTracker()).Scan(IncludeStarting)
