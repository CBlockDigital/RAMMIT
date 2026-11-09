// The only place that talks to Python (App/Api.py). Every backend method is reached as
// Api.MethodName(...args) and always returns a Promise.
//
// Python -> JS notifications arrive through window.RammitEvents (see On()).

export async function WaitForApi(RequiredMethod) {
    while (!window.pywebview || !window.pywebview.api || typeof window.pywebview.api[RequiredMethod] !== 'function') {
        await new Promise(Resolve => setTimeout(Resolve, 40));
    }
}

export const Api = new Proxy({}, {
    get: (_Target, Name) => (...Args) => {
        const Fn = window.pywebview && window.pywebview.api && window.pywebview.api[Name];
        if (typeof Fn !== 'function') return Promise.reject(new Error('Backend method missing: ' + String(Name)));
        return Fn(...Args);
    },
});

// Fn(...Args) one call at a time. pywebview runs every call to Python on its own thread, so two calls in flight can
// finish in either order (two resizes would leave the window at the older height). While one runs, only the newest
// arguments wait and are sent when it has finished; older ones are dropped. Errors are ignored, like a resize's.
// A call that never answers stops holding the others up after GiveUpMs (App/WindowSize.py applies resizes under one
// lock, so a late one still lands before the next).
export function OneAtATime(Fn, GiveUpMs = 3000) {
    let Running = false;
    let Waiting = null;
    const Run = (...Args) => {
        if (Running) { Waiting = Args; return; }
        Running = true;
        const GiveUp = new Promise(Resolve => setTimeout(Resolve, GiveUpMs));
        Promise.race([Promise.resolve().then(() => Fn(...Args)), GiveUp]).catch(() => {}).finally(() => {
            Running = false;
            if (Waiting) {
                const Next = Waiting;
                Waiting = null;
                Run(...Next);
            }
        });
    };
    return Run;
}

const Handlers = {};
window.RammitEvents = {
    AccountsChanged: Payload => Fire('AccountsChanged', Payload),
    ConfigsChanged: Payload => Fire('ConfigsChanged', Payload),
    ShowMessage: Payload => Fire('ShowMessage', Payload),
};

function Fire(Event, Payload) {
    (Handlers[Event] || []).forEach(Handler => {
        try { Handler(Payload); } catch (Error) { ReportError(Error); }
    });
}

export function On(Event, Handler) {
    (Handlers[Event] = Handlers[Event] || []).push(Handler);
}

export function ReportError(Error) {
    const Text = String(Error && Error.message ? Error.message : Error);
    try { Api.LogClientError(Text).catch(() => {}); } catch (_) { /* backend not ready */ }
    console.error(Error);
}
