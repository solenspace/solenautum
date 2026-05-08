import "@testing-library/jest-dom/vitest";

import { vi } from "vitest";

// Next.js client-router hooks need an app-router context which vitest's
// jsdom env does not supply. Default to inert stubs so any component
// that calls `usePathname()` / `useRouter()` renders cleanly. Per-test
// `vi.mock("next/navigation", ...)` overrides this default when a test
// needs to assert on `router.push` / a specific pathname.
vi.mock("next/navigation", async () => {
  const actual = await vi.importActual<typeof import("next/navigation")>("next/navigation");
  return {
    ...actual,
    usePathname: () => "/missions",
    useRouter: () => ({
      push: vi.fn(),
      replace: vi.fn(),
      refresh: vi.fn(),
      back: vi.fn(),
      forward: vi.fn(),
      prefetch: vi.fn(),
    }),
    useSearchParams: () => new URLSearchParams(),
  };
});

// jsdom 29 ships an opaque localStorage proxy that does not implement the
// Storage interface methods. Substitute a Map-backed Storage so feature code
// using `localStorage.getItem`/`setItem` works under Vitest the same way it
// does in a real browser.
class MemoryStorage implements Storage {
  private _data = new Map<string, string>();

  get length(): number {
    return this._data.size;
  }
  clear(): void {
    this._data.clear();
  }
  getItem(key: string): string | null {
    return this._data.get(key) ?? null;
  }
  key(index: number): string | null {
    return Array.from(this._data.keys())[index] ?? null;
  }
  removeItem(key: string): void {
    this._data.delete(key);
  }
  setItem(key: string, value: string): void {
    this._data.set(key, value);
  }
}

Object.defineProperty(window, "localStorage", {
  configurable: true,
  value: new MemoryStorage(),
});
Object.defineProperty(globalThis, "localStorage", {
  configurable: true,
  value: window.localStorage,
});
