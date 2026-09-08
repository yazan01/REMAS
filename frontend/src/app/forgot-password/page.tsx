"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { AuthShell, ErrorNote, InfoNote } from "@/components/AuthShell";
import { useLocale } from "@/i18n/LocaleProvider";
import { ApiError, api } from "@/lib/api";
import { useSession } from "@/lib/session";

export default function ForgotPasswordPage() {
  const { t, locale } = useLocale();
  const { signIn } = useSession();
  const router = useRouter();

  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [password, setPassword] = useState("");
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);

  async function request(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api("/account/password/reset-request", {
        method: "POST",
        auth: false,
        body: { email },
      });
      setSent(true);
    } catch (err) {
      if (err instanceof ApiError) setError(err);
    } finally {
      setBusy(false);
    }
  }

  // Development convenience: the backend logs the token rather than mailing it,
  // and exposes it on a dev-only endpoint. In production this becomes the link
  // the customer clicks in their inbox.
  async function resetNow(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const { token } = await api<{ token: string }>(
        `/account/password/dev-token?email=${encodeURIComponent(email)}`,
        { auth: false },
      );
      const res = await api<{ access_token: string }>("/account/password/reset", {
        method: "POST",
        auth: false,
        body: { token, password },
      });
      await signIn(res.access_token);
      router.push("/dashboard");
    } catch (err) {
      if (err instanceof ApiError) setError(err);
      setBusy(false);
    }
  }

  return (
    <AuthShell title={t("auth.resetTitle")} body={t("auth.resetBody")}>
      {!sent ? (
        <form onSubmit={request} className="stack stack-4">
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
          {error && <ErrorNote text={error.localised(locale)} />}
          <button type="submit" className="btn btn-primary btn-block" disabled={busy}>
            {busy ? t("common.loading") : t("auth.resetSend")}
          </button>
          <p className="muted" style={{ fontSize: "var(--text-sm)" }}>
            <Link href="/login">{t("nav.signIn")}</Link>
          </p>
        </form>
      ) : (
        <form onSubmit={resetNow} className="stack stack-4">
          <InfoNote>{t("auth.resetSent")}</InfoNote>
          <div className="field">
            <label htmlFor="password">{t("security.newPassword")}</label>
            <input
              id="password"
              type="password"
              required
              minLength={8}
              dir="ltr"
              autoComplete="new-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
            <span className="hint">{t("auth.passwordHint")}</span>
          </div>
          {error && <ErrorNote text={error.localised(locale)} />}
          <button type="submit" className="btn btn-primary btn-block" disabled={busy}>
            {busy ? t("common.loading") : t("auth.resetNew")}
          </button>
        </form>
      )}
    </AuthShell>
  );
}
