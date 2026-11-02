// The custom drop-down used everywhere (markup: .CustomSelect > .CustomSelectTrigger + .CustomSelectOptions).
// Value lives in the element's data-value attribute.

let OutsideClickBound = false;
const BoundSelects = new WeakSet();

export function CloseAllSelects(Except) {
    document.querySelectorAll('.CustomSelect.Open').forEach(Sel => { if (Sel !== Except) Sel.classList.remove('Open'); });
}

// OnChange(Value) fires only when the user picks an option. OnOpen() fires as the list opens.
export function InitSelect(Sel, OnChange, OnOpen) {
    if (!Sel || BoundSelects.has(Sel)) return;
    BoundSelects.add(Sel);
    Sel.querySelector('.CustomSelectTrigger').addEventListener('click', Event => {
        Event.stopPropagation();
        CloseAllSelects(Sel);
        const Opening = !Sel.classList.contains('Open');
        Sel.classList.toggle('Open');
        if (Opening && OnOpen) OnOpen();
    });
    Sel.querySelector('.CustomSelectOptions').addEventListener('click', Event => {
        const Option = Event.target.closest('.CustomSelectOption');
        if (!Option) return;
        Event.stopPropagation();
        SetSelectValue(Sel, Option.dataset.value);
        Sel.classList.remove('Open');
        if (OnChange) OnChange(Option.dataset.value);
    });
    if (!OutsideClickBound) {
        OutsideClickBound = true;
        document.addEventListener('click', () => CloseAllSelects(null));
    }
}

// Sets the value and label. Looks options up by comparison, never by building a selector from data.
export function SetSelectValue(Sel, Value) {
    if (!Sel) return false;
    const Option = [...Sel.querySelectorAll('.CustomSelectOption')].find(O => O.dataset.value === Value);
    if (!Option) return false;
    Sel.dataset.value = Value;
    const Label = Sel.querySelector('.CustomSelectText');
    Label.textContent = Option.dataset.label || Option.textContent;  // name only, never the row's swatch
    return true;
}

export const GetSelectValue = Sel => (Sel ? Sel.dataset.value : undefined);

// Options: [{ Value, Label, Swatch?: [Background, Card, Accent, Text] }]
export function SetSelectOptions(Sel, Options) {
    const List = Sel.querySelector('.CustomSelectOptions');
    List.replaceChildren(...Options.map(Opt => {
        const Item = document.createElement('div');
        Item.className = 'CustomSelectOption';
        Item.dataset.value = Opt.Value;
        Item.dataset.label = Opt.Label;
        if (Opt.Swatch) {
            const Swatch = document.createElement('span');
            Swatch.className = 'ThemeSwatch';
            // CSSOM setProperty: an invalid colour is simply ignored (and the server validated it).
            Opt.Swatch.slice(0, 4).forEach((Color, Index) => Swatch.style.setProperty('--S' + Index, Color));
            Item.append(Swatch);
        }
        const Name = document.createElement('span');
        Name.textContent = Opt.Label;
        Item.append(Name);
        if (Opt.Title) Item.title = Opt.Title;
        return Item;
    }));
}

// Generic markup builder for drop-downs created from JS.
export function BuildSelect(Id, Options, Style) {
    const Sel = document.createElement('div');
    Sel.className = 'CustomSelect';
    Sel.id = Id;
    if (Style) Sel.style.cssText = Style;
    const Trigger = document.createElement('div');
    Trigger.className = 'CustomSelectTrigger';
    const Text = document.createElement('span');
    Text.className = 'CustomSelectText';
    const Arrow = document.createElement('span');
    Arrow.className = 'CustomSelectArrow';
    Arrow.textContent = '▼';
    Trigger.append(Text, Arrow);
    const List = document.createElement('div');
    List.className = 'CustomSelectOptions';
    Sel.append(Trigger, List);
    SetSelectOptions(Sel, Options);
    SetSelectValue(Sel, Options[0].Value);
    return Sel;
}
