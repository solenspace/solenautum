"use client";

import { useState } from "react";
import { z } from "zod";

import { Kbd } from "@/components/ui/kbd";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { useMissionStore, useSubmitMission } from "@/features/run-mission";
import { useT } from "@/shared/i18n";

const _MAX_URLS = 20;

/**
 * Validates the parsed URL array. Returns an i18n KEY (`validation`
 * namespace) on failure, never a user-facing string — resolved at the
 * UI layer per the project's i18n contract.
 */
const urlsSchema = z
  .array(z.string().url({ message: "missionUrlsInvalid" }))
  .min(1, { message: "missionUrlsRequired" })
  .max(_MAX_URLS, { message: "missionUrlsTooMany" });

type ValidationKey = "missionUrlsRequired" | "missionUrlsTooMany" | "missionUrlsInvalid";

const _VALIDATION_KEYS: ReadonlySet<ValidationKey> = new Set([
  "missionUrlsRequired",
  "missionUrlsTooMany",
  "missionUrlsInvalid",
]);

function _isValidationKey(value: unknown): value is ValidationKey {
  return typeof value === "string" && _VALIDATION_KEYS.has(value as ValidationKey);
}

/**
 * Right-side slide-over for composing a 1–20 URL mission. Opened from
 * the command palette (Cmd+K → "New multi-URL mission") and submitted
 * with Cmd+Enter. URLs are newline-separated, parsed client-side, and
 * forwarded as a `{ urls: [...] }` body via `useSubmitMission.submitMany`.
 *
 * The sheet's `Esc`-to-close and outside-click-to-close come from the
 * underlying Base UI Dialog (no custom escape handler needed).
 */
export function MultiUrlSlideover() {
  const t = useT();
  const open = useMissionStore((s) => s.multiUrlOpen);
  const closeMultiUrl = useMissionStore((s) => s.closeMultiUrl);
  const { submitMany, isSubmitting } = useSubmitMission();

  const [text, setText] = useState("");
  const [validationError, setValidationError] = useState<ValidationKey | null>(null);

  const parsedUrls = text
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
  const count = parsedUrls.length;

  async function handleSubmit() {
    setValidationError(null);
    const parsed = urlsSchema.safeParse(parsedUrls);
    if (!parsed.success) {
      const message = parsed.error.issues[0]?.message;
      setValidationError(_isValidationKey(message) ? message : "missionUrlsInvalid");
      return;
    }
    await submitMany(parsed.data);
    setText("");
    closeMultiUrl();
  }

  return (
    <Sheet
      open={open}
      onOpenChange={(next) => {
        if (!next) {
          closeMultiUrl();
          setValidationError(null);
        }
      }}
    >
      <SheetContent side="right" className="w-full border-l border-border/50 sm:max-w-2xl">
        <SheetHeader className="border-b border-border/50 pb-2">
          <SheetTitle className="text-[13px]">{t("mission", "newMultiUrlMission")}</SheetTitle>
        </SheetHeader>
        <div className="flex flex-col gap-3 p-4">
          <p className="text-xs text-muted-foreground">{t("mission", "multiUrlHelp")}</p>
          <textarea
            aria-label={t("mission", "newMultiUrlMission")}
            value={text}
            onChange={(event) => setText(event.target.value)}
            placeholder={t("mission", "multiUrlPlaceholder")}
            spellCheck={false}
            rows={12}
            disabled={isSubmitting}
            onKeyDown={(event) => {
              if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
                event.preventDefault();
                void handleSubmit();
              }
            }}
            className="w-full resize-none rounded-md border border-border/50 bg-card px-3 py-2 font-mono text-[13px] outline-hidden focus-visible:ring-2 focus-visible:ring-ring/40"
          />
          <div className="flex items-center justify-between text-[11px] text-muted-foreground">
            <span>
              {count} {t("mission", "urlCount", { count })}
            </span>
            <span className="flex items-center gap-1.5">
              {validationError ? (
                <span className="text-destructive">{t("validation", validationError)}</span>
              ) : null}
              <Kbd>⌘↩</Kbd>
            </span>
          </div>
        </div>
      </SheetContent>
    </Sheet>
  );
}
