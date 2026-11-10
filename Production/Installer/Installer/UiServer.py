"""Serves the installer's own page from memory on 127.0.0.1 (RAMMIT's App/LocalServer.py, minus the disk).

The page, CSS, JS, icon font and icon are read once at start-up from the bundle inside RAMMIT-Setup.exe
(PyInstaller's unpack folder when frozen, Installer/Ui/ from source) into a dict. After that the server
never looks at the disk, so it works on a PC with no RAMMIT at all and can't be pointed at other files.

Hardening, same as RAMMIT's server (see its SECURITY.md):
  * 127.0.0.1 on a random free port, GET/HEAD only
  * any Host header other than its own address is refused (blocks DNS-rebinding pages)
  * exact-path lookups in the dict: no directory listings, no ../, only allowlisted file types
  * every response (page, scripts, images, errors) carries a strict Content-Security-Policy, nosniff and no-store
  * idle connections are dropped after 15 seconds
"""
import http.server
import os
import posixpath
import threading
import urllib.parse

AllowedTypes = {
    ".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8", ".js": "text/javascript; charset=utf-8",
    ".png": "image/png", ".ico": "image/x-icon", ".svg": "image/svg+xml", ".woff2": "font/woff2",
}

# Scripts only from this server: no inline, eval or remote code (pywebview's bridge is injected by WebView2).
ContentSecurityPolicy = ("default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
                         "img-src 'self' data:; font-src 'self'; connect-src 'self'; base-uri 'none'; "
                         "form-action 'none'; frame-ancestors 'none'")


def LoadEmbeddedUi(BundleDir):
    """{'/HTML/Installer.html': bytes, ...} for every allowlisted file under <BundleDir>/Ui, plus the icon."""
    Files = {}
    UiDir = os.path.join(BundleDir, "Ui")
    for Root, _Dirs, Names in os.walk(UiDir):
        for Name in Names:
            if os.path.splitext(Name)[1].lower() in AllowedTypes:
                Full = os.path.join(Root, Name)
                with open(Full, "rb") as File:
                    Files["/" + os.path.relpath(Full, UiDir).replace("\\", "/")] = File.read()
    Icon = os.path.join(BundleDir, "RAMMIT-Downloader.png")
    if os.path.isfile(Icon):
        with open(Icon, "rb") as File:
            Files["/RAMMIT-Downloader.png"] = File.read()
    if "/HTML/Installer.html" not in Files:
        raise RuntimeError("The installer page is missing from this build")
    return Files


class _Handler(http.server.BaseHTTPRequestHandler):
    server_version = "RAMMIT-Setup"
    sys_version = ""
    timeout = 15  # seconds a connection may sit idle: a local program can't hold threads open by never sending a request

    def log_message(self, format, *args):  # noqa: A002 - stdlib signature
        pass

    def do_HEAD(self):
        self._Serve(SendBody=False)

    def do_GET(self):
        self._Serve(SendBody=True)

    def _Serve(self, SendBody):
        if self.headers.get("Host") not in self.server.AllowedHosts:
            return self._Send(403, b"Forbidden", "text/plain", SendBody)
        Key = self._Resolve(urllib.parse.unquote(urllib.parse.urlsplit(self.path).path))
        if Key is None:
            return self._Send(404, b"Not found", "text/plain", SendBody)
        self._Send(200, self.server.Files[Key], AllowedTypes[posixpath.splitext(Key)[1].lower()], SendBody)

    def _Resolve(self, UrlPath):
        if "\\" in UrlPath or "\x00" in UrlPath or ":" in UrlPath:
            return None
        Clean = "/" + posixpath.normpath(UrlPath).lstrip("/")
        if posixpath.splitext(Clean)[1].lower() not in AllowedTypes:
            return None
        return Clean if Clean in self.server.Files else None

    def _Send(self, Status, Body, ContentType, SendBody):
        self.send_response(Status)
        self.send_header("Content-Type", ContentType)
        self.send_header("Content-Length", str(len(Body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        # On every response, not only pages: an .svg opened on its own is a document too, and would otherwise
        # run any script inside it with the bridge attached.
        self.send_header("Content-Security-Policy", ContentSecurityPolicy)
        self.end_headers()
        if SendBody:
            self.wfile.write(Body)


class UiServer:
    def __init__(self, Files, HandlerClass=_Handler):
        self._Httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), HandlerClass)
        self._Httpd.daemon_threads = True
        self._Httpd.Files = dict(Files)
        self.Port = self._Httpd.server_address[1]
        self._Httpd.AllowedHosts = {f"127.0.0.1:{self.Port}"}
        self.Origin = f"http://127.0.0.1:{self.Port}"

    def Start(self):
        threading.Thread(target=self._Httpd.serve_forever, name="UiServer", daemon=True).start()
        return self

    def Stop(self):
        self._Httpd.shutdown()
        self._Httpd.server_close()

    def Url(self, Page):
        return f"{self.Origin}/HTML/{Page}"
