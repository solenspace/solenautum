"use client";

import { useState } from "react";
import { z } from "zod";

import { useMissionStore } from "./store";

/**
 * Validation errors are returned as i18n KEYS, not strings. The top-bar
 * and the multi-URL slide-over resolve them via `t("validation", error)`
 * per `code-standards.md` — validators never return user-facing copy.
 * The literal union keeps the resolved-at-UI cast typesafe at the call
 * site.
 */
export type SubmitMissionError = "urlRequired" | "urlTooLong" | "urlInvalid" | "missionFailed";

const urlSchema = z.string().min(1, "urlRequired").max(2048, "urlTooLong").url("urlInvalid");

interface UseSubmitMissionState {
  /** Single-URL submit. Thin wrapper around `submitMany([url])`. */
  submit: (input: string) => Promise<void>;
  /** Multi-URL submit (1–20 URLs). Spec 10. The caller is responsible
   * for parsing newline-separated input into an array; this hook only
   * forwards it to the API. Returns once the BFF responds. */
  submitMany: (urls: string[]) => Promise<void>;
  isSubmitting: boolean;
  error: SubmitMissionError | null;
}

export function useSubmitMission(): UseSubmitMissionState {
  const open = useMissionStore((s) => s.openMission);
  const [error, setError] = useState<SubmitMissionError | null>(null);
  const [isSubmitting, setSubmitting] = useState(false);

  async function submitMany(urls: string[]): Promise<void> {
    setError(null);
    setSubmitting(true);
    try {
      const response = await fetch("/api/missions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ urls }),
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

  async function submit(input: string): Promise<void> {
    setError(null);
    const parsed = urlSchema.safeParse(input.trim());
    if (!parsed.success) {
      const message = parsed.error.issues[0]?.message;
      setError(_isSubmitError(message) ? message : "urlInvalid");
      return;
    }
    await submitMany([parsed.data]);
  }

  return { submit, submitMany, isSubmitting, error };
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
