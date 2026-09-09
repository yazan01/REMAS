"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { ErrorNote, Loading } from "@/components/AuthShell";
import { AdminUsers } from "@/components/admin/AdminUsers";
import { ContentEditor } from "@/components/admin/ContentEditor";
import { ReportTemplates } from "@/components/ReportTemplates";
import { useLocale } from "@/i18n/LocaleProvider";
import type { MessageKey } from "@/i18n/messages";
import {
  ApiError,
  api,
  downloadFile,
  uploadFile,
  type AdminFramework,
  type AdminOrganization,
  type AuditRow,
} from "@/lib/api";
import { useRequireSession } from "@/lib/session";

const IVALUE_ROLES = new Set(["ivalue_admin", "ivalue_reviewer"]);
type Tab = "frameworks" | "content" | "templates" | "organizations" | "users" | "audit";
const TABS: Tab[] = ["frameworks", "content", "templates", "organizations", "users", "audit"];

export default function AdminPage() {
  const { t, pick, locale, num } = useLocale();
  const { me, loading } = useRequireSession();
  const [tab, setTab] = useState<Tab>("frameworks");
  const [error, setError] = useState<ApiError | null>(null);

  const isStaff = !!me && IVALUE_ROLES.has(me.user.role);

  if (loading || !me) return <Loading label={t("common.loading")} />;

  if (!isStaff) {
    return (
      <div className="shell shell-narrow" style={{ paddingBlock: "var(--space-8)" }}>
        <ErrorNote
          text={
            locale === "ar"
              ? "هذه الصفحة متاحة لفريق iValue فقط."
              : "This page is available to the iValue team only."
          }
        />
      </div>
    );
  }

  return (
    <div className="shell" style={{ paddingBottom: "var(--space-8)" }}>
      <div className="page-head">
        <div>
          <span className="eyebrow">iValue</span>
          <h1>{t("admin.title")}</h1>
        </div>
        <nav className="row row-tight">
          {TABS.map((key) => (
            <button
              key={key}
              type="button"
              className={`btn btn-sm ${tab === key ? "btn-primary" : "btn-ghost"}`}
              onClick={() => setTab(key)}
            >
              {key === "templates"
                ? t("template.title")
                : key === "users"
                  ? t("admin.usersTab")
                  : t(`admin.${key}` as MessageKey)}
            </button>
          ))}
        </nav>
      </div>

      {error && (
        <div style={{ marginBlockStart: "var(--space-4)" }}>
          <ErrorNote text={error.localised(locale)} />
        </div>
      )}

      <div style={{ marginBlockStart: "var(--space-5)" }}>
        {tab === "frameworks" && <Frameworks onError={setError} />}
        {tab === "content" && <ContentEditor onError={setError} />}
        {tab === "templates" && <ReportTemplates onError={setError} />}
        {tab === "organizations" && <Organizations onError={setError} />}
        {tab === "users" && (
          <AdminUsers onError={setError} canWrite={me.user.role === "ivalue_admin"} />
        )}
        {tab === "audit" && <AuditLog onError={setError} />}
      </div>
    </div>
  );
}

/* ─────────────────────────── frameworks tab ─────────────────────────────── */

