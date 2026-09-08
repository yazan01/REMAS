"use client";

import { useEffect, useState } from "react";

import { useLocale } from "@/i18n/LocaleProvider";

type Mode = "light" | "dark" | "system";

const KEY = "remas.theme";

export function ThemeToggle() {
  const { locale } = useLocale();
  const [mode, setMode] = useState<Mode>("system");

  useEffect(() => {
    try {
      const stored = localStorage.getItem(KEY);
      if (stored === "dark" || stored === "light") setMode(stored);
    } catch {
      /* storage can be blocked */
    }
  }, []);

  function apply(next: Mode) {
    setMode(next);
    const root = document.documentElement;
    try {
      if (next === "system") {
        root.removeAttribute("data-theme");
        localStorage.removeItem(KEY);
      } else {
        root.setAttribute("data-theme", next);
        localStorage.setItem(KEY, next);
      }
    } catch {
      /* non-fatal */
    }
  }

  // system → dark → light → system
  const next: Mode = mode === "system" ? "dark" : mode === "dark" ? "light" : "system";
  const label =
    locale === "ar"
      ? { system: "تلقائي", dark: "ليلي", light: "نهاري" }[mode]
      : { system: "Auto", dark: "Dark", light: "Light" }[mode];

  return (
    <button
      type="button"
      className="icon-btn"
      onClick={() => apply(next)}
      title={label}
      aria-label={label}
    >
      {mode === "dark" ? <MoonIcon /> : mode === "light" ? <SunIcon /> : <AutoIcon />}
    </button>
  );
}

function SunIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" aria-hidden="true">
      <circle cx="12" cy="12" r="4.2" />
      <path d="M12 2.6v2.1M12 19.3v2.1M2.6 12h2.1M19.3 12h2.1M5.4 5.4l1.5 1.5M17.1 17.1l1.5 1.5M18.6 5.4l-1.5 1.5M6.9 17.1l-1.5 1.5" />
    </svg>
  );
}

function MoonIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinejoin="round" aria-hidden="true">
      <path d="M20 14.2A8.4 8.4 0 0 1 9.8 4a8.4 8.4 0 1 0 10.2 10.2z" />
    </svg>
  );
}

function AutoIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true">
      <circle cx="12" cy="12" r="8.4" />
      <path d="M12 3.6v16.8a8.4 8.4 0 0 0 0-16.8z" fill="currentColor" stroke="none" />
    </svg>
  );
}
