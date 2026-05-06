"use client";

import { createContext, type ReactNode, useContext, useMemo } from "react";

import { type Keys, type Namespace, type TranslateParams, translate } from "./translate";

export type T = <N extends Namespace, K extends Keys<N>>(
  namespace: N,
  key: K,
  params?: TranslateParams,
) => string;

const _t: T = translate;
const I18nContext = createContext<T>(_t);

export function I18nProvider({ children }: { children: ReactNode }) {
  // Single-locale today; useMemo guarantees stable identity so descendant
  // hooks do not re-run their effects on every parent re-render.
  const value = useMemo<T>(() => _t, []);
  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useT(): T {
  return useContext(I18nContext);
}
