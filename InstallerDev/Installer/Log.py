"""Small rotating log in %LOCALAPPDATA%\\RAMMIT-Setup\\Setup.log (adapted from RAMMIT's App/Log.py).

Rule: never pass a cookie, token or the contents of a Config file to the logger. Log paths, versions,
error types and status codes only.
"""
import logging
import logging.handlers
import os

import Locations

Logger = logging.getLogger("RAMMIT-Setup")


def Setup():
    if Logger.handlers:
        return Logger
    Logger.setLevel(logging.INFO)
    try:
        os.makedirs(os.path.dirname(Locations.Current.LogFile), exist_ok=True)
        Handler = logging.handlers.RotatingFileHandler(Locations.Current.LogFile, maxBytes=256 * 1024, backupCount=1, encoding="utf-8")
        Handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        Logger.addHandler(Handler)
    except OSError:
        Logger.addHandler(logging.NullHandler())
    return Logger


def Close():
    """Closes the log file so a full uninstall can delete it (and RAMMIT-Setup\\ with it). Later messages are dropped."""
    for Handler in list(Logger.handlers):
        Logger.removeHandler(Handler)
        Handler.close()
    Logger.addHandler(logging.NullHandler())
