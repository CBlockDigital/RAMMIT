// End-to-end UI tests: real HTML/JS/CSS + real Python backend (Tests/UiHarness.py) in headless Chrome.
// Usage: node Tests/TestUi.mjs <PuppeteerCoreDir> <ChromeExe> <ScratchDir> [ScreenshotDir]
import { createRequire } from 'module';
import { spawn } from 'child_process';
import { cpSync, mkdirSync, rmSync, writeFileSync } from 'fs';
import http from 'http';
import path from 'path';
import { fileURLToPath } from 'url';

const [PuppeteerDir, ChromeExe, ScratchDir, ShotDir] = process.argv.slice(2);
const Puppeteer = createRequire(path.join(PuppeteerDir, 'x.js'))('puppeteer-core');
const ProjectDir = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
if (ShotDir) mkdirSync(ShotDir, { recursive: true });

const Wait = Ms => new Promise(R => setTimeout(R, Ms));
const Results = [];
const Errors = [];
const Check = (Name, Ok, Detail = '') => { Results.push({ Name, Ok }); console.log((Ok ? 'PASS ' : 'FAIL ') + Name + (Detail ? ' -- ' + Detail : '')); };

// ---------------------------------------------------------------- start the backend harness
const Harness = spawn('python', [path.join(ProjectDir, 'Tests', 'UiHarness.py'), ScratchDir], { stdio: ['ignore', 'pipe', 'inherit'] });
const Port = await new Promise((Resolve, Reject) => {
    Harness.stdout.on('data', D => { const M = String(D).match(/PORT (\d+)/); if (M) Resolve(Number(M[1])); });
    Harness.on('exit', Code => Reject(new Error('harness exited ' + Code)));
});
const Base = `http://127.0.0.1:${Port}`;

function RawGet(UrlPath, Host = `127.0.0.1:${Port}`, Method = 'GET') {
    return new Promise(Resolve => {
        const Req = http.request({ host: '127.0.0.1', port: Port, path: UrlPath, method: Method, headers: { Host } }, Res => {
            let Body = ''; Res.on('data', C => Body += C); Res.on('end', () => Resolve({ Status: Res.statusCode, Headers: Res.headers, Body }));
        });
        Req.on('error', E => Resolve({ Status: 0, Body: String(E) }));
        Req.end();
    });
}
const Hook = async (Name, Body) => (await fetch(Base + '/__TestHook/' + Name, Body ? { method: 'POST', body: JSON.stringify(Body) } : {})).json();
const CallApi = async (Name, ...Args) => (await fetch(Base + '/__TestApi/' + Name, { method: 'POST', body: JSON.stringify(Args) })).json();

// Stands in for pywebview's injected bridge: window.pywebview.api.X(...) -> POST /__TestApi/X
const Shim = `
    window.pywebview = { api: new Proxy({}, { get: (_T, Name) => (...Args) =>
        fetch('/__TestApi/' + String(Name), { method: 'POST', body: JSON.stringify(Args) }).then(R => R.json()) }) };
    // Python->JS events only ever go to the main window (Api._Notify), so only Index.html polls.
    if (location.pathname.endsWith('Index.html')) setInterval(async () => {
        try {
            const Events = await (await fetch('/__TestHook/Events')).json();
            Events.forEach(Script => { const M = Script.match(/RammitEvents\\.(\\w+)\\((.*)\\)$/); if (M && window.RammitEvents) window.RammitEvents[M[1]](JSON.parse(M[2])); });
        } catch (_) {}
    }, 250);`;

const Browser = await Puppeteer.launch({ executablePath: ChromeExe, headless: 'new' });
const Page = await Browser.newPage();
await Page.setViewport({ width: 765, height: 757, deviceScaleFactor: 1 });
await Page.evaluateOnNewDocument(Shim);
Page.on('pageerror', E => Errors.push('pageerror :: ' + E.message));
Page.on('console', M => { if (M.type() === 'error') Errors.push('console :: ' + M.text()); });
Page.on('response', R => { if (R.status() >= 400) Errors.push('http ' + R.status() + ' ' + R.url()); });
Page.on('dialog', D => D.accept());

