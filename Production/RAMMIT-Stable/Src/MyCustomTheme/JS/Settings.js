// SETTINGS panel: launcher, Roblox channel, instance limit, launch delay, fold-away toggle.
// Themes have their own module (Themes.js).

import { Api, ReportError } from './Bridge.js';
import { ById, DigitsOnly } from './Dom.js';
import { InitSelect, SetSelectValue } from './Select.js';
import { State } from './State.js';
import { ShowStatus } from './Status.js';
import { UpdateCounter } from './Launch.js';

export function InitSettingsPanel() {
    InitSelect(ById('LauncherSelect'), Value => SaveSetting('Launcher', Value));
    ById('SaveChannelBtn').addEventListener('click', SaveChannel);
    ById('ResetChannelBtn').addEventListener('click', ResetChannel);
    ById('SaveSettingsBtn').addEventListener('click', SaveNumbers);
    ById('SettingsToggle').addEventListener('click', ToggleSettings);
    ['MaxInstances', 'LaunchDelay'].forEach(Id => ById(Id).addEventListener('input', () => DigitsOnly(ById(Id))));
}

export function RestoreSettingsPanel(Settings) {
    SetSelectValue(ById('LauncherSelect'), Settings.Launcher);
    ById('ChannelEntry').value = Settings.Channel || '';
    ById('MaxInstances').value = Settings.MaxInstances;
    ById('LaunchDelay').value = Settings.LaunchDelay;
    State.SettingsCollapsed = !!Settings.SettingsCollapsed;
    ApplySettingsCollapse();
}

async function SaveSetting(Key, Value) {
    const Result = await Api.UpdateSetting(Key, Value);
    if (Result && Result.Error) ShowStatus(Result.Error, false);
}

async function SaveChannel() {
    const Result = await Api.SaveChannel(ById('ChannelEntry').value.trim());
    ShowStatus(Result.Ok ? 'Channel updated' : Result.Error, !!Result.Ok);
}

async function ResetChannel() {
    ById('ChannelEntry').value = await Api.GetChannel();
}

async function SaveNumbers() {
    const MaxInstances = parseInt(ById('MaxInstances').value, 10);
    const LaunchDelay = parseInt(ById('LaunchDelay').value, 10);
    if (isNaN(MaxInstances) || MaxInstances < 1 || MaxInstances > 100) { ShowStatus('Max Instances must be 1 to 100', false); return; }
    if (isNaN(LaunchDelay) || LaunchDelay < 0 || LaunchDelay > 300) { ShowStatus('Launch Delay must be 0 to 300', false); return; }
    const Result = await Api.UpdateSettings({ MaxInstances, LaunchDelay });
    if (Result && Result.Error) { ShowStatus(Result.Error, false); return; }
    ShowStatus('Settings saved', true);
    UpdateCounter();
}

export function ToggleSettings() {
    State.SettingsCollapsed = !State.SettingsCollapsed;
    ApplySettingsCollapse();
    Api.UpdateSetting('SettingsCollapsed', State.SettingsCollapsed).catch(ReportError);
}

function ApplySettingsCollapse() {
    ById('SettingsPanel').classList.toggle('Collapsed', State.SettingsCollapsed);
    ById('SettingsToggle').classList.toggle('Flipped', State.SettingsCollapsed);
}
