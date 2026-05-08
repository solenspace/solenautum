"use client";

import { UserButton } from "@clerk/nextjs";
import { Globe2, ListPlus, Moon, Search, Sun } from "lucide-react";
import { useId, useState } from "react";

import { Kbd } from "@/components/ui/kbd";
import { SidebarTrigger } from "@/components/ui/sidebar";
import { useMissionStore, useSubmitMission } from "@/features/run-mission";
import { useT } from "@/shared/i18n";
import { useShortcut } from "@/shared/keyboard";
import { useTheme } from "@/shared/theme";

/**
 * Persistent top bar — 44px (`h-11`) header with the brand wordmark, the
 * always-visible URL input, theme toggle, and the Clerk user button.
 *
 * Mobile: a `<SidebarTrigger>` exposes the hamburger that the shadcn
 * `<Sidebar>` primitive expects below the `md` breakpoint (the sidebar
 * itself is `hidden md:block` and depends on this trigger for access).
 *
 * Validation errors arrive from `useSubmitMission` as i18n keys, never as
 * strings. The component resolves them via `t("validation", error)` so the
 * `i18n-keeper` rule (validators-return-keys) holds end-to-end.
 */
export function TopBar() {
  const t = useT();
  const inputId = useId();
  const [url, setUrl] = useState("");
  const { submit, isSubmitting, error } = useSubmitMission();
  const { theme, toggle: toggleTheme } = useTheme();
  const openMultiUrl = useMissionStore((s) => s.openMultiUrl);
  const openDescription = useMissionStore((s) => s.openDescription);

  useShortcut("/", () => {
    document.getElementById(inputId)?.focus();
  });

  return (
    <header className="flex h-11 items-center gap-2 border-b border-border/50 bg-background px-3">
      {/* Sidebar collapse / expand. Always visible so a user who closed
          the sidebar with Cmd+B (or by clicking the in-sidebar trigger)
          can reopen it without knowing the shortcut. */}
      <SidebarTrigger
        aria-label={t("common", "toggleSidebar")}
        className="text-muted-foreground hover:text-foreground"
      />
      <span className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground/70">
        {t("common", "brandName")}
      </span>
      <div className="ml-3 flex h-8 flex-1 items-center gap-2 rounded-md border border-border/50 bg-card pl-2 pr-1.5">
        <Globe2 className="h-3.5 w-3.5 text-muted-foreground" aria-hidden />
        <input
          id={inputId}
          type="url"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder={t("mission", "urlPlaceholder")}
          autoComplete="off"
          spellCheck={false}
          className="flex-1 bg-transparent font-mono text-[13px] outline-hidden placeholder:text-muted-foreground/60"
          onKeyDown={(e) => {
            if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
              e.preventDefault();
              void submit(url).then(() => setUrl(""));
            }
          }}
          disabled={isSubmitting}
        />
        <Kbd>⌘↩</Kbd>
      </div>
      {error ? (
        <span className="text-[11px] text-destructive">{t("validation", error)}</span>
      ) : null}
      <button
        type="button"
        onClick={openMultiUrl}
        aria-label={t("mission", "newMultiUrlMission")}
        title={t("mission", "newMultiUrlMission")}
        className="flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground transition-all hover:bg-accent/40 hover:text-foreground active:scale-95"
      >
        <ListPlus className="h-3.5 w-3.5" aria-hidden />
      </button>
      <button
        type="button"
        onClick={openDescription}
        aria-label={t("mission", "newDescriptionMission")}
        title={t("mission", "newDescriptionMission")}
        className="flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground transition-all hover:bg-accent/40 hover:text-foreground active:scale-95"
      >
        <Search className="h-3.5 w-3.5" aria-hidden />
      </button>
      <button
        type="button"
        onClick={toggleTheme}
        aria-label={theme === "dark" ? t("common", "switchToLight") : t("common", "switchToDark")}
        className="flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground transition-all hover:bg-accent/40 hover:text-foreground active:scale-95"
      >
        {theme === "dark" ? (
          <Sun className="h-3.5 w-3.5" aria-hidden />
        ) : (
          <Moon className="h-3.5 w-3.5" aria-hidden />
        )}
      </button>
      <UserButton appearance={{ elements: { userButtonAvatarBox: "h-7 w-7" } }} />
    </header>
  );
}
