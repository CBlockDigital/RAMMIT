// Themed tooltips (the CBlock tooltip), instead of the browser's own.
// Any element with data-tooltip="..." or a title="..." gets one: a title is moved into data-tooltip when hovered,
// so the native tooltip never shows and no existing title has to change. "\n" in the text starts a new line.
// Look: .Tooltip in Style.css (colours from the theme; --TooltipRadius rounds it, 0 by default).

const OffsetX = 12, OffsetY = 16;  // from the cursor
const FlipGap = 12;                // from the cursor when flipped to its left / above it
let Tip = null;
let Target = null;
let LastX = 0, LastY = 0;

// Takes over a title (also one set again later, e.g. an account's status) and returns the text to show.
function ReadText(Node) {
    if (Node.hasAttribute('title')) {
        Node.dataset.tooltip = Node.getAttribute('title');
        Node.removeAttribute('title');
    }
    return (Node.dataset.tooltip || '').replace(/\\n/g, '\n');
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
    Target = Node;
    Tip.textContent = Text;
    Place();  // before it fades in, so it never flashes where it was last time
    Tip.classList.add('Visible');
}

function Hide() {
    Target = null;
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
        if (!Target) return;
        if (!Target.isConnected) { Hide(); return; }  // re-drawn under the cursor: no mouseout ever comes
        if (Target.hasAttribute('title')) Show(Target); else Place();
    });
    document.addEventListener('mouseout', Event => { if (!Event.relatedTarget) Hide(); });  // left the window
    document.addEventListener('mousedown', Hide);
    document.addEventListener('scroll', Hide, true);
    window.addEventListener('blur', Hide);
}
