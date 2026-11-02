// Headless UI test of every installer screen: the real HTML/JS/CSS served from memory by the real UiServer, the
// real InstallerApi/Setup/Releases (Tests/UiHarness.py) against a fake release server, in test mode.
// A screenshot of each screen is taken at the window size the page asked for (width 544 = the 560 px window's
// client area at 100%).
//
// Usage: node Tests/TestUi.mjs <PuppeteerCoreDir> <ChromeExe> <ScratchDir> <ScreenshotDir>
//   ScratchDir is wiped by the harness; keep ScreenshotDir somewhere else.
import { createRequire } from 'module';
import { spawn } from 'child_process';
import { mkdirSync } from 'fs';
import http from 'http';
import path from 'path';
import { fileURLToPath } from 'url';

const [PuppeteerDir, ChromeExe, ScratchDir, ShotDir] = process.argv.slice(2);
const Puppeteer = createRequire(path.join(PuppeteerDir, 'x.js'))('puppeteer-core');
const ProjectDir = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
mkdirSync(ShotDir, { recursive: true });
if (path.resolve(ShotDir).toLowerCase().startsWith(path.resolve(ScratchDir).toLowerCase())) throw new Error('ScreenshotDir must be outside ScratchDir');

const ClientWidth = 544;
const FrameHeight = 39;  // the harness window has no native frame, so InstallerApi adds its 39 px fallback
const Sleep = Ms => new Promise(R => setTimeout(R, Ms));
const Results = [];
const Errors = [];
const Shots = [];
const Check = (Name, Ok, Detail = '') => { Results.push({ Name, Ok: !!Ok }); console.log((Ok ? 'PASS ' : 'FAIL ') + Name + (Detail ? ' -- ' + Detail : '')); };

// ---------------------------------------------------------------- backend harness
const Harness = spawn('python', [path.join(ProjectDir, 'Tests', 'UiHarness.py'), ScratchDir], { stdio: ['ignore', 'pipe', 'inherit'] });
const Port = await new Promise((Resolve, Reject) => {
    Harness.stdout.on('data', D => { const M = String(D).match(/PORT (\d+)/); if (M) Resolve(Number(M[1])); });
    Harness.on('exit', Code => Reject(new Error('harness exited ' + Code)));
});
const Base = `http://127.0.0.1:${Port}`;
const Hook = async (Name, Body) => (await fetch(Base + '/__TestHook/' + Name, Body ? { method: 'POST', body: JSON.stringify(Body) } : {})).json();
const CallApi = async (Name, ...Args) => (await fetch(Base + '/__TestApi/' + Name, { method: 'POST', body: JSON.stringify(Args) })).json();
function RawGet(UrlPath, Host = `127.0.0.1:${Port}`) {
    return new Promise(Resolve => {
        const Req = http.request({ host: '127.0.0.1', port: Port, path: UrlPath, headers: { Host } }, Res => {
            let Body = ''; Res.on('data', C => Body += C); Res.on('end', () => Resolve({ Status: Res.statusCode, Headers: Res.headers, Body }));
        });
        Req.on('error', E => Resolve({ Status: 0, Body: String(E) }));
        Req.end();
    });
}

// Stands in for pywebview's bridge: api.X(...) -> POST /__TestApi/X, and replays Python->JS events.
const Shim = `
    window.pywebview = { api: new Proxy({}, { get: (_T, Name) => (...Args) =>
        fetch('/__TestApi/' + String(Name), { method: 'POST', body: JSON.stringify(Args) }).then(R => R.json()) }) };
    setInterval(async () => {
        try {
            const Events = await (await fetch('/__TestHook/Events')).json();
            Events.forEach(Script => {
                const M = Script.match(/InstallerEvents\\.(\\w+)\\((.*)\\)$/s);
                if (M && window.InstallerEvents) window.InstallerEvents[M[1]](JSON.parse(M[2]));
            });
        } catch (_) {}
    }, 100);`;

const Browser = await Puppeteer.launch({ executablePath: ChromeExe, headless: 'new' });
const Page = await Browser.newPage();
await Page.setViewport({ width: ClientWidth, height: 400, deviceScaleFactor: 1 });
await Page.evaluateOnNewDocument(Shim);
Page.on('pageerror', E => Errors.push('pageerror :: ' + E.message));
Page.on('console', M => { if (M.type() === 'error') Errors.push('console :: ' + M.text()); });
Page.on('response', R => { if (R.status() >= 400 && !R.url().includes('/__Test')) Errors.push('http ' + R.status() + ' ' + R.url()); });

