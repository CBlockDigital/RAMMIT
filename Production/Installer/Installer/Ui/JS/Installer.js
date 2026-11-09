// Installer page entry point (Installer.html). Test1's StartAction / UpdateProgress / OnActionDone logic, with:
//   * buttons wired here instead of onclick= (CSP), text set with textContent / El() only
//   * a loading screen instead of fake values, an error screen instead of alert()
//   * "RAMMIT is running", "Older RAMMIT found", Update / Downgrade (any version) + Undo, a working Launch button
//   * accounts an earlier uninstall kept are offered back on a fresh install

import { Api, On, WaitForApi, ReportError } from './Bridge.js';
import { ById, SetLines } from './Dom.js';
import { Go, Nav, SetMenu, BuildCrumbs, FitWindow, WatchSize } from './Screens.js';
import { CreateVersionPicker } from './VersionPicker.js';

const State = {
    Installed: false, Version: '', Branch: '', Path: '', DefaultPath: '', Legacy: null, KeptConfig: null, UndoVersion: '',
    Latest: '', UpdateAvailable: false, VersionsLoaded: false, ShowTest: false,
    LegacyMode: '', LastStart: null, InstallChoice: null,
};

const InstallPicker = CreateVersionPicker(ById('InstallVersionSelect'));
const ChangePicker = CreateVersionPicker(ById('ChangeVersionSelect'), () => { ById('ChangeVersionError').textContent = ''; ShowChangeButton(); });
const V = Ver => (Ver ? 'v' + Ver : '...');
const WithBranch = (Ver, Branch) => V(Ver) + (Ver && Branch === 'Dev' ? ' (Dev)' : '');

// Compares x.y.z[-pre] like Releases.ParseVersion: a pre-release sorts below its release.
function CompareVersions(A, B) {
    const Split = Ver => { const [Main, Pre] = String(Ver).split('-'); return [Main.split('.').map(Number), Pre]; };
    const [Am, Ap] = Split(A), [Bm, Bp] = Split(B);
    for (let I = 0; I < 3; I++) if ((Am[I] || 0) !== (Bm[I] || 0)) return (Am[I] || 0) - (Bm[I] || 0);
    if (Ap === Bp) return 0;
    if (!Ap) return 1;
    if (!Bp) return -1;
    return Ap.localeCompare(Bp, undefined, { numeric: true });
}

// The Update / Downgrade screen's button says what the picked version will do.
function ShowChangeButton() {
    const Ver = ChangePicker.Value();
    const Btn = ById('ChangeInstallBtn');
    const Older = Ver && State.Version && CompareVersions(Ver, State.Version) < 0;
    Btn.textContent = !Ver ? 'UP TO DATE' : (Older ? 'DOWNGRADE' : 'UPDATE');
    Btn.className = 'BtnInst ' + (Older ? 'Primary' : 'Install');
    Btn.disabled = !Ver;
}

// ------------------------------------------------------------ progress (Test1's UpdateProgress, unchanged logic)

function SetStages(List, Active) {
    List.querySelectorAll('li').forEach((Li, I) => {
        Li.className = I < Active ? 'Done' : (I === Active ? 'Active' : '');
    });
}

function UpdateProgress(Data) {
    if (Data.StageLabel) ById('StageLabel').textContent = Data.StageLabel;
    if (Data.StagePct !== undefined) {
        ById('StagePct').textContent = Data.StagePct + '%';
        ById('StageFill').style.width = Data.StagePct + '%';
    }
    if (Data.StageDetail !== undefined) ById('StageDetail').textContent = Data.StageDetail;
    if (Data.OverallPct !== undefined) {
        ById('OverallPct').textContent = Data.OverallPct + '%';
        ById('OverallFill').style.width = Data.OverallPct + '%';
    }
    if (Data.Stages) SetStages(ById('StageList'), Data.Stages.Active);
}

