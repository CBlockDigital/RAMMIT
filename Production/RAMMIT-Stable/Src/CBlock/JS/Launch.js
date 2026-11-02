// LAUNCHER CONTROLS panel: launch option + its boxes, the launch/cancel button, batch progress,
// the RUNNING counter, and window height.

import { Api, ReportError } from './Bridge.js';
import { ById, Debounce } from './Dom.js';
import { InitSelect, SetSelectValue, GetSelectValue } from './Select.js';
import { CreateLaunchForm } from './LaunchForm.js';
import { State } from './State.js';
import { ApplySelection, ApplyAccountStatus, SelectedInListOrder } from './Accounts.js';
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
    const Names = SelectedInListOrder();
    if (!Names.length) { ShowLaunchError('No account selected.'); return; }
    SetLaunchStatus(Names.length > 1 ? `Launching 1 / ${Names.length}...` : 'Launching...');
    State.AccountStatus = {};
    ApplyAccountStatus();
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

const StatusCells = {
    ok: { State: 'Ok', Text: '✓' }, launching: { State: 'Launching', Text: '•••' },
    queued: { State: 'Queued', Text: '…' }, skipped: { State: 'Queued', Text: '–' },
};

function ApplyProgress(Progress) {
    State.AccountStatus = {};
    Object.entries(Progress.Results || {}).forEach(([Name, Value]) => {
        const Text = String(Value);
        if (StatusCells[Text]) State.AccountStatus[Name] = StatusCells[Text];
        else if (Text.startsWith('error:')) State.AccountStatus[Name] = { State: 'Error', Text: '✗', Title: Text.slice(6) };
    });
    ApplyAccountStatus();
    if (Progress.Running) SetLaunchStatus(`Launching ${Math.min(Progress.Done + 1, Progress.Total)} / ${Progress.Total}...`);
}

function FinishBatch(Progress) {
    const Values = Object.values(Progress.Results || {}).map(String);
    const Ok = Values.filter(V => V === 'ok').length;
    const Errors = Values.filter(V => V.startsWith('error:'));
    if (Errors.length || Progress.Message) {
        let Text = `Launched ${Ok}/${Progress.Total}`;
        if (Progress.Message) Text += ' — ' + Progress.Message;
        if (Errors.length) Text += ` — ${Errors.length} failed: ${Errors[0].slice(6)}`;
        ShowLaunchError(Text);
    } else {
        ShowLaunchDone(`Launched ${Ok}/${Progress.Total}`);
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
    } catch (_) { /* backend busy - next tick */ }
}

export function StartCounterLoop() {
    UpdateCounter();
    setInterval(UpdateCounter, 1000);
}
