import { EN, type Keys, type Namespace, type Translations } from "./keys/en";

/**
 * Pure translation function. No locale switching in Spec 08 — English only —
 * but the signature lets the callsite stay stable when other locales arrive.
 *
 * `params.count` selects between `${key}_one` (count === 1) and `${key}_other`
 * (everything else); the unsuffixed `key` is returned only when no `_one` /
 * `_other` pair exists. Other params are interpolated into `{name}`
 * placeholders inside the resolved string.
 *
 * Missing keys return the key itself (so a developer sees `mission:loading`
 * in the UI rather than empty space) and `console.warn` once per
 * `(namespace, key)` pair so noise stays bounded.
 */
export type TranslateParams = Record<string, string | number | undefined>;

export function translate<N extends Namespace, K extends Keys<N>>(
  namespace: N,
  key: K,
  params?: TranslateParams,
): string {
  const ns = EN[namespace] as unknown as Record<string, string>;
  const baseKey = String(key);

  let resolvedKey = baseKey;
  if (params && typeof params.count === "number") {
    const suffix = params.count === 1 ? "_one" : "_other";
    const pluralKey = `${baseKey}${suffix}`;
    if (pluralKey in ns) {
      resolvedKey = pluralKey;
    }
  }

  const template = ns[resolvedKey];
  if (template === undefined) {
    _warnMissing(namespace, baseKey);
    return baseKey;
  }
  return _interpolate(template, params);
}

const _warned = new Set<string>();

function _warnMissing(namespace: string, key: string): void {
  const id = `${namespace}:${key}`;
  if (_warned.has(id)) return;
  _warned.add(id);
  console.warn(`i18n: missing key ${id}`);
}

function _interpolate(template: string, params: TranslateParams | undefined): string {
  if (!params) return template;
  return template.replace(/\{(\w+)\}/g, (match, name: string) => {
    const value = params[name];
    return value === undefined ? match : String(value);
  });
}

export type { Keys, Namespace, Translations };