function UpdateUninstallProgress(Data) {
    if (Data.Label) ById('UninstStageLabel').textContent = Data.Label;
    if (Data.Pct !== undefined) {
        ById('UninstPct').textContent = Data.Pct + '%';
        ById('UninstFill').style.width = Data.Pct + '%';
    }
    if (Data.Stages) SetStages(ById('UninstStageList'), Data.Stages.Active);
}

function ResetProgress(Heading) {
    ById('ProgressHeading').textContent = Heading;
    UpdateProgress({ StageLabel: 'Downloading', StagePct: 0, StageDetail: '', OverallPct: 0, Stages: { Active: 0 } });
}

function ResetUninstallProgress(Heading) {
    ById('UninstHeading').textContent = Heading;
    UpdateUninstallProgress({ Label: 'Deleting files', Pct: 0, Stages: { Active: 0 } });
}

// ------------------------------------------------------------ error + running screens (new)

let ErrorRetry = null;
let ErrorBack = null;

function ShowError(Message, Details, Retry, Back, Title) {
    ById('ErrorTitle').textContent = Title || 'Something went wrong.';
    ById('ErrorText').textContent = Message || 'Something unexpected went wrong.';
    ById('ErrorDetail').textContent = Details || '';
    ById('ErrorCopyBtn').hidden = !Details;
    ErrorRetry = Retry;
    ErrorBack = Back;
    ById('ErrorRetryBtn').hidden = !Retry;
    ById('ErrorBackBtn').textContent = Back ? 'BACK' : 'CLOSE';
    Go('Error');
}

let RunningRetry = null;
let RunningBack = null;

function ShowRunning(ActionText, Retry, Back) {
    ById('RunningAction').textContent = ActionText;
    RunningRetry = Retry;
    RunningBack = Back;
    ById('RunningCloseBtn').disabled = false;
    Go('Running');
}

// Runs Start() unless RAMMIT is open; then shows the Running screen, which retries Start() itself.
async function IfNotRunning(ActionText, Start, Back) {
    const Result = await Api.CheckRunning().catch(() => ({ Running: false }));
    if (Result.Running) ShowRunning(ActionText, () => IfNotRunning(ActionText, Start, Back), Back);
    else Start();
}

// ------------------------------------------------------------ versions

async function LoadVersions(Refresh) {
    const Result = await Api.ListVersions(State.ShowTest, !!Refresh).catch(Error => ({ Error: String(Error) }));
    if (Result.Error) return Result;
    State.VersionsLoaded = true;
    State.Latest = Result.Latest;
    State.UpdateAvailable = Result.UpdateAvailable;
    InstallPicker.SetVersions(Result.Versions.map(Ver => ({ ...Ver, Installed: false })), Result.Latest, Result.Latest);
    // Newest first, the installed one greyed out between newer and older; preselect the latest when it's newer.
    ChangePicker.SetVersions(Result.Versions, Result.Latest, State.UpdateAvailable ? Result.Latest : '');
    ShowChangeButton();
    ById('LatestVer').textContent = V(Result.Latest);
    ById('FooterVersion').textContent = Result.Latest ? V(Result.Latest) : '';
    return Result;
}

async function NeedVersions(Then, Back) {
    if (State.VersionsLoaded) return Then();
    Go('Loading');
    const Result = await LoadVersions(true);
    if (Result.Error) ShowError(Result.Error, Result.Details, () => NeedVersions(Then, Back), Back, "Couldn't load the versions.");
    else Then();
}

document.querySelectorAll('.ShowTestVersions').forEach(Box => Box.addEventListener('change', async () => {
    State.ShowTest = Box.checked;
    document.querySelectorAll('.ShowTestVersions').forEach(Other => { Other.checked = Box.checked; });
    await LoadVersions(false);
}));

// ------------------------------------------------------------ actions (Test1's StartAction)

