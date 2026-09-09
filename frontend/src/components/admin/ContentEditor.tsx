"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { useLocale } from "@/i18n/LocaleProvider";
import type { MessageKey } from "@/i18n/messages";
import {
  ApiError,
  api,
  type AdminFramework,
  type Axis,
  type FrameworkVersion,
  type MaturityLevel,
  type Question,
} from "@/lib/api";

type Section = "pillars" | "levels" | "scoring" | "roadmap" | "initiatives";

/**
 * FR-33 — pillars, questions, weights, maturity levels, scoring logic and the
 * required supporting documents, all editable without a code change.
 *
 * Everything here targets one framework version, and a published version is
 * read-only: the version selector only offers drafts for editing, which is what
 * keeps historical assessments reproducible (FR-35).
 */
export function ContentEditor({ onError }: { onError: (e: ApiError) => void }) {
  const { t } = useLocale();
  const [frameworks, setFrameworks] = useState<AdminFramework[]>([]);
  const [versionId, setVersionId] = useState<string | null>(null);
  const [version, setVersion] = useState<FrameworkVersion | null>(null);
  const [section, setSection] = useState<Section>("pillars");
  const [notice, setNotice] = useState<string | null>(null);

  const loadFrameworks = useCallback(async () => {
    const rows = await api<AdminFramework[]>("/admin/frameworks");
    setFrameworks(rows);
    setVersionId((current) => {
      if (current) return current;
      // Open on the version worth editing: the fullest draft, falling back to
      // the fullest version of any status. An empty draft left over from a
      // clone would otherwise greet the editor with a blank screen.
      const best = [...rows.flatMap((f) => f.versions)].sort(
        (a, b) =>
          b.question_count - a.question_count ||
          Number(b.status === "draft") - Number(a.status === "draft"),
      )[0];
      return best?.id ?? null;
    });
  }, []);

  const loadVersion = useCallback(async (id: string) => {
    setVersion(await api<FrameworkVersion>(`/frameworks/versions/${id}`));
  }, []);

  useEffect(() => {
    loadFrameworks().catch((e) => e instanceof ApiError && onError(e));
  }, [loadFrameworks, onError]);

  useEffect(() => {
    if (versionId) loadVersion(versionId).catch((e) => e instanceof ApiError && onError(e));
  }, [versionId, loadVersion, onError]);

  const editable = useMemo(() => version?.status === "draft", [version]);

  const flash = (message: string) => {
    setNotice(message);
    setTimeout(() => setNotice(null), 2500);
  };

  const refresh = async () => {
    if (versionId) await loadVersion(versionId);
    await loadFrameworks();
  };

  if (!frameworks.length) return <div className="card card-pad dim">{t("common.loading")}</div>;

  return (
    <div className="stack stack-4">
      <div className="row row-tight">
        <div className="field" style={{ minWidth: 300 }}>
          <label htmlFor="version-select">{t("admin.versions")}</label>
          <select
            id="version-select"
            value={versionId ?? ""}
            onChange={(e) => setVersionId(e.target.value)}
          >
            {frameworks.map((framework) =>
              framework.versions.map((v) => (
                <option key={v.id} value={v.id}>
                  {framework.code} · {v.version} · {t(`admin.${v.status}` as MessageKey)} ·{" "}
                  {v.question_count}
                </option>
              )),
            )}
          </select>
        </div>
        {version && (
          <span className={`chip ${editable ? "chip-warn" : "chip-ok"}`}>
            {editable ? t("admin.draft") : t("admin.published")}
          </span>
        )}
        {notice && <span className="chip chip-ok push">{notice}</span>}
      </div>

      {!editable && version && (
        <div className="note note-warn">{t("admin.publishedReadOnly")}</div>
      )}

      <nav className="row row-tight">
        {(["pillars", "levels", "scoring", "roadmap", "initiatives"] as Section[]).map((key) => (
          <button
            key={key}
            type="button"
            className={`btn btn-sm ${section === key ? "btn-secondary" : "btn-ghost"}`}
            onClick={() => setSection(key)}
          >
            {t(`content.${key}` as MessageKey)}
          </button>
        ))}
      </nav>

      {version && section === "pillars" && (
        <Pillars version={version} editable={editable} onDone={refresh} onError={onError} flash={flash} />
      )}
      {version && section === "levels" && (
        <Levels version={version} editable={editable} onDone={refresh} onError={onError} flash={flash} />
      )}
      {version && section === "scoring" && (
        <Scoring version={version} editable={editable} onDone={refresh} onError={onError} flash={flash} />
      )}
      {version && section === "roadmap" && (
        <Horizons version={version} onDone={refresh} onError={onError} flash={flash} />
      )}
      {version && section === "initiatives" && (
        <Initiatives version={version} onDone={refresh} onError={onError} flash={flash} />
      )}
    </div>
  );
}

