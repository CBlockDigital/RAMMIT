"""Resizing a window the user may be holding (main window and config wizard).

Grabbing or dragging a title bar starts Windows' move loop, which keeps the size the window had when it began: a
resize sent meanwhile is undone, or only flickers. So while a window is held, Resize() only records the height, and
when the loop ends (ResizeEnd fires for moves too) it is applied once. That resize sets the size only (SWP_NOMOVE),
because pywebview's resize also writes a position read a moment ago, which drags the window back if it is still
moving. Same fix as the installer's (Production/Installer, InstallerApi._WatchDrags).
"""
import ctypes
import ctypes.wintypes
import threading

from App.Log import Logger

SwpNoMove, SwpNoZOrder, SwpNoActivate = 0x2, 0x4, 0x10


class HeldWindow:
    """Wraps a pywebview window. Keep it in a _-prefixed Api attribute: pywebview exposes public ones to the page."""

    def __init__(self, Window):
        self._Window = Window
        self._Dragging = False
        self._Width = 0   # logical px last asked for
        self._Height = 0
        Events = getattr(Window, "events", None)
        if hasattr(Events, "shown"):  # the UI tests' stand-in window has no shown event
            Events.shown += self._WatchDrags

    def _WatchDrags(self):
        try:
            Native = self._Window.native
            Native.ResizeBegin += lambda _Sender, _Args: setattr(self, "_Dragging", True)
            Native.ResizeEnd += self._OnLetGo
        except Exception as Error:
            Logger.warning("Can't watch window drags: %s", type(Error).__name__)

    def Resize(self, Width, Height):
        self._Width, self._Height = Width, Height
        if self._Dragging:
            return  # held: Windows would undo it; _OnLetGo applies it
        self._Window.resize(Width, Height)

    def _OnLetGo(self, _Sender, _Args):
        self._Dragging = False
        threading.Thread(target=self._ReapplyHeight, daemon=True).start()

    def _ReapplyHeight(self):
        if not self._Height:
            return
        try:
            Native = self._Window.native
            Scale = self._WindowScale(Native)
            if abs(Native.Height / Scale - self._Height) >= 2:
                self._SetHeight(Native, round(self._Height * Scale))
        except Exception:
            pass

    @staticmethod
    def _WindowScale(Native):
        """The window's real DPI scale. Not Form.DeviceDpi: pywebview's SetProcessDPIAware leaves that at 96."""
        return max(1.0, ctypes.windll.user32.GetDpiForWindow(ctypes.wintypes.HWND(Native.Handle.ToInt64())) / 96.0)

    @staticmethod
    def _SetHeight(Native, PhysicalHeight):
        Hwnd = ctypes.wintypes.HWND(Native.Handle.ToInt64())
        Rect = ctypes.wintypes.RECT()
        ctypes.windll.user32.GetWindowRect(Hwnd, ctypes.byref(Rect))
        ctypes.windll.user32.SetWindowPos(Hwnd, None, 0, 0, Rect.right - Rect.left, PhysicalHeight, SwpNoMove | SwpNoZOrder | SwpNoActivate)
