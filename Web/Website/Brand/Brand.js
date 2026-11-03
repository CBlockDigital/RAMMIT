// Brand pack page: copy buttons (text selection is off site-wide), nav border, no dragging.

(function () {
    document.addEventListener('dragstart', Event => Event.preventDefault());

    const Nav = document.getElementById('Nav');
    const UpdateNav = () => Nav.classList.toggle('IsScrolled', window.scrollY > 8);
    UpdateNav();
    window.addEventListener('scroll', UpdateNav, { passive: true });

    if (!navigator.clipboard) return;

    const MakeButton = (Text, Label) => {
        const Button = document.createElement('button');
        Button.type = 'button';
        Button.className = 'CopyButton';
        Button.textContent = 'Copy';
        Button.setAttribute('aria-label', 'Copy ' + Label);
        Button.addEventListener('click', () => {
            navigator.clipboard.writeText(Text).then(() => {
                Button.textContent = 'Copied';
                Button.classList.add('IsCopied');
                setTimeout(() => {
                    Button.textContent = 'Copy';
                    Button.classList.remove('IsCopied');
                }, 1400);
            });
        });
        return Button;
    };

    document.querySelectorAll('.Swatch code').forEach(Code => {
        Code.appendChild(MakeButton(Code.textContent.trim(), Code.textContent.trim()));
    });

    document.querySelectorAll('.CopyRow').forEach(Row => {
        const Text = Row.querySelector('.CopyText').textContent.trim();
        Row.appendChild(MakeButton(Text, Row.querySelector('.CopyName').textContent.trim()));
    });
})();
