"""Small rotating log in Config/RAMMIT.log.

Rule for everyone editing RAMMIT: never pass a cookie, auth ticket or launch URL to the
logger. Log usernames, error types and status codes only.
"""
import logging
import logging.handlers

from App import Paths

Logger = logging.getLogger("RAMMIT")


def Setup():
    if Logger.handlers:
        return Logger
    Logger.setLevel(logging.INFO)
    try:
        Paths.EnsureConfigDir()
        Handler = logging.handlers.RotatingFileHandler(Paths.LogFile, maxBytes=256 * 1024, backupCount=1, encoding="utf-8")
        Handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        Logger.addHandler(Handler)
    except OSError:
        Logger.addHandler(logging.NullHandler())
    return Logger
