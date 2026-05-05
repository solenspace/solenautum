import type { ReactNode } from "react";

import { I18nProvider } from "./provider";

/**
 * Wraps `children` with the in-process i18n primitive for Vitest. Use as the
 * `wrapper` option to `renderHook` or as the outermost element in `render`.
 */
export function I18nTestWrapper({ children }: { children: ReactNode }) {
  return <I18nProvider>{children}</I18nProvider>;
}
