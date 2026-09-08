/* ═══════════════════════════════════════════════════════════════════════════
   ★ نظام ألوان المنصة — المصدر الوحيد ★
   REMAS palette — the single source of truth.

   غيّر قيمة واحدة هنا، تتغيّر في كل شاشة في الموقع: الأزرار، البطاقات،
   الرسوم البيانية، الجداول، الوضع الليلي — كلها تقرأ من هنا ولا تحمل أي
   لون مكتوب مباشرةً في أي ملف آخر.

   Change one value here and it changes everywhere: buttons, cards, charts,
   tables, dark mode. No colour is hard-coded anywhere else in the codebase.

   البنية / Structure
   ──────────────────
   brand   : الهوية الأساسية (سلّم من فاتح إلى غامق)
   accent  : لون التمييز (النحاسي)
   neutral : الأسطح والنصوص والحدود
   status  : نجاح / تحذير / خطر
   maturity: سلّم مستويات النضج الخمسة — قلب المنتج البصري
   ═══════════════════════════════════════════════════════════════════════════ */

export type ThemeTokens = Record<string, string>;

/** ──────────────────────────────────────────────────────────────────────
 *  ١. الوضع النهاري  ·  Light mode
 *  ────────────────────────────────────────────────────────────────────── */
export const light: ThemeTokens = {
  /* الهوية — أزرق كحلي عميق · Brand: deep navy */
  "brand-50": "#eef3f9",
  "brand-100": "#dbe6f2",
  "brand-200": "#b6cbe2",
  "brand-300": "#88a9cc",
  "brand-400": "#5b82ab",
  "brand-500": "#3d6690",
  "brand-600": "#2b4f75",
  "brand-700": "#1e3a5c",
  "brand-800": "#172c46",
  "brand-900": "#101f33",

  /* التمييز — نحاسي · Accent: brass */
  "accent-100": "#f6e9d4",
  "accent-300": "#dcb877",
  "accent-500": "#b8863b",
  "accent-600": "#a0712c",
  "accent-700": "#7d5620",

  /* الأسطح والنصوص · Neutrals */
  paper: "#f2f4f7",
  "paper-alt": "#e8ecf1",
  surface: "#ffffff",
  "surface-2": "#f6f8fa",
  "surface-3": "#eef2f6",
  ink: "#0f1b28",
  "ink-2": "#3f5162",
  "ink-3": "#6b7d8d",
  "ink-4": "#93a3b1",
  line: "#dbe2e9",
  "line-2": "#c6d0da",
  "line-strong": "#a9b6c3",

  /* الحالات · Status */
  ok: "#1f6b4a",
  "ok-bg": "#dcefe4",
  warn: "#8a6420",
  "warn-bg": "#f6ebd6",
  danger: "#9b3d2e",
  "danger-bg": "#f8e2dc",
  info: "#1e3a5c",
  "info-bg": "#dde7f2",

  /* سلّم النضج ١←٥ · Maturity ramp */
  "m-1": "#c9d2db",
  "m-2": "#9db4cc",
  "m-3": "#6d8fb2",
  "m-4": "#426b95",
  "m-5": "#1e3a5c",

  /* التفاعل · Interaction */
  "focus-ring": "#3d6690",
  "on-brand": "#ffffff",
  "on-accent": "#ffffff",
  overlay: "rgba(15, 27, 40, 0.42)",

  /* الظلال · Elevation */
  "shadow-sm": "0 1px 2px rgba(15, 27, 40, 0.06)",
  "shadow-md": "0 2px 4px rgba(15, 27, 40, 0.05), 0 8px 20px -12px rgba(15, 27, 40, 0.22)",
  "shadow-lg": "0 4px 8px rgba(15, 27, 40, 0.05), 0 20px 44px -20px rgba(15, 27, 40, 0.28)",
};

/** ──────────────────────────────────────────────────────────────────────
 *  ٢. الوضع الليلي  ·  Dark mode
 *  نفس الأدوار، لا عكس آلي — كل قيمة مضبوطة على تباين مقروء.
 *  ────────────────────────────────────────────────────────────────────── */
