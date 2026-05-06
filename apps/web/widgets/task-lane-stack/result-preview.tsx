/**
 * Result preview for a single lane. Renders the trimmed preview that
 * arrived on `task_end`. Pure presentational — error chips render
 * separately via `InlineErrorChip` higher in the lane body so they stay
 * visible even when no `task_end` ever arrives.
 */
export function ResultPreview({ preview }: { preview: string | undefined }) {
  if (preview === undefined) return null;
  return (
    <div className="rounded-md border border-border bg-card p-3 text-sm text-foreground">
      <pre className="whitespace-pre-wrap break-words font-sans">{preview}</pre>
    </div>
  );
}