type PanelProps = {
  version: FrameworkVersion;
  editable?: boolean;
  onDone: () => Promise<void>;
  onError: (e: ApiError) => void;
  flash: (m: string) => void;
};

/* ───────────────────────── pillars & questions ─────────────────────────── */

function Pillars({ version, editable, onDone, onError, flash }: PanelProps) {
  const { t } = useLocale();
  const [openAxis, setOpenAxis] = useState<string | null>(version.axes[0]?.id ?? null);
  const [adding, setAdding] = useState(false);

  async function call(path: string, method: string, body?: unknown, message?: string) {
    try {
      await api(path, { method, body });
      await onDone();
      if (message) flash(message);
    } catch (e) {
      if (e instanceof ApiError) onError(e);
    }
  }

  return (
    <div className="stack stack-3">
      <div className="row row-tight">
        <span className="chip mono">
          {version.axis_count} {t("admin.axes")}
        </span>
        <span className="chip mono">
          {version.question_count} {t("admin.questionsCount")}
        </span>
        {editable && (
          <button type="button" className="btn btn-primary btn-sm push" onClick={() => setAdding(true)}>
            {t("content.addPillar")}
          </button>
        )}
      </div>

      {adding && (
        <AxisForm
          onCancel={() => setAdding(false)}
          onSave={async (body) => {
            await call(`/admin/versions/${version.id}/axes`, "POST", body, t("common.save"));
            setAdding(false);
          }}
        />
      )}

      {version.axes.map((axis) => (
        <AxisPanel
          key={axis.id}
          axis={axis}
          open={openAxis === axis.id}
          editable={!!editable}
          onToggle={() => setOpenAxis(openAxis === axis.id ? null : axis.id)}
          onCall={call}
        />
      ))}
    </div>
  );
}

