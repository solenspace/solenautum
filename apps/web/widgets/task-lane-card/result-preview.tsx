import type { TaskEnd } from "@autumn/sse-protocol";

/**
 * Terminal result preview. Text-tier (highest contrast) per the three-tier
 * hierarchy: reasoning is dim, tool chips are neutral, the result block is
 * the brightest content in the lane. Renders the first ~500 chars of the
 * parsed markdown; full markdown is fetched on demand from the api in a
 * later spec.
 */
export function ResultPreview({ taskEnd }: { taskEnd: TaskEnd }) {
  const preview = taskEnd.content.preview ?? "";
  return (
    <div className="rounded-md border border-border bg-card p-3 text-sm text-foreground">
      <pre className="whitespace-pre-wrap break-words font-sans">{preview}</pre>
    </div>
  );
}
