"use client";

import { ArrowUpRight } from "lucide-react";

import { useT } from "@/shared/i18n";

interface ResultPreviewProps {
  /** Trimmed markdown preview from `task_end.content.preview`. */
  preview: string | undefined;
  /** Owning mission id; together with `taskId` builds the snapshot href. */
  missionId: string;
  /** Owning task id. */
  taskId: string;
  /** Snapshot key from `task_end.content.snapshot_key`. When present, the
   * "Download HTML" link renders below the preview (Spec 14). */
  snapshotKey?: string;
}

/**
 * Detects the local-fs blob backend so the download link renders disabled
 * with a hint instead of a dead `file://` redirect that the browser
 * refuses to follow. We key off `NODE_ENV !== "production"` because the
 * api uses `BLOB_STORE_BACKEND=local` only in dev; staging and prod ship
 * R2-backed signed URLs which the browser opens normally.
 */
function _isDevBlobBackend(): boolean {
  return process.env.NODE_ENV !== "production";
}

/**
 * Result preview for a single lane. Renders the trimmed preview that
 * arrived on `task_end`, plus the Spec 14 "Download HTML" link when a
 * snapshot key is present. Error chips render separately via
 * `InlineErrorChip` higher in the lane body so they stay visible even
 * when no `task_end` ever arrives.
 */
export function ResultPreview({ preview, missionId, taskId, snapshotKey }: ResultPreviewProps) {
  const t = useT();

  // Failed tasks (no scrape ever ran, or scrape produced no parsable
  // content) arrive here with `preview = null` or `""`. The earlier
  // `=== undefined` check let those through and rendered an empty
  // `<pre>` card — a sad blank rectangle below the failure chip. Treat
  // any non-content value the same as missing.
  const hasPreview = typeof preview === "string" && preview.trim().length > 0;
  if (!hasPreview && !snapshotKey) return null;

  const isDev = _isDevBlobBackend();

  return (
    <div className="flex flex-col gap-2">
      {hasPreview ? (
        <div className="rounded-md border border-border bg-card p-3 text-sm text-foreground">
          <pre className="whitespace-pre-wrap break-words font-sans">{preview}</pre>
        </div>
      ) : null}
      {snapshotKey ? (
        isDev ? (
          <span className="inline-flex items-center gap-1 text-[11px] text-muted-foreground/70">
            {t("mission", "downloadHtmlDevDisabled")}
          </span>
        ) : (
          <a
            href={`/api/missions/${missionId}/tasks/${taskId}/snapshot`}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 text-[11px] text-muted-foreground transition-colors hover:text-foreground"
          >
            {t("mission", "downloadHtml")}
            <ArrowUpRight className="h-3 w-3" aria-hidden />
          </a>
        )
      ) : null}
    </div>
  );
}
