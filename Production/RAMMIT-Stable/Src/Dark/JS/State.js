// Shared UI state for the main window. Modules read and write it directly; keep it small.
export const State = {
    Accounts: [],                 // [{ Username, DisplayName, Locked }] in list order
    Selected: new Set(),          // usernames ticked for launch
    SelectionAnchor: -1,          // row index for shift-click ranges
    AccountStatus: {},            // username -> { State, Text, Title }
    Configs: [],                  // [{ Name, Method, Params }]
    SelectedConfig: '',           // config name
    BatchRunning: false,
    SettingsCollapsed: false,
    ToursDone: new Set(),
};
