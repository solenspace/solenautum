"use client";

import type { SseError, TaskEnd } from "@autumn/sse-protocol";
import type { Keys } from "@/shared/i18n";
import { useT } from "@/shared/i18n";
import { cn } from "@/shared/utils/cn";

/**
 * Renders inline error chips above the result preview when the agent
 * surfaced typed errors (Spec 09). The chip stays visible even without
 * a `task_end` — a mission can fail before any task completes.
 */
export function ResultPreview({
  taskEnd,
  errors = [],
}: {
  taskEnd: TaskEnd | null;
  errors?: SseError[];
}) {
  if (!taskEnd && errors.length === 0) return null;
  return (
    <div className="flex flex-col gap-2">
      {errors.map((error) => (
        <ErrorChip key={error.seq} error={error} />
      ))}
      {taskEnd ? (
        <div className="rounded-md border border-border bg-card p-3 text-sm text-foreground">
          <pre className="whitespace-pre-wrap break-words font-sans">
            {taskEnd.content.preview ?? ""}
          </pre>
        </div>
      ) : null}
    </div>
  );
}

const _ERROR_KEYS: Record<string, Keys<"mission">> = {
  site_not_supported: "errorSiteNotSupported",
  not_found: "errorNotFound",
  render_timeout: "errorRenderTimeout",
  upstream_error: "errorUpstream",
};

function ErrorChip({ error }: { error: SseError }) {
  const t = useT();
  const code = error.content.code;
  const key = _ERROR_KEYS[code];
  const copy = key
    ? t("mission", key, { protections: _protections(error) })
    : error.content.message;

  return (
    <div
      role="alert"
      className={cn(
        "rounded border border-state-error/40 bg-state-error/5 px-2.5 py-1.5",
        "text-[12px] leading-snug text-state-error",
      )}
    >
      {copy}
    </div>
  );
}

function _protections(error: SseError): string {
  // The SSE protocol's error.content carries `[k: string]: unknown`,
  // so optional `detected_protections` reads as `unknown` without a cast.
  const raw = error.content.detected_protections;
  return Array.isArray(raw) && raw.length > 0 ? raw.join(", ") : "an enterprise WAF";
}
