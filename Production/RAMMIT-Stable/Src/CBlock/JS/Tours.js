// Guided tutorial engine: a menu of spotlight tours over the real controls (content: TourData.js).

import { Api, ReportError } from './Bridge.js';
import { El, ById } from './Dom.js';
import { State } from './State.js';
import { ToggleSettings } from './Settings.js';
import { Tours } from './TourData.js';

let Steps = [];
let StepIndex = 0;
let Active = false;
let TourId = null;
let Queue = [];
let CollapseBefore = null;   // the settings panel's state before a tour opened it
let ReflowTimer = null;

// Returns true when it changed the layout, so the spotlight is re-measured after the slide.
const Actions = {
    ExpandSettings() {
        if (!State.SettingsCollapsed) return false;
        if (CollapseBefore === null) CollapseBefore = true;
        ToggleSettings();
        return true;
    },
};

export function InitTours(ToursDone) {
    State.ToursDone = new Set(ToursDone || []);
    ById('HelpBtn').addEventListener('click', OpenMenu);
    ById('TourNext').addEventListener('click', () => ShowStep(StepIndex + 1));
    ById('TourBack').addEventListener('click', () => ShowStep(StepIndex - 1));
    ById('TourSkip').addEventListener('click', () => { Queue = []; RestoreLayout(); OpenMenu(); });
    ById('TourClose').addEventListener('click', CloseTour);
    ById('TourAll').addEventListener('click', () => { Queue = Tours.map(T => T.Id); StartTour(Queue.shift()); });
    document.addEventListener('keydown', Event => {
        if (ById('TourOverlay').hidden) return;
        if (Event.key === 'Escape') CloseTour();
        else if (!Active) return;
        else if (Event.key === 'ArrowRight' || Event.key === 'Enter') ShowStep(StepIndex + 1);
        else if (Event.key === 'ArrowLeft') ShowStep(StepIndex - 1);
    });
    window.addEventListener('resize', () => { if (Active && Steps[StepIndex]) Position(Steps[StepIndex]); });
}

export function OpenMenu() {
    Active = false;
    Steps = [];
    ById('TourMenuList').replaceChildren(...Tours.map(Tour => {
        const Item = El('button', { Class: 'TourMenuItem' },
            El('span', { Class: 'TmText' }, El('span', { Class: 'TmName', Text: Tour.Name }), El('span', { Class: 'TmDesc', Text: Tour.Desc })),
            El('span', { Class: 'TmDone', Text: State.ToursDone.has(Tour.Id) ? '✓' : '' }));
        Item.addEventListener('click', () => StartTour(Tour.Id));
        return Item;
    }));
    ById('TourOverlay').hidden = false;
    ById('TourOverlay').classList.add('Plain');
    ById('TourSpot').hidden = true;
    ById('TourCard').hidden = true;
    ById('TourMenu').hidden = false;
    MarkSeen();
}

export function StartTour(Id) {
    const Tour = Tours.find(T => T.Id === Id);
    if (!Tour) { CloseTour(); return; }
    TourId = Id;
    Steps = Tour.Steps;
    Active = true;
    ById('TourOverlay').hidden = false;
    ById('TourMenu').hidden = true;
    ById('TourCard').hidden = false;
    MarkSeen();
    ShowStep(0);
}

function ShowStep(Index) {
    const Step = Steps[Index];
    if (!Step) { FinishTour(); return; }
    StepIndex = Index;
    const LayoutChanged = Step.Before && Actions[Step.Before] ? Actions[Step.Before]() : false;
    const Tour = Tours.find(T => T.Id === TourId) || { Name: '' };
    ById('TourStep').textContent = `${Tour.Name.toUpperCase()} — ${Index + 1} OF ${Steps.length}`;
    ById('TourTitle').textContent = Step.Title;
    const Body = ById('TourBody');
    Body.innerHTML = Step.Body;  // trusted static content from TourData.js
    if (Step.Keys) {
        Body.append(El('div', { Class: 'TourKeys' }, ...Step.Keys.map(([Key, Meaning]) =>
            El('div', { Class: 'TourKey' }, El('kbd', { Text: Key }), El('span', { Text: Meaning })))));
    }
    ById('TourBack').disabled = Index === 0;
    ById('TourNext').textContent = Index === Steps.length - 1 ? (Queue.length ? 'NEXT TOPIC' : 'DONE') : 'NEXT';
    Position(Step);
    clearTimeout(ReflowTimer);
    if (LayoutChanged) {
        // The settings panel slides open over 0.3s - re-measure once it lands.
        const Panel = ById('SettingsPanel');
        const Settle = () => {
            Panel.removeEventListener('transitionend', Settle);
            clearTimeout(ReflowTimer);
            if (Active && Steps[StepIndex] === Step) Position(Step);
        };
        Panel.addEventListener('transitionend', Settle);
        ReflowTimer = setTimeout(Settle, 600);
    }
}

function Position(Step) {
    const Overlay = ById('TourOverlay'), Spot = ById('TourSpot'), Card = ById('TourCard');
    const Target = Step.Target ? document.querySelector(Step.Target) : null;
    const Rect = Target ? Target.getBoundingClientRect() : null;
    const Offscreen = Rect && (Rect.right <= 0 || Rect.bottom <= 0 || Rect.left >= window.innerWidth || Rect.top >= window.innerHeight);
    if (!Rect || Rect.width === 0 || Rect.height === 0 || Offscreen) {
        Overlay.classList.add('Plain');
        Spot.hidden = true;
        Card.classList.add('Centered');
        Card.style.top = Card.style.left = '';
        return;
    }
    Overlay.classList.remove('Plain');
    Spot.hidden = false;
    const Pad = 5, Gap = 14;
    Object.assign(Spot.style, { top: (Rect.top - Pad) + 'px', left: (Rect.left - Pad) + 'px',
        width: (Rect.width + Pad * 2) + 'px', height: (Rect.height + Pad * 2) + 'px' });
    Card.classList.remove('Centered');
    Card.style.transform = '';
    const Width = Card.offsetWidth, Height = Card.offsetHeight;
    let Top = Rect.bottom + Gap;
    if (Top + Height > window.innerHeight - 10) Top = Rect.top - Height - Gap;
    if (Top < 10) Top = Math.max(10, Math.min(window.innerHeight - Height - 10, Rect.top));
    const Left = Math.max(10, Math.min(Rect.left + Rect.width / 2 - Width / 2, window.innerWidth - Width - 10));
    Card.style.top = Top + 'px';
    Card.style.left = Left + 'px';
}

function FinishTour() {
    if (TourId) State.ToursDone.add(TourId);
    Api.UpdateSetting('ToursDone', [...State.ToursDone]).catch(ReportError);
    RestoreLayout();
    if (Queue.length) { StartTour(Queue.shift()); return; }
    OpenMenu();
}

function CloseTour() {
    Queue = [];
    RestoreLayout();
    Active = false;
    ById('TourOverlay').hidden = true;
    MarkSeen();
}

function RestoreLayout() {
    clearTimeout(ReflowTimer);
    if (CollapseBefore === true && !State.SettingsCollapsed) ToggleSettings();
    CollapseBefore = null;
}

function MarkSeen() {
    Api.UpdateSetting('TutorialSeen', true).catch(ReportError);
}
