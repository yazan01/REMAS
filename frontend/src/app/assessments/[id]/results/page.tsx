"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { ErrorNote, Loading } from "@/components/AuthShell";
import { RadarChart } from "@/components/RadarChart";
import { useLocale } from "@/i18n/LocaleProvider";
import {
  ApiError,
  api,
  type Assessment,
  type Axis,
  type FrameworkVersion,
  type Scoring,
} from "@/lib/api";
import { useRequireSession } from "@/lib/session";
import { maturityRamp } from "@/theme/palette";

export default function ResultsPage() {
  const { t, pick, num, locale } = useLocale();
  const { me, loading } = useRequireSession();
  const params = useParams<{ id: string }>();
  const isStaff =
    !!me && (me.user.role === "ivalue_admin" || me.user.role === "ivalue_reviewer");

  const [assessment, setAssessment] = useState<Assessment | null>(null);
  const [framework, setFramework] = useState<FrameworkVersion | null>(null);
  const [scoring, setScoring] = useState<Scoring | null>(null);
  const [error, setError] = useState<ApiError | null>(null);

  useEffect(() => {
    if (!me) return;
    (async () => {
      try {
        const detail = await api<Assessment>(`/assessments/${params.id}`);
        setAssessment(detail);
        const [version, result] = await Promise.all([
          api<FrameworkVersion>(
            `/frameworks/versions/${detail.framework_version_id}?with_questions=false`,
          ),
          api<Scoring>(`/assessments/${params.id}/results`),
        ]);
        setFramework(version);
        setScoring(result);
      } catch (err) {
        if (err instanceof ApiError) setError(err);
      }
    })();
  }, [me, params.id]);

  const axisById = useMemo(() => {
    const map = new Map<string, Axis>();
    framework?.axes.forEach((a) => map.set(a.id, a));
    return map;
  }, [framework]);

  const levelLabel = (level: number | null) => {
    if (level === null || !framework) return "—";
    const found = framework.maturity_levels.find((l) => l.score === level);
    return found ? pick(found, "label") : String(level);
  };

  if (loading || !me) return <Loading label={t("common.loading")} />;

  if (error) {
    return (
      <div className="shell shell-narrow stack stack-4" style={{ paddingBlock: "var(--space-8)" }}>
        <ErrorNote text={error.localised(locale)} />
        <Link href="/dashboard" className="btn btn-secondary" style={{ alignSelf: "flex-start" }}>
          {t("nav.dashboard")}
        </Link>
      </div>
    );
  }

  if (!scoring || !framework || !assessment) return <Loading label={t("common.loading")} />;

  const scored = scoring.axes.filter((a) => a.is_scored && a.score !== null);
  const radarData = scored.map((a) => ({
    label: axisById.get(a.axis_id)?.code ?? a.code,
    value: a.score ?? 0,
  }));

  return (
    <div className="shell" style={{ paddingBottom: "var(--space-8)" }}>
      <div className="page-head">
        <div>
          <span className="eyebrow">{assessment.name}</span>
          <h1>{t("results.title")}</h1>
        </div>
        <div className="row row-tight">
          {assessment.submitted_at && (
            <span className="chip mono">
              {t("results.assessmentDate")} {assessment.submitted_at.slice(0, 10)}
            </span>
          )}
          <Link href={`/assessments/${params.id}/insights`} className="btn btn-primary btn-sm">
            {t("ai.title")}
          </Link>
          {isStaff && (
            <Link href={`/assessments/${params.id}/review`} className="btn btn-secondary btn-sm">
              {t("review.title")}
            </Link>
          )}
        </div>
      </div>

      {/* headline numbers */}
      <section className="grid grid-auto-sm" style={{ marginBlockStart: "var(--space-5)" }}>
        <div className="stat stat-hero">
          <div className="stat-value">
            {scoring.overall_score === null ? "—" : num(scoring.overall_score)}
            {scoring.overall_score !== null && (
              <span className="dim" style={{ fontSize: "var(--text-lg)", fontWeight: 400 }}>
                {" "}
                / 5
              </span>
            )}
          </div>
          <div className="stat-label">{t("results.overall")}</div>
        </div>
        <Stat label={t("results.level")} value={levelLabel(scoring.maturity_level)} />
        <Stat
          label={t("results.completeness")}
          value={`${Math.round(scoring.completeness * 100)}%`}
        />
        <Stat
          label={t("results.evidence")}
          value={`${Math.round(scoring.evidence_completeness * 100)}%`}
        />
      </section>

      <div className="split" style={{ marginBlockStart: "var(--space-6)" }}>
        <section className="stack stack-5">
          {/* per-axis bars */}
          <div>
            <div className="section-head" style={{ marginBlockEnd: "var(--space-3)" }}>
              <h2>{t("results.byAxis")}</h2>
            </div>
            <div className="card">
              {scoring.axes.map((row) => {
                const axis = axisById.get(row.axis_id);
                const pct = row.score !== null ? ((row.score - 1) / 4) * 100 : 0;
                const band = row.maturity_level
                  ? maturityRamp[row.maturity_level - 1]
                  : "var(--line-2)";
                const name = axis ? pick(axis, "name") : row.code;
                return (
                  <div className="axis-row" key={row.axis_id}>
                    <span className="mono dim" style={{ fontSize: "var(--text-xs)" }}>
                      {row.code}
                    </span>
                    <span className="axis-name" title={name}>
                      {name}
                    </span>
                    <span
                      className="axis-track"
                      title={`${t("results.coverage")} ${Math.round(row.coverage * 100)}%`}
                    >
                      <span style={{ width: `${pct}%`, background: band }} />
                    </span>
                    <span
                      className="axis-score"
                      style={{ color: row.is_scored ? undefined : "var(--ink-4)" }}
                      title={row.is_scored ? undefined : t("results.notScoredHint")}
                    >
                      {row.is_scored && row.score !== null ? num(row.score) : "—"}
                    </span>
                  </div>
                );
              })}
            </div>
            <p className="dim" style={{ fontSize: "var(--text-xs)", marginBlockStart: "var(--space-3)" }}>
              {t("results.formulaNote")}
            </p>
          </div>

          {/* heat map */}
          {scored.length > 0 && (
            <div>
              <div className="section-head" style={{ marginBlockEnd: "var(--space-3)" }}>
                <h2>{t("results.heatmap")}</h2>
              </div>
              <div className="heat">
                {scoring.axes.map((row) => {
                  const level = row.maturity_level ?? 0;
                  const bg = level ? maturityRamp[level - 1] : "var(--surface-2)";
                  const light = level <= 2;
                  const axis = axisById.get(row.axis_id);
                  return (
                    <div
                      key={row.axis_id}
                      className="heat-cell"
                      style={{
                        background: bg,
                        color: light ? "var(--ink)" : "var(--on-brand)",
                        borderColor: "transparent",
                      }}
                      title={axis ? pick(axis, "name") : row.code}
                    >
                      <span className="code">{row.code}</span>
                      <span className="val">
                        {row.is_scored && row.score !== null ? num(row.score) : "—"}
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </section>

        {/* radar + strengths/gaps */}
        <aside className="stack stack-4">
          <div className="card card-tight stack stack-3">
            <span className="eyebrow">{t("results.radar")}</span>
            <RadarChart data={radarData} max={5} />
          </div>

          <div className="card card-tight stack stack-3">
            <h3 style={{ fontSize: "var(--text-base)" }}>{t("results.strengths")}</h3>
            <ChipList ids={scoring.strengths} axisById={axisById} pick={pick} tone="chip-ok" />
            <hr className="divider" />
            <h3 style={{ fontSize: "var(--text-base)" }}>{t("results.gaps")}</h3>
            <ChipList ids={scoring.gaps} axisById={axisById} pick={pick} tone="chip-danger" />
          </div>
        </aside>
      </div>

      {/* priorities */}
      {scoring.priorities.length > 0 && (
        <section className="section">
          <div className="section-head">
            <h2>{t("results.priorities")}</h2>
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th style={{ width: 64 }}>{t("results.priorityRank")}</th>
                  <th>{t("results.axis")}</th>
                  <th style={{ width: 90 }}>{t("results.score")}</th>
                  <th style={{ width: 120 }}>{t("results.evidence")}</th>
                </tr>
              </thead>
              <tbody>
                {scoring.priorities.slice(0, 10).map((row) => {
                  const axis = axisById.get(row.axis_id);
                  return (
                    <tr key={row.axis_id}>
                      <td>
                        <span className={`chip mono ${row.rank <= 3 ? "chip-accent" : ""}`}>
                          {row.rank}
                        </span>
                      </td>
                      <td>
                        <span className="mono dim" style={{ fontSize: "var(--text-xs)" }}>
                          {row.code}
                        </span>{" "}
                        {axis ? pick(axis, "name") : row.code}
                      </td>
                      <td className="mono">{num(row.score)}</td>
                      <td className="mono">{Math.round((1 - row.evidence_gap) * 100)}%</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>
      )}

      <div style={{ marginBlockStart: "var(--space-6)" }}>
        <Link href="/dashboard" className="btn btn-secondary">
          {t("nav.dashboard")}
        </Link>
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="stat">
      <div className="stat-value">{value}</div>
      <div className="stat-label">{label}</div>
    </div>
  );
}

function ChipList({
  ids,
  axisById,
  pick,
  tone,
}: {
  ids: string[];
  axisById: Map<string, Axis>;
  pick: (row: Record<string, unknown> | null | undefined, field: string) => string;
  tone: string;
}) {
  if (ids.length === 0)
    return (
      <span className="dim" style={{ fontSize: "var(--text-sm)" }}>
        —
      </span>
    );
  return (
    <div className="row row-tight">
      {ids.map((id) => {
        const axis = axisById.get(id);
        return (
          <span key={id} className={`chip ${tone}`}>
            {axis ? pick(axis, "name") : id}
          </span>
        );
      })}
    </div>
  );
}
