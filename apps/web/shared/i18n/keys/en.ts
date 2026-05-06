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
    selectAll: "Select all",
    deselectAll: "Deselect all",
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
    errorGeneric: "{message}",
    errorProtectionFallback: "an enterprise WAF",
    thinking: "…thinking",
    headerDone: "done",
    headerDone_one: "done",
    headerDone_other: "done",
    headerStreaming: "streaming",
    headerErrored: "errored",
    headerElapsed: "elapsed",
    reconnecting: "Reconnecting…",
    connecting: "Connecting…",
    ariaMissionRegion: "Mission status updates",
    ariaMissionStarted: "Mission started with {count} URLs",
    ariaMissionStarted_one: "Mission started with 1 URL",
    ariaMissionStarted_other: "Mission started with {count} URLs",
    ariaLaneTerminal: "Lane {url} {status}",
    ariaMissionComplete: "{succeeded} of {total} succeeded",
    ariaMissionFailed: "Mission failed: {message}",
    newDescriptionMission: "New description-mode mission",
    descriptionPlaceholder: "Describe what you need…",
    searching: "Searching… {count} found",
    searching_one: "Searching… 1 found",
    searching_other: "Searching… {count} found",
    discoveryComplete: "{count} URLs found",
    discoveryComplete_one: "1 URL found",
    discoveryComplete_other: "{count} URLs found",
    approveNUrls: "Approve {count} URLs",
    approveNUrls_one: "Approve 1 URL",
    approveNUrls_other: "Approve {count} URLs",
    selectedOf: "{selected} of {total}",
    skipApprovalForFutureSearches: "Skip approval for this mission's future searches",
    refineQuery: "Refine query",
    querySpecificity:
      "Query needs more specificity. Try adding a domain, timeframe, or a concrete entity.",
    searchPaused: "Search paused — Tavily returned {status}.",
    noResults: "No results for this query.",
    edited: "edited",
  },
  validation: {
    urlRequired: "URL required",
    urlTooLong: "URL too long",
    urlInvalid: "URL invalid",
    missionFailed: "Mission failed",
    missionUrlsRequired: "Add at least one URL",
    missionUrlsTooMany: "Maximum 20 URLs per mission",
    missionUrlsInvalid: "One or more URLs are invalid",
    queryRequired: "Query required",
    queryTooLong: "Query too long",
  },
} as const;

export type Translations = typeof EN;
export type Namespace = keyof Translations;
export type Keys<N extends Namespace> = keyof Translations[N];
