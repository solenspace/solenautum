"use client";

import { useState } from "react";
import { z } from "zod";

import { Kbd } from "@/components/ui/kbd";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { useMissionStore, useSubmitMission } from "@/features/run-mission";
import { useT } from "@/shared/i18n";

/**
 * Validators return i18n KEYS, not strings (project-wide rule from
 * `code-standards.md`). The slide-over resolves them via `t("validation", key)`.
 */
const querySchema = z
  .string()
  .trim()
  .min(1, { message: "queryRequired" })
  .max(2000, { message: "queryTooLong" });

type ValidationKey = "queryRequired" | "queryTooLong";

const _VALIDATION_KEYS: ReadonlySet<ValidationKey> = new Set(["queryRequired", "queryTooLong"]);

function _isValidationKey(value: unknown): value is ValidationKey {
  return typeof value === "string" && _VALIDATION_KEYS.has(value as ValidationKey);
}

/**
 * Right-side slide-over for composing a description-mode mission. Opened
 * from the command palette ("New description-mode mission", `⌘⇧D`) and
 * submitted with Cmd+Enter. The single textarea holds a free-text query
 * (1–2000 chars); the discovery agent receives it on submit. The
 * skip-approval checkbox flips `missions.skip_approval` so the runner
 * proceeds straight to scraping after Tavily returns.
 *
 * Mirrors the structure of `multi-url-slideover`: validation runs
 * locally and the hook is only called with already-valid input, so
 * close-on-success is unconditional after a successful `await`.
 */
export function DescriptionModeSlideover() {
  const t = useT();
  const open = useMissionStore((s) => s.descriptionOpen);
  const closeDescription = useMissionStore((s) => s.closeDescription);
  const { submitDescription, isSubmitting } = useSubmitMission();

  const [query, setQuery] = useState("");
  const [skipApproval, setSkipApproval] = useState(false);
  const [validationError, setValidationError] = useState<ValidationKey | null>(null);

  async function handleSubmit() {
    setValidationError(null);
    const parsed = querySchema.safeParse(query);
    if (!parsed.success) {
      const message = parsed.error.issues[0]?.message;
      setValidationError(_isValidationKey(message) ? message : "queryRequired");
      return;
    }
    await submitDescription(parsed.data, skipApproval);
    setQuery("");
    setSkipApproval(false);
    closeDescription();
  }

  return (
    <Sheet
      open={open}
      onOpenChange={(next) => {
        if (!next) {
          closeDescription();
          setValidationError(null);
        }
      }}
    >
      <SheetContent side="right" className="w-full border-l border-border/50 sm:max-w-2xl">
        <SheetHeader className="border-b border-border/50 pb-2">
          <SheetTitle className="text-[13px]">{t("mission", "newDescriptionMission")}</SheetTitle>
        </SheetHeader>
        <div className="flex flex-col gap-3 p-4">
          <textarea
            aria-label={t("mission", "newDescriptionMission")}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder={t("mission", "descriptionPlaceholder")}
            spellCheck
            rows={8}
            disabled={isSubmitting}
            maxLength={2000}
            onKeyDown={(event) => {
              if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
                event.preventDefault();
                void handleSubmit();
              }
            }}
            className="min-h-32 w-full resize-none rounded-md border border-border/50 bg-card px-3 py-2 text-[13px] outline-hidden focus-visible:ring-2 focus-visible:ring-ring/40"
          />
          <label className="flex items-center gap-2 text-[11px] text-muted-foreground">
            <input
              type="checkbox"
              checked={skipApproval}
              onChange={(event) => setSkipApproval(event.currentTarget.checked)}
              disabled={isSubmitting}
              className="h-3.5 w-3.5 rounded border-border/50"
            />
            {t("mission", "skipApprovalForFutureSearches")}
          </label>
          <div className="flex items-center justify-between text-[11px] text-muted-foreground">
            <span className="font-mono tabular-nums">{query.length} / 2000</span>
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
