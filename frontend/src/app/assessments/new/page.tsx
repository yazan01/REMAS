"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";

import { ErrorNote, Loading } from "@/components/AuthShell";
import { useLocale } from "@/i18n/LocaleProvider";
import { ApiError, api, type Assessment, type FrameworkVersion, type Layer } from "@/lib/api";
import { useRequireSession } from "@/lib/session";

export default function NewAssessmentPage() {
  const { t, pick, num, locale } = useLocale();
  const { me, loading } = useRequireSession();
  const router = useRouter();

  const [framework, setFramework] = useState<FrameworkVersion | null>(null);
  const [layers, setLayers] = useState<Layer[]>([]);
  const [name, setName] = useState("");
  const [layer, setLayer] = useState("quick_score");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!me) return;
    api<FrameworkVersion>("/frameworks/current").then((data) => {
      setFramework(data);
      setSelected(new Set(data.axes.map((a) => a.id)));
    });
    api<Layer[]>("/catalogue/layers", { auth: false }).then(setLayers).catch(() => setLayers([]));
  }, [me]);

  useEffect(() => {
    if (!name && framework) {
      const year = new Date().getFullYear();
      setName(locale === "ar" ? `تقييم النضج ${year}` : `Maturity assessment ${year}`);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [framework]);

  function toggleAxis(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (!framework) return;
    setBusy(true);
    setError(null);
    try {
      const created = await api<Assessment>("/assessments", {
        method: "POST",
        body: {
          name,
          layer,
          framework_version_id: framework.id,
          // An empty list means "every pillar", so only send a real subset.
          selected_axis_ids: selected.size === framework.axes.length ? [] : Array.from(selected),
        },
      });
      router.push(`/assessments/${created.id}`);
    } catch (err) {
      if (err instanceof ApiError) setError(err);
      setBusy(false);
    }
  }

  if (loading || !me || !framework) return <Loading label={t("common.loading")} />;

  const questionCount = framework.axes
    .filter((a) => selected.has(a.id))
    .reduce((sum, a) => sum + a.questions.length, 0);

  return (
    <div className="shell" style={{ paddingBottom: "var(--space-8)", maxWidth: 940 }}>
      <div className="page-head">
        <div>
          <span className="eyebrow">{framework.framework_code} · v{framework.version}</span>
          <h1>{t("assessment.createTitle")}</h1>
        </div>
      </div>

      <form onSubmit={onSubmit} className="stack stack-5" style={{ marginBlockStart: "var(--space-5)" }}>
        <div className="card card-pad stack stack-4">
          <div className="field">
            <label htmlFor="name">{t("assessment.name")}</label>
            <input id="name" required value={name} onChange={(e) => setName(e.target.value)} />
          </div>

          <div className="field">
            <label htmlFor="layer">{t("assessment.layer")}</label>
            <select id="layer" value={layer} onChange={(e) => setLayer(e.target.value)}>
              {layers.map((item) => (
                <option key={item.key} value={item.key}>
                  {pick(item, "name")}
                </option>
              ))}
            </select>
            {layers.find((l) => l.key === layer) && (
              <span className="hint">{pick(layers.find((l) => l.key === layer)!, "summary")}</span>
            )}
          </div>
        </div>

        <div className="card card-pad stack stack-4">
          <div className="row row-tight">
            <h2 style={{ fontSize: "var(--text-lg)" }}>{t("assessment.selectAxes")}</h2>
            <span className="chip mono">
              {selected.size} / {framework.axes.length}
            </span>
            <div className="row row-tight push">
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={() => setSelected(new Set(framework.axes.map((a) => a.id)))}
              >
                {t("assessment.selectAll")}
              </button>
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={() => setSelected(new Set())}
              >
                {t("assessment.clearAll")}
              </button>
            </div>
          </div>
          <p className="dim" style={{ fontSize: "var(--text-sm)" }}>
            {t("assessment.selectAxesHint")}
          </p>

          <div className="grid grid-auto-md" style={{ gap: "var(--space-2)" }}>
            {framework.axes.map((axis) => {
              const on = selected.has(axis.id);
              return (
                <label key={axis.id} className="option-tile" data-on={on}>
                  <input type="checkbox" checked={on} onChange={() => toggleAxis(axis.id)} />
                  <span className="mono dim" style={{ fontSize: "var(--text-xs)" }}>
                    {axis.code}
                  </span>
                  <span style={{ fontSize: "var(--text-sm)" }}>{pick(axis, "name")}</span>
                  <span className="chip mono push">{axis.questions.length}</span>
                </label>
              );
            })}
          </div>
        </div>

        {error && <ErrorNote text={error.localised(locale)} />}

        <div className="row">
          <button type="submit" className="btn btn-primary" disabled={busy || selected.size === 0}>
            {busy ? t("common.loading") : t("assessment.create")}
          </button>
          <span className="dim mono" style={{ fontSize: "var(--text-sm)" }}>
            {num(questionCount, 0)} {t("assessment.questions")}
          </span>
        </div>
      </form>
    </div>
  );
}
