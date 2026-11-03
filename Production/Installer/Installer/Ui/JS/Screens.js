// Screen switching, breadcrumbs and window sizing. Go(), BuildCrumbs() and the slide classes are Test1's code;
// the changes are marked "new".

import { Api, ReportError } from './Bridge.js';
import { ById, El } from './Dom.js';

const Crumbs = {
    Install:       ['Menu', 'Version', 'Progress', 'Done'],
    Update:        ['Menu', 'Version', 'Progress', 'Done'],  // new: Update / Downgrade picks a version first
    Repair:        ['Menu', 'Progress', 'Done'],
    Uninstall:     ['Menu', 'Confirm', 'Progress', 'Goodbye'],
    // new
    LegacyInstall: ['Old version', 'Version', 'Progress', 'Done'],
    LegacyRemove:  ['Old version', 'Confirm', 'Progress', 'Done'],
    LegacyMove:    ['Old version', 'Progress', 'Done'],  // choices 1/2 with RAMMIT already installed
};

const CrumbScreens = {
    Install:       ['MenuFresh', 'Version', 'Progress', 'InstallDone'],
    Update:        ['MenuInstalled', 'ChangeVersion', 'Progress', 'ActionDone'],
    Repair:        ['MenuInstalled', 'Progress', 'ActionDone'],
    Uninstall:     ['MenuInstalled', 'ConfirmUninstall', 'ProgressUninstall', 'UninstallDone'],
    LegacyInstall: ['Legacy', 'Version', 'Progress', 'InstallDone'],
    LegacyRemove:  ['Legacy', 'LegacyConfirm', 'ProgressUninstall', 'LegacyDone'],
    LegacyMove:    ['Legacy', 'ProgressUninstall', 'LegacyDone'],
};

const ResultScreens = ['ActionDone', 'InstallDone', 'UninstallDone', 'LegacyDone'];
// new: screens outside the crumb trail (loading, error, "RAMMIT is running", settings clash) keep the
// trail of the step they interrupt.
const SideScreens = ['Loading', 'Error', 'Running', 'ConfigConflict'];

const ScreenAction = {};
Object.keys(CrumbScreens).forEach(Action => {
    CrumbScreens[Action].forEach(Scr => { if (!ScreenAction[Scr]) ScreenAction[Scr] = Action; });
});

export const Nav = { CurrentAction: 'Install', CurrentMenu: 'MenuFresh', CurrentScreen: 'Loading', Sliding: false };
let LastCrumbIdx = 0;
let Pending = null;  // new: a Go() that arrived mid-slide runs when the slide ends (Test1 dropped it)

export function SetMenu(Installed) {
    Nav.CurrentMenu = Installed ? 'MenuInstalled' : 'MenuFresh';
    if (!Installed) Nav.CurrentAction = 'Install';
}

export function BuildCrumbs() {
    const Target = ById('Breadcrumbs');
    if (Nav.CurrentScreen === 'Loading') {  // Test1's start-up crumb
        Target.replaceChildren(El('div', { Class: 'Crumb', Text: 'Loading...' }));
        return;
    }
    const Labels = Crumbs[Nav.CurrentAction] || ['Menu'];
    const Screens = CrumbScreens[Nav.CurrentAction] || [Nav.CurrentMenu];
    let Idx = Screens.indexOf(Nav.CurrentScreen);
    if (Idx === -1 && ResultScreens.includes(Nav.CurrentScreen)) Idx = Screens.length - 1;
    if (Idx === -1 && SideScreens.includes(Nav.CurrentScreen)) Idx = LastCrumbIdx;
    LastCrumbIdx = Math.max(0, Idx);

    const Nodes = [];
    Labels.forEach((Label, I) => {
        if (I > 0) Nodes.push(El('span', { Class: 'CrumbArrow' }, El('i', { Class: 'ph-bold ph-caret-right' })));
        const Btn = El('div', { Class: 'Crumb', Text: Label });
        if (I < Idx) Btn.classList.add('Done');
        if (I === Idx) Btn.classList.add('Active');
        Nodes.push(Btn);
    });
    Target.replaceChildren(...Nodes);
}

export function Go(Screen, Action) {
    if (Nav.Sliding) {
        Pending = [Screen, Action];
        return;
    }
    if (Screen === Nav.CurrentScreen) {
        if (Action) Nav.CurrentAction = Action;
        BuildCrumbs();
        return;
    }
    if (Action) Nav.CurrentAction = Action;
    else if (ScreenAction[Screen] && !(CrumbScreens[Nav.CurrentAction] || []).includes(Screen)) Nav.CurrentAction = ScreenAction[Screen];

    // Screen names come from this file's own code, never from data, so the selector is safe.
    const OldEl = document.querySelector('[data-screen="' + Nav.CurrentScreen + '"]');
    const NewEl = document.querySelector('[data-screen="' + Screen + '"]');
    if (!NewEl) return;

    const Screens = CrumbScreens[Nav.CurrentAction] || [];
    const OldIdx = Screens.indexOf(Nav.CurrentScreen);
    const NewIdx = Screens.indexOf(Screen);
    const Forward = (OldIdx === -1 || NewIdx === -1) ? true : NewIdx >= OldIdx;

    Nav.Sliding = true;
    Nav.CurrentScreen = Screen;
    BuildCrumbs();

    const OutClass = Forward ? 'SlideOut' : 'SlideOutBack';
    const InClass = Forward ? 'SlideIn' : 'SlideInBack';
    if (OldEl) {
        OldEl.classList.remove('Active');
        OldEl.classList.add(OutClass);
    }
    NewEl.classList.add(InClass);
    FitWindow();

    setTimeout(() => {
        if (OldEl) OldEl.classList.remove(OutClass);
        NewEl.classList.remove(InClass);
        NewEl.classList.add('Active');
        Nav.Sliding = false;
        FitWindow();
        if (Pending) {
            const [NextScreen, NextAction] = Pending;
            Pending = null;
            Go(NextScreen, NextAction);
        }
    }, 250);
}

// ------------------------------------------------------------ window sizing (new)
// Test1 kept a height per screen in both Python and HTML and multiplied it by the DPI, which pywebview 6
// already applies (windows came out too tall at 125%/150%). Now the page measures what it shows: the bottom
// of the card plus the body's 20px bottom padding, in CSS px. Python adds only the title bar.

let LastSent = 0;
let FitQueued = false;

export function FitWindow() {
    if (FitQueued) return;
    FitQueued = true;
    requestAnimationFrame(() => {
        FitQueued = false;
        // Focusing or clicking something below the fold scrolls the page even with overflow: hidden; measure
        // from the top of the page and scroll back.
        const Scrolled = window.scrollY;
        if (Scrolled) window.scrollTo(0, 0);
        const Card = document.querySelector('.InstallerWindow');
        const Needed = Math.ceil(Card.getBoundingClientRect().bottom + 20);
        window.InstallerFitHeight = Needed;  // read by the UI tests
        if (Math.abs(Needed - LastSent) < 2) return;
        LastSent = Needed;
        Api.ResizeInstaller(Needed, window.innerHeight).catch(ReportError);
    });
}

export function WatchSize() {
    const Observer = new ResizeObserver(() => FitWindow());
    Observer.observe(document.querySelector('.InstallerWindow'));
    Observer.observe(ById('Breadcrumbs'));
}
