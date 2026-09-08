"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { Loading } from "@/components/AuthShell";
import { useLocale } from "@/i18n/LocaleProvider";
import type { MessageKey } from "@/i18n/messages";
import { api, type Assessment } from "@/lib/api";
import { useRequireSession } from "@/lib/session";

type Step = { key: string; label_ar: string; label_en: string };

const DONE_STATUSES = ["submitted", "under_review", "completed"];

export default function DashboardPage() {
  const { t, pick, num, locale } = useLocale();
  const { me, loading } = useRequireSession();
  const [assessments, setAssessments] = useState<Assessment[] | null>(null);
  const [steps, setSteps] = useState<Step[]>([]);

  useEffect(() => {
    if (!me) return;
    api<Assessment[]>("/assessments").then(setAssessments).catch(() => setAssessments([]));
    api<Step[]>("/organization/onboarding").then(setSteps).catch(() => setSteps([]));
  }, [me]);

  const stats = useMemo(() => {
    const list = assessments ?? [];
    const done = list.filter((a) => DONE_STATUSES.includes(a.status));
    const scores = done.map((a) => a.overall_score).filter((s): s is number => s !== null);
    return {
      total: list.length,
      active: list.length - done.length,
      done: done.length,
      best: scores.length ? Math.max(...scores) : null,
    };
  }, [assessments]);

  if (loading || !me) return <Loading label={t("common.loading")} />;

  const orgName = pick(
    { name_ar: me.organization_name_ar, name_en: me.organization_name_en },
    "name",
  );
  const profilePct = Math.round(me.profile_completeness * 100);

  return (
    <div className="shell" style={{ paddingBottom: "var(--space-8)" }}>
      <div className="page-head">
        <div>
          <span className="eyebrow">
            {t("dashboard.welcome")} · {me.user.full_name}
          </span>
          <h1>{orgName}</h1>
        </div>
        <Link href="/assessments/new" className="btn btn-primary">
          <PlusIcon />
          {t("dashboard.newAssessment")}
        </Link>
      </div>

      <section className="grid grid-auto-sm" style={{ marginBlockStart: "var(--space-5)" }}>
        <Stat label={t("dashboard.total")} value={num(stats.total, 0)} />
        <Stat label={t("dashboard.active")} value={num(stats.active, 0)} />
        <Stat label={t("dashboard.done")} value={num(stats.done, 0)} />
        <Stat
          label={t("dashboard.bestScore")}
          value={stats.best === null ? "—" : num(stats.best)}
          hero={stats.best !== null}
        />
      </section>

      <div className="split" style={{ marginBlockStart: "var(--space-6)" }}>
        <section>
          <div className="section-head" style={{ marginBlockEnd: "var(--space-4)" }}>
            <h2>{t("nav.assessments")}</h2>
          </div>

          {assessments === null && (
            <div className="card card-pad dim">{t("common.loading")}</div>
          )}

          {assessments?.length === 0 && (
            <div className="card card-pad stack stack-3">
              <EmptyIcon />
              <p style={{ fontWeight: 500 }}>{t("dashboard.noAssessments")}</p>
              <p className="muted" style={{ fontSize: "var(--text-sm)" }}>
                {t("dashboard.noAssessmentsBody")}
              </p>
              <Link
                href="/assessments/new"
                className="btn btn-secondary btn-sm"
                style={{ alignSelf: "flex-start" }}
              >
                {t("dashboard.newAssessment")}
              </Link>
            </div>
          )}

          <div className="stack stack-3">
            {assessments?.map((assessment) => {
              const done = DONE_STATUSES.includes(assessment.status);
              const pct = Math.round(assessment.completion * 100);
              return (
                <article
                  key={assessment.id}
                  className="card card-tight card-interactive stack stack-3"
                >
                  <div className="row row-tight">
                    <h3 style={{ fontSize: "var(--text-base)" }}>{assessment.name}</h3>
                    <span className={`chip ${done ? "chip-ok" : "chip-brand"}`}>
                      <span className="dot" />
                      {t(`assessment.status.${assessment.status}` as MessageKey)}
                    </span>
                    {assessment.overall_score !== null && (
                      <span className="chip chip-accent mono">
                        {num(assessment.overall_score)} / 5
                      </span>
                    )}
                    <div className="row row-tight push">
                      <Link
                        href={`/assessments/${assessment.id}/evidence`}
                        className="btn btn-ghost btn-sm"
                      >
                        {t("nav.evidence")}
                      </Link>
                      <Link
                        href={
                          done
                            ? `/assessments/${assessment.id}/results`
                            : `/assessments/${assessment.id}`
                        }
                        className="btn btn-secondary btn-sm"
                      >
                        {done ? t("assessment.viewResults") : t("assessment.open")}
                      </Link>
                    </div>
                  </div>
                  <div className="row row-tight">
                    <div className="meter">
                      <span style={{ width: `${pct}%` }} />
                    </div>
                    <span className="mono dim" style={{ fontSize: "var(--text-xs)" }}>
                      {pct}%
                    </span>
                  </div>
                </article>
              );
            })}
          </div>
        </section>

        <aside className="stack stack-4">
          <div className="card card-tight stack stack-3">
            <span className="stat-label">{t("dashboard.profileCompleteness")}</span>
            <div className="row row-tight">
              <Ring value={profilePct} />
              <div className="meter">
                <span style={{ width: `${profilePct}%` }} />
              </div>
            </div>
          </div>

          <div className="card card-tight stack stack-3">
            <h3 style={{ fontSize: "var(--text-base)" }}>{t("dashboard.onboarding")}</h3>
            <ol className="steps">
              {steps.map((step, index) => (
                <li key={step.key}>
                  <span className="steps-num mono">{index + 1}</span>
                  <span>{locale === "ar" ? step.label_ar : step.label_en}</span>
                </li>
              ))}
            </ol>
          </div>
        </aside>
      </div>

      <style>{`
        .steps { margin:0; padding:0; list-style:none; display:flex; flex-direction:column; gap:var(--space-2); }
        .steps li {
          display:flex; align-items:center; gap:var(--space-3);
          font-size:var(--text-sm); color:var(--ink-2);
        }
        .steps-num {
          flex:none; width:20px; height:20px; border-radius:var(--radius-pill);
          background:var(--surface-3); color:var(--ink-3);
          display:grid; place-items:center; font-size:0.66rem;
        }
      `}</style>
    </div>
  );
}

