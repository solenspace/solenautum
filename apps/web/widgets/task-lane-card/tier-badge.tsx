import type { LucideIcon } from "lucide-react";
import { AppWindow, Globe2, ShieldCheck } from "lucide-react";

import { cn } from "@/shared/utils/cn";

type Tier = "http" | "stealth" | "dynamic";

const _META: Record<Tier, { code: string; icon: LucideIcon; tone: string }> = {
  http: {
    code: "HT",
    icon: Globe2,
    tone: "text-[#6B8860] border-[#6B8860]/40 dark:text-[#7B9B7A] dark:border-[#7B9B7A]/40",
  },
  stealth: {
    code: "ST",
    icon: ShieldCheck,
    tone: "text-[#5E5B7F] border-[#5E5B7F]/40 dark:text-[#726B96] dark:border-[#726B96]/40",
  },
  dynamic: {
    code: "DY",
    icon: AppWindow,
    tone: "text-[#9E8C3A] border-[#9E8C3A]/40 dark:text-[#D4B856] dark:border-[#D4B856]/40",
  },
};

/**
 * Tier badge — glyph + 2-letter code, color-blind safe per `ui-context.md`.
 * Glyph and code together carry the tier identity so a colorblind user
 * still distinguishes the three tiers without leaning on hue alone.
 */
export function TierBadge({ tier }: { tier: Tier }) {
  const meta = _META[tier];
  const Icon = meta.icon;
  return (
    <span
      className={cn(
        "inline-flex h-[22px] items-center gap-1 rounded border px-1.5 font-mono text-[11px]",
        meta.tone,
      )}
    >
      <Icon className="h-3 w-3" aria-hidden />
      {meta.code}
    </span>
  );
}
