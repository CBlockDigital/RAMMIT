========================================================
  RAMMIT  -  Roblox Multi-Account Launcher   (v1.2.0)
  Setup Guide (read this first)
========================================================

WHAT IT IS
----------
RAMMIT lets you save multiple Roblox accounts and launch several of
them at the same time on one PC. You do NOT need Python or any other
program installed - everything RAMMIT needs is inside this folder.

The bottom of the Settings panel shows your version, for example
"RAMMIT v1.2.0 · Stable". Please include it when you report a problem.


WHAT YOU NEED
-------------
  * Windows 10 or Windows 11
  * Roblox installed (get it from https://www.roblox.com/download)


HOW TO INSTALL (3 steps)
------------------------
  1. Right-click the ZIP you downloaded and choose "Extract All...".
     Pick a normal location such as your Desktop or Documents.

  2. Open the extracted "RAMMIT" folder. Keep ALL the files together -
     RAMMIT.exe needs the "Runtime" and "Src" folders next to it. Do not move
     RAMMIT.exe out on its own.

  3. Double-click  RAMMIT.exe  to start.

  (Optional) Right-click RAMMIT.exe > "Send to" > "Desktop (create
  shortcut)" so you can launch it easily later.


FIRST TIME YOU RUN IT
---------------------
Windows may show a blue box that says "Windows protected your PC".
This appears for any new app that is not code-signed. To continue:
    -> click "More info"
    -> click "Run anyway"

RAMMIT opens its own window and walks you through the basics. Press
the "?" button any time to see the tutorials again.


HOW TO USE
----------
  * Add an account:   "+ ADD" opens a Roblox login window. Sign in and
                      the account saves itself.
  * Launch accounts:  tick one or more accounts and press LAUNCH.
                      Set how many can run at once in Settings.
  * IMPORTANT: start RAMMIT BEFORE opening Roblox. If Roblox is already
    open when RAMMIT starts, only one client can run - close every
    Roblox window and launch again. (A warning sign appears next to
    RUNNING when this happens.)


THEMES
------
Pick a look in Settings > Theme: Dark, 2016 Roblox (Light), CBlock,
or the example "My Custom Theme". Every theme is a folder inside "Src".
Want your own? Read  HowToMakeATheme.txt  in this folder, or press
"?" in RAMMIT and choose "Making your own theme".


PRIVACY / SECURITY
------------------
  * Your logins are saved in Config\Accounts.json, ENCRYPTED with your
    Windows user account. A copy of that file is useless on another PC
    or Windows user.
  * Because of that, if you move RAMMIT to a different PC or Windows
    user, saved accounts show a warning sign - remove them and add
    them again.
  * Still: never share your Config folder, and never share the RAMMIT
    folder after you have added accounts.
  * This download ships with NO accounts saved. You start fresh.
  * RAMMIT only talks to roblox.com. Nothing is sent anywhere else.


TROUBLESHOOTING
---------------
  * "It won't open / nothing happens":
      Make sure RAMMIT.exe, "Runtime" and "Src" are in the SAME folder.
      Some antivirus tools block new apps - allow RAMMIT if prompted.
  * "The window is blank or looks broken after changing theme":
      Rename or delete the theme folder you made inside "Src" - RAMMIT
      falls back to the Dark theme.
  * "My antivirus deleted RAMMIT.exe" (e.g. Behavior:Win32/DefenseEvasion):
      RAMMIT is not signed with a paid certificate, so some antivirus
      engines guess wrongly. Download the zip again; this version is built
      to avoid that guess. If it still happens, report it as a false
      positive (Windows Security > Protection history > the entry), or
      submit RAMMIT.exe at https://www.microsoft.com/wdsi/filesubmission
  * "Accounts won't launch":
      Make sure Roblox is installed and you can open it normally first.
      Hover the red X next to an account to read why it failed.
  * An account's row turned red, or "Cookie expired. Renew this account.":
      Its saved login expired (for example you changed your password).
      Click that account alone: + ADD becomes RENEW (and LAUNCH becomes
      RENEW AND LAUNCH). Press it and sign in to the same account again.
      RAMMIT checks the saved logins with Roblox (users.roblox.com only)
      when it starts and every 5 minutes; nothing goes anywhere else.
  * "Auth failed":
      Roblox didn't answer, or asked RAMMIT to slow down. Wait a minute and
      try again.
  * A log file is kept at Config\RAMMIT.log (it never contains logins).


Enjoy RAMMIT.
