"use client";

import type { Keys, T } from "@/shared/i18n";
import { useT } from "@/shared/i18n";
import { cn } from "@/shared/utils/cn";

const _ERROR_KEYS: Record<string, Keys<"mission">> = {
  site_not_supported: "errorSiteNotSupported",
  not_found: "errorNotFound",
  render_timeout: "errorRenderTimeout",
  upstream_error: "errorUpstream",
  agent_failed: "errorAgentFailed",
  discovery_failed: "errorDiscoveryFailed",
};

// Trim the upstream `message` so a multi-line Pydantic stack trace
// from `pydantic_ai.exceptions.UnexpectedModelBehavior` does not
// overrun the lane log. The chip flags the failure; detail lives in
// the api log for the operator to inspect.
function _truncate(message: string, max = 160): string {
  const oneLine = message.split(/\r?\n/, 1)[0]?.trim() ?? "";
  if (oneLine.length <= max) return oneLine;
  return `${oneLine.slice(0, max - 1)}…`;
}

export interface InlineErrorChipProps {
  /** SSE error code emitted by the agent (Spec 09 — `site_not_supported`,
   *  `render_timeout`, `not_found`, `upstream_error`, …). */
  code: string;
  /** Free-form fallback when the code is not in the mapped key set. */
  message: string;
  /** Detected WAF / bot-protection names interpolated into the
   *  `errorSiteNotSupported` template. */
  detectedProtections?: string[];
}

/**
 * Inline error chip surfaced when the agent emits an `error` event with a
 * recognised `code`. Renders a short, scannable line above the preview
 * block so the operator can identify a failed lane without scrolling the
 * reasoning stream.
 */
export function InlineErrorChip({ code, message, detectedProtections }: InlineErrorChipProps) {
  const t = useT();
  const key = _ERROR_KEYS[code];
  // Unrecognised codes pass the SSE-protocol `message` through a thin i18n
  // template (`errorGeneric: "{message}"`) so all rendered copy still
  // routes through `t()`; the template can be re-shaped per locale later.
  const copy = key
    ? t("mission", key, { protections: _protections(t, detectedProtections) })
    : t("mission", "errorGeneric", { message: _truncate(message) });

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

function _protections(t: T, detected: string[] | undefined): string {
  return detected && detected.length > 0
    ? detected.join(", ")
    : t("mission", "errorProtectionFallback");
}
