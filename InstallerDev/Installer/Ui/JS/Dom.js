// Small DOM helpers (RAMMIT's Src/Dark/JS/Dom.js, trimmed to what the installer uses).
// Build UI with El(...) + textContent. Never put data (paths, versions, messages) into innerHTML.

export const ById = Id => document.getElementById(Id);

// El('em', { Class: 'Path', Text: 'C:\\RAMMIT' }, ...Children)
export function El(Tag, Props = {}, ...Children) {
    const Node = document.createElement(Tag);
    if (Props.Class) Node.className = Props.Class;
    if (Props.Id) Node.id = Props.Id;
    if (Props.Text !== undefined) Node.textContent = String(Props.Text);
    if (Props.Title) Node.title = String(Props.Title);
    if (Props.Value !== undefined) Node.dataset.value = Props.Value;
    Children.forEach(Child => Child && Node.append(Child));
    return Node;
}

// Fills Target with lines of text. Each line is an array of parts: a string, or { Em: 'text' } for <em>,
// or { Strong: 'text' }. An empty line array gives a blank line (Test1's <br><br>).
export function SetLines(Target, Lines) {
    const Nodes = [];
    Lines.forEach((Line, Index) => {
        if (Index > 0) Nodes.push(document.createElement('br'));
        Line.forEach(Part => {
            if (typeof Part === 'string') Nodes.push(document.createTextNode(Part));
            else if (Part.Em !== undefined) Nodes.push(El('em', { Text: Part.Em, Class: Part.Class }));
            else if (Part.Strong !== undefined) Nodes.push(El('strong', { Text: Part.Strong, Class: Part.Class }));
        });
    });
    Target.replaceChildren(...Nodes);
}