function ApplyState(S) {
    Object.assign(State, { Installed: S.Installed, Version: S.Version, Branch: S.Branch, Path: S.Path, DefaultPath: S.DefaultPath,
        Legacy: S.Legacy, KeptConfig: S.KeptConfig, UndoVersion: S.UndoVersion });
    SetMenu(S.Installed);
    ById('InstalledVer').textContent = WithBranch(S.Version, S.Branch);
    ById('UninstallVer').textContent = V(S.Version);
    ShowKept();
    if (!ById('InstallPath').value) ById('InstallPath').value = S.DefaultPath;
    ById('InstallPath').placeholder = '';
    if (S.Legacy) {
        ById('LegacyVer').textContent = S.Legacy.Version ? 'v' + S.Legacy.Version : 'unknown version';
        ById('LegacyPath').textContent = S.Legacy.Path;
        ById('LegacyConfirmPath').textContent = S.Legacy.Path;
        document.querySelectorAll('.LegacyMenuVer').forEach(E => { E.textContent = ById('LegacyVer').textContent; });
        document.querySelectorAll('.LegacyMenuPath').forEach(E => { E.textContent = S.Legacy.Path; });
    }
    ShowLegacyButtons();
    UpdateUndo();
}

// An old version put off with Ignore: reachable from either menu, on the same screen with the same four choices.
// With RAMMIT already installed, the two "move" choices don't reinstall it (MoveIntoInstalled).
function ShowLegacyButtons() {
    const PutOff = !!(State.Legacy && State.Legacy.Deferred);
    ById('FreshLegacyBtn').hidden = ById('InstalledLegacyBtn').hidden = !PutOff;
    ById('FreshLegacyLine').hidden = ById('InstalledLegacyLine').hidden = !PutOff;
}

// Choices 1/2 with RAMMIT already installed: only the old version's accounts and settings come across (and
// MoveRemove then removes it). Asks which accounts to keep when both have some, like an install does.
async function MoveIntoInstalled(ConfigChoice) {
    const Back = () => Go('Legacy', 'LegacyMove');
    const Check = await Api.CheckLegacyMove().catch(Error => ({ Error: String(Error) }));
    if (Check.Running) { ShowRunning('move your accounts', () => MoveIntoInstalled(ConfigChoice), Back); return; }
    if (Check.Error) { ShowError(Check.Error, '', null, Back); return; }
    if (Check.NeedsConfigChoice && !ConfigChoice) {
        ById('UseOldBtn').textContent = "USE THE OLD VERSION'S ACCOUNTS";
        Go('ConfigConflict', 'LegacyMove');
        return;
    }
    ResetUninstallProgress('Moving your accounts...');
    Go('ProgressUninstall', 'LegacyMove');
    StartJob('LegacyMove', () => Api.StartLegacyMove(State.LegacyMode, ConfigChoice || ''), Back);
}

// Accounts an earlier uninstall kept (or Test1's uninstall): mentioned on the fresh menu, offered on Install.
function ShowKept() {
    const Kept = State.Installed || State.LegacyMode ? null : State.KeptConfig;
    ById('KeptFreshLine').hidden = !Kept;
    ById('KeptRow').hidden = !Kept;
    if (Kept) {
        ById('KeptFreshPath').textContent = Kept.Path;
        ById('KeptPath').textContent = Kept.Path;
    }
}

function UpdateUndo() {
    ById('UndoRow').hidden = !State.UndoVersion;
    ById('UndoBtn').textContent = 'UNDO LAST CHANGE (BACK TO ' + V(State.UndoVersion).toUpperCase() + ')';
}

function StartJob(Action, Call, Back) {
    State.LastStart = { Action, Call, Back };
    Call().then(Result => {
        if (Result && Result.Error) {
            if (Result.Running) ShowRunning('continue', () => StartJob(Action, Call, Back), Back);
            else ShowError(Result.Error, '', null, Back);
        }
    }).catch(Error => { ReportError(Error); ShowError(String(Error), '', null, Back); });
}

