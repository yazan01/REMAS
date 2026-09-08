"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";

import { ErrorNote, Loading } from "@/components/AuthShell";
import { useLocale } from "@/i18n/LocaleProvider";
import type { MessageKey } from "@/i18n/messages";
import {
  ApiError,
  api,
  downloadFile,
  type AIFinding,
  type AIJobRow,
  type Assessment,
  type Axis,
  type FrameworkVersion,
  type LayerFeatures,
  type Roadmap,
} from "@/lib/api";
import { useRequireSession } from "@/lib/session";

const IVALUE_ROLES = new Set(["ivalue_admin", "ivalue_reviewer"]);

export default function InsightsPage() {
  const { t, pick, locale, num } = useLocale();
  const { me, loading } = useRequireSession();
  const params = useParams<{ id: string }>();
  const assessmentId = params.id;
  const isStaff = !!me && IVALUE_ROLES.has(me.user.role);

  const [assessment, setAssessment] = useState<Assessment | null>(null);
  const [axes, setAxes] = useState<Map<string, Axis>>(new Map());
  const [features, setFeatures] = useState<LayerFeatures | null>(null);
  const [findings, setFindings] = useState<AIFinding[]>([]);
  const [jobs, setJobs] = useState<AIJobRow[]>([]);
  const [roadmap, setRoadmap] = useState<Roadmap | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [running, setRunning] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [reportLocale, setReportLocale] = useState<"ar" | "en">("ar");

  const refresh = useCallback(async () => {
    const [findingRows, jobRows] = await Promise.all([
      api<AIFinding[]>(`/assessments/${assessmentId}/ai/findings`),
      api<AIJobRow[]>(`/assessments/${assessmentId}/ai/jobs`),
    ]);
    setFindings(findingRows);
    setJobs(jobRows);
    try {
      setRoadmap(await api<Roadmap>(`/assessments/${assessmentId}/roadmap`));
    } catch {
      setRoadmap(null); // the layer may not include the roadmap
    }
  }, [assessmentId]);

  useEffect(() => {
    if (!me) return;
    (async () => {
      try {
        const detail = await api<Assessment>(`/assessments/${assessmentId}`);
        setAssessment(detail);
        setReportLocale(locale);
        const [version, layer] = await Promise.all([
          api<FrameworkVersion>(`/frameworks/versions/${detail.framework_version_id}?with_questions=false`),
          api<LayerFeatures>(`/assessments/${assessmentId}/layer-features`),
        ]);
        setAxes(new Map(version.axes.map((a) => [a.id, a])));
        setFeatures(layer);
        await refresh();
      } catch (err) {
        if (err instanceof ApiError) setError(err);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [me, assessmentId, refresh]);

  async function runPipeline(stages: string[], setBusy: (v: boolean) => void) {
    setBusy(true);
    setError(null);
    try {
      await api(`/assessments/${assessmentId}/ai/run`, { method: "POST", body: { stages } });
      await refresh();
    } catch (err) {
      if (err instanceof ApiError) setError(err);
    } finally {
      setBusy(false);
    }
  }

  async function reviewFinding(id: string, review_status: string) {
    try {
      await api(`/ai/findings/${id}`, { method: "PATCH", body: { review_status } });
      await refresh();
    } catch (err) {
      if (err instanceof ApiError) setError(err);
    }
  }

  async function toggleInitiative(id: string, is_included: boolean) {
    try {
      await api(`/initiatives/${id}`, { method: "PATCH", body: { is_included } });
      await refresh();
    } catch (err) {
      if (err instanceof ApiError) setError(err);
    }
  }

  const narrative = useMemo(
    () => findings.find((f) => f.kind === "narrative" && f.review_status !== "rejected"),
    [findings],
  );
  const byAxis = useMemo(() => {
    const map = new Map<string, AIFinding[]>();
    for (const finding of findings) {
      if (!finding.axis_id) continue;
      if (!["strength", "gap", "opportunity"].includes(finding.kind)) continue;
      const list = map.get(finding.axis_id) ?? [];
      list.push(finding);
      map.set(finding.axis_id, list);
    }
    return map;
  }, [findings]);
  const coverage = useMemo(
    () => findings.filter((f) => f.kind === "evidence_coverage"),
    [findings],
  );

  if (loading || !me || !assessment) return <Loading label={t("common.loading")} />;

  const lastJob = jobs[0];
  const canReport = features?.features.includes("pdf_report") || isStaff;
  const canAnalyse = features?.features.includes("ai_analysis") || isStaff;

  return (
    <div className="shell" style={{ paddingBottom: "var(--space-8)" }}>
      <div className="page-head">
        <div>
          <span className="eyebrow">{assessment.name}</span>
          <h1>{t("ai.title")}</h1>
        </div>
        <div className="row row-tight">
          <Link href={`/assessments/${assessmentId}/results`} className="btn btn-secondary btn-sm">
            {t("results.title")}
          </Link>
          {canAnalyse && (
            <button
              type="button"
              className="btn btn-primary btn-sm"
              disabled={running}
              onClick={() => void runPipeline(["extract", "relevance", "analyse"], setRunning)}
            >
              {running ? t("ai.running") : t("ai.run")}
            </button>
          )}
        </div>
      </div>

      {error && (
        <div style={{ marginBlockStart: "var(--space-4)" }}>
          <ErrorNote text={error.localised(locale)} />
        </div>
      )}

      <div className="note note-info" style={{ marginBlockStart: "var(--space-4)" }}>
        {t("ai.disclaimer")}
        {lastJob && (
          <>
            {" · "}
            <span className="mono">
              {t("ai.provider")}: {lastJob.provider}
              {lastJob.model ? ` (${lastJob.model})` : ""}
            </span>
          </>
        )}
      </div>

      {findings.length === 0 ? (
        <div className="card card-pad dim" style={{ marginBlockStart: "var(--space-5)" }}>
          {t("ai.noRuns")}
        </div>
      ) : (
        <>
          {narrative && (
            <section style={{ marginBlockStart: "var(--space-6)" }}>
              <div className="section-head">
                <h2>{t("ai.narrative")}</h2>
                <ReviewBadge finding={narrative} />
              </div>
              <div className="card card-pad">
                <p style={{ fontSize: "var(--text-base)" }}>{pick(narrative, "body")}</p>
                {isStaff && (
                  <div className="row row-tight" style={{ marginBlockStart: "var(--space-4)" }}>
                    <button
                      type="button"
                      className="btn btn-secondary btn-sm"
                      onClick={() => void reviewFinding(narrative.id, "accepted")}
                    >
                      {t("ai.accept")}
                    </button>
                    <button
                      type="button"
                      className="btn btn-ghost btn-sm"
                      onClick={() => void reviewFinding(narrative.id, "rejected")}
                    >
                      {t("ai.reject")}
                    </button>
                  </div>
                )}
              </div>
            </section>
          )}

          {byAxis.size > 0 && (
            <section style={{ marginBlockStart: "var(--space-6)" }}>
              <div className="section-head">
                <h2>{t("results.byAxis")}</h2>
              </div>
              <div className="stack stack-3">
                {Array.from(byAxis.entries()).map(([axisId, items]) => {
                  const axis = axes.get(axisId);
                  const of = (kind: string) => items.find((i) => i.kind === kind);
                  return (
                    <article key={axisId} className="card card-tight stack stack-3">
                      <div className="row row-tight">
                        <span className="mono" style={{ fontSize: "var(--text-xs)", color: "var(--brand-500)" }}>
                          {axis?.code}
                        </span>
                        <h3 style={{ fontSize: "var(--text-base)" }}>
                          {axis ? pick(axis, "name") : axisId}
                        </h3>
                      </div>
                      <dl className="finding-grid">
                        <dt>{t("ai.strengths")}</dt>
                        <dd>{pick(of("strength"), "body") || "—"}</dd>
                        <dt>{t("ai.gaps")}</dt>
                        <dd>{pick(of("gap"), "body") || "—"}</dd>
                        <dt>{t("ai.opportunities")}</dt>
                        <dd>{pick(of("opportunity"), "body") || "—"}</dd>
                      </dl>
                    </article>
                  );
                })}
              </div>
            </section>
          )}

          {coverage.length > 0 && (
            <section style={{ marginBlockStart: "var(--space-6)" }}>
              <div className="section-head">
                <h2>{t("ai.evidenceCoverage")}</h2>
                <span className="chip mono">{coverage.length}</span>
              </div>
              <div className="stack stack-2">
                {coverage.map((finding) => {
                  const citation = (finding.citation ?? {}) as Record<string, unknown>;
                  const verdict = String(citation.verdict ?? "");
                  const tone =
                    verdict === "covered" ? "chip-ok" : verdict === "partial" ? "chip-warn" : "chip-danger";
                  return (
                    <article key={finding.id} className="card card-tight stack stack-2">
                      <div className="row row-tight">
                        <span className="mono dim" style={{ fontSize: "var(--text-xs)" }}>
                          {String(citation.filename ?? "")}
                        </span>
                        <span className={`chip ${tone}`}>{verdict}</span>
                        {citation.ocr_required ? (
                          <span className="chip chip-warn">{t("ai.needsOcr")}</span>
                        ) : null}
                        {typeof finding.confidence === "number" && (
                          <span className="chip mono push">
                            {t("ai.confidence")} {Math.round(finding.confidence * 100)}%
                          </span>
                        )}
                      </div>
                      <p className="muted" style={{ fontSize: "var(--text-sm)" }}>
                        {pick(finding, "body")}
                      </p>
                      {typeof citation.excerpt === "string" && citation.excerpt && (
                        <blockquote className="citation">
                          <span className="mono dim" style={{ fontSize: "var(--text-xs)" }}>
                            {t("ai.citation")}
                            {citation.page ? ` · ${t("ai.page")} ${citation.page}` : ""}
                          </span>
                          <span>{citation.excerpt}</span>
                        </blockquote>
                      )}
                    </article>
                  );
                })}
              </div>
            </section>
          )}
        </>
      )}

      {/* roadmap */}
      <section style={{ marginBlockStart: "var(--space-7)" }}>
        <div className="section-head">
          <div>
            <h2>{t("roadmap.title")}</h2>
          </div>
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            disabled={generating}
            onClick={() => void runPipeline(["recommend"], setGenerating)}
          >
            {generating ? t("report.generating") : t("roadmap.generate")}
          </button>
        </div>

        {!roadmap || roadmap.total === 0 ? (
          <div className="card card-pad dim">{t("roadmap.empty")}</div>
        ) : (
          <div className="lanes">
            {roadmap.horizons.map((horizon) => (
              <div key={horizon.code} className="lane">
                <div className="lane-head">
                  <strong style={{ fontSize: "var(--text-sm)" }}>{pick(horizon, "name")}</strong>
                  <span className="mono dim" style={{ fontSize: "var(--text-xs)" }}>
                    {horizon.months_from}–{horizon.months_to} {t("roadmap.months")}
                  </span>
                </div>
                <div className="lane-body">
                  {horizon.initiatives.length === 0 && <span className="dim">—</span>}
                  {horizon.initiatives.map((initiative) => (
                    <div
                      key={initiative.id}
                      className="init-card"
                      style={{ opacity: initiative.is_included ? 1 : 0.5 }}
                    >
                      <div className="row row-tight">
                        <span className="chip mono chip-brand">P{initiative.priority}</span>
                        <span className="chip">
                          {t(
                            `roadmap.source${
                              initiative.source === "reviewer"
                                ? "Reviewer"
                                : initiative.source === "ai"
                                  ? "Ai"
                                  : "Engine"
                            }` as MessageKey,
                          )}
                        </span>
                      </div>
                      <strong style={{ fontSize: "var(--text-sm)" }}>
                        {pick(initiative, "title")}
                      </strong>
                      {pick(initiative, "objective") && (
                        <span className="muted" style={{ fontSize: "var(--text-xs)" }}>
                          {pick(initiative, "objective")}
                        </span>
                      )}
                      {initiative.linked_gap && (
                        <span className="mono dim" style={{ fontSize: "var(--text-xs)" }}>
                          {t("roadmap.linkedGap")}: {initiative.linked_gap}
                        </span>
                      )}
                      {isStaff && (
                        <label className="check" style={{ fontSize: "var(--text-xs)" }}>
                          <input
                            type="checkbox"
                            checked={initiative.is_included}
                            onChange={(e) =>
                              void toggleInitiative(initiative.id, e.target.checked)
                            }
                          />
                          {t("roadmap.include")}
                        </label>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* report */}
      {canReport && (
        <section style={{ marginBlockStart: "var(--space-7)" }}>
          <div className="section-head">
            <h2>{t("report.title")}</h2>
          </div>
          <div className="card card-pad row">
            <div className="field" style={{ maxWidth: 180 }}>
              <label htmlFor="report-locale">{t("report.locale")}</label>
              <select
                id="report-locale"
                value={reportLocale}
                onChange={(e) => setReportLocale(e.target.value as "ar" | "en")}
              >
                <option value="ar">العربية</option>
                <option value="en">English</option>
              </select>
            </div>
            <div className="row row-tight push">
              <button
                type="button"
                className="btn btn-primary"
                onClick={() =>
                  void downloadFile(
                    `/assessments/${assessmentId}/report.pdf?locale=${reportLocale}`,
                    `REMAS-${assessment.name}-${reportLocale}.pdf`,
                  ).catch((err) => err instanceof ApiError && setError(err))
                }
              >
                {t("report.downloadPdf")}
              </button>
              <button
                type="button"
                className="btn btn-secondary"
                onClick={() =>
                  void downloadFile(
                    `/assessments/${assessmentId}/report.json?locale=${reportLocale}`,
                    `remas-${assessmentId}-${reportLocale}.json`,
                  ).catch((err) => err instanceof ApiError && setError(err))
                }
              >
                {t("report.exportJson")}
              </button>
              {isStaff && (
                <button
                  type="button"
                  className="btn btn-secondary"
                  onClick={async () => {
                    try {
                      await api(`/assessments/${assessmentId}/report/release`, {
                        method: "POST",
                        body: { locale: reportLocale },
                      });
                      setAssessment(
                        await api<Assessment>(`/assessments/${assessmentId}`),
                      );
                    } catch (err) {
                      if (err instanceof ApiError) setError(err);
                    }
                  }}
                >
                  {t("report.release")}
                </button>
              )}
            </div>
          </div>
        </section>
      )}

      <style>{`
        .finding-grid {
          margin:0; display:grid; grid-template-columns:120px minmax(0,1fr);
          gap:var(--space-2) var(--space-4); font-size:var(--text-sm);
        }
        .finding-grid dt { color:var(--ink-3); font-size:var(--text-xs); }
        .finding-grid dd { margin:0; color:var(--ink-2); }
        .citation {
          margin:0; padding:var(--space-3); border-inline-start:3px solid var(--brand-300);
          background:var(--surface-2); border-radius:var(--radius-sm);
          display:flex; flex-direction:column; gap:4px; font-size:var(--text-sm);
        }
        .lanes { display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); gap:var(--space-3); }
        .lane { border:1px solid var(--line); border-radius:var(--radius); background:var(--surface); overflow:hidden; }
        .lane-head {
          padding:var(--space-3); background:var(--surface-2);
          border-block-end:1px solid var(--line);
          display:flex; align-items:center; justify-content:space-between; gap:var(--space-2);
        }
        .lane-body { padding:var(--space-3); display:flex; flex-direction:column; gap:var(--space-3); }
        .init-card {
          display:flex; flex-direction:column; gap:6px;
          padding:var(--space-3); border:1px solid var(--line);
          border-radius:var(--radius-sm); background:var(--surface-2);
        }
        @media (max-width:640px) { .finding-grid { grid-template-columns:1fr; } }
      `}</style>
    </div>
  );
}

function ReviewBadge({ finding }: { finding: AIFinding }) {
  const { t } = useLocale();
  const map: Record<string, string> = {
    draft: "chip",
    accepted: "chip chip-ok",
    rejected: "chip chip-danger",
    edited: "chip chip-warn",
  };
  return (
    <span className={map[finding.review_status] ?? "chip"}>
      {t(`ai.${finding.review_status}` as MessageKey)}
    </span>
  );
}
