"""Smoke test of the BUILT RAMMIT-Setup.exe, in test mode, against the local fake release server.

    python Tests/SmokeExe.py <dist\\RAMMIT-Setup.exe> <ScreenshotPng>

Starts the exe with RAMMIT_INSTALLER_TEST=1 (throw-away registry key + temp folders), waits (polling) until its
window has resized itself for the menu, screenshots the window, closes it with WM_CLOSE and cleans up.
"""
import ctypes
import os
import subprocess
import sys
import time

import Support

import win32con
import win32gui
from PIL import ImageGrab

ExePath, ShotPath = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
Env = Support.TestEnvironment("Exe")
Server = Support.FakeReleaseServer([{"Version": "1.1.0", "Zip": Support.MakeAppZip("1.1.0")},
                                    {"Version": "1.0.0", "Zip": Support.MakeAppZip("1.0.0")}])
Env.SetReleasesUrl(Server.ListUrl)
ctypes.windll.user32.SetProcessDPIAware()
Process = subprocess.Popen([ExePath], env=dict(os.environ))
Ok = False
try:
    def FindWindow():
        Found = []
        win32gui.EnumWindows(lambda H, _X: Found.append(H) if win32gui.IsWindowVisible(H) and win32gui.GetWindowText(H) == "RAMMIT Installer (test mode)" else None, None)
        return Found[0] if Found else None
    Hwnd = Support.WaitUntil(FindWindow, 90, 0.2)
    print("window found:", bool(Hwnd))
    StartHeight = None
    if Hwnd:
        Rect = win32gui.GetWindowRect(Hwnd)
        StartHeight = Rect[3] - Rect[1]
        # The release list was fetched, the menu shown, and the window resized so its client area is exactly the
        # 371 logical px the menu page measures (start size from HeightMap.json is 323 incl. the frame).
        Scale = ctypes.windll.user32.GetDpiForWindow(Hwnd) / 96
        Grown = Support.WaitUntil(lambda: any("/repos/" in P for P in Server.Requests)
                                  and abs(win32gui.GetClientRect(Hwnd)[3] / Scale - 371) <= 2, 60, 0.2)
        time.sleep(1.0)  # let the 0.25 s slide and the spinner fade finish before the picture (cosmetic only)
        Rect = win32gui.GetWindowRect(Hwnd)
        Client = win32gui.GetClientRect(Hwnd)
        print("start height:", StartHeight, "now:", Rect[3] - Rect[1], "width:", Rect[2] - Rect[0], "menu loaded:", bool(Grown))
        print(f"client area: {Client[2]}x{Client[3]} px at {Scale:.2f}x = {Client[2] / Scale:.0f}x{Client[3] / Scale:.0f} logical (the menu page asks for 371)")
        try:
            win32gui.SetForegroundWindow(Hwnd)
        except win32gui.error:
            pass  # Windows may refuse focus stealing; the grab still works when nothing covers the window
        ImageGrab.grab(bbox=Rect, all_screens=True).save(ShotPath)
        Ok = bool(Grown) and abs(Client[3] / Scale - 371) <= 2  # client area = exactly what the page measured
        win32gui.PostMessage(Hwnd, win32con.WM_CLOSE, 0, 0)
        print("closed:", Support.WaitUntil(lambda: Process.poll() is not None, 30) is not None and Process.poll() is not None,
              "exit code:", Process.poll())
    with open(Env.Locations.LogFile, encoding="utf-8") as File:
        print("log:\n" + File.read())
finally:
    import psutil
    try:  # one-file exes run as bootloader + child: end both, or the child keeps the window open
        for Child in psutil.Process(Process.pid).children(recursive=True):
            Child.kill()
    except psutil.Error:
        pass
    if Process.poll() is None:
        Process.kill()
    Server.Stop()
    Env.Cleanup()
print("SMOKE", "PASS" if Ok else "FAIL")
sys.exit(0 if Ok else 1)
