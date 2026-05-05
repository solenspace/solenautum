"use client";

import { useEffect } from "react";

/**
 * Lightweight keyboard shortcut registry. One global `keydown` listener per
 * mounted hook; combos are normalized to lower-case `meta+...` strings so a
 * mac `⌘` and a windows `ctrl` can register against the same handler.
 *
 * Combos accept either a single string or an array. Each combo is a `+`-
 * separated set of modifiers and a key, e.g. `cmd+k`, `control+k`, `escape`,
 * `shift+/`, `cmd+shift+n`. The `cmd` / `⌘` aliases resolve to `meta`.
 */
type KeyCombo = string | string[];
type Handler = (event: KeyboardEvent) => void;

const _MOD_MAP: Record<string, string> = {
  "⌘": "meta",
  cmd: "meta",
  "⌃": "control",
  ctrl: "control",
  control: "control",
  "⌥": "alt",
  alt: "alt",
  opt: "alt",
  option: "alt",
  "⇧": "shift",
  shift: "shift",
};

// A combo can be written with or without `+` between the modifier symbols
// and the key (`⌘K` vs. `cmd+k`). Splitting first on `+` then lifting any
// leading mod symbols out of the trailing segment handles both forms.
function normalize(combo: string): string {
  const cleaned = combo.toLowerCase().trim();
  const segments = cleaned.split("+").flatMap((segment) => {
    const trimmed = segment.trim();
    const out: string[] = [];
    let rest = trimmed;
    while (rest.length > 0) {
      const head = rest.charAt(0);
      const mod = _MOD_MAP[head];
      if (!mod) break;
      out.push(mod);
      rest = rest.slice(1);
    }
    if (rest.length > 0) out.push(_MOD_MAP[rest] ?? rest);
    return out;
  });
  const key = segments.pop() ?? "";
  const mods = segments.sort();
  return [...mods, key].join("+");
}

function describe(event: KeyboardEvent): string {
  const parts: string[] = [];
  if (event.altKey) parts.push("alt");
  if (event.ctrlKey) parts.push("control");
  if (event.metaKey) parts.push("meta");
  if (event.shiftKey) parts.push("shift");
  parts.push(event.key.toLowerCase());
  return parts.join("+");
}

function _isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (target.isContentEditable) return true;
  const tag = target.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT";
}

export interface UseShortcutOptions {
  /** Allow the shortcut to fire even when an input/textarea has focus. */
  allowInInput?: boolean;
}

/**
 * Mount a keyboard shortcut. The handler runs only when the combo matches
 * the live event; `preventDefault` is called for matched events so a
 * registered shortcut never falls through to the browser's default action.
 *
 * Shortcuts skip events that originate from an editable element (`<input>`,
 * `<textarea>`, `contenteditable`) unless `allowInInput` is `true`. The
 * top-bar URL field opts in via `allowInInput` so `Cmd+Enter` keeps working
 * while the user is typing.
 */
export function useShortcut(
  combo: KeyCombo,
  handler: Handler,
  options: UseShortcutOptions = {},
): void {
  useEffect(() => {
    const combos = (Array.isArray(combo) ? combo : [combo]).map(normalize);
    const wrapped = (event: KeyboardEvent) => {
      if (!options.allowInInput && _isEditableTarget(event.target)) return;
      const pressed = describe(event);
      if (!combos.includes(pressed)) return;
      event.preventDefault();
      handler(event);
    };
    window.addEventListener("keydown", wrapped);
    return () => window.removeEventListener("keydown", wrapped);
  }, [combo, handler, options.allowInInput]);
}

/**
 * Shell-level mount point for global shortcuts that have no natural home in
 * a feature folder. Currently a no-op — `useShortcut` is invoked directly by
 * the widgets that own the action — but the component reserves a stable
 * insertion site so future global handlers (`?` for help, `Cmd+Shift+L` for
 * theme toggle) land in one place.
 */
export function KeyboardShortcuts(): null {
  return null;
}
