// Small DOM helpers shared by every page.
// Build UI with El(...) + textContent. Never put data (names, URLs, params) into innerHTML.

export const ById = Id => document.getElementById(Id);

// El('span', { Class: 'AcctUser', Text: '(@name)', Title: 'tip' }, ...Children)
export function El(Tag, Props = {}, ...Children) {
    const Node = document.createElement(Tag);
    if (Props.Class) Node.className = Props.Class;
    if (Props.Id) Node.id = Props.Id;
    if (Props.Text !== undefined) Node.textContent = String(Props.Text);
    if (Props.Title) Node.title = String(Props.Title);
    if (Props.Type) Node.type = Props.Type;
    if (Props.Placeholder) Node.placeholder = Props.Placeholder;
    if (Props.Style) Node.style.cssText = Props.Style;
    if (Props.Value !== undefined) Node.dataset.value = Props.Value;
    if (Props.MaxLength) Node.maxLength = Props.MaxLength;
    Children.forEach(Child => Child && Node.append(Child));
    return Node;
}

export function Debounce(Fn, Ms) {
    let Timer = null;
    return (...Args) => {
        clearTimeout(Timer);
        Timer = setTimeout(() => Fn(...Args), Ms);
    };
}

export const Sleep = Ms => new Promise(Resolve => setTimeout(Resolve, Ms));

export const DigitsOnly = Input => { Input.value = Input.value.replace(/[^0-9]/g, ''); };
