"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { AuthShell, ErrorNote, InfoNote } from "@/components/AuthShell";
import { useLocale } from "@/i18n/LocaleProvider";
import { ApiError, api } from "@/lib/api";
import { useSession } from "@/lib/session";

export default function RegisterPage() {
  const { t, locale } = useLocale();
  const { signIn } = useSession();
  const router = useRouter();

  const [form, setForm] = useState({
    email: "",
    password: "",
    full_name: "",
    organization_name_ar: "",
    organization_name_en: "",
  });
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const [registered, setRegistered] = useState(false);

  const set = (key: keyof typeof form) => (e: { target: { value: string } }) =>
    setForm((prev) => ({ ...prev, [key]: e.target.value }));

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api("/auth/register", { method: "POST", auth: false, body: { ...form, locale } });
      setRegistered(true);
    } catch (err) {
      if (err instanceof ApiError) setError(err);
    } finally {
      setBusy(false);
    }
  }

  // Development convenience: the backend logs the verification token instead of
  // sending mail, and exposes it on a dev-only endpoint. In production this
  // block is replaced by "check your inbox".
  async function verifyNow() {
    setBusy(true);
    setError(null);
    try {
      const { token } = await api<{ token: string }>(
        `/auth/dev/verification-token?email=${encodeURIComponent(form.email)}`,
        { auth: false },
      );
      const res = await api<{ access_token: string }>("/auth/verify", {
        method: "POST",
        auth: false,
        body: { token },
      });
      await signIn(res.access_token);
      router.push("/dashboard");
    } catch (err) {
      if (err instanceof ApiError) setError(err);
      setBusy(false);
    }
  }

  if (registered) {
    return (
      <AuthShell title={t("auth.verifyTitle")} body={t("auth.verifyBody")}>
        <div className="stack stack-4">
          <InfoNote>
            <span dir="ltr" className="mono" style={{ fontSize: "var(--text-sm)" }}>
              {form.email}
            </span>
          </InfoNote>
          {error && <ErrorNote text={error.localised(locale)} />}
          <button type="button" className="btn btn-primary btn-block" onClick={verifyNow} disabled={busy}>
            {busy ? t("common.loading") : t("auth.verifyNow")}
          </button>
        </div>
      </AuthShell>
    );
  }

  return (
    <AuthShell title={t("auth.registerTitle")} body={t("auth.registerBody")}>
      <form onSubmit={onSubmit} className="stack stack-4">
        <div className="field">
          <label htmlFor="full_name">{t("auth.fullName")}</label>
          <input id="full_name" required value={form.full_name} onChange={set("full_name")} />
        </div>
        <div className="field">
          <label htmlFor="org_ar">{t("auth.orgNameAr")}</label>
          <input id="org_ar" required dir="rtl" value={form.organization_name_ar} onChange={set("organization_name_ar")} />
        </div>
        <div className="field">
          <label htmlFor="org_en">{t("auth.orgNameEn")}</label>
          <input id="org_en" required dir="ltr" value={form.organization_name_en} onChange={set("organization_name_en")} />
        </div>
        <div className="field">
          <label htmlFor="email">{t("auth.email")}</label>
          <input id="email" type="email" required dir="ltr" autoComplete="email" value={form.email} onChange={set("email")} />
        </div>
        <div className="field">
          <label htmlFor="password">{t("auth.password")}</label>
          <input
            id="password"
            type="password"
            required
            minLength={8}
            dir="ltr"
            autoComplete="new-password"
            value={form.password}
            onChange={set("password")}
          />
          <span className="hint">{t("auth.passwordHint")}</span>
        </div>

        {error && <ErrorNote text={error.localised(locale)} />}

        <button type="submit" className="btn btn-primary btn-block" disabled={busy}>
          {busy ? t("common.loading") : t("auth.submitRegister")}
        </button>

        <p className="muted" style={{ fontSize: "var(--text-sm)" }}>
          {t("auth.hasAccount")} <Link href="/login">{t("nav.signIn")}</Link>
        </p>
      </form>
    </AuthShell>
  );
}
