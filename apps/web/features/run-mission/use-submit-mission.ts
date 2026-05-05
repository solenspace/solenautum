"use client";

import { useState } from "react";
import { z } from "zod";

import { useMissionStore } from "./store";

/**
 * Validation errors are returned as i18n KEYS, not strings. The top-bar
 * resolves them via `t("validation", error)` per `code-standards.md` —
 * validators never return user-facing copy. The literal union keeps the
 * resolved-at-UI cast typesafe at the call site.
 */
export type SubmitMissionError = "urlRequired" | "urlTooLong" | "urlInvalid" | "missionFailed";

const urlSchema = z.string().min(1, "urlRequired").max(2048, "urlTooLong").url("urlInvalid");

interface UseSubmitMissionState {
  submit: (input: string) => Promise<void>;
  isSubmitting: boolean;
  error: SubmitMissionError | null;
}

export function useSubmitMission(): UseSubmitMissionState {
  const open = useMissionStore((s) => s.openMission);
  const [error, setError] = useState<SubmitMissionError | null>(null);
  const [isSubmitting, setSubmitting] = useState(false);

  async function submit(input: string): Promise<void> {
    setError(null);
    const parsed = urlSchema.safeParse(input.trim());
    if (!parsed.success) {
      const message = parsed.error.issues[0]?.message;
      setError(_isSubmitError(message) ? message : "urlInvalid");
      return;
    }

    setSubmitting(true);
    try {
      const response = await fetch("/api/missions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url: parsed.data }),
      });
      if (!response.ok) {
        setError("missionFailed");
        return;
      }
      const payload = (await response.json()) as { mission_id: string };
      open(payload.mission_id);
    } catch {
      setError("missionFailed");
    } finally {
      setSubmitting(false);
    }
  }

  return { submit, isSubmitting, error };
}

const _SUBMIT_ERRORS: ReadonlySet<SubmitMissionError> = new Set([
  "urlRequired",
  "urlTooLong",
  "urlInvalid",
  "missionFailed",
]);

function _isSubmitError(value: unknown): value is SubmitMissionError {
  return typeof value === "string" && _SUBMIT_ERRORS.has(value as SubmitMissionError);
}
