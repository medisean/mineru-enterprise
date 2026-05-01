/**
 * Language toggle button — fixed top-right, visible on all pages.
 */
"use client";
import { useI18nStore } from "@/lib/i18n-store";
import { Languages } from "lucide-react";

export function LanguageToggle() {
  const { locale, setLocale } = useI18nStore();

  return (
    <button
      onClick={() => setLocale(locale === "zh" ? "en" : "zh")}
      className="fixed top-4 right-4 z-50 flex items-center gap-1.5 text-xs font-medium text-gray-500 hover:text-gray-800 px-2.5 py-1.5 rounded-lg hover:bg-white/80 shadow-sm border border-gray-200 bg-white/60 backdrop-blur-sm transition-colors"
      title={locale === "zh" ? "Switch to English" : "切换为中文"}
    >
      <Languages className="h-3.5 w-3.5" />
      {locale === "zh" ? "EN" : "中"}
    </button>
  );
}