function Frameworks({ onError }: { onError: (e: ApiError) => void }) {
  const { t, pick, locale } = useLocale();
  const [frameworks, setFrameworks] = useState<AdminFramework[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [importInto, setImportInto] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [draft, setDraft] = useState({ code: "", name_ar: "", name_en: "" });
  const fileInput = useRef<HTMLInputElement>(null);

  const refresh = useCallback(async () => {
    setFrameworks(await api<AdminFramework[]>("/admin/frameworks"));
  }, []);

  useEffect(() => {
    refresh().catch((err) => err instanceof ApiError && onError(err));
  }, [refresh, onError]);

  async function act(id: string, path: string, body?: unknown) {
    setBusy(id);
    try {
      await api(path, { method: "POST", body });
      await refresh();
    } catch (err) {
      if (err instanceof ApiError) onError(err);
    } finally {
      setBusy(null);
    }
  }

  async function createFramework() {
    setBusy("new");
    try {
      await api("/admin/frameworks", { method: "POST", body: draft });
      setDraft({ code: "", name_ar: "", name_en: "" });
      setCreating(false);
      await refresh();
    } catch (err) {
      if (err instanceof ApiError) onError(err);
    } finally {
      setBusy(null);
    }
  }

  async function setActive(id: string, is_active: boolean) {
    setBusy(id);
    try {
      await api(`/admin/frameworks/${id}`, { method: "PATCH", body: { is_active } });
      await refresh();
    } catch (err) {
      if (err instanceof ApiError) onError(err);
    } finally {
      setBusy(null);
    }
  }

  async function doImport(file: File) {
    if (!importInto) return;
    setBusy(importInto);
    setNotice(null);
    try {
      const res = await uploadFile<{ axes_created: number; questions_created: number }>(
        `/admin/versions/${importInto}/import`,
        file,
      );
      setNotice(
        `${t("admin.imported")}: ${res.axes_created} ${t("admin.axes")} · ${res.questions_created} ${t("admin.questionsCount")}`,
      );
      await refresh();
    } catch (err) {
      if (err instanceof ApiError) onError(err);
    } finally {
      setBusy(null);
      setImportInto(null);
      if (fileInput.current) fileInput.current.value = "";
    }
  }

  return (
    <div className="stack stack-4">
      <div className="row row-tight">
        <button
          type="button"
          className="btn btn-primary btn-sm"
          onClick={() => setCreating(!creating)}
        >
          {t("admin.newFramework")}
        </button>
        <button
          type="button"
          className="btn btn-secondary btn-sm"
          onClick={() =>
            void downloadFile("/admin/import-template.csv", "remas-import-template.csv")
          }
        >
          {t("admin.template")}
        </button>
        {notice && <span className="chip chip-ok">{notice}</span>}
      </div>

      {creating && (
        <div className="card card-pad stack stack-3">
          <div className="grid grid-auto-md">
            <div className="field">
              <label htmlFor="fw-code">{t("content.code")}</label>
              <input
                id="fw-code"
                dir="ltr"
                value={draft.code}
                onChange={(e) => setDraft({ ...draft, code: e.target.value.toUpperCase() })}
              />
            </div>
            <div className="field">
              <label htmlFor="fw-ar">{t("admin.frameworkNameAr")}</label>
              <input
                id="fw-ar"
                value={draft.name_ar}
                onChange={(e) => setDraft({ ...draft, name_ar: e.target.value })}
              />
            </div>
            <div className="field">
              <label htmlFor="fw-en">{t("admin.frameworkNameEn")}</label>
              <input
                id="fw-en"
                dir="ltr"
                value={draft.name_en}
                onChange={(e) => setDraft({ ...draft, name_en: e.target.value })}
              />
            </div>
          </div>
          {/* A new framework always starts as an empty 0.1 draft with the
              standard five levels and horizons seeded, so it can be imported
              into straight away. */}
          <div className="row row-tight">
            <button
              type="button"
              className="btn btn-primary btn-sm"
              disabled={busy === "new" || draft.code.length < 2 || !draft.name_ar || !draft.name_en}
              onClick={() => void createFramework()}
            >
              {t("admin.create")}
            </button>
            <button type="button" className="btn btn-ghost btn-sm" onClick={() => setCreating(false)}>
              {t("common.cancel")}
            </button>
          </div>
        </div>
      )}

      <input
        ref={fileInput}
        type="file"
        hidden
        accept=".csv,.xlsx,.xlsm"
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) void doImport(file);
        }}
      />

      {frameworks.map((framework) => (
        <article key={framework.id} className="card card-pad stack stack-4">
          <div className="row row-tight">
            <span className="mono chip chip-brand">{framework.code}</span>
            <h3 style={{ fontSize: "var(--text-lg)" }}>{pick(framework, "name")}</h3>
            {!framework.is_active && <span className="chip chip-warn">{t("admin.archived")}</span>}
            <button
              type="button"
              className="btn btn-ghost btn-sm push"
              disabled={busy === framework.id}
              onClick={() => void setActive(framework.id, !framework.is_active)}
            >
              {framework.is_active ? t("admin.deactivate") : t("admin.activate")}
            </button>
          </div>

          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>{t("admin.versions")}</th>
                  <th style={{ width: 120 }}>{t("assessment.status.draft")}</th>
                  <th className="num" style={{ width: 90 }}>
                    {t("admin.axes")}
                  </th>
                  <th className="num" style={{ width: 90 }}>
                    {t("admin.questionsCount")}
                  </th>
                  <th style={{ width: 260 }} />
                </tr>
              </thead>
              <tbody>
                {framework.versions.map((version) => (
                  <tr key={version.id}>
                    <td className="mono">{version.version}</td>
                    <td>
                      <span
                        className={`chip ${
                          version.status === "published"
                            ? "chip-ok"
                            : version.status === "draft"
                              ? "chip-warn"
                              : ""
                        }`}
                      >
                        {t(`admin.${version.status}` as MessageKey)}
                      </span>
                    </td>
                    <td className="mono" style={{ textAlign: "end" }}>
                      {version.axis_count}
                    </td>
                    <td className="mono" style={{ textAlign: "end" }}>
                      {version.question_count}
                    </td>
                    <td>
                      <div className="row row-tight">
                        {version.status === "draft" && (
                          <>
                            <button
                              type="button"
                              className="btn btn-secondary btn-sm"
                              disabled={busy === version.id}
                              onClick={() => {
                                setImportInto(version.id);
                                fileInput.current?.click();
                              }}
                            >
                              {t("admin.import")}
                            </button>
                            <button
                              type="button"
                              className="btn btn-primary btn-sm"
                              disabled={busy === version.id || version.axis_count === 0}
                              onClick={() =>
                                void act(version.id, `/admin/versions/${version.id}/publish`)
                              }
                            >
                              {t("admin.publish")}
                            </button>
                          </>
                        )}
                        {version.status !== "draft" && (
                          <button
                            type="button"
                            className="btn btn-secondary btn-sm"
                            disabled={busy === version.id}
                            onClick={() =>
                              void act(version.id, `/admin/versions/${version.id}/clone`, {
                                version: `${nextVersion(version.version)}-draft`,
                              })
                            }
                          >
                            {t("admin.clone")}
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <p className="dim" style={{ fontSize: "var(--text-xs)" }}>
            {t("admin.importHint")}
          </p>
        </article>
      ))}
    </div>
  );
}

function nextVersion(current: string): string {
  const match = current.match(/^(\d+)\.(\d+)/);
  if (!match) return `${current}.1`;
  return `${match[1]}.${Number(match[2]) + 1}`;
}

/* ────────────────────────── organizations tab ───────────────────────────── */

function Organizations({ onError }: { onError: (e: ApiError) => void }) {
  const { t, pick } = useLocale();
  const [rows, setRows] = useState<AdminOrganization[]>([]);

  const refresh = useCallback(async () => {
    setRows(await api<AdminOrganization[]>("/admin/organizations"));
  }, []);

  useEffect(() => {
    refresh().catch((err) => err instanceof ApiError && onError(err));
  }, [refresh, onError]);

  async function toggle(id: string, is_active: boolean) {
    try {
      await api(`/admin/organizations/${id}`, { method: "PATCH", body: { is_active } });
      await refresh();
    } catch (err) {
      if (err instanceof ApiError) onError(err);
    }
  }

  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>{t("admin.organizations")}</th>
            <th className="num" style={{ width: 90 }}>
              {t("admin.users")}
            </th>
            <th className="num" style={{ width: 110 }}>
              {t("admin.assessments")}
            </th>
            <th className="num" style={{ width: 110 }}>
              {t("dashboard.profileCompleteness")}
            </th>
            <th style={{ width: 110 }}>{t("admin.active")}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((org) => (
            <tr key={org.id}>
              <td>
                {pick(org, "name")}
                {org.is_ivalue && <span className="chip chip-brand push">iValue</span>}
                <span className="mono dim" style={{ display: "block", fontSize: "var(--text-xs)" }}>
                  {org.slug}
                </span>
              </td>
              <td className="mono" style={{ textAlign: "end" }}>
                {org.user_count}
              </td>
              <td className="mono" style={{ textAlign: "end" }}>
                {org.assessment_count}
              </td>
              <td className="mono" style={{ textAlign: "end" }}>
                {Math.round(org.profile_completeness * 100)}%
              </td>
              <td>
                <label className="check">
                  <input
                    type="checkbox"
                    checked={org.is_active}
                    disabled={org.is_ivalue}
                    onChange={(e) => void toggle(org.id, e.target.checked)}
                  />
                </label>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/* ───────────────────────────── audit tab ────────────────────────────────── */

function AuditLog({ onError }: { onError: (e: ApiError) => void }) {
  const { t } = useLocale();
  const [rows, setRows] = useState<AuditRow[]>([]);
  const [query, setQuery] = useState("");

  const search = useCallback(
    async (q: string) => {
      try {
        const res = await api<{ items: AuditRow[] }>(
          `/admin/audit?limit=150${q ? `&q=${encodeURIComponent(q)}` : ""}`,
        );
        setRows(res.items);
      } catch (err) {
        if (err instanceof ApiError) onError(err);
      }
    },
    [onError],
  );

  useEffect(() => {
    void search("");
  }, [search]);

  return (
    <div className="stack stack-4">
      <div className="row row-tight">
        <div className="field" style={{ flex: 1, maxWidth: 380 }}>
          <input
            placeholder={t("admin.searchAudit")}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") void search(query);
            }}
          />
        </div>
        <button type="button" className="btn btn-secondary btn-sm" onClick={() => void search(query)}>
          {t("common.retry")}
        </button>
        <button
          type="button"
          className="btn btn-ghost btn-sm push"
          onClick={() => void downloadFile("/admin/audit/export.csv", "remas-audit.csv")}
        >
          {t("admin.exportCsv")}
        </button>
      </div>

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th style={{ width: 160 }}>{t("admin.when")}</th>
              <th style={{ width: 210 }}>{t("admin.actor")}</th>
              <th>{t("admin.action")}</th>
              <th style={{ width: 160 }}>{t("admin.entity")}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.id}>
                <td className="mono" style={{ fontSize: "var(--text-xs)" }}>
                  {row.created_at.slice(0, 19).replace("T", " ")}
                </td>
                <td className="mono" style={{ fontSize: "var(--text-xs)" }} dir="ltr">
                  {row.actor_email ?? "—"}
                </td>
                <td className="mono">{row.action}</td>
                <td className="mono dim" style={{ fontSize: "var(--text-xs)" }}>
                  {row.entity_type}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
