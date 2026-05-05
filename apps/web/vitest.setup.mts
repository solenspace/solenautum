import "@testing-library/jest-dom/vitest";

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
