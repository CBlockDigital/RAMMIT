// LAUNCHER CONTROLS panel: launch option + its boxes, the launch/cancel button, batch progress,
// the RUNNING counter, and window height.

import { Api, ReportError } from './Bridge.js';
import { ById, Debounce } from './Dom.js';
import { InitSelect, SetSelectValue, GetSelectValue } from './Select.js';
import { CreateLaunchForm } from './LaunchForm.js';
import { State } from './State.js';
import { ApplySelection, ApplyAccountStatus, SelectedInListOrder, RenewTarget, RenewAccount } from './Accounts.js';
import { SetLaunchStatus, ShowLaunchError, ShowLaunchDone } from './Status.js';
import { ThemeNoteExtra } from './Themes.js';

// Window height per launch option comes from this theme's HeightMap.json ("MainWindow").
let HeightMap = { 'Home': 716, 'PlayerFilterExtra': 50 };

let Form = null;
let BatchPoll = null;

const SaveParams = Debounce(() => Api.UpdateSetting('LaunchParams', Form.GetParams()).catch(ReportError), 300);

export async function LoadHeightMap() {
    const Map = await Api.GetHeightMap();
    if (Map && Map.MainWindow) HeightMap = Map.MainWindow;
}

export function InitLaunchPanel() {
    Form = CreateLaunchForm(ById('LaunchFields'), { OnChange: SaveParams, OnResize: ResizeForCurrentOption });
    InitSelect(ById('LaunchOptionSelect'), Option => {
        Form.Render(Option, {});
        Api.UpdateSettings({ LaunchOption: Option, LaunchParams: {} }).catch(ReportError);
    });
    ById('LaunchBtn').addEventListener('click', OnLaunchClick);
    document.addEventListener('ThemeNoteChanged', ResizeForCurrentOption);
}

// Called once at start-up with the saved settings.
export function RestoreLaunchPanel(Settings) {
    const Option = SetSelectValue(ById('LaunchOptionSelect'), Settings.LaunchOption) ? Settings.LaunchOption : 'Home';
    Form.Render(Option, Settings.LaunchParams || {});
}

export function ResizeForCurrentOption() {
    let Height = HeightMap[GetSelectValue(ById('LaunchOptionSelect'))] || HeightMap.Home || 716;
    const PlayerSel = ById('PlayerModeSelect');
    if (PlayerSel && ['min_only', 'max_only', 'range'].includes(GetSelectValue(PlayerSel))) Height += HeightMap.PlayerFilterExtra || 0;
    Height += ThemeNoteExtra();  // exactly as much as a note under the Theme list adds (0 when there is none)
    Api.ResizeWindow(Height).catch(() => {});
}

function OnLaunchClick() {
    if (State.BatchRunning) { Api.CancelLaunch().catch(ReportError); return; }
    LaunchSelected().catch(Error => { ReportError(Error); ShowLaunchError('Launch failed: ' + Error.message); });
}

async function LaunchSelected() {
    const Renew = RenewTarget();
    if (Renew && !(await RenewAccount(Renew))) return;  // RENEW AND LAUNCH: sign in again first, launch only if it worked
    const Names = SelectedInListOrder();
    if (!Names.length) { ShowLaunchError('No account selected.'); return; }
    SetLaunchStatus(Names.length > 1 ? `Launching 1 / ${Names.length}...` : 'Launching...');
    Waiting = null;
    LastProgress = null;
    LastResults = {};
    RenderAccountStatus();
    const Option = GetSelectValue(ById('LaunchOptionSelect'));
    const Result = await Api.LaunchAccounts(Names, Option, Form.GetParams(), State.SelectedConfig);
    if (Result && Result.Error) { ShowLaunchError(Result.Error); return; }
    SetBatchRunning(true);
    clearInterval(BatchPoll);
    BatchPoll = setInterval(PollProgress, 350);
}

async function PollProgress() {
    let Progress;
    try { Progress = await Api.GetLaunchProgress(); } catch (_) { return; }
    if (!Progress) return;
    ApplyProgress(Progress);
    if (!Progress.Running) {
        clearInterval(BatchPoll);
        BatchPoll = null;
        SetBatchRunning(false);
        FinishBatch(Progress);
    }
}

function SetBatchRunning(Running) {
    State.BatchRunning = Running;
    const Button = ById('LaunchBtn');
    Button.classList.toggle('Cancel', Running);
    if (Running) Button.textContent = 'CANCEL LAUNCH';
    else ApplySelection();
}

