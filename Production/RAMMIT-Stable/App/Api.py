"""The JavaScript bridge: every public method here is callable from the UI as
`window.pywebview.api.<MethodName>(...)` (see Src/<Theme>/JS/Bridge.js).

Rules for editing this class:
  * Treat every argument as untrusted - validate it (Storage / Roblox helpers do the work).
  * Never return a cookie, auth ticket or launch URI to JavaScript.
  * Keep ALL state in "_"-prefixed attributes. pywebview exposes every public attribute,
    including nested objects such as windows, to the page.
  * Return plain dicts with PascalCase keys; errors are {"Error": "message for the user"}.
"""
import json
import subprocess
import threading
import time

import webview

from App import MultiInstance, Roblox, Storage, Themes
from App.Log import Logger
from App.Version import AppChannel, AppName, AppVersion, VersionLabel
from App.WindowSize import HeldWindow

LockedLoginMessage = "This saved login can't be read on this PC or Windows user. Remove the account and add it again."
RobloxFirstMessage = "Roblox was already open when RAMMIT started, so only one client can run. Close every Roblox window, then launch again."
LoginTimeoutSeconds = 300
LoginCheckSeconds = 300  # how often saved logins are checked for expiry (the first check runs at start-up)
ExpiredMessage = "Cookie expired. Renew this account."


