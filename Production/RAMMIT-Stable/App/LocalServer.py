"""Tiny static web server on 127.0.0.1 that serves the UI in Src/ to the pywebview windows.

Hardening (see SECURITY.md):
  * binds to 127.0.0.1 on a random free port, GET/HEAD only
  * rejects any Host header other than its own address (blocks DNS-rebinding pages)
  * no directory listings, only an allowlist of file types, no paths outside Src/
  * every response carries a strict Content-Security-Policy, nosniff and no-store

The web root is the active theme's folder (Src/<Theme>/, see App/Themes.py), looked up on
every request, so switching theme is just "save the setting, reload the page".
"""
import http.server
import os
import posixpath
import threading
import urllib.parse

from App import Paths, Themes

AllowedTypes = {
    ".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8", ".js": "text/javascript; charset=utf-8",
    ".png": "image/png", ".ico": "image/x-icon", ".svg": "image/svg+xml",
    ".woff2": "font/woff2", ".woff": "font/woff", ".ttf": "font/ttf",
}

# Scripts only from this server: no inline, eval or remote code. pywebview's bridge is injected
# by WebView2 itself and is not affected (verified in the real window, 2026-11-02).
ContentSecurityPolicy = ("default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
                         "img-src 'self' data:; font-src 'self'; connect-src 'self'; base-uri 'none'; "
                         "form-action 'none'; frame-ancestors 'none'")


class _Handler(http.server.BaseHTTPRequestHandler):
    server_version = "RAMMIT"
    sys_version = ""

    def log_message(self, format, *args):  # noqa: A002 - stdlib signature
        pass

    def do_HEAD(self):
        self._Serve(SendBody=False)

    def do_GET(self):
        self._Serve(SendBody=True)

    def _Serve(self, SendBody):
        if self.headers.get("Host") not in self.server.AllowedHosts:
            return self._Send(403, b"Forbidden", "text/plain", SendBody)
        UrlPath = urllib.parse.unquote(urllib.parse.urlsplit(self.path).path)
        _ThemeId, Root = Themes.ResolveRoot(self.server.GetActiveTheme())
        FilePath = self._Resolve(Root, UrlPath)
        if not FilePath:
            return self._Send(404, b"Not found", "text/plain", SendBody)
        try:
            with open(FilePath, "rb") as File:
                Body = File.read()
        except OSError:
            return self._Send(404, b"Not found", "text/plain", SendBody)
        self._Send(200, Body, AllowedTypes[os.path.splitext(FilePath)[1].lower()], SendBody)

    @staticmethod
    def _Resolve(Root, UrlPath):
        Clean = posixpath.normpath(UrlPath).lstrip("/")
        if not Clean or Clean.startswith("..") or "\\" in Clean or ":" in Clean or "\x00" in Clean:
            return None
        FilePath = os.path.join(Root, *Clean.split("/"))
        if os.path.splitext(FilePath)[1].lower() not in AllowedTypes:
            return None
        if not os.path.isfile(FilePath) or not Paths.IsInside(Root, FilePath):
            return None
        return FilePath

    def _Send(self, Status, Body, ContentType, SendBody):
        self.send_response(Status)
        self.send_header("Content-Type", ContentType)
        self.send_header("Content-Length", str(len(Body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        if ContentType.startswith("text/html"):
            self.send_header("Content-Security-Policy", ContentSecurityPolicy)
        self.end_headers()
        if SendBody:
            self.wfile.write(Body)


class LocalServer:
    def __init__(self, GetActiveTheme):
        self._Httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self._Httpd.daemon_threads = True
        self._Httpd.GetActiveTheme = GetActiveTheme
        self.Port = self._Httpd.server_address[1]
        self._Httpd.AllowedHosts = {f"127.0.0.1:{self.Port}"}
        self.Origin = f"http://127.0.0.1:{self.Port}"

    def Start(self):
        threading.Thread(target=self._Httpd.serve_forever, name="LocalServer", daemon=True).start()
        return self

    def Stop(self):
        self._Httpd.shutdown()
        self._Httpd.server_close()

    def Url(self, Page):
        return f"{self.Origin}/HTML/{Page}"
