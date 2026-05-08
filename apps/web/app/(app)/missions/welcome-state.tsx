"use client";

import { Globe2, ListPlus, Search } from "lucide-react";
import Link from "next/link";

import { Kbd } from "@/components/ui/kbd";
import { useMissionStore, useMissions, useRecentMissions } from "@/features/run-mission";
import { useT } from "@/shared/i18n";
import { cn } from "@/shared/utils/cn";

/**
 * Landing card for users who already have missions but haven't opened
 * one yet. Replaces the old empty middle column. Surfaces three
 * interactive composer buttons (URL, multi-URL, description-mode) so
 * keyboard-shy users have parity with the cmd-palette flow, plus the
 * three most recent missions as direct links into `/missions/[id]`.
 */
export function WelcomeState() {
  const t = useT();
  const { missions, isLoading } = useMissions();
  const recent = useRecentMissions();
  const openMultiUrl = useMissionStore((s) => s.openMultiUrl);
  const openDescription = useMissionStore((s) => s.openDescription);

  if (isLoading || missions.length === 0) return null;

  function focusUrlInput(): void {
    const input = document.querySelector<HTMLInputElement>('input[type="url"]');
    input?.focus();
  }

  return (
    <div className="mx-auto flex h-full w-full max-w-3xl flex-col justify-center px-6 py-10">
      <h2 className="text-base font-medium text-foreground">{t("mission", "welcomeTitle")}</h2>
      <p className="mt-1 text-sm text-muted-foreground">{t("mission", "welcomeSubtitle")}</p>

      <div className="mt-5 grid gap-3 sm:grid-cols-3">
        <_ActionCard
          icon={<Globe2 className="h-3.5 w-3.5" aria-hidden />}
          label={t("mission", "newMission")}
          kbd="⌘↩"
          hint={t("mission", "welcomeNewHint")}
          onClick={focusUrlInput}
        />
        <_ActionCard
          icon={<ListPlus className="h-3.5 w-3.5" aria-hidden />}
          label={t("mission", "newMultiUrlMission")}
          kbd="⌘⇧N"
          hint={t("mission", "welcomeMultiHint")}
          onClick={openMultiUrl}
        />
        <_ActionCard
          icon={<Search className="h-3.5 w-3.5" aria-hidden />}
          label={t("mission", "newDescriptionMission")}
          kbd="⌘⇧D"
          hint={t("mission", "welcomeDescriptionHint")}
          onClick={openDescription}
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
                  className="flex h-9 items-center gap-2 border-l-2 border-transparent px-3 transition-all hover:border-l-primary/50 hover:bg-accent/40"
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

function _ActionCard({
  icon,
  label,
  kbd,
  hint,
  onClick,
}: {
  icon: React.ReactNode;
  label: string;
  kbd: string;
  hint: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="group flex flex-col rounded-md border border-border/50 bg-background/40 px-3 py-2 text-left transition-all hover:-translate-y-px hover:border-border hover:bg-accent/30 hover:shadow-sm active:translate-y-0 active:shadow-none focus-visible:border-ring focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring/40"
    >
      <div className="flex items-center justify-between gap-2">
        <span className="flex items-center gap-1.5 text-[12px] font-medium text-foreground">
          <span aria-hidden className="text-muted-foreground group-hover:text-foreground">
            {icon}
          </span>
          {label}
        </span>
        <Kbd>{kbd}</Kbd>
      </div>
      <p className="mt-1 text-[11px] text-muted-foreground">{hint}</p>
    </button>
  );
}

const _DOT_COLOR = {
  pending: "bg-muted-foreground/60",
  running: "bg-primary",
  succeeded: "bg-state-success",
  failed: "bg-state-error",
  cancelled: "bg-muted-foreground/60",
} as const;
