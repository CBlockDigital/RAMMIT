// LAUNCH CONFIGS panel: saved launch setups. Adding/editing happens in the wizard window
// (Wizard.html); the backend fires ConfigsChanged when it saves one.

import { Api, ReportError } from './Bridge.js';
import { El, ById } from './Dom.js';
import { State } from './State.js';
import { ShowLaunchError } from './Status.js';

const MaxNameLength = 15;
let LastJson = '';

function Describe(Params) {
    const P = Params || {};
    const Parts = [];
    if (P.Url) Parts.push(P.Url);
    if (P.PlaceId) Parts.push(P.PlaceId);
    if (P.JobId) Parts.push(P.JobId);
    if (P.PlayerMode && P.PlayerMode !== 'any') Parts.push(P.PlayerMode);
    if (P.MinPlayers) Parts.push('min:' + P.MinPlayers);
    if (P.MaxPlayers) Parts.push('max:' + P.MaxPlayers);
    if (P.PingMode && P.PingMode !== 'any') Parts.push(P.PingMode + ' ping');
    return Parts.join(', ');
}

export async function RefreshConfigs(Force) {
    const Configs = await Api.GetConfigs();
    const Json = JSON.stringify(Configs);
    if (!Force && Json === LastJson) return;
    LastJson = Json;
    State.Configs = Configs;
    if (State.SelectedConfig && !Configs.some(C => C.Name === State.SelectedConfig)) State.SelectedConfig = '';
    ById('ConfigList').replaceChildren(...Configs.map(Config => {
        const Params = Describe(Config.Params);
        const Short = Config.Name.length > MaxNameLength ? Config.Name.slice(0, MaxNameLength - 1) + '...' : Config.Name;
        const Row = El('li', { Class: 'ConfigItem ListItem' },
            El('span', { Class: 'ColName', Text: Short, Title: Config.Name }),
            El('span', { Class: 'ColMethod', Text: Config.Method }),
            El('span', { Class: 'ColParams', Text: Params, Title: Params }));
        Row.addEventListener('click', () => SelectConfig(Config.Name, true));
        Row.addEventListener('dblclick', () => { SelectConfig(Config.Name, false); EditConfig(); });
        return Row;
    }));
    ApplyConfigSelection();
    AutoSizeConfigColumns();
}

function ApplyConfigSelection() {
    ById('ConfigList').querySelectorAll('.ListItem').forEach((Row, Index) => {
        Row.classList.toggle('Selected', State.Configs[Index] && State.Configs[Index].Name === State.SelectedConfig);
    });
}

// Toggle = clicking the selected row again clears it.
export function SelectConfig(Name, Toggle) {
    State.SelectedConfig = (Toggle && State.SelectedConfig === Name) ? '' : Name;
    ApplyConfigSelection();
    Api.UpdateSetting('SelectedConfig', State.SelectedConfig).catch(ReportError);
}

export async function AddConfig() {
    const Result = await Api.OpenConfigWizard('');
    if (Result && Result.Error) ShowLaunchError(Result.Error);
}

export async function EditConfig() {
    if (!State.SelectedConfig) return;
    const Result = await Api.OpenConfigWizard(State.SelectedConfig);
    if (Result && Result.Error) ShowLaunchError(Result.Error);
}

export async function RemoveConfig() {
    if (!State.SelectedConfig) return;
    await Api.RemoveConfig(State.SelectedConfig);
    State.SelectedConfig = '';
    await RefreshConfigs(true);
}

// Size the Name and Method columns to their longest entry.
export function AutoSizeConfigColumns() {
    const List = ById('ConfigList');
    const Wrapper = List.closest('.ListWrapper') || List.parentElement;
    const Rows = List.querySelectorAll('.ConfigItem');
    if (!Rows.length) return;
    const Ctx = document.createElement('canvas').getContext('2d');
    let NameWidth = 0, MethodWidth = 0;
    Ctx.font = '14px Segoe UI';
    Rows.forEach(Row => {
        NameWidth = Math.max(NameWidth, Ctx.measureText(Row.children[0].textContent).width);
        MethodWidth = Math.max(MethodWidth, Ctx.measureText(Row.children[1].textContent).width);
    });
    Ctx.font = '600 10px Segoe UI';
    const Header = document.querySelector('.ConfigListHeader');
    if (Header) {
        NameWidth = Math.max(NameWidth, Ctx.measureText(Header.children[0].textContent).width);
        MethodWidth = Math.max(MethodWidth, Ctx.measureText(Header.children[1].textContent).width);
    }
    Wrapper.style.setProperty('--ColNameWidth', (NameWidth + 20) + 'px');
    Wrapper.style.setProperty('--ColMethodWidth', (MethodWidth + 20) + 'px');
}
