import type { Metadata } from "next";

import { Header } from "@/components/Header";
import { LocaleProvider } from "@/i18n/LocaleProvider";
import { SessionProvider } from "@/lib/session";
import { BootScript, ThemeStyle } from "@/theme/ThemeStyle";

import "./globals.css";

export const metadata: Metadata = {
  title: "REMAS — تقييم النضج المؤسسي",
  description:
    "منصة تقييم النضج المؤسسي للمطوّرين العقاريين — Real Estate Developer Maturity Assessment.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ar" dir="rtl" suppressHydrationWarning>
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link
          rel="stylesheet"
          href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans+Arabic:wght@300;400;500;600;700&family=IBM+Plex+Sans:wght@400;500;600&family=Readex+Pro:wght@300;400;500;600&display=swap"
        />
        {/* Palette tokens, server-rendered from src/theme/palette.ts */}
        <ThemeStyle />
        {/* Restores stored language + theme before first paint */}
        <BootScript />
      </head>
      <body>
        <LocaleProvider>
          <SessionProvider>
            <Header />
            <main>{children}</main>
          </SessionProvider>
        </LocaleProvider>
      </body>
    </html>
  );
}
