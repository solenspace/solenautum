"use client";

import Link from "next/link";

import { Kbd } from "@/components/ui/kbd";
import { useMissions, useRecentMissions } from "@/features/run-mission";
import { useT } from "@/shared/i18n";
import { cn } from "@/shared/utils/cn";

/**
 * Landing card for users who already have missions but haven't opened
 * one yet. Replaces the old empty middle column. Surfaces the five most
 * recent missions as direct links into `/missions/[id]` so the wasted
 * space becomes a navigation aid rather than dead canvas, and mirrors
 * the keyboard shortcuts the top bar already exposes.
 */
export function WelcomeState() {
  const t = useT();
  const { missions, isLoading } = useMissions();
  const recent = useRecentMissions();

  if (isLoading || missions.length === 0) return null;

  return (
    <div className="mx-auto flex h-full w-full max-w-3xl flex-col justify-center px-6 py-10">
      <h2 className="text-base font-medium text-foreground">{t("mission", "welcomeTitle")}</h2>
      <p className="mt-1 text-sm text-muted-foreground">{t("mission", "welcomeSubtitle")}</p>

      <div className="mt-5 grid gap-3 sm:grid-cols-3">
        <_Hint label={t("mission", "newMission")} kbd="⌘↩" hint={t("mission", "welcomeNewHint")} />
        <_Hint
          label={t("mission", "newMultiUrlMission")}
          kbd="⌘⇧N"
          hint={t("mission", "welcomeMultiHint")}
        />
        <_Hint
          label={t("mission", "newDescriptionMission")}
          kbd="⌘⇧D"
          hint={t("mission", "welcomeDescriptionHint")}
        />
      </div>

      {recent.length > 0 ? (
        <div className="mt-6 rounded-md border border-border/50 bg-background/40">
          <header className="border-b border-border/40 px-3 py-1.5">
            <h3 className="font-mono text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
              {t("common", "recent")}
            </h3>
          </header>
          <ul className="divide-y divide-border/40">
            {recent.map((mission) => (
              <li key={mission.id}>
                <Link
                  href={`/missions/${mission.id}`}
                  className="flex h-9 items-center gap-2 px-3 transition-colors hover:bg-accent/40"
                >
                  <span
                    aria-hidden
                    className={cn("h-1.5 w-1.5 rounded-full", _DOT_COLOR[mission.status])}
                  />
                  <span className="font-mono text-[11px] tabular-nums text-muted-foreground">
                    {mission.id.slice(0, 8)}
                  </span>
                  <span className="flex-1 truncate font-mono text-[13px] text-foreground">
                    {mission.prompt}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

function _Hint({ label, kbd, hint }: { label: string; kbd: string; hint: string }) {
  return (
    <div className="rounded-md border border-border/50 bg-background/40 px-3 py-2">
      <div className="flex items-center justify-between gap-2">
        <span className="text-[12px] font-medium text-foreground">{label}</span>
        <Kbd>{kbd}</Kbd>
      </div>
      <p className="mt-1 text-[11px] text-muted-foreground">{hint}</p>
    </div>
  );
}

const _DOT_COLOR = {
  pending: "bg-muted-foreground/60",
  running: "bg-primary",
  succeeded: "bg-state-success",
  failed: "bg-state-error",
  cancelled: "bg-muted-foreground/60",
} as const;