// Row marks come from two places: the batch's results (queued / launching / skipped / error) and, once an account's
// launch went through, its client's live state from GetCounter (App/MultiInstance.ClientTracker): "•••" while Roblox
// starts, "✓" once its game window is open, nothing again once that window closes.
const StatusCells = {
    launching: { State: 'Launching', Text: '•••' },
    queued: { State: 'Queued', Text: '…' }, skipped: { State: 'Queued', Text: '–' },
};
const LiveCells = {
    starting: { State: 'Launching', Text: '•••', Title: 'Roblox is starting' },
    running: { State: 'Ok', Text: '✓', Title: 'Open in Roblox' },
};
let LastResults = {};   // username -> the batch's result for it
let LiveAccounts = {};  // username -> "starting" / "running"

function RenderAccountStatus() {
    State.AccountStatus = {};
    Object.entries(LastResults).forEach(([Name, Value]) => {
        const Text = String(Value);
        if (Text === 'ok') {  // launched: the live state decides; until the first counter tick, it's starting
            if (State.BatchRunning) State.AccountStatus[Name] = LiveCells.starting;
        } else if (StatusCells[Text]) State.AccountStatus[Name] = StatusCells[Text];
        else if (Text.startsWith('error:')) State.AccountStatus[Name] = { State: 'Error', Text: '✗', Title: Text.slice(6) };
    });
    Object.entries(LiveAccounts).forEach(([Name, Live]) => { if (LiveCells[Live]) State.AccountStatus[Name] = LiveCells[Live]; });
    ApplyAccountStatus();
}

// The status line only says "Launched" once the game windows are open (as RAMMIT's earlier test builds did): while an account
// is being launched, or its window isn't open yet, it says "Launching X / Y..."; in the launch delay after an account
// whose window is already open, "Launched X/Y". After the last launch it waits for the windows, then ShowLaunchDone
// (which clears itself); it gives up waiting after WindowWait.
const WindowWait = 30000;
let LastProgress = null;
let Waiting = null;  // { Names, Ok, Total, Since } after a batch, until its windows are open

const IsOpen = Name => LiveAccounts[Name] === 'running';

function BatchStatusText(Progress) {
    const Results = Progress.Results || {};
    if (Object.values(Results).includes('launching')) return `Launching ${Math.min(Progress.Done + 1, Progress.Total)} / ${Progress.Total}...`;
    const Last = Object.keys(Results).filter(Name => Results[Name] === 'ok').pop();
    return Last && IsOpen(Last) ? `Launched ${Progress.Done}/${Progress.Total}` : `Launching ${Progress.Done} / ${Progress.Total}...`;
}

function RenderLaunchStatus() {
    if (State.BatchRunning && LastProgress) { SetLaunchStatus(BatchStatusText(LastProgress)); return; }
    if (!Waiting) return;
    if (Waiting.Names.every(IsOpen) || Date.now() - Waiting.Since > WindowWait) {
        ShowLaunchDone(`Launched ${Waiting.Ok}/${Waiting.Total}`);
        Waiting = null;
    } else {
        SetLaunchStatus(`Launching ${Waiting.Total} / ${Waiting.Total}...`);
    }
}

function ApplyProgress(Progress) {
    LastResults = Progress.Results || {};
    LastProgress = Progress;
    RenderAccountStatus();
    if (Progress.Running) RenderLaunchStatus();
}

function FinishBatch(Progress) {
    const Results = Progress.Results || {};
    const Values = Object.values(Results).map(String);
    const Ok = Values.filter(V => V === 'ok').length;
    const Errors = Values.filter(V => V.startsWith('error:'));
    if (Errors.length || Progress.Message) {
        let Text = `Launched ${Ok}/${Progress.Total}`;
        if (Progress.Message) Text += ' — ' + Progress.Message;
        if (Errors.length) Text += ` — ${Errors.length} failed: ${Errors[0].slice(6)}`;
        ShowLaunchError(Text);
    } else {
        Waiting = { Names: Object.keys(Results).filter(Name => Results[Name] === 'ok'), Ok, Total: Progress.Total, Since: Date.now() };
        RenderLaunchStatus();
    }
    UpdateCounter();
}

export async function UpdateCounter() {
    try {
        const Counter = await Api.GetCounter();
        const Label = ById('CounterLabel');
        // MultiReady is false when Roblox was already open before RAMMIT started (see App/MultiInstance.py).
        Label.textContent = `RUNNING: ${Counter.Running} / ${Counter.Max}` + (Counter.MultiReady === false ? ' ⚠' : '');
        Label.title = Counter.MultiReady === false
            ? 'Roblox was already open when RAMMIT started, so only one client can run. Close every Roblox window and RAMMIT will take over on the next launch.' : '';
        LiveAccounts = Counter.Accounts || {};
        RenderAccountStatus();
        RenderLaunchStatus();
    } catch (_) { /* backend busy - next tick */ }
}

export function StartCounterLoop() {
    UpdateCounter();
    setInterval(UpdateCounter, 1000);
}
