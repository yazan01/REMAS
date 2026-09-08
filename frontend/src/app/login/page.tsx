"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { AuthShell, ErrorNote } from "@/components/AuthShell";
import { useLocale } from "@/i18n/LocaleProvider";
import { ApiError, api } from "@/lib/api";
import { useSession } from "@/lib/session";

export default function LoginPage() {
  const { t, locale } = useLocale();
  const { signIn } = useSession();
  const router = useRouter();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [mfaCode, setMfaCode] = useState("");
  const [needsMfa, setNeedsMfa] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const res = await api<{ access_token: string }>("/auth/login", {
        method: "POST",
        auth: false,
        body: { email, password, mfa_code: mfaCode || null },
      });
      await signIn(res.access_token);
      router.push("/dashboard");
    } catch (err) {
      if (err instanceof ApiError) {
        // The API tells us a second factor is required rather than the client
        // having to guess from the account state.
        if (err.details?.mfa_required) setNeedsMfa(true);
        setError(err);
      }
      setBusy(false);
    }
  }

  return (
    <AuthShell title={t("auth.signInTitle")} body={t("auth.signInBody")}>
      <form onSubmit={onSubmit} className="stack stack-4">
        <div className="field">
          <label htmlFor="email">{t("auth.email")}</label>
          <input
            id="email"
            type="email"
            required
            dir="ltr"
            autoComplete="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="password">{t("auth.password")}</label>
          <input
            id="password"
            type="password"
            required
            dir="ltr"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </div>

        {needsMfa && (
          <div className="field">
            <label htmlFor="mfa">{t("auth.mfaPrompt")}</label>
            <input
              id="mfa"
              inputMode="numeric"
              dir="ltr"
              autoComplete="one-time-code"
              maxLength={8}
              value={mfaCode}
              onChange={(e) => setMfaCode(e.target.value)}
            />
          </div>
        )}

        {error && <ErrorNote text={error.localised(locale)} />}

        <button type="submit" className="btn btn-primary btn-block" disabled={busy}>
          {busy ? t("common.loading") : t("auth.submitSignIn")}
        </button>

        <div className="row row-tight" style={{ justifyContent: "space-between" }}>
          <Link href="/forgot-password" style={{ fontSize: "var(--text-sm)" }}>
            {t("auth.forgot")}
          </Link>
          <span className="muted" style={{ fontSize: "var(--text-sm)" }}>
            {t("auth.noAccount")} <Link href="/register">{t("nav.register")}</Link>
          </span>
        </div>
      </form>
    </AuthShell>
  );
}