function StartAction(Action) {
    Nav.CurrentAction = Action;
    const BackToMenu = () => Go(Nav.CurrentMenu, Action);
    if (Action === 'Repair') {
        IfNotRunning('repair it', () => {
            ResetProgress('Repairing RAMMIT...');
            ById('ActionDoneTitle').textContent = 'Repair complete.';
            Go('Progress', Action);
            StartJob(Action, () => Api.StartRepair(), BackToMenu);
        }, BackToMenu);
    } else if (Action === 'Update') {
        const Ver = ChangePicker.Value();
        if (!Ver) { ById('ChangeVersionError').textContent = 'Pick a version from the list.'; return; }
        if (Ver === State.Version) { ById('ChangeVersionError').textContent = "That's the version you have. Use Repair to reinstall it."; return; }
        const Older = CompareVersions(Ver, State.Version) < 0;
        const Back = () => Go('ChangeVersion', Action);
        IfNotRunning(Older ? 'downgrade it' : 'update it', () => {
            ResetProgress((Older ? 'Downgrading' : 'Updating') + ' RAMMIT to ' + V(Ver) + '...');
            ById('ActionDoneTitle').textContent = Older ? 'Downgraded successfully.' : 'Updated successfully.';
            Go('Progress', Action);
            StartJob(Action, () => Api.StartChangeVersion(Ver), Back);
        }, Back);
    } else if (Action === 'Undo') {
        const Back = () => Go('ChangeVersion', 'Update');
        IfNotRunning('change its version', () => {
            ResetProgress('Going back to RAMMIT ' + V(State.UndoVersion) + '...');
            ById('ActionDoneTitle').textContent = 'Last change undone.';
            Go('Progress', 'Update');
            StartJob('Undo', () => Api.StartUndo(), Back);
        }, Back);
    } else if (Action === 'Uninstall') {
        const RemoveConfigs = ById('RemoveConfigs').checked;
        const Back = () => Go('ConfirmUninstall', Action);
        IfNotRunning('uninstall it', () => {
            ResetUninstallProgress('Removing RAMMIT...');
            Go('ProgressUninstall', Action);
            StartJob(Action, () => Api.StartUninstall(RemoveConfigs), Back);
        }, Back);
    } else if (Action === 'Install') {
        StartInstall();
    }
}

async function StartInstall(ConfigChoice) {
    const Version = InstallPicker.Value();
    const InstPath = ById('InstallPath').value.trim();
    const Flow = State.LegacyMode ? 'LegacyInstall' : 'Install';
    const Back = () => Go('Version', Flow);
    ById('PathError').textContent = '';
    if (!Version) { ById('PathError').textContent = 'Pick a version from the list.'; return; }
    const Kept = KeptChoice();
    const Check = await Api.CheckInstall(InstPath, State.LegacyMode, Kept).catch(Error => ({ Error: String(Error) }));
    if (Check.Running) { ShowRunning('install it', () => StartInstall(ConfigChoice), Back); return; }
    if (Check.Error) { ById('PathError').textContent = Check.Error; return; }
    if (Check.NeedsConfigChoice && !ConfigChoice) {
        ById('UseOldBtn').textContent = State.LegacyMode ? "USE THE OLD VERSION'S ACCOUNTS" : 'USE MY SAVED ACCOUNTS FROM BEFORE';
        Go('ConfigConflict', Flow);
        return;
    }
    ById('InstallPath').value = Check.Path;
    ResetProgress('Installing RAMMIT...');
    Go('Progress', Flow);
    const Shortcuts = [['ShortcutDesktop', 'Desktop'], ['ShortcutStartMenu', 'StartMenu']].filter(([Id]) => ById(Id).checked).map(([, Name]) => Name);
    StartJob('Install', () => Api.StartInstall(Version, Check.Path, { Legacy: State.LegacyMode, ConfigChoice: ConfigChoice || '', KeptConfig: Kept, Shortcuts }), Back);
}

