"use client";

import { Kbd } from "@/components/ui/kbd";
import { useT } from "@/shared/i18n";

/**
 * Sticky bottom toolbar for the approval gate. Holds the count, the
 * select-all toggle, the skip-approval checkbox, and the primary
 * approve button (Cmd+Enter).
 *
 * Stays inside the slide-over (sticky bottom-0) — not the viewport — so
 * it never floats over unrelated UI when the user scrolls outside the
 * gate.
 */
export function BulkToolbar({
  selectedCount,
  totalCount,
  canSubmit,
  skipApproval,
  onSkipApprovalChange,
  onSubmit,
  onToggleAll,
  submitting,
}: {
  selectedCount: number;
  totalCount: number;
  canSubmit: boolean;
  skipApproval: boolean;
  onSkipApprovalChange: (value: boolean) => void;
  onSubmit: () => void;
  onToggleAll: () => void;
  submitting: boolean;
}) {
  const t = useT();
  const allSelected = selectedCount === totalCount && totalCount > 0;
  return (
    <div className="sticky bottom-0 flex h-12 items-center gap-3 border-t border-border/50 bg-background/95 px-4 backdrop-blur">
      <span className="font-mono text-[11px] tabular-nums text-muted-foreground">
        {t("mission", "selectedOf", { selected: selectedCount, total: totalCount })}
      </span>
      <span className="flex-1" />
      <button
        type="button"
        onClick={onToggleAll}
        className="text-[11px] text-muted-foreground hover:text-foreground"
      >
        {allSelected ? t("common", "deselectAll") : t("common", "selectAll")}
      </button>
      <label className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
        <input
          type="checkbox"
          checked={skipApproval}
          onChange={(event) => onSkipApprovalChange(event.currentTarget.checked)}
          className="h-3.5 w-3.5 rounded border-border/50"
        />
        {t("mission", "skipApprovalForFutureSearches")}
      </label>
      <button
        type="button"
        disabled={!canSubmit || submitting}
        onClick={onSubmit}
        className="inline-flex h-8 items-center gap-1.5 rounded-md bg-primary px-3 text-[13px] font-medium text-primary-foreground disabled:opacity-50"
      >
        {t("mission", "approveNUrls", { count: selectedCount })}
        <Kbd>⌘↩</Kbd>
      </button>
    </div>
  );
}
