// Themed tooltips (the CBlock tooltip), instead of the browser's own.
// Any element with data-tooltip="..." or a title="..." gets one: a title is moved into data-tooltip when hovered,
// so the native tooltip never shows and no existing title has to change. A line break in the text starts a new line.
// The text is shown as plain text (textContent), never as HTML. While a tooltip shows, a changed title or
// data-tooltip on its element (e.g. + ADD turning into RENEW) updates it straight away.
// Look: .Tooltip in Style.css (colours from the theme; --TooltipRadius rounds it, 0 by default).

const OffsetX = 12, OffsetY = 16;  // from the cursor
const FlipGap = 12;                // from the cursor when flipped to its left / above it
let Tip = null;
let Target = null;
let LastX = 0, LastY = 0;
const Watch = new MutationObserver(() => { if (Target) Refresh(); });

// Takes over a title (also one set again later, e.g. an account's status) and returns the text to show.
// Screen readers used the title as the element's name (an icon-only button) or its description (anything with text),
// so it moves to aria-label or aria-description, unless the page set that attribute to something else.
function ReadText(Node) {
    if (Node.hasAttribute('title')) {
        const Old = Node.dataset.tooltip;
        const Text = Node.getAttribute('title');
        Node.dataset.tooltip = Text;
        Node.removeAttribute('title');
        const Attr = Node.textContent.trim() ? 'aria-description' : 'aria-label';
        const Ours = !Node.hasAttribute(Attr) || Node.getAttribute(Attr) === Old;
        if (Ours && Text) Node.setAttribute(Attr, Text);
        else if (Ours) Node.removeAttribute(Attr);
    }
    return Node.dataset.tooltip || '';
}

// Right of / below the cursor; where that would leave the window, the other side of the cursor instead.
function Place() {
    const Width = Tip.offsetWidth, Height = Tip.offsetHeight;
    let X = LastX + OffsetX, Y = LastY + OffsetY;
    if (X + Width > innerWidth) X = LastX - FlipGap - Width;
    if (Y + Height > innerHeight) Y = LastY - FlipGap - Height;
    Tip.style.left = Math.max(0, X) + 'px';
    Tip.style.top = Math.max(0, Y) + 'px';
}

function Show(Node) {
    const Text = ReadText(Node);
    if (!Text) { Hide(); return; }
    if (Target !== Node) {
        Watch.disconnect();
        Watch.observe(Node, { attributes: true, attributeFilter: ['title', 'data-tooltip'] });
    }
    Target = Node;
    Tip.textContent = Text;
    Place();  // before it fades in, so it never flashes where it was last time
    Tip.classList.add('Visible');
}

// The element under the cursor changed its text, or the cursor moved: keep the tooltip right.
function Refresh() {
    if (!Target.isConnected) { Hide(); return; }  // re-drawn under the cursor: no mouseout ever comes
    const Text = ReadText(Target);
    if (!Text) { Hide(); return; }
    if (Tip.textContent !== Text) Tip.textContent = Text;
    Place();
}

function Hide() {
    Target = null;
    Watch.disconnect();
    if (Tip) Tip.classList.remove('Visible');
}

export function InitTooltips() {
    Tip = document.createElement('div');
    Tip.className = 'Tooltip';
    Tip.setAttribute('role', 'tooltip');
    document.body.append(Tip);

    document.addEventListener('mouseover', Event => {
        LastX = Event.clientX; LastY = Event.clientY;
        const Node = Event.target.closest('[data-tooltip], [title]');
        if (Node) Show(Node); else if (Target) Hide();
    });
    document.addEventListener('mousemove', Event => {
        LastX = Event.clientX; LastY = Event.clientY;
        if (Target) Refresh();
    });
    document.addEventListener('mouseout', Event => { if (!Event.relatedTarget) Hide(); });  // left the window
    document.addEventListener('mousedown', Hide);
    document.addEventListener('scroll', Hide, true);
    window.addEventListener('blur', Hide);
}