// '' (nothing kept, or the old Test1 flow), 'Use' (bring the kept accounts back) or 'Fresh' (start without them).
const KeptChoice = () => (State.KeptConfig && !State.LegacyMode ? (ById('UseKept').checked ? 'Use' : 'Fresh') : '');

// ------------------------------------------------------------ results (Test1's OnActionDone)

const Warn = Result => (Result.Warnings || []).map(Text => [Text]);

// What the install made, from the ticked shortcut boxes: [] when neither was ticked.
function ShortcutLine(Made) {
    const Places = { Desktop: 'the Desktop', StartMenu: 'the Start Menu' };
    const Where = (Made || []).map(Name => Places[Name]).filter(Boolean);
    if (!Where.length) return [];
    return [[Where.length > 1 ? `Shortcuts were added to ${Where.join(' and ')}.` : `A shortcut was added to ${Where[0]}.`]];
}

On('Progress', UpdateProgress);
On('UninstallProgress', UpdateUninstallProgress);

On('Done', async Result => {
    if (Result.Action === 'Install') {
        State.Installed = true; State.Version = Result.Version; State.Branch = Result.Branch; State.Path = Result.Path;
        State.UndoVersion = ''; State.KeptConfig = null;
        SetLines(ById('InstallDoneText'), [
            ['Installed ', { Em: WithBranch(Result.Version, Result.Branch) }, ' to ', { Em: Result.Path, Class: 'Path' }, '.'],
            ...(Result.MovedLegacy ? [['Your accounts and settings came across from the old version.']] : []),
            ...(Result.KeptLine ? [[Result.KeptLine]] : []),
            ...ShortcutLine(Result.Shortcuts),
            ...Warn(Result),
            [],
            ['Have fun - and ping us if anything breaks.'],
        ]);
        Go('InstallDone');
    } else if (Result.Action === 'Uninstall') {
        const Lines = [['RAMMIT has been removed from this system.']];
        if (Result.ConfigKept) Lines.push(['Your ', { Em: 'Config/' }, ' folder was kept in ', { Em: Result.Path, Class: 'Path' }, '. Installing again brings it back.']);
        if (Result.Left && Result.Left.length) Lines.push(["Files RAMMIT didn't install were left in ", { Em: Result.Path, Class: 'Path' }, '.']);
        Lines.push([], ["If something broke, please open an issue - we'd love a second chance."]);
        SetLines(ById('UninstallDoneText'), Lines);
        Go('UninstallDone');
    } else if (Result.Action === 'LegacyMove') {
        State.Legacy = null;
        State.LegacyMode = '';
        ShowLegacyButtons();
        const Lines = [['Your accounts and settings from the old version are now in ', { Em: Result.InstallPath, Class: 'Path' }, '.']];
        if (Result.Mode === 'MoveRemove') Lines.push(['The old version was removed from ', { Em: Result.Path, Class: 'Path' }, '.']);
        else Lines.push(['The old version was left as it is in ', { Em: Result.Path, Class: 'Path' }, '.']);
        if (Result.Left && Result.Left.length) Lines.push(['Files it didn\'t install were left there: ', { Em: Result.Left.slice(0, 3).join(', ') }, '.']);
        Lines.push(...Warn(Result), ['Press ', { Em: 'Continue' }, ' to go back to the menu.']);
        ById('LegacyDoneTitle').textContent = 'Accounts moved.';
        SetLines(ById('LegacyDoneText'), Lines);
        Go('LegacyDone');
    } else if (Result.Action === 'LegacyRemove') {
        State.Legacy = null;
        ShowLegacyButtons();
        ById('LegacyDoneTitle').textContent = 'Old version removed.';
        const Lines = [['The old test version was removed from ', { Em: Result.Path, Class: 'Path' }, '.']];
        if (Result.Left && Result.Left.length) Lines.push(['Files it didn\'t install were left there: ', { Em: Result.Left.slice(0, 3).join(', ') }, '.']);
        Lines.push(['Press ', { Em: 'Continue' }, State.Installed ? ' to go back to the menu.' : ' to install the new RAMMIT.']);
        SetLines(ById('LegacyDoneText'), Lines);
        Go('LegacyDone');
    } else {
        State.Version = Result.Version;
        State.Branch = Result.Branch;
        State.UndoVersion = Result.UndoVersion || '';
        ById('InstalledVer').textContent = WithBranch(Result.Version, Result.Branch);
        ById('UninstallVer').textContent = V(Result.Version);
        UpdateUndo();
        SetLines(ById('ActionDoneText'), [
            ['RAMMIT is now on ', { Em: V(Result.Version) }, '.'],
            ...(Result.OldVersion && Result.OldVersion !== Result.Version ? [['Your settings from ', { Em: V(Result.OldVersion) }, ' are backed up in ', { Em: 'Config.Backup/' }, '.']] : []),
            ...Warn(Result),
            ['You can close this window and launch the app.'],
        ]);
        Go('ActionDone');
    }
});