class Api:
    def __init__(self, Server=None):
        self._Server = Server
        self._Accounts = Storage.LoadAccounts()
        self._Settings = Storage.LoadSettings()
        self._Configs = Storage.LoadConfigs()
        self._DataLock = threading.RLock()
        self._Clients = MultiInstance.ClientTracker()  # which running client is which account (holds launch tickets)
        self._Expired = set()  # lowercase usernames whose saved login Roblox rejected (401): shown red, RENEW offered
        self._Batch = self._EmptyBatch()
        self._MainWindow = None
        self._WizardWindow = None
        self._MainSizer = None    # App/WindowSize.HeldWindow: resizes that wait while the title bar is held
        self._WizardSizer = None
        self._WizardEditName = ""
        self._LoginWindow = None
        self._LoginLock = threading.Lock()
        self._Splash = None  # App/Splash.py start-up spinner, set by Main.py
        self._ThemeVersionOkOnce = set()  # "ThemeId@AppVersion" allowed for this run only
        self._SaveSettings()  # rewrites Settings.json without keys older builds left behind

    # ------------------------------------------------------------ wiring (called by Main.py)

    def _AttachMainWindow(self, Window):
        self._MainWindow = Window
        self._MainSizer = HeldWindow(Window)

    def _ChosenThemeId(self):
        return self._Settings.get("Theme", Themes.DefaultThemeId)

    def _ActiveThemeId(self):
        """The theme to serve: the chosen one, or Dark while a chosen theme that doesn't list this RAMMIT
        version hasn't been OK'd (its code may not work with this version; Themes.js asks)."""
        Chosen = self._ChosenThemeId()
        return Themes.DefaultThemeId if self._ThemeNeedsOk(Chosen) else Chosen

    def _ThemeNeedsOk(self, ThemeId):
        if ThemeId == Themes.DefaultThemeId or Themes.VersionCheck(ThemeId)["Compatible"] is not False:
            return False
        Key = f"{ThemeId}@{AppVersion}"
        return Key not in self._ThemeVersionOkOnce and Key not in self._Settings.get("ThemeVersionOk", [])

    def _SaveSettings(self):
        try:
            Storage.SaveSettings(self._Settings)
        except OSError as Error:
            Logger.error("Could not save settings: %s", Error)

    def _Notify(self, Event, Payload=None):
        """Call window.RammitEvents.<Event>(Payload) in the main window. Payload is JSON-encoded, never spliced raw."""
        Window = self._MainWindow
        if not Window or Event not in ("AccountsChanged", "ShowMessage", "ConfigsChanged"):
            return
        try:
            Window.evaluate_js(f"window.RammitEvents && window.RammitEvents.{Event}({json.dumps(Payload)})")
        except Exception as Error:
            Logger.warning("Could not notify UI (%s): %s", Event, type(Error).__name__)

    # ------------------------------------------------------------ app

    def BootFinished(self):
        """Called by the page once everything is loaded: fades out the start-up spinner."""
        if self._Splash:
            self._Splash.Dismiss()

    def GetAppInfo(self):
        return {"Name": AppName, "Version": AppVersion, "Channel": AppChannel, "Label": VersionLabel()}

    def LogClientError(self, Message):
        Logger.warning("UI: %s", Storage.CleanText(Message, 300) if isinstance(Message, str) else "non-text error")

    # ------------------------------------------------------------ accounts

    def GetAccounts(self):
        with self._DataLock:
            return [{"Username": A["Username"], "DisplayName": A["DisplayName"], "Locked": A["Cookie"] is None,
                     "Expired": A["Username"].lower() in self._Expired}
                    for A in self._Accounts]

    def AddAccount(self):
        return self._OpenLogin("RAMMIT - Login to Roblox")

    def RenewAccount(self, Username):
        """Sign in again for an expired account (RENEW). Waits until the login window is done, so RENEW AND LAUNCH can
        launch right after: {"Renewed": True, "Username": its name now} when the same Roblox user signed in (the name
        changes when the account was renamed on Roblox), {"Renewed": False} when it was a different account (added as a
        new one) or the window was closed."""
        Account = self._AccountByName(Username)
        if not Account:
            return {"Error": "Account not found."}
        Done = threading.Event()
        Outcome = {}
        Opened = self._OpenLogin("RAMMIT - Renew Cookie", RenewFor=Account["Username"], Done=Done, Outcome=Outcome)
        if "Error" in Opened:
            return Opened
        Done.wait(LoginTimeoutSeconds + 10)
        if Outcome.get("Result") == "Renewed":
            return {"Ok": True, "Renewed": True, "Username": Outcome.get("Username", Account["Username"])}
        return {"Ok": True, "Renewed": False}

    def _OpenLogin(self, Title, RenewFor=None, Done=None, Outcome=None):
        with self._LoginLock:
            if self._LoginWindow is not None:
                return {"Error": "A login window is already open."}
            Window = webview.create_window(Title, url="https://www.roblox.com/login", width=480, height=640)
            self._LoginWindow = Window
        Window.events.closed += self._OnLoginClosed
        threading.Thread(target=self._PollLogin, args=(Window, RenewFor, Done, Outcome), name="LoginPoll", daemon=True).start()
        return {"Ok": True}

    def _OnLoginClosed(self):
        with self._LoginLock:
            self._LoginWindow = None

    def _PollLogin(self, Window, RenewFor=None, Done=None, Outcome=None):
        try:
            time.sleep(2)
            Deadline = time.time() + LoginTimeoutSeconds
            while time.time() < Deadline and self._LoginWindow is Window:
                try:
                    Cookie = self._FindLoginCookie(Window.get_cookies())
                except Exception:
                    return  # window was closed
                if Cookie:
                    # The WebView2 cookie store is shared by RAMMIT's windows for the whole session.
                    # Clearing it means the next "+ ADD" shows a fresh login instead of re-saving this account.
                    try:
                        Window.clear_cookies()
                    except Exception:
                        pass
                    Result = self._FinishLogin(Cookie, RenewFor, Outcome)
                    if Outcome is not None:
                        Outcome["Result"] = Result
                    break
                time.sleep(1.5)
            with self._LoginLock:
                if self._LoginWindow is Window:
                    self._LoginWindow = None
            self._DestroyQuietly(Window)
        finally:
            if Done:
                Done.set()

    @staticmethod
    def _FindLoginCookie(CookieJars):
        for Jar in CookieJars or []:
            for Name, Morsel in Jar.items():
                if Name == ".ROBLOSECURITY" and Morsel.value:
                    return Morsel.value
        return None

    def _FinishLogin(self, Cookie, RenewFor=None, Outcome=None):
        """Saves a new login. Renewing (RenewFor = an account's username): the same Roblox user replaces that account's
        login in place (same user id, or same username if its id isn't known yet); a different user is added as a new
        account instead. Returns "Renewed", "Added", or None on failure; Outcome["Username"] gets the saved name."""
        State, User = Roblox.CheckLogin(Cookie)
        if State != "Valid":
            self._Notify("ShowMessage", {"Text": "Login worked but Roblox did not confirm the account. Try again.", "Error": True})
            return None
        UserId, Username, DisplayName = User
        Username, DisplayName = Storage.CleanText(Username, 50), Storage.CleanText(DisplayName, 50)
        try:
            with self._DataLock:
                Target = next((A for A in self._Accounts if RenewFor and A["Username"].lower() == RenewFor.lower()), None)
                Same = Target is not None and (Target["UserId"] == UserId if Target["UserId"] else Target["Username"].lower() == Username.lower())
                if Same:
                    OldName = Target["Username"]
                    Target.update({"Username": Username, "DisplayName": DisplayName, "UserId": UserId, "Cookie": Cookie, "Stored": None})
                    self._Expired.discard(OldName.lower())
                    if OldName != Username:  # renamed on Roblox: keep it selected, and its open client, under its new name
                        self._Settings["SelectedAccounts"] = [Username if N == OldName else N for N in self._Settings["SelectedAccounts"]]
                        self._SaveSettings()
                        self._Clients.Rename(OldName, Username)
                else:
                    self._Accounts = [A for A in self._Accounts if A["Username"].lower() != Username.lower() and A["UserId"] != UserId]
                    self._Accounts.append({"Username": Username, "DisplayName": DisplayName, "UserId": UserId, "Cookie": Cookie, "Stored": None})
                self._Expired.discard(Username.lower())
                Storage.SaveAccounts(self._Accounts)
        except Exception as Error:
            Logger.error("Could not save account %s: %s", Username, type(Error).__name__)
            self._Notify("ShowMessage", {"Text": "Could not save the account securely.", "Error": True})
            return None
        if Outcome is not None:
            Outcome["Username"] = Username
        if Same:
            Logger.info("Renewed account %s", Username)
        else:
            Logger.info("Saved account %s", Username)
            if RenewFor:
                self._Notify("ShowMessage", {"Text": f"Signed in as @{Username}, not @{RenewFor}: added it as a new account.", "Error": True})
        self._Notify("AccountsChanged")
        return "Renewed" if Same else "Added"

    def _StartLoginChecks(self):
        """Called by Main.py once the window exists: checks every saved login now, then every LoginCheckSeconds."""
        threading.Thread(target=self._CheckLogins, name="LoginChecks", daemon=True).start()

    def _CheckLogins(self, Forever=True):
        while True:
            with self._DataLock:
                Accounts = [(A["Username"], A["Cookie"]) for A in self._Accounts if A["Cookie"]]
            Changed = Save = False
            for Username, Cookie in Accounts:
                State, User = Roblox.CheckLogin(Cookie)
                with self._DataLock:
                    Account = next((A for A in self._Accounts if A["Username"] == Username), None)
                    if not Account or Account["Cookie"] != Cookie:
                        continue  # removed or renewed meanwhile
                    Key = Username.lower()
                    if State == "Expired" and Key not in self._Expired:
                        self._Expired.add(Key)
                        Changed = True
                    elif State == "Valid":
                        if Key in self._Expired:
                            self._Expired.discard(Key)
                            Changed = True
                        if not Account["UserId"]:
                            Account["UserId"] = User[0]
                            Save = True
            if Save:
                try:
                    with self._DataLock:
                        Storage.SaveAccounts(self._Accounts)
                except Exception as Error:
                    Logger.error("Could not save account ids: %s", type(Error).__name__)
            if Changed:
                self._Notify("AccountsChanged")
            if not Forever:
                return
            time.sleep(LoginCheckSeconds)

    def RemoveAccounts(self, Usernames):
        if not isinstance(Usernames, list):
            return {"Error": "Nothing selected."}
        Doomed = {U.lower() for U in Usernames if isinstance(U, str)}
        with self._DataLock:
            Before = len(self._Accounts)
            self._Accounts = [A for A in self._Accounts if A["Username"].lower() not in Doomed]
            self._Expired -= Doomed
            Storage.SaveAccounts(self._Accounts)
            self._Settings["SelectedAccounts"] = [U for U in self._Settings["SelectedAccounts"] if U.lower() not in Doomed]
            self._SaveSettings()
            return {"Removed": Before - len(self._Accounts)}

    def _AccountByName(self, Username):
        if not isinstance(Username, str):
            return None
        with self._DataLock:
            return next((A for A in self._Accounts if A["Username"].lower() == Username.lower()), None)

    # ------------------------------------------------------------ launch configs

    def GetConfigs(self):
        with self._DataLock:
            return [{"Name": C["Name"], "Method": C["Method"], "Params": dict(C["Params"])} for C in self._Configs]

    def RemoveConfig(self, Name):
        with self._DataLock:
            self._Configs = [C for C in self._Configs if C["Name"] != Name]
            Storage.SaveConfigs(self._Configs)
            if self._Settings["SelectedConfig"] == Name:
                self._Settings["SelectedConfig"] = ""
                self._SaveSettings()
        return {"Ok": True}

    def OpenConfigWizard(self, EditName=""):
        if self._WizardWindow is not None:
            return {"Error": "The config window is already open."}
        EditName = EditName if isinstance(EditName, str) and any(C["Name"] == EditName for C in self._Configs) else ""
        self._WizardEditName = EditName
        Size = Themes.LoadHeightMap(self._ActiveThemeId())[0]["WizardWindow"]
        Method = next((C["Method"] for C in self._Configs if C["Name"] == EditName), "Home")
        Window = webview.create_window("Edit Launch Config" if EditName else "Add Launch Config",
                                       url=self._Server.Url("Wizard.html"), js_api=self,
                                       width=Size["Width"], height=Size.get(Method, Size["Home"]), resizable=False, on_top=True,
                                       background_color=Themes.BackgroundColor(self._ActiveThemeId()))
        Window.events.closed += self._OnWizardClosed
        GuardNavigation(Window, self._Server, "Wizard.html")
        self._WizardWindow = Window
        self._WizardSizer = HeldWindow(Window)
        return {"Ok": True}

    def _OnWizardClosed(self):
        self._WizardWindow = None
        self._WizardSizer = None

    def GetWizardData(self):
        with self._DataLock:
            Config = next((C for C in self._Configs if C["Name"] == self._WizardEditName), None)
        return {"EditData": Config}

    def WizardConfirm(self, Name, Method, Params):
        try:
            Config = Storage.CleanConfig(Name, Method, Params)
        except Storage.InvalidValue as Error:
            return {"Error": str(Error)}
        with self._DataLock:
            # Editing replaces the original entry; saving over another config's name replaces that one.
            Keep = [C for C in self._Configs if C["Name"] not in (Config["Name"], self._WizardEditName)]
            Position = next((I for I, C in enumerate(self._Configs) if C["Name"] in (self._WizardEditName, Config["Name"])), len(Keep))
            Keep.insert(min(Position, len(Keep)), Config)
            self._Configs = Keep
            Storage.SaveConfigs(self._Configs)
            if self._WizardEditName and self._Settings["SelectedConfig"] == self._WizardEditName:
                self._Settings["SelectedConfig"] = Config["Name"]
                self._SaveSettings()
        self._Notify("ConfigsChanged")
        self._CloseWizard()
        return {"Ok": True}

    def WizardCancel(self):
        self._CloseWizard()

    def _CloseWizard(self):
        # Clear the reference ourselves too: if the "closed" event is missed, the wizard could never reopen.
        Window, self._WizardWindow = self._WizardWindow, None
        self._DestroyQuietly(Window)

    # ------------------------------------------------------------ launching

    @staticmethod
    def _EmptyBatch():
        return {"Running": False, "Cancelled": False, "Total": 0, "Done": 0, "Current": "", "Message": "", "Results": {}}

    def _ResolveTarget(self, LaunchOption, LaunchParams, ConfigName):
        """{"Option", "Params"} with a Config option replaced by what it stores, or {"Error"}."""
        if LaunchOption == "Config":
            with self._DataLock:
                Config = next((C for C in self._Configs if C["Name"] == ConfigName), None)
            if not Config:
                return {"Error": "No config selected."}
            return {"Option": Config["Method"], "Params": dict(Config["Params"])}
        if LaunchOption not in Storage.LaunchOptions:
            return {"Error": "Unknown launch option."}
        return {"Option": LaunchOption, "Params": Storage.CleanParams(LaunchParams)}

    @staticmethod
    def _ParseTarget(Option, Params):
        """Validate what the user typed, before any network call. Returns {"PlaceId", "JobId", "VipUrl"} or {"Error"}."""
        if Option == "Home":
            return {}
        if Option == "Game URL":
            PlaceId = Roblox.PlaceIdFromGameUrl(Params.get("Url", ""))
            return {"PlaceId": PlaceId} if PlaceId else {"Error": "Invalid Game URL."}
        if Option in ("Place ID", "Place ID + Job ID"):
            PlaceId = Params.get("PlaceId", "").strip()
            if not Roblox.IsPlaceId(PlaceId):
                return {"Error": "Invalid Place ID."}
            if Option == "Place ID":
                return {"PlaceId": PlaceId}
            JobId = Params.get("JobId", "").strip()
            if not JobId:
                return {"Error": "Job ID is required."}
            if not Roblox.IsJobId(JobId):
                return {"Error": "Invalid Job ID (expected xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx)."}
            return {"PlaceId": PlaceId, "JobId": JobId}
        if Option == "VIP Link":
            Url = Params.get("Url", "").strip()
            return {"VipUrl": Url} if Url else {"Error": "VIP link is required."}
        return {"Error": "Unknown launch option."}

    def _LaunchOne(self, Username, Option, Params):
        Account = self._AccountByName(Username)
        if not Account:
            return {"Error": "Account not found."}
        if Account["Cookie"] is None:
            return {"Error": LockedLoginMessage}
        Target = self._ParseTarget(Option, Params)
        if "Error" in Target:
            return Target
        PlayerMode, PingMode = Params.get("PlayerMode", "any"), Params.get("PingMode", "any")
        try:
            MinPlayers = int(Params.get("MinPlayers") or 0)
            MaxPlayers = int(Params.get("MaxPlayers") or 999)
        except ValueError:
            return {"Error": "Player counts must be whole numbers."}

        with MultiInstance.LaunchLock:
            Running = MultiInstance.CountRunning(self._Clients)
            if Running >= self._Settings["MaxInstances"]:
                return {"Error": "Instance limit reached."}
            if not MultiInstance.HoldMutex() and Running > 0:
                return {"Error": RobloxFirstMessage}
            MultiInstance.LockCookieFile()
            Exe = Roblox.FindLauncherPath(self._Settings["Launcher"])
            if not Exe:
                return {"Error": "Launcher not found."}
            Cookie = Account["Cookie"]
            PlaceId, JobId, LinkCode = Target.get("PlaceId"), Target.get("JobId"), None
            if "VipUrl" in Target:
                PlaceId, LinkCode = Roblox.ResolveVipLink(Target["VipUrl"], Cookie)
                if not PlaceId or not LinkCode:
                    return {"Error": "Could not resolve VIP link."}
            if PlaceId and not JobId and not LinkCode and (PlayerMode != "any" or PingMode != "any"):
                Server = Roblox.PickServer(Roblox.FetchServers(PlaceId, Cookie), PlayerMode, PingMode, MinPlayers, MaxPlayers)
                if not Server:
                    return {"Error": "No servers found matching filters."}
                JobId = Server["id"]
            Ticket = Roblox.GetAuthTicket(Cookie)
            if Ticket is Roblox.LoginExpired:
                with self._DataLock:
                    # Not when a new login was saved meanwhile: RENEW updates this same entry, + ADD replaces it.
                    Marked = any(A is Account for A in self._Accounts) and Account["Cookie"] is Cookie
                    if Marked:
                        self._Expired.add(Account["Username"].lower())
                if Marked:
                    self._Notify("AccountsChanged")
                return {"Error": ExpiredMessage}
            if not Ticket:
                return {"Error": "Auth failed."}
            try:
                LaunchUrl = Roblox.BuildLaunchUrl(Ticket, PlaceId, JobId, LinkCode)
            except ValueError as Error:
                return {"Error": str(Error)}
            self._Clients.Expect(Ticket, Account["Username"])  # before the client exists, so no scan can miss it
            try:
                Proc = subprocess.Popen([Exe, LaunchUrl], creationflags=subprocess.CREATE_NO_WINDOW)
            except OSError as Error:
                self._Clients.Forget(Ticket)  # or it would count as "starting" until it times out
                Logger.warning("Could not start Roblox: %s", type(Error).__name__)
                return {"Error": "Could not start Roblox."}
            self._Clients.Started(Ticket, Proc.pid)
            Logger.info("Launched %s (%s)", Username, Option)
            return {"Ok": True}

    def LaunchAccounts(self, Usernames, LaunchOption, LaunchParams=None, ConfigName=""):
        """Launch accounts one after another on a worker thread; the UI polls GetLaunchProgress()."""
        with self._DataLock:
            if self._Batch["Running"]:
                return {"Error": "A launch is already running."}
            Ordered = []
            for Name in Usernames if isinstance(Usernames, list) else []:
                Account = self._AccountByName(Name)
                if Account and Account["Username"] not in Ordered:
                    Ordered.append(Account["Username"])
            if not Ordered:
                return {"Error": "No account selected."}
            Target = self._ResolveTarget(LaunchOption, LaunchParams, ConfigName)
            if "Error" in Target:
                return Target
            Check = self._ParseTarget(Target["Option"], Target["Params"])
            if "Error" in Check:
                return Check
            self._Batch = {**self._EmptyBatch(), "Running": True, "Total": len(Ordered),
                           "Results": {U: "queued" for U in Ordered}}
        threading.Thread(target=self._RunBatch, args=(Ordered, Target["Option"], Target["Params"]), name="Batch", daemon=True).start()
        return {"Ok": True, "Total": len(Ordered)}

    def _RunBatch(self, Usernames, Option, Params):
        Batch = self._Batch
        Delay = float(self._Settings["LaunchDelay"])
        for Number, Username in enumerate(Usernames):
            if Batch["Cancelled"]:
                break
            with self._DataLock:
                Batch["Current"], Batch["Results"][Username] = Username, "launching"
            try:
                Result = self._LaunchOne(Username, Option, Params)
            except Exception as Error:
                Logger.exception("Launch of %s crashed", Username)
                Result = {"Error": f"Launch failed ({type(Error).__name__})."}
            with self._DataLock:
                Batch["Current"], Batch["Done"] = "", Number + 1
                Batch["Results"][Username] = "ok" if Result.get("Ok") else "error:" + Result.get("Error", "Launch failed.")
            if Result.get("Error") == "Instance limit reached.":
                Batch["Message"] = "Instance limit reached."
                break
            if Number < len(Usernames) - 1:
                Waited = 0.0
                while Waited < Delay and not Batch["Cancelled"]:
                    time.sleep(0.1)
                    Waited += 0.1
        with self._DataLock:
            if Batch["Cancelled"] and not Batch["Message"]:
                Batch["Message"] = "Cancelled."
            for Username, State in Batch["Results"].items():
                if State in ("queued", "launching"):
                    Batch["Results"][Username] = "skipped"
            Batch["Current"], Batch["Running"] = "", False

    def GetLaunchProgress(self):
        with self._DataLock:
            return {**self._Batch, "Results": dict(self._Batch["Results"])}

    def CancelLaunch(self):
        with self._DataLock:
            if not self._Batch["Running"]:
                return {"Error": "Nothing to cancel."}
            self._Batch["Cancelled"] = True
            self._Batch["Message"] = "Cancelled."
            return {"Ok": True}

    def GetGameMaxPlayers(self, PlaceId):
        return Roblox.GetGameMaxPlayers(PlaceId) if Roblox.IsPlaceId(PlaceId) else 0

    def GetCounter(self):
        """Running count, plus each launched account's live state: {"Accounts": {Username: "starting" / "running"}}
        (a closed client's account is simply absent)."""
        Running = MultiInstance.CountRunning(self._Clients, IncludeStarting=False)  # the label: open game windows only
        return {"Running": Running, "Max": self._Settings["MaxInstances"], "MultiReady": MultiInstance.IsReady(),
                "Accounts": self._Clients.Accounts()}

    # ------------------------------------------------------------ settings

    def GetSettings(self):
        with self._DataLock:
            return {**json.loads(json.dumps(self._Settings)), "Channel": Roblox.GetChannel()}

    def UpdateSetting(self, Key, Value):
        return self.UpdateSettings({Key: Value} if isinstance(Key, str) else {})

    def UpdateSettings(self, Changes):
        """Apply several settings at once. All-or-nothing: one invalid value rejects the batch."""
        if not isinstance(Changes, dict) or not Changes:
            return {"Error": "Nothing to save."}
        try:
            Clean = {Key: Storage.CoerceSetting(Key, Value) for Key, Value in Changes.items()}
        except Storage.InvalidValue as Error:
            return {"Error": str(Error)}
        with self._DataLock:
            self._Settings.update(Clean)
            self._SaveSettings()
        return {"Ok": True}

    def SaveChannel(self, Channel):
        if not isinstance(Channel, str) or not Roblox.ChannelPattern.match(Channel.strip()):
            return {"Error": "Channel names may only use letters, numbers, dot, dash and underscore."}
        return {"Ok": True} if Roblox.SetChannel(Channel.strip()) else {"Error": "Failed to update channel."}

    def GetChannel(self):
        return Roblox.GetChannel()

    # ------------------------------------------------------------ themes

    def GetThemes(self):
        Chosen, Active = self._ChosenThemeId(), self._ActiveThemeId()
        List = [{**Theme, "NeedsOk": self._ThemeNeedsOk(Theme["Id"])} for Theme in Themes.ListThemes()]
        # Blocked: the chosen theme was swapped for Dark at start-up because it doesn't list this version.
        Blocked = next((Theme for Theme in List if Theme["Id"] == Chosen), None) if Active != Chosen else None
        return {"Themes": List, "Active": Active, "Served": Themes.ResolveRoot(Active)[0], "Blocked": Blocked,
                "AppVersion": AppVersion, "Warnings": Themes.ThemeWarnings(Active)[:5]}

    def AllowThemeVersion(self, ThemeId, Remember=False):
        """Use a theme although it doesn't list this RAMMIT version. Remember = don't ask again until RAMMIT
        changes version; otherwise only for this run."""
        if not Themes.ThemeDir(ThemeId):
            return {"Error": "That theme folder no longer exists."}
        if not isinstance(Remember, bool):
            return {"Error": "Expected true or false."}
        Key = f"{ThemeId}@{AppVersion}"
        with self._DataLock:
            self._ThemeVersionOkOnce.add(Key)
            if Remember:
                Saved = [Entry for Entry in self._Settings.get("ThemeVersionOk", []) if Entry != Key]
                self._Settings["ThemeVersionOk"] = (Saved + [Key])[-50:]
                self._SaveSettings()
        return {"Ok": True}

    def GetHeightMap(self):
        return Themes.LoadHeightMap(self._ActiveThemeId())[0]

    def OpenThemesFolder(self):
        try:
            Themes.OpenThemesFolder()
            return {"Ok": True}
        except OSError as Error:
            return {"Error": f"Could not open the Themes folder ({type(Error).__name__})."}

    # ------------------------------------------------------------ windows

    def ResizeWindow(self, Height):
        # pywebview 6 takes logical pixels and applies the monitor DPI itself - do not scale again.
        try:
            Height = max(400, min(int(Height), 1400))
        except (TypeError, ValueError):
            return
        if self._MainSizer:
            try:
                self._MainSizer.Resize(int(900 * 0.85), int(Height * 0.85))
            except Exception:
                pass

    def ResizeWizard(self, Height):
        try:
            Height = max(200, min(int(Height), 1200))
        except (TypeError, ValueError):
            return
        Window, Sizer = self._WizardWindow, self._WizardSizer
        if Window and Sizer:
            try:
                if abs(Height - Window.height) < 2:  # Test1: skip tiny resizes so the window doesn't jitter
                    return
                Sizer.Resize(Themes.LoadHeightMap(self._ActiveThemeId())[0]["WizardWindow"]["Width"], Height)
            except Exception:
                pass

    @staticmethod
    def _DestroyQuietly(Window):
        if Window:
            try:
                Window.destroy()
            except Exception:
                pass


def GuardNavigation(Window, Server, Page):
    """pywebview injects the full js_api into whatever page a window shows, so a privileged
    window must never stay on anything but the local UI. Send it straight back if it leaves."""
    def OnLoaded():
        try:
            Url = Window.get_current_url() or ""
        except Exception:
            return
        if not Url.startswith(Server.Origin + "/"):
            Logger.warning("Blocked navigation away from the RAMMIT UI")
            Window.load_url(Server.Url(Page))
    Window.events.loaded += OnLoaded
