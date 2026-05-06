"use client";

import { useEffect, useMemo } from "react";

import type { DiscoveredUrl } from "@/entities/mission/types";
import { useApprovalState } from "@/features/run-mission";

import { BulkToolbar } from "./bulk-toolbar";
import { DomainFilterStrip } from "./domain-filter-strip";
import { UrlRow } from "./url-row";

/**
 * Inline approval gate rendered inside the mission slide-over while the
 * mission is in `awaiting_approval` phase. Composes the domain-filter
 * strip, the URL-row list, and the bulk toolbar.
 *
 * Submit (Cmd+Enter) POSTs the user-edited subset to
 * `POST /api/missions/{id}/approve`. Selection seeds from the agent's
 * own confidence (rows with `score >= 0.4` start checked).
 *
 * `isStreaming` is wired in for completeness (the spec disables Approve
 * during streaming) but the gate today only renders post-`discovery_complete`,
 * so it's effectively always `false`. Keeping the prop guards future
 * experiments where the gate renders mid-stream.
 */
export function ApprovalGate({
  missionId,
  discoveredUrls,
  isStreaming = false,
}: {
  missionId: string;
  discoveredUrls: DiscoveredUrl[];
  isStreaming?: boolean;
}) {
  const state = useApprovalState(missionId, discoveredUrls);

  const visible = useMemo(() => {
    let rows = discoveredUrls.slice();
    if (state.domainFilter !== null) {
      const filter = state.domainFilter;
      rows = rows.filter((u) => {
        try {
          return new URL(u.url).hostname === filter;
        } catch {
          return false;
        }
      });
    }
    if (state.sortBy === "score") {
      rows.sort((a, b) => b.score - a.score);
    } else {
      rows.sort((a, b) => {
        try {
          return new URL(a.url).hostname.localeCompare(new URL(b.url).hostname);
        } catch {
          return a.url.localeCompare(b.url);
        }
      });
    }
    return rows;
  }, [discoveredUrls, state.domainFilter, state.sortBy]);

  // Cmd+A toggles all selected/deselected. Cmd+Enter submits when valid.
  useEffect(() => {
    function handleShortcut(event: KeyboardEvent) {
      if (!(event.metaKey || event.ctrlKey)) return;
      if (event.key === "a") {
        event.preventDefault();
        state.toggleAll();
      } else if (event.key === "Enter" && !isStreaming && state.selected.size > 0) {
        event.preventDefault();
        void state.submit();
      }
    }
    window.addEventListener("keydown", handleShortcut);
    return () => window.removeEventListener("keydown", handleShortcut);
  }, [isStreaming, state]);

  return (
    <div className="flex flex-col">
      <DomainFilterStrip
        urls={discoveredUrls}
        active={state.domainFilter}
        onChange={state.setDomainFilter}
      />
      <ul className="flex flex-col">
        {visible.map((u) => (
          <UrlRow
            key={u.url}
            url={u}
            checked={state.selected.has(u.url)}
            edited={state.edits[u.url]}
            onToggle={() => state.toggle(u.url)}
            onEdit={(next) => state.setEdit(u.url, next)}
          />
        ))}
      </ul>
      <BulkToolbar
        selectedCount={state.selected.size}
        totalCount={discoveredUrls.length}
        canSubmit={!isStreaming && state.selected.size > 0}
        skipApproval={state.skipApproval}
        onSkipApprovalChange={state.setSkipApproval}
        onSubmit={() => void state.submit()}
        onToggleAll={state.toggleAll}
        submitting={state.submitting}
      />
    </div>
  );
}