// Polls instead of fixed waits: the PC is shared, so boot and slide timing vary.
const WaitFor = async (Test, Ms = 15000) => { for (const End = Date.now() + Ms; Date.now() < End; await Sleep(60)) { try { if (await Test()) return true; } catch (_) {} } return false; };
const Active = () => Page.evaluate(() => { const E = document.querySelector('.InstallerScreen.Active'); return E ? E.dataset.screen : null; });
const Still = () => Page.evaluate(() => !document.querySelector('.SlideIn, .SlideOut, .SlideInBack, .SlideOutBack'));
// 45 s: installs/updates unpack the real 23 MB release zip, which antivirus scanning slows down on a busy PC.
const OnScreen = async (Screen, Ms = 45000) => WaitFor(async () => (await Active()) === Screen && await Still(), Ms);
const Text = Sel => Page.$eval(Sel, E => E.innerText.trim()).catch(() => null);
const Visible = Sel => Page.$eval(Sel, E => !!(E.offsetWidth || E.offsetHeight)).catch(() => false);
const Crumbs = () => Page.$$eval('#Breadcrumbs .Crumb', Els => Els.map(E => E.textContent + (E.classList.contains('Active') ? '*' : '')).join(' > '));
const ClickBtn = async Id => {
    if (!await WaitFor(() => Visible('#' + Id))) throw new Error('#' + Id + ' not visible; active screen: ' + await Active() + ' / ' + await Text('.InstallerScreen.Active'));
    await Page.click('#' + Id);
};
const Open = async () => { await Page.goto(`${Base}/HTML/Installer.html`, { waitUntil: 'load' }); };
// Picker rows as "S 1.1.0 (latest)" (branch letter, version, tag); Disabled rows get a trailing " [disabled]".
const Rows = Sel => Page.$$eval(Sel + ' .CustomSelectOption', Els => Els.map(E => {
    const Cell = E.querySelector('.BranchCell'), Text = E.querySelector('.VersionText'), Tag = E.querySelector('.VersionTag');
    if (!Cell) return E.textContent;
    const Ver = Text.firstChild.textContent;
    return Cell.textContent + ' ' + Ver + (Tag ? ' ' + Tag.textContent : '') + (E.classList.contains('Disabled') ? ' [disabled]' : '');
}));
const Prefix = Sel => Page.$eval(Sel + ' .InstVersionPrefix', E => E.textContent + '/' + E.title);
const OpenPicker = async Sel => {
    await Page.focus(Sel + ' .InstVersionInput');
    await WaitFor(() => Page.$eval(Sel, E => E.classList.contains('Open')));
};
const PickRow = (Sel, Ver) => Page.evaluate((S, V) => [...document.querySelectorAll(S + ' .CustomSelectOption')].find(E => E.dataset.value === V)
    .dispatchEvent(new MouseEvent('mousedown', { bubbles: true })), Sel, Ver);

// Sizes the viewport like the real window (the height the page asked for), then screenshots.
async function Shot(Name, Screen) {
    const Ok = await OnScreen(Screen);
    // The screen can still be filling in (e.g. the version list): only take a height the page asked for that
    // stays the same over two checks 200 ms apart.
    let Height = 0, Previous = -1;
    await WaitFor(async () => {
        const H = await Page.evaluate(() => window.InstallerFitHeight || 0);
        const State = await Hook('State');
        const Matches = H && State.LastResize && State.LastResize[1] === H + FrameHeight;
        if (Matches && H === Previous) { Height = H; return true; }
        Previous = Matches ? H : -1;
        await Sleep(200);
        return false;
    }, 15000);
    if (Height) await Page.setViewport({ width: ClientWidth, height: Height, deviceScaleFactor: 1 });
    await Page.evaluate(() => new Promise(R => requestAnimationFrame(() => requestAnimationFrame(R))));
    const Layout = await Page.evaluate(() => {
        const Card = document.querySelector('.InstallerWindow').getBoundingClientRect();
        return { Bottom: Card.bottom, Right: Card.right, Inner: window.innerHeight, Fit: window.InstallerFitHeight };
    });
    const Fits = Layout.Bottom + 20 <= Layout.Inner + 1 && Layout.Right <= ClientWidth;
    const File = path.join(ShotDir, Name + '.png');
    await Page.screenshot({ path: File });
    Shots.push(File);
    Check(`screen ${Screen}: shown, window sized to content (${Height}px + frame), nothing cut off`, Ok && Height > 0 && Fits, Ok ? JSON.stringify(Layout) : 'active: ' + await Active());
}