function AxisPanel({
  axis,
  open,
  editable,
  onToggle,
  onCall,
}: {
  axis: Axis;
  open: boolean;
  editable: boolean;
  onToggle: () => void;
  onCall: (path: string, method: string, body?: unknown, message?: string) => Promise<void>;
}) {
  const { t, pick } = useLocale();
  const [editing, setEditing] = useState(false);
  const [addingQuestion, setAddingQuestion] = useState(false);
  const [editingQuestion, setEditingQuestion] = useState<string | null>(null);

  return (
    <article className="card">
      <div className="row row-tight" style={{ padding: "var(--space-3) var(--space-4)" }}>
        <button type="button" className="btn btn-ghost btn-sm" onClick={onToggle} aria-expanded={open}>
          {open ? "−" : "+"}
        </button>
        <span className="mono" style={{ fontSize: "var(--text-xs)", color: "var(--brand-500)" }}>
          {axis.code}
        </span>
        <strong style={{ fontSize: "var(--text-sm)" }}>{pick(axis, "name")}</strong>
        <span className="chip mono">
          {t("questionnaire.weight")} {axis.weight}
        </span>
        <span className="chip mono">{axis.questions.length}</span>
        {editable && (
          <div className="row row-tight push">
            <button type="button" className="btn btn-ghost btn-sm" onClick={() => setEditing(!editing)}>
              {t("content.edit")}
            </button>
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              onClick={() => onCall(`/admin/axes/${axis.id}`, "DELETE", undefined, t("content.deleted"))}
            >
              {t("evidence.delete")}
            </button>
          </div>
        )}
      </div>

      {editing && (
        <div style={{ padding: "0 var(--space-4) var(--space-4)" }}>
          <AxisForm
            initial={axis}
            onCancel={() => setEditing(false)}
            onSave={async (body) => {
              await onCall(`/admin/axes/${axis.id}`, "PATCH", body, t("common.save"));
              setEditing(false);
            }}
          />
        </div>
      )}

      {open && (
        <div className="stack stack-2" style={{ padding: "0 var(--space-4) var(--space-4)" }}>
          {axis.questions.map((question) => (
            <div key={question.id} className="panel stack stack-2">
              <div className="row row-tight">
                <span className="mono dim" style={{ fontSize: "var(--text-xs)" }}>
                  {question.code}
                </span>
                <span style={{ fontSize: "var(--text-sm)", flex: 1, minWidth: 0 }}>
                  {pick(question, "text")}
                </span>
                <span className="chip mono">{question.weight}</span>
                {question.is_mandatory && <span className="chip chip-brand">{t("questionnaire.mandatory")}</span>}
                {question.evidence_required && <span className="chip">{t("content.evidence")}</span>}
                {editable && (
                  <div className="row row-tight push">
                    <button
                      type="button"
                      className="btn btn-ghost btn-sm"
                      onClick={() =>
                        setEditingQuestion(editingQuestion === question.id ? null : question.id)
                      }
                    >
                      {t("content.edit")}
                    </button>
                    <button
                      type="button"
                      className="btn btn-ghost btn-sm"
                      onClick={() =>
                        onCall(`/admin/questions/${question.id}`, "DELETE", undefined, t("content.deleted"))
                      }
                    >
                      {t("evidence.delete")}
                    </button>
                  </div>
                )}
              </div>
              {editingQuestion === question.id && (
                <QuestionForm
                  initial={question}
                  onCancel={() => setEditingQuestion(null)}
                  onSave={async (body) => {
                    await onCall(`/admin/questions/${question.id}`, "PATCH", body, t("common.save"));
                    setEditingQuestion(null);
                  }}
                />
              )}
            </div>
          ))}

          {editable && !addingQuestion && (
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              style={{ alignSelf: "flex-start" }}
              onClick={() => setAddingQuestion(true)}
            >
              {t("content.addQuestion")}
            </button>
          )}
          {addingQuestion && (
            <QuestionForm
              onCancel={() => setAddingQuestion(false)}
              onSave={async (body) => {
                await onCall(`/admin/axes/${axis.id}/questions`, "POST", body, t("common.save"));
                setAddingQuestion(false);
              }}
            />
          )}
        </div>
      )}
    </article>
  );
}

function AxisForm({
  initial,
  onCancel,
  onSave,
}: {
  initial?: Axis;
  onCancel: () => void;
  onSave: (body: Record<string, unknown>) => Promise<void>;
}) {
  const { t } = useLocale();
  const [form, setForm] = useState({
    code: initial?.code ?? "",
    name_ar: initial?.name_ar ?? "",
    name_en: initial?.name_en ?? "",
    description_ar: initial?.description_ar ?? "",
    description_en: initial?.description_en ?? "",
    weight: initial?.weight ?? 1,
  });
  const set = (k: keyof typeof form) => (e: { target: { value: string } }) =>
    setForm({ ...form, [k]: k === "weight" ? Number(e.target.value) : e.target.value });

  return (
    <div className="panel stack stack-3">
      <div className="grid grid-auto-md">
        <Field id="ax-code" label={t("content.code")} value={form.code} onChange={set("code")} dir="ltr" />
        <Field id="ax-weight" label={t("questionnaire.weight")} value={String(form.weight)} onChange={set("weight")} type="number" />
        <Field id="ax-ar" label={t("content.nameAr")} value={form.name_ar} onChange={set("name_ar")} />
        <Field id="ax-en" label={t("content.nameEn")} value={form.name_en} onChange={set("name_en")} dir="ltr" />
      </div>
      <div className="row row-tight">
        <button type="button" className="btn btn-primary btn-sm" onClick={() => onSave(form)}>
          {t("common.save")}
        </button>
        <button type="button" className="btn btn-ghost btn-sm" onClick={onCancel}>
          {t("common.cancel")}
        </button>
      </div>
    </div>
  );
}

