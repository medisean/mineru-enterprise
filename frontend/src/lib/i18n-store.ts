/**
 * i18n store — persists locale preference to localStorage.
 */
import { create } from "zustand";
import { persist } from "zustand/middleware";

export type Locale = "zh" | "en";

interface I18nState {
  locale: Locale;
  setLocale: (locale: Locale) => void;
}

export const useI18nStore = create<I18nState>()(
  persist(
    (set) => ({
      locale: "zh",
      setLocale: (locale) => set({ locale }),
    }),
    {
      name: "i18n-store",
    }
  )
);