On('Failed', Failure => {
    const Last = State.LastStart;
    const Back = Last ? Last.Back : () => Go(Nav.CurrentMenu);
    const Retry = Last ? () => { RetryLast(); } : null;
    if (Failure.Running) ShowRunning('continue', Retry, Back);
    else ShowError(Failure.Message, Failure.Details, Retry, Back);
});

function RetryLast() {
    const Last = State.LastStart;
    if (!Last) return;
    if (Last.Action === 'Uninstall' || Last.Action === 'LegacyRemove') {
        ResetUninstallProgress(ById('UninstHeading').textContent);
        Go('ProgressUninstall');
    } else {
        ResetProgress(ById('ProgressHeading').textContent);
        Go('Progress');
    }
    StartJob(Last.Action, Last.Call, Last.Back);
}

// ------------------------------------------------------------ buttons

const Click = (Id, Handler) => ById(Id).addEventListener('click', Event => {
    Event.preventDefault();
    Promise.resolve().then(Handler).catch(ReportError);
});
const CloseWindow = () => Api.CloseWindow().catch(() => window.close());

Click('FreshInstallBtn', () => NeedVersions(() => Go('Version', 'Install'), () => Go('MenuFresh', 'Install')));
Click('FreshCancelBtn', CloseWindow);
Click('FreshLegacyBtn', () => Go('Legacy', 'LegacyInstall'));
Click('InstalledLegacyBtn', () => Go('Legacy', 'LegacyMove'));
Click('InstalledCancelBtn', CloseWindow);
Click('UpdateBtn', () => {
    ById('ChangeVersionError').textContent = State.VersionsLoaded ? '' : "Couldn't load the version list. You can still undo the last change.";
    ShowChangeButton();
    Go('ChangeVersion', 'Update');
    if (!State.VersionsLoaded) LoadVersions(true).then(R => { if (!R.Error) ById('ChangeVersionError').textContent = ''; });
});
Click('RepairBtn', () => StartAction('Repair'));
Click('UninstallBtn', () => Go('ConfirmUninstall', 'Uninstall'));
Click('VersionBackBtn', () => Go(State.LegacyMode ? 'Legacy' : Nav.CurrentMenu, State.LegacyMode ? 'LegacyInstall' : 'Install'));
Click('VersionInstallBtn', () => StartAction('Install'));
Click('BrowseBtn', async () => {
    const Result = await Api.BrowseFolder();
    if (Result) { ById('InstallPath').value = Result; ById('PathError').textContent = ''; }
});
Click('ChangeBackBtn', () => Go('MenuInstalled', 'Update'));
Click('ChangeInstallBtn', () => StartAction('Update'));
Click('UndoBtn', () => StartAction('Undo'));
Click('UninstallBackBtn', () => Go(Nav.CurrentMenu, 'Uninstall'));
Click('UninstallConfirmBtn', () => StartAction('Uninstall'));
Click('InstallDoneCloseBtn', CloseWindow);
Click('ActionDoneCloseBtn', CloseWindow);
Click('UninstallDoneCloseBtn', CloseWindow);
// LAUNCH RAMMIT on both done screens (install, and update / repair / undo): starts it and closes the installer.
async function LaunchRammit(DoneScreen) {
    const Result = await Api.Launch();
    if (Result && Result.Error) ShowError(Result.Error, '', null, () => Go(DoneScreen), "RAMMIT didn't start.");
    else CloseWindow();
}
Click('LaunchBtn', () => LaunchRammit('InstallDone'));
Click('ActionLaunchBtn', () => LaunchRammit('ActionDone'));

