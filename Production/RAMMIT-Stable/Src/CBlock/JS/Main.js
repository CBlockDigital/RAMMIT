// Main window entry point (Index.html). Boot order matters: wire controls, wait for the Python
// bridge, then load data and restore the last session.

import { Api, WaitForApi, On, ReportError } from './Bridge.js';
import { ById } from './Dom.js';
import { State } from './State.js';
import { RefreshAccounts, RestoreSelection, ToggleSelectAll, AddAccount, RemoveSelectedAccounts } from './Accounts.js';
import { RefreshConfigs, AddConfig, EditConfig, RemoveConfig, AutoSizeConfigColumns } from './Configs.js';
import { InitLaunchPanel, LoadHeightMap, RestoreLaunchPanel, ResizeForCurrentOption, StartCounterLoop } from './Launch.js';
import { InitSettingsPanel, RestoreSettingsPanel } from './Settings.js';
import { InitThemePicker, LoadThemes } from './Themes.js';
import { InitTours, StartTour } from './Tours.js';
import { ShowLaunchError, ShowStatus } from './Status.js';
import { InitTooltips } from './Tooltip.js';

function WireButtons() {
    ById('AddAccountBtn').addEventListener('click', () => AddAccount().catch(ReportError));
    ById('RemoveAccountBtn').addEventListener('click', () => RemoveSelectedAccounts().catch(ReportError));
    ById('SelectAllBtn').addEventListener('click', ToggleSelectAll);
    ById('AddConfigBtn').addEventListener('click', () => AddConfig().catch(ReportError));
    ById('EditConfigBtn').addEventListener('click', () => EditConfig().catch(ReportError));
    ById('RemoveConfigBtn').addEventListener('click', () => RemoveConfig().catch(ReportError));
}

async function Boot() {
    InitTooltips();
    WireButtons();
    InitLaunchPanel();
    InitSettingsPanel();
    InitThemePicker();
    await WaitForApi('GetSettings');

    On('AccountsChanged', () => RefreshAccounts().then(() => RestoreSelection([...State.Selected])).catch(ReportError));
    On('ConfigsChanged', () => RefreshConfigs(true).catch(ReportError));
    On('ShowMessage', Message => (Message && Message.Error ? ShowLaunchError : ShowStatus)(String(Message && Message.Text), true));

    const Step = async (Name, Fn) => {
        try { await Fn(); } catch (Error) { ReportError(Error); ShowLaunchError(`${Name} failed: ${Error.message || Error}`); }
    };
    let Settings = {};
    await Step('Settings', async () => { Settings = await Api.GetSettings(); });
    await Step('Accounts', async () => { await RefreshAccounts(); RestoreSelection(Settings.SelectedAccounts); });
    await Step('Configs', async () => { State.SelectedConfig = Settings.SelectedConfig || ''; await RefreshConfigs(true); });
    await Step('Themes', async () => { await LoadThemes(); await LoadHeightMap(); });
    await Step('Restore', async () => {
        RestoreSettingsPanel(Settings);
        RestoreLaunchPanel(Settings);
        InitTours(Settings.ToursDone);
        const Info = await Api.GetAppInfo();
        ById('AppVersion').textContent = `${Info.Name} ${Info.Label}`;
        if (Info.CodeName) ById('AppVersion').title = `Code name: ${Info.CodeName}`;  // themed tooltip (Tooltip.js)
    });
    StartCounterLoop();
    // Everything is loaded: let the native start-up spinner (App/Splash.py) fade out.
    Api.BootFinished().catch(() => {});
    // Final resize + column sizing once the layout has settled.
    setTimeout(() => { ResizeForCurrentOption(); AutoSizeConfigColumns(); }, 300);
    if (!Settings.TutorialSeen) setTimeout(() => StartTour('basics'), 900);
}

Boot().catch(Error => {
    ReportError(Error);
    ShowLaunchError('Start-up failed: ' + (Error.message || Error));
    Api.BootFinished().catch(() => {});  // never leave the spinner covering an error
});
