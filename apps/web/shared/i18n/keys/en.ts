/**
 * English translations. The single source of truth for the in-process i18n
 * primitive. Keys live under flat namespaces; plural variants use the
 * `_one` / `_other` suffix and are selected by the `count` parameter at
 * resolve time.
 *
 * Adding a new key:
 *   1. Add it under the appropriate namespace below.
 *   2. The literal type of `EN` propagates through `Translations`, `Keys<N>`,
 *      and `Params<N, K>` automatically — no separate interface to maintain.
 */
export const EN = {
  common: {
    brandName: "Autumn",
    searchOrCommand: "Search or run a command",
    nothingFound: "No matches",
    recent: "Recent",
    actions: "Actions",
    account: "Account",
    toggleSidebar: "Toggle sidebar",
    signOut: "Sign out",
    goTo: "Go to",
  },
  mission: {
    urlPlaceholder: "Paste a URL — ⌘↩ to run",
    yourMissions: "Your missions",
    newMission: "New URL mission",
    newMultiUrlMission: "New multi-URL mission",
    multiUrlHelp: "One URL per line. 1 to 20 URLs.",
    multiUrlPlaceholder: "https://...\nhttps://...",
    urlCount: "URLs",
    urlCount_one: "URL",
    urlCount_other: "URLs",
    toggleReasoning: "Toggle reasoning",
    loading: "Loading…",
    noMissions: "No missions yet",
    noMissionsHint: "Paste a URL above or press {shortcut}",
    noMissionsHintPrefix: "Paste a URL above or press",
    status_running: "Running",
    status_pending: "Queued",
    status_succeeded: "Done",
    status_failed: "Failed",
    status_cancelled: "Cancelled",
    errorSiteNotSupported:
      "This site uses {protections}. Out of scope for now — try a different URL.",
    errorNotFound: "Page not found at this URL.",
    errorRenderTimeout: "Page took too long to render.",
    errorUpstream: "Upstream returned an error.",
  },
  validation: {
    urlRequired: "URL required",
    urlTooLong: "URL too long",
    urlInvalid: "URL invalid",
    missionFailed: "Mission failed",
    missionUrlsRequired: "Add at least one URL",
    missionUrlsTooMany: "Maximum 20 URLs per mission",
    missionUrlsInvalid: "One or more URLs are invalid",
  },
} as const;

export type Translations = typeof EN;
export type Namespace = keyof Translations;
export type Keys<N extends Namespace> = keyof Translations[N];
