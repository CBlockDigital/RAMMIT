"""Single source of truth for the RAMMIT version (shown in the UI footer, the log and the exe's file version).

AppChannel says which line this code belongs to. This tree (Production/RAMMIT-Stable) is the Stable line, so
Stable is the default, also when running from source. `Build.ps1 -Channel Dev` marks a test build instead and adds
the git commit to the label. Build.ps1 writes App/BuildInfo.py for the length of a build and deletes it
afterwards; it is never committed.
"""

AppName = "RAMMIT"
AppVersion = "1.1.2"

try:
    from App.BuildInfo import AppChannel, AppCommit
except ImportError:
    AppChannel, AppCommit = "Stable", ""


def VersionLabel():
    """'v1.0.0 · Stable', or 'v1.0.0 · Dev (a1b2c3d)' for a dev build whose commit is known."""
    Label = f"v{AppVersion} · {AppChannel}"
    return f"{Label} ({AppCommit})" if AppCommit and AppChannel != "Stable" else Label
