"use client";

import { useEffect, useRef, useState } from "react";
import { z } from "zod";

import type { DiscoveredUrl } from "@/entities/mission/types";
import { useT } from "@/shared/i18n";

import { ScorePill } from "./score-pill";

const urlSchema = z.string().url();

/**
 * One row of the approval gate at 28px (h-7). Layout:
 *
 *   [checkbox] [favicon] [hostname] [path] [score-pill] [edited?]
 *
 * Clicking the hostname or path enters inline-edit mode; Enter or blur
 * commits a valid URL via `onEdit`, Escape cancels. Rows whose source
 * `score < 0.4` render dimmed and are excluded from the default
 * selection (the agent's own confidence drives the seed).
 */
export function UrlRow({
  url,
  checked,
  edited,
  onToggle,
  onEdit,
}: {
  url: DiscoveredUrl;
  checked: boolean;
  edited: string | undefined;
  onToggle: () => void;
  onEdit: (next: string | null) => void;
}) {
  const t = useT();
  const [editing, setEditing] = useState(false);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const display = edited ?? url.url;

  // Focus the inline-edit input when it mounts. Done via ref+effect rather
  // than `autoFocus` so the a11y linter (which warns on autofocus diversion
  // of screen-reader flow) doesn't flag this — the input only mounts in
  // response to a user click on the row itself, so the focus jump is
  // user-initiated.
  useEffect(() => {
    if (editing) inputRef.current?.focus();
  }, [editing]);

  let parsed: URL | null = null;
  try {
    parsed = new URL(display);
  } catch {
    parsed = null;
  }

  const dimmed = url.score < 0.4;
  const hostname = parsed?.hostname ?? display;
  const pathPart = parsed ? parsed.pathname + parsed.search : "";

  return (
    <li
      data-state={checked ? "checked" : "unchecked"}
      className="grid h-7 grid-cols-[16px_16px_auto_1fr_auto_24px] items-center gap-2 border-b border-border/50 px-3 hover:bg-muted/40 data-[state=checked]:bg-muted/20"
    >
      <input
        type="checkbox"
        checked={checked}
        onChange={onToggle}
        aria-label={url.url}
        className="h-3.5 w-3.5 rounded border-border/50"
      />
      {url.favicon_url ? (
        // eslint-disable-next-line @next/next/no-img-element — vendor favicons fail next/image domain checks; cheap raw <img> avoids the config noise.
        <img src={url.favicon_url} alt="" className="h-3 w-3 rounded-sm" />
      ) : (
        <span className="h-3 w-3" aria-hidden />
      )}
      {editing ? (
        <input
          ref={inputRef}
          type="url"
          defaultValue={display}
          onBlur={(e) => {
            const value = e.currentTarget.value;
            setEditing(false);
            const isValid = urlSchema.safeParse(value).success;
            if (isValid && value !== url.url) onEdit(value);
            else if (value === url.url) onEdit(null);
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter") (e.currentTarget as HTMLInputElement).blur();
            if (e.key === "Escape") {
              e.currentTarget.value = display;
              setEditing(false);
            }
          }}
          className="col-span-3 bg-transparent font-mono text-[13px] outline-hidden"
        />
      ) : (
        <>
          <button
            type="button"
            onClick={() => setEditing(true)}
            className={`text-left font-mono text-[13px] ${
              dimmed ? "text-muted-foreground/60" : "text-foreground"
            }`}
          >
            {hostname}
          </button>
          <button
            type="button"
            onClick={() => setEditing(true)}
            className="truncate text-left font-mono text-[13px] text-muted-foreground"
          >
            {pathPart}
          </button>
        </>
      )}
      <ScorePill score={url.score} />
      <span className="text-[11px] text-muted-foreground">
        {edited ? t("mission", "edited") : null}
      </span>
    </li>
  );
}