function QuestionForm({
  initial,
  onCancel,
  onSave,
}: {
  initial?: Question;
  onCancel: () => void;
  onSave: (body: Record<string, unknown>) => Promise<void>;
}) {
  const { t } = useLocale();
  const [form, setForm] = useState({
    code: initial?.code ?? "",
    text_ar: initial?.text_ar ?? "",
    text_en: initial?.text_en ?? "",
    evidence_hint_ar: initial?.evidence_hint_ar ?? "",
    evidence_hint_en: initial?.evidence_hint_en ?? "",
    weight: initial?.weight ?? 1,
    is_mandatory: initial?.is_mandatory ?? true,
    evidence_required: initial?.evidence_required ?? false,
    allow_not_applicable: initial?.allow_not_applicable ?? true,
  });

  return (
    <div className="panel stack stack-3">
      <div className="grid grid-auto-md">
        <Field id="q-code" label={t("content.code")} value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value })} dir="ltr" />
        <Field id="q-weight" label={t("questionnaire.weight")} value={String(form.weight)} type="number" onChange={(e) => setForm({ ...form, weight: Number(e.target.value) })} />
      </div>
      <Field id="q-ar" label={t("content.textAr")} value={form.text_ar} onChange={(e) => setForm({ ...form, text_ar: e.target.value })} textarea />
      <Field id="q-en" label={t("content.textEn")} value={form.text_en} onChange={(e) => setForm({ ...form, text_en: e.target.value })} textarea dir="ltr" />
      <div className="grid grid-auto-md">
        <Field id="q-ev-ar" label={t("content.evidenceHintAr")} value={form.evidence_hint_ar ?? ""} onChange={(e) => setForm({ ...form, evidence_hint_ar: e.target.value })} />
        <Field id="q-ev-en" label={t("content.evidenceHintEn")} value={form.evidence_hint_en ?? ""} onChange={(e) => setForm({ ...form, evidence_hint_en: e.target.value })} dir="ltr" />
      </div>
      <div className="row row-tight">
        <label className="check">
          <input type="checkbox" checked={form.is_mandatory} onChange={(e) => setForm({ ...form, is_mandatory: e.target.checked })} />
          {t("questionnaire.mandatory")}
        </label>
        <label className="check">
          <input type="checkbox" checked={form.evidence_required} onChange={(e) => setForm({ ...form, evidence_required: e.target.checked })} />
          {t("content.evidenceRequired")}
        </label>
        <label className="check">
          <input type="checkbox" checked={form.allow_not_applicable} onChange={(e) => setForm({ ...form, allow_not_applicable: e.target.checked })} />
          {t("questionnaire.notApplicable")}
        </label>
      </div>
      <div className="row row-tight">
        <button type="button" className="btn btn-primary btn-sm" onClick={() => onSave(form)}>
          {t("common.save")}
        </button>
        <button type="button" className="btn btn-ghost btn-sm" onClick={onCancel}>
          {t("common.cancel")}
        </button>
      </div>
    </div>
  );
}

/* ─────────────────────────── maturity levels ───────────────────────────── */

function Levels({ version, editable, onDone, onError, flash }: PanelProps) {
  const { t } = useLocale();
  const [rows, setRows] = useState<MaturityLevel[]>(version.maturity_levels);

  useEffect(() => setRows(version.maturity_levels), [version]);

  function patch(score: number, field: string, value: string) {
    setRows(rows.map((r) => (r.score === score ? { ...r, [field]: value } : r)));
  }

  async function save() {
    try {
      await api(`/admin/versions/${version.id}/levels`, { method: "PUT", body: rows });
      await onDone();
      flash(t("common.save"));
    } catch (e) {
      if (e instanceof ApiError) onError(e);
    }
  }

  return (
    <div className="card card-pad stack stack-3">
      <p className="dim" style={{ fontSize: "var(--text-sm)" }}>{t("content.levelsHint")}</p>
      {rows.map((level) => (
        <div key={level.score} className="panel grid grid-auto-md">
          <Field id={`l-ar-${level.score}`} label={`${t("content.labelAr")} · ${level.score}`} value={level.label_ar} onChange={(e) => patch(level.score, "label_ar", e.target.value)} disabled={!editable} />
          <Field id={`l-en-${level.score}`} label={`${t("content.labelEn")} · ${level.score}`} value={level.label_en} onChange={(e) => patch(level.score, "label_en", e.target.value)} dir="ltr" disabled={!editable} />
          <Field id={`l-dar-${level.score}`} label={t("content.descAr")} value={level.description_ar ?? ""} onChange={(e) => patch(level.score, "description_ar", e.target.value)} disabled={!editable} />
          <Field id={`l-den-${level.score}`} label={t("content.descEn")} value={level.description_en ?? ""} onChange={(e) => patch(level.score, "description_en", e.target.value)} dir="ltr" disabled={!editable} />
        </div>
      ))}
      {editable && (
        <button type="button" className="btn btn-primary" style={{ alignSelf: "flex-start" }} onClick={save}>
          {t("common.save")}
        </button>
      )}
    </div>
  );
}

