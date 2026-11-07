// Config wizard window entry point (Wizard.html): add or edit one saved launch config.
//
// Window sizing follows Test1's wizard (the user's tuned original):
//   * the window opens at this theme's HeightMap.json "WizardWindow" height for the method,
//   * changing method snaps straight to that height,
//   * anything else (filters, help panel, drop-downs, clicks) re-measures: body height with any
//     drop-down closed + ExtraPadding, plus only the part of an open drop-down that would be cut off.
// The CSS keeps the same box model as Test1's wizard, so its heights apply 1:1.

import { Api, WaitForApi, ReportError } from './Bridge.js';
import { ById } from './Dom.js';
import { InitSelect, SetSelectValue, GetSelectValue } from './Select.js';
import { CreateLaunchForm, FilterMethods } from './LaunchForm.js';
import { InitTooltips } from './Tooltip.js';

let SizeMap = { Home: 287, ExtraPadding: 20 };
let InitDone = false;

function FitToContent() {
    setTimeout(() => {
        const Body = document.body;
        const OpenSelect = document.querySelector('.CustomSelect.Open');
        if (OpenSelect) OpenSelect.classList.remove('Open');
        Body.style.overflow = 'auto';
        let Needed = Body.scrollHeight + SizeMap.ExtraPadding;
        Body.style.overflow = 'hidden';
        if (OpenSelect) {
            OpenSelect.classList.add('Open');
            const Clipped = OpenSelect.querySelector('.CustomSelectOptions').getBoundingClientRect().bottom - window.innerHeight;
            if (Clipped > 0) Needed += Clipped + 5;
        }
        Api.ResizeWizard(Needed).catch(() => {});
    }, 10);
}

const CurrentMethod = () => GetSelectValue(ById('MethodSelect'));

// Only the filter methods re-measure when their boxes are drawn (Test1: InitFilters -> WizResize).
const Form = CreateLaunchForm(ById('DynamicFields'), {
    Wizard: true,
    OnResize: () => { if (FilterMethods.includes(CurrentMethod())) FitToContent(); },
});

InitSelect(ById('MethodSelect'), Method => {
    Form.Render(Method, {});
    if (InitDone) Api.ResizeWizard(SizeMap[Method] || SizeMap.Home).catch(() => {});
});
// Opening/closing any drop-down, and clicks elsewhere, re-measure. Picking a method does not
// (it snaps to the map above), so clicks inside the method list are skipped.
document.addEventListener('click', Event => {
    if (Event.target.closest('#MethodSelect .CustomSelectOptions')) return;
    FitToContent();
}, true);
ById('WizHelpBtn').addEventListener('click', () => { ById('WizHelp').hidden = !ById('WizHelp').hidden; FitToContent(); });
ById('CancelBtn').addEventListener('click', () => Api.WizardCancel().catch(ReportError));
ById('ConfirmBtn').addEventListener('click', async () => {
    const Name = ById('ConfigName').value.trim();
    if (!Name) { ById('ErrorMsg').textContent = 'Name is required.'; return; }
    const Result = await Api.WizardConfirm(Name, CurrentMethod(), Form.GetParams());
    if (Result && Result.Error) ById('ErrorMsg').textContent = Result.Error;
});

async function Boot() {
    InitTooltips();
    await WaitForApi('GetWizardData');
    const HeightMap = await Api.GetHeightMap().catch(() => null);
    if (HeightMap && HeightMap.WizardWindow) SizeMap = HeightMap.WizardWindow;
    const Data = await Api.GetWizardData();
    const Config = Data && Data.EditData;
    if (Config) {
        ById('WizardTitle').textContent = 'EDIT LAUNCH CONFIG';
        ById('ConfigName').value = Config.Name;
        SetSelectValue(ById('MethodSelect'), Config.Method);
        Form.Render(Config.Method, Config.Params);
    } else {
        Form.Render('Home', {});
    }
    InitDone = true;
}

Boot().catch(ReportError);
