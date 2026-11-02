// SAVED ACCOUNTS panel: list, multi-select, add, remove.
// Selection is stored by username, so it survives reordering and removals.

import { Api, ReportError } from './Bridge.js';
import { El, ById } from './Dom.js';
import { State } from './State.js';
import { ShowLaunchError } from './Status.js';

export async function RefreshAccounts() {
    State.Accounts = await Api.GetAccounts();
    const Known = new Set(State.Accounts.map(A => A.Username));
    [...State.Selected].forEach(Name => { if (!Known.has(Name)) State.Selected.delete(Name); });
    const List = ById('AccountList');
    List.replaceChildren(...State.Accounts.map((Account, Index) => {
        const Check = El('span', { Class: 'AcctCheck' }, El('i', { Class: 'ph-bold ph-check' }));
        const Label = El('span', { Class: 'AcctLabel', Text: Account.DisplayName + ' ' },
            El('span', { Class: 'AcctUser', Text: `(@${Account.Username})` }),
            Account.Locked ? El('span', { Class: 'AcctLocked', Text: '⚠', Title: 'This saved login was made on another PC or Windows user. Remove it and add the account again.' }) : null);
        const Row = El('li', { Class: 'AccountItem ListItem' }, Check, Label, El('span', { Class: 'AcctStatus' }));
        Check.addEventListener('click', Event => { Event.stopPropagation(); ToggleAccount(Index); });
        Row.addEventListener('click', Event => OnAccountClick(Event, Index));
        return Row;
    }));
    ApplySelection();
    ApplyAccountStatus();
}

// Plain click = only this one (click again to clear). Ctrl+click = add/remove one.
// Shift+click = range from the last clicked row. Checkbox = toggle one.
function OnAccountClick(Event, Index) {
    const Name = State.Accounts[Index].Username;
    if (Event.shiftKey && State.SelectionAnchor >= 0) {
        const Low = Math.min(State.SelectionAnchor, Index), High = Math.max(State.SelectionAnchor, Index);
        if (!Event.ctrlKey) State.Selected.clear();
        for (let K = Low; K <= High; K++) State.Selected.add(State.Accounts[K].Username);
    } else if (Event.ctrlKey) {
        ToggleAccount(Index);
        return;
    } else {
        const OnlyThis = State.Selected.size === 1 && State.Selected.has(Name);
        State.Selected.clear();
        if (!OnlyThis) State.Selected.add(Name);
        State.SelectionAnchor = Index;
    }
    ApplySelection();
    SaveSelection();
}

function ToggleAccount(Index) {
    const Name = State.Accounts[Index].Username;
    if (State.Selected.has(Name)) State.Selected.delete(Name);
    else State.Selected.add(Name);
    State.SelectionAnchor = Index;
    ApplySelection();
    SaveSelection();
}

export function ToggleSelectAll() {
    const AllSelected = State.Accounts.length > 0 && State.Selected.size >= State.Accounts.length;
    State.Selected.clear();
    if (!AllSelected) State.Accounts.forEach(A => State.Selected.add(A.Username));
    State.SelectionAnchor = -1;
    ApplySelection();
    SaveSelection();
}

export const SelectedInListOrder = () => State.Accounts.map(A => A.Username).filter(Name => State.Selected.has(Name));

export function ApplySelection() {
    ById('AccountList').querySelectorAll('.ListItem').forEach((Row, Index) => {
        Row.classList.toggle('Selected', State.Selected.has(State.Accounts[Index].Username));
    });
    const Count = State.Selected.size;
    ById('SelectionCount').textContent = Count ? ` (${Count} SELECTED)` : '';
    ById('SelectAllBtn').textContent = (State.Accounts.length > 0 && Count >= State.Accounts.length) ? 'CLEAR' : 'SELECT ALL';
    if (!State.BatchRunning) ById('LaunchBtn').textContent = Count > 1 ? `LAUNCH ${Count} SELECTED` : 'LAUNCH SELECTED';
}

export function ApplyAccountStatus() {
    ById('AccountList').querySelectorAll('.ListItem').forEach((Row, Index) => {
        const Status = State.AccountStatus[State.Accounts[Index].Username];
        const Cell = Row.querySelector('.AcctStatus');
        Cell.className = 'AcctStatus' + (Status ? ' ' + Status.State : '');
        Cell.textContent = Status ? Status.Text : '';
        Cell.title = (Status && Status.Title) || '';
    });
}

export function RestoreSelection(Usernames) {
    State.Selected = new Set((Usernames || []).filter(Name => State.Accounts.some(A => A.Username === Name)));
    ApplySelection();
}

function SaveSelection() {
    Api.UpdateSetting('SelectedAccounts', SelectedInListOrder()).catch(ReportError);
}

export async function AddAccount() {
    const Result = await Api.AddAccount();
    if (Result && Result.Error) ShowLaunchError(Result.Error);
}

export async function RemoveSelectedAccounts() {
    const Names = SelectedInListOrder();
    if (!Names.length) return;
    const Prompt = Names.length === 1
        ? `Remove @${Names[0]}? You will need to sign in again to add it back.`
        : `Remove these ${Names.length} accounts? You will need to sign in again to add them back.`;
    if (!window.confirm(Prompt)) return;
    await Api.RemoveAccounts(Names);
    State.Selected.clear();
    State.SelectionAnchor = -1;
    State.AccountStatus = {};
    await RefreshAccounts();
}
