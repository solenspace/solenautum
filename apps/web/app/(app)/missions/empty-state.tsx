"use client";

import { Kbd } from "@/components/ui/kbd";
import { useMissions } from "@/features/run-mission";
import { useT } from "@/shared/i18n";

/**
 * Empty state for `/missions`. Renders only when the user has no
 * missions yet — once any mission exists, the sidebar carries the
 * primary list and the main pane stays clear so a mission's slide-over
 * has visual space without competing copy underneath. Vertically
 * centered in the main pane (not the viewport), left-aligned within
 * its panel. No illustration, no marketing copy — the action is
 * already visible in the top bar, so the empty state just points at it.
 */
export function EmptyState() {
  const t = useT();
  const { missions, isLoading } = useMissions();
  // Render nothing while the first poll is in flight to avoid a flash
  // of empty-state copy before the sidebar populates; render nothing
  // after that whenever the user already has missions.
  if (isLoading || missions.length > 0) return null;
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
