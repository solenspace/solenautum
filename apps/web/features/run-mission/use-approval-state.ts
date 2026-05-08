"use client";

import { useCallback, useMemo, useState } from "react";

import type { DiscoveredUrl } from "@/entities/mission/types";

export type SortBy = "score" | "domain";

export interface ApprovalState {
  selected: Set<string>;
  edits: Record<string, string>;
  domainFilter: string | null;
  sortBy: SortBy;
  skipApproval: boolean;
  submitting: boolean;
  submitError: boolean;
  toggle: (url: string) => void;
  toggleAll: () => void;
  setEdit: (url: string, edited: string | null) => void;
  setDomainFilter: (domain: string | null) => void;
  setSortBy: (sort: SortBy) => void;
  setSkipApproval: (value: boolean) => void;
  submit: () => Promise<void>;
}

/**
 * Owns the approval-gate's local state: which URLs are checked, which
 * have been inline-edited, the active domain filter, sort order, and
 * the `skip_approval` toggle. `submit` POSTs the resolved URL list to
 * `POST /api/missions/{id}/approve`.
 *
 * Default selection seeds from `discoveredUrls` filtered to `score >=
 * 0.4` so the user starts with the agent's high-confidence picks
 * pre-checked (per the spec's UX guidance).
 */
export function useApprovalState(
  missionId: string,
  discoveredUrls: DiscoveredUrl[],
): ApprovalState {
  const initialSelection = useMemo(() => {
    const set = new Set<string>();
    for (const u of discoveredUrls) {
      if (u.score >= 0.4) set.add(u.url);
    }
    return set;
  }, [discoveredUrls]);

  const [selected, setSelected] = useState<Set<string>>(initialSelection);
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [domainFilter, setDomainFilter] = useState<string | null>(null);
  const [sortBy, setSortBy] = useState<SortBy>("score");
  const [skipApproval, setSkipApproval] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState(false);

  const toggle = useCallback((url: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(url)) next.delete(url);
      else next.add(url);
      return next;
    });
  }, []);

  const toggleAll = useCallback(() => {
    setSelected((prev) => {
      if (prev.size === discoveredUrls.length) return new Set();
      return new Set(discoveredUrls.map((u) => u.url));
    });
  }, [discoveredUrls]);

  const setEdit = useCallback((url: string, edited: string | null) => {
    setEdits((prev) => {
      const next = { ...prev };
      if (edited === null) delete next[url];
      else next[url] = edited;
      return next;
    });
  }, []);

  const submit = useCallback(async () => {
    setSubmitError(false);
    // Resolve each selected URL through the edits map; an edited URL
    // shadows its original value but inherits the original's selected
    // state (we never re-key edits onto the new URL).
    const urls = Array.from(selected).map((u) => edits[u] ?? u);
    if (urls.length === 0) {
      setSubmitError(true);
      return;
    }
    setSubmitting(true);
    try {
      const response = await fetch(`/api/missions/${missionId}/approve`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ urls, skip_approval: skipApproval }),
      });
      if (!response.ok) setSubmitError(true);
    } catch {
      setSubmitError(true);
    } finally {
      setSubmitting(false);
    }
  }, [missionId, selected, edits, skipApproval]);

  return {
    selected,
    edits,
    domainFilter,
    sortBy,
    skipApproval,
    submitting,
    submitError,
    toggle,
    toggleAll,
    setEdit,
    setDomainFilter,
    setSortBy,
    setSkipApproval,
    submit,
  };
}