// Older RAMMIT found
Click('LegacyMoveRemoveBtn', () => {
    State.LegacyMode = 'MoveRemove';
    if (State.Installed) { MoveIntoInstalled(); return; }
    NeedVersions(() => Go('Version', 'LegacyInstall'), () => Go('Legacy', 'LegacyInstall'));
});
Click('LegacyMoveKeepBtn', () => {
    State.LegacyMode = 'MoveKeep';
    if (State.Installed) { MoveIntoInstalled(); return; }
    // The new one can't share the old one's folder when the old one stays.
    if (State.Legacy && ById('InstallPath').value.trim().toLowerCase() === State.Legacy.Path.toLowerCase()) ById('InstallPath').value = State.Legacy.Path + '-New';
    NeedVersions(() => Go('Version', 'LegacyInstall'), () => Go('Legacy', 'LegacyInstall'));
});
Click('LegacyRemoveBtn', () => Go('LegacyConfirm', 'LegacyRemove'));
Click('LegacyIgnoreBtn', async () => {
    const Result = await Api.IgnoreLegacy(ById('LegacyDontAsk').checked);
    if (Result && Result.Error) { ShowError(Result.Error, '', null, () => Go('Legacy')); return; }
    State.LegacyMode = '';
    // Ticked: gone for good. Unticked: put off - it stays on the menu as OLD VERSION.
    State.Legacy = ById('LegacyDontAsk').checked ? null : Object.assign({}, State.Legacy, { Deferred: true });
    ShowLegacyButtons();
    Go(Nav.CurrentMenu, State.Installed ? 'Update' : 'Install');
});
Click('LegacyConfirmBackBtn', () => Go('Legacy', 'LegacyRemove'));
Click('LegacyConfirmRemoveBtn', () => {
    const Back = () => Go('LegacyConfirm', 'LegacyRemove');
    IfNotRunning('remove it', () => {
        ResetUninstallProgress('Removing the old version...');
        Go('ProgressUninstall', 'LegacyRemove');
        StartJob('LegacyRemove', () => Api.StartLegacyRemove(), Back);
    }, Back);
});
Click('LegacyDoneContinueBtn', () => { State.LegacyMode = ''; Go(Nav.CurrentMenu, State.Installed ? 'Update' : 'Install'); });

// Settings clash
const MovingIntoInstalled = () => !!(State.Installed && State.LegacyMode);
Click('KeepNewBtn', () => (MovingIntoInstalled() ? MoveIntoInstalled('KeepNew') : StartInstall('KeepNew')));
Click('UseOldBtn', () => (MovingIntoInstalled() ? MoveIntoInstalled('UseOld') : StartInstall('UseOld')));
Click('ConflictBackBtn', () => (MovingIntoInstalled() ? Go('Legacy', 'LegacyMove') : Go('Version', State.LegacyMode ? 'LegacyInstall' : 'Install')));

