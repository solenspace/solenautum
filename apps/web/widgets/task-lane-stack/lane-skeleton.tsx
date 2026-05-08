/**
 * Skeleton lane shown before the corresponding `task_start` event lands.
 * Matches the 32px collapsed-row geometry so the swap to a real
 * `TaskLaneRow` doesn't reflow the stack.
 */
export function LaneSkeleton() {
  return (
    <li className="rounded-md border border-border/50 bg-card" aria-hidden>
      <div className="flex h-8 items-center gap-2 px-2">
        <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-muted-foreground/30" />
        <span className="h-3 w-12 animate-pulse rounded bg-muted/40" />
        <span className="h-3 flex-1 animate-pulse rounded bg-muted/40" />
      </div>
    </li>
  );
}
