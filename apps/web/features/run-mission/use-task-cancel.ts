"use client";

import { useCallback, useState } from "react";

/**
 * Per-task cancellation hook (Spec 14). Returns a `cancelTask` callback
 * that fires `DELETE /api/missions/{missionId}/tasks/{taskId}` and a
 * `pending` flag for optional disabled-button feedback.
 *
 * The api-side cancel is idempotent so a duplicate click is harmless;
 * the hook does not de-duplicate by `taskId`. Network failures fall
 * through silently — the user can press X again, and the SSE stream is
 * the source of truth for the lane's eventual `cancelled` status.
 */
export function useTaskCancel(): {
  cancelTask: (missionId: string, taskId: string) => Promise<void>;
  pending: boolean;
} {
  const [pending, setPending] = useState(false);

  const cancelTask = useCallback(async (missionId: string, taskId: string) => {
    setPending(true);
    try {
      await fetch(`/api/missions/${missionId}/tasks/${taskId}`, { method: "DELETE" });
    } catch {
      // Idempotent retry path; the next click re-issues the DELETE.
    } finally {
      setPending(false);
    }
  }, []);

  return { cancelTask, pending };
}
