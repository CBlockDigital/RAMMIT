// The two status lines: under the launch panel (LaunchStatus) and under Settings (StatusMessage).
import { ById } from './Dom.js';

let LaunchTimer = null;
let SettingsTimer = null;

export function SetLaunchStatus(Text) {
    clearTimeout(LaunchTimer);
    const Line = ById('LaunchStatus');
    Line.classList.remove('Error');
    Line.textContent = Text;
}

export function ShowLaunchError(Text) {
    clearTimeout(LaunchTimer);
    const Line = ById('LaunchStatus');
    Line.textContent = Text;
    Line.classList.add('Error');
    LaunchTimer = setTimeout(() => { Line.textContent = ''; Line.classList.remove('Error'); }, 8000);
}

export function ShowLaunchDone(Text) {
    SetLaunchStatus(Text);
    LaunchTimer = setTimeout(() => { ById('LaunchStatus').textContent = ''; }, 6000);
}

export function ShowStatus(Text, Success) {
    clearTimeout(SettingsTimer);
    const Line = ById('StatusMessage');
    Line.textContent = Text;
    Line.className = 'StatusMessage ' + (Success ? 'Success' : 'Error');
    SettingsTimer = setTimeout(() => { Line.textContent = ''; Line.className = 'StatusMessage'; }, 3500);
}
