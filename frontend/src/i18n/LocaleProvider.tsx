"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { messages, type Locale, type MessageKey } from "./messages";

const STORAGE_KEY = "remas.locale";

type Bilingual = Record<string, unknown>;

type LocaleContextValue = {
  locale: Locale;
  dir: "rtl" | "ltr";
  isArabic: boolean;
  setLocale: (locale: Locale) => void;
  toggle: () => void;
  /** UI string lookup. */
  t: (key: MessageKey) => string;
  /**
   * Content lookup: picks `<field>_ar` or `<field>_en` off an API object.
   * Content ships in both languages on every row, so this never refetches.
   */
  pick: (row: Bilingual | null | undefined, field: string) => string;
  /** Same as `pick`, for list-valued bilingual fields. */
  pickList: (row: Bilingual | null | undefined, field: string) => string[];
  /** Locale-aware number formatting with Western digits in both languages. */
  num: (value: number | null | undefined, digits?: number) => string;
};

const LocaleContext = createContext<LocaleContextValue | null>(null);

export function LocaleProvider({ children }: { children: ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>("ar");

  // Restore the visitor's last choice before first paint of the client tree.
  useEffect(() => {
    try {
      const stored = window.localStorage.getItem(STORAGE_KEY);
      if (stored === "ar" || stored === "en") setLocaleState(stored);
    } catch {
      /* storage can be blocked; the Arabic default still renders */
    }
  }, []);

  // The document element carries dir/lang so native form controls, scrollbars
  // and text selection all flip with the toggle, not just our own layout.
  useEffect(() => {
    const root = document.documentElement;
    root.lang = locale;
    root.dir = locale === "ar" ? "rtl" : "ltr";
    root.dataset.locale = locale;
  }, [locale]);

  const setLocale = useCallback((next: Locale) => {
    setLocaleState(next);
    try {
      window.localStorage.setItem(STORAGE_KEY, next);
    } catch {
      /* non-fatal */
    }
  }, []);

  const value = useMemo<LocaleContextValue>(() => {
    const dict = messages[locale];
    return {
      locale,
      dir: locale === "ar" ? "rtl" : "ltr",
      isArabic: locale === "ar",
      setLocale,
      toggle: () => setLocale(locale === "ar" ? "en" : "ar"),
      t: (key) => dict[key] ?? key,
      pick: (row, field) => {
        if (!row) return "";
        const value = row[`${field}_${locale}`];
        if (typeof value === "string" && value.length > 0) return value;
        const fallback = row[`${field}_${locale === "ar" ? "en" : "ar"}`];
        return typeof fallback === "string" ? fallback : "";
      },
      pickList: (row, field) => {
        if (!row) return [];
        const value = row[`${field}_${locale}`];
        if (Array.isArray(value)) return value as string[];
        const fallback = row[`${field}_${locale === "ar" ? "en" : "ar"}`];
        return Array.isArray(fallback) ? (fallback as string[]) : [];
      },
      num: (value, digits = 2) => {
        if (value === null || value === undefined || Number.isNaN(value)) return "—";
        return new Intl.NumberFormat(locale === "ar" ? "ar-SA-u-nu-latn" : "en-GB", {
          minimumFractionDigits: Number.isInteger(value) ? 0 : digits,
          maximumFractionDigits: digits,
        }).format(value);
      },
    };
  }, [locale, setLocale]);

  return <LocaleContext.Provider value={value}>{children}</LocaleContext.Provider>;
}

export function useLocale(): LocaleContextValue {
  const ctx = useContext(LocaleContext);
  if (!ctx) throw new Error("useLocale must be used inside <LocaleProvider>");
  return ctx;
}
