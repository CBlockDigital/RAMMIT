"""Lets several Roblox clients run at once, and counts how many are running.

Roblox detects a second client through a named kernel object, "ROBLOX_singletonEvent". If
RAMMIT creates a *mutex* with that name first, Roblox cannot create its event and every client
believes it is the only one. RAMMIT also keeps an exclusive lock on RobloxCookies.dat so each
client keeps its own session.

Catch: if Roblox is already running when RAMMIT starts, the name already belongs to Roblox's
event and Windows refuses the mutex (error 6, ERROR_INVALID_HANDLE). HoldMutex() is retried
before every launch; once every Roblox window is closed it succeeds.

Counting uses both libraries together: pywin32 finds visible Roblox windows, psutil confirms
the owning process and tracks clients RAMMIT just spawned (they have no window for a few
seconds - without that a batch launch would overshoot MaxInstances).
"""
import msvcrt
import os
import threading

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


def _IsPlayer(Pid):
    try:
        Proc = psutil.Process(Pid)
        return Proc.is_running() and Proc.name() == PlayerExe
    except (psutil.Error, OSError):
        return False


def CountRunning(TrackedPids=None):
    """Number of running Roblox clients. Prunes dead pids from TrackedPids in place."""
    Pids = set()

    def OnWindow(Hwnd, _Extra):
        if win32gui.IsWindowVisible(Hwnd):
            try:
                _Thread, Pid = win32process.GetWindowThreadProcessId(Hwnd)
                if _IsPlayer(Pid):
                    Pids.add(Pid)
            except Exception:
                pass
        return True

    try:
        win32gui.EnumWindows(OnWindow, None)
    except Exception as Error:
        Logger.warning("EnumWindows failed: %s", Error)
    if TrackedPids is not None:
        for Pid in list(TrackedPids):
            if _IsPlayer(Pid):
                Pids.add(Pid)
            else:
                TrackedPids.discard(Pid)
    return len(Pids)
