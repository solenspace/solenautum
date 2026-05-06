"use client";

import { Kbd } from "@/components/ui/kbd";
import { useT } from "@/shared/i18n";

/**
 * Empty state for `/missions`. Vertically centered in the main pane (not
 * the viewport), left-aligned within its panel. No illustration, no
 * marketing copy — the action is already visible in the top bar, so the
 * empty state just points at it.
 */
export function EmptyState() {
  const t = useT();
  return (
    <div className="flex h-full items-center px-6">
      <div className="max-w-md">
        <h2 className="text-base font-medium text-foreground">{t("mission", "noMissions")}</h2>
        <p className="mt-1 flex items-center gap-1.5 text-sm text-muted-foreground">
          <span>{t("mission", "noMissionsHintPrefix")}</span>
          <Kbd>⌘N</Kbd>
        </p>
      </div>
    </div>
  );
}