/* ──────────────────────────── scoring rules ────────────────────────────── */

function Scoring({ version, editable, onDone, onError, flash }: PanelProps) {
  const { t } = useLocale();
  const config = version.scoring_config as Record<string, unknown>;
  const [form, setForm] = useState({
    formula: String(config.formula ?? "weighted_average"),
    na_handling: String(config.na_handling ?? "exclude"),
    min_axis_coverage: Number(config.min_axis_coverage ?? 0.6),
    strength_threshold: Number(config.strength_threshold ?? 3.5),
    gap_threshold: Number(config.gap_threshold ?? 2.5),
  });

  useEffect(() => {
    const c = version.scoring_config as Record<string, unknown>;
    setForm({
      formula: String(c.formula ?? "weighted_average"),
      na_handling: String(c.na_handling ?? "exclude"),
      min_axis_coverage: Number(c.min_axis_coverage ?? 0.6),
      strength_threshold: Number(c.strength_threshold ?? 3.5),
      gap_threshold: Number(c.gap_threshold ?? 2.5),
    });
  }, [version]);

  async function save() {
    try {
      await api(`/admin/versions/${version.id}/scoring`, { method: "PATCH", body: form });
      await onDone();
      flash(t("common.save"));
    } catch (e) {
      if (e instanceof ApiError) onError(e);
    }
  }

  return (
    <div className="card card-pad stack stack-4">
      <div className="note note-warn">{t("content.scoringWarning")}</div>

      <div className="field" style={{ maxWidth: 420 }}>
        <label htmlFor="formula">{t("admin.formula")}</label>
        <select id="formula" value={form.formula} disabled={!editable} onChange={(e) => setForm({ ...form, formula: e.target.value })}>
          <option value="weighted_average">{t("content.formulaWeighted")}</option>
          <option value="brd_literal">{t("content.formulaLiteral")}</option>
        </select>
        <span className="hint">
          {form.formula === "brd_literal" ? t("content.formulaLiteralHint") : t("content.formulaWeightedHint")}
        </span>
      </div>

      <div className="field" style={{ maxWidth: 420 }}>
        <label htmlFor="na">{t("admin.naHandling")}</label>
        <select id="na" value={form.na_handling} disabled={!editable} onChange={(e) => setForm({ ...form, na_handling: e.target.value })}>
          <option value="exclude">{t("content.naExclude")}</option>
          <option value="zero">{t("content.naZero")}</option>
        </select>
      </div>

      <div className="grid grid-auto-sm">
        <Field id="cov" label={t("admin.minCoverage")} type="number" step="0.05" value={String(form.min_axis_coverage)} disabled={!editable} onChange={(e) => setForm({ ...form, min_axis_coverage: Number(e.target.value) })} />
        <Field id="str" label={t("content.strengthThreshold")} type="number" step="0.1" value={String(form.strength_threshold)} disabled={!editable} onChange={(e) => setForm({ ...form, strength_threshold: Number(e.target.value) })} />
        <Field id="gap" label={t("content.gapThreshold")} type="number" step="0.1" value={String(form.gap_threshold)} disabled={!editable} onChange={(e) => setForm({ ...form, gap_threshold: Number(e.target.value) })} />
      </div>

      {editable && (
        <button type="button" className="btn btn-primary" style={{ alignSelf: "flex-start" }} onClick={save}>
          {t("common.save")}
        </button>
      )}
    </div>
  );
}