export const dark: ThemeTokens = {
  "brand-50": "#0f1a26",
  "brand-100": "#14243a",
  "brand-200": "#1d3350",
  "brand-300": "#2c4a6d",
  "brand-400": "#4a72a0",
  "brand-500": "#6d9bc9",
  "brand-600": "#8fb4dd",
  "brand-700": "#a9c7e8",
  "brand-800": "#c6dbf1",
  "brand-900": "#e2edf8",

  "accent-100": "#33260f",
  "accent-300": "#8a6528",
  "accent-500": "#d5a35c",
  "accent-600": "#e2b877",
  "accent-700": "#f0d5a6",

  paper: "#0a1119",
  "paper-alt": "#0d151f",
  surface: "#121c28",
  "surface-2": "#182432",
  "surface-3": "#1f2d3d",
  ink: "#e6edf4",
  "ink-2": "#a8bacb",
  "ink-3": "#7d92a6",
  "ink-4": "#5d7185",
  line: "#22303f",
  "line-2": "#2d3e50",
  "line-strong": "#3f5468",

  ok: "#5cc192",
  "ok-bg": "#0f2f22",
  warn: "#d9b160",
  "warn-bg": "#312811",
  danger: "#e0836a",
  "danger-bg": "#361d16",
  info: "#8fb4dd",
  "info-bg": "#14243a",

  "m-1": "#233242",
  "m-2": "#2f4b64",
  "m-3": "#456d92",
  "m-4": "#6193c0",
  "m-5": "#8fb4dd",

  "focus-ring": "#6d9bc9",
  "on-brand": "#0a1119",
  "on-accent": "#0a1119",
  overlay: "rgba(3, 7, 12, 0.66)",

  "shadow-sm": "0 1px 2px rgba(0, 0, 0, 0.5)",
  "shadow-md": "0 2px 4px rgba(0, 0, 0, 0.4), 0 8px 20px -12px rgba(0, 0, 0, 0.8)",
  "shadow-lg": "0 4px 8px rgba(0, 0, 0, 0.4), 0 20px 44px -20px rgba(0, 0, 0, 0.9)",
};

/** ──────────────────────────────────────────────────────────────────────
 *  ٣. رموز غير لونية — المقاسات والخطوط
 *     Non-colour tokens: spacing, radii, type. Theme-independent.
 *  ────────────────────────────────────────────────────────────────────── */
export const constants: ThemeTokens = {
  "radius-sm": "5px",
  "radius": "9px",
  "radius-lg": "14px",
  "radius-pill": "999px",

  "space-1": "4px",
  "space-2": "8px",
  "space-3": "12px",
  "space-4": "16px",
  "space-5": "24px",
  "space-6": "32px",
  "space-7": "48px",
  "space-8": "72px",

  "font-body":
    '"IBM Plex Sans Arabic", "IBM Plex Sans", -apple-system, "Segoe UI", Tahoma, sans-serif',
  "font-display": '"Readex Pro", "IBM Plex Sans Arabic", sans-serif',
  "font-mono": '"IBM Plex Mono", ui-monospace, "Cascadia Mono", monospace',

  "text-xs": "0.72rem",
  "text-sm": "0.82rem",
  "text-base": "0.94rem",
  "text-lg": "1.06rem",
  "text-xl": "1.25rem",
  "text-2xl": "1.55rem",
  "text-3xl": "2rem",
  "text-4xl": "clamp(2rem, 1.3rem + 2.8vw, 3.1rem)",

  "ease": "cubic-bezier(0.2, 0, 0, 1)",
  "shell-max": "1180px",
};

/** Serialise a token map into CSS custom properties. */
function toCss(tokens: ThemeTokens): string {
  return Object.entries(tokens)
    .map(([name, value]) => `--${name}:${value};`)
    .join("");
}

/**
 * The complete stylesheet for the token layer, covering all three theme
 * states: no stamp (follows the OS), explicit light, explicit dark.
 */
export function paletteCss(): string {
  return [
    `:root{${toCss(constants)}${toCss(light)}}`,
    `@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){${toCss(dark)}}}`,
    `:root[data-theme="dark"]{${toCss(dark)}}`,
    `:root[data-theme="light"]{${toCss(light)}}`,
  ].join("\n");
}

/** Ordered maturity ramp, for charts that need the scale as an array. */
export const maturityRamp = ["var(--m-1)", "var(--m-2)", "var(--m-3)", "var(--m-4)", "var(--m-5)"];
