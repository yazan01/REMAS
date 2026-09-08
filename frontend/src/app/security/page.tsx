"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";

import { ErrorNote, InfoNote, Loading } from "@/components/AuthShell";
import { useLocale } from "@/i18n/LocaleProvider";
import { ApiError, api } from "@/lib/api";
import { useRequireSession, useSession } from "@/lib/session";

type Member = {
  id: string;
  email: string;
  full_name: string;
  role: string;
  mfa_enabled: boolean;
};

type Invite = {
  id: string;
  email: string;
  role: string;
  accepted: boolean;
  expires_at: string;
};

const IVALUE_ROLES = new Set(["ivalue_admin", "ivalue_reviewer"]);

export default function SecurityPage() {
  const { t, locale } = useLocale();
  const { me, loading } = useRequireSession();
  const { refresh: refreshSession } = useSession();

  const [error, setError] = useState<ApiError | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");

  const [enrolment, setEnrolment] = useState<{ secret: string; otpauth_uri: string } | null>(null);
  const [code, setCode] = useState("");

  const [members, setMembers] = useState<Member[]>([]);
  const [invites, setInvites] = useState<Invite[]>([]);
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState("contributor");

  const loadTeam = useCallback(async () => {
    const [memberRows, inviteRows] = await Promise.all([
      api<Member[]>("/account/members"),
      api<Invite[]>("/account/invitations").catch(() => [] as Invite[]),
    ]);
    setMembers(memberRows);
    setInvites(inviteRows);
  }, []);

  useEffect(() => {
    if (!me) return;
    loadTeam().catch((err) => err instanceof ApiError && setError(err));
  }, [me, loadTeam]);

  async function changePassword(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setNotice(null);
    try {
      await api("/account/password/change", {
        method: "POST",
        body: { current_password: current, new_password: next },
      });
      setCurrent("");
      setNext("");
      setNotice(t("security.saved"));
    } catch (err) {
      if (err instanceof ApiError) setError(err);
    }
  }

  async function startEnrolment() {
    setError(null);
    try {
      setEnrolment(await api("/account/mfa/enrol", { method: "POST" }));
    } catch (err) {
      if (err instanceof ApiError) setError(err);
    }
  }

  async function confirmEnrolment(event: FormEvent) {
    event.preventDefault();
    setError(null);
    try {
      await api("/account/mfa/confirm", { method: "POST", body: { code } });
      setEnrolment(null);
      setCode("");
      setNotice(t("security.saved"));
      await refreshSession();
    } catch (err) {
      if (err instanceof ApiError) setError(err);
    }
  }

  async function invite(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setNotice(null);
    try {
      await api("/account/invitations", {
        method: "POST",
        body: { email: inviteEmail, role: inviteRole },
      });
      setInviteEmail("");
      setNotice(t("security.sent"));
      await loadTeam();
    } catch (err) {
      if (err instanceof ApiError) setError(err);
    }
  }

  if (loading || !me) return <Loading label={t("common.loading")} />;

  const mfaOn = members.find((m) => m.id === me.user.id)?.mfa_enabled ?? false;
  const mandatory = IVALUE_ROLES.has(me.user.role);

  return (
    <div className="shell" style={{ paddingBottom: "var(--space-8)", maxWidth: 860 }}>
      <div className="page-head">
        <div>
          <span className="eyebrow" dir="ltr">
            {me.user.email}
          </span>
          <h1>{t("security.title")}</h1>
        </div>
      </div>

      {error && (
        <div style={{ marginBlockStart: "var(--space-4)" }}>
          <ErrorNote text={error.localised(locale)} />
        </div>
      )}
      {notice && (
        <div style={{ marginBlockStart: "var(--space-4)" }}>
          <InfoNote>{notice}</InfoNote>
        </div>
      )}

      {/* password */}
      <section style={{ marginBlockStart: "var(--space-6)" }}>
        <div className="section-head">
          <h2>{t("security.password")}</h2>
        </div>
        <form onSubmit={changePassword} className="card card-pad stack stack-4">
          <div className="field">
            <label htmlFor="current">{t("security.currentPassword")}</label>
            <input
              id="current"
              type="password"
              required
              dir="ltr"
              autoComplete="current-password"
              value={current}
              onChange={(e) => setCurrent(e.target.value)}
            />
          </div>
          <div className="field">
            <label htmlFor="next">{t("security.newPassword")}</label>
            <input
              id="next"
              type="password"
              required
              minLength={8}
              dir="ltr"
              autoComplete="new-password"
              value={next}
              onChange={(e) => setNext(e.target.value)}
            />
            <span className="hint">{t("auth.passwordHint")}</span>
          </div>
          <button type="submit" className="btn btn-primary" style={{ alignSelf: "flex-start" }}>
            {t("security.changePassword")}
          </button>
        </form>
      </section>

      {/* MFA */}
      <section style={{ marginBlockStart: "var(--space-6)" }}>
        <div className="section-head">
          <h2>{t("security.mfa")}</h2>
          <span className={`chip ${mfaOn ? "chip-ok" : "chip-warn"}`}>
            {mfaOn ? t("security.mfaOn") : t("security.mfaOff")}
          </span>
        </div>
        <div className="card card-pad stack stack-4">
          {mandatory && <p className="dim" style={{ fontSize: "var(--text-sm)" }}>{t("security.mfaRequired")}</p>}

          {!enrolment && !mfaOn && (
            <button
              type="button"
              className="btn btn-primary"
              style={{ alignSelf: "flex-start" }}
              onClick={startEnrolment}
            >
              {t("security.mfaEnrol")}
            </button>
          )}

          {enrolment && (
            <form onSubmit={confirmEnrolment} className="stack stack-4">
              <p className="muted" style={{ fontSize: "var(--text-sm)" }}>
                {t("security.mfaScan")}
              </p>
              <div className="panel stack stack-2">
                <span className="dim" style={{ fontSize: "var(--text-xs)" }}>
                  {t("security.mfaSecret")}
                </span>
                <code className="mono" dir="ltr" style={{ wordBreak: "break-all" }}>
                  {enrolment.secret}
                </code>
              </div>
              <div className="field" style={{ maxWidth: 200 }}>
                <label htmlFor="code">{t("security.mfaCode")}</label>
                <input
                  id="code"
                  inputMode="numeric"
                  dir="ltr"
                  required
                  minLength={6}
                  maxLength={8}
                  value={code}
                  onChange={(e) => setCode(e.target.value)}
                />
              </div>
              <button type="submit" className="btn btn-primary" style={{ alignSelf: "flex-start" }}>
                {t("security.mfaConfirm")}
              </button>
            </form>
          )}
        </div>
      </section>

      {/* team */}
      <section style={{ marginBlockStart: "var(--space-6)" }}>
        <div className="section-head">
          <h2>{t("security.team")}</h2>
          <span className="chip mono">{members.length}</span>
        </div>

        <div className="table-wrap" style={{ marginBlockEnd: "var(--space-4)" }}>
          <table>
            <thead>
              <tr>
                <th>{t("auth.fullName")}</th>
                <th>{t("auth.email")}</th>
                <th style={{ width: 150 }}>{t("security.inviteRole")}</th>
                <th style={{ width: 90 }}>{t("security.mfa")}</th>
              </tr>
            </thead>
            <tbody>
              {members.map((member) => (
                <tr key={member.id}>
                  <td>{member.full_name}</td>
                  <td className="mono" dir="ltr" style={{ fontSize: "var(--text-xs)" }}>
                    {member.email}
                  </td>
                  <td className="mono">{member.role}</td>
                  <td>
                    <span className={`chip ${member.mfa_enabled ? "chip-ok" : ""}`}>
                      {member.mfa_enabled ? "✓" : "—"}
                    </span>
                  </td>
                </tr>
              ))}
              {invites
                .filter((i) => !i.accepted)
                .map((invite) => (
                  <tr key={invite.id}>
                    <td className="dim">—</td>
                    <td className="mono" dir="ltr" style={{ fontSize: "var(--text-xs)" }}>
                      {invite.email}
                    </td>
                    <td className="mono">{invite.role}</td>
                    <td>
                      <span className="chip chip-warn">{t("security.pending")}</span>
                    </td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>

        <form onSubmit={invite} className="card card-pad row" style={{ alignItems: "flex-end" }}>
          <div className="field" style={{ flex: 1, minWidth: 220 }}>
            <label htmlFor="invite-email">{t("security.inviteEmail")}</label>
            <input
              id="invite-email"
              type="email"
              required
              dir="ltr"
              value={inviteEmail}
              onChange={(e) => setInviteEmail(e.target.value)}
            />
          </div>
          <div className="field" style={{ width: 190 }}>
            <label htmlFor="invite-role">{t("security.inviteRole")}</label>
            <select
              id="invite-role"
              value={inviteRole}
              onChange={(e) => setInviteRole(e.target.value)}
            >
              <option value="contributor">contributor</option>
              <option value="viewer">viewer</option>
              <option value="org_admin">org_admin</option>
            </select>
          </div>
          <button type="submit" className="btn btn-primary">
            {t("security.invite")}
          </button>
        </form>
      </section>
    </div>
  );
}
