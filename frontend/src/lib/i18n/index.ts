/**
 * i18n core — exports dictionaries and t() function.
 */
import { zh } from "./zh";
import { en } from "./en";
import type { Locale } from "../i18n-store";

const dictionaries: Record<Locale, Record<string, string>> = { zh, en };

export function t(locale: Locale, key: string, params?: Record<string, string | number>): string {
  let text = dictionaries[locale]?.[key] || dictionaries.zh[key] || key;
  if (params) {
    Object.entries(params).forEach(([k, v]) => {
      text = text.replace(new RegExp(`\\{${k}\\}`, "g"), String(v));
    });
  }
  return text;
}
