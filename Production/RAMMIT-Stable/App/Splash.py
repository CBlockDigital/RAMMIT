"""Native "RAMMIT is starting" spinner shown over the main window until the UI has finished booting.

Ported from the splash overlay in Test1's modded pywebview 6.1 (Src/Mods/webview), but done in app
code on stock pywebview 6.2.1 - no vendored library. Same look and timing as Test1's settings:
a 30% arc, one turn per 0.5 s, 0.2 s extra then a 0.3 s fade. Unlike the mod, the arc is scaled by
the monitor DPI so it is the same size at 100% and 150%.

How it works: a borderless WinForms form owned by the main window is kept exactly over its client
area and repainted every 16 ms. It covers WebView2 start-up (which can take a second or two) and
the page boot. The page calls Api.BootFinished() when accounts/configs/settings are loaded, which
calls Dismiss(). If that never comes (a broken custom theme, say), it dismisses itself after
TimeoutSeconds so RAMMIT can never get stuck behind it.

Colours come from the active theme (--Accent on --Background), see Main.py.
"""
import time

import clr

clr.AddReference("System.Windows.Forms")
clr.AddReference("System.Drawing")

import System.Windows.Forms as WinForms  # noqa: E402
from System import Action  # noqa: E402
from System.Drawing import Color, Pen, Point  # noqa: E402
from System.Drawing.Drawing2D import LineCap, SmoothingMode  # noqa: E402

from App.Log import Logger  # noqa: E402

TickMs = 16


def _ToColor(Hex):
    Hex = Hex.lstrip("#")
    return Color.FromArgb(255, int(Hex[0:2], 16), int(Hex[2:4], 16), int(Hex[4:6], 16))


class SplashScreen:
    def __init__(self, Foreground="#0078d4", Background="#0a0a0a", ArcPercent=30, LoopSeconds=0.5,
                 ExtraSeconds=0.2, FadeSeconds=0.3, TimeoutSeconds=15, Radius=18, Thickness=3.5):
        self._Foreground = _ToColor(Foreground)
        self._Background = _ToColor(Background)
        self._ArcDegrees = max(5, min(100, ArcPercent)) / 100 * 360
        # Real clock time, not timer ticks: ticks get skipped while WebView2 is busy starting up.
        self._LoopSeconds = max(0.1, LoopSeconds)
        self._ExtraSeconds, self._FadeSeconds, self._TimeoutSeconds = ExtraSeconds, FadeSeconds, TimeoutSeconds
        self._Radius, self._Thickness = Radius, Thickness  # logical px, scaled by the monitor's DPI
        self._Scale = 1.0
        self._Form = None
        self._Overlay = None
        self._Timer = None
        self._ShownAt = None
        self._DismissAt = None
        self._Removed = False

    # ------------------------------------------------------------ wiring

    def Attach(self, Window):
        """Call before webview.start(). Hooks the window's native form as soon as pywebview builds it."""
        Window.events.before_show += self._OnBeforeShow

    def _OnBeforeShow(self, window):  # pywebview passes the window to a parameter named "window"
        try:
            self._Form = window.native
            self._Form.Shown += self._OnShown
        except Exception as Error:
            Logger.warning("Splash unavailable: %s", type(Error).__name__)

    def Dismiss(self):
        """Thread-safe: start the extra-time + fade, then remove."""
        Form = self._Form
        if Form is None or self._Removed:
            return
        try:
            Form.BeginInvoke(Action(self._StartDismiss))
        except Exception:
            pass

    # ------------------------------------------------------------ UI thread

    def _OnShown(self, _Sender, _Args):
        Overlay = WinForms.Form()
        Overlay.FormBorderStyle = getattr(WinForms.FormBorderStyle, "None")
        Overlay.ShowInTaskbar = False
        Overlay.StartPosition = WinForms.FormStartPosition.Manual
        Overlay.BackColor = self._Background
        Overlay.Text = "RAMMIT loading"
        Overlay.Paint += self._OnPaint
        # Flicker-free repaint: DoubleBuffered is a protected property, so set it through reflection.
        try:
            Flags = __import__("System").Reflection.BindingFlags
            Overlay.GetType().GetProperty("DoubleBuffered", Flags.Instance | Flags.NonPublic).SetValue(Overlay, True, None)
        except Exception:
            pass
        self._Overlay = Overlay
        try:
            self._Scale = max(1.0, self._Form.DeviceDpi / 96.0)  # same size at 100% and 150% scaling
        except Exception:
            self._Scale = 1.0
        self._ShownAt = time.monotonic()
        self._SyncBounds()
        self._Form.LocationChanged += self._SyncBounds
        self._Form.SizeChanged += self._SyncBounds
        Overlay.Show(self._Form)  # owned: stays above the main window, moves/minimises with it
        self._Timer = WinForms.Timer()
        self._Timer.Interval = TickMs
        self._Timer.Tick += self._OnTick
        self._Timer.Start()
        Logger.info("Splash shown")

    def _SyncBounds(self, _Sender=None, _Args=None):
        if self._Removed or self._Overlay is None:
            return
        Client = self._Form.ClientRectangle
        TopLeft = self._Form.PointToScreen(Point(Client.Left, Client.Top))
        self._Overlay.SetBounds(TopLeft.X, TopLeft.Y, Client.Width, Client.Height)

    def _StartDismiss(self):
        if self._DismissAt is None and not self._Removed:
            self._DismissAt = time.monotonic()

    def _OnTick(self, _Sender, _Args):
        Now = time.monotonic()
        if self._DismissAt is None and Now - self._ShownAt >= self._TimeoutSeconds:
            Logger.warning("Splash timed out waiting for the UI; removing it")
            self._DismissAt = Now
        if self._DismissAt is not None:
            Fading = Now - self._DismissAt - self._ExtraSeconds
            if Fading >= self._FadeSeconds:
                self._Remove()
                return
            if Fading >= 0:
                self._Overlay.Opacity = max(0.0, 1.0 - Fading / max(0.001, self._FadeSeconds))
        self._Overlay.Invalidate()

    def _OnPaint(self, _Sender, Args):
        Graphics = Args.Graphics
        Graphics.SmoothingMode = SmoothingMode.AntiAlias
        Graphics.Clear(self._Background)
        Width, Height = self._Overlay.ClientSize.Width, self._Overlay.ClientSize.Height
        if not Width or not Height:
            return
        Progress = ((time.monotonic() - self._ShownAt) % self._LoopSeconds) / self._LoopSeconds
        Radius = int(self._Radius * self._Scale)
        ArcPen = Pen(self._Foreground, self._Thickness * self._Scale)
        ArcPen.StartCap = LineCap.Round
        ArcPen.EndCap = LineCap.Round
        Graphics.DrawArc(ArcPen, Width // 2 - Radius, Height // 2 - Radius, Radius * 2, Radius * 2, Progress * 360, self._ArcDegrees)
        ArcPen.Dispose()

    def _Remove(self):
        if self._Removed:
            return
        self._Removed = True
        self._Timer.Stop()
        self._Timer.Dispose()
        try:
            self._Form.LocationChanged -= self._SyncBounds
            self._Form.SizeChanged -= self._SyncBounds
        except Exception:
            pass
        self._Overlay.Close()
        self._Overlay.Dispose()
        Logger.info("Splash removed after %d ms", (time.monotonic() - self._ShownAt) * 1000)
