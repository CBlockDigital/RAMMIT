// The boxes that appear under a launch method (Game URL, Place ID, Job ID, VIP link) plus the
// Players / Ping server filters. Shared by the main window and the config wizard.
//
// Params use the backend's public keys: Url, PlaceId, JobId, PlayerMode, PingMode, MinPlayers, MaxPlayers.

import { Api } from './Bridge.js';
import { BuildSelect, InitSelect, SetSelectValue, GetSelectValue } from './Select.js';
import { El, ById, Debounce, DigitsOnly } from './Dom.js';

export const FilterMethods = ['Game URL', 'Place ID'];
const PlayerOptions = [
    { Value: 'any', Label: 'Any' }, { Value: 'smallest', Label: 'Smallest Server' },
    { Value: 'biggest', Label: 'Biggest (Non-Full)' }, { Value: 'min_only', Label: 'Min Players' },
    { Value: 'max_only', Label: 'Max Players' }, { Value: 'range', Label: 'Player Range' },
];
const PingOptions = [{ Value: 'any', Label: 'Any' }, { Value: 'lowest', Label: 'Lowest Ping' }, { Value: 'highest', Label: 'Highest Ping' }];

export const PlaceIdFromUrl = Url => { const M = String(Url || '').match(/roblox\.com\/games\/(\d+)/i); return M ? M[1] : null; };