/* ─────────────────────────── roadmap horizons ──────────────────────────── */

type Horizon = {
  code: string;
  name_ar: string;
  name_en: string;
  months_from: number;
  months_to: number;
  order_index: number;
};

function Horizons({ version, onDone, onError, flash }: PanelProps) {
  const { t } = useLocale();
  const [rows, setRows] = useState<Horizon[]>([]);

  useEffect(() => {
    // A version seeded before horizons were configurable has none stored; the
    // defaults give the editor something to save rather than an empty form.
    api<Horizon[]>(`/admin/versions/${version.id}/horizons`)
      .then((rows) => setRows(rows.length ? rows : DEFAULT_HORIZONS))
      .catch(() => setRows(DEFAULT_HORIZONS));
  }, [version.id]);

  function patch(index: number, field: keyof Horizon, value: string) {
    setRows(rows.map((r, i) => (i === index ? { ...r, [field]: field.startsWith("months") ? Number(value) : value } : r)));
  }

  async function save() {
    try {
      await api(`/admin/versions/${version.id}/horizons`, {
        method: "PUT",
        body: rows.map((r, i) => ({ ...r, order_index: i })),
      });
      await onDone();
      flash(t("common.save"));
    } catch (e) {
      if (e instanceof ApiError) onError(e);
    }
  }

  return (
    <div className="card card-pad stack stack-3">
      <p className="dim" style={{ fontSize: "var(--text-sm)" }}>{t("content.horizonsHint")}</p>
      {rows.map((horizon, index) => (
        <div key={horizon.code} className="panel grid grid-auto-sm">
          <Field id={`h-code-${index}`} label={t("content.code")} value={horizon.code} dir="ltr" onChange={(e) => patch(index, "code", e.target.value)} />
          <Field id={`h-ar-${index}`} label={t("content.nameAr")} value={horizon.name_ar} onChange={(e) => patch(index, "name_ar", e.target.value)} />
          <Field id={`h-en-${index}`} label={t("content.nameEn")} value={horizon.name_en} dir="ltr" onChange={(e) => patch(index, "name_en", e.target.value)} />
          <Field id={`h-from-${index}`} label={t("content.monthsFrom")} type="number" value={String(horizon.months_from)} onChange={(e) => patch(index, "months_from", e.target.value)} />
          <Field id={`h-to-${index}`} label={t("content.monthsTo")} type="number" value={String(horizon.months_to)} onChange={(e) => patch(index, "months_to", e.target.value)} />
        </div>
      ))}
      <div className="row row-tight">
        <button type="button" className="btn btn-primary btn-sm" onClick={save}>
          {t("common.save")}
        </button>
        <button
          type="button"
          className="btn btn-secondary btn-sm"
          onClick={() =>
            setRows([
              ...rows,
              { code: `h${rows.length + 1}`, name_ar: "", name_en: "", months_from: 0, months_to: 3, order_index: rows.length },
            ])
          }
        >
          {t("content.addHorizon")}
        </button>
      </div>
    </div>
  );
}

const DEFAULT_HORIZONS: Horizon[] = [
  { code: "immediate", name_ar: "أولويات فورية", name_en: "Immediate priorities", months_from: 0, months_to: 3, order_index: 0 },
  { code: "short", name_ar: "المدى القصير", name_en: "Short term", months_from: 3, months_to: 6, order_index: 1 },
  { code: "medium", name_ar: "المدى المتوسط", name_en: "Medium term", months_from: 6, months_to: 12, order_index: 2 },
  { code: "long", name_ar: "المدى الطويل", name_en: "Long term", months_from: 12, months_to: 24, order_index: 3 },
];

/* ────────────────────────── initiative library ─────────────────────────── */

type Template = {
  id: string;
  code: string;
  axis_id: string | null;
  title_ar: string;
  title_en: string;
  applies_min_score: number;
  applies_max_score: number;
  default_horizon_code: string | null;
  is_active: boolean;
};

