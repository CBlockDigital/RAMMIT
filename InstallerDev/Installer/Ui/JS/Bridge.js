// The only place that talks to Python (InstallerApi.py). Every backend method is reached as
// Api.MethodName(...args) and always returns a Promise (same pattern as RAMMIT's Bridge.js).
//
// Python -> JS events arrive through window.InstallerEvents (see On()): Progress, UninstallProgress, Done, Failed.

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

const Handlers = {};
window.InstallerEvents = {
    Progress: Payload => Fire('Progress', Payload),
    UninstallProgress: Payload => Fire('UninstallProgress', Payload),
    Done: Payload => Fire('Done', Payload),
    Failed: Payload => Fire('Failed', Payload),
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