try {
    // ------------------------------------------------------------ server hardening
    const Html = await RawGet('/HTML/Installer.html');
    Check('server: page served from memory with CSP', Html.Status === 200 && /script-src 'self'/.test(Html.Headers['content-security-policy'] || ''));
    Check('server: no listing, no traversal, no source', (await RawGet('/')).Status === 404 && (await RawGet('/HTML/')).Status === 404
        && (await RawGet('/../Installer.py')).Status === 404 && (await RawGet('/%2e%2e/InstallerApi.py')).Status === 404);
    Check('server: foreign Host rejected', (await RawGet('/HTML/Installer.html', 'evil.example')).Status === 403);

    // ------------------------------------------------------------ A. fresh PC
    await Hook('Server', { HoldList: true });
    await Open();
    await Shot('01-Loading', 'Loading');
    Check('loading: Test1 start crumb, no fake values', (await Crumbs()) === 'Loading...' && (await Text('#StagePct')) === '0%' && (await Text('#StageDetail')) === '');
    await Hook('Server', { HoldList: false });
    await Shot('02-MenuFresh', 'MenuFresh');
    Check('fresh menu: wording + buttons', (await Text('[data-screen=MenuFresh] .InstallerMessage')).startsWith('RAMMIT is not installed on this system.')
        && (await Text('#FreshInstallBtn')) === 'INSTALL' && (await Text('#FreshCancelBtn')) === 'CANCEL');
    Check('footer shows latest version', await Page.$eval('#FooterVersion', E => E.textContent) === 'v1.1.0' && (await Text('.InstFooter span')) === 'RAMMIT INSTALLER');

    await ClickBtn('FreshInstallBtn');
    await Shot('03-Version', 'Version');
    Check('version: crumbs', (await Crumbs()) === 'Menu > Version* > Progress > Done', await Crumbs());
    Check('version: latest preselected', await Page.$eval('#InstallVersionSelect', E => E.dataset.value) === '1.1.0'
        && await Page.$eval('#InstallVersionSelect .InstVersionInput', E => E.value) === '1.1.0 (latest)');
    Check('branch cell: S where Test1 had v, tooltip names the branch', (await Prefix('#InstallVersionSelect')) === 'S/Stable', await Prefix('#InstallVersionSelect'));
    Check('version: default path', (await Page.$eval('#InstallPath', E => E.value)).endsWith('LocalAppData\\RAMMIT'));
    await OpenPicker('#InstallVersionSelect');
    const Listed = await Rows('#InstallVersionSelect');
    Check('picker: stable versions only, branch column, latest tagged', JSON.stringify(Listed) === JSON.stringify(['S 1.1.0 (latest)', 'S 1.0.0', 'S 0.9.0']), JSON.stringify(Listed));
    // The list spans the branch cell (like the theme list spans the swatch): letters under the picked letter,
    // versions under the typed text.
    const Align = await Page.evaluate(() => {
        const Box = E => E.getBoundingClientRect();
        const Sel = document.querySelector('#InstallVersionSelect');
        const P = Box(Sel.querySelector('.InstVersionPrefix')), I = Box(Sel.querySelector('.InstVersionInput'));
        const C = Box(Sel.querySelector('.CustomSelectOption .BranchCell')), T = Box(Sel.querySelector('.CustomSelectOption .VersionText'));
        const L = Box(Sel.querySelector('.CustomSelectOptions')), Tr = Box(Sel.querySelector('.CustomSelectTrigger'));
        return { Letter: Math.abs((C.left + C.right) / 2 - (P.left + P.right) / 2), Text: Math.abs(T.left - I.left), ListLeft: Math.abs(L.left - Tr.left) };
    });
    Check('picker: list spans the branch column, letters + versions line up', Align.Letter <= 1 && Align.Text <= 1 && Align.ListLeft <= 0.5, JSON.stringify(Align));
    Check('picker: row letter tooltip', await Page.$eval('#InstallVersionSelect .CustomSelectOption .BranchCell', E => E.title) === 'Stable');
    await Shot('03b-VersionPickerOpen', 'Version');
    await Page.keyboard.type('lat');
    Check('picker: "latest" search', JSON.stringify(await Rows('#InstallVersionSelect')) === '["S 1.1.0 (latest)"]');
    await Page.$eval('#InstallVersionSelect .InstVersionInput', E => E.blur());
    await Page.click('[data-screen=Version] .InstCheckboxRow');
    await WaitFor(async () => (await Rows('#InstallVersionSelect')).length === 4);
    const WithDev = await Rows('#InstallVersionSelect');
    Check('picker: "Show dev versions" adds the pre-release as D', WithDev[0] === 'D 1.2.0-beta.1'
        && await Page.$eval('#InstallVersionSelect .CustomSelectOption .BranchCell', E => E.title + '/' + getComputedStyle(E).color) === 'Dev/rgb(255, 193, 7)', JSON.stringify(WithDev));
    await OpenPicker('#InstallVersionSelect');
    await Page.keyboard.type('dev');
    Check('picker: "dev" search', JSON.stringify(await Rows('#InstallVersionSelect')) === '["D 1.2.0-beta.1"]');
    await PickRow('#InstallVersionSelect', '1.2.0-beta.1');
    Check('picking a Dev version shows D in the branch cell', (await Prefix('#InstallVersionSelect')) === 'D/Dev');
    await Shot('03c-VersionDevPicked', 'Version');
    await Page.click('[data-screen=Version] .InstCheckboxRow');
    await WaitFor(async () => (await Rows('#InstallVersionSelect')).length === 3);
    Check('hiding dev versions drops the Dev pick', (await Prefix('#InstallVersionSelect')) === 'S/Stable');
    // pick 1.0.0 so an update exists later
    await OpenPicker('#InstallVersionSelect');
    await PickRow('#InstallVersionSelect', '1.0.0');
    Check('picker: pick 1.0.0', await Page.$eval('#InstallVersionSelect', E => E.dataset.value) === '1.0.0');

    await Page.$eval('#InstallPath', E => { E.value = 'relative\\folder'; });
    await ClickBtn('VersionInstallBtn');
    await WaitFor(async () => !!(await Text('#PathError')));
    await Shot('04-VersionPathError', 'Version');
    Check('bad path explained under the field', /Pick a folder on this PC/.test(await Text('#PathError')), await Text('#PathError'));
    await ClickBtn('BrowseBtn');
    await WaitFor(async () => (await Page.$eval('#InstallPath', E => E.value)).endsWith('Picked\\RAMMIT'));
    Check('browse: Test1 rule adds \\RAMMIT', (await Page.$eval('#InstallPath', E => E.value)).endsWith('Picked\\RAMMIT'));
    const DefaultPath = (await CallApi('GetState')).DefaultPath;
    await Page.$eval('#InstallPath', (E, P) => { E.value = P; }, DefaultPath);

    await Hook('Running', { Running: true });
    await Hook('Server', { ChunkDelay: 0.12 });
    await ClickBtn('VersionInstallBtn');
    await Shot('05-Running', 'Running');
    Check('running: says what to do', /Close RAMMIT before you install it/.test(await Text('[data-screen=Running] .InstResultText')));
    await ClickBtn('RunningCloseBtn');
    await OnScreen('Progress');
    await WaitFor(async () => { const P = await Text('#StagePct'); return P && P !== '0%' && P !== '100%' && (await Text('#StageLabel')) === 'Downloading'; });
    await Shot('06-Progress', 'Progress');
    Check('progress: real byte progress + stage list', /RAMMIT-1\.0\.0\.zip - .* \/ /.test(await Text('#StageDetail'))
        && await Page.$eval('#StageList li.Active', E => E.dataset.stage) === 'Download', await Text('#StageDetail'));
    Check('progress: crumbs', (await Crumbs()) === 'Menu > Version > Progress* > Done', await Crumbs());
    await Hook('Server', { ChunkDelay: 0 });
    await Shot('07-InstallDone', 'InstallDone');
    const DoneText = await Text('#InstallDoneText');
    Check('install done: Test1 wording with real version + path', DoneText.startsWith('Installed v1.0.0 to ') && DoneText.includes(DefaultPath)
        && DoneText.includes('A desktop shortcut has been created.') && DoneText.includes('Have fun - and ping us if anything breaks.'), DoneText);
    let St = await Hook('State');
    Check('install: registry + Apps entry written (test keys)', St.Registry && St.Registry.Version === '1.0.0' && St.Apps && St.Apps.DisplayVersion === '1.0.0');
    await ClickBtn('LaunchBtn');
    Check('LAUNCH RAMMIT starts the app and closes the installer', await WaitFor(async () => { const S = await Hook('State'); return S.Launches === 1 && S.Closed >= 1; }));

    // ------------------------------------------------------------ B. installed
    await Open();
    await Shot('08-MenuInstalled', 'MenuInstalled');
    Check('installed menu: versions + buttons (no separate Change version)', (await Text('#InstalledVer')) === 'v1.0.0' && (await Text('#LatestVer')) === 'v1.1.0'
        && JSON.stringify(await Page.$$eval('[data-screen=MenuInstalled] .BtnInst', Els => Els.map(E => E.textContent))) === '["UPDATE / DOWNGRADE","REPAIR","UNINSTALL","CANCEL"]');
    await ClickBtn('UpdateBtn');
    await Shot('09-UpdateDowngrade', 'ChangeVersion');
    Check('update/downgrade: crumbs', (await Crumbs()) === 'Menu > Version* > Progress > Done', await Crumbs());
    Check('a reload never brings back a stale "Show dev versions" tick', !(await Page.$eval('[data-screen=ChangeVersion] .ShowTestVersions', E => E.checked)));
    Check('update/downgrade: newer version preselected, button says UPDATE', await Page.$eval('#ChangeVersionSelect', E => E.dataset.value) === '1.1.0'
        && (await Text('#ChangeInstallBtn')) === 'UPDATE' && !(await Page.$eval('#ChangeInstallBtn', E => E.disabled)));
    await OpenPicker('#ChangeVersionSelect');
    const UpRows = await Rows('#ChangeVersionSelect');
    Check('update/downgrade list: newer, installed greyed out, older', JSON.stringify(UpRows) === JSON.stringify(['S 1.1.0 (latest)', 'S 1.0.0 (installed) [disabled]', 'S 0.9.0']), JSON.stringify(UpRows));
    await PickRow('#ChangeVersionSelect', '1.0.0');
    Check('the installed version can\'t be picked', await Page.$eval('#ChangeVersionSelect', E => E.dataset.value) === '1.1.0');
    await Shot('09b-UpdateDowngradeList', 'ChangeVersion');
    await PickRow('#ChangeVersionSelect', '0.9.0');
    Check('older pick: button says DOWNGRADE', (await Text('#ChangeInstallBtn')) === 'DOWNGRADE');
    await OpenPicker('#ChangeVersionSelect');
    await PickRow('#ChangeVersionSelect', '1.1.0');
    Check('newer pick: button says UPDATE again', (await Text('#ChangeInstallBtn')) === 'UPDATE');
    await ClickBtn('ChangeInstallBtn');
    await OnScreen('Progress');
    Check('update: heading', (await Text('#ProgressHeading')) === 'Updating RAMMIT to v1.1.0...', await Text('#ProgressHeading'));
    await Shot('10-ActionDone', 'ActionDone');
    Check('update done', (await Text('#ActionDoneTitle')) === 'Updated successfully.' && (await Text('#ActionDoneText')).startsWith('RAMMIT is now on v1.1.0.'), await Text('#ActionDoneText'));

    await Open();
    await OnScreen('MenuInstalled');
    await ClickBtn('UpdateBtn');
    await Shot('11-UpToDate', 'ChangeVersion');
    Check('on the latest: nothing picked, button disabled UP TO DATE', await Page.$eval('#ChangeVersionSelect', E => E.dataset.value) === ''
        && (await Text('#ChangeInstallBtn')) === 'UP TO DATE' && await Page.$eval('#ChangeInstallBtn', E => E.disabled));
    Check('undo offered', await Visible('#UndoBtn') && (await Text('#UndoBtn')) === 'UNDO LAST CHANGE (BACK TO V1.0.0)', await Text('#UndoBtn'));
    await OpenPicker('#ChangeVersionSelect');
    Check('installed + latest row greyed out', (await Rows('#ChangeVersionSelect'))[0] === 'S 1.1.0 (latest, installed) [disabled]');
    await PickRow('#ChangeVersionSelect', '0.9.0');
    await ClickBtn('ChangeInstallBtn');
    await OnScreen('Progress');
    Check('downgrade: heading', (await Text('#ProgressHeading')) === 'Downgrading RAMMIT to v0.9.0...', await Text('#ProgressHeading'));
    await OnScreen('ActionDone');
    Check('downgrade to 0.9.0', (await Text('#ActionDoneTitle')) === 'Downgraded successfully.' && (await Text('#ActionDoneText')).includes('v0.9.0')
        && (await Text('#ActionDoneText')).includes('Config.Backup/'), await Text('#ActionDoneText'));

    await Open();
    await OnScreen('MenuInstalled');
    await ClickBtn('UpdateBtn');
    await OnScreen('ChangeVersion');
    Check('undo now offers 1.1.0', (await Text('#UndoBtn')) === 'UNDO LAST CHANGE (BACK TO V1.1.0)');
    await Hook('Server', { Offline: true });
    await ClickBtn('UndoBtn');
    await OnScreen('ActionDone');
    Check('undo works offline', (await Text('#ActionDoneTitle')) === 'Last change undone.' && (await Text('#ActionDoneText')).startsWith('RAMMIT is now on v1.1.0.'));

    await Hook('Server', { Forget: true });  // a new installer process has no cached release list
    await Open();  // still offline
    await Shot('12-MenuInstalledOffline', 'MenuInstalled');
    Check('offline: menu still usable', (await Text('#LatestVer')) === 'unknown (offline)');
    await ClickBtn('RepairBtn');
    await Shot('13-Error', 'Error');
    Check('error screen: message, details, retry', /Couldn't reach GitHub/.test(await Text('#ErrorText')) && await Visible('#ErrorDetail')
        && await Visible('#ErrorRetryBtn') && (await Text('#ErrorBackBtn')) === 'BACK', await Text('#ErrorText'));
    await Hook('Server', { Offline: false });
    await ClickBtn('ErrorRetryBtn');
    await OnScreen('ActionDone');
    Check('retry after error: repair complete', (await Text('#ActionDoneTitle')) === 'Repair complete.');

    await Hook('StartScreen', { Screen: 'ConfirmUninstall' });
    await Open();
    await Shot('14-ConfirmUninstall', 'ConfirmUninstall');
    await Hook('StartScreen', { Screen: '' });
    Check('/Uninstall opens straight at the confirm screen (Settings > Apps)', (await Crumbs()) === 'Menu > Confirm* > Progress > Goodbye'
        && (await Text('#ConfirmUninstallMsg')).startsWith("You're about to uninstall RAMMIT v1.1.0."));
    await Page.click('[data-screen=ConfirmUninstall] .InstCheckboxRow');
    Check('tick box changes the warning (Test1)', /also remove your Config\/ folder/.test(await Text('#ConfirmUninstallMsg')));
    await Page.click('[data-screen=ConfirmUninstall] .InstCheckboxRow');
    await Hook('Accounts', { Path: DefaultPath });  // RAMMIT has run once: there is a Config folder to keep
    await Hook('SlowUninstall', { Delay: 0.4 });
    await ClickBtn('UninstallConfirmBtn');
    await OnScreen('ProgressUninstall');
    await Shot('15-ProgressUninstall', 'ProgressUninstall');
    await Hook('SlowUninstall', { Delay: 0 });
    await Shot('16-UninstallDone', 'UninstallDone');
    Check('goodbye: sad face + Config kept line with where', await Page.$('[data-screen=UninstallDone] .InstResultIcon.Sad svg') !== null
        && (await Text('#UninstallDoneText')).includes('Config/ folder was kept in ' + DefaultPath + '. Installing again brings it back.'), await Text('#UninstallDoneText'));
    St = await Hook('State');
    Check('uninstall: Apps entry gone, registry keeps only the pointer to the kept accounts',
        St.Apps === null && JSON.stringify(St.Registry) === JSON.stringify({ KeptConfigPath: DefaultPath }), JSON.stringify(St.Registry));

    // ------------------------------------------------------------ B2. installing again finds the kept accounts
    await Open();
    await Shot('16b-MenuFreshKept', 'MenuFresh');
    Check('fresh menu mentions the kept accounts', await Visible('#KeptFreshLine') && (await Text('#KeptFreshPath')) === DefaultPath);
    await ClickBtn('FreshInstallBtn');
    await Shot('16c-VersionKept', 'Version');
    Check('install offers them back (ticked) and installs where they are', await Visible('#KeptRow') && await Page.$eval('#UseKept', E => E.checked)
        && (await Text('#KeptPath')) === DefaultPath && (await Page.$eval('#InstallPath', E => E.value)) === DefaultPath);
    await ClickBtn('VersionBackBtn');
    await OnScreen('MenuFresh');

    // ------------------------------------------------------------ C. an old Test1 install
    const Old = (await Hook('Legacy', {})).Path;
    await Open();
    await Shot('17-Legacy', 'Legacy');
    Check('older RAMMIT found: path + version + 4 choices', (await Text('#LegacyPath')) === Old && (await Text('#LegacyVer')) === 'v1.0.0'
        && (await Page.$$('[data-screen=Legacy] .BtnInst')).length === 4, await Crumbs());
    await ClickBtn('LegacyRemoveBtn');
    await Shot('18-LegacyConfirm', 'LegacyConfirm');
    await ClickBtn('LegacyConfirmBackBtn');
    await OnScreen('Legacy');
    await Hook('Accounts', { Path: DefaultPath });  // the kept Config now "has accounts" -> clash
    await ClickBtn('LegacyMoveKeepBtn');
    await OnScreen('Version');
    Check('legacy flow crumbs', (await Crumbs()) === 'Old version > Version* > Progress > Done', await Crumbs());
    await ClickBtn('VersionInstallBtn');
    await Shot('19-ConfigConflict', 'ConfigConflict');
    await ClickBtn('KeepNewBtn');
    await Shot('20-InstallDoneLegacy', 'InstallDone');
    Check('install done mentions the move', (await Text('#InstallDoneText')).includes('came across from the old version'));

    // remove the new one again, point the registry back at the (kept) Test1 install, and use choice 3
    // Straight through the API; its events must not reach the next page. Watch the never-emptied log, because
    // the page's own replay also drains /__TestHook/Events and can take the Done event first.
    const LogStart = (await Hook('EventLog')).length;
    await CallApi('StartUninstall', true);
    Check('uninstall through the API finished', await WaitFor(async () => (await Hook('EventLog')).slice(LogStart).some(S => S.includes('.Done('))));
    await Hook('Events');  // empty the queue so none of this uninstall's events are replayed into the next page
    await Hook('Legacy', {});
    await Open();
    await OnScreen('Legacy');
    await ClickBtn('LegacyRemoveBtn');
    await OnScreen('LegacyConfirm');
    await ClickBtn('LegacyConfirmRemoveBtn');
    await Shot('21-LegacyDone', 'LegacyDone');
    Check('old version removed', (await Text('#LegacyDoneText')).includes(Old));
    await ClickBtn('LegacyDoneContinueBtn');
    await OnScreen('MenuFresh');

    // choice 4: ignore + don't ask again
    await Hook('Legacy', {});
    await Open();
    await OnScreen('Legacy');
    await Page.click('[data-screen=Legacy] .InstCheckboxRow');
    await ClickBtn('LegacyIgnoreBtn');
    await OnScreen('MenuFresh');
    Check('ignore + don\'t ask again saved', (await Hook('State')).Registry.IgnoreLegacyInstall === '1');
    await Open();
    Check('not asked again', await OnScreen('MenuFresh'));

    // ------------------------------------------------------------ D. no internet on a fresh PC
    await Hook('Server', { Offline: true, Forget: true });
    await Open();
    await Shot('22-ErrorBoot', 'Error');
    Check('boot error: Close + Retry', (await Text('#ErrorTitle')) === "Couldn't load the versions." && (await Text('#ErrorBackBtn')) === 'CLOSE' && await Visible('#ErrorRetryBtn'));
    await Hook('Server', { Offline: false });
    await ClickBtn('ErrorRetryBtn');
    Check('retry recovers', await OnScreen('MenuFresh'));

    Check('no page errors', Errors.length === 0, Errors.join(' | '));
} catch (Error) {
    Check('test run crashed', false, Error.stack);
} finally {
    await Browser.close();
    await Hook('Shutdown', {}).catch(() => {});
    await WaitFor(async () => Harness.exitCode !== null, 5000);
    if (Harness.exitCode === null) Harness.kill();
}

console.log('\nSCREENSHOTS');
Shots.forEach(S => console.log('  ' + S));
const Failed = Results.filter(R => !R.Ok).length;
console.log(`\n${Results.length - Failed}/${Results.length} UI checks passed`);
process.exit(Failed ? 1 : 0);