const Text = Sel => Page.$eval(Sel, E => E.innerText.trim()).catch(() => null);
const Count = Sel => Page.$$eval(Sel, E => E.length);
// Polls instead of a fixed wait: on a busy PC the page finishes booting (and resizing) later than usual.
const WaitFor = async (Test, Ms = 5000) => { for (const End = Date.now() + Ms; Date.now() < End; await Wait(100)) if (await Test()) return true; return !!(await Test()); };
const Open = async (Page2 = 'Index.html') => { await Page.goto(`${Base}/HTML/${Page2}`, { waitUntil: 'load' }); await Wait(700); };
const Pick = async (Id, Value) => {
    await Page.click(`#${Id} .CustomSelectTrigger`); await Wait(200);
    await Page.evaluate((Id2, V) => [...document.querySelectorAll(`#${Id2} .CustomSelectOption`)].find(O => O.dataset.value === V).click(), Id, Value);
    await Wait(350);
};
const SetValue = async (Target, Sel, Value) => { await Target.$eval(Sel, E => { E.value = ''; E.focus(); }); await Target.type(Sel, Value); };
const Shot = async Name => { if (ShotDir) await Page.screenshot({ path: path.join(ShotDir, Name + '.png') }); };
const WaitLaunchDone = async () => { for (let I = 0; I < 60; I++) { const T = await Text('#LaunchStatus'); if (T && T.startsWith('Launched')) return T; await Wait(150); } return Text('#LaunchStatus'); };
const Bg = () => Page.evaluate(() => getComputedStyle(document.body).backgroundColor);
const RowClick = async (Index, Mods = []) => {
    for (const M of Mods) await Page.keyboard.down(M);
    await Page.click(`#AccountList .ListItem:nth-child(${Index + 1}) .AcctLabel`);
    for (const M of Mods) await Page.keyboard.up(M);
    await Wait(150);
};

