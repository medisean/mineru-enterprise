/**
 * React hook — returns a t() function bound to the current locale.
 */
"use client";
import { useI18nStore } from "../i18n-store";
import { t } from "./index";

export function useT() {
  const locale = useI18nStore((s) => s.locale);
  return (key: string, params?: Record<string, string | number>) => t(locale, key, params);
}
