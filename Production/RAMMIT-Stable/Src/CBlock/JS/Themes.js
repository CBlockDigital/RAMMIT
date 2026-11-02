// Theme picker. A theme is a whole UI folder in Src/ (App/Themes.py); the backend serves the
// chosen folder, so switching = save the setting and reload this window.

import { Api, ReportError } from './Bridge.js';
import { ById } from './Dom.js';
import { InitSelect, SetSelectOptions, SetSelectValue } from './Select.js';
import { ShowStatus } from './Status.js';

let LastInfo = null;
let StartupAsked = false;

export function InitThemePicker() {
    // Re-scan Src/ every time the list opens, so a newly copied theme folder shows up straight away.
    InitSelect(ById('ThemeSelect'), ThemeId => ChooseTheme(ThemeId).catch(ReportError), () => LoadThemes().catch(ReportError));
    ById('ReloadThemesBtn').addEventListener('click', () => window.location.reload());
    ById('OpenThemesBtn').addEventListener('click', async () => {
        const Result = await Api.OpenThemesFolder();
        if (Result && Result.Error) ShowStatus(Result.Error, false);
    });
}

export async function LoadThemes() {
    const Info = await Api.GetThemes();
    LastInfo = Info;
    const Sel = ById('ThemeSelect');
    SetSelectOptions(Sel, Info.Themes.map(Theme => ({
        Value: Theme.Id, Label: Theme.Name, Swatch: Theme.Swatch,
        Title: `${Theme.Name} by ${Theme.Author} (Src\\${Theme.Id})` + (Theme.Description ? ' - ' + Theme.Description : ''),
    })));
    if (!SetSelectValue(Sel, Info.Active)) SetSelectValue(Sel, Info.Served);
    // Long names are cut with "..." (they never wrap, so the height map holds); hover shows all of it.
    Sel.querySelector('.CustomSelectTrigger').title = Sel.querySelector('.CustomSelectText').textContent;
    // Square swatch as tall as the picker: its width (and the list's swatch column) = the button's
    // natural height, so the settings row keeps the height HeightMap.json was tuned for.
    ById('ThemePicker').style.setProperty('--ThemeSwatchSize', getComputedStyle(Sel.querySelector('.CustomSelectTrigger')).height);  // exact, not rounded like offsetHeight
    const Note = ById('ThemeWarning');
    const NoteText = (Info.Warnings || []).join(' ');
    if (Note.textContent !== NoteText) {
        Note.textContent = NoteText;
        document.dispatchEvent(new Event('ThemeNoteChanged'));  // Launch.js resizes the window to fit it
    }
    // The chosen theme doesn't list this RAMMIT version, so Dark is showing instead: ask once per start.
    // Not awaited - the start-up spinner must not wait for an answer.
    if (Info.Blocked && !StartupAsked) {
        StartupAsked = true;
        AskAboutBlockedTheme(Info).catch(ReportError);
    }
    return Info;
}

// Window height (HeightMap units) the note line under the Theme list adds, so a note never pushes the
// bottom of the Settings card out of the window. 0 when there is no note or Settings is collapsed.
export function ThemeNoteExtra() {
    const Note = ById('ThemeWarning');
    const Below = Note.nextElementSibling;
    if (!Note.textContent || !Below) return 0;
    const Shown = Below.getBoundingClientRect().top;
    Note.style.display = 'none';
    const Hidden = Below.getBoundingClientRect().top;
    Note.style.display = '';
    // Measured on screen, where the page is zoomed (.Container); HeightMap values are before that zoom.
    const Zoom = parseFloat(getComputedStyle(Note.closest('.Container') || document.body).zoom) || 1;
    return Math.ceil((Shown - Hidden) / Zoom);
}

async function ChooseTheme(ThemeId) {
    const Theme = LastInfo && LastInfo.Themes.find(T => T.Id === ThemeId);
    if (Theme && Theme.NeedsOk) {
        const Answer = await AskThemeVersion(Theme, LastInfo.AppVersion, false);
        if (!Answer) { SetSelectValue(ById('ThemeSelect'), LastInfo.Active); return; }
        const Allowed = await Api.AllowThemeVersion(ThemeId, Answer.Remember);
        if (Allowed && Allowed.Error) { ShowStatus(Allowed.Error, false); SetSelectValue(ById('ThemeSelect'), LastInfo.Active); return; }
    }
    const Result = await Api.UpdateSetting('Theme', ThemeId);
    if (Result && Result.Error) { ShowStatus(Result.Error, false); return; }
    window.location.reload();
}

async function AskAboutBlockedTheme(Info) {
    const Answer = await AskThemeVersion(Info.Blocked, Info.AppVersion, true);
    if (Answer) {
        const Allowed = await Api.AllowThemeVersion(Info.Blocked.Id, Answer.Remember);
        if (Allowed && Allowed.Error) { ShowStatus(Allowed.Error, false); return; }
        window.location.reload();
        return;
    }
    // Stay on Dark: make it the saved choice, so the question doesn't come back at every start.
    const Result = await Api.UpdateSetting('Theme', Info.Served);
    if (Result && Result.Error) ShowStatus(Result.Error, false);
    await LoadThemes();
}

// Resolves to {Remember} for "use it anyway", or null for Cancel / Stay on Dark / Escape.
function AskThemeVersion(Theme, AppVersion, AtStartup) {
    const Modal = ById('ThemeVersionModal');
    const Supported = (Theme.Supported || []).join(', ');
    ById('ThemeVersionText').textContent = AtStartup
        ? `"${Theme.Name}" supports RAMMIT ${Supported}, but this is RAMMIT ${AppVersion}, so RAMMIT opened in Dark for now. The theme may look or work wrong.`
        : `"${Theme.Name}" supports RAMMIT ${Supported}, but this is RAMMIT ${AppVersion}. It may look or work wrong.`;
    const Line = String(AppVersion).split('.').slice(0, 2).join('.');  // "1.0" covers every 1.0.x
    ById('ThemeVersionHint').textContent = 'Downloaded it? Check where it was published for an updated version. '
        + `Made it yourself? Check it still works fine, then add "${Line}" to "SupportedVersions" in its Theme.json.`;
    ById('ThemeVersionCancel').textContent = AtStartup ? 'STAY ON DARK' : 'CANCEL';
    ById('ThemeVersionRemember').checked = false;
    Modal.hidden = false;
    return new Promise(Resolve => {
        const Listening = new AbortController();
        const Finish = Answer => { Listening.abort(); Modal.hidden = true; Resolve(Answer); };
        ById('ThemeVersionUse').addEventListener('click', () => Finish({ Remember: ById('ThemeVersionRemember').checked }), { signal: Listening.signal });
        ById('ThemeVersionCancel').addEventListener('click', () => Finish(null), { signal: Listening.signal });
        document.addEventListener('keydown', Event => { if (Event.key === 'Escape') Finish(null); }, { signal: Listening.signal });
    });
}