// Running
Click('RunningCloseBtn', async () => {
    ById('RunningCloseBtn').disabled = true;
    const Result = await Api.CloseRunning();
    ById('RunningCloseBtn').disabled = false;
    if (Result && Result.Ok && RunningRetry) RunningRetry();
});
Click('RunningRetryBtn', () => { if (RunningRetry) RunningRetry(); });
Click('RunningBackBtn', () => { if (RunningBack) RunningBack(); else Go(Nav.CurrentMenu); });

// Error
Click('ErrorRetryBtn', () => { if (ErrorRetry) ErrorRetry(); });
Click('ErrorBackBtn', () => { if (ErrorBack) ErrorBack(); else CloseWindow(); });
Click('ErrorCopyBtn', async () => {
    const Text = ById('ErrorText').textContent + '\n' + ById('ErrorDetail').textContent;
    try {
        await navigator.clipboard.writeText(Text);
    } catch (_) {
        const Range = document.createRange();
        Range.selectNodeContents(ById('ErrorDetail'));
        getSelection().removeAllRanges();
        getSelection().addRange(Range);
        document.execCommand('copy');
    }
    ById('ErrorCopyBtn').textContent = 'COPIED';
    setTimeout(() => { ById('ErrorCopyBtn').textContent = 'COPY DETAILS'; }, 1500);
});

// Confirm uninstall: Test1's conditional text, built with nodes instead of innerHTML
ById('RemoveConfigs').addEventListener('change', () => {
    const Line = ById('ConfirmUninstallLine');
    if (ById('RemoveConfigs').checked) SetLines(Line, [['This will also remove your ', { Strong: 'Config/' }, ' folder and its backups.']]);
    else SetLines(Line, [['Your saved accounts and configs in ', { Strong: 'Config/' }, ' will be left untouched, and installing again brings them back.']]);
});

// Path typed by hand: clear the old complaint
ById('InstallPath').addEventListener('input', () => { ById('PathError').textContent = ''; });

// ------------------------------------------------------------ boot

async function Boot() {
    // A reload can bring back old tick boxes (browser form restore) that no longer match State.
    document.querySelectorAll('.ShowTestVersions, #RemoveConfigs, #LegacyDontAsk').forEach(Box => { Box.checked = false; });
    ['UseKept', 'ShortcutDesktop', 'ShortcutStartMenu'].forEach(Id => { ById(Id).checked = true; });
    WatchSize();
    BuildCrumbs();
    FitWindow();
    await WaitForApi('GetState');
    await Load();
}

async function Load() {
    const Start = await Api.GetState();
    ApplyState(Start);
    Api.BootFinished().catch(() => {});  // the Loading screen takes over from the native spinner

    if (Start.StartScreen === 'ConfirmUninstall') {  // Settings > Apps > Uninstall: no network needed
        Go('ConfirmUninstall', 'Uninstall');
        LoadVersions(false);
        return;
    }
    const Result = await LoadVersions(false);
    if (Result.Error) {
        ById('LatestVer').textContent = 'unknown (offline)';
        ById('FooterVersion').textContent = State.Installed ? V(State.Version) : '';
        ShowChangeButton();
        if (State.Installed) { Go('MenuInstalled', 'Update'); return; }  // Repair/Undo/Uninstall still work
        if (State.Legacy && !State.Legacy.Deferred) { Go('Legacy', 'LegacyInstall'); return; }
        if (State.Legacy) { Go('MenuFresh', 'Install'); return; }  // put off: the menu, with OLD VERSION
        ShowError(Result.Error, Result.Details, () => { Go('Loading'); Load().catch(ReportError); }, null, "Couldn't load the versions.");
        return;
    }
    if (State.Installed) Go('MenuInstalled', 'Update');
    else if (State.Legacy && !State.Legacy.Deferred) Go('Legacy', 'LegacyInstall');
    else Go('MenuFresh', 'Install');  // with OLD VERSION when the old one was put off
}

Boot().catch(Error => { ReportError(Error); ShowError(String(Error), '', null, null); });
