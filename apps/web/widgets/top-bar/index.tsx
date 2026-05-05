"use client";

import { Globe2 } from "lucide-react";
import { useId, useState } from "react";

import { Kbd } from "@/components/ui/kbd";
import { useSubmitMission } from "@/features/run-mission";
import { useT } from "@/shared/i18n";
import { useShortcut } from "@/shared/keyboard";

/**
 * Persistent top bar — 44px (`h-11`) header with the brand wordmark and the
 * always-visible URL input. The `/` shortcut focuses the input from
 * anywhere in the shell; `Cmd+Enter` submits without leaving the keyboard.
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

  useShortcut("/", () => {
    document.getElementById(inputId)?.focus();
  });

  return (
    <header className="flex h-11 items-center gap-2 border-b border-border/50 bg-background px-3">
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
    </header>
  );
}
