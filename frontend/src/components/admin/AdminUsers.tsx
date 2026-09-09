"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { useLocale } from "@/i18n/LocaleProvider";
import { ApiError, api, type AdminOrganization, type AdminUser, type AdminUserListing } from "@/lib/api";

/** Mirrors `UserRole` in the backend; the API returns the raw enum values. */
const ROLE_KEY: Record<string, string> = {
  ivalue_admin: "مسؤول المنصة|Platform administrator",
  ivalue_reviewer: "مراجع iValue|iValue reviewer",
  org_owner: "مالك المنشأة|Organisation owner",
  org_admin: "مسؤول المنشأة|Organisation administrator",
  contributor: "مساهم|Contributor",
  viewer: "مطّلع|Viewer",
};

/**
 * FR-31 — the user register across every tenant. Reviewers may read it; only a
 * platform administrator can change a role or suspend an account, which is why
 * the write controls disappear rather than fail on submit.
 */
export function AdminUsers({
  onError,
  canWrite,
}: {
  onError: (e: ApiError) => void;
  canWrite: boolean;
}) {
  const { t, pick, locale } = useLocale();
  const [listing, setListing] = useState<AdminUserListing | null>(null);
  const [orgs, setOrgs] = useState<AdminOrganization[]>([]);
  const [query, setQuery] = useState("");
  const [org, setOrg] = useState("");
  const [role, setRole] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    const params = new URLSearchParams({ limit: "300" });
    if (query) params.set("q", query);
    if (org) params.set("organization_id", org);
    if (role) params.set("role", role);
    setListing(await api<AdminUserListing>(`/admin/users?${params}`));
  }, [query, org, role]);

  useEffect(() => {
    load().catch((e) => e instanceof ApiError && onError(e));
  }, [load, onError]);

  useEffect(() => {
    api<AdminOrganization[]>("/admin/organizations")
      .then(setOrgs)
      .catch(() => setOrgs([]));
  }, []);

  const roles = useMemo(() => listing?.roles ?? [], [listing]);

  const roleLabel = (value: string) => {
    const pair = ROLE_KEY[value];
    if (!pair) return value;
    const [ar, en] = pair.split("|");
    return locale === "ar" ? ar : en;
  };

  async function patch(user: AdminUser, body: Record<string, unknown>) {
    setBusy(user.id);
    try {
      await api(`/admin/users/${user.id}`, { method: "PATCH", body });
      await load();
      setNotice(t("users.updated"));
      setTimeout(() => setNotice(null), 2500);
    } catch (e) {
      if (e instanceof ApiError) onError(e);
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="stack stack-4">
      <div className="row row-tight">
        <div className="field" style={{ flex: 1, maxWidth: 320 }}>
          <input
            placeholder={t("users.search")}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") void load();
            }}
          />
        </div>
        <div className="field" style={{ minWidth: 200 }}>
          <select value={org} onChange={(e) => setOrg(e.target.value)} aria-label={t("users.organization")}>
            <option value="">{t("users.allOrganizations")}</option>
            {orgs.map((o) => (
              <option key={o.id} value={o.id}>
                {pick(o, "name")}
              </option>
            ))}
          </select>
        </div>
        <div className="field" style={{ minWidth: 180 }}>
          <select value={role} onChange={(e) => setRole(e.target.value)} aria-label={t("users.role")}>
            <option value="">{t("users.allRoles")}</option>
            {roles.map((r) => (
              <option key={r} value={r}>
                {roleLabel(r)}
              </option>
            ))}
          </select>
        </div>
        <span className="chip mono">{listing?.count ?? 0}</span>
        {notice && <span className="chip chip-ok">{notice}</span>}
      </div>

      {!canWrite && <div className="note note-warn">{t("users.adminOnly")}</div>}

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>{t("admin.users")}</th>
              <th style={{ width: 190 }}>{t("users.organization")}</th>
              <th style={{ width: 210 }}>{t("users.role")}</th>
              <th style={{ width: 150 }}>{t("users.lastLogin")}</th>
              <th style={{ width: 120 }}>{t("admin.active")}</th>
            </tr>
          </thead>
          <tbody>
            {(listing?.items ?? []).map((user) => (
              <tr key={user.id} style={user.is_active ? undefined : { opacity: 0.55 }}>
                <td>
                  <span style={{ display: "block", fontSize: "var(--text-sm)" }}>{user.full_name}</span>
                  <span className="mono dim" style={{ fontSize: "var(--text-xs)" }} dir="ltr">
                    {user.email}
                  </span>
                  <span className="row row-tight" style={{ marginBlockStart: 4 }}>
                    {user.mfa_enabled && <span className="chip chip-ok">{t("users.mfa")}</span>}
                    <span className={`chip ${user.email_verified ? "" : "chip-warn"}`}>
                      {user.email_verified ? t("users.verified") : t("users.unverified")}
                    </span>
                  </span>
                </td>
                <td style={{ fontSize: "var(--text-sm)" }}>
                  {pick(
                    {
                      name_ar: user.organization_name_ar ?? "—",
                      name_en: user.organization_name_en ?? "—",
                    },
                    "name",
                  )}
                </td>
                <td>
                  {canWrite ? (
                    <select
                      value={user.role}
                      disabled={busy === user.id}
                      aria-label={t("users.role")}
                      onChange={(e) => void patch(user, { role: e.target.value })}
                    >
                      {roles.map((r) => (
                        <option key={r} value={r}>
                          {roleLabel(r)}
                        </option>
                      ))}
                    </select>
                  ) : (
                    <span className="chip">{roleLabel(user.role)}</span>
                  )}
                </td>
                <td className="mono dim" style={{ fontSize: "var(--text-xs)" }}>
                  {user.last_login_at ? user.last_login_at.slice(0, 16).replace("T", " ") : t("users.never")}
                </td>
                <td>
                  {canWrite ? (
                    <button
                      type="button"
                      className="btn btn-ghost btn-sm"
                      disabled={busy === user.id}
                      onClick={() => void patch(user, { is_active: !user.is_active })}
                    >
                      {user.is_active ? t("users.suspend") : t("users.activate")}
                    </button>
                  ) : (
                    <span className={`chip ${user.is_active ? "chip-ok" : "chip-warn"}`}>
                      {user.is_active ? t("admin.active") : t("users.suspend")}
                    </span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
