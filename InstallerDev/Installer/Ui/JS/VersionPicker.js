// Test1's searchable version picker (type to filter, "latest" finds the latest), made reusable so the Install
// and Update / Downgrade screens each get one. Markup: .CustomSelect.InstVersionSelect > .InstVersionTrigger
// (.InstVersionPrefix + input .InstVersionInput) + .CustomSelectOptions. The picked version is in data-value.
//
// New:
//   * a branch column: the prefix cell (Test1's "v") shows S (Stable) or D (Dev, a GitHub pre-release) for the
//     picked version, every row shows its own letter under it, and hovering a letter names the branch
//   * the installed version can be listed greyed out (Disabled), so the list reads older / installed / newer
//   * search: "latest", "stable"/"s" and "dev"/"d" filter by tag or branch; digits filter by version
//   * the list can be empty while loading/offline

import { El } from './Dom.js';

export const BranchLetter = Branch => (Branch === 'Dev' ? 'D' : 'S');
const BranchName = Branch => (Branch === 'Dev' ? 'Dev' : 'Stable');

export function CreateVersionPicker(Sel, OnPick) {
    const Input = Sel.querySelector('.InstVersionInput');
    const Prefix = Sel.querySelector('.InstVersionPrefix');
    const List = Sel.querySelector('.CustomSelectOptions');
    let Versions = [];       // [{ Version, Branch, Prerelease, Latest, Installed }]
    let Latest = '';
    let FirstClick = true;

    const Find = Ver => Versions.find(V => V.Version === Ver);
    const Pickable = Ver => { const V = Find(Ver); return !!V && !V.Installed; };
    const Tags = V => [V.Version === Latest ? 'latest' : '', V.Installed ? 'installed' : ''].filter(Boolean);
    const Display = Ver => { const V = Find(Ver); const T = V ? Tags(V) : []; return Ver + (T.length ? ' (' + T.join(', ') + ')' : ''); };

    function ShowBranch(Ver) {
        const Branch = BranchName((Find(Ver) || {}).Branch);
        Prefix.textContent = BranchLetter(Branch);
        Prefix.dataset.branch = Branch;
        Prefix.title = Branch;
    }

    function Matches(V, Q) {
        if (!Q) return true;
        if ('latest'.indexOf(Q) === 0) return V.Version === Latest;
        if ('stable'.indexOf(Q) === 0) return V.Branch !== 'Dev';
        if ('dev'.indexOf(Q) === 0) return V.Branch === 'Dev';
        return V.Version.indexOf(Q.replace(/^v/, '')) !== -1;
    }

    function BuildList(Filter) {
        const Q = (Filter || '').trim().toLowerCase();
        const Rows = Versions.filter(V => Matches(V, Q)).map(V => {
            const Branch = BranchName(V.Branch);
            const Cell = El('span', { Class: 'BranchCell', Text: BranchLetter(Branch), Title: Branch });
            Cell.dataset.branch = Branch;
            const Label = El('span', { Class: 'VersionText', Text: V.Version });
            if (Tags(V).length) Label.append(El('span', { Class: 'VersionTag', Text: '(' + Tags(V).join(', ') + ')' }));
            const Opt = El('div', { Class: 'CustomSelectOption' + (V.Installed ? ' Disabled' : ''), Value: V.Version }, Cell, Label);
            if (V.Installed) Opt.title = "That's the version you have";
            Opt.addEventListener('mousedown', Event => { Event.preventDefault(); if (!V.Installed) Select(V.Version); });
            return Opt;
        });
        if (!Rows.length) Rows.push(El('div', { Class: 'CustomSelectOption Empty', Text: Versions.length ? 'No matching version' : 'No versions loaded' }));
        List.replaceChildren(...Rows);
    }

    function Show(Ver) {
        Input.value = Ver ? Display(Ver) : '';
        ShowBranch(Ver);
    }

    function Select(Ver) {
        Sel.dataset.value = Ver;
        Show(Ver);
        Sel.classList.remove('Open');
        FirstClick = false;
        Input.blur();
        if (OnPick) OnPick(Ver);
    }

    Input.addEventListener('focus', () => {
        if (FirstClick) Input.value = '';
        else {
            Input.value = Sel.dataset.value || '';
            Input.select();
        }
        Sel.classList.add('Open');
        BuildList('');  // the whole list on open (Test1 filtered it to the picked version); typing filters
    });
    Input.addEventListener('input', () => {
        Sel.classList.add('Open');
        BuildList(Input.value);
    });
    Input.addEventListener('blur', () => {
        Sel.classList.remove('Open');
        const Typed = Input.value.trim().replace(/^v/i, '');
        if (Pickable(Typed)) Select(Typed);
        else {
            Show(Sel.dataset.value || '');
            FirstClick = false;
        }
    });
    Input.addEventListener('keydown', Event => {
        if (Event.key !== 'Enter') return;
        const Typed = Input.value.trim().replace(/^v/i, '');
        if (Pickable(Typed)) Select(Typed);
        else Input.blur();
    });
    Prefix.addEventListener('mousedown', Event => { Event.preventDefault(); Input.focus(); });  // the letter opens the list too
    document.addEventListener('click', Event => { if (!Sel.contains(Event.target)) Sel.classList.remove('Open'); });

    return {
        // Keeps the current pick when it is still pickable, otherwise picks Default; '' leaves nothing picked.
        // Default undefined = the latest (or the first pickable version).
        SetVersions(NewVersions, NewLatest, Default) {
            Versions = NewVersions || [];
            Latest = NewLatest || '';
            const Keep = Pickable(Sel.dataset.value) ? Sel.dataset.value : '';
            const Fallback = Default === undefined ? (Pickable(Latest) ? Latest : ((Versions.find(V => !V.Installed) || {}).Version || '')) : '';
            const Pick = Keep || (Default && Pickable(Default) ? Default : Fallback);
            Sel.dataset.value = Pick;
            Show(Pick);
            Input.placeholder = !Versions.length ? 'No versions loaded' : (Pick ? '' : 'Pick a version');
            FirstClick = true;
            BuildList('');
        },
        Value: () => Sel.dataset.value || '',
        Select,
    };
}