function Stat({ label, value, hero }: { label: string; value: string; hero?: boolean }) {
  return (
    <div className={`stat ${hero ? "stat-hero" : ""}`}>
      <div className="stat-value">{value}</div>
      <div className="stat-label">{label}</div>
    </div>
  );
}

/** Small completion ring — reads faster than a percentage alone. */
function Ring({ value }: { value: number }) {
  const r = 15;
  const circumference = 2 * Math.PI * r;
  const offset = circumference * (1 - value / 100);
  return (
    <svg width="38" height="38" viewBox="0 0 38 38" style={{ flex: "none" }} aria-hidden="true">
      <circle cx="19" cy="19" r={r} fill="none" stroke="var(--surface-3)" strokeWidth="4" />
      <circle
        cx="19"
        cy="19"
        r={r}
        fill="none"
        stroke="var(--brand-500)"
        strokeWidth="4"
        strokeLinecap="round"
        strokeDasharray={circumference}
        strokeDashoffset={offset}
        transform="rotate(-90 19 19)"
      />
      <text
        x="19"
        y="19"
        textAnchor="middle"
        dominantBaseline="central"
        fontSize="10"
        fontFamily="var(--font-mono)"
        fill="var(--ink-2)"
      >
        {value}
      </text>
    </svg>
  );
}

function PlusIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" aria-hidden="true">
      <path d="M12 5v14M5 12h14" />
    </svg>
  );
}

function EmptyIcon() {
  return (
    <svg width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="var(--ink-4)" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M6 3.5h8.5L19 8v12.5H6z" />
      <path d="M14 3.5V8h5M9 13h6M9 16.5h4" />
    </svg>
  );
}