try {
    // ------------------------------------------------------------ server hardening
    const Html = await RawGet('/HTML/Index.html');
    Check('server: page served', Html.Status === 200);
    Check('server: CSP header on HTML', /default-src 'none'/.test(Html.Headers['content-security-policy'] || ''));
    Check('server: nosniff + no-store', Html.Headers['x-content-type-options'] === 'nosniff' && Html.Headers['cache-control'] === 'no-store');
    Check('server: no directory listing', (await RawGet('/HTML/')).Status === 404 && (await RawGet('/')).Status === 404);
    Check('server: ../ traversal blocked', (await RawGet('/../Config/Accounts.json')).Status === 404 && (await RawGet('/%2e%2e/Config/Accounts.json')).Status === 404);
    Check('server: other theme folders not reachable', (await RawGet('/../Light/Theme.json')).Status === 404);
    Check('server: disallowed file types blocked', (await RawGet('/Theme.json')).Status === 404 && (await RawGet('/HeightMap.json')).Status === 404);
    Check('server: foreign Host header rejected (DNS rebinding)', (await RawGet('/HTML/Index.html', 'evil.example:80')).Status === 403);
    Check('server: PUT not allowed', (await RawGet('/HTML/Index.html', undefined, 'PUT')).Status >= 400);

    // ------------------------------------------------------------ start-up + migration
    await Open();
    await Shot('01-Dark');
    Check('accounts listed', await Count('#AccountList .ListItem') === 4);
    Check('account label', (await Text('#AccountList .ListItem:nth-child(1) .AcctLabel')) === 'Nova (@NovaBuilds)');
    const State0 = await Hook('State');
    Check('Accounts.json migrated to DPAPI', State0.AccountsFile.includes('dpapi1:') && !State0.AccountsFile.includes('FakeCookie'));
    Check('legacy selected_account restored', (await Text('#SelectionCount')) === '(1 SELECTED)');
    Check('legacy theme "dark" -> Dark', (await Text('#ThemeSelect .CustomSelectText')) === 'Dark');
    Check('saved Game URL restored', await Page.$eval('#UrlInput', E => E.value) === 'https://www.roblox.com/games/920587237');
    Check('legacy selected_config restored', (await Text('#ConfigList .Selected .ColName')) === 'Grind Server');
    Check('max instances restored', await Page.$eval('#MaxInstances', E => E.value) === '3');
    Check('multi instance method dropdown removed', await Page.$('#MultiMethodSelect') === null && !(await Text('.SettingsGrid')).includes('Multi Instance'));
    const SettingsFile = (await CallApi('GetSettings'));
    Check('multi_method not in settings', !('multi_method' in SettingsFile) && !('MultiMethod' in SettingsFile));
    Check('version and channel shown', /^RAMMIT v\d+\.\d+\.\d+ · (Dev|Stable)/.test(await Text('#AppVersion')));
    Check('counter shows limit', (await Text('#CounterLabel')) === 'RUNNING: 0 / 3');

    // ------------------------------------------------------------ XSS
    const XssRow = await Page.$$eval('#ConfigList .ListItem', Rows => Rows.map(R => R.innerHTML).join(''));
    Check('config name rendered as text (no XSS)', !(await Page.$('#ConfigList img')) && !(await Page.$('#ConfigList b')) && XssRow.includes('&lt;img'));

    // ------------------------------------------------------------ selection
    await RowClick(0);
    Check('click selects only that row', (await Text('#SelectionCount')) === '(1 SELECTED)' && await Count('#AccountList .Selected') === 1);
    await RowClick(2, ['Shift']);
    Check('shift+click selects range', await Count('#AccountList .Selected') === 3);
    await RowClick(1, ['Control']);
    Check('ctrl+click toggles one', await Count('#AccountList .Selected') === 2);
    await Page.click('#SelectAllBtn'); await Wait(150);
    Check('select all', await Count('#AccountList .Selected') === 4 && (await Text('#SelectAllBtn')) === 'CLEAR');
    Check('launch button counts', (await Text('#LaunchBtn')) === 'LAUNCH 4 SELECTED');
    await Page.click('#SelectAllBtn'); await Wait(150);
    Check('clear all', await Count('#AccountList .Selected') === 0);
    Check('selection persisted by username', await WaitFor(async () => Array.isArray((await CallApi('GetSettings')).SelectedAccounts) && (await CallApi('GetSettings')).SelectedAccounts.length === 0));

    // ------------------------------------------------------------ launching
    await Pick('LaunchOptionSelect', 'Home');
    await RowClick(0); await RowClick(1, ['Control']);
    await Page.click('#LaunchBtn');
    const Done1 = await WaitLaunchDone();
    Check('batch launch of 2', Done1 === 'Launched 2/2', Done1);
    Check('rows show ok marks', await Count('#AccountList .AcctStatus.Ok') === 2);
    let St = await Hook('State');
    Check('two clients started', St.Launches.length === 2 && St.Launches.every(U => U.startsWith('roblox-player:1+launchmode:play+gameinfo:FAKETICKET0123+')));

    await Pick('LaunchOptionSelect', 'Place ID + Job ID');
    await Page.type('#PlaceIdInput', '606849621');
    await Page.type('#JobIdInput', 'abc+launchmode:edit');
    await Page.click('#LaunchBtn'); await Wait(400);
    Check('job id injection rejected', /Invalid Job ID/.test(await Text('#LaunchStatus')), await Text('#LaunchStatus'));

    await Pick('LaunchOptionSelect', 'Game URL');
    await Page.type('#UrlInput', 'https://www.roblox.com/games/920587237/Adopt-Me');
    await Pick('PlayerModeSelect', 'smallest');
    await Page.click('#AccountList .ListItem:nth-child(3) .AcctLabel'); await Wait(150);
    await Page.click('#LaunchBtn');
    const Done2 = await WaitLaunchDone();
    St = await Hook('State');
    Check('server filter picks smallest non-full server', Done2 === 'Launched 1/1' && St.Launches.at(-1).includes('placeId=920587237') && St.Launches.at(-1).includes('gameId=11111111-1111-1111-1111-111111111111'), Done2);
    Check('player filter params saved', (await CallApi('GetSettings')).LaunchParams.PlayerMode === 'smallest');

    await Page.click('#SelectAllBtn'); await Wait(150);
    await Page.click('#LaunchBtn');
    const Done3 = await WaitLaunchDone();
    Check('instance limit stops the batch', /Instance limit reached/.test(Done3) && Done3.startsWith('Launched 0/4'), Done3);
    Check('counter updated', (await Text('#CounterLabel')) === 'RUNNING: 3 / 3');
    await Shot('02-AfterLaunches');

    // ------------------------------------------------------------ settings
    await SetValue(Page, '#MaxInstances', '0');
    await Page.click('#SaveSettingsBtn'); await Wait(200);
    Check('max instances 0 rejected', /1 to 100/.test(await Text('#StatusMessage')), await Text('#StatusMessage') + ' / ' + await Page.$eval('#MaxInstances', E => E.value));
    await SetValue(Page, '#MaxInstances', '10');
    await Page.click('#SaveSettingsBtn');
    Check('settings saved', await WaitFor(async () => (await Text('#StatusMessage')) === 'Settings saved' && (await CallApi('GetSettings')).MaxInstances === 10));
    Check('backend rejects bad types', !!(await CallApi('UpdateSetting', 'MaxInstances', 'lots')).Error && !!(await CallApi('UpdateSetting', 'Bogus', 1)).Error);
    await SetValue(Page, '#ChannelEntry', 'bad channel!');
    await Page.click('#SaveChannelBtn'); await Wait(250);
    Check('invalid channel rejected', /letters, numbers/.test(await Text('#StatusMessage')));
    await SetValue(Page, '#ChannelEntry', 'zbeta');
    await Page.click('#SaveChannelBtn'); await Wait(250);
    Check('valid channel saved', (await Text('#StatusMessage')) === 'Channel updated', await Text('#StatusMessage'));
    await Page.click('#SettingsToggle');
    Check('settings fold away', await WaitFor(async () => (await Page.$eval('#SettingsPanel', E => E.classList.contains('Collapsed'))) && (await CallApi('GetSettings')).SettingsCollapsed === true));
    await Page.click('#SettingsToggle'); await Wait(450);

    // ------------------------------------------------------------ configs + wizard
    await Pick('LaunchOptionSelect', 'Config');
    if (!(await Page.$('#ConfigList .ListItem:nth-child(1).Selected'))) { await Page.click('#ConfigList .ListItem:nth-child(1)'); await Wait(150); }
    await RowClick(3);
    await CallApi('UpdateSettings', { MaxInstances: 20 });
    await Page.click('#LaunchBtn');
    const Done4 = await WaitLaunchDone();
    St = await Hook('State');
    Check('launch via saved config', Done4 === 'Launched 1/1' && St.Launches.at(-1).includes('placeId=2753915549') && St.Launches.at(-1).includes('gameId=11111111'), Done4 + ' ' + St.Launches.at(-1));

    const Wiz = await Browser.newPage();
    await Wiz.setViewport({ width: 400, height: 640 });
    await Wiz.evaluateOnNewDocument(Shim);
    Wiz.on('pageerror', E => Errors.push('wizard pageerror :: ' + E.message));
    await CallApi('OpenConfigWizard', '');
    await Wiz.goto(`${Base}/HTML/Wizard.html`, { waitUntil: 'load' }); await Wait(500);
    await Wiz.click('#ConfirmBtn'); await Wait(200);
    Check('wizard requires a name', (await Wiz.$eval('#ErrorMsg', E => E.textContent)) === 'Name is required.');
    await Wiz.type('#ConfigName', 'Trade Range');
    await Wiz.click('#MethodSelect .CustomSelectTrigger'); await Wait(150);
    await Wiz.evaluate(() => [...document.querySelectorAll('#MethodSelect .CustomSelectOption')].find(O => O.dataset.value === 'Place ID').click()); await Wait(250);
    await Wiz.type('#PlaceIdInput', '920587237');
    await Wiz.click('#PlayerModeSelect .CustomSelectTrigger'); await Wait(150);
    await Wiz.evaluate(() => [...document.querySelectorAll('#PlayerModeSelect .CustomSelectOption')].find(O => O.dataset.value === 'range').click()); await Wait(600);
    await Wiz.type('#MinPlayersInput', '5'); await Wiz.type('#MaxPlayersInput', '99');
    Check('wizard clamps max players to game cap', (await Wiz.$eval('#MaxPlayersInput', E => E.value)) === '19');
    await Wiz.click('#ConfirmBtn'); await Wait(900);
    const Saved = (await CallApi('GetConfigs')).find(C => C.Name === 'Trade Range');
    Check('wizard saved config', Saved && Saved.Method === 'Place ID' && Saved.Params.PlayerMode === 'range' && Saved.Params.MaxPlayers === '19');
    Check('main list updated by ConfigsChanged event', (await Page.$$eval('#ConfigList .ColName', E => E.map(X => X.title))).includes('Trade Range'));
    await CallApi('OpenConfigWizard', 'Trade Range');
    await Wiz.goto(`${Base}/HTML/Wizard.html`, { waitUntil: 'load' }); await Wait(500);
    Check('wizard edit prefill', (await Wiz.$eval('#WizardTitle', E => E.textContent)) === 'EDIT LAUNCH CONFIG' && (await Wiz.$eval('#PlaceIdInput', E => E.value)) === '920587237' && (await Wiz.$eval('#MinPlayersInput', E => E.value)) === '5');
    await SetValue(Wiz, '#ConfigName', 'Trade Renamed');
    await Wiz.click('#ConfirmBtn'); await Wait(700);
    const Names = (await CallApi('GetConfigs')).map(C => C.Name);
    Check('wizard rename replaces (no duplicate)', Names.includes('Trade Renamed') && !Names.includes('Trade Range'));
    await Wiz.close();

    // ------------------------------------------------------------ add / remove accounts
    await Hook('Login', ['FreshAlt']); await Wait(800);
    Check('new login appears (AccountsChanged)', await Count('#AccountList .ListItem') === 5 && (await Text('#AccountList .ListItem:nth-child(5) .AcctLabel')) === 'New FreshAlt (@FreshAlt)');
    await Hook('Login', ['FreshAlt']); await Wait(800);
    Check('same account re-login replaces, no duplicate', await Count('#AccountList .ListItem') === 5);
    await RowClick(4);
    await Page.click('#RemoveAccountBtn');
    Check('remove account (after confirm)', await WaitFor(async () => await Count('#AccountList .ListItem') === 4));
    Check('add while login window open is refused', !!(await CallApi('AddAccount')).Ok && !!(await CallApi('AddAccount')).Error);

    // ------------------------------------------------------------ themes
    Check('theme list has 4 themes', await Count('#ThemeSelect .CustomSelectOption') === 4 && await Count('#ThemeSelect .CustomSelectOption .ThemeSwatch') === 4 && await Count('#ThemeSelect .CustomSelectText .ThemeSwatch') === 0 && !!(await Page.$('#ActiveThemeSwatch')));
    const DarkBg = await Bg();
    await Promise.all([Page.waitForNavigation({ waitUntil: 'load' }), Pick('ThemeSelect', 'Light')]);
    Check('Light theme loads', await WaitFor(async () => (await Bg()) === 'rgb(228, 228, 228)' && (await Text('#ThemeSelect .CustomSelectText')) === '2016 Roblox'), await Bg());
    Check('Light uses its own stylesheet', await WaitFor(async () => (await Page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue('--Accent').trim())) === '#00a2ff'));
    await Shot('03-Light');
    await Promise.all([Page.waitForNavigation({ waitUntil: 'load' }), Pick('ThemeSelect', 'MyCustomTheme')]); await Wait(900);
    Check('MyCustomTheme loads', (await Bg()) === 'rgb(13, 15, 26)', await Bg());
    await Shot('04-MyCustomTheme');
    await CallApi('UpdateSetting', 'Theme', 'Ghost');
    await Open();
    Check('missing theme falls back to Dark with warning', (await Bg()) === DarkBg && /Ghost/.test(await Text('#ThemeWarning')));
    Check('path-like theme names rejected', !!(await CallApi('UpdateSetting', 'Theme', '../Config')).Error);
    await CallApi('UpdateSetting', 'Theme', 'Dark');
    await Open();

    // ------------------------------------------------------------ theme versions (Theme.json "SupportedVersions")
    const MakeTheme = (Id, Meta) => {
        cpSync(path.join(ScratchDir, 'Src', 'Dark'), path.join(ScratchDir, 'Src', Id), { recursive: true });
        writeFileSync(path.join(ScratchDir, 'Src', Id, 'Theme.json'), JSON.stringify(Meta));
    };
    const ModalShown = async () => !(await Page.$eval('#ThemeVersionModal', E => E.hidden));
    MakeTheme('OldTheme', { Name: 'Old Theme', SupportedVersions: ['0.9'] });
    MakeTheme('OldTheme2', { Name: 'Old Theme 2', SupportedVersions: ['0.9'] });
    MakeTheme('NoVersions', { Name: 'No Versions' });
    await Open();
    await Pick('ThemeSelect', 'OldTheme');
    Check('version dialog asks before an unsupported theme', await ModalShown()
        && /supports RAMMIT 0\.9, but this is RAMMIT \d/.test(await Text('#ThemeVersionText'))
        && /published.*"SupportedVersions"/.test(await Text('#ThemeVersionHint')), await Text('#ThemeVersionText'));
    await Shot('06-ThemeVersionDialog');
    await Page.click('#ThemeVersionCancel'); await Wait(300);
    Check('cancel keeps the current theme', !(await ModalShown()) && (await Text('#ThemeSelect .CustomSelectText')) === 'Dark' && (await CallApi('GetSettings')).Theme === 'Dark');
    // Chosen while unsupported (as after a RAMMIT update): opens in Dark and asks.
    await CallApi('UpdateSetting', 'Theme', 'OldTheme');
    await Open();
    Check('unsupported theme opens in Dark and asks', await WaitFor(ModalShown) && (await Bg()) === DarkBg && (await Text('#ThemeVersionCancel')) === 'STAY ON DARK');
    await Promise.all([Page.waitForNavigation({ waitUntil: 'load' }), Page.click('#ThemeVersionUse')]); await Wait(900);
    Check('use it anyway loads the theme', (await Text('#ThemeSelect .CustomSelectText')) === 'Old Theme' && !(await ModalShown()));
    await CallApi('UpdateSetting', 'Theme', 'OldTheme2');
    await Open();
    await WaitFor(ModalShown);
    await Page.click('#ThemeVersionCancel');
    Check('stay on Dark saves Dark', await WaitFor(async () => !(await ModalShown()) && (await CallApi('GetSettings')).Theme === 'Dark')
        && (await Text('#ThemeSelect .CustomSelectText')) === 'Dark');
    // A note under the Theme list grows the window by exactly the note's height, at any Windows scaling.
    const WindowHeight = async () => ((await (await fetch(Base + '/__TestHook/State')).json()).LastResize || [0, 0])[1];
    // The app resizes ~300 ms after booting: wait for a new height (when one is expected) that stays put.
    const SettledHeight = async Previous => {
        let Last = null;
        for (let I = 0; I < 40; I++) {
            const Now = await WindowHeight();
            if (Now === Last && Now !== Previous) return Now;
            Last = Now; await Wait(250);
        }
        return Last;
    };
    const NoteShift = () => Page.evaluate(() => {
        const Note = document.getElementById('ThemeWarning'), Below = Note.nextElementSibling;
        const Shown = Below.getBoundingClientRect().top; Note.style.display = 'none';
        const Hidden = Below.getBoundingClientRect().top; Note.style.display = '';
        return Shown - Hidden;
    });
    const Viewport = Page.viewport();
    const Extra = [];
    let WithNote;
    for (const Scale of [1, 1.25, 1.5, 2]) {
        await Page.setViewport({ ...Viewport, deviceScaleFactor: Scale });
        await CallApi('UpdateSetting', 'Theme', 'Dark'); await Open();
        const Plain = await SettledHeight(WithNote);
        await CallApi('UpdateSetting', 'Theme', 'NoVersions'); await Open();
        WithNote = await SettledHeight(Plain);
        await WaitFor(async () => !!(await Text('#ThemeWarning')));
        Extra.push([Scale, WithNote - Plain, await NoteShift(), (await Text('#ThemeWarning')) || '']);
    }
    await Page.setViewport(Viewport);
    Check('note line grows the window by its own height', Extra.every(([, Grow, Shift, Note]) => /SupportedVersions/.test(Note) && Shift > 0 && Math.abs(Grow - Shift) <= 1), JSON.stringify(Extra));
    Check('note height is the same at 100/125/150/200% scaling', new Set(Extra.map(E => E[1])).size === 1, JSON.stringify(Extra));
    for (const Id of ['OldTheme', 'OldTheme2', 'NoVersions']) rmSync(path.join(ScratchDir, 'Src', Id), { recursive: true, force: true });
    await CallApi('UpdateSetting', 'Theme', 'Dark');
    await Open();

    // ------------------------------------------------------------ tutorials
    await Page.click('#HelpBtn'); await Wait(300);
    Check('tutorial menu lists 7 topics', await Count('#TourMenuList .TourMenuItem') === 7);
    const Topics = await Page.$$eval('#TourMenuList .TmName', E => E.map(X => X.textContent));
    Check('theme tutorial present', Topics.includes('Making your own theme'));
    await Page.click('#TourAll'); await Wait(300);
    let Cards = 0, OffScreen = [];
    for (let I = 0; I < 60 && !(await Page.$eval('#TourCard', E => E.hidden)); I++) {
        const Box = await Page.$eval('#TourCard', E => { const R = E.getBoundingClientRect(); return { T: R.top, B: R.bottom, L: R.left, R: R.right }; });
        if (Box.T < 0 || Box.L < 0 || Box.B > 757 || Box.R > 765) OffScreen.push(await Text('#TourTitle'));
        if (I === 30) await Shot('05-Tour');
        Cards++;
        await Page.click('#TourNext'); await Wait(260);
    }
    Check('run-all tutorials completes', Cards === 34 && !(await Page.$eval('#TourMenu', E => E.hidden)), 'cards=' + Cards);
    Check('every tutorial card on screen', OffScreen.length === 0, OffScreen.join(', '));
    Check('all topics ticked', await Count('#TourMenuList .TmDone:not(:empty)') === 7);
    await Page.keyboard.press('Escape'); await Wait(200);
} catch (Error) {
    Check('test run crashed', false, Error.stack);
} finally {
    Check('no console/page/http errors', Errors.length === 0, Errors.join(' | '));
    await Browser.close();
    Harness.kill();
    const Failed = Results.filter(R => !R.Ok).length;
    console.log(`\n${Results.length - Failed}/${Results.length} passed`);
    process.exit(Failed ? 1 : 0);
}