function Initiatives({ version, onDone, onError, flash }: PanelProps) {
  const { t, pick } = useLocale();
  const [rows, setRows] = useState<Template[]>([]);
  const [adding, setAdding] = useState(false);
  const [form, setForm] = useState({
    code: "",
    title_ar: "",
    title_en: "",
    applies_min_score: 1,
    applies_max_score: 5,
    default_horizon_code: "immediate",
  });

  const load = useCallback(async () => {
    setRows(await api<Template[]>(`/admin/versions/${version.id}/initiative-templates`));
  }, [version.id]);

  useEffect(() => {
    load().catch((e) => e instanceof ApiError && onError(e));
  }, [load, onError]);

  async function create() {
    try {
      await api(`/admin/versions/${version.id}/initiative-templates`, { method: "POST", body: form });
      setAdding(false);
      setForm({ code: "", title_ar: "", title_en: "", applies_min_score: 1, applies_max_score: 5, default_horizon_code: "immediate" });
      await load();
      flash(t("common.save"));
    } catch (e) {
      if (e instanceof ApiError) onError(e);
    }
  }

  async function remove(id: string) {
    try {
      await api(`/admin/initiative-templates/${id}`, { method: "DELETE" });
      await load();
    } catch (e) {
      if (e instanceof ApiError) onError(e);
    }
  }

  return (
    <div className="stack stack-3">
      <div className="row row-tight">
        <span className="chip mono">{rows.length}</span>
        <p className="dim" style={{ fontSize: "var(--text-sm)", flex: 1 }}>{t("content.initiativesHint")}</p>
        <button type="button" className="btn btn-primary btn-sm" onClick={() => setAdding(!adding)}>
          {t("content.addInitiative")}
        </button>
      </div>

      {adding && (
        <div className="panel stack stack-3">
          <div className="grid grid-auto-md">
            <Field id="i-code" label={t("content.code")} value={form.code} dir="ltr" onChange={(e) => setForm({ ...form, code: e.target.value })} />
            <Field id="i-min" label={t("content.appliesFrom")} type="number" step="0.1" value={String(form.applies_min_score)} onChange={(e) => setForm({ ...form, applies_min_score: Number(e.target.value) })} />
            <Field id="i-max" label={t("content.appliesTo")} type="number" step="0.1" value={String(form.applies_max_score)} onChange={(e) => setForm({ ...form, applies_max_score: Number(e.target.value) })} />
          </div>
          <Field id="i-ar" label={t("content.titleAr")} value={form.title_ar} onChange={(e) => setForm({ ...form, title_ar: e.target.value })} />
          <Field id="i-en" label={t("content.titleEn")} value={form.title_en} dir="ltr" onChange={(e) => setForm({ ...form, title_en: e.target.value })} />
          <div className="row row-tight">
            <button type="button" className="btn btn-primary btn-sm" onClick={create}>
              {t("common.save")}
            </button>
            <button type="button" className="btn btn-ghost btn-sm" onClick={() => setAdding(false)}>
              {t("common.cancel")}
            </button>
          </div>
        </div>
      )}

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th style={{ width: 120 }}>{t("content.code")}</th>
              <th>{t("roadmap.title")}</th>
              <th style={{ width: 130 }}>{t("content.appliesBand")}</th>
              <th style={{ width: 120 }}>{t("roadmap.horizon")}</th>
              <th style={{ width: 90 }} />
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.id}>
                <td className="mono">{row.code}</td>
                <td>{pick(row, "title")}</td>
                <td className="mono">
                  {row.applies_min_score} – {row.applies_max_score}
                </td>
                <td className="mono dim">{row.default_horizon_code ?? "—"}</td>
                <td>
                  <button type="button" className="btn btn-ghost btn-sm" onClick={() => remove(row.id)}>
                    {t("evidence.delete")}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/* ────────────────────────────── shared field ───────────────────────────── */

function Field({
  id,
  label,
  value,
  onChange,
  type = "text",
  dir,
  step,
  textarea,
  disabled,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (e: { target: { value: string } }) => void;
  type?: string;
  dir?: "ltr" | "rtl";
  step?: string;
  textarea?: boolean;
  disabled?: boolean;
}) {
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      {textarea ? (
        <textarea id={id} rows={2} value={value} dir={dir} disabled={disabled} onChange={onChange} />
      ) : (
        <input id={id} type={type} step={step} value={value} dir={dir} disabled={disabled} onChange={onChange} />
      )}
    </div>
  );
}