// Options: { Wizard: bool (labels above boxes), OnChange(), OnResize() }
export function CreateLaunchForm(Container, Options = {}) {
    const Wizard = !!Options.Wizard;
    const OnChange = Options.OnChange || (() => {});
    const OnResize = Options.OnResize || (() => {});
    let Method = 'Home';
    let MaxPlayersCap = 0;   // the game's maxPlayers, 0 = unknown
    let PlayerMode = 'any';

    const Cap = () => (MaxPlayersCap > 0 ? MaxPlayersCap - 1 : 999);
    const Label = (Text, Style) => El('label', Wizard ? { Text } : { Class: 'LaunchOptionLabel', Text, Style });
    const Input = (Id, Placeholder, Style) => El('input', {
        Type: 'text', Id, Placeholder, Class: Wizard ? '' : 'LaunchInput', Style: Wizard ? '' : Style, MaxLength: 300,
    });

    const FetchMaxPlayers = Debounce(PlaceId => {
        if (!PlaceId || !/^\d+$/.test(PlaceId)) { MaxPlayersCap = 0; ReclampPlayers(); return; }
        Api.GetGameMaxPlayers(PlaceId).then(Max => { MaxPlayersCap = Max || 0; ReclampPlayers(); }).catch(() => { MaxPlayersCap = 0; });
    }, 400);

    function CurrentPlaceId() {
        if (ById('PlaceIdInput')) return ById('PlaceIdInput').value.trim();
        if (ById('UrlInput')) return PlaceIdFromUrl(ById('UrlInput').value);
        return null;
    }

    function BuildFilters() {
        const PlayerSel = BuildSelect('PlayerModeSelect', PlayerOptions);
        const PingSel = BuildSelect('PingModeSelect', PingOptions, Wizard ? '' : 'margin-bottom:10px');
        InitSelect(PlayerSel, Mode => { RenderPlayerFields(Mode); OnChange(); OnResize(); }, OnResize);
        InitSelect(PingSel, () => { OnChange(); OnResize(); }, OnResize);
        return [Label('Players', 'margin-top:10px'), PlayerSel, El('div', { Id: 'PlayerSubFields' }),
                Label('Ping', 'margin-top:10px'), PingSel];
    }

    function RenderPlayerFields(Mode, Values = {}) {
        const Sub = ById('PlayerSubFields');
        if (!Sub) return;
        PlayerMode = Mode;
        const CapText = MaxPlayersCap > 0 ? ` (${Cap()})` : '';
        const Rows = [];
        if (Mode === 'min_only') {
            Rows.push(El('div', { Style: 'margin-top:8px' }, Input('MinPlayersInput', 'Min Players (0)')));
        } else if (Mode === 'max_only') {
            Rows.push(El('div', { Style: 'margin-top:8px' }, Input('MaxPlayersInput', 'Max Players' + CapText)));
        } else if (Mode === 'range') {
            Rows.push(El('div', { Style: 'display:flex; gap:8px; margin-top:8px' },
                Input('MinPlayersInput', 'Min (0)', 'flex:1'), Input('MaxPlayersInput', 'Max' + CapText, 'flex:1')));
        }
        Sub.replaceChildren(...Rows);
        if (Wizard) Sub.querySelectorAll('input').forEach(I => { I.style.flex = '1'; });
        const MinEl = ById('MinPlayersInput'), MaxEl = ById('MaxPlayersInput');
        if (MinEl && Values.MinPlayers) MinEl.value = Values.MinPlayers;
        if (MaxEl && Values.MaxPlayers) MaxEl.value = Values.MaxPlayers;
        [MinEl, MaxEl].forEach(El2 => El2 && El2.addEventListener('input', () => { ClampPlayers(); OnChange(); }));
    }

    function ClampPlayers() {
        const MinEl = ById('MinPlayersInput'), MaxEl = ById('MaxPlayersInput');
        [MinEl, MaxEl].forEach(Box => {
            if (!Box) return;
            DigitsOnly(Box);
            const Value = parseInt(Box.value, 10);
            if (!isNaN(Value) && Value > Cap()) Box.value = Cap();
        });
        if (MinEl && MaxEl && MinEl.value !== '' && MaxEl.value !== '') {
            const Min = parseInt(MinEl.value, 10), Max = parseInt(MaxEl.value, 10);
            if (Min > Max) MaxEl.value = Min;
        }
    }

    function ReclampPlayers() {
        ClampPlayers();
        const MaxEl = ById('MaxPlayersInput');
        if (MaxEl) MaxEl.placeholder = (PlayerMode === 'range' ? 'Max' : 'Max Players') + (MaxPlayersCap > 0 ? ` (${Cap()})` : '');
    }

    // Draw the boxes for a method and fill them from Params.
    function Render(NewMethod, Params = {}) {
        Method = NewMethod;
        const Nodes = [];
        if (Method === 'Game URL') {
            if (Wizard) Nodes.push(Label('Game URL'));
            Nodes.push(Input('UrlInput', 'https://www.roblox.com/games/...'), ...BuildFilters());
        } else if (Method === 'Place ID') {
            if (Wizard) Nodes.push(Label('Place ID'));
            Nodes.push(Input('PlaceIdInput', 'Place ID'), ...BuildFilters());
        } else if (Method === 'Place ID + Job ID') {
            if (Wizard) Nodes.push(Label('Place ID'));
            Nodes.push(Input('PlaceIdInput', 'Place ID'));
            if (Wizard) Nodes.push(Label('Job ID'));
            Nodes.push(Input('JobIdInput', 'Job ID', 'margin-bottom:10px'));
        } else if (Method === 'VIP Link') {
            if (Wizard) Nodes.push(Label('VIP Link'));
            Nodes.push(Input('VipUrlInput', 'VIP Server Link', 'margin-bottom:10px'));
        }
        Container.replaceChildren(...Nodes);

        const Fill = (Id, Value) => { const Box = ById(Id); if (Box && Value) Box.value = Value; };
        Fill('UrlInput', Method === 'Game URL' ? Params.Url : '');
        Fill('VipUrlInput', Method === 'VIP Link' ? Params.Url : '');
        Fill('PlaceIdInput', Params.PlaceId);
        Fill('JobIdInput', Params.JobId);
        if (ById('PlayerModeSelect')) {
            const Mode = PlayerOptions.some(O => O.Value === Params.PlayerMode) ? Params.PlayerMode : 'any';
            SetSelectValue(ById('PlayerModeSelect'), Mode);
            SetSelectValue(ById('PingModeSelect'), PingOptions.some(O => O.Value === Params.PingMode) ? Params.PingMode : 'any');
            RenderPlayerFields(Mode, Params);
        }
        Container.querySelectorAll('#UrlInput, #PlaceIdInput, #JobIdInput, #VipUrlInput').forEach(Box => {
            Box.addEventListener('input', () => {
                OnChange();
                if (Box.id === 'UrlInput' || Box.id === 'PlaceIdInput') FetchMaxPlayers(CurrentPlaceId());
            });
        });
        MaxPlayersCap = 0;
        if (FilterMethods.includes(Method)) FetchMaxPlayers(CurrentPlaceId());
        OnResize();
    }

    function GetParams() {
        const Params = {};
        const Value = Id => (ById(Id) ? ById(Id).value.trim() : undefined);
        if (Method === 'Game URL') Params.Url = Value('UrlInput');
        else if (Method === 'VIP Link') Params.Url = Value('VipUrlInput');
        if (Method === 'Place ID' || Method === 'Place ID + Job ID') Params.PlaceId = Value('PlaceIdInput');
        if (Method === 'Place ID + Job ID') Params.JobId = Value('JobIdInput');
        if (ById('PlayerModeSelect')) {
            Params.PlayerMode = GetSelectValue(ById('PlayerModeSelect'));
            Params.PingMode = GetSelectValue(ById('PingModeSelect'));
            if (Value('MinPlayersInput')) Params.MinPlayers = Value('MinPlayersInput');
            if (Value('MaxPlayersInput')) Params.MaxPlayers = Value('MaxPlayersInput');
        }
        Object.keys(Params).forEach(Key => Params[Key] === undefined && delete Params[Key]);
        return Params;
    }

    return { Render, GetParams, get Method() { return Method; } };
}
