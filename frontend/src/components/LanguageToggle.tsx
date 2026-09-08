"use client";

import { useLocale } from "@/i18n/LocaleProvider";

/**
 * The language switch. It sits in the header on every screen, signed-out ones
 * included, so the first thing a visitor sees can be flipped before they read
 * anything else.
 *
 * It shows the language you would switch *to*, written in that language — the
 * label a reader who cannot read the current one still recognises.
 */
export function LanguageToggle() {
  const { locale, toggle, t } = useLocale();

  return (
    <button
      type="button"
      onClick={toggle}
      className="lang-btn"
      // The accessible name states what the button does, not what the current
      // language is — a screen-reader user needs the action, not the state.
      aria-label={t("lang.switchAction")}
      title={t("lang.switchAction")}
    >
      <svg
        width="15"
        height="15"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.6"
        aria-hidden="true"
      >
        <circle cx="12" cy="12" r="9" />
        <path d="M3 12h18M12 3c2.4 2.6 3.6 5.6 3.6 9s-1.2 6.4-3.6 9c-2.4-2.6-3.6-5.6-3.6-9s1.2-6.4 3.6-9z" />
      </svg>
      {t("lang.switchTo")}
    </button>
  );
}
