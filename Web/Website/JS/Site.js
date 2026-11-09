// RAMMIT website: hero launch replay, nav border.

(function () {
    const ReduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    // ===== NO DRAGGING =====
    // Images and links can't be dragged out of the page (CSS covers Chromium/Safari; this covers Firefox too).
    document.addEventListener('dragstart', Event => Event.preventDefault());

    // ===== NAV =====
    const Nav = document.getElementById('Nav');
    const UpdateNav = () => Nav.classList.toggle('IsScrolled', window.scrollY > 8);
    UpdateNav();
    window.addEventListener('scroll', UpdateNav, { passive: true });

    // ===== HERO LAUNCH REPLAY =====
    // Frames and timings come from the real capture (capture/screenshots/manifest.json):
    // Ms is the time since LAUNCH 3 SELECTED was pressed.
    const Player = document.getElementById('LaunchPlayer');
    const PressRing = document.getElementById('PressRing');
    const Status = document.getElementById('LaunchStatus');
    if (!Player) return;

    const IdleMs = 2400;
    const HoldMs = 3200;
    const Frames = [
        { File: 'main-idle.png', Ms: -IdleMs, Text: 'RUNNING: 0 / 5' },
        { File: 'launch-f000.png', Ms: 0, Text: 'Launching 1 / 3…' },
        { File: 'launch-f001.png', Ms: 337, Text: 'Launching 1 / 3…' },
        { File: 'launch-f002.png', Ms: 1483, Text: 'Launching 2 / 3…' },
        { File: 'launch-f003.png', Ms: 1763, Text: 'Launching 2 / 3…' },
        { File: 'launch-f004.png', Ms: 2058, Text: 'Launching 2 / 3…' },
        { File: 'launch-f005.png', Ms: 3209, Text: 'Launching 3 / 3…' },
        { File: 'launch-f006.png', Ms: 4006, Text: 'Launching 3 / 3…' },
        { File: 'launch-f007.png', Ms: 5189, Text: 'Launched 3/3' },
        { File: 'launch-f008.png', Ms: 5532, Text: 'Launched 3/3' }
    ];
    const LoopMs = Frames[Frames.length - 1].Ms + HoldMs + IdleMs;

    const SetStatus = (Text) => {
        Status.textContent = Text;
        Status.classList.toggle('IsDone', Text.startsWith('Launched'));
    };

    if (ReduceMotion) {
        Player.querySelector('.LaunchFrame').src = 'Assets/Shots/main-launched.png';
        SetStatus('Launched 3/3');
        return;
    }

    // Build the frame stack once every image has loaded, so swaps never flash.
    const FirstImage = Player.querySelector('.LaunchFrame');
    const Images = [FirstImage];
    const Loads = Frames.slice(1).map(Frame => new Promise(Resolve => {
        const Img = new Image();
        Img.className = 'LaunchFrame';
        Img.alt = '';
        Img.decoding = 'async';
        Img.onload = Img.onerror = Resolve;
        Img.src = 'Assets/Shots/' + Frame.File;
        Images.push(Img);
    }));

    Promise.all(Loads).then(() => {
        Images.slice(1).forEach(Img => Player.insertBefore(Img, PressRing));

        let ActiveIndex = 0;
        let StartTime = performance.now();
        let PressedThisLoop = false;

        const Show = (Index) => {
            if (Index === ActiveIndex) return;
            Images[ActiveIndex].classList.remove('IsActive');
            Images[Index].classList.add('IsActive');
            ActiveIndex = Index;
            SetStatus(Frames[Index].Text);
        };

        // Pause the loop while the hero is off screen.
        let Running = false;
        let RafId = 0;

        const Tick = (Now) => {
            if (!Running) return;
            const Elapsed = (Now - StartTime) % LoopMs;
            const SinceLaunch = Elapsed - IdleMs;

            if (SinceLaunch < 0) {
                PressedThisLoop = false;
                Show(0);
            } else {
                if (!PressedThisLoop) {
                    PressedThisLoop = true;
                    PressRing.classList.remove('IsPressed');
                    void PressRing.offsetWidth;
                    PressRing.classList.add('IsPressed');
                }
                let Index = 1;
                for (let I = 1; I < Frames.length; I++) {
                    if (SinceLaunch >= Frames[I].Ms) Index = I;
                }
                Show(Index);
            }
            RafId = requestAnimationFrame(Tick);
        };

        const Start = () => {
            if (Running) return;
            Running = true;
            StartTime = performance.now();
            RafId = requestAnimationFrame(Tick);
        };

        if ('IntersectionObserver' in window) {
            new IntersectionObserver(Entries => {
                Entries.forEach(Entry => {
                    if (Entry.isIntersecting) Start();
                    else {
                        Running = false;
                        cancelAnimationFrame(RafId);
                    }
                });
            }).observe(Player);
        } else {
            Start();
        }
    });
})();
