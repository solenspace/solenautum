"use client";

import { createContext, type ReactNode, useCallback, useContext, useEffect, useState } from "react";

/**
 * Minimal in-app theme provider — no external dependency, no flash on
 * first paint. Persists the user's choice in localStorage and toggles
 * the `dark` class on the html root so Tailwind's `dark:` modifier
 * (used throughout `components/ui/*`) actually engages.
 *
 * Two reasons we keep this in-house instead of pulling `next-themes`:
 *
 *   1. The shadcn primitives already drive every dark-mode change off
 *      the `dark` class on `<html>`; a one-line side effect is all
 *      they need.
 *   2. `next-themes` ships its own React tree (`ThemeProvider`) and a
 *      separate hydration script; adding it would push another client
 *      boundary into the root layout and broaden the bundle for a
 *      feature that is essentially `classList.toggle("dark")`.
 *
 * Default = light. The first paint runs a small inline script (set in
 * the root layout) that reads the saved value and applies the class
 * before React hydrates so users do not see a light-mode flash.
 */
export type Theme = "light" | "dark";

interface ThemeContextValue {
  theme: Theme;
  setTheme: (next: Theme) => void;
  toggle: () => void;
}

const _STORAGE_KEY = "autumn:theme";
const _ThemeContext = createContext<ThemeContextValue | null>(null);

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, _setTheme] = useState<Theme>(() => _readInitialTheme());

  useEffect(() => {
    const root = document.documentElement;
    if (theme === "dark") root.classList.add("dark");
    else root.classList.remove("dark");
    try {
      localStorage.setItem(_STORAGE_KEY, theme);
    } catch {
      // Private mode / quota — the toggle still works in-session,
      // just doesn't survive a reload.
    }
  }, [theme]);

  const setTheme = useCallback((next: Theme) => _setTheme(next), []);
  const toggle = useCallback(
    () => _setTheme((current) => (current === "dark" ? "light" : "dark")),
    [],
  );

  return (
    <_ThemeContext.Provider value={{ theme, setTheme, toggle }}>{children}</_ThemeContext.Provider>
  );
}

export function useTheme(): ThemeContextValue {
  const ctx = useContext(_ThemeContext);
  if (ctx === null) {
    throw new Error("useTheme must be used inside <ThemeProvider>");
  }
  return ctx;
}

function _readInitialTheme(): Theme {
  if (typeof window === "undefined") return "light";
  try {
    const stored = localStorage.getItem(_STORAGE_KEY);
    if (stored === "light" || stored === "dark") return stored;
  } catch {
    // ignore
  }
  // Honor the OS preference for first-time visitors.
  if (window.matchMedia?.("(prefers-color-scheme: dark)").matches) return "dark";
  return "light";
}

/**
 * Inline script source that runs before React hydrates to apply the
 * saved theme class on `<html>`. Keeps the first paint flash-free.
 * Embedded in the root layout via `dangerouslySetInnerHTML`.
 */
export const THEME_HYDRATION_SCRIPT = `
(function() {
  try {
    var t = localStorage.getItem(${JSON.stringify(_STORAGE_KEY)});
    if (t !== "light" && t !== "dark") {
      t = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
    }
    if (t === "dark") document.documentElement.classList.add("dark");
  } catch (e) { /* noop */ }
})();
`;
