"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";

import { LanguageToggle } from "@/components/LanguageToggle";
import { useLocale } from "@/i18n/LocaleProvider";
import { useSession } from "@/lib/session";
import { ThemeToggle } from "@/theme/ThemeToggle";

export function Header() {
  const { t, pick } = useLocale();
  const { me, signOut } = useSession();
  const router = useRouter();
  const pathname = usePathname();

  const orgName = me
    ? pick({ name_ar: me.organization_name_ar, name_en: me.organization_name_en }, "name")
    : null;

  return (
    <header className="masthead">
      <div className="shell masthead-inner">
        <Link href={me ? "/dashboard" : "/"} className="brand">
          {/* Five ascending bars — the maturity scale the whole product measures */}
          <span className="brand-mark" aria-hidden="true">
            <i />
            <i />
            <i />
            <i />
            <i />
          </span>
          <span>
            <span className="brand-name">{t("app.name")}</span>
            <span className="brand-sub">{t("app.tagline")}</span>
          </span>
        </Link>

        <nav className="row row-tight push">
          {me ? (
            <>
              <Link
                href="/dashboard"
                className="nav-link"
                aria-current={pathname === "/dashboard" ? "page" : undefined}
              >
                {t("nav.dashboard")}
              </Link>
              <span className="chip" title={me.user.email}>
                <span className="dot" />
                {orgName}
              </span>
              <LanguageToggle />
              <ThemeToggle />
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={() => {
                  signOut();
                  router.push("/");
                }}
              >
                {t("nav.signOut")}
              </button>
            </>
          ) : (
            <>
              <LanguageToggle />
              <ThemeToggle />
              <Link href="/login" className="btn btn-ghost btn-sm">
                {t("nav.signIn")}
              </Link>
              <Link href="/register" className="btn btn-primary btn-sm">
                {t("nav.register")}
              </Link>
            </>
          )}
        </nav>
      </div>
    </header>
  );
}
