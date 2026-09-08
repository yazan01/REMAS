"use client";

import { useCallback, useEffect, useState } from "react";

import { useLocale } from "@/i18n/LocaleProvider";
import type { MessageKey } from "@/i18n/messages";
import { ApiError, api, type ReportTemplateRow } from "@/lib/api";

type Listing = {
  templates: ReportTemplateRow[];
  available_sections: string[];
  defaults: { sections: ReportTemplateRow["sections"]; branding: Record<string, unknown> };
};

/**
 * FR-34 — report sections, wording, branding and output formats are edited
 * here, not in code. Everything on this screen ends up in the rendered PDF.
 */
export function ReportTemplates({ onError }: { onError: (e: ApiError) => void }) {
  const { t, pick, locale } = useLocale();
  const [listing, setListing] = useState<Listing | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [draft, setDraft] = useState<ReportTemplateRow | null>(null);
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    const data = await api<Listing>("/admin/report-templates");
    setListing(data);
    setSelectedId((current) => current ?? data.templates[0]?.id ?? null);
  }, []);

  useEffect(() => {
    refresh().catch((err) => err instanceof ApiError && onError(err));
  }, [refresh, onError]);

  useEffect(() => {
    const found = listing?.templates.find((tpl) => tpl.id === selectedId);
    setDraft(found ? structuredClone(found) : null);
    setSaved(false);
  }, [listing, selectedId]);

  async function save() {
    if (!draft) return;
    setBusy(true);
    try {
      await api(`/admin/report-templates/${draft.id}`, {
        method: "PATCH",
        body: {
          sections: draft.sections,
          branding: draft.branding,
          copy_blocks: draft.copy_blocks,
          output_formats: draft.output_formats,
          include_comparison: draft.include_comparison,
        },
      });
      setSaved(true);
      await refresh();
    } catch (err) {
      if (err instanceof ApiError) onError(err);
    } finally {
      setBusy(false);
    }
  }

  function patchBranding(key: string, value: string) {
    setDraft((prev) =>
      prev ? { ...prev, branding: { ...prev.branding, [key]: value } } : prev,
    );
  }

  function patchSection(key: string, patch: Partial<ReportTemplateRow["sections"][number]>) {
    setDraft((prev) =>
      prev
        ? {
            ...prev,
            sections: prev.sections.map((s) => (s.key === key ? { ...s, ...patch } : s)),
          }
        : prev,
    );
  }

  if (!listing) return <div className="card card-pad dim">{t("common.loading")}</div>;
  if (!draft) return <div className="card card-pad dim">{t("template.title")}</div>;

  const brand = draft.branding as Record<string, string>;
  const fallback = (listing.defaults.branding ?? {}) as Record<string, string>;

  return (
    <div className="stack stack-4">
      <div className="row row-tight">
        <div className="field" style={{ minWidth: 260 }}>
          <label htmlFor="template-select">{t("template.title")}</label>
          <select
            id="template-select"
            value={selectedId ?? ""}
            onChange={(e) => setSelectedId(e.target.value)}
          >
            {listing.templates.map((tpl) => (
              <option key={tpl.id} value={tpl.id}>
                {pick(tpl, "name")} {tpl.is_default ? "★" : ""}
              </option>
            ))}
          </select>
        </div>
        {saved && <span className="chip chip-ok push">{t("template.saved")}</span>}
      </div>

      <div className="split">
        {/* sections */}
        <div className="card card-pad stack stack-3">
          <h3 style={{ fontSize: "var(--text-base)" }}>{t("template.sections")}</h3>
          {draft.sections
            .slice()
            .sort((a, b) => a.order - b.order)
            .map((section) => (
              <div key={section.key} className="option-tile" data-on={section.enabled}>
                <input
                  type="checkbox"
                  checked={section.enabled}
                  onChange={(e) => patchSection(section.key, { enabled: e.target.checked })}
                  aria-label={t("template.enabled")}
                />
                <span style={{ fontSize: "var(--text-sm)", minWidth: 130 }}>
                  {t(`template.section.${section.key}` as MessageKey)}
                </span>
                <input
                  className="section-title-input"
                  placeholder={t("template.sectionTitle")}
                  value={
                    (locale === "ar" ? section.title_ar : section.title_en) ?? ""
                  }
                  onChange={(e) =>
                    patchSection(section.key, {
                      [locale === "ar" ? "title_ar" : "title_en"]: e.target.value || null,
                    })
                  }
                />
              </div>
            ))}

          <label className="check">
            <input
              type="checkbox"
              checked={draft.include_comparison}
              onChange={(e) =>
                setDraft({ ...draft, include_comparison: e.target.checked })
              }
            />
            {t("template.comparison")}
          </label>
        </div>

        {/* branding */}
        <div className="card card-pad stack stack-4">
          <h3 style={{ fontSize: "var(--text-base)" }}>{t("template.branding")}</h3>

          <div className="field">
            <label htmlFor="brand-org">{t("template.orgName")}</label>
            <input
              id="brand-org"
              value={brand.organisation_name ?? ""}
              onChange={(e) => patchBranding("organisation_name", e.target.value)}
            />
          </div>

          <div className="row row-tight">
            <ColourField
              id="brand-primary"
              label={t("template.primary")}
              value={brand.primary ?? fallback.primary ?? ""}
              onChange={(v) => patchBranding("primary", v)}
            />
            <ColourField
              id="brand-accent"
              label={t("template.accent")}
              value={brand.accent ?? fallback.accent ?? ""}
              onChange={(v) => patchBranding("accent", v)}
            />
          </div>

          <div className="field">
            <label>{t("template.formats")}</label>
            <div className="row row-tight">
              {["pdf", "html", "json"].map((format) => (
                <label key={format} className="check">
                  <input
                    type="checkbox"
                    checked={draft.output_formats.includes(format)}
                    onChange={(e) =>
                      setDraft({
                        ...draft,
                        output_formats: e.target.checked
                          ? [...draft.output_formats, format]
                          : draft.output_formats.filter((f) => f !== format),
                      })
                    }
                  />
                  <span className="mono">{format}</span>
                </label>
              ))}
            </div>
          </div>

          <button
            type="button"
            className="btn btn-primary"
            style={{ alignSelf: "flex-start" }}
            onClick={save}
            disabled={busy}
          >
            {busy ? t("common.loading") : t("template.save")}
          </button>
        </div>
      </div>

      <style>{`
        .section-title-input {
          margin-inline-start: auto; max-width: 200px;
          background: var(--surface); border: 1px solid var(--line);
          border-radius: var(--radius-sm); padding: 5px 9px;
          font-size: var(--text-xs);
        }
        .colour-field { display:flex; flex-direction:column; gap:var(--space-2); }
        .colour-row { display:flex; align-items:center; gap:var(--space-2); }
        .colour-row input[type="color"] {
          width: 38px; height: 34px; padding: 2px; border: 1px solid var(--line-2);
          border-radius: var(--radius-sm); background: var(--surface); cursor: pointer;
        }
      `}</style>
    </div>
  );
}

function ColourField({
  id,
  label,
  value,
  onChange,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <div className="colour-field">
      <label htmlFor={id} style={{ fontSize: "var(--text-sm)", color: "var(--ink-2)" }}>
        {label}
      </label>
      <div className="colour-row">
        <input id={id} type="color" value={value} onChange={(e) => onChange(e.target.value)} />
        <input
          className="section-title-input mono"
          dir="ltr"
          style={{ marginInlineStart: 0, width: 100 }}
          value={value}
          onChange={(e) => onChange(e.target.value)}
        />
      </div>
    </div>
  );
}
